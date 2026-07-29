# Town Hall — Voice Civic Briefing Platform

A voice-activated civic briefing ability for OpenHome. Ask your agent what's happening in local and state government and get a spoken summary of upcoming meetings, active legislation, and public agendas — pulled live from official government sources.

**Town Hall is designed to be extended.** Virginia and Richmond, VA are the reference implementations. The architecture is built so any developer can add a source for their city, county, state, or federal body by implementing a single Python class.

---

## Trigger Words

| Phrase | What it does |
| --- | --- |
| `"virginia state"` | goes straight to the Virginia General Assembly briefing |
| `"state of virginia"` | goes straight to the Virginia General Assembly briefing |
| `"virginia legislature"` | goes straight to the Virginia General Assembly briefing |
| `"richmond city"` | goes straight to the Richmond City Council briefing |
| `"richmond city council"` | goes straight to the Richmond City Council briefing |
| `"richmond legislation"` | fetches pending Richmond ordinances and resolutions |
| `"town hall"` | asks which briefing you want, then delivers it |
| `"configure topics"` | opens interactive topic preference configuration |
| `"set topics"` | opens interactive topic preference configuration |

Naming a jurisdiction in the trigger skips straight to that briefing — no confirmation step. The generic `"town hall"` trigger is the only one that asks a follow-up question. Topic configuration triggers allow you to set meeting preferences (housing, zoning, transportation, etc.).

---

## Current Sources

| Source | Level | Auth |
| --- | --- | --- |
| Virginia General Assembly (LIS) | State | `LIS_API_KEY` required |
| Richmond City Council (Legistar) | City | none |

### Planned Sources

| Source | Level | Status |
| --- | --- | --- |
| U.S. Congress (congress.gov API) | Federal | planned |
| Richmond, VA (expanded) | City | planned |

