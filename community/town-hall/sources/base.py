from abc import ABC, abstractmethod

class CivicSource(ABC):
    """Base class for all civic data sources (Cities, Counties, States)."""

    @abstractmethod
    def get_name(self) -> str:
        """Returns the human-readable name of the source (e.g. 'Richmond City Council')."""
        pass

    @abstractmethod
    async def fetch_updates(self) -> str:
        """
        Fetches the latest updates from the source.
        Returns a string (Markdown formatted) containing the updates.
        """
        pass

    def get_metadata(self) -> dict:
        """Optional metadata about the source."""
        return {}
