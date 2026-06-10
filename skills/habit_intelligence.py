"""
skills/habit_intelligence.py — Rule-based Habit Analytics & Intervention Engine for ARIA
========================================================================================
Asynchronously compiles presence sessions, computes productivity scores and weekly trends,
evaluates health break interventions, suggests matching RAG study notes, and exports habit datasets.
"""

import sqlite3
import json
import time
import os
import threading
import numpy as np
from typing import Dict, Any, List

from skills.base_agent import BaseAgent

class AriaHabitIntelligence(BaseAgent):
    def __init__(self, aria_instance, db_path: str = "aria_orchestrator.db"):
        super().__init__("HabitIntelligenceAgent", aria_instance)
        self.db_path = db_path
        
        # Background loops management
        self._running = True
        self._thread = threading.Thread(target=self._background_loop, name="HabitIntelligenceBackground", daemon=True)
        self._thread.start()
        print("[HabitIntelligence] Background daemon active (Fast/Slow loops running).")

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        self.log_state_shift("RUNNING", "Fetching latest productivity and habit stats...")
        
        # Forces immediate compilation on query request
        weekly_stats = self._calculate_weekly_presence_metrics()
        current_session_min = self._calculate_current_session_duration()
        interventions = self._evaluate_intervention_triggers(current_session_min)
        
        report = {
            "analytics": weekly_stats,
            "current_session_minutes": current_session_min,
            "triggered_interventions": interventions
        }
        
        self.log_state_shift("IDLE", f"Habit report compiled. Score: {weekly_stats.get('productivity_score', 0)}/100.")
        return json.dumps(report)

    def stop(self):
        self._running = False
        if self._thread:
            try:
                self._thread.join(timeout=1.0)
            except Exception:
                pass
            print("[HabitIntelligence] Background daemon stopped.")

    def _background_loop(self):
        fast_tick_seconds = 30
        slow_tick_seconds = 600  # 10 minutes
        last_slow_run = 0

        while self._running:
            try:
                now = time.time()
                
                # 1. Fast Loop (30s) - Current session length & active stretch break triggers
                current_session_min = self._calculate_current_session_duration()
                self._evaluate_intervention_triggers(current_session_min)
                
                # 2. Slow Loop (10 minutes or on startup) - Weekly analytics, trends, RAG suggestion prep, & datasets
                if now - last_slow_run >= slow_tick_seconds or last_slow_run == 0:
                    weekly_stats = self._calculate_weekly_presence_metrics()
                    
                    from skills.blackboard import AriaBlackboard
                    blackboard = AriaBlackboard()
                    blackboard.publish(
                        topic="habits",
                        key="weekly_analytics",
                        value=weekly_stats,
                        source=self.agent_name,
                        ttl_hours=24
                    )
                    
                    # Save completed sessions to dataset folder for future P7 modeling
                    completed_sessions = self._get_completed_sessions_list()
                    self._export_habit_dataset(completed_sessions)
                    
                    last_slow_run = now
            except Exception as e:
                print(f"[HabitIntelligence] Background thread error: {e}")
                
            # Sleep in 1-second chunks to exit quickly if thread is stopped
            for _ in range(fast_tick_seconds):
                if not self._running:
                    break
                time.sleep(1)

    def _get_sessions_for_range(self, start_time: int, end_time: int) -> List[Dict[str, Any]]:
        """Reconstructs continuous presence sessions from the visual timeline events."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    SELECT event_type, timestamp 
                    FROM vision_event_timeline 
                    WHERE entity_name IN ('chinmaya', 'chinmay', 'user')
                      AND timestamp >= ? AND timestamp < ?
                    ORDER BY timestamp ASC
                """, (start_time, end_time))
                rows = cursor.fetchall()
            finally:
                conn.close()
        except Exception as e:
            print(f"[HabitIntelligence] Database error retrieving session range: {e}")
            return []

        sessions = []
        active_start = None
        for row in rows:
            event, ts = row[0], row[1]
            if "APPEARED" in event:
                if active_start is None:
                    active_start = ts
            elif "LEFT" in event or "REMOVED" in event:
                if active_start is not None:
                    duration = ts - active_start
                    if duration > 60:  # Noise filter: session must be > 1 minute
                        sessions.append({
                            "start": active_start,
                            "end": ts,
                            "duration": duration
                        })
                    active_start = None
        return sessions

    def _get_completed_sessions_list(self) -> List[Dict[str, Any]]:
        return self._get_sessions_for_range(0, int(time.time()))

    def _calculate_weekly_presence_metrics(self) -> Dict[str, Any]:
        """Calculates dynamic productivity scores, weekly trends, start/end hours, and streaks."""
        now = time.time()
        lt = time.localtime(now)
        start_of_today = int(time.mktime(time.struct_time((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))))
        
        this_week_start = int(now - 7 * 86400)
        last_week_start = int(now - 14 * 86400)
        
        this_week_sessions = self._get_sessions_for_range(this_week_start, now)
        last_week_sessions = self._get_sessions_for_range(last_week_start, this_week_start)
        
        current_session_min = self._calculate_current_session_duration()
        
        all_this_week_durations = [s["duration"] // 60 for s in this_week_sessions]
        if current_session_min > 0:
            all_this_week_durations.append(current_session_min)
            
        total_sessions = len(this_week_sessions) + (1 if current_session_min > 0 else 0)
        average_session_minutes = int(np.mean(all_this_week_durations)) if all_this_week_durations else 0
        longest_session_minutes = int(np.max(all_this_week_durations)) if all_this_week_durations else 0
        
        # Start/End Hours
        start_hours = [time.localtime(s["start"]).tm_hour for s in this_week_sessions]
        if current_session_min > 0:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT timestamp FROM vision_event_timeline 
                    WHERE entity_name IN ('chinmaya', 'chinmay', 'user') AND event_type LIKE '%APPEARED'
                    ORDER BY id DESC LIMIT 1
                """)
                row = cursor.fetchone()
                if row:
                    start_hours.append(time.localtime(row[0]).tm_hour)
                    
        average_start_hour = int(np.mean(start_hours)) if start_hours else 0
        
        end_hours = [time.localtime(s["end"]).tm_hour for s in this_week_sessions]
        average_end_hour = int(np.mean(end_hours)) if end_hours else 0
        
        # Most Active Day
        day_counts = {}
        for s in this_week_sessions:
            day = time.strftime("%A", time.localtime(s["start"]))
            day_counts[day] = day_counts.get(day, 0) + 1
        if current_session_min > 0 and row:
            day = time.strftime("%A", time.localtime(row[0]))
            day_counts[day] = day_counts.get(day, 0) + 1
        most_active_day = max(day_counts, key=day_counts.get) if day_counts else "None"
        
        # Weekly presence hours
        this_week_hours = sum(s["duration"] for s in this_week_sessions) / 3600.0
        if current_session_min > 0:
            this_week_hours += current_session_min / 60.0
        this_week_hours = round(this_week_hours, 1)
        
        last_week_hours = sum(s["duration"] for s in last_week_sessions) / 3600.0
        last_week_hours = round(last_week_hours, 1)
        
        # Trend Percentage
        if last_week_hours > 0.0:
            trend_percentage = round(((this_week_hours - last_week_hours) / last_week_hours) * 100.0, 1)
        else:
            trend_percentage = 0.0
            
        # Today's stats
        today_sessions = [s for s in this_week_sessions if s["start"] >= start_of_today]
        sessions_today = len(today_sessions) + (1 if current_session_min > 0 else 0)
        
        focus_minutes_today = sum(s["duration"] for s in today_sessions) // 60
        if current_session_min > 0:
            focus_minutes_today += current_session_min
            
        today_streaks = [s["duration"] // 60 for s in today_sessions]
        if current_session_min > 0:
            today_streaks.append(current_session_min)
        longest_focus_streak_today = max(today_streaks) if today_streaks else 0
        
        # Productivity Score Formula out of 100
        focus_points = min(50, focus_minutes_today // 6)             # 300 focus mins (5h) -> 50 points
        consistency_points = min(30, sessions_today * 10)           # 3 completed sessions -> 30 points
        streak_points = min(20, longest_focus_streak_today // 15)   # 300 min focus streak -> 20 points
        productivity_score = focus_points + consistency_points + streak_points
        
        return {
            "average_session_minutes": average_session_minutes,
            "total_sessions": total_sessions,
            "longest_session_minutes": longest_session_minutes,
            "current_focus_streak": current_session_min,
            "longest_focus_streak": longest_session_minutes,
            "sessions_today": sessions_today,
            "average_start_hour": average_start_hour,
            "average_end_hour": average_end_hour,
            "most_active_day": most_active_day,
            "weekly_presence_hours": this_week_hours,
            "last_week_presence_hours": last_week_hours,
            "trend_percentage": trend_percentage,
            "productivity_score": productivity_score
        }

    def _calculate_current_session_duration(self) -> int:
        """Determines how many minutes the user has currently been present continuously."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    SELECT event_type, timestamp 
                    FROM vision_event_timeline 
                    WHERE entity_name IN ('chinmaya', 'chinmay', 'user')
                    ORDER BY id DESC LIMIT 1
                """)
                row = cursor.fetchone()
            finally:
                conn.close()
        except Exception as e:
            print(f"[HabitIntelligence] Error querying current presence: {e}")
            return 0

        if row and "APPEARED" in row[0]:
            return int((time.time() - row[1]) // 60)
        return 0

    def _evaluate_intervention_triggers(self, current_minutes: int) -> List[str]:
        """Component 6.5: Evaluates stretch reminders and matches topics dynamically to the RAG vault."""
        fired_actions = []

        # Rule A: Physical Fatigue Stretch Gate (>= 90 continuous minutes)
        if current_minutes >= 90:
            fired_actions.append("STRETCH_BREAK_RECOMMENDED")
            aria = self.aria
            if aria and hasattr(aria, "alert_router") and aria.alert_router:
                try:
                    aria.alert_router.dispatch_alert(
                        title="🧘‍♂️ TIME FOR A STRETCH BREAK",
                        body=f"You've been focused at the desk for {current_minutes} minutes. Stand up and stretch.",
                        priority="MEDIUM",
                        category="HEALTH"
                    )
                except Exception:
                    pass

        # Rule B: Contextual Academic Suggestion (19:00 - 22:00, present for >= 15m)
        current_hour = time.localtime().tm_hour
        if 19 <= current_hour <= 22 and current_minutes >= 15:
            fired_actions.append("SUGGEST_STUDY_RESOURCES")
            topic = self._determine_active_study_topic()
            matching_doc = self._find_matching_study_resource(topic)
            
            aria = self.aria
            if aria and hasattr(aria, "alert_router") and aria.alert_router:
                try:
                    aria.alert_router.dispatch_alert(
                        title="📚 STUDY SESSION ACTIVE",
                        body=f"You were recently studying {topic}. Open '{matching_doc}'?",
                        priority="LOW",
                        category="EDUCATION"
                    )
                except Exception:
                    pass
        return fired_actions

    def _determine_active_study_topic(self) -> str:
        """Determines the active study topic based on recent chat history keywords."""
        topics = {
            "DBMS": ["dbms", "database", "sql", "transaction"],
            "DSA": ["dsa", "data structure", "algorithm", "tree", "graph", "sort"],
            "Java": ["java", "oop", "inheritance", "class"],
            "CN": ["cn", "network", "tcp", "ip", "routing"],
            "OS": ["os", "operating system", "process", "thread", "memory management"]
        }
        
        try:
            conn = sqlite3.connect("aria_memory.db")
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT content FROM conversation_history ORDER BY id DESC LIMIT 50")
                rows = cursor.fetchall()
                for row in rows:
                    content = row[0].lower()
                    for topic, keywords in topics.items():
                        for kw in keywords:
                            if kw in content:
                                return topic
            finally:
                conn.close()
        except Exception as e:
            print(f"[HabitIntelligence] Error reading history: {e}")

        try:
            conn = sqlite3.connect("aria_memory.db")
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT topic FROM current_focus ORDER BY last_reinforced DESC LIMIT 1")
                row = cursor.fetchone()
                if row:
                    focus_topic = row[0].lower()
                    for topic, keywords in topics.items():
                        for kw in keywords:
                            if kw in focus_topic:
                                return topic
            finally:
                conn.close()
        except Exception as e:
            print(f"[HabitIntelligence] Error reading focus: {e}")

        return "DBMS"  # fallback default

    def _find_matching_study_resource(self, topic: str) -> str:
        """Retrieves matching notes filename from the RAG knowledge vault."""
        try:
            from skills.embedding_engine import AriaEmbeddingEngine
            from skills.vector_store import AriaVectorStore
            
            vault_dir = "data/knowledge_vault"
            if not os.path.exists(vault_dir):
                return f"{topic}_notes.pdf"
                
            encoder = AriaEmbeddingEngine()
            vector_store = AriaVectorStore(vault_dir)
            vector_store.load()
            
            query_embedding = encoder.get_embedding(topic)
            if query_embedding:
                chunks = vector_store.search(query_embedding, k=1)
                if chunks:
                    source_path = chunks[0].get("source")
                    if source_path:
                        return os.path.basename(source_path)
        except Exception as e:
            print(f"[HabitIntelligence] RAG query failed: {e}")
        return f"{topic}_notes.pdf"

    def _determine_topic_at_time(self, timestamp: int) -> str:
        """Determines the active study topic near a specific historical timestamp."""
        topics = {
            "DBMS": ["dbms", "database", "sql", "transaction"],
            "DSA": ["dsa", "data structure", "algorithm", "tree", "graph", "sort"],
            "Java": ["java", "oop", "inheritance", "class"],
            "CN": ["cn", "network", "tcp", "ip", "routing"],
            "OS": ["os", "operating system", "process", "thread", "memory management"]
        }
        
        try:
            conn = sqlite3.connect("aria_memory.db")
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT content FROM conversation_history "
                    "WHERE timestamp >= ? AND timestamp <= ? "
                    "ORDER BY ABS(timestamp - ?) ASC LIMIT 10",
                    (timestamp - 14400, timestamp + 14400, timestamp)
                )
                rows = cursor.fetchall()
                for row in rows:
                    content = row[0].lower()
                    for topic, keywords in topics.items():
                        for kw in keywords:
                            if kw in content:
                                return topic
            finally:
                conn.close()
        except Exception as e:
            pass
        return "DBMS"

    def _export_habit_dataset(self, completed_sessions: list):
        """Quietly saves completed focus session details for future offline P7 model training."""
        dataset_dir = "data/habit_dataset"
        if not os.path.exists(dataset_dir):
            os.makedirs(dataset_dir, exist_ok=True)
            
        for s in completed_sessions:
            start_ts = s["start"]
            local_time = time.localtime(start_ts)
            date_str = time.strftime("%Y-%m-%d", local_time)
            start_hour = local_time.tm_hour
            duration_mins = s["duration"] // 60
            
            topic = self._determine_topic_at_time(start_ts)
            
            record = {
                "date": date_str,
                "start_hour": start_hour,
                "duration": duration_mins,
                "topic": topic
            }
            
            filename = os.path.join(dataset_dir, f"session_{start_ts}.json")
            if not os.path.exists(filename):
                try:
                    with open(filename, "w", encoding="utf-8") as f:
                        json.dump(record, f, indent=2)
                except Exception as e:
                    print(f"[HabitIntelligence] Failed to write habit dataset: {e}")
