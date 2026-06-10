import os
import sqlite3
import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple
from contextlib import closing

class AriaResourceManager:
    def __init__(self, db_path: str = "aria_orchestrator.db"):
        self.db_path = db_path
        self._init_resource_ledger()

    def _init_resource_ledger(self):
        """Initializes tables for time-slot schedules and focus budget history."""
        if not self.db_path:
            return
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS task_schedules (
                        task_id TEXT PRIMARY KEY,
                        scheduled_date TEXT,       -- '2026-06-10'
                        time_slot TEXT,            -- '19:00-20:30'
                        allocated_duration INTEGER -- in minutes
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS focus_budget_history (
                        date_string TEXT PRIMARY KEY,
                        allocated_minutes INTEGER,
                        completed_minutes INTEGER DEFAULT 0,
                        fatigue_score REAL,
                        productivity_score REAL
                    )
                """)
                conn.commit()
        except Exception as e:
            print(f"[ResourceManager] Database initialization failed: {e}")

    def estimate_task_duration(self, task_description: str, agent_target: str) -> int:
        """Component P17: Queries completed tasks in agent_tasks to calculate historical averages.
        Component P20: Applies learned duration policies if ACTIVE or PROBATION."""
        desc_lower = task_description.lower()
        default_duration = 45  # default baseline in minutes
        
        # Keyword-based default fallbacks
        if any(k in desc_lower for k in ["docker", "aws", "deploy"]):
            default_duration = 60
        elif any(k in desc_lower for k in ["security", "spring", "auth"]):
            default_duration = 90
        elif any(k in desc_lower for k in ["java", "dsa", "leetcode", "array", "graph"]):
            default_duration = 45

        if not os.path.exists(self.db_path):
            return default_duration

        # 1. Fetch policy-based calibrated multiplier if any
        multiplier = 1.0
        policy_applied = False
        try:
            from skills.learning_engine import AriaLongTermLearningEngine
            engine = AriaLongTermLearningEngine(self.db_path)
            for kw in ["spring", "docker", "java", "dsa", "dbms"]:
                if kw in desc_lower or kw == agent_target.lower():
                    policy_id = f"POL_DUR_{kw.upper()}"
                    val, status = engine.fetch_calibrated_value(policy_id, 1.0)
                    if status != "DEFAULT":
                        multiplier = val
                        policy_applied = True
                        break
        except Exception as e:
            print(f"[ResourceManager] Error fetching learned duration policy: {e}")

        # 2. Estimate base duration from history or fallback
        base_estimate = default_duration
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                # Calculate average duration (completed_at - started_at) in minutes for completed tasks
                cursor = conn.execute("""
                    SELECT AVG(completed_at - started_at) / 60.0 as avg_mins
                    FROM agent_tasks
                    WHERE status = 'COMPLETED' 
                      AND started_at IS NOT NULL 
                      AND completed_at IS NOT NULL
                      AND (task_description LIKE ? OR agent_name = ?)
                """, (f"%{agent_target}%", agent_target.lower()))
                row = cursor.fetchone()
                if row and row["avg_mins"] is not None:
                    base_estimate = max(15, int(row["avg_mins"]))
        except Exception as e:
            print(f"[ResourceManager] Error estimating task duration: {e}")

        if policy_applied:
            return max(15, int(round(default_duration * multiplier)))

        return base_estimate

    def get_daily_capacity(self) -> Tuple[int, float]:
        """Component P17: Calculates focus budget capacity, adjusted for calendar density and history.
        Component P22: Calibrated dynamically using LifeOS state and circadian multipliers."""
        # 1. Fetch current physiological and routine pressures
        energy_score = 70
        routine_pressure = 0.0
        life_state = "NORMAL"
        circadian_multiplier = 1.0
        try:
            from skills.personal_os_reasoning import PersonalOSReasoningEngine
            os_engine = PersonalOSReasoningEngine(db_path=self.db_path)
            pressures = os_engine.compute_systemic_pressures()
            energy_score = pressures.get("raw_energy_score", 70)
            routine_pressure = pressures.get("routine_pressure", 0.0)
            life_state = pressures.get("life_state", "NORMAL")
            circadian_multiplier = pressures.get("circadian_focus_multiplier", 1.0)
        except Exception as e:
            print(f"[ResourceManager] PersonalOS Engine query failed, using defaults: {e}")

        # 2. Get rolling historical baseline
        historical_baseline = self._get_historical_baseline_capacity()

        # 3. Apply capacity caps/boosts based on LifeState
        if life_state in ("BURNOUT_RISK_MODE", "RECOVERY_MODE"):
            # Burnout or Recovery caps the capacity to protect health
            baseline_capacity = max(45, int(historical_baseline * 0.4))
        elif life_state == "HIGH_PERFORMANCE_MODE":
            # Boost capacity during high performance periods
            baseline_capacity = int(historical_baseline * 1.2)
        else:
            baseline_capacity = historical_baseline

        # 4. Apply calendar routines busy time
        available_baseline = baseline_capacity - int(routine_pressure * 120)

        # 5. Scale by physiological energy and hourly circadian multipliers
        energy_factor = energy_score / 100.0
        adjusted_capacity = int(available_baseline * energy_factor * circadian_multiplier)

        return max(60, adjusted_capacity), energy_factor

    def _get_historical_baseline_capacity(self) -> int:
        """Calculates rolling average of completed focus minutes over past 7 days."""
        if not os.path.exists(self.db_path):
            return 240  # 4 hours baseline fallback
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT AVG(completed_minutes) FROM (
                        SELECT completed_minutes 
                        FROM focus_budget_history 
                        WHERE completed_minutes > 0
                        ORDER BY date_string DESC LIMIT 7
                    )
                """)
                val = cursor.fetchone()[0]
                if val is not None:
                    return max(120, min(360, int(val)))
        except Exception:
            pass
        return 240

    def calculate_campaign_splits(self, campaign_priorities: Dict[str, int]) -> Dict[str, float]:
        """Allocates focus budget fractions proportionally based on campaign priority weights."""
        total_priority = sum(campaign_priorities.values())
        if total_priority == 0:
            return {camp: 1.0 / len(campaign_priorities) for camp in campaign_priorities}
        return {camp: priority / total_priority for camp, priority in campaign_priorities.items()}

    def schedule_and_allocate_tasks(self, campaign_id: str, proposed_tasks: List[Dict[str, Any]], campaign_priorities: Dict[str, int]) -> Dict[str, Any]:
        """Component P17: Performs calendar-aware scheduling, energy-scaling, splits, and time-slot assignments."""
        today_str = time.strftime("%Y-%m-%d")
        
        # 1. Fetch capacity and energy levels
        capacity_minutes, energy_factor = self.get_daily_capacity()
        print(f"[ResourceManager] Daily Capacity: {capacity_minutes}m, Energy Factor: {energy_factor}")

        # Fetch active LifeState for guard throttling
        life_state = "NORMAL"
        try:
            from skills.personal_os_reasoning import PersonalOSReasoningEngine
            os_engine = PersonalOSReasoningEngine(db_path=self.db_path)
            life_state = os_engine.compute_systemic_pressures().get("life_state", "NORMAL")
        except Exception:
            pass

        # 2. Calculate campaign splits
        splits = self.calculate_campaign_splits(campaign_priorities)
        campaign_budget = int(capacity_minutes * splits.get(campaign_id, 1.0))
        print(f"[ResourceManager] Split budget for campaign '{campaign_id}': {campaign_budget}m (LifeState: {life_state})")

        scheduled_today = []
        deferred_schedule = []
        
        current_date = datetime.strptime(today_str, "%Y-%m-%d")
        remaining_today_budget = campaign_budget
        
        # Basic available time slots model
        available_slots = ["19:00-20:30", "20:30-22:00", "07:00-08:30"]

        from datetime import timedelta

        for idx, task in enumerate(proposed_tasks):
            t_id = task.get("id") or f"T_GEN_{idx}"
            desc = task.get("description", "")
            target = task.get("agent_target", "ResearchAgent")
            
            # Estimate duration and scale for energy fatigue
            base_duration = self.estimate_task_duration(desc, target)
            scaled_duration = int(base_duration * (1.5 - energy_factor))
            
            # P22 Life State constraints
            should_defer = False
            
            # A. Exam Mode restriction: defer any non-academic tasks today
            if life_state == "EXAM_MODE":
                desc_l = desc.lower()
                academic_agents = {"careeragent", "learningagent", "studyagent", "academicagent"}
                academic_keywords = [
                    "study", "exam", "dsa", "leetcode", "dbms", "notes", "academics",
                    "revise", "revision", "sql", "learn", "practice", "homework", "assignment",
                    "quiz", "test", "chapter", "syllabus", "lecture"
                ]
                is_academic = any(k in desc_l for k in academic_keywords) or target.lower() in academic_agents
                if not is_academic:
                    should_defer = True
                    print(f"[ResourceManager] EXAM_MODE active: deferring non-study task '{t_id}' ({desc})")

            # B. Fatigue safety / Burnout cap: defer long tasks (> 60 mins)
            elif life_state in ("BURNOUT_RISK_MODE", "RECOVERY_MODE"):
                if scaled_duration > 60:
                    should_defer = True
                    print(f"[ResourceManager] {life_state} active: deferring long task '{t_id}' ({scaled_duration}m)")

            if not should_defer and remaining_today_budget >= scaled_duration:
                # Schedule today
                slot_index = len(scheduled_today) % len(available_slots)
                slot = available_slots[slot_index]
                self._record_task_schedule(t_id, today_str, slot, scaled_duration)
                scheduled_today.append({"task_id": t_id, "date": today_str, "slot": slot, "duration": scaled_duration})
                remaining_today_budget -= scaled_duration
            else:
                # Schedule tomorrow (or next day)
                target_date = current_date + timedelta(days=1)
                date_str = target_date.strftime("%Y-%m-%d")
                slot_index = len(deferred_schedule) % len(available_slots)
                slot = available_slots[slot_index]
                
                self._record_task_schedule(t_id, date_str, slot, scaled_duration)
                deferred_schedule.append({"task_id": t_id, "date": date_str, "slot": slot, "duration": scaled_duration})
                
                # Mark status as deferred in DB to protect from burnout
                self._update_task_status_deferred(t_id)

        # 3. Log focus budget history for today
        allocated_today = campaign_budget - remaining_today_budget
        self._record_focus_history(today_str, allocated_today, energy_factor)

        return {
            "allocation_status": "CAPACITY_STRETCH_APPLIED" if deferred_schedule else "AUTHORIZED_IMMEDIATE_RUN",
            "allocated_today_minutes": allocated_today,
            "scheduled_today": scheduled_today,
            "deferred_schedule": deferred_schedule
        }

    def _record_task_schedule(self, task_id: str, date_str: str, time_slot: str, duration: int):
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO task_schedules (task_id, scheduled_date, time_slot, allocated_duration)
                    VALUES (?, ?, ?, ?)
                """, (task_id, date_str, time_slot, duration))
                conn.commit()
        except Exception as e:
            print(f"[ResourceManager] Failed to record task schedule: {e}")

    def _record_focus_history(self, date_str: str, allocated: int, energy_factor: float):
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO focus_budget_history (date_string, allocated_minutes, completed_minutes, fatigue_score, productivity_score)
                    VALUES (?, ?, 0, ?, 0.0)
                """, (date_str, allocated, round(1.0 - energy_factor, 2)))
                conn.commit()
        except Exception as e:
            print(f"[ResourceManager] Failed to record focus history: {e}")

    def _update_task_status_deferred(self, task_id: str):
        if not os.path.exists(self.db_path):
            return
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    UPDATE agent_tasks 
                    SET status = 'DEFERRED_CAPACITY_LIMIT' 
                    WHERE id = ?
                """, (task_id,))
                conn.commit()
        except Exception as e:
            print(f"[ResourceManager] Failed to update task status to deferred: {e}")

    def complete_task_resource_minutes(self, task_id: str, completed_minutes: int, productivity_score: float = 1.0):
        """Allows scheduler to record completed focus minutes, refining the historical baseline."""
        today = time.strftime("%Y-%m-%d")
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                # Update task duration in schedule
                conn.execute("UPDATE task_schedules SET allocated_duration = ? WHERE task_id = ?", (completed_minutes, task_id))
                # Update rolling focus budget history
                conn.execute("""
                    INSERT INTO focus_budget_history (date_string, allocated_minutes, completed_minutes, fatigue_score, productivity_score)
                    VALUES (?, ?, ?, 0.0, ?)
                    ON CONFLICT(date_string) DO UPDATE SET
                        completed_minutes = completed_minutes + excluded.completed_minutes,
                        productivity_score = (productivity_score + excluded.productivity_score) / 2.0
                """, (today, completed_minutes, completed_minutes, productivity_score))
                conn.commit()
            print(f"[ResourceManager] Logged completion: {completed_minutes}m for task {task_id}")
        except Exception as e:
            print(f"[ResourceManager] Failed to log task completion resources: {e}")
