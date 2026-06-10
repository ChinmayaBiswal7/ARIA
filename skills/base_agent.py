from typing import Dict, Any

class BaseAgent:
    def __init__(self, agent_name: str, aria_instance):
        self.agent_name = agent_name
        self.aria = aria_instance

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        """Core execution method. Must be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement run()")

    def log_state_shift(self, status: str, details: str = ""):
        """Logs status shifts to database status boards and console output."""
        try:
            from skills.agent_status import update_agent_status
            update_agent_status(self.agent_name, status, details)
        except Exception as e:
            print(f"[{self.agent_name}] Failed to update agent status db: {e}")
        print(f"[{self.agent_name}] Status: {status} | {details}")