> Want to add your city, county, or state? See [Contributing a Source](#contributing-a-source) below.

---

## Setup

### Cloud Mode vs. Local Mode

Town Hall supports two operating modes:

**Cloud Mode** (`OPENHOME_CLOUD_MODE=1`):
- Basic meeting listings with dates, times, and links
- No PDF parsing or legislation tracking
- Works on OpenHome cloud platform (restricted environment)
- No external dependencies required

**Local Mode** (default):
- Full PDF parsing of agendas and minutes
- Richmond legislation tracking with natural language search
- Detailed agenda item extraction
- Requires `pdftotext` system utility

### 1. Install dependencies

For **local mode** with full features, install the `pdftotext` utility:

```bash
cd community/town-hall
pip install -r requirements.txt
```

Required packages:
- `pypdf>=4.0.0` - for parsing PDF agenda documents
- `requests>=2.31.0` - for HTTP requests

### 2. Trigger words

Set at least one of the trigger phrases listed above in the Dashboard when you install the ability.

### 3. LIS API key (required for the Virginia source)

The Virginia General Assembly source reads from the LIS REST API and will report an error without a key:

1. Register for a free key at [lis.virginia.gov/developers](https://lis.virginia.gov/developers).
2. In the OpenHome Dashboard, go to **Settings → Third-Party Keys** and add:
   - **Label:** `LIS_API_KEY`
   - **Value:** your key (`XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX`)

The ability logs `LIS_API_KEY resolved successfully` on startup if the key is found. If it's missing, a warning tells you the exact label to use.

---

## Usage Examples

- *"Hey OpenHome, virginia state."* → Virginia bills, immediately
- *"State of Virginia."* → Virginia bills, immediately
- *"Virginia legislature."* → Virginia bills, immediately
- *"Richmond city."* → Richmond meetings, immediately
- *"Richmond city council."* → Richmond meetings, immediately
- *"Town hall."* → *"Which briefing would you like — Virginia General Assembly or Richmond City Council?"*
- *"Configure topics."* → Interactive topic preference setup for meeting prioritization
- *"Richmond legislation."* → Fetches and summarizes pending ordinances and resolutions
- *"Get details on meeting 1."* → Fetches and summarizes specific meeting agenda
- *"Get details on ORD. 2026-093."* → Looks up specific ordinance by ID
- *"Tell me about housing bonds."* → Searches legislation by keywords
- *"What's the zoning ordinance?"* → Finds zoning-related legislation
- *"Tell me about City Council."* → Finds and details the next City Council meeting

---

## How It Works

### Scenario 1: Direct Trigger with Keyword

**User says:** *"Richmond city"*

**What happens:**

1. **Trigger routing** — The word "richmond" in your phrase routes directly to the Richmond City Council source
2. **Fetch live data** — Richmond source makes HTTP GET to `richmondva.legistar.com/Calendar.aspx`
3. **Parse HTML** — Extracts upcoming meeting IDs and agenda availability using regex
4. **Format briefing** — Builds markdown with 5 upcoming meetings, each showing meeting ID and agenda status
5. **Cache the result** — Writes `townhall_briefing.md` to context directory for instant future access
6. **LLM summarization** — The agent's LLM converts markdown to 4-6 natural spoken sentences
7. **Speak the briefing** — Agent reads the summary aloud

**Example spoken output:**
> "There are 8 upcoming meetings this week. The City Council meets Monday, July 27 at 6:00 PM. The Commission of Architectural Review meets Tuesday, July 28 at 3:30 PM. The Public Safety Standing Committee meets Tuesday, July 28 at 1:00 PM. Say details on meeting 1 or tell me about City Council to learn more."

**Behind the scenes:**
```
User: "richmond city"
  ↓
Trigger matched → sources filtered by keyword "richmond"
  ↓
RichmondCitySource.fetch_updates()
  ↓
HTTP GET https://richmondva.legistar.com/Calendar.aspx
  ↓
Parse: 8 meetings found in next 7 days
  ↓
Return markdown:
  ### Richmond City Council
  
  8 upcoming meetings this week:
  1. **City Council** - Monday, July 27 at 6:00 PM
  2. **Commission of Architectural Review** - Tuesday, July 28 at 3:30 PM
  3. **Public Safety Standing Committee** - Tuesday, July 28 at 1:00 PM
  ...
  
  Say 'details on meeting [number]' or 'tell me about [body name]'
  ↓
Cache → townhall_briefing.md
  ↓
LLM summarizes → natural speech
  ↓
Agent speaks summary
```

---

### Scenario 2: Direct Trigger for Virginia (with API Key)

**User says:** *"Virginia state"*

**What happens:**

1. **Trigger routing** — The word "virginia" routes to Virginia General Assembly source
2. **API key check** — Verifies `LIS_API_KEY` is set in third-party keys
3. **Fetch session list** — HTTP GET to `lis.virginia.gov/Session/api/getsessionlistasync`
4. **Pick current session** — Ranks sessions by active status, regular vs special, and year; chooses 2026 Regular Session
5. **Fetch legislation** — HTTP GET to legislation list API for chosen session
6. **Filter and score** — Prioritizes bills matching focus topics (housing, education, zoning), limits to 8 bills
7. **Format briefing** — Each bill shows number, description (max 160 chars), status, and patron
8. **Cache and summarize** — Same as Richmond (cache → LLM → speech)

**Example spoken output:**
> "The Virginia General Assembly has eight active bills from the 2026 Regular Session. House Bill 1234 on affordable housing is in committee. Senate Bill 567 on school funding passed the Senate. House Bill 890 on zoning reform is awaiting a vote..."

**Behind the scenes:**
```
User: "virginia state"
  ↓
Trigger matched → sources filtered by keyword "virginia"
  ↓
VirginiaStateSource.fetch_updates()
  ↓
Check self._api_key → "XXXXXXXX-XXXX-..." (set)
  ↓
HTTP GET lis.virginia.gov/Session/api/getsessionlistasync
  ↓
Rank sessions → 20261 (2026 Regular Session) chosen
  ↓
HTTP GET legislation list for session 20261
  ↓
Filter: 3 bills match focus topics, 5 other bills added → 8 total
  ↓
Return markdown with bill details
  ↓
Cache → townhall_briefing.md
  ↓
LLM summarizes → natural speech
  ↓
Agent speaks summary
```

---

### Scenario 3: Generic Trigger (No Keyword)

**User says:** *"Town hall"*

**What happens:**

1. **No keyword match** — The phrase "town hall" contains neither "virginia" nor "richmond"
2. **Ask which source** — Agent speaks: *"Which briefing would you like — Virginia General Assembly or Richmond City Council?"*
3. **User responds** — User says: *"Richmond"*
4. **Route and fetch** — Same flow as Scenario 1 from step 2 onward

**Example conversation:**
> **User:** "Town hall"  
> **Agent:** "Which briefing would you like — Virginia General Assembly or Richmond City Council?"  
> **User:** "Give me Richmond."  
> **Agent:** "Pulling the latest from Richmond City Council. The Richmond City Council has five upcoming meetings..."

---

### Scenario 4: Missing API Key (Virginia)

**User says:** *"Virginia state"*

**What happens if `LIS_API_KEY` is not set:**

1. **Trigger routing** — Routes to Virginia source as normal
2. **API key check fails** — `self._api_key` is `None`
3. **Return error message** — Virginia source returns helpful markdown error instead of crashing
4. **Agent speaks error** — LLM converts to natural speech

**Example spoken output:**
> "The Virginia General Assembly source is unavailable. The LIS API key is not set. You'll need to add a third-party key named LIS_API_KEY in Settings under Third-Party Keys."

**The error in markdown:**
```markdown
### Virginia General Assembly
- Error: LIS_API_KEY not set. Add a third-party key named 'LIS_API_KEY' in Settings → Third-Party Keys.
```

No crash, no stack trace — just a clear, actionable error message the agent can speak naturally.

---

### Scenario 5: Setting Topic Preferences

**User says:** *"Configure topics"*

**What happens:**

1. **Trigger routing** — The phrase "configure topics" routes to topic configuration flow
2. **Ask for topics** — Agent speaks: *"What topics are you interested in for Richmond City Council? You can say housing, zoning, transportation, education, public safety, or budget. Say multiple topics separated by 'and'."*
3. **User responds** — User says: *"Housing and zoning"*
4. **Save preferences** — Topic preferences stored in `topic_preferences.json`
5. **Apply to source** — Richmond source will prioritize meetings matching housing/zoning keywords
6. **Confirm** — Agent speaks: *"Got it. I'll prioritize housing, zoning meetings for Richmond City Council."*

**Example conversation:**
> **User:** "Configure topics"  
> **Agent:** "What topics are you interested in for Richmond City Council? You can say housing, zoning, transportation, education, public safety, or budget. Say multiple topics separated by 'and'."  
> **User:** "Housing and zoning"  
> **Agent:** "Got it. I'll prioritize housing, zoning meetings for Richmond City Council."

**How prioritization works:**

When you set topic preferences, future Richmond briefings will:
- Show meetings matching your topics first (e.g., Planning Commission, Housing Authority)
- Then show other meetings (e.g., City Council, Finance Committee)
- Still display all meetings, just reordered by relevance

**Topic keywords:**
- `housing`: housing, affordable housing, residential, development
- `zoning`: zoning, planning, land use, rezoning
- `transportation`: transportation, transit, traffic, road, parking
- `education`: school, education, schools
- `public safety`: police, fire, safety, emergency
- `budget`: budget, finance, appropriation

---

### Scenario 6: Getting Meeting Details

**User says (after getting briefing):** *"Get details on meeting 1"* or *"Tell me about City Council"*

**What happens:**

1. **Parse reference** — Agent extracts meeting reference (number, name, or ID)
2. **Route to source** — Main capability routes request to Richmond source's `get_details()` method
3. **Fetch agenda/minutes** — Richmond source downloads PDF document from Legistar
4. **Parse PDF content** — Extracts agenda items using pypdf library
5. **Format response** — Returns structured markdown with meeting info and agenda items
6. **Speak summary** — Agent summarizes the agenda items naturally

**Example conversation:**
> **User:** "Richmond city"  
> **Agent:** "There are 8 upcoming meetings this week. The City Council meets Monday, July 27 at 6:00 PM. The Commission of Architectural Review meets Tuesday, July 28 at 3:30 PM..."  
> **User:** "Get details on meeting 1"  
> **Agent:** "The City Council meeting on Monday, July 27 has 12 agenda items including approval of previous minutes, public comment period, zoning amendments for the West End district, budget appropriations for public safety..."

**What gets extracted:**

Richmond's Legistar system provides PDFs with agenda items. The capability:
- Downloads the PDF (typically 50-500KB)
- Extracts text from first 5 pages
- Identifies numbered agenda items (1., 2., 3... or A., B., C... or I., II., III...)
- Cleans and formats each item (max 150 chars)
- Returns up to 15 items in the spoken briefing

**Multiple reference formats supported:**
- By number: `"details on meeting 1"`, `"meeting 3"`
- By body name: `"tell me about City Council"`, `"Planning Commission meeting"`
- By meeting ID: `"get details for 1354765"` (from previous briefings)

**Fallback behavior:**

If PDF parsing fails or pypdf is not installed:
- Returns meeting metadata (date, time, location, document size)
- Provides direct link to PDF on Legistar site
- User can still access full document via browser

---

### Scenario 7: Richmond Legislation Tracking

**User says:** *"Richmond legislation"*

**What happens:**

1. **Fetch recent agendas** — Downloads PDFs from last 5 meetings
2. **Extract legislation** — Parses ordinances (ORD.) and resolutions (RES.) from agenda text
3. **Deduplicate** — Tracks by ID to avoid showing same item multiple times
4. **Format by type** — Groups ordinances and resolutions separately
5. **Summarize** — LLM creates natural summary of pending items

**Example conversation:**
> **User:** "Richmond legislation"  
> **Agent:** "Richmond City has 35 pending items. There are 28 ordinances including special use authorizations for residential developments, right-of-way closures, and zoning amendments. There are 7 resolutions including housing bond approvals and budget appropriations..."

**What gets tracked:**

From actual meeting agendas:
- **Ordinances (ORD.)**: Land use, zoning, code amendments, special use permits
- **Resolutions (RES.)**: Bond approvals, appointments, policy statements

**Example items:**
```
ORD. 2026-093 — To authorize the special use of the property known as 
                3317 Rear Monument Avenue for up to four single-family 
                attached dwellings

RES. 2026-R030 — To approve the issuance by the Richmond Redevelopment 
                 and Housing Authority of multifamily housing revenue bonds

ORD. 2026-120 — To authorize the special use of the properties on South 
                Meadow Street for a mixed-use development
```

**Looking up specific legislation:**

Users can query by ID or search by topic:

**By ID:**
- `"Get details on ORD. 2026-093"`
- `"Tell me about RES. 2026-R030"`
- `"Details for ordinance 2026-120"`

**By Topic/Keywords:**
- `"Tell me about housing bonds"` → Finds housing authority bond resolution
- `"What's the zoning ordinance"` → Finds zoning-related ordinances
- `"Monument Avenue"` → Finds ordinances for that address
- `"Special use permits"` → Lists all special use ordinances
- `"Affordable housing"` → Finds housing trust fund ordinance

The search looks for keywords in ordinance descriptions and returns:
- Single match → Full details
- Multiple matches → Numbered list (say the ORD number for details)
- No matches → Falls back to meeting search

**Why this approach:**

Rather than scraping a separate legislation API (which requires complex AJAX handling), we extract legislation from meeting agendas we're already parsing. This gives us:
- **Active legislation**: Only items currently on meeting agendas (actually being discussed)
- **No additional API**: Reuses existing Legistar calendar integration
- **Context**: Legislation appears with meeting info (when it will be voted on)
- **Performance**: Already have the data from meeting briefings

---

### Caching and Watchdog Loop

**Background process (runs automatically on startup):**

1. **Warm cache immediately** — 3 seconds after the ability loads, fetch all sources once
2. **Refresh daily** — Every 24 hours, re-fetch all sources and update `townhall_briefing.md`
3. **Cache validation** — Before serving a cached briefing, each source validates its section isn't all error messages

**Why cache?**
- Government APIs can be slow (1–3 seconds per call)
- Voice interactions need instant responses
- Briefings are time-insensitive (hourly changes are fine)

**Cache invalidation:**
- If a source's cached section contains only error lines, it's considered invalid
- Invalid cache → fresh fetch is triggered
- Otherwise, cached briefing is served immediately

---

## Architecture

Town Hall is built around a `CivicSource` base class. Each source is an independent module that knows how to fetch and format updates from one government body. The core ability just loops over registered sources and aggregates their output.

```
community/town-hall/
├── main.py                  # ability entry point, watchdog loop, LIS key resolution
├── sources/
│   ├── base.py              # CivicSource abstract base class — start here to contribute
│   ├── __init__.py          # register your source here (discover_sources)
│   ├── virginia_state.py    # reference: Virginia General Assembly (state legislature)
│   └── richmond_va.py       # reference: Richmond City Council (Legistar)
└── README.md
```

### CivicSource interface

```python
class CivicSource(ABC):
    def get_name(self) -> str: ...           # display name, e.g. "Virginia General Assembly"
    def get_source_url(self) -> str: ...     # canonical URL for the data source
    async def fetch_updates(self) -> str:    # returns a markdown-formatted briefing string
        ...
    async def search(self, query: str) -> str: ...     # optional
    async def get_details(self, item_id: str) -> str:  # optional
```

HTTP helpers (`_http_get`, `_http_post`) are available on the base class using the standard `requests` library.

### Watchdog loop

On startup, Town Hall warms the briefing cache immediately, then refreshes daily. Briefings are written to `townhall_briefing.md` in the agent's context directory so responses are instant even when sources are slow.

---

## Contributing a Source

We welcome sources for any city, county, state, or federal body. The pattern is the same regardless of jurisdiction.

### Steps

1. Fork this repo and branch off `dev`:
   ```bash
   git checkout -b add-your-source-name dev
   ```

2. Create `sources/your_source.py` and subclass `CivicSource`:
   ```python
   from .base import CivicSource

   class YourCitySource(CivicSource):
       def get_name(self) -> str:
           return "Your City Council"

       def get_source_url(self) -> str:
           return "https://yourcity.gov/calendar"

       async def fetch_updates(self) -> str:
           # http calls are synchronous, but fetch_updates must stay async
           resp = self._http_get(self.get_source_url())
           # parse resp.text, return a markdown string
           return "### Your City Council\n- ..."
   ```

3. Auto-discovery handles registration — just add your file to `sources/` and it will be found automatically. No registration needed!

4. If your source needs an API key, follow the same pattern as `virginia_state.py` — accept the key via `set_api_key()` and document the label name in your source's docstring and in this README.

5. Open a PR against `dev` on `openhome-dev/abilities`. See the [contribution guide](https://docs.openhome.com/community/contributing) for the full checklist.

### Source guidelines

- Return a markdown string from `fetch_updates()` — the agent's LLM converts it to speech.
- Keep the output concise: 5–10 bullet points max. This is a voice briefing, not a report.
- Use `self._http_get()` for all HTTP calls — the base class uses `requests` internally, so you get standard Response objects.
- Surface errors as strings in the return value (e.g. `"Error fetching ... HTTP 403"`) rather than raising — the briefing aggregator will include them so the agent can report and debug.
- No `print()` — logging is available via the platform when needed.
- No hardcoded API keys — use placeholders and document the key label in the README.

---

## Developer Notes

- **Adding a federal source** — U.S. Congress data is available via the [congress.gov API](https://api.congress.gov/) (free key). A `FederalCongressSource` following the same pattern is on the roadmap.
- **Adding more city sources** — Legistar (used for Richmond) powers hundreds of city council sites. A generic `LegistarCitySource` that accepts a city subdomain would cover many U.S. cities at once.
- **Knowledge gaps** — when a source returns no usable data, it is logged to `knowledge_gaps.json` in the ability directory. Review this to see which jurisdictions are failing and prioritize fixes.
