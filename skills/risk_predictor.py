"""
skills/risk_predictor.py -- Phase 6A: Predictive Risk Forecaster
================================================================
Assesses active projects and calculates a dynamic risk index (0.0 to 1.0)
using indicators like velocity decay, bottlenecks, baseline health, and blocker flags.
Logs entries into SQLite project_risk_history with deduplication throttling.
Fully cp1252 safe.
"""

import os
import json
import sqlite3
import time
from skills.project_health import ProjectHealthCalculator


class AriaRiskPredictor:
    def __init__(self, db_path=None, json_path=None):
        repo_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = db_path or os.path.join(repo_path, "aria_memory.db")
        self.json_path = json_path or os.path.join(repo_path, "aria_projects.json")
        self.health_calc = ProjectHealthCalculator()
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS project_risk_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER,
                    project_name TEXT,
                    risk_score REAL,
                    health_score REAL,
                    tier TEXT,
                    confidence REAL,
                    catalysts TEXT
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[RiskPredictor] Database initialization failed: {e}")

    def _get_days_since_last_completion(self, project_name: str) -> float:
        if not os.path.exists(self.db_path):
            return 14.0
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        current_time = int(time.time())
        try:
            cursor.execute("""
                SELECT timestamp FROM project_timeline 
                WHERE project_name = ? AND event_type = 'task_completed'
                ORDER BY timestamp DESC LIMIT 1
            """, (project_name,))
            row = cursor.fetchone()
            if row:
                return (current_time - row[0]) / 86400
            return 14.0  # Default penalty if no completions recorded
        except Exception:
            return 14.0
        finally:
            conn.close()

    def calculate_project_risk(self, project_name: str) -> dict:
        if not os.path.exists(self.json_path):
            return {"project": project_name, "risk_score": 0.0, "health_score": 50.0, "tier": "STABLE", "confidence": 0.5, "catalysts": [], "trend_msg": ""}

        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)["active_projects"].get(project_name)
        except Exception:
            project_data = None

        if not project_data:
            return {"project": project_name, "risk_score": 0.0, "health_score": 50.0, "tier": "STABLE", "confidence": 0.5, "catalysts": [], "trend_msg": ""}

        risk_score = 0.0
        catalysts = []

        # 1. Stagnation: Days since last task completion (Max 0.35 weight)
        days_idle = self._get_days_since_last_completion(project_name)
        if days_idle >= 5:
            weight = min(0.35, days_idle * 0.05)
            risk_score += weight
            catalysts.append(f"Velocity Decay: No tasks completed for {round(days_idle, 1)} days.")

        # 2. Structural Bottlenecks (Heavy blocking dependencies) (Max 0.30 weight)
        pending_tasks = project_data.get("pending_tasks", [])
        heavy_blockers = []
        for t in pending_tasks:
            if isinstance(t, dict):
                if t.get("is_blocking") and t.get("estimated_hours", 0) >= 15:
                    heavy_blockers.append(t)
        
        if heavy_blockers:
            risk_score += 0.30
            catalysts.append(f"Dependency Friction: Heavy blocking task '{heavy_blockers[0]['task_name']}' ({heavy_blockers[0]['estimated_hours']}h expected effort).")

        # 3. Baseline Health Vulnerability (Max 0.20 weight)
        try:
            health_info = self.health_calc.score_project(project_name)
            current_health = float(health_info["score"])
            health_grade = health_info["grade"]
        except Exception:
            current_health = 50.0
            health_grade = "C"

        if current_health < 70:
            risk_score += 0.20
            catalysts.append(f"Low Baseline Health: Vitality is low ({current_health}/100, Grade {health_grade}).")

        # 4. Explicit Active Blockers (Max 0.15 weight)
        if project_data.get("status") == "Blocked" or project_data.get("blockers"):
            risk_score += 0.15
            catalysts.append("Active Friction: Explicit project blockers are currently unresolved.")

        # Clamp and round
        risk_score = min(1.0, max(0.0, round(risk_score, 2)))

        # Determine Tier
        if risk_score >= 0.70:
            tier = "CRITICAL"
        elif risk_score >= 0.40:
            tier = "ELEVATED"
        else:
            tier = "STABLE"

        # 5. Confidence Score (0.0 to 1.0)
        confidence = 0.5  # baseline
        if "metrics" in project_data:
            confidence += 0.2
        if days_idle < 14:
            confidence += 0.2
        focus = project_data.get("current_focus", "")
        next_action = project_data.get("next_action", "")
        if focus and focus.lower() not in ["none", ""]:
            confidence += 0.05
        if next_action and next_action.lower() not in ["none", ""]:
            confidence += 0.05
        confidence = min(1.0, round(confidence, 2))

        # 6. Trend Detection from History
        trend_msg = ""
        current_time = int(time.time())
        one_week_ago = current_time - (7 * 86400)
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT risk_score FROM project_risk_history 
                WHERE project_name = ? AND timestamp >= ? 
                ORDER BY timestamp ASC LIMIT 1
            """, (project_name, one_week_ago))
            row = cursor.fetchone()
            if row:
                old_risk = row[0]
                delta = risk_score - old_risk
                if delta > 0.02:
                    trend_msg = f"Trend: Risk has increased by {round(delta, 2)} over the last 7 days."
                elif delta < -0.02:
                    trend_msg = f"Trend: Risk has decreased by {round(abs(delta), 2)} over the last 7 days."
                else:
                    trend_msg = "Trend: Risk profile is stable compared to last week."
            conn.close()
        except Exception as te:
            print(f"[RiskPredictor] Trend query error: {te}")

        # 7. Throttled SQLite Logging
        self._log_history_throttled(project_name, risk_score, current_health, tier, confidence, catalysts)

        return {
            "project": project_name,
            "risk_score": risk_score,
            "health_score": current_health,
            "tier": tier,
            "confidence": confidence,
            "catalysts": catalysts,
            "trend_msg": trend_msg
        }

    def _log_history_throttled(self, project_name: str, risk: float, health: float, tier: str, confidence: float, catalysts: list):
        if not os.path.exists(self.db_path):
            return

        current_time = int(time.time())
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Fetch latest logged entry
            cursor.execute("""
                SELECT timestamp, risk_score, health_score, tier 
                FROM project_risk_history 
                WHERE project_name = ? 
                ORDER BY timestamp DESC LIMIT 1
            """, (project_name,))
            row = cursor.fetchone()
            
            should_log = False
            if not row:
                should_log = True
            else:
                last_time, last_risk, last_health, last_tier = row
                time_delta = current_time - last_time
                risk_delta = abs(risk - last_risk)
                health_delta = abs(health - last_health)
                
                # Option A + Option B combined throttling
                if time_delta >= 3600:  # > 1 hour
                    should_log = True
                elif risk_delta > 0.02:  # Significant risk shift
                    should_log = True
                elif health_delta > 2.0:  # Significant health shift
                    should_log = True
                elif tier != last_tier:  # Status level tier change
                    should_log = True

            if should_log:
                catalysts_str = json.dumps(catalysts)
                cursor.execute("""
                    INSERT INTO project_risk_history 
                    (timestamp, project_name, risk_score, health_score, tier, confidence, catalysts)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (current_time, project_name, risk, health, tier, confidence, catalysts_str))
                conn.commit()
            
            conn.close()
        except Exception as e:
            print(f"[RiskPredictor] Throttled logging error: {e}")

    def analyze_all_risks(self) -> list:
        if not os.path.exists(self.json_path):
            return []
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                projects = list(json.load(f).get("active_projects", {}).keys())
        except Exception:
            return []

        return [self.calculate_project_risk(p) for p in projects]
