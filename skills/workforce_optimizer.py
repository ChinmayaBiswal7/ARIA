import os
import sqlite3
import json
import time
import math
from typing import List, Dict, Any
from contextlib import closing

class AriaWorkforceOptimizer:
    def __init__(self, db_path: str = "aria_orchestrator.db"):
        self.db_path = db_path

    def select_optimal_team(self, domain_keyword: str, task_category: str, default_team: List[str]) -> List[str]:
        """Component P19: Evaluates and ranks agent teams, filtering by maturity and speed efficiency."""
        domain_clean = domain_keyword.upper().strip()
        category_clean = task_category.upper().strip()
        now = int(time.time())

        # If default team has 0 or 1 agents, optimizer is not needed
        if len(default_team) <= 1:
            return default_team

        # Category-specific default adjustments as requested by USER
        adjusted_default = self._get_adjusted_default_team(category_clean, default_team)

        if not os.path.exists(self.db_path):
            return adjusted_default

        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                
                # Fetch all sessions matching domain and category
                cursor = conn.execute("""
                    SELECT participating_agents, 
                           AVG(review_score) as avg_review, 
                           AVG(success_score) as avg_success,
                           AVG(execution_time_ms) as avg_time,
                           COUNT(*) as total_runs
                    FROM workforce_sessions
                    WHERE domain_keyword = ? AND task_category = ?
                    GROUP BY participating_agents
                """, (domain_clean, category_clean))
                
                rows = cursor.fetchall()
                if not rows:
                    return adjusted_default

                candidates = []
                for row in rows:
                    combination_str = row["participating_agents"]
                    try:
                        agents = json.loads(combination_str)
                    except Exception:
                        continue
                        
                    avg_review = row["avg_review"] or 0.0
                    avg_success = row["avg_success"] or 0.0
                    avg_time = row["avg_time"] or 1000.0
                    total_runs = row["total_runs"] or 0

                    # 1. Failure Memory and Blacklist
                    if avg_success < 0.40 or avg_review < 0.50:
                        print(f"[WorkforceOptimizer] Blacklisted combination: {agents} (Avg Success: {avg_success:.2f}, Avg Review: {avg_review:.2f})")
                        continue

                    # 2. Consecutive Failure Cooldown Check
                    # Fetch last 3 sessions for this combination to check for consecutive failures
                    cursor_fail = conn.execute("""
                        SELECT success_score, timestamp
                        FROM workforce_sessions
                        WHERE participating_agents = ?
                        ORDER BY timestamp DESC
                        LIMIT 3
                    """, (combination_str,))
                    recent_runs = cursor_fail.fetchall()
                    if len(recent_runs) == 3 and all(r[0] == 0.0 for r in recent_runs):
                        last_failure_time = recent_runs[0][1]
                        if now - last_failure_time < 86400:
                            print(f"[WorkforceOptimizer] Cooldown active for combination: {agents} (3 consecutive failures)")
                            continue

                    # 3. Calculate Speed Efficiency
                    # efficiency: higher when average execution time is lower
                    efficiency = 3000.0 / (3000.0 + avg_time)

                    # 4. Calculate Confidence-Weighted Selection Score
                    # score = (review * 0.4 + success * 0.4 + efficiency * 0.2) * ln(runs + 1)
                    weighted_score = (avg_review * 0.4 + avg_success * 0.4 + efficiency * 0.2) * math.log(total_runs + 1)

                    # Determine team maturity status
                    is_trusted = total_runs >= 10
                    is_matured = total_runs >= 5

                    candidates.append({
                        "agents": agents,
                        "score": weighted_score,
                        "is_trusted": is_trusted,
                        "is_matured": is_matured,
                        "total_runs": total_runs
                    })

                if not candidates:
                    return adjusted_default

                # Sort strategy:
                # 1. Trusted teams (total_runs >= 10) sorted by score descending
                # 2. Matured teams (total_runs >= 5) sorted by score descending
                # 3. Rest sorted by score descending
                trusted_candidates = [c for c in candidates if c["is_trusted"]]
                matured_candidates = [c for c in candidates if c["is_matured"] and not c["is_trusted"]]
                other_candidates = [c for c in candidates if not c["is_matured"]]

                trusted_candidates.sort(key=lambda x: x["score"], reverse=True)
                matured_candidates.sort(key=lambda x: x["score"], reverse=True)
                other_candidates.sort(key=lambda x: x["score"], reverse=True)

                best_choice = None
                if trusted_candidates:
                    best_choice = trusted_candidates[0]
                elif matured_candidates:
                    best_choice = matured_candidates[0]
                else:
                    best_choice = other_candidates[0]

                if best_choice:
                    print(f"[WorkforceOptimizer] Selected optimized team: {best_choice['agents']} (Runs: {best_choice['total_runs']}, Score: {best_choice['score']:.3f})")
                    return best_choice["agents"]

        except Exception as e:
            print(f"[WorkforceOptimizer] Failure selecting team: {e}")
            
        return adjusted_default

    def _get_adjusted_default_team(self, category: str, default_team: List[str]) -> List[str]:
        """Applies USER requested default allocations by task category."""
        if category == "LEARNING":
            return ["LearningAgent", "ResearchAgent", "PlannerAgent"]
        elif category == "PROJECT":
            return ["CodingAgent", "ResearchAgent", "PlannerAgent"]
        elif category == "INTERVIEW":
            return ["CareerAgent", "ResearchAgent", "PlannerAgent"]
        elif category == "RESUME":
            return ["CareerAgent", "PlannerAgent"]
        elif category == "GENERAL":
            return ["ResearchAgent", "PlannerAgent"]
        return default_team
