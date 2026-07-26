# Town Hall — Civic Morning Briefing

A voice-activated civic watchdog for Richmond, VA and the Virginia General Assembly. Ask your agent for a morning briefing and get a spoken summary of upcoming City Council meetings and active state legislation, filtered for housing, education, and zoning topics.

## Trigger Words

| Phrase | What it does |
| --- | --- |
| "town hall" | starts the briefing flow |
| "morning briefing" | starts the briefing flow |
| "city hall" | starts the briefing flow |

## What It Does

- **Morning briefing** — speaks a 4–6 sentence summary of upcoming Richmond City Council meetings and relevant Virginia General Assembly bills.
- **Background refresh** — a watchdog loop warms the briefing cache on startup and refreshes it every hour so responses are instant.
- **Cached context** — writes `townhall_briefing.md` into the agent's context so the briefing is always available even if live sources are slow.
- **Gap logging** — logs unanswered civic questions to `knowledge_gaps.json` in the ability directory for future iteration.

## Data Sources

| Source | URL | Auth required |
| --- | --- | --- |
| Richmond City Council calendar | `richmondva.legistar.com` | none |
| Virginia General Assembly bills (CSV) | `lis.blob.core.windows.net` | none |
| Virginia LIS API (enrichment) | `lis.virginia.gov` | optional (see below) |

The ability works without any API key — it falls back to the public hourly CSV from the LIS blob storage. The LIS API key is optional and only used if the CSV fetch returns nothing.

## Setup

### 1. Trigger words

Set at least one of the trigger words above in the Dashboard when you install the ability.

### 2. LIS API key (optional)

To enable the Virginia LIS REST API as a fallback when the public CSV is unavailable:

1. Register for a free developer key at [lis.virginia.gov/developers](https://lis.virginia.gov/developers).
2. In the OpenHome Dashboard, go to **Settings → Third-Party Keys** and add a new key:
   - **Label:** `LIS_API_KEY`
   - **Value:** your key (format: `XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX`)

The ability will log `LIS_API_KEY resolved successfully` on startup when the key is found, or a warning with setup instructions if it is missing.

## Usage Examples

- *"Hey OpenHome, town hall."*
- *"Give me my morning briefing."*
- *"What's happening at city hall?"*

## Developer Notes

- **Sources** are modular — each lives in `sources/` and implements `CivicSource`. Adding a new government data source means adding one file there and registering it in `sources/__init__.py`.
- **Watchdog loop** starts on `call()`, refreshes every 3600 seconds, and writes to `townhall_briefing.md`.
- **API errors** — a 401/403 from the LIS API surfaces as a clear spoken error with the key label to look up. Check agent logs for `LIS_API_KEY` messages.
- **Knowledge gaps** — logged to `knowledge_gaps.json` when the agent can't answer a civic question. Review this file to guide future source additions.
- **No `print()` calls** — all logging uses `self.worker.editor_logging_handler`.
