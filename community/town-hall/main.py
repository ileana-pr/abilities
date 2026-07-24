import json
from datetime import datetime
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

from .sources import discover_sources
from .sources.virginia_state import VirginiaStateSource

LIS_API_KEY_ALIASES = (
    "lis_api_key",
    "LIS_API_KEY",
    "lis-api-key",
    "virginia_lis_api_key",
)
BRIEFING_FILE = "townhall_briefing.md"


class TownHallCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    SOURCES = discover_sources()

    #{{register capability}}

    def _resolve_lis_key(self) -> str | None:
        for name in LIS_API_KEY_ALIASES:
            try:
                key = self.capability_worker.get_api_keys(name)
            except Exception:
                key = None
            if key and str(key).strip():
                self.worker.editor_logging_handler.info(
                    f"LIS key resolved via get_api_keys('{name}')"
                )
                return str(key).strip()
        self.worker.editor_logging_handler.warning(
            "LIS key not found. Settings third-party key must be named lis_api_key"
        )
        return None

    def _bind_sources(self):
        """attach worker for session_tasks http + inject lis api key."""
        key = self._resolve_lis_key()
        for source in self.SOURCES:
            source.bind_worker(self.worker)
            if isinstance(source, VirginiaStateSource):
                source.set_api_key(key)

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

    async def read_cached_briefing(self) -> str | None:
        """return a usable cached briefing if present."""
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
        # reject empty/error-only caches
        if "Error fetching" in content and "HB" not in content and "Meeting ID" not in content:
            return None
        return content

    async def collect_briefing(self, announce: bool = False) -> str:
        """fetch all sources now and refresh the ambient briefing file."""
        self._bind_sources()
        aggregated = [
            "# TownHall Civic Briefing\n"
            f"Build: resp-fix-v5\n"
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        ]
        for source in self.SOURCES:
            if announce:
                await self.capability_worker.speak(
                    f"Checking {source.get_name()}."
                )
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

    async def collect_briefing_with_keepalive(self) -> str:
        """fetch while speaking short keepalives so sleep mode does not trip."""
        stop = {"done": False}

        async def _keepalive():
            while not stop["done"]:
                await self.worker.session_tasks.sleep(10.0)
                if not stop["done"]:
                    await self.capability_worker.speak("Still pulling updates.")

        self.worker.session_tasks.create(_keepalive())
        try:
            return await self.collect_briefing(announce=True)
        finally:
            stop["done"] = True

    async def watchdog_loop(self):
        """warm cache quickly, then refresh hourly."""
        await self.worker.session_tasks.sleep(3.0)
        while True:
            try:
                await self.collect_briefing(announce=False)
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"TownHall Coordinator Error: {e}"
                )
            await self.worker.session_tasks.sleep(3600.0)

    async def run(self):
        await self.capability_worker.speak(
            "Town Hall is standing by. Would you like your morning briefing?"
        )
        user_input = await self.capability_worker.user_response()

        if "briefing" in user_input.lower() or "yes" in user_input.lower():
            await self.capability_worker.speak("One sec. Pulling the latest civic updates.")
            try:
                briefing = await self.read_cached_briefing()
                if briefing:
                    self.worker.editor_logging_handler.info("Using cached briefing")
                else:
                    briefing = await self.collect_briefing_with_keepalive()
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
                "Using ONLY the briefing text below, summarize the most important "
                "upcoming Richmond meetings and Virginia bills in 4 to 6 short sentences. "
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
        self._bind_sources()
        self.worker.session_tasks.create(self.watchdog_loop())
        self.worker.session_tasks.create(self.run())
