import json
import asyncio
from datetime import datetime
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# Import the discovery helper
from .sources import discover_sources
from .sources.virginia_state import VirginiaStateSource

LIS_API_KEY_NAME = "lis_api_key"

class TownHallCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    
    # Auto-discover all sources in the sources/ directory
    SOURCES = discover_sources()

    #{{register capability}}

    def _inject_lis_api_key(self):
        """prefer openhome settings key; virginia source also falls back to LIS_API_KEY env."""
        key = None
        try:
            key = self.capability_worker.get_api_keys(LIS_API_KEY_NAME)
        except Exception:
            key = None
        if not key:
            return
        for source in self.SOURCES:
            if isinstance(source, VirginiaStateSource):
                source.set_api_key(key)

    async def log_gap(self, query: str, reason: str):
        """Logs queries the agent couldn't answer."""
        gap_data = {
            "query": query,
            "reason": reason,
            "timestamp": str(datetime.now())
        }
        await self.capability_worker.write_file(
            "knowledge_gaps.json", 
            json.dumps(gap_data) + "\n", 
            in_ability_directory=True
        )

    async def write_context_file(self, filename: str, content: str):
        """Safe write pattern for context files."""
        exists = await self.capability_worker.check_if_file_exists(filename, in_ability_directory=False)
        if exists:
            await self.capability_worker.delete_file(filename, in_ability_directory=False)
        await self.capability_worker.write_file(filename, content, in_ability_directory=False)

    async def watchdog_loop(self):
        """Core coordinator that iterates through all sources."""
        while True:
            try:
                self._inject_lis_api_key()
                aggregated_updates = [f"# TownHall Civic Briefing\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
                
                for source in self.SOURCES:
                    self.worker.editor_logging_handler.info(f"Polling source: {source.get_name()}")
                    updates = await source.fetch_updates()
                    aggregated_updates.append(updates)
                
                final_context = "\n\n---\n\n".join(aggregated_updates)
                await self.write_context_file("townhall_briefing.md", final_context)
                
            except Exception as e:
                self.worker.editor_logging_handler.error(f"TownHall Coordinator Error: {e}")
            
            # Poll every hour
            await self.worker.session_tasks.sleep(3600.0)

    async def run(self):
        """Voice interaction handling."""
        await self.capability_worker.speak("Town Hall is standing by. Would you like your morning briefing?")
        user_input = await self.capability_worker.user_response()
        
        if "briefing" in user_input.lower() or "yes" in user_input.lower():
            # Trigger summary based on aggregated context
            summary = self.capability_worker.text_to_text_response(
                "Summarize the aggregated civic data from the 'TownHall Civic Briefing' context. "
                "Focus on the most immediate meetings or bills."
            )
            await self.capability_worker.speak(summary)
            
            await self.capability_worker.speak("Would you like me to draft a message to any of these offices?")
            # ... action logic ...
        else:
            response = self.capability_worker.text_to_text_response(user_input)
            await self.capability_worker.speak(response)
            if "don't know" in response.lower():
                await self.log_gap(user_input, "Information not in modular sources.")

        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self._inject_lis_api_key()
        self.worker.session_tasks.create(self.watchdog_loop())
        self.worker.session_tasks.create(self.run())
