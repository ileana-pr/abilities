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
| `"remove topics"` | remove specific topics (or clear all) from preferences |
| `"delete topics"` | same as remove topics |
| `"clear topics"` | same as remove topics |

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

### 1. Dependencies

None. All data comes from public web APIs over plain HTTP using the OpenHome SDK — no external Python packages or system utilities required. The ability runs identically on the OpenHome cloud platform and in local development.

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
- *"Town hall."* → *"Which briefing would you like?"* (user names a jurisdiction)
- *"Configure topics."* → Interactive free-form topic preference setup
- *"Remove topics."* → Remove mistaken topics (or clear all)
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
2. **Fetch live data** — Richmond source queries the Legistar Web API (`webapi.legistar.com/v1/richmondva/events`) for meetings in a window from 3 days back to 14 days ahead
3. **Format briefing** — Builds markdown with numbered upcoming meetings, each showing date, time, and agenda status
4. **Cache the result** — Writes `townhall_briefing.md` to context directory for instant future access
5. **LLM summarization** — The agent's LLM converts markdown to 4-6 natural spoken sentences
6. **Speak the briefing** — Agent reads the summary aloud
7. **Follow-up loop** — Agent asks whether you want meeting details, recent legislation, or something else (up to 3 turns), then exits when you say you're done

**Example spoken output:**
> "There are 8 upcoming meetings this week. The City Council meets Monday, July 27 at 6:00 PM. The Commission of Architectural Review meets Tuesday, July 28 at 3:30 PM. The Public Safety Standing Committee meets Tuesday, July 28 at 1:00 PM."  
> **Agent:** "Want details on a meeting, recent legislation, or something else from that briefing? Or say you're done."  
> **User:** "Any new legislation?"  
> **Agent:** *(topic-prioritized ordinances/resolutions summary)*  
> **User:** "Details on meeting 1"  
> **Agent:** *(City Council agenda highlights)*  
> **User:** "I'm done."  
> **Agent:** "Okay."

