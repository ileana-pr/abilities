from abc import ABC, abstractmethod
from typing import Optional
import json


class _SimpleResponse:
    """minimal response wrapper for sdk results that are plain strings."""

    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    @property
    def content(self) -> bytes:
        return (self.text or "").encode("utf-8", errors="ignore")

    def json(self):
        return json.loads(self.text or "{}")


class CivicSource(ABC):
    """base class for all civic data sources (cities, counties, states)."""

    def __init__(self):
        self._api_key: Optional[str] = None
        self._worker = None

    def required_api_key_name(self) -> Optional[str]:
        """override to declare the third-party key name this source needs.
        return None if no api key is required."""
        return None

    def set_api_key(self, api_key: Optional[str]) -> None:
        """called by the capability coordinator after resolving required_api_key_name."""
        self._api_key = api_key.strip() if api_key else None

    def trigger_keywords(self) -> tuple[str, ...]:
        """override to declare which keywords in the trigger phrase activate this source.
        return an empty tuple to always include this source regardless of trigger."""
        return ()

    @staticmethod
    def extract_section(content: str, name: str) -> str | None:
        """return the ### {name} section only (exact heading line, not a prefix)."""
        if not content or not name:
            return None
        heading = f"### {name}"
        lines = content.splitlines(keepends=True)
        start = None
        for i, line in enumerate(lines):
            if line.strip() == heading:
                start = i
                break
        if start is None:
            return None
        end = len(lines)
        for j in range(start + 1, len(lines)):
            stripped = lines[j].strip()
            if stripped == "---" or stripped.startswith("### "):
                end = j
                break
        return "".join(lines[start:end])

    def validate_cache(self, content: str) -> bool:
        """return False if this source's section is missing or contains an error."""
        section = self.extract_section(content, self.get_name())
        if not section:
            return False
        data_lines = [
            l.strip() for l in section.split("\n")
            if l.strip() and not l.strip().startswith("#")
        ]
        if not data_lines:
            return False
        for line in data_lines:
            lowered = line.lower()
            if lowered.startswith("- error") or lowered.startswith("error"):
                return False
        return True


    @abstractmethod
    def get_name(self) -> str:
        pass

    @abstractmethod
    def get_source_url(self) -> str:
        pass

    @abstractmethod
    async def fetch_updates(self) -> str:
        pass

    async def search(self, query: str) -> str:
        """search this source for specific items (optional feature)."""
        return f"Live search not yet implemented for {self.get_name()}."

    async def get_details(self, item_id: str) -> str:
        """get detailed information about a specific item (optional feature)."""
        return f"Detail retrieval not yet implemented for {self.get_name()}."

    async def fetch_legislation(self) -> str:
        """fetch pending legislation (optional feature for sources with legislative data)."""
        return f"Legislation tracking not available for {self.get_name()}."

    def set_topic_preferences(self, topics: list[str]) -> None:
        """store user's topic preferences (optional feature for sources with topic filtering)."""
        pass  # sources that support this will override

    def get_topic_preferences(self) -> list[str]:
        """retrieve stored topic preferences (optional feature)."""
        return []  # default: no preferences

    def get_metadata(self) -> dict:
        """return additional metadata about this source (optional)."""
        return {}

    def bind_worker(self, worker):
        """bind the worker for http requests."""
        self._worker = worker

    @staticmethod
    def _normalize_response(response):
        """wrap sdk results so callers can rely on .text/.status_code."""
        if response is None:
            return _SimpleResponse("", status_code=502)

        if isinstance(response, dict):
            text = response.get("text") or response.get("body") or response.get("content") or ""
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="ignore")
            status = int(response.get("status_code") or response.get("status") or 200)
            return _SimpleResponse(str(text), status_code=status)

        if isinstance(response, (bytes, bytearray)):
            return _SimpleResponse(response.decode("utf-8", errors="ignore"), status_code=200)

        # response-like object from the sdk (duck-typed without getattr)
        try:
            status = int(response.status_code or 200)
            text = response.text
            if text is None:
                content = response.content
                if isinstance(content, bytes):
                    text = content.decode("utf-8", errors="ignore")
                else:
                    text = str(content or "")
            return _SimpleResponse(text or "", status_code=status)
        except Exception:
            pass

        text = response if isinstance(response, str) else str(response)
        lowered = (text or "").lower()
        if (
            not text.strip()
            or text.startswith("coroutine ")
            or "traceback" in lowered
            or lowered.startswith("error")
            or "failed" in lowered[:100]
        ):
            return _SimpleResponse(text, status_code=502)
        return _SimpleResponse(text, status_code=200)

    def _http_get(self, url: str, headers: dict = None, timeout: float = None):
        """http get using openhome sdk. timeout is accepted for call-site
        compatibility but the sdk manages request timeouts itself."""
        if not self._worker:
            raise RuntimeError("worker not bound - call bind_worker() first")
        response = self._worker.session_tasks.get(url, headers=headers or {})
        return self._normalize_response(response)

    def _http_post(self, url: str, headers: dict = None, json_body: dict = None, timeout: float = None):
        """http post using openhome sdk."""
        if not self._worker:
            raise RuntimeError("worker not bound - call bind_worker() first")
        response = self._worker.session_tasks.post(
            url, headers=headers or {}, json=json_body
        )
        return self._normalize_response(response)
