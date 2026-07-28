import json
from datetime import datetime
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

from .sources import discover_sources
from .sources.base import CivicSource

BRIEFING_FILE = "townhall_briefing.md"


class TownHallCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    sources: list = []

    #{{register capability}}

    def _resolve_api_key(self, key_name: str) -> str | None:
        try:
            key = self.capability_worker.get_api_keys(key_name)
        except Exception as e:
            self.worker.editor_logging_handler.warning(
                f"{key_name} lookup raised an error: {e}"
            )
            return None
        if key and str(key).strip():
            self.worker.editor_logging_handler.info(f"{key_name} resolved successfully")
            return str(key).strip()
        self.worker.editor_logging_handler.warning(
            f"{key_name} not found. Add a third-party key named '{key_name}' in Settings."
        )
        return None

    def _bind_sources(self):
        """attach worker and inject any required api keys for each source."""
        for source in self.sources:
            source.bind_worker(self.worker)
            key_name = source.required_api_key_name()
            if key_name:
                source.set_api_key(self._resolve_api_key(key_name))

    def _filter_sources(self, phrase: str) -> list[CivicSource]:
        """return sources whose trigger_keywords match the phrase.
        falls back to all sources if nothing matches or source declares no keywords."""
        phrase_lower = phrase.lower()
        matched = [
            s for s in self.sources
            if s.trigger_keywords() and any(kw in phrase_lower for kw in s.trigger_keywords())
        ]
        return matched if matched else self.sources

    async def log_gap(self, query: str, reason: str):
        gap_data = {
            "query": query,
            "reason": reason,
            "timestamp": str(datetime.now()),
        }
        await self.capability_worker.write_file(
            "knowledge_gaps.json",
            json.dumps(gap_data) + "\n",
            in_ability_directory=True,
        )

    async def write_context_file(self, filename: str, content: str):
        exists = await self.capability_worker.check_if_file_exists(
            filename, in_ability_directory=False
        )
        if exists:
            await self.capability_worker.delete_file(filename, in_ability_directory=False)
        await self.capability_worker.write_file(
            filename, content, in_ability_directory=False
        )

    async def read_cached_briefing(self, active_sources: list[CivicSource]) -> str | None:
        """return a usable cached briefing if present and all active sources validate it."""
        exists = await self.capability_worker.check_if_file_exists(
            BRIEFING_FILE, in_ability_directory=False
        )
        if not exists:
            return None
        try:
            content = await self.capability_worker.read_file(
                BRIEFING_FILE, in_ability_directory=False
            )
        except Exception:
            return None
        if not content:
            return None
        if not all(source.validate_cache(content) for source in active_sources):
            return None
        return content

    async def collect_briefing(
        self, active_sources: list[CivicSource], announce: bool = False
    ) -> str:
        """fetch active sources and refresh the ambient briefing file."""
        self._bind_sources()
        source_names = ", ".join(s.get_name() for s in active_sources)
        aggregated = [
            f"# TownHall Civic Briefing\n"
            f"Sources: {source_names}\n"
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        ]
        for source in active_sources:
            if announce:
                await self.capability_worker.speak(f"Checking {source.get_name()}.")
            self.worker.editor_logging_handler.info(f"Polling source: {source.get_name()}")
            updates = await source.fetch_updates()
            self.worker.editor_logging_handler.info(
                f"Source {source.get_name()} returned {len(updates)} chars"
            )
            aggregated.append(updates)
        final_context = "\n\n---\n\n".join(aggregated)
        await self.write_context_file(BRIEFING_FILE, final_context)
        self.worker.editor_logging_handler.info(
            f"Briefing ready ({len(final_context)} chars): {final_context[:400]}"
        )
        return final_context

    async def collect_briefing_with_keepalive(
        self, active_sources: list[CivicSource]
    ) -> str:
        """fetch while speaking short keepalives so sleep mode does not trip."""
        stop = {"done": False}

        async def _keepalive():
            while not stop["done"]:
                await self.worker.session_tasks.sleep(10.0)
                if not stop["done"]:
                    await self.capability_worker.speak("Still pulling updates.")

        self.worker.session_tasks.create(_keepalive())
        try:
            return await self.collect_briefing(active_sources, announce=True)
        finally:
            stop["done"] = True

    async def watchdog_loop(self):
        """warm cache quickly, then refresh hourly."""
        await self.worker.session_tasks.sleep(3.0)
        while True:
            try:
                await self.collect_briefing(self.sources, announce=False)
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"TownHall watchdog error: {e}"
                )
            await self.worker.session_tasks.sleep(3600.0)

    async def run(self):
        # get the trigger phrase that activated this ability if the worker exposes it
        trigger_phrase = (
            getattr(self.worker, "trigger_phrase", "")
            or getattr(self.worker, "matched_phrase", "")
            or ""
        )

        await self.capability_worker.speak(
            "Town Hall is standing by. Would you like your morning briefing?"
        )
        user_input = await self.capability_worker.user_response()

        if "briefing" in user_input.lower() or "yes" in user_input.lower():
            # route to relevant sources using trigger phrase, then user input as fallback
            routing_phrase = trigger_phrase or user_input
            active_sources = self._filter_sources(routing_phrase)
            source_names = ", ".join(s.get_name() for s in active_sources)
            self.worker.editor_logging_handler.info(
                f"Routing to sources: {source_names} (phrase: '{routing_phrase}')"
            )

            await self.capability_worker.speak("One sec. Pulling the latest civic updates.")
            try:
                briefing = await self.read_cached_briefing(active_sources)
                if briefing:
                    self.worker.editor_logging_handler.info("Using cached briefing")
                else:
                    briefing = await self.collect_briefing_with_keepalive(active_sources)
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"TownHall briefing fetch error: {e}"
                )
                await self.capability_worker.speak(
                    "I couldn't reach the civic sources right now. Try again in a minute."
                )
                self.capability_worker.resume_normal_flow()
                return

            summary = self.capability_worker.text_to_text_response(
                "You are giving a short spoken morning civic briefing. "
                f"Using ONLY the briefing text below, summarize the most important "
                f"updates from {source_names} in 4 to 6 short sentences. "
                "Do not mention documents, databases, or missing context. "
                "If a section contains an error message, quote the key error briefly "
                "so we can debug, then cover whatever else is available. "
                "Speak plainly for a smart speaker.\n\n"
                f"BRIEFING TEXT:\n{briefing}"
            )
            await self.capability_worker.speak(summary)

            lower = briefing.lower()
            if (
                "error fetching" in lower
                or "fetch issues" in lower
                or "http worker not bound" in lower
            ):
                snippet = briefing.replace("\n", " ")
                if len(snippet) > 350:
                    snippet = snippet[:350]
                await self.capability_worker.speak(f"Debug details: {snippet}")

            await self.capability_worker.speak(
                "Would you like me to draft a message to any of these offices?"
            )
        else:
            response = self.capability_worker.text_to_text_response(user_input)
            await self.capability_worker.speak(response)
            if "don't know" in response.lower():
                await self.log_gap(user_input, "Information not in modular sources.")

        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.sources = discover_sources()
        self._bind_sources()
        self.worker.session_tasks.create(self.watchdog_loop())
        self.worker.session_tasks.create(self.run())