**Behind the scenes:**
```
User: "richmond city"
  ↓
Trigger matched → sources filtered by keyword "richmond"
  ↓
RichmondCitySource.fetch_updates()
  ↓
HTTP GET https://webapi.legistar.com/v1/richmondva/events (JSON)
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
  ↓
Follow-up loop (legislation / meeting details / briefing Q&A) → done
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
6. **Filter and score** — Prioritizes bills matching the user's topic preferences (falls back to housing/education/zoning), limits to 8 bills
7. **Format briefing** — Each bill shows number, description (max 160 chars), status, and patron
8. **Cache and summarize** — Same as Richmond (cache → LLM → speech)
9. **Follow-up loop** — Same post-briefing invitation as Richmond: ask about a bill/topic from the briefing, or say you're done. (Virginia's briefing *is* legislation, so asking for "legislation" re-highlights bills from that briefing.)

**Example spoken output:**
> "The Virginia General Assembly has eight active bills from the 2026 Regular Session. House Bill 1234 on affordable housing is in committee. Senate Bill 567 on school funding passed the Senate. House Bill 890 on zoning reform is awaiting a vote..."  
> **Agent:** "Want details on a meeting, recent legislation, or something else from that briefing? Or say you're done."  
> **User:** "Anything on housing?"  
> **Agent:** *(answers from the briefing text)*  
> **User:** "Done."

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

1. **No keyword match** — The phrase "town hall" doesn't name any jurisdiction's trigger keywords
2. **Ask** — Agent speaks: *"Which briefing would you like?"* (no long menu of sources)
3. **User responds** — User names a jurisdiction, e.g. *"Richmond"* or *"Virginia"*
4. **Route and fetch** — If a matching source exists, same flow as Scenario 1; if not, a graceful "I don't have a briefing for that yet" message

**Example conversation:**
> **User:** "Town hall"  
> **Agent:** "Which briefing would you like?"  
> **User:** "Richmond."  
> **Agent:** "Pulling the latest from Richmond City Council..."

**Unavailable source:**
> **User:** "Town hall"  
> **Agent:** "Which briefing would you like?"  
> **User:** "Norfolk."  
> **Agent:** "I don't have a briefing for that yet. Try naming a supported city, county, state, or federal source..."

Users are expected to know whether their locality is available. As new sources (including federal) ship, the same open-ended question works without changes to `main.py`.

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

1. **Topic config trigger** — Handled before jurisdiction routing (no need to name a city/state)
2. **Ask for topics** — Agent invites free-form interests (examples only: housing, zoning, parks, climate…). If topics already exist, it reads them back and asks what to **add**
3. **User responds** — e.g. *"Housing and parks and climate"*
4. **Parse freely** — Splits on "and"/commas; any phrase is accepted, not just a fixed catalog
5. **Append** — New topics are added to the existing user list (duplicates skipped); nothing is wiped
6. **Apply everywhere** — The full list is injected into every registered source that supports filtering
7. **Confirm** — Agent speaks which topics were added and the full prioritized list

**Example conversation:**
> **User:** "Configure topics"  
> **Agent:** "What topics are you interested in? You can name anything — for example housing, zoning, transportation, parks, or climate..."  
> **User:** "Housing and parks"  
> **Agent:** "Added housing, parks. I'll prioritize housing, parks across your civic briefings."  
> **User:** "Configure topics"  
> **Agent:** "Your current topics are housing, parks. What would you like to add?"  
> **User:** "Climate"  
> **Agent:** "Added climate. I'll prioritize housing, parks, climate across your civic briefings."

**How prioritization works:**

Topic preferences belong to the **user**, not a single locality. Known catalog topics (housing, zoning, etc.) expand to related keywords; free-form topics match on the phrase itself (and significant words). Richmond meetings, Virginia bills, and future sources all reuse the same list.

**Built-in keyword expansions** (optional boost for common topics):
- `housing`: housing, affordable housing, residential, development
- `zoning`: zoning, planning, land use, rezoning
- `transportation`: transportation, transit, traffic, road, parking
- `education`: school, education, schools
- `public safety`: police, fire, safety, emergency
- `budget`: budget, finance, appropriation

### Removing topics

**User says:** *"Remove topics"* (also `"delete topics"` / `"clear topics"`)

**What happens:**

1. Agent reads back the current list and asks which to remove
2. User names one or more topics (same free-form parsing as add), **or** says *"clear all"*
3. Matching items are dropped; the rest stay
4. Agent confirms what was removed and what's left

**Example:**
> **User:** "Remove topics"  
> **Agent:** "Your current topics are housing, parks, climate. Which should I remove? Say the topic names, or say clear all."  
> **User:** "Parks"  
> **Agent:** "Removed parks. I'll prioritize housing, climate across your civic briefings."

---

### Scenario 6: Getting Meeting Details

**User says (after getting briefing):** *"Get details on meeting 1"* or *"Tell me about City Council"*

**What happens:**

1. **Parse reference** — Agent extracts meeting reference (number, name, or ID)
2. **Route to source** — Main capability routes request to Richmond source's `get_details()` method
3. **Fetch agenda items** — Richmond source queries the Legistar Web API (`/events/{id}/eventitems`)
4. **Format response** — Returns structured markdown with meeting info and agenda items (legislation items first)
5. **Speak summary** — Agent summarizes the agenda items naturally

**Example conversation:**
> **User:** "Richmond city"  
> **Agent:** "There are 8 upcoming meetings this week. The City Council meets Monday, July 27 at 6:00 PM. The Commission of Architectural Review meets Tuesday, July 28 at 3:30 PM..."  
> **User:** "Get details on meeting 1"  
> **Agent:** "The City Council meeting on Monday, July 27 has 12 agenda items including approval of previous minutes, public comment period, zoning amendments for the West End district, budget appropriations for public safety..."

**What gets extracted:**

The Legistar Web API returns structured agenda items for each meeting. The capability:
- Fetches items via `GET /v1/richmondva/events/{EventId}/eventitems`
- Prefers items tied to legislation (ordinances/resolutions with file numbers) over procedural boilerplate
- Cleans and formats each item (max 150 chars)
- Returns up to 15 items in the spoken briefing

**Multiple reference formats supported:**
- By number: `"details on meeting 1"`, `"meeting 3"`
- By body name: `"tell me about City Council"`, `"Planning Commission meeting"`
- By meeting ID: `"get details for 5180"` (from previous briefings)

**Fallback behavior:**

If agenda items are not yet published for a meeting:
- Returns meeting metadata (date, time, location)
- Provides direct links to the agenda/minutes PDFs on Legistar when available

---

### Scenario 7: Richmond Legislation Tracking

**User says:** *"Richmond legislation"* (also works as an in-session follow-up after a Richmond meeting briefing: *"any new legislation?"*)

**What happens:**

1. **Query the Legistar Web API** — `GET /v1/richmondva/matters` filtered to ordinances and resolutions introduced in the last 60 days
2. **Sanity-check** — Skips API rows with dirty dates (a few historical records carry bad metadata)
3. **Topic priority** — If the user has topic preferences, matching items are listed first under a "Matching your topics" heading; remaining items follow
4. **Format by type** — When no topics are set, groups ordinances and resolutions separately, each with its current status
5. **Summarize** — LLM creates natural summary of pending items

**Example conversation:**
> **User:** "Richmond legislation"  
> **Agent:** "Richmond City has 35 pending items. There are 28 ordinances including special use authorizations for residential developments, right-of-way closures, and zoning amendments. There are 7 resolutions including housing bond approvals and budget appropriations..."

**What gets tracked:**

From the city's official legislative records:
- **Ordinances (ORD.)**: Land use, zoning, code amendments, special use permits
- **Resolutions (RES.)**: Bond approvals, appointments, policy statements
- **Status for each item**: Adopted, Consent Agenda, Regular Agenda, Withdrawn, etc.

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

Richmond runs on Legistar (by Granicus), which exposes an official public web API at `webapi.legistar.com/v1/richmondva/`. Using it instead of scraping HTML or parsing PDFs gives us:
- **Structured data**: File numbers, titles, statuses, and dates as clean JSON — no fragile parsing
- **Current status**: Each item reports where it stands (Adopted, Consent Agenda, Withdrawn...)
- **Cloud compatible**: Plain HTTP GET works within the OpenHome platform's module restrictions
- **Reusable pattern**: Hundreds of U.S. cities use Legistar — the same code works by swapping the client name in the URL

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
    # optional features — base class provides default stubs; override where available
    async def search(self, query: str) -> str: ...
    async def get_details(self, item_id: str) -> str: ...
    async def fetch_legislation(self) -> str: ...
    def set_topic_preferences(self, topics: list[str]) -> None: ...
    def get_topic_preferences(self) -> list[str]: ...
```

