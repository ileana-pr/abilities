import json
import re
from datetime import datetime
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

from .sources import discover_sources
from .sources.base import CivicSource

BRIEFING_FILE = "townhall_briefing.md"
TOPICS_FILE = "topic_preferences.json"


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

    async def _load_topic_preferences(self) -> dict:
        """load user's topic preferences from file."""
        exists = await self.capability_worker.check_if_file_exists(
            TOPICS_FILE, in_ability_directory=True
        )
        if not exists:
            return {}
        
        content = await self.capability_worker.read_file(
            TOPICS_FILE, in_ability_directory=True
        )
        return json.loads(content) if content else {}

    async def _save_topic_preferences(self, preferences: dict) -> None:
        """save topic preferences to file."""
        await self.capability_worker.write_file(
            TOPICS_FILE,
            json.dumps(preferences, indent=2),
            in_ability_directory=True
        )

    async def _bind_sources(self):
        """inject api keys, worker, and topic preferences for each source."""
        # load topic preferences
        topic_prefs = await self._load_topic_preferences()
        
        for source in self.sources:
            # bind worker for http requests
            source.bind_worker(self.worker)
            
            # inject api key if needed
            key_name = source.required_api_key_name()
            if key_name:
                source.set_api_key(self._resolve_api_key(key_name))
            
            # inject topic preferences if source supports it
            if hasattr(source, 'set_topic_preferences'):
                source_topics = topic_prefs.get(source.get_name(), [])
                if source_topics:
                    source.set_topic_preferences(source_topics)

    def _match_sources(self, phrase: str) -> list[CivicSource]:
        """sources whose keywords appear in the phrase, plus any that declare none.
        returns an empty list when the phrase names no jurisdiction."""
        phrase_lower = phrase.lower()
        matched = [
            s for s in self.sources
            if s.trigger_keywords() and any(kw in phrase_lower for kw in s.trigger_keywords())
        ]
        always_on = [s for s in self.sources if not s.trigger_keywords()]
        return matched + always_on

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
        await self._bind_sources()
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
        """warm cache quickly, then refresh daily."""
        await self.worker.session_tasks.sleep(3.0)
        while True:
            try:
                await self.collect_briefing(self.sources, announce=False)
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"TownHall watchdog error: {e}"
                )
            await self.worker.session_tasks.sleep(86400.0)

    async def _capture_trigger_phrase(self) -> str:
        """the utterance that activated this ability, used to pick sources."""
        try:
            spoken = await self.capability_worker.wait_for_complete_transcription()
            return (spoken or "").strip().lower()
        except Exception as e:
            self.worker.editor_logging_handler.warning(
                f"trigger capture unavailable: {e}"
            )
            return ""

    async def _choose_sources(self) -> list[CivicSource]:
        """route straight from the trigger phrase; ask only if it names no jurisdiction."""
        phrase = await self._capture_trigger_phrase()
        active = self._match_sources(phrase)
        if active:
            self.worker.editor_logging_handler.info(
                f"Routed '{phrase}' to {', '.join(s.get_name() for s in active)}"
            )
            return active
        options = " or ".join(s.get_name() for s in self.sources)
        await self.capability_worker.speak(f"Which briefing would you like — {options}?")
        answer = await self.capability_worker.user_response()
        return self._match_sources(answer) or self.sources

    async def _configure_topics(self, source: CivicSource) -> None:
        """interactive flow to set user topic preferences."""
        await self.capability_worker.speak(
            f"What topics are you interested in for {source.get_name()}? "
            "You can say housing, zoning, transportation, education, public safety, or budget. "
            "Say multiple topics separated by 'and'."
        )
        
        response = await self.capability_worker.user_response()
        
        # parse topics from response
        response_lower = response.lower()
        topics = []
        for topic in ['housing', 'zoning', 'transportation', 'education', 'public safety', 'budget']:
            if topic in response_lower:
                topics.append(topic)
        
        if not topics:
            await self.capability_worker.speak("I didn't catch any topics. Showing all meetings.")
            return
        
        # save preferences
        prefs = await self._load_topic_preferences()
        prefs[source.get_name()] = topics
        await self._save_topic_preferences(prefs)
        
        # apply to source
        if hasattr(source, 'set_topic_preferences'):
            source.set_topic_preferences(topics)
        
        topic_list = ', '.join(topics)
        await self.capability_worker.speak(
            f"Got it. I'll prioritize {topic_list} meetings for {source.get_name()}."
        )

    async def _handle_details_request(self, phrase: str, active_sources: list[CivicSource]) -> bool:
        """check if this is a details request and handle it. returns True if handled."""
        # check for legislation request first
        if 'legislation' in phrase:
            for source in active_sources:
                if hasattr(source, 'fetch_legislation'):
                    await self.capability_worker.speak(f"Fetching pending legislation for {source.get_name()}.")
                    try:
                        leg_info = await source.fetch_legislation()
                        
                        # summarize for voice
                        summary = self.capability_worker.text_to_text_response(
                            "You are summarizing pending legislation. "
                            "Using ONLY the info below, provide a clear spoken summary. "
                            "Mention the total count, highlight 3-5 interesting items by topic. "
                            "Keep it conversational for a smart speaker.\n\n"
                            f"LEGISLATION INFO:\n{leg_info}"
                        )
                        await self.capability_worker.speak(summary)
                        
                    except Exception as e:
                        self.worker.editor_logging_handler.error(f"Legislation fetch error: {e}")
                        await self.capability_worker.speak(
                            f"I couldn't fetch legislation details right now. {str(e)[:100]}"
                        )
                    
                    self.capability_worker.resume_normal_flow()
                    return True
        
        # detect meeting details requests
        details_keywords = ['details', 'detail', 'tell me about', 'about meeting', 'meeting', 'agenda']
        if not any(kw in phrase for kw in details_keywords):
            return False
        
        # extract meeting reference (number, name, or ID)
        # patterns: "details on meeting 1", "tell me about city council", "meeting 1354765"
        meeting_ref = None
        
        # try number pattern first: "meeting 1", "number 3", etc.
        number_match = re.search(r'(?:meeting|number)\s*(\d+)', phrase)
        if number_match:
            meeting_ref = number_match.group(1)
        
        # try standalone number after "details"
        if not meeting_ref:
            standalone_match = re.search(r'details?\s+(?:on|for|about)?\s*(\d+)', phrase)
            if standalone_match:
                meeting_ref = standalone_match.group(1)
        
        # try body name extraction: "about city council", "planning commission"
        if not meeting_ref:
            # remove trigger words and common phrases
            cleaned = re.sub(r'(tell me about|details? (?:on|for|about)|meeting|the)\s*', '', phrase, flags=re.IGNORECASE)
            if cleaned.strip() and len(cleaned.strip()) > 3:
                meeting_ref = cleaned.strip()
        
        if not meeting_ref:
            await self.capability_worker.speak(
                "I didn't catch which meeting you want details for. Try saying the meeting number like 'details on meeting 1'."
            )
            self.capability_worker.resume_normal_flow()
            return True
        
        # route to source's get_details
        for source in active_sources:
            if hasattr(source, 'get_details'):
                await self.capability_worker.speak(f"Fetching details for {source.get_name()}.")
                try:
                    details = await source.get_details(meeting_ref)
                    
                    # summarize the details for voice
                    summary = self.capability_worker.text_to_text_response(
                        "You are summarizing a civic meeting agenda. "
                        "Using ONLY the details below, provide a clear spoken summary. "
                        "Mention the meeting name, date, time, and 3-5 key agenda items. "
                        "Keep it conversational for a smart speaker.\n\n"
                        f"MEETING DETAILS:\n{details}"
                    )
                    await self.capability_worker.speak(summary)
                    
                except Exception as e:
                    self.worker.editor_logging_handler.error(f"Details fetch error: {e}")
                    await self.capability_worker.speak(
                        f"I couldn't fetch those details right now. {str(e)[:100]}"
                    )
                
                self.capability_worker.resume_normal_flow()
                return True
        
        await self.capability_worker.speak("Details are not available for this source yet.")
        self.capability_worker.resume_normal_flow()
        return True


    async def run(self):
        active_sources = await self._choose_sources()
        
        # check if user wants to configure topics (on first time or explicit request)
        phrase = await self._capture_trigger_phrase()
        
        # handle details requests
        if await self._handle_details_request(phrase, active_sources):
            return
        
        # handle topic configuration
        if 'configure' in phrase or 'set topics' in phrase:
            for source in active_sources:
                if hasattr(source, 'set_topic_preferences'):
                    await self._configure_topics(source)
            self.capability_worker.resume_normal_flow()
            return
        
        # ask if user wants to configure topics (first time only)
        prefs = await self._load_topic_preferences()
        for source in active_sources:
            if source.get_name() not in prefs and hasattr(source, 'set_topic_preferences'):
                await self.capability_worker.speak(
                    "Would you like to set topic preferences to prioritize certain meetings?"
                )
                response = await self.capability_worker.user_response()
                if 'yes' in response.lower():
                    await self._configure_topics(source)
        
        source_names = ", ".join(s.get_name() for s in active_sources)
        await self.capability_worker.speak(f"Pulling the latest from {source_names}.")
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
            "You are giving a short spoken civic briefing. "
            f"Using ONLY the briefing text below, summarize the most important "
            f"updates from {source_names} in 4 to 6 short sentences. "
            "Do not mention documents, databases, or missing context. "
            "If a section contains an error, say briefly that the source was "
            "unavailable, then cover whatever else is there. "
            "Speak plainly for a smart speaker.\n\n"
            f"BRIEFING TEXT:\n{briefing}"
        )
        await self.capability_worker.speak(summary)

        for source in active_sources:
            if not source.validate_cache(briefing):
                await self.log_gap(source.get_name(), "Source returned no usable data.")

        await self.capability_worker.speak(
            "Would you like me to draft a message to any of these offices?"
        )
        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.sources = discover_sources()
        # note: _bind_sources is now async and called in collect_briefing
        self.worker.session_tasks.create(self.watchdog_loop())
        self.worker.session_tasks.create(self.run())
