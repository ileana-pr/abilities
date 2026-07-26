# Town Hall — Voice Civic Briefing Platform

A voice-activated civic briefing ability for OpenHome. Ask your agent what's happening in local and state government and get a spoken summary of upcoming meetings, active legislation, and public agendas — pulled live from official government sources.

**Town Hall is designed to be extended.** Virginia and Richmond, VA are the reference implementations. The architecture is built so any developer can add a source for their city, county, state, or federal body by implementing a single Python class.

---

## Trigger Words

| Phrase | What it does |
| --- | --- |
| `"town hall"` | starts the civic briefing flow |
| `"morning briefing"` | starts the civic briefing flow |
| `"city hall"` | starts the civic briefing flow |

---

## Current Sources

| Source | Level | Auth |
| --- | --- | --- |
| Virginia General Assembly (LIS) | State | none (CSV) / optional API key |
| Richmond City Council (Legistar) | City | none |

### Planned Sources

| Source | Level | Status |
| --- | --- | --- |
| U.S. Congress (congress.gov API) | Federal | planned |
| Richmond, VA (expanded) | City | planned |

> Want to add your city, county, or state? See [Contributing a Source](#contributing-a-source) below.

---

## Setup

### 1. Trigger words

Set at least one of the trigger phrases listed above in the Dashboard when you install the ability.

### 2. LIS API key (optional — Virginia only)

The Virginia source works without a key using the public LIS CSV feed. For API access as a fallback:

1. Register for a free key at [lis.virginia.gov/developers](https://lis.virginia.gov/developers).
2. In the OpenHome Dashboard, go to **Settings → Third-Party Keys** and add:
   - **Label:** `LIS_API_KEY`
   - **Value:** your key (`XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX`)

The ability logs `LIS_API_KEY resolved successfully` on startup if the key is found. If it's missing, a warning tells you the exact label to use.

---

## Usage Examples

- *"Hey OpenHome, town hall."*
- *"Give me my morning briefing."*
- *"What's happening at city hall?"*
- *"What bills are moving in the General Assembly?"*

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

HTTP helpers (`_http_get`, `_http_post`) are available on the base class — no extra dependencies needed.

### Watchdog loop

On startup, Town Hall warms the briefing cache immediately, then refreshes every hour. Briefings are written to `townhall_briefing.md` in the agent's context directory so responses are instant even when sources are slow.

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
           resp = await self._http_get(self.get_source_url())
           # parse resp.text, return a markdown string
           return "### Your City Council\n- ..."
   ```

3. Register it in `sources/__init__.py`:
   ```python
   from .your_source import YourCitySource

   def discover_sources():
       return [
           RichmondCitySource(),
           VirginiaStateSource(),
           YourCitySource(),   # add here
       ]
   ```

4. If your source needs an API key, follow the same pattern as `virginia_state.py` — accept the key via `set_api_key()` and document the label name in your source's docstring and in this README.

5. Open a PR against `dev` on `openhome-dev/abilities`. See the [contribution guide](https://docs.openhome.com/community/contributing) for the full checklist.

### Source guidelines

- Return a markdown string from `fetch_updates()` — the agent's LLM converts it to speech.
- Keep the output concise: 5–10 bullet points max. This is a voice briefing, not a report.
- Use `self._http_get()` for all HTTP calls — do not use `requests`, `httpx`, or `aiohttp` directly.
- Surface errors as strings in the return value (e.g. `"Error fetching ... HTTP 403"`) rather than raising — the briefing aggregator will include them so the agent can report and debug.
- No `print()` — use `self._worker.editor_logging_handler.info(...)` for logs.
- No hardcoded API keys — use placeholders and document the key label in the README.

---

## Developer Notes

- **Adding a federal source** — U.S. Congress data is available via the [congress.gov API](https://api.congress.gov/) (free key). A `FederalCongressSource` following the same pattern is on the roadmap.
- **Adding more city sources** — Legistar (used for Richmond) powers hundreds of city council sites. A generic `LegistarCitySource` that accepts a city subdomain would cover many U.S. cities at once.
- **Knowledge gaps** — unanswered civic questions are logged to `knowledge_gaps.json` in the ability directory. Review this to prioritize which sources to add next.
