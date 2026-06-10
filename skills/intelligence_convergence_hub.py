import sqlite3
import os
import time
from typing import Dict, Any, List

class AriaIntelligenceConvergenceHub:
    # Configurable Thresholds
    RECEPTIVENESS_SILENT_THRESHOLD = 3.0
    SKILL_TRUST_AVOID_THRESHOLD = 0.60
    
    # Class-level default database path to support dynamic testing isolation
    default_db_path = "aria_memory.db"

    def __init__(self, db_path: str = None):
        self.db_path = db_path if db_path is not None else self.default_db_path

    def _get_receptiveness_score(self) -> float:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Use governor_state key 'receptiveness_score' as the real source
                cursor.execute("SELECT value FROM governor_state WHERE key = 'receptiveness_score'")
                row = cursor.fetchone()
                if row:
                    return float(row[0])
        except Exception as e:
            print(f"[ConvergenceHub] Error fetching receptiveness_score: {e}")
        return 5.0  # Nominal default

    def _get_latest_causal_cause(self) -> str:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT assigned_cause FROM causal_attributions ORDER BY id DESC LIMIT 1")
                row = cursor.fetchone()
                if row:
                    return row[0]
        except Exception as e:
            print(f"[ConvergenceHub] Error fetching latest causal cause: {e}")
        return ""

    def _get_skill_trust_map(self) -> Dict[str, float]:
        trust_map = {}
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT skill_name, trust_score FROM skill_trust")
                for row in cursor.fetchall():
                    trust_map[row[0].strip().lower()] = row[1]
        except Exception as e:
            print(f"[ConvergenceHub] Error fetching skill trust map: {e}")
        return trust_map

    def compile_converged_intelligence_matrix(self) -> Dict[str, Any]:
        """Wave 1 & Wave 2: Concentrates isolated telemetry into active executive indicators."""
        receptiveness = self._get_receptiveness_score()
        latest_cause = self._get_latest_causal_cause()
        trust_map = self._get_skill_trust_map()
        
        # Identify low trust skills using configurable threshold
        low_trust_skills = [
            name for name, score in trust_map.items() 
            if score < self.SKILL_TRUST_AVOID_THRESHOLD
        ]

        return {
            "metrics_timestamp": int(time.time()),
            "user_receptiveness_score": receptiveness,
            "latest_causal_cause": latest_cause,
            "low_trust_skills": low_trust_skills,
            "skill_trust_matrix": trust_map
        }

    def generate_convergence_overrides(self) -> Dict[str, Any]:
        """Computes actionable behavior overrides and routing penalties for runtimes."""
        receptiveness = self._get_receptiveness_score()
        latest_cause = self._get_latest_causal_cause()
        trust_map = self._get_skill_trust_map()

        # Wave 1 overrides: Silent Mode
        interaction_mode = "STANDARD"
        max_proactive_interventions = 3
        if receptiveness < self.RECEPTIVENESS_SILENT_THRESHOLD:
            interaction_mode = "SILENT"
            max_proactive_interventions = 0

        # Causal remedies overrides
        timeout_factor = 1.0
        extra_delay = 0.0
        if latest_cause == "latency":
            timeout_factor = 2.0
            extra_delay = 3.0

        # Dynamic routing penalties hierarchy
        # trust >= 0.80 -> Preferred
        # 0.60-0.79 -> Normal
        # 0.40-0.59 -> Penalized
        # < 0.40 -> Avoid if alternatives exist
        skill_routing_penalties = {}
        avoid_skills = []
        for name, score in trust_map.items():
            if score >= 0.80:
                penalty = "Preferred"
            elif score >= 0.60:
                penalty = "Normal"
            elif score >= 0.40:
                penalty = "Penalized"
                avoid_skills.append(name)
            else:
                penalty = "Avoid if alternatives exist"
                avoid_skills.append(name)

        return {
            "interaction_mode": interaction_mode,
            "avoid_skills": avoid_skills,
            "skill_routing_penalties": skill_routing_penalties,
            "timeout_factor": timeout_factor,
            "extra_delay": extra_delay,
            "max_proactive_interventions": max_proactive_interventions
        }
