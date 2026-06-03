"""
skills/decision_engine.py -- Phase 5A: Executive Decision Engine
================================================================
Calculates a Return on Investment (ROI) score for every task using:

    ROI = (Project Base Weight * Task Impact) / Estimated Hours

- Active blockers take absolute precedence (Emergency override).
- Surfaces high-impact, low-effort quick wins (<= 3 hours, >= 7 impact) first.
- Merges project-level priority metrics with task-specific metadata.
- Fully cp1252 encoding safe.
"""

import os
import json
from skills.project_health import ProjectHealthCalculator


class AriaDecisionEngine:
    def __init__(self, db_path=None, json_path=None):
        repo_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = db_path or os.path.join(repo_path, "aria_memory.db")
        self.json_path = json_path or os.path.join(repo_path, "aria_projects.json")
        self.health_calc = ProjectHealthCalculator()
        self._init_db()

    def load_projects(self) -> dict:
        if not os.path.exists(self.json_path):
            return {}
        with open(self.json_path, 'r', encoding='utf-8') as f:
            try:
                return json.load(f).get("active_projects", {})
            except Exception:
                return {}

    def analyze_best_move(self) -> dict:
        projects = self.load_projects()
        if not projects:
            return {
                "type": "REST",
                "project": "None",
                "task": "None",
                "reason": "No active projects found. Feel free to rest or set new goals.",
                "score": 0.0
            }

        # Ingest Life OS pressures
        try:
            from skills.personal_os_reasoning import PersonalOSReasoningEngine
            pos_engine = PersonalOSReasoningEngine(db_path=self.db_path)
            pressures = pos_engine.compute_systemic_pressures()
            is_academic_guard = "ACADEMIC_GUARD" in pressures["active_guards"]
            is_burnout_guard = "BURNOUT_PROTECTION" in pressures["active_guards"]
        except Exception:
            is_academic_guard = False
            is_burnout_guard = False

        scored_tasks = []

        # 1. Critical Rule: Active blockers take absolute precedence
        for name, data in projects.items():
            if data.get("status") == "Blocked" and data.get("blockers"):
                blocker = data["blockers"][0]
                focus = data.get("current_focus", "Resolve Blocker")
                res = {
                    "type": "CRITICAL_BLOCKER",
                    "project": name,
                    "task": focus,
                    "reason": f"Project is halted by: '{blocker}'. Resolving this blocker is your highest strategic move.",
                    "score": 10.0
                }
                self._log_decision_if_new(res)
                return res

        # 2. Compute ROI for all pending tasks
        for name, data in projects.items():
            # Get metrics with fallbacks
            metrics = data.get("metrics", {})
            proj_impact = metrics.get("impact")
            proj_urgency = metrics.get("urgency")
            proj_base_pri = metrics.get("base_priority")

            if proj_impact is None or proj_urgency is None or proj_base_pri is None:
                # Fall back to PriorityEngine auto-inference
                try:
                    from skills.priority_engine import PriorityEngine
                    pe = PriorityEngine()
                    pe_score = pe.score_project(name, data, projects)
                    if proj_impact is None:
                        proj_impact = pe_score["impact"]
                    if proj_urgency is None:
                        proj_urgency = pe_score["urgency"]
                    if proj_base_pri is None:
                        proj_base_pri = pe_score["priority_score"]
                except Exception:
                    if proj_impact is None:
                        proj_impact = 5.0
                    if proj_urgency is None:
                        proj_urgency = 5.0
                    if proj_base_pri is None:
                        proj_base_pri = 5.0

            # Composite project priority score
            project_base = (proj_base_pri * 0.4) + (proj_urgency * 0.3) + (proj_impact * 0.3)
            
            for task in data.get("pending_tasks", []):
                # Handle string-based tasks gracefully for backward compatibility
                if isinstance(task, str):
                    task_name = task
                    effort = 5.0
                    is_blocking = False
                    task_impact = proj_impact
                else:
                    task_name = task.get("task_name", "Unnamed Task")
                    effort = max(0.5, task.get("estimated_hours", 5.0))
                    is_blocking = task.get("is_blocking", False)
                    # Task-specific impact overrides project-level impact
                    task_impact = task.get("impact", proj_impact)

                # ROI calculation
                roi_score = (project_base * task_impact) / effort
                if is_blocking:
                    roi_score *= 1.5  # Bottleneck multiplier

                # Phase 6D: Life Intelligence Adjustments
                if is_academic_guard:
                    if name.lower() == "academics" or "dsa" in task_name.lower() or "study" in task_name.lower():
                        roi_score *= 2.5
                    else:
                        roi_score *= 0.3
                if is_burnout_guard and effort > 3:
                    roi_score *= 0.4

                scored_tasks.append({
                    "project": name,
                    "task": task_name,
                    "roi": round(roi_score, 2),
                    "effort": effort,
                    "impact": task_impact
                })

        if not scored_tasks:
            return {
                "type": "REST",
                "project": "None",
                "task": "None",
                "reason": "All clear. No pending tasks found.",
                "score": 0.0
            }

        # Sort tasks by highest ROI score
        scored_tasks.sort(key=lambda x: x["roi"], reverse=True)
        top = scored_tasks[0]

        # 3. Quick Win Short-Circuit (Low effort, high impact)
        if top["effort"] <= 3 and top["impact"] >= 7:
            reason = f"Surfaced as an immediate high-impact quick win. It requires only ~{top['effort']} hours but clears high-value ground for {top['project']}."
        else:
            try:
                health = self.health_calc.score_project(top["project"])
                h_score = health["score"]
                h_grade = health["grade"]
            except Exception:
                h_score = 50
                h_grade = "C"
            reason = f"Highest strategic ROI score ({top['roi']}). {top['project']} is sitting at health {h_score}% ({h_grade})."

        res = {
            "type": "RECOMMENDATION",
            "project": top["project"],
            "task": top["task"],
            "reason": reason,
            "score": top["roi"]
        }
        self._log_decision_if_new(res)
        return res

    def _init_db(self):
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS decision_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    project_name TEXT NOT NULL,
                    task_name TEXT NOT NULL,
                    decision_type TEXT NOT NULL,
                    score REAL NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    completed_at INTEGER
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[DecisionEngine] Database initialization failed: {e}")

    def _log_decision_if_new(self, decision: dict):
        if decision["type"] not in ["RECOMMENDATION", "CRITICAL_BLOCKER"]:
            return
        try:
            import sqlite3
            import time
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check last logged decision
            cursor.execute("""
                SELECT timestamp, project_name, task_name 
                FROM decision_history 
                ORDER BY id DESC LIMIT 1
            """)
            row = cursor.fetchone()
            
            now = int(time.time())
            should_insert = True
            
            if row:
                last_ts, last_proj, last_task = row
                # Cooldown: 1 hour (3600 seconds) AND same project + task
                if now - last_ts < 3600 and last_proj == decision["project"] and last_task == decision["task"]:
                    should_insert = False
            
            if should_insert:
                cursor.execute("""
                    INSERT INTO decision_history 
                    (timestamp, project_name, task_name, decision_type, score, reason)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (now, decision["project"], decision["task"], decision["type"], decision["score"], decision["reason"]))
                conn.commit()
            conn.close()
        except Exception as e:
            print(f"[DecisionEngine] Failed to log decision to history: {e}")
