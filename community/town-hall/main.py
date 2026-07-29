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

    async def _load_topic_preferences(self) -> list[str]:
        """load the user's topic preferences (shared across all sources)."""
        exists = await self.capability_worker.check_if_file_exists(
            TOPICS_FILE, in_ability_directory=True
        )
        if not exists:
            return []

        content = await self.capability_worker.read_file(
            TOPICS_FILE, in_ability_directory=True
        )
        if not content:
            return []

        data = json.loads(content)

        # current format: {"topics": ["housing", "zoning"]}
        if isinstance(data, dict) and isinstance(data.get("topics"), list):
            return [t for t in data["topics"] if isinstance(t, str)]

        # legacy per-source format: {"Richmond City Council": ["housing"], ...}
        if isinstance(data, dict):
            topics = []
            for value in data.values():
                if isinstance(value, list):
                    for topic in value:
                        if isinstance(topic, str) and topic not in topics:
                            topics.append(topic)
            return topics

        return []

    async def _save_topic_preferences(self, topics: list[str]) -> None:
        """save user-level topic preferences."""
        await self.capability_worker.write_file(
            TOPICS_FILE,
            json.dumps({"topics": topics}, indent=2),
            in_ability_directory=True,
        )

    async def _bind_sources(self):
        """inject api keys, worker, and topic preferences for each source."""
        topics = await self._load_topic_preferences()

        for source in self.sources:
            # bind worker for http requests
            source.bind_worker(self.worker)

            # inject api key if needed
            key_name = source.required_api_key_name()
            if key_name:
                source.set_api_key(self._resolve_api_key(key_name))

            # same user topics applied to every source that supports filtering
            if topics:
                source.set_topic_preferences(topics)

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

    async def _choose_sources(self, phrase: str) -> list[CivicSource]:
        """route from the trigger phrase; ask only if it names no jurisdiction."""
        active = self._match_sources(phrase)
        if active:
            self.worker.editor_logging_handler.info(
                f"Routed '{phrase}' to {', '.join(s.get_name() for s in active)}"
            )
            return active

        # keep the prompt short — don't enumerate every source (the list grows over time)
        await self.capability_worker.speak("Which briefing would you like?")
        answer = await self.capability_worker.user_response()
        matched = self._match_sources(answer)
        if matched:
            return matched

        # user named something we don't have yet
        await self.log_gap(answer, "No matching civic source for requested jurisdiction.")
        await self.capability_worker.speak(
            "I don't have a briefing for that yet. "
            "Try naming a supported city, county, state, or federal source, "
            "or say town hall again later as new sources are added."
        )
        return []

    def _parse_topics_from_response(self, response: str) -> list[str]:
        """extract free-form topic phrases from spoken user input."""
        text = (response or "").lower().strip()
        if not text:
            return []

        # strip common lead-ins
        for prefix in (
            "i'm interested in",
            "i am interested in",
            "interested in",
            "i care about",
            "add",
            "also add",
            "my topics are",
            "topics are",
            "topics",
        ):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                break

        # split on and / also / plus / commas / semicolons
        parts = re.split(r"\s*(?:,|;|\band\b|\balso\b|\bplus\b)\s*", text)

        topics = []
        skip = {"please", "thanks", "thank you", "yes", "okay", "ok", "um", "uh"}
        for part in parts:
            part = part.strip(" .!?'\"")
            part = re.sub(r"^(the|a|an|some|my)\s+", "", part)
            if not part or len(part) < 2 or part in skip:
                continue
            if part not in topics:
                topics.append(part)
        return topics

    async def _configure_topics(self) -> None:
        """interactive flow to add user-level topic preferences (shared across sources)."""
        existing = await self._load_topic_preferences()
        if existing:
            current = ", ".join(existing)
            await self.capability_worker.speak(
                f"Your current topics are {current}. "
                "What would you like to add? You can name anything — for example housing, "
                "zoning, parks, or climate. Say multiple topics separated by 'and'."
            )
        else:
            await self.capability_worker.speak(
                "What topics are you interested in? "
                "You can name anything — for example housing, zoning, transportation, "
                "parks, or climate. Say multiple topics separated by 'and'."
            )

        response = await self.capability_worker.user_response()
        new_topics = self._parse_topics_from_response(response)

        if not new_topics:
            await self.capability_worker.speak(
                "I didn't catch any topics. Your existing preferences are unchanged."
            )
            return

        # append new topics; keep prior ones
        merged = list(existing)
        added = []
        for topic in new_topics:
            if topic not in merged:
                merged.append(topic)
                added.append(topic)

        if not added:
            await self.capability_worker.speak(
                "Those topics are already on your list. No changes made."
            )
            return

        await self._save_topic_preferences(merged)
        self._apply_topics_to_sources(merged)

        added_list = ", ".join(added)
        all_list = ", ".join(merged)
        await self.capability_worker.speak(
            f"Added {added_list}. I'll prioritize {all_list} across your civic briefings."
        )

    def _apply_topics_to_sources(self, topics: list[str]) -> None:
        """push the current user topic list into every registered source."""
        for source in self.sources:
            source.set_topic_preferences(topics)

    async def _remove_topics(self) -> None:
        """interactive flow to remove topics from the user's preference list."""
        existing = await self._load_topic_preferences()
        if not existing:
            await self.capability_worker.speak(
                "You don't have any topic preferences saved."
            )
            return

        current = ", ".join(existing)
        await self.capability_worker.speak(
            f"Your current topics are {current}. "
            "Which should I remove? Say the topic names, or say clear all."
        )

        response = await self.capability_worker.user_response()
        response_lower = (response or "").lower().strip()

        # wipe the whole list
        if any(
            phrase in response_lower
            for phrase in (
                "clear all",
                "clear everything",
                "remove all",
                "delete all",
                "all of them",
                "everything",
            )
        ):
            await self._save_topic_preferences([])
            self._apply_topics_to_sources([])
            await self.capability_worker.speak("Cleared all topic preferences.")
            return

        to_remove = self._parse_topics_from_response(response)
        if not to_remove:
            await self.capability_worker.speak(
                "I didn't catch which topics to remove. Your list is unchanged."
            )
            return

        removed = []
        remaining = []
        for topic in existing:
            if topic in to_remove:
                removed.append(topic)
            else:
                remaining.append(topic)

        if not removed:
            await self.capability_worker.speak(
                "None of those matched your saved topics. Your list is unchanged."
            )
            return

        await self._save_topic_preferences(remaining)
        self._apply_topics_to_sources(remaining)

        removed_list = ", ".join(removed)
        if remaining:
            await self.capability_worker.speak(
                f"Removed {removed_list}. I'll prioritize {', '.join(remaining)} across your civic briefings."
            )
        else:
            await self.capability_worker.speak(
                f"Removed {removed_list}. You have no topic preferences left."
            )

    def _is_done_intent(self, phrase: str) -> bool:
        """true when the user wants to end the follow-up loop."""
        text = (phrase or "").lower().strip()
        if not text:
            return True
        done_phrases = (
            "done",
            "i'm done",
            "im done",
            "that's all",
            "thats all",
            "nothing",
            "no thanks",
            "no thank you",
            "stop",
            "bye",
            "goodbye",
            "never mind",
            "nevermind",
            "no",
        )
        return any(p == text or text.startswith(p + " ") for p in done_phrases) or text in done_phrases

    def _is_legislation_intent(self, phrase: str) -> bool:
        """true for a full legislation list request (not a specific item lookup)."""
        text = (phrase or "").lower().strip()
        # specific file numbers are details, not a full list
        if re.search(r'\b(ord\.?|res\.?)\s*\d', text):
            return False
        list_markers = (
            "legislation",
            "pending legislation",
            "new legislation",
            "any legislation",
            "recent legislation",
            "the legislation",
            "new bills",
            "pending bills",
            "any bills",
            "ordinances and resolutions",
        )
        if any(marker in text for marker in list_markers):
            return True
        return text in (
            "bills",
            "bill",
            "ordinances",
            "ordinance",
            "resolutions",
            "resolution",
        )

    def _is_details_intent(self, phrase: str) -> bool:
        text = (phrase or "").lower()
        if re.search(r'\b(ord\.?|res\.?)\s*\d', text):
            return True
        details_keywords = (
            'details', 'detail', 'tell me about', 'about meeting',
            'meeting', 'agenda', 'more about', 'what about',
            'ordinance', 'resolution',
        )
        return any(kw in text for kw in details_keywords)

    async def _speak_and_maybe_end(self, end_session: bool) -> None:
        if end_session:
            self.capability_worker.resume_normal_flow()

    async def _handle_legislation_request(
        self,
        active_sources: list[CivicSource],
        briefing: str = "",
        end_session: bool = True,
    ) -> bool:
        """fetch and speak legislation for active sources. returns True if handled."""
        for source in active_sources:
            await self.capability_worker.speak(
                f"Fetching pending legislation for {source.get_name()}."
            )
            try:
                leg_info = await source.fetch_legislation()

                # virginia (and others without a legislation endpoint) already
                # put bills in the briefing — answer from that instead of the stub
                if briefing and "not available" in leg_info.lower():
                    summary = self.capability_worker.text_to_text_response(
                        "You are answering a follow-up about legislation from a civic briefing. "
                        "Using ONLY the briefing text below, highlight the most relevant bills "
                        "or legislation items in 3-5 short sentences. Prefer items matching "
                        "common civic topics if present. Speak plainly for a smart speaker.\n\n"
                        f"USER ASKED ABOUT: legislation\n\nBRIEFING TEXT:\n{briefing}"
                    )
                    await self.capability_worker.speak(summary)
                else:
                    summary = self.capability_worker.text_to_text_response(
                        "You are summarizing pending legislation. "
                        "Using ONLY the info below, provide a clear spoken summary. "
                        "Mention the total count, lead with any items marked as matching "
                        "the user's topics, then highlight 3-5 interesting items. "
                        "Keep it conversational for a smart speaker.\n\n"
                        f"LEGISLATION INFO:\n{leg_info}"
                    )
                    await self.capability_worker.speak(summary)

            except Exception as e:
                self.worker.editor_logging_handler.error(f"Legislation fetch error: {e}")
                await self.capability_worker.speak(
                    f"I couldn't fetch legislation details right now. {str(e)[:100]}"
                )

            await self._speak_and_maybe_end(end_session)
            return True
        return False

    async def _handle_meeting_details(
        self,
        phrase: str,
        active_sources: list[CivicSource],
        end_session: bool = True,
    ) -> bool:
        """handle meeting / item detail requests. returns True if handled."""
        # extract meeting reference (number, name, ID, or legislation search terms)
        meeting_ref = None

        number_match = re.search(r'(?:meeting|number)\s*(\d+)', phrase)
        if number_match:
            meeting_ref = number_match.group(1)

        if not meeting_ref:
            standalone_match = re.search(r'details?\s+(?:on|for|about)?\s*(\d+)', phrase)
            if standalone_match:
                meeting_ref = standalone_match.group(1)

        if not meeting_ref:
            # ord/res ids or body/topic phrases
            cleaned = re.sub(
                r'(tell me about|details? (?:on|for|about)|meeting|more about|what about|the)\s*',
                '',
                phrase,
                flags=re.IGNORECASE,
            )
            if cleaned.strip() and len(cleaned.strip()) > 2:
                meeting_ref = cleaned.strip()

        if not meeting_ref:
            await self.capability_worker.speak(
                "I didn't catch which meeting or item you want details for. "
                "Try saying the meeting number like 'details on meeting 1'."
            )
            await self._speak_and_maybe_end(end_session)
            return True

        for source in active_sources:
            await self.capability_worker.speak(f"Fetching details for {source.get_name()}.")
            try:
                details = await source.get_details(meeting_ref)

                summary = self.capability_worker.text_to_text_response(
                    "You are summarizing a civic meeting agenda or legislation item. "
                    "Using ONLY the details below, provide a clear spoken summary. "
                    "Mention the name, date/time when present, and 3-5 key points. "
                    "Keep it conversational for a smart speaker.\n\n"
                    f"DETAILS:\n{details}"
                )
                await self.capability_worker.speak(summary)

            except Exception as e:
                self.worker.editor_logging_handler.error(f"Details fetch error: {e}")
                await self.capability_worker.speak(
                    f"I couldn't fetch those details right now. {str(e)[:100]}"
                )

            await self._speak_and_maybe_end(end_session)
            return True

        return True

    async def _handle_details_request(
        self,
        phrase: str,
        active_sources: list[CivicSource],
        briefing: str = "",
        end_session: bool = True,
    ) -> bool:
        """check if this is a details/legislation request and handle it. returns True if handled."""
        if self._is_legislation_intent(phrase):
            return await self._handle_legislation_request(
                active_sources, briefing=briefing, end_session=end_session
            )

        if not self._is_details_intent(phrase):
            return False

        return await self._handle_meeting_details(
            phrase, active_sources, end_session=end_session
        )

    async def _answer_from_briefing(self, question: str, briefing: str) -> None:
        """answer a free-form follow-up using only the briefing already fetched."""
        summary = self.capability_worker.text_to_text_response(
            "You are answering a follow-up question about a civic briefing the user just heard. "
            "Using ONLY the briefing text below, answer in 2-4 short sentences. "
            "If the briefing does not contain the answer, say you don't have that detail "
            "in the current briefing and suggest asking about a meeting number or legislation. "
            "Do not invent facts. Speak plainly for a smart speaker.\n\n"
            f"USER QUESTION:\n{question}\n\nBRIEFING TEXT:\n{briefing}"
        )
        await self.capability_worker.speak(summary)

    async def _follow_up_loop(
        self, active_sources: list[CivicSource], briefing: str
    ) -> None:
        """after a briefing, allow a few turns of legislation / details / Q&A."""
        await self.capability_worker.speak(
            "Want details on a meeting, recent legislation, or something else from that briefing? "
            "Or say you're done."
        )

        for _ in range(3):
            answer = await self.capability_worker.user_response()
            answer = (answer or "").strip()

            if self._is_done_intent(answer):
                await self.capability_worker.speak("Okay.")
                break

            if self._is_legislation_intent(answer):
                await self._handle_legislation_request(
                    active_sources, briefing=briefing, end_session=False
                )
                await self.capability_worker.speak(
                    "Anything else, or are you done?"
                )
                continue

            if self._is_details_intent(answer):
                await self._handle_meeting_details(
                    answer, active_sources, end_session=False
                )
                await self.capability_worker.speak(
                    "Anything else, or are you done?"
                )
                continue

            # free-form question about what was just presented
            await self._answer_from_briefing(answer, briefing)
            await self.capability_worker.speak(
                "Anything else, or are you done?"
            )

        self.capability_worker.resume_normal_flow()

    async def run(self):
        phrase = await self._capture_trigger_phrase()

        # topic config is user-level — no jurisdiction needed
        if 'configure' in phrase or 'set topics' in phrase:
            await self._configure_topics()
            self.capability_worker.resume_normal_flow()
            return

        if (
            'remove topics' in phrase
            or 'delete topics' in phrase
            or 'clear topics' in phrase
            or (('remove' in phrase or 'delete' in phrase) and 'topic' in phrase)
        ):
            await self._remove_topics()
            self.capability_worker.resume_normal_flow()
            return

        active_sources = await self._choose_sources(phrase)
        if not active_sources:
            self.capability_worker.resume_normal_flow()
            return

        # dedicated details/legislation triggers (no follow-up loop)
        if await self._handle_details_request(phrase, active_sources, end_session=True):
            return

        # offer topic setup once if the user has none yet
        topics = await self._load_topic_preferences()
        if not topics:
            await self.capability_worker.speak(
                "Would you like to set topic preferences to prioritize certain meetings?"
            )
            response = await self.capability_worker.user_response()
            if 'yes' in response.lower():
                await self._configure_topics()

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

        await self._follow_up_loop(active_sources, briefing)

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.sources = discover_sources()
        # note: _bind_sources is now async and called in collect_briefing
        self.worker.session_tasks.create(self.watchdog_loop())
        self.worker.session_tasks.create(self.run())
