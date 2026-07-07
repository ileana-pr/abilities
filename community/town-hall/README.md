# 🏛️ TownHall: Your Personal Civic Watchdog

TownHall revolutionizes civic engagement by automatically monitoring local and state government activity and providing you with a concise, voice-activated morning briefing.

## Features
- **Morning Briefing**: Get a summary of Richmond City Council agendas and Virginia General Assembly legislation.
- **Civic Watchdog**: A background daemon that periodically scrapes official government portals (Legistar, LIS) to keep your agent's knowledge fresh.
- **Engagement**: Draft professional emails to your representatives directly via voice.
- **Gap Analysis**: Automatically tracks questions it couldn't answer, helping you identify what local data needs to be added next.

## Setup
1. **Trigger Words**: Set triggers like "Town Hall," "Morning Briefing," or "What's happening at City Hall?"
2. **Location**: Currently pre-configured for **Richmond, VA** and the **Virginia State Legislature**.
3. **Data Sources**:
    - Richmond City Council: Scraped from `richmondva.legistar.com`.
    - Virginia State: Monitoring focus on current session bills.

## How to Use
- *"Hey OpenHome, give me my Town Hall briefing."*
- *"What is the City Council discussing today?"*
- *"Draft an email to my commissioner about the new zoning permit."*

## Developer Notes
- **Watchdog Loop**: The ability runs a background loop every hour to update `townhall_briefing.md`.
- **Context Injection**: Uses Openhome's Ambient Context Injection to ensure the Agent always has the latest meeting IDs and bill summaries in its system prompt.
- **Gaps**: Check `knowledge_gaps.json` in the ability directory to see what civic information users are asking for that isn't yet covered.
