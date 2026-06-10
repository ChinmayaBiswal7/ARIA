"""
skills/personal_os_reasoning.py -- Phase 6D: Personal OS Reasoning Engine
========================================================================
Calculates academic, energy, and routine pressures from database logs and JSON files,
determining overall life load and active system guards.
Fully cp1252 safe.
"""

import os
import json
import sqlite3
import time
from datetime import datetime
from typing import Tuple

DB_PATH = "aria_memory.db"
HEALTH_PATH = "aria_health_state.json"

class PersonalOSReasoningEngine:
    def __init__(self, db_path=None, health_path=None):
        repo_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = db_path or os.path.join(repo_path, "aria_memory.db")
        self.health_path = health_path or os.path.join(repo_path, "aria_health_state.json")
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_calendar (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,          -- Event epoch time (0 for routines)
                    day_of_week TEXT,                    -- 'Monday', 'Tuesday', etc.
                    event_type TEXT NOT NULL,            -- 'academic_exam', 'gdg_event', 'routine_commitment'
                    title TEXT NOT NULL,                 -- e.g. "Data Structures Midterm"
                    associated_goal TEXT,                -- Maps to target goals
                    criticality INTEGER DEFAULT 5        -- Base weight (1 to 10)
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[PersonalOS] Database initialization failed: {e}")

    def _get_days_until_next_exam(self, current_time: float = None) -> float:
        if current_time is None:
            current_time = time.time()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        current_time_int = int(current_time)
        try:
            cursor.execute("""
                SELECT MIN(timestamp) FROM life_calendar 
                WHERE event_type = 'academic_exam' AND timestamp > ?
            """, (current_time_int,))
            row = cursor.fetchone()
            if row and row[0]:
                return (row[0] - current_time_int) / 86400
            return 99.0  # Clear runway default
        except Exception as e:
            print(f"[PersonalOS] Failed to query next exam: {e}")
            return 99.0
        finally:
            conn.close()

    def _get_routine_density(self) -> float:
        """Calculates today's routine commitments load factor."""
        day_name = datetime.now().strftime('%A')
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT SUM(criticality) FROM life_calendar 
                WHERE event_type = 'routine_commitment' AND day_of_week = ?
            """, (day_name,))
            total_crit = cursor.fetchone()[0]
            return min(1.0, (total_crit or 0) / 20.0)
        except Exception as e:
            print(f"[PersonalOS] Failed to query routine density: {e}")
            return 0.0
        finally:
            conn.close()

    def _get_biometric_energy(self) -> Tuple[int, float, float, int]:
        # 1. Try JSON file first
        base_energy = 70
        try:
            if os.path.exists(self.health_path):
                with open(self.health_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    base_energy = int(data["physiological_state"].get("calculated_energy_score", 70))
        except Exception:
            pass

        # 2. Try DB health_data fallback
        if base_energy == 70:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT sleep_quality FROM health_data ORDER BY timestamp DESC LIMIT 1")
                row = cursor.fetchone()
                conn.close()
                if row and row[0]:
                    # Map quality to number if it's text or direct value
                    try:
                        base_energy = int(row[0])
                    except ValueError:
                        base_energy = 70
            except Exception:
                pass

        # 3. Incorporate rolling statistics from HealthSkill
        rolling_sleep_avg = 7.5
        sleep_debt = 0.0
        rolling_steps_avg = 5000
        try:
            from skills.health_skill import HealthSkill
            hs = HealthSkill(db_path=self.db_path)
            stats = hs.get_rolling_biometric_stats()
            rolling_sleep_avg = stats["rolling_sleep_avg"]
            sleep_debt = stats["sleep_debt"]
            rolling_steps_avg = stats["rolling_steps_avg"]
        except Exception as e:
            print(f"[PersonalOS] Failed to fetch rolling stats: {e}")

        # Calculate final adjusted energy
        adjusted_energy = base_energy - int(sleep_debt * 2.5)
        if rolling_steps_avg >= 10000:
            adjusted_energy += 10
        elif rolling_steps_avg < 2000:
            adjusted_energy -= 5
            
        final_energy = max(10, min(100, adjusted_energy))
        return final_energy, rolling_sleep_avg, sleep_debt, rolling_steps_avg

    def get_circadian_focus_multiplier(self, current_time=None) -> float:
        """Determines hourly cognitive/focus capacity scaling factor based on current local hour."""
        if current_time is None:
            current_time = time.time()
        
        # Resolve current local hour
        local_time = time.localtime(current_time)
        hour = local_time.tm_hour
        
        # Focus capacity mapping
        if 8 <= hour < 12:
            return 1.4  # Peak focus hours
        elif 17 <= hour < 21:
            return 1.2  # Evening rebound study/sprints
        elif 13 <= hour < 15:
            return 0.8  # Post-lunch dip
        elif 22 <= hour < 23:
            return 0.7  # Soporific zone / late-night winddown
        elif hour >= 23 or hour < 5:
            return 0.5  # Sleep safety zone / late-night restriction
        else:
            return 1.0  # Nominal baseline zone

    def compute_systemic_pressures(self, current_time=None) -> dict:
        if current_time is None:
            current_time = time.time()

        # 1. Smooth academic pressure curve (pass current_time so tests can control it)
        days_until_exam = self._get_days_until_next_exam(current_time)
        if days_until_exam <= 1.0:
            academic_pressure = 1.0
        elif days_until_exam <= 3.0:
            academic_pressure = 0.9
        elif days_until_exam <= 7.0:
            academic_pressure = 0.6
        elif days_until_exam <= 14.0:
            academic_pressure = 0.35
        elif days_until_exam <= 20.0:
            academic_pressure = 0.2
        elif days_until_exam <= 30.0:
            academic_pressure = 0.1
        else:
            academic_pressure = 0.05

        # 2. Energy pressure from rolling biometric values
        energy_score, rolling_sleep_avg, sleep_debt, rolling_steps_avg = self._get_biometric_energy()
        energy_pressure = round((100 - energy_score) / 100, 2)

        # 3. Routine pressure
        routine_pressure = round(self._get_routine_density(), 2)

        # 4. Overall Life Load (Weighted summation)
        overall_life_load = round((academic_pressure * 0.5) + (energy_pressure * 0.3) + (routine_pressure * 0.2), 2)

        # 5. Fetch Calibrated Burnout Policy from learning engine (reusing P20 learn policy)
        burnout_limit = 0.70
        try:
            from skills.learning_engine import AriaLongTermLearningEngine
            learning_engine = AriaLongTermLearningEngine(self.db_path)
            burnout_limit, _ = learning_engine.fetch_calibrated_value("POL_BURNOUT_LIMIT", 0.70)
        except Exception:
            pass

        # 6. Evaluate Life State Machine Transition
        local_time = time.localtime(current_time)
        local_hour = local_time.tm_hour

        # State Priority Logic:
        # A. True Burnout Risk: dangerously low energy (< 30) OR extreme overall load at threshold
        #    This is the highest-severity state, indicating physiological danger.
        if energy_score < 30 or overall_life_load >= burnout_limit:
            life_state = "BURNOUT_RISK_MODE"
        # B. Exam Mode: exam pressure within 3 days (takes priority over recovery)
        elif days_until_exam <= 3.0:
            life_state = "EXAM_MODE"
        # C. Recovery Mode: significant sleep debt (>= 5h) even if energy is moderate (30–44)
        #    Separated from true burnout: the body needs sleep, not full shutdown.
        elif sleep_debt >= 5.0 or energy_score < 45:
            life_state = "RECOVERY_MODE"
        # D. Focus Mode (moderate academic workload, exam within a week)
        elif days_until_exam <= 7.0:
            life_state = "FOCUS_MODE"
        # E. High Performance Mode (low load and high energy)
        elif overall_life_load < 0.35 and energy_score >= 75:
            life_state = "HIGH_PERFORMANCE_MODE"
        # F. Nominal Normal
        else:
            life_state = "NORMAL"

        # 7. Establish guards based on current state and safety constraints
        active_guards = []
        if life_state == "BURNOUT_RISK_MODE" or overall_life_load >= burnout_limit:
            active_guards.append("BURNOUT_PROTECTION")
        if life_state == "EXAM_MODE" or academic_pressure >= 0.6:
            active_guards.append("ACADEMIC_GUARD")
        if life_state == "EXAM_MODE" or days_until_exam <= 3.0:
            active_guards.append("EXAM_PREP_GUARD")
        if life_state == "RECOVERY_MODE" or energy_score < 45 or ((local_hour >= 22 or local_hour < 5) and sleep_debt > 5.0):
            active_guards.append("FATIGUE_SAFETY_GATE")

        circadian_multiplier = self.get_circadian_focus_multiplier(current_time)

        return {
            "academic_pressure": academic_pressure,
            "energy_pressure": energy_pressure,
            "routine_pressure": routine_pressure,
            "overall_life_load": overall_life_load,
            "active_guards": active_guards,
            "raw_energy_score": energy_score,
            "rolling_sleep_avg": rolling_sleep_avg,
            "sleep_debt": sleep_debt,
            "rolling_steps_avg": rolling_steps_avg,
            "circadian_focus_multiplier": circadian_multiplier,
            "life_state": life_state,
            "burnout_limit_policy": burnout_limit
        }
