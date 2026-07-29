import re
import io
import subprocess
from datetime import datetime, timedelta
from typing import Optional

from .base import CivicSource

try:
    from pypdf import PdfReader
    HAS_PDF_SUPPORT = True
except ImportError:
    HAS_PDF_SUPPORT = False

# check for pdftotext utility
try:
    subprocess.run(['pdftotext', '-v'], capture_output=True, timeout=2)
    HAS_PDFTOTEXT = True
except (FileNotFoundError, subprocess.TimeoutExpired):
    HAS_PDFTOTEXT = False

DEFAULT_TOPICS = {
    'housing': ['housing', 'affordable housing', 'residential', 'development'],
    'zoning': ['zoning', 'planning', 'land use', 'rezoning'],
    'transportation': ['transportation', 'transit', 'traffic', 'road', 'parking'],
    'education': ['school', 'education', 'schools'],
    'public safety': ['police', 'fire', 'safety', 'emergency'],
    'budget': ['budget', 'finance', 'appropriation'],
}


class RichmondCitySource(CivicSource):
    """richmond city council - fetches meetings from legistar calendar."""

    def __init__(self):
        super().__init__()
        self._recent_meetings = []  # cache for get_details lookups
        self._numbered_meetings = {}  # map ordinal numbers to meeting IDs
        self._topic_preferences = []  # user's topic interests
        self._recent_legislation = []  # cache of legislation from agendas

    def get_name(self) -> str:
        return "Richmond City Council"

    def get_source_url(self) -> str:
        return "https://richmondva.legistar.com/Calendar.aspx"

    def trigger_keywords(self) -> tuple[str, ...]:
        return ("richmond", "legislation")

    def set_topic_preferences(self, topics: list[str]) -> None:
        """store user's topic interests."""
        self._topic_preferences = [t.lower() for t in topics]

    def get_topic_preferences(self) -> list[str]:
        """retrieve stored topic preferences."""
        return getattr(self, '_topic_preferences', [])

    def _matches_topics(self, meeting: dict, topics: list[str]) -> bool:
        """check if meeting matches any user topic interest."""
        body = meeting.get('body', '').lower()
        for topic in topics:
            keywords = DEFAULT_TOPICS.get(topic, [topic])
            if any(kw in body for kw in keywords):
                return True
        return False

    def _parse_meeting_row(self, row: str) -> Optional[dict]:
        """extract meeting details from a table row."""
        meeting = {}

        # extract all td cell contents first
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
        
        # clean cells - remove HTML tags and extra whitespace
        cleaned_cells = []
        for cell in cells:
            text = re.sub(r'<[^>]+>', '', cell)
            text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
            text = re.sub(r'\s+', ' ', text).strip()
            cleaned_cells.append(text)

        # extract body/committee name (usually first meaningful cell)
        for cell in cleaned_cells[:3]:
            if any(word in cell.lower() for word in ['council', 'committee', 'commission', 'board']):
                if len(cell) > 3 and len(cell) < 100:
                    meeting['body'] = cell
                    break

        # extract date from cleaned cells
        for cell in cleaned_cells:
            date_match = re.match(r'(\d{1,2}/\d{1,2}/\d{4})$', cell)
            if date_match:
                try:
                    meeting['date'] = datetime.strptime(cell, '%m/%d/%Y')
                except ValueError:
                    pass
                break

        # extract time from cleaned cells
        for cell in cleaned_cells:
            time_match = re.match(r'(\d{1,2}:\d{2}\s*[AP]M)$', cell, re.IGNORECASE)
            if time_match:
                meeting['time'] = cell
                break

        # extract location from cleaned cells (contains keywords but not just keywords)
        for cell in cleaned_cells:
            cell_lower = cell.lower()
            if any(word in cell_lower for word in ['chamber', 'city hall', 'room', 'floor']):
                if len(cell) > 5 and len(cell) < 100:
                    meeting['location'] = cell
                    break

        # extract meeting ID
        id_match = re.search(r'MeetingDetail\.aspx\?ID=(\d+)&amp;GUID=([0-9A-F-]+)', row)
        if id_match:
            meeting['id'] = id_match.group(1)
            meeting['guid'] = id_match.group(2)

        # check for agenda availability
        agenda_match = re.search(r'View\.ashx\?M=A&amp;ID=(\d+)&amp;GUID=([0-9A-F-]+)', row)
        meeting['has_agenda'] = bool(agenda_match)
        if agenda_match:
            meeting['agenda_url'] = (
                f"https://richmondva.legistar.com/View.ashx?"
                f"M=A&ID={agenda_match.group(1)}&GUID={agenda_match.group(2)}"
            )

        # check for minutes
        minutes_match = re.search(r'View\.ashx\?M=M\d*&amp;ID=(\d+)&amp;GUID=([0-9A-F-]+)', row)
        meeting['has_minutes'] = bool(minutes_match)
        if minutes_match:
            meeting['minutes_url'] = (
                f"https://richmondva.legistar.com/View.ashx?"
                f"M=M&ID={minutes_match.group(1)}&GUID={minutes_match.group(2)}"
            )

        # check for video
        meeting['has_video'] = 'Video' in row and 'Not&nbsp;available' not in row

        return meeting if 'date' in meeting else None

    def _format_date(self, dt: datetime) -> str:
        """format date as 'Monday, July 28'."""
        return dt.strftime('%A, %B %-d')

    def _format_meeting_title(self, number: int, meeting: dict) -> str:
        """format meeting as compact title line for initial briefing."""
        body = meeting.get('body', 'Unknown Body')
        date = meeting.get('date')
        time = meeting.get('time', '')
        
        date_str = self._format_date(date) if date else '?'
        return f"{number}. **{body}** - {date_str} at {time}"

    def _format_meeting_line(self, meeting: dict, number: int) -> str:
        """format a single meeting as markdown with ordinal number."""
        body = meeting.get('body', 'Unknown Body')
        date = meeting.get('date')
        time = meeting.get('time', '')
        location = meeting.get('location', '')

        # build the main line with number
        date_str = self._format_date(date) if date else '?'
        line = f"- **{number}. {body}** meets {date_str}"
        if time:
            line += f" at {time}"

        # add location if available
        if location:
            line += f"\n  Location: {location}"

        # add availability info
        available = []
        if meeting.get('has_agenda'):
            available.append('Agenda')
        if meeting.get('has_minutes'):
            available.append('Minutes')
        if meeting.get('has_video'):
            available.append('Video')

        if available:
            line += f"\n  {', '.join(available)} available"

        return line

    def _filter_meetings(
        self, meetings: list[dict], days_ahead: int = 14, priority_bodies: tuple = None, topics: list = None
    ) -> list[dict]:
        """filter meetings to upcoming and recent past ones, prioritize city council and topics."""
        now = datetime.now()
        cutoff_future = now + timedelta(days=days_ahead)
        cutoff_past = now - timedelta(days=3)  # include last 3 days

        # filter to recent and upcoming meetings
        relevant = [
            m for m in meetings
            if m.get('date') and cutoff_past <= m['date'] <= cutoff_future
        ]

        # sort by date
        relevant.sort(key=lambda m: m['date'])

        # prioritize by topics if provided
        if topics:
            priority = []
            other = []
            for m in relevant:
                if self._matches_topics(m, topics):
                    priority.append(m)
                else:
                    other.append(m)
            return priority + other

        # prioritize certain bodies if specified
        if priority_bodies:
            priority = []
            other = []
            for m in relevant:
                body = m.get('body', '').lower()
                if any(p.lower() in body for p in priority_bodies):
                    priority.append(m)
                else:
                    other.append(m)
            return priority + other

        return relevant

    async def fetch_updates(self) -> str:
        """fetch upcoming richmond meetings and format for voice."""
        url = self.get_source_url()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            )
        }

        try:
            response = self._http_get(url, headers=headers, timeout=15)
            if response.status_code >= 400:
                return f"### Richmond City Council\n- Error fetching calendar: HTTP {response.status_code}"

            html = response.text or ""

            # extract table rows
            tr_pattern = r'<tr[^>]*class="[^"]*rgRow[^"]*"[^>]*>(.*?)</tr>'
            rows = re.findall(tr_pattern, html, re.DOTALL | re.IGNORECASE)

            # parse each row
            meetings = []
            for row in rows:
                meeting = self._parse_meeting_row(row)
                if meeting:
                    meetings.append(meeting)

            # cache for get_details
            self._recent_meetings = meetings

            # filter to next 7 days, prioritize topics and city council
            topics = self.get_topic_preferences()
            filtered = self._filter_meetings(
                meetings, days_ahead=7, priority_bodies=('City Council',) if not topics else None, topics=topics
            )

            # build numbered list
            self._numbered_meetings = {}
            lines = ["### Richmond City Council"]

            if not filtered:
                lines.append("- No upcoming meetings in the next week")
                lines.append(f"- Source: {self.get_source_url()}")
                return "\n".join(lines)

            # show first 5-8 titles
            display_count = min(8, len(filtered))
            lines.append(f"\n{len(filtered)} upcoming meetings this week:")

            for i, meeting in enumerate(filtered[:display_count], 1):
                self._numbered_meetings[i] = meeting.get('id')
                lines.append(self._format_meeting_title(i, meeting))

            if len(filtered) > display_count:
                lines.append(f"\n...plus {len(filtered) - display_count} more meetings")

            lines.append(f"\nSay 'details on meeting [number]' or 'tell me about [body name]'")
            
            # extract legislation summary from recent meeting agendas
            leg_summary = self._get_legislation_summary()
            if leg_summary:
                lines.append(f"\n{leg_summary}")

            return "\n".join(lines)

        except Exception as e:
            return f"### Richmond City Council\n- Error fetching calendar: {str(e)}"

    def _search_legislation(self, query: str) -> list[dict]:
        """search cached legislation by keywords in description."""
        query_lower = query.lower()
        query_words = query_lower.split()
        
        matches = []
        for leg in self._recent_legislation:
            desc_lower = leg['description'].lower()
            
            # check if all query words appear in description
            if all(word in desc_lower for word in query_words):
                matches.append(leg)
            # or if any significant word matches (for single-word queries)
            elif len(query_words) == 1 and len(query_words[0]) > 4 and query_words[0] in desc_lower:
                matches.append(leg)
        
        return matches
    
    async def get_details(self, item_ref: str) -> str:
        """fetch details by number, meeting ID, body name, date, or legislation search."""
        # check if this is a legislation reference (ORD./RES. format)
        leg_match = re.match(r'^(ORD\.?|RES\.?)\s*(\d{4}-[A-Z]?\d+)$', item_ref.upper().strip())
        if leg_match:
            leg_type = 'Ordinance' if leg_match.group(1).startswith('ORD') else 'Resolution'
            leg_id = leg_match.group(2)
            
            # search in cached legislation
            for leg in self._recent_legislation:
                if leg['id'] == leg_id:
                    return (
                        f"### {leg_type} {leg_id}\n"
                        f"**Description:** {leg['description']}\n\n"
                        f"*This {leg_type.lower()} appears in recent meeting agendas. "
                        f"Full text and voting record available on Richmond Legistar.*"
                    )
            
            # not in cache, return helpful message
            return (
                f"### {leg_type} {leg_id}\n"
                f"This {leg_type.lower()} is not in the recent meeting cache. "
                f"Try 'richmond legislation' to see all pending items, or "
                f"'richmond city' to refresh meeting data."
            )
        
        # try legislation text search if we have legislation cached
        # and query contains potential legislation keywords or looks like a search query
        leg_keywords = ['ordinance', 'resolution', 'zoning', 'housing', 'development', 
                        'authorize', 'amend', 'close', 'special use', 'bond', 'budget',
                        'street', 'avenue', 'road', 'boulevard', 'trust', 'fund', 'transportation']
        item_lower = item_ref.lower()
        
        # search legislation if: keywords present OR we have legislation cache and no obvious meeting ref
        should_search_legislation = (
            any(kw in item_lower for kw in leg_keywords) or 
            (self._recent_legislation and not item_ref.isdigit() and len(item_ref) > 4)
        )
        
        if should_search_legislation:
            matches = self._search_legislation(item_ref)
            
            if len(matches) == 1:
                # single match - return it
                leg = matches[0]
                return (
                    f"### {leg['type']} {leg['id']}\n"
                    f"**Description:** {leg['description']}\n\n"
                    f"*This {leg['type'].lower()} appears in recent meeting agendas. "
                    f"Full text and voting record available on Richmond Legistar.*"
                )
            elif len(matches) > 1:
                # multiple matches - list them
                lines = [f"Found {len(matches)} matching items:"]
                for i, leg in enumerate(matches[:10], 1):
                    lines.append(f"{i}. **{leg['type']} {leg['id']}** — {leg['description'][:80]}...")
                if len(matches) > 10:
                    lines.append(f"\n...plus {len(matches) - 10} more matches")
                lines.append(f"\nSay the ORD or RES number to get full details (e.g., 'ORD. {matches[0]['id']}')")
                return "\n".join(lines)
            # if no matches, continue to meeting search below
        
        # otherwise, treat as meeting reference
        meeting = None
        
        # try as number first
        if item_ref.isdigit():
            number = int(item_ref)
            if number in self._numbered_meetings:
                meeting_id = self._numbered_meetings[number]
                meeting = next((m for m in self._recent_meetings if m.get('id') == meeting_id), None)
        
        # try as meeting ID
        if not meeting:
            meeting = next((m for m in self._recent_meetings if m.get('id') == item_ref), None)
        
        # try as body name match
        if not meeting:
            item_lower = item_ref.lower()
            for m in self._recent_meetings:
                if item_lower in m.get('body', '').lower():
                    meeting = m
                    break
        
        if not meeting:
            return f"Could not find meeting or legislation matching '{item_ref}'. Try using the meeting number (1-8) from the briefing or a legislation ID like 'ORD. 2026-093'."

        body = meeting.get('body', 'Meeting')
        date_str = self._format_date(meeting['date']) if meeting.get('date') else 'Unknown date'

        # try to fetch agenda first, then minutes
        content_url = None
        content_type = None

        if meeting.get('has_agenda'):
            content_url = meeting.get('agenda_url')
            content_type = 'Agenda'
        elif meeting.get('has_minutes'):
            content_url = meeting.get('minutes_url')
            content_type = 'Minutes'

        if not content_url:
            return (
                f"### {body} - {date_str}\n"
                f"- No agenda or minutes available yet for this meeting"
            )

        # fetch the document (usually PDF)
        try:
            resp = self._http_get(content_url, timeout=20)
            if resp.status_code >= 400:
                return f"### {body} - {date_str}\n- Error fetching {content_type.lower()}: HTTP {resp.status_code}"

            size_kb = len(resp.content) // 1024
            
            # build base response
            lines = [
                f"### {body} - {date_str}",
                f"- **{content_type}** ({size_kb}KB)",
                f"- Time: {meeting.get('time', 'TBD')}",
                f"- Location: {meeting.get('location', 'TBD')}"
            ]
            
            # try to parse PDF content using pdftotext first (most reliable), then pypdf
            pdf_text = None
            
            if HAS_PDFTOTEXT and resp.content:
                try:
                    # use pdftotext utility (very reliable for text extraction)
                    result = subprocess.run(
                        ['pdftotext', '-', '-'],
                        input=resp.content,
                        capture_output=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        pdf_text = result.stdout.decode('utf-8', errors='ignore')
                except Exception:
                    pass  # fall through to pypdf
            
            if not pdf_text and HAS_PDF_SUPPORT and resp.content:
                try:
                    pdf_file = io.BytesIO(resp.content)
                    reader = PdfReader(pdf_file)
                    
                    # extract text from first few pages
                    text_parts = []
                    max_pages = min(5, len(reader.pages))
                    for page_num in range(max_pages):
                        page = reader.pages[page_num]
                        text = page.extract_text()
                        if text:
                            text_parts.append(text)
                    
                    pdf_text = '\n'.join(text_parts)
                except Exception:
                    pass  # no text extracted
            
            if pdf_text and pdf_text.strip():
                # extract agenda items based on actual Richmond format
                agenda_items = self._extract_richmond_agenda_items(pdf_text)
                
                if agenda_items:
                    lines.append("\n**Agenda Items:**")
                    for i, item in enumerate(agenda_items[:15], 1):
                        lines.append(f"{i}. {item}")
                    
                    if len(agenda_items) > 15:
                        lines.append(f"\n...plus {len(agenda_items) - 15} more items")
                else:
                    # fallback: show summary
                    summary = self._summarize_agenda(pdf_text)
                    if summary:
                        lines.append(f"\n**Summary:**\n{summary}")
            else:
                # no text extracted
                if not HAS_PDFTOTEXT and not HAS_PDF_SUPPORT:
                    lines.append(f"\n*PDF parsing not available*")
                else:
                    lines.append(f"\n*Unable to extract text from PDF*")
                lines.append(f"- Direct link: {content_url}")
            
            return '\n'.join(lines)

        except Exception as e:
            return f"### {body} - {date_str}\n- Error fetching details: {str(e)}"
    
    def _extract_richmond_agenda_items(self, text: str) -> list[str]:
        """extract agenda items from Richmond Legistar PDFs (actual format)."""
        items = []
        
        # richmond format: numbered item, then ID on next line, then description
        # example:
        # 1.
        # ORD. 2026-093
        # Description text here...
        # OR
        # 1.
        # COA-1867092026
        # 2405 Jefferson Avenue - Paint mural...
        
        lines = text.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # look for numbered item (just "1." or "2." on its own line)
            if re.match(r'^\d+\.$', line):
                item_parts = []
                i += 1
                
                # next few lines form the item
                while i < len(lines) and len(item_parts) < 10:
                    next_line = lines[i].strip()
                    
                    # stop at next numbered item or section header
                    if re.match(r'^\d+\.$', next_line):
                        break
                    if next_line in ['Attachments:', 'Patrons:', 'Legislative History', 'To be continued']:
                        break
                    
                    # skip date lines (legislative history)
                    if re.match(r'^\d{1,2}/\d{1,2}/\d{2}', next_line):
                        break
                    
                    # skip lines that are clearly section headers or metadata
                    if next_line in ['Agenda', 'City Council', 'Planning Commission', 'July 27, 2026']:
                        i += 1
                        continue
                    
                    # collect non-empty lines that aren't IDs
                    if next_line and len(next_line) > 5:
                        # include lines that look like descriptions (not just IDs)
                        if not re.match(r'^(ORD\.|RES\.|COA-|CD\.)', next_line):
                            item_parts.append(next_line)
                    
                    i += 1
                
                # combine parts into item description (take first meaningful line or two)
                if item_parts:
                    # use first 1-2 parts as description
                    item_text = ' '.join(item_parts[:2]).strip()
                    item_text = re.sub(r'\s+', ' ', item_text)
                    
                    # clean up common noise
                    item_text = re.sub(r'Page \d+', '', item_text)
                    item_text = re.sub(r'Printed on.*', '', item_text)
                    
                    # limit length
                    if len(item_text) > 150:
                        item_text = item_text[:147] + '...'
                    
                    if item_text and len(item_text) > 20:
                        items.append(item_text)
            else:
                i += 1
        
        return items
    
    def _summarize_agenda(self, text: str) -> str:
        """create a brief summary of agenda content."""
        # look for key sections
        sections = []
        
        if 'CONSENT AGENDA' in text:
            sections.append('consent items')
        if 'REGULAR AGENDA' in text:
            sections.append('regular business')
        if 'CONCEPTUAL REVIEW' in text:
            sections.append('conceptual reviews')
        if 'Public Comment' in text:
            sections.append('public comment period')
        if 'Ordinance' in text or 'ORD.' in text:
            sections.append('ordinances')
        if 'Resolution' in text or 'RES.' in text:
            sections.append('resolutions')
        
        # count numbered items
        item_matches = re.findall(r'^\d+\.$', text, re.MULTILINE)
        item_count = len(item_matches)
        
        if sections:
            section_text = ', '.join(sections)
            return f"Meeting includes {section_text}. {item_count} items total."
        elif item_count > 0:
            return f"Meeting has {item_count} agenda items."
        else:
            return "Full agenda available at link above."
    
    def _extract_legislation_from_text(self, text: str) -> list[dict]:
        """extract ordinances and resolutions from agenda text."""
        legislation = []
        lines = text.split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # look for ORD. or RES. markers
            if re.match(r'^(ORD\.|RES\.)\s*$', line):
                leg_type = 'Ordinance' if line.startswith('ORD') else 'Resolution'
                leg_id = None
                description = []
                
                # next line should be the ID
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if re.match(r'^\d{4}-[A-Z]?\d+$', next_line):
                        leg_id = next_line
                        i += 2  # skip ID line
                    else:
                        i += 1
                else:
                    i += 1
                
                # gather description lines
                while i < len(lines) and len(description) < 5:
                    desc_line = lines[i].strip()
                    
                    # stop at next item marker
                    if re.match(r'^(ORD\.|RES\.|\d+\.|Patrons:|Attachments:|Legislative History)', desc_line):
                        break
                    
                    # stop at date lines (legislative history)
                    if re.match(r'^\d{1,2}/\d{1,2}/\d{2}', desc_line):
                        break
                    
                    if desc_line and len(desc_line) > 10:
                        description.append(desc_line)
                    
                    i += 1
                
                # format description
                if description:
                    desc_text = ' '.join(description[:2])  # first 2 lines usually sufficient
                    desc_text = re.sub(r'\s+', ' ', desc_text).strip()
                    if len(desc_text) > 150:
                        desc_text = desc_text[:147] + '...'
                    
                    legislation.append({
                        'type': leg_type,
                        'id': leg_id or '?',
                        'description': desc_text
                    })
            else:
                i += 1
        
        return legislation
    
    def _get_legislation_summary(self) -> str:
        """get quick legislation summary from cached meetings (synchronous)."""
        # only process if we have recent meetings with agendas
        meetings_with_agendas = [m for m in self._recent_meetings[:3] if m.get('has_agenda')]
        if not meetings_with_agendas:
            return ""
        
        # quick count from meeting data
        ordinance_count = 0
        resolution_count = 0
        
        # we'll count from the most recent meeting only to keep it fast
        # full legislation list available via separate query
        latest = meetings_with_agendas[0]
        
        return f"**Pending Legislation:** Say 'richmond legislation' for details on active ordinances and resolutions"
    
    async def fetch_legislation(self) -> str:
        """fetch and summarize pending legislation from recent meeting agendas."""
        # use recent meetings cache if available
        if not self._recent_meetings:
            # trigger a meeting fetch
            await self.fetch_updates()
        
        # collect legislation from all recent meetings
        all_legislation = []
        seen_ids = set()
        
        for meeting in self._recent_meetings[:5]:  # check last 5 meetings
            if not meeting.get('has_agenda'):
                continue
            
            agenda_url = meeting.get('agenda_url')
            if not agenda_url:
                continue
            
            try:
                resp = self._http_get(agenda_url, timeout=15)
                if resp.status_code != 200:
                    continue
                
                # extract text
                pdf_text = None
                if HAS_PDFTOTEXT:
                    try:
                        result = subprocess.run(
                            ['pdftotext', '-', '-'],
                            input=resp.content,
                            capture_output=True,
                            timeout=10
                        )
                        if result.returncode == 0:
                            pdf_text = result.stdout.decode('utf-8', errors='ignore')
                    except Exception:
                        pass
                
                if pdf_text:
                    items = self._extract_legislation_from_text(pdf_text)
                    for item in items:
                        item_id = item['id']
                        if item_id not in seen_ids:
                            seen_ids.add(item_id)
                            all_legislation.append(item)
            
            except Exception:
                continue
        
        # cache for later reference
        self._recent_legislation = all_legislation
        
        # format output
        if not all_legislation:
            return "### Richmond City Legislation\n- No pending ordinances or resolutions found in recent agendas."
        
        lines = ["### Richmond City Legislation"]
        lines.append(f"\n{len(all_legislation)} pending items from recent meeting agendas:\n")
        
        # group by type
        ordinances = [l for l in all_legislation if l['type'] == 'Ordinance']
        resolutions = [l for l in all_legislation if l['type'] == 'Resolution']
        
        if ordinances:
            lines.append(f"**Ordinances ({len(ordinances)}):**")
            for leg in ordinances[:10]:
                lines.append(f"- **ORD. {leg['id']}** — {leg['description']}")
        
        if resolutions:
            lines.append(f"\n**Resolutions ({len(resolutions)}):**")
            for leg in resolutions[:10]:
                lines.append(f"- **RES. {leg['id']}** — {leg['description']}")
        
        total = len(ordinances) + len(resolutions)
        if total > 20:
            lines.append(f"\n*Showing 20 of {total} items. Check recent meeting agendas for complete list.*")
        
        return '\n'.join(lines)
