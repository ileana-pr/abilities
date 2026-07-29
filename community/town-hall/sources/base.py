from abc import ABC, abstractmethod
from typing import Optional


class _SimpleResponse:
    """minimal response wrapper for sdk results that are plain strings."""

    def __init__(self, text: str):
        self.text = text
        self.status_code = 200

    @property
    def content(self) -> bytes:
        return self.text.encode("utf-8", errors="ignore")


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

    def validate_cache(self, content: str) -> bool:
        """return False if this source's section in the aggregated briefing looks errored.
        the coordinator uses this to decide whether to serve or discard a cached briefing."""
        name = self.get_name()
        marker = f"### {name}"
        if marker not in content:
            return True
        start = content.index(marker)
        end = content.find("---", start)
        section = content[start:end] if end != -1 else content[start:]
        data_lines = [
            l.strip() for l in section.split("\n")
            if l.strip() and not l.strip().startswith("#")
        ]
        if not data_lines:
            return False
        return not all(
            l.lower().startswith("- error") or l.lower().startswith("error")
            for l in data_lines
        )

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
        """wrap plain-string sdk results so callers can rely on .text/.status_code."""
        if hasattr(response, "status_code"):
            return response
        text = response if isinstance(response, str) else str(response)
        return _SimpleResponse(text)

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
        response = self._worker.session_tasks.post(url, headers=headers or {}, json=json_body)
        return self._normalize_response(response)
