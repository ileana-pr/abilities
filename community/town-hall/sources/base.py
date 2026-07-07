from abc import ABC, abstractmethod

class CivicSource(ABC):
    """Base class for all civic data sources (Cities, Counties, States)."""

    @abstractmethod
    def get_name(self) -> str:
        """Returns the human-readable name of the source (e.g. 'Richmond City Council')."""
        pass

    @abstractmethod
    def get_source_url(self) -> str:
        """Returns the primary URL or document link for the data source."""
        pass

    @abstractmethod
    async def fetch_updates(self) -> str:
        """
        Fetches the latest updates from the source.
        Returns a string (Markdown formatted) containing the updates.
        """
        pass

    async def search(self, query: str) -> str:
        """
        Performs a live search on the source for a specific topic.
        Returns a Markdown string of results.
        """
        return f"Live search not yet implemented for {self.get_name()}."

    async def get_details(self, item_id: str) -> str:
        """
        Fetches the full text or detailed records for a specific item.
        Used when the user asks 'probing' or 'follow-up' questions.
        """
        return f"Detail retrieval not yet implemented for {self.get_name()}."

    def get_metadata(self) -> dict:
        """Optional metadata about the source."""
        return {}

