import sqlite3
import os
import datetime
import re

DB_PATH = "aria_memory.db"

class MemorySkill:
    """Handles long-term SQLite database storage for ARIA (reminders, paths, preferences)."""
    
    def __init__(self):
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(DB_PATH)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Reminders Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL,
                    due_date TEXT,
                    created_at TEXT NOT NULL,
                    status TEXT DEFAULT 'pending'
                )
            """)
            cursor.execute("PRAGMA table_info(reminders)")
            reminder_cols = {row[1] for row in cursor.fetchall()}
            if "due_at" not in reminder_cols:
                cursor.execute("ALTER TABLE reminders ADD COLUMN due_at TEXT")
            # Project Folders Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    path TEXT NOT NULL
                )
            """)
            # Preferences & Habits Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS personal_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT DEFAULT 'active'
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    active_window TEXT NOT NULL,
                    battery_percent INTEGER,
                    wifi_status TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            # Semantic Knowledge Graph Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS semantic_graph (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    target TEXT NOT NULL,
                    metadata TEXT,
                    UNIQUE(source, relation, target)
                )
            """)
            # Persistent Task Tree Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_tree (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_name TEXT NOT NULL,
                    task_name TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    dependency TEXT,
                    blocker TEXT,
                    created_at TEXT,
                    deadline TEXT,
                    time_state TEXT DEFAULT 'ongoing',
                    UNIQUE(goal_name, task_name)
                )
            """)
            # Episodic Replay Memory Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS episodic_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            # Failure Analytics Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS failure_analytics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal TEXT NOT NULL,
                    step INTEGER NOT NULL,
                    failure_type TEXT NOT NULL,
                    action_attempted TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            # Strategy Weights Table (Self-Optimizing Cognition)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategy_weights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_key TEXT UNIQUE NOT NULL,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    weight REAL DEFAULT 1.0
                )
            """)
            conn.commit()

    # --- Reminders API ---
    def parse_reminder_text(self, reminder_text):
        text = reminder_text.strip()
        lower = text.lower()
        now = datetime.datetime.now()
        due_date = "today"
        target_date = now.date()

        if " tomorrow" in lower:
            target_date = (now + datetime.timedelta(days=1)).date()
            due_date = "tomorrow"
            text = re.sub(r'(?i)\s+tomorrow\b', '', text).strip()
            lower = text.lower()
        elif " next week" in lower:
            target_date = (now + datetime.timedelta(days=7)).date()
            due_date = "next week"
            text = re.sub(r'(?i)\s+next week\b', '', text).strip()
            lower = text.lower()
        elif " today" in lower:
            text = re.sub(r'(?i)\s+today\b', '', text).strip()
            lower = text.lower()

        time_match = re.search(
            r'(?i)\b(?:at|by)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b',
            text
        )
        due_at = None
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            meridian = (time_match.group(3) or "").lower()
            if meridian == "pm" and hour < 12:
                hour += 12
            elif meridian == "am" and hour == 12:
                hour = 0

            if 0 <= hour <= 23 and 0 <= minute <= 59:
                due_dt = datetime.datetime.combine(target_date, datetime.time(hour, minute))
                if due_dt <= now and due_date == "today":
                    due_dt += datetime.timedelta(days=1)
                    due_date = "tomorrow"
                due_at = due_dt.strftime("%Y-%m-%d %H:%M")
                text = (text[:time_match.start()] + text[time_match.end():]).strip()

        text = re.sub(r'\s+', ' ', text).strip(" .,")
        return text, due_date, due_at

    def add_reminder(self, task, due_date="today", due_at=None):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO reminders (task, due_date, due_at, created_at) VALUES (?, ?, ?, ?)",
                (task, due_date, due_at, now)
            )
            conn.commit()
        when = due_at if due_at else due_date
        return f"Saved reminder to {task} for {when}."

    def get_pending_reminders(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT task, due_date, due_at FROM reminders WHERE status = 'pending' ORDER BY COALESCE(due_at, due_date), id")
            rows = cursor.fetchall()
        if not rows:
            return "You have no pending reminders."
        
        lines = [f"- {r[0]} (for {r[2] or r[1]})" for r in rows]
        return "Here are your reminders:\n" + "\n".join(lines)

    def get_due_reminders(self):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, task FROM reminders WHERE status = 'pending' AND due_at IS NOT NULL AND due_at <= ? ORDER BY due_at",
                (now,)
            )
            return cursor.fetchall()

    def complete_reminder(self, reminder_id):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE reminders SET status = 'completed' WHERE id = ?", (reminder_id,))
            conn.commit()

    def clear_reminders(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE reminders SET status = 'completed'")
            conn.commit()
        return "Cleared all reminders."

    # --- Folders API ---
    def save_folder(self, name, path):
        normalized_name = name.lower().strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO folders (name, path) VALUES (?, ?)",
                (normalized_name, path)
            )
            conn.commit()
        return f"Registered folder '{name}' pointing to: {path}."

    def get_folder_path(self, name):
        normalized_name = name.lower().strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path FROM folders WHERE name = ?", (normalized_name,))
            row = cursor.fetchone()
        return row[0] if row else None

    # --- Preferences API ---
    def set_preference(self, key, value):
        # Write to legacy table for backward compatibility
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO preferences (key, value) VALUES (?, ?)",
                (key.lower(), value)
            )
            conn.commit()

        # Safely propagate to user-segregated memory system
        try:
            from skills.memory_manager import MemoryManager
            mm = MemoryManager()
            # Try to get active user from dashboard or fallback
            try:
                from dashboard import CognitionState
                username = getattr(CognitionState, "active_user", "chinmaya") or "chinmaya"
            except Exception:
                username = "chinmaya"
            
            mm.set_preference(username, key, value, confidence=1.0, evidence=["legacy_memory_skill_write"])
        except Exception as e:
            print(f"[MemorySkill] Failed to sync preference to MemoryManager: {e}")

        return f"Saved preference {key} as: {value}."

    def get_preference(self, key, default=None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM preferences WHERE key = ?", (key.lower(),))
            row = cursor.fetchone()
        return row[0] if row else default

    # --- Personal Brain API ---
    def add_personal_note(self, category, content):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO personal_notes (category, content, created_at) VALUES (?, ?, ?)",
                (category.lower().strip(), content.strip(), now)
            )
            conn.commit()
        return f"I saved that under {category}."

    def get_personal_notes(self, category=None, limit=20):
        query = "SELECT category, content, created_at FROM personal_notes WHERE status = 'active'"
        params = []
        if category:
            query += " AND category = ?"
            params.append(category.lower().strip())
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()

    def log_activity(self, active_window, battery_percent=None, wifi_status=None):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO activity_log (active_window, battery_percent, wifi_status, created_at) VALUES (?, ?, ?, ?)",
                (active_window, battery_percent, wifi_status, now)
            )
            conn.commit()

    def get_recent_activity(self, limit=10):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT active_window, battery_percent, wifi_status, created_at FROM activity_log ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            return cursor.fetchall()

    def get_personal_brain_summary(self):
        notes = self.get_personal_notes(limit=12)
        activity = self.get_recent_activity(limit=5)

        parts = []
        if notes:
            lines = [f"- {cat}: {content}" for cat, content, _ in notes]
            parts.append("What I remember about you:\n" + "\n".join(lines))
        else:
            parts.append("I do not have personal notes about you yet.")

        if activity:
            lines = []
            for window, battery, wifi, created in activity:
                battery_txt = f"{battery}%" if battery is not None else "unknown battery"
                lines.append(f"- {created}: {window} ({battery_txt}, {wifi})")
            parts.append("Recent laptop activity:\n" + "\n".join(lines))

        reminders = self.get_pending_reminders()
        parts.append(reminders)
        return "\n\n".join(parts)

    def add_semantic_relation(self, source, relation, target, metadata=None):
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO semantic_graph (source, relation, target, metadata) VALUES (?, ?, ?, ?)",
                (source.strip(), relation.strip(), target.strip(), json.dumps(metadata) if metadata else None)
            )
            conn.commit()
        return f"Relation added: {source} --({relation})--> {target}"

    def get_semantic_connections(self, entity):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT relation, target, metadata FROM semantic_graph WHERE source = ?",
                (entity.strip(),)
            )
            forward = cursor.fetchall()
            cursor.execute(
                "SELECT source, relation, metadata FROM semantic_graph WHERE target = ?",
                (entity.strip(),)
            )
            backward = cursor.fetchall()
        return forward, backward

    def save_episode(self, goal, steps, outcome):
        import json
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO episodic_memory (goal, steps_json, outcome, created_at) VALUES (?, ?, ?, ?)",
                (goal.strip(), json.dumps(steps), outcome.strip(), now)
            )
            conn.commit()
        return "Episode logged successfully"

    def get_successful_episodes(self, goal_keyword):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT steps_json FROM episodic_memory WHERE goal LIKE ? AND outcome = 'success' ORDER BY id DESC LIMIT 3",
                (f"%{goal_keyword.strip()}%",)
            )
            return cursor.fetchall()

    def log_failure(self, goal, step, failure_type, action_attempted):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO failure_analytics (goal, step, failure_type, action_attempted, timestamp) VALUES (?, ?, ?, ?, ?)",
                (goal.strip(), step, failure_type.strip(), action_attempted.strip(), now)
            )
            conn.commit()
        return "Failure logged successfully"

    def add_task_tree_node(self, goal, task, status='pending', dependency=None, blocker=None, deadline=None, time_state='ongoing'):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO task_tree (goal_name, task_name, status, dependency, blocker, created_at, deadline, time_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (goal.strip(), task.strip(), status.strip().lower(), dependency.strip() if dependency else None, blocker.strip() if blocker else None, now, deadline, time_state)
            )
            conn.commit()
        return f"Task updated in database: {goal} -> {task} [{status}]"

    def compress_memories(self):
        """Compresses older activity logs and episodic runs into rolling summaries to prevent db bloat."""
        import datetime
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 1. Compress Activity Logs
                cursor.execute("SELECT COUNT(*) FROM activity_log")
                count = cursor.fetchone()[0]
                if count > 50:
                    cursor.execute("SELECT active_window, created_at FROM activity_log ORDER BY id ASC LIMIT ?", (count - 20,))
                    old_rows = cursor.fetchall()
                    summary_text = "Summary of older window activities: " + ", ".join([f"'{win}' at {ts}" for win, ts in old_rows])
                    # Delete old rows
                    cursor.execute("DELETE FROM activity_log WHERE id IN (SELECT id FROM activity_log ORDER BY id ASC LIMIT ?)", (count - 20,))
                    # Save single rolling summary note
                    cursor.execute(
                        "INSERT INTO personal_notes (category, content, status, created_at) VALUES (?, ?, ?, ?)",
                        ("System Archive", summary_text, "active", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
                    )
                    
                # 2. Compress Failure Analytics
                cursor.execute("SELECT COUNT(*) FROM failure_analytics")
                fail_count = cursor.fetchone()[0]
                if fail_count > 30:
                    cursor.execute("SELECT failure_type, goal FROM failure_analytics ORDER BY id ASC LIMIT ?", (fail_count - 10,))
                    old_fails = cursor.fetchall()
                    fail_summary = f"Archived {len(old_fails)} failures. Highlights: " + ", ".join([f"[{ft}] on goal '{g}'" for ft, g in old_fails[:5]])
                    cursor.execute("DELETE FROM failure_analytics WHERE id IN (SELECT id FROM failure_analytics ORDER BY id ASC LIMIT ?)", (fail_count - 10,))
                    cursor.execute(
                        "INSERT INTO personal_notes (category, content, status, created_at) VALUES (?, ?, ?, ?)",
                        ("System Archive", fail_summary, "active", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
                    )
                    
                conn.commit()
            print("[MemorySkill] Database context compression GC completed.")
            return "Memory compression completed"
        except Exception as e:
            print(f"[MemorySkill] Memory compression error: {e}")
            return str(e)

    def record_strategy_outcome(self, strategy_key, success=True, latency=1.0, interrupted=False, user_corrected=False, load_level=0.1):
        strategy_key = strategy_key.strip().lower()
        
        # Multi-Factor Reward Engine
        reward = 0.0
        if success:
            reward += 0.15
            # Speed bonus
            if latency < 2.0:
                reward += 0.05
            elif latency > 5.0:
                reward -= 0.05
        else:
            reward -= 0.3
            
        if interrupted:
            reward -= 0.1
        if user_corrected:
            reward -= 0.2
        if load_level > 0.6:
            reward -= 0.05

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT success_count, failure_count, weight FROM strategy_weights WHERE strategy_key = ?", (strategy_key,))
            row = cursor.fetchone()
            if row:
                success_count, failure_count, weight = row
                if success:
                    success_count += 1
                else:
                    failure_count += 1
                weight = max(min(weight + reward, 2.0), 0.1)
                cursor.execute(
                    "UPDATE strategy_weights SET success_count = ?, failure_count = ?, weight = ? WHERE strategy_key = ?",
                    (success_count, failure_count, weight, strategy_key)
                )
            else:
                success_count = 1 if success else 0
                failure_count = 0 if success else 1
                weight = max(min(1.0 + reward, 2.0), 0.1)
                cursor.execute(
                    "INSERT INTO strategy_weights (strategy_key, success_count, failure_count, weight) VALUES (?, ?, ?, ?)",
                    (strategy_key, success_count, failure_count, weight)
                )
            conn.commit()
        return f"Recorded strategy outcome for '{strategy_key}': success={success}, reward={reward:+.2f}, new weight={weight:.2f}"

    def record_counterfactual_update(self, failed_strategy, alternative_strategy):
        failed_strategy = failed_strategy.strip().lower()
        alternative_strategy = alternative_strategy.strip().lower()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Decay failed strategy further due to counterfactual confirmation
            cursor.execute("SELECT weight FROM strategy_weights WHERE strategy_key = ?", (failed_strategy,))
            row_fail = cursor.fetchone()
            w_fail = row_fail[0] if row_fail else 1.0
            new_w_fail = max(w_fail - 0.25, 0.1)
            cursor.execute("INSERT OR REPLACE INTO strategy_weights (strategy_key, weight) VALUES (?, ?)", (failed_strategy, new_w_fail))
            
            # 2. Boost alternative strategy counterfactually
            cursor.execute("SELECT weight FROM strategy_weights WHERE strategy_key = ?", (alternative_strategy,))
            row_alt = cursor.fetchone()
            w_alt = row_alt[0] if row_alt else 1.0
            new_w_alt = min(w_alt + 0.15, 2.0)
            cursor.execute("INSERT OR REPLACE INTO strategy_weights (strategy_key, weight) VALUES (?, ?)", (alternative_strategy, new_w_alt))
            
            conn.commit()
            
        return f"Counterfactual updated: '{failed_strategy}' decayed to {new_w_fail:.2f}, '{alternative_strategy}' boosted to {new_w_alt:.2f}." 

    def get_strategy_weights(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT strategy_key, success_count, failure_count, weight FROM strategy_weights ORDER BY weight DESC")
            rows = cursor.fetchall()
            return {r[0]: {"success": r[1], "failures": r[2], "weight": r[3]} for r in rows}


