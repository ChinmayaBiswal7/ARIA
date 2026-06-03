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

    def _get_days_until_next_exam(self) -> float:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        current_time = int(time.time())
        try:
            cursor.execute("""
                SELECT MIN(timestamp) FROM life_calendar 
                WHERE event_type = 'academic_exam' AND timestamp > ?
            """, (current_time,))
            row = cursor.fetchone()
            if row and row[0]:
                return (row[0] - current_time) / 86400
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

    def _get_biometric_energy(self) -> int:
        # 1. Try JSON file first
        try:
            if os.path.exists(self.health_path):
                with open(self.health_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    val = data["physiological_state"].get("calculated_energy_score", 70)
                    return int(val)
        except Exception:
            pass

        # 2. Try DB health_data fallback
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # Fetch latest record
            cursor.execute("SELECT sleep_quality FROM health_data ORDER BY timestamp DESC LIMIT 1")
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                return int(row[0])
        except Exception:
            pass

        return 70  # Sane default

    def compute_systemic_pressures(self) -> dict:
        # 1. Smooth academic pressure curve
        days_until_exam = self._get_days_until_next_exam()
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

        # 2. Energy pressure
        energy_score = self._get_biometric_energy()
        energy_pressure = round((100 - energy_score) / 100, 2)

        # 3. Routine pressure
        routine_pressure = round(self._get_routine_density(), 2)

        # 4. Overall Life Load (Weighted summation)
        overall_life_load = round((academic_pressure * 0.5) + (energy_pressure * 0.3) + (routine_pressure * 0.2), 2)

        # Active Guards check
        active_guards = []
        if academic_pressure >= 0.6:
            active_guards.append("ACADEMIC_GUARD")
        if energy_pressure >= 0.55:
            active_guards.append("BURNOUT_PROTECTION")

        return {
            "academic_pressure": academic_pressure,
            "energy_pressure": energy_pressure,
            "routine_pressure": routine_pressure,
            "overall_life_load": overall_life_load,
            "active_guards": active_guards,
            "raw_energy_score": energy_score
        }