HTTP helpers (`_http_get`, `_http_post`) are available on the base class via the OpenHome SDK (`worker.session_tasks`). Call `bind_worker()` first (the coordinator does this automatically).

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

3. Register your source in `sources/__init__.py` by importing it and appending an instance to the list returned by `discover_sources()`. (OpenHome forbids dynamic imports, so registration is explicit.)

4. If your source needs an API key, follow the same pattern as `virginia_state.py` — accept the key via `set_api_key()` and document the label name in your source's docstring and in this README.

5. Open a PR against `dev` on `openhome-dev/abilities`. See the [contribution guide](https://docs.openhome.com/community/contributing) for the full checklist.

### Source guidelines

- Return a markdown string from `fetch_updates()` — the agent's LLM converts it to speech.
- Keep the output concise: 5–10 bullet points max. This is a voice briefing, not a report.
- Use `self._http_get()` for all HTTP calls — the base class routes through the OpenHome SDK (`worker.session_tasks`) and returns response-like objects with `.text` and `.status_code`.
- Surface errors as strings in the return value (e.g. `"Error fetching ... HTTP 403"`) rather than raising — the briefing aggregator will include them so the agent can report and debug.
- No `print()` — logging is available via the platform when needed.
- No hardcoded API keys — use placeholders and document the key label in the README.

---

## Developer Notes

- **Adding a federal source** — U.S. Congress data is available via the [congress.gov API](https://api.congress.gov/) (free key). A `FederalCongressSource` following the same pattern is on the roadmap.
- **Adding more city sources** — Legistar (used for Richmond) powers hundreds of city council sites. A generic `LegistarCitySource` that accepts a city subdomain would cover many U.S. cities at once.
- **Knowledge gaps** — when a source returns no usable data, it is logged to `knowledge_gaps.json` in the ability directory. Review this to see which jurisdictions are failing and prioritize fixes.
