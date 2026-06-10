"""
skills/habit_dataset_monitor.py — Dataset Quality & Size Audit Agent for ARIA
=============================================================================
Scans the local data/habit_dataset/ session repository, analyzes historical density,
and checks readiness for neural network training using strict sample and duration gates.
"""

import os
import json
import glob
from typing import Dict, Any

from skills.base_agent import BaseAgent

class AriaHabitDatasetMonitor(BaseAgent):
    def __init__(self, aria_instance, dataset_dir: str = "data/habit_dataset"):
        super().__init__("HabitDatasetMonitorAgent", aria_instance)
        self.dataset_dir = dataset_dir
        self._ensure_directory_exists()

    def _ensure_directory_exists(self):
        if not os.path.exists(self.dataset_dir):
            os.makedirs(self.dataset_dir, exist_ok=True)

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        self.log_state_shift("RUNNING", "Auditing habit logging dataset metrics...")
        
        stats = self.compile_dataset_profile()
        
        # Enforce strict readiness gates for future P7 Neural training
        min_sessions = 100
        min_days = 14
        
        rec_sessions = 300
        rec_days = 21
        
        ideal_sessions = 500
        ideal_days = 42
        
        total_sessions = stats["total_sessions"]
        days_covered = stats["days_covered"]
        
        is_ready = (total_sessions >= min_sessions) and (days_covered >= min_days)
        is_recommended = (total_sessions >= rec_sessions) and (days_covered >= rec_days)
        is_ideal = (total_sessions >= ideal_sessions) and (days_covered >= ideal_days)
        
        status_msg = "COLLECTING_DATA"
        if is_ideal:
            status_msg = "IDEAL_READY"
        elif is_recommended:
            status_msg = "RECOMMENDED_READY"
        elif is_ready:
            status_msg = "MINIMUM_READY"
            
        stats["ready_for_neural_training"] = is_ready
        stats["training_status"] = status_msg
        stats["gates"] = {
            "minimum": {"sessions": min_sessions, "days": min_days, "met": is_ready},
            "recommended": {"sessions": rec_sessions, "days": rec_days, "met": is_recommended},
            "ideal": {"sessions": ideal_sessions, "days": ideal_days, "met": is_ideal}
        }
        
        self.log_state_shift("IDLE", f"Dataset profile compiled. Total sessions: {total_sessions}. Status: {status_msg}.")
        return json.dumps(stats)

    def compile_dataset_profile(self) -> Dict[str, Any]:
        """Scans session JSON logs to compile exact counts, day scopes, and topic metrics."""
        search_path = os.path.join(self.dataset_dir, "session_*.json")
        file_list = glob.glob(search_path)
        
        total_sessions = len(file_list)
        unique_days = set()
        topic_counts: Dict[str, int] = {}

        for file_path in file_list:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                if "date" in data:
                    unique_days.add(data["date"])
                
                topic = data.get("topic", "UNKNOWN").upper().strip()
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
            except Exception:
                continue

        return {
            "total_sessions": total_sessions,
            "days_covered": len(unique_days),
            "topic_distributions": topic_counts
        }
