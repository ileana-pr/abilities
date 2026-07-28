import re

from .base import CivicSource


class RichmondCitySource(CivicSource):
    def __init__(self):
        super().__init__()

    def get_name(self) -> str:
        return "Richmond City Council"

    def get_source_url(self) -> str:
        return "https://richmondva.legistar.com/Calendar.aspx"

    def trigger_keywords(self) -> tuple[str, ...]:
        return ("richmond",)

    async def fetch_updates(self) -> str:
        url = "https://richmondva.legistar.com/Calendar.aspx"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            )
        }
        try:
            response = await self._http_get(url, headers=headers, timeout=15)
            if response.status_code >= 400:
                return f"Error fetching Richmond calendar: HTTP {response.status_code}"
            html = response.text or ""

            # extract meeting detail links and agenda links
            meeting_matches = re.findall(
                r"MeetingDetail\.aspx\?ID=(\d+)&amp;GUID=([0-9A-F-]+)", html
            )
            agenda_matches = re.findall(
                r"View\.ashx\?M=A&amp;ID=(\d+)&amp;GUID=([0-9A-F-]+)", html
            )

            updates = ["### Richmond City Council (Upcoming)"]
            for i in range(min(5, len(meeting_matches))):
                agenda_status = (
                    "✅ Agenda Available" if i < len(agenda_matches) else "❌ No Agenda Yet"
                )
                updates.append(
                    f"- **Meeting ID**: {meeting_matches[i][0]} | {agenda_status}"
                )

            return "\n".join(updates) if len(updates) > 1 else "No upcoming Richmond meetings found."
        except Exception as e:
            return f"Error fetching Richmond calendar: {str(e)}"
