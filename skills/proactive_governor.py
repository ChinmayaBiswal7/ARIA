import sqlite3
import time
import os
from skills.active_context import ActiveContext

class AriaProactiveGovernor:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path="aria_memory.db"):
        self.db_path = db_path
        self._init_db()
        if self._initialized:
            return
        self.last_alert_time = 0
        self.COOLDOWN = 14400  # 4 hours cooldown
        self._initialized = True

    def _init_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS governor_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            cursor.execute("INSERT OR IGNORE INTO governor_state (key, value) VALUES ('receptiveness_score', '5.0')")
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Governor] DB init failed: {e}")

    def get_receptiveness_score(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM governor_state WHERE key = 'receptiveness_score'")
            row = cursor.fetchone()
            conn.close()
            if row:
                return float(row[0])
        except Exception as e:
            print(f"[Governor] Failed to read receptiveness score: {e}")
        return 5.0

    def set_receptiveness_score(self, score):
        score = max(0.0, min(10.0, score))
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO governor_state (key, value) VALUES ('receptiveness_score', ?)", (str(score),))
            conn.commit()
            conn.close()
            print(f"[Governor] Receptiveness score set to {score:.1f}")
        except Exception as e:
            print(f"[Governor] Failed to write receptiveness score: {e}")

    def log_feedback(self, feedback_text):
        from skills.command_patterns import FEEDBACK_NEGATIVE_WORDS, FEEDBACK_POSITIVE_WORDS
        f = feedback_text.lower().strip()

        score = self.get_receptiveness_score()
        if any(w in f for w in FEEDBACK_NEGATIVE_WORDS):
            score -= 1.0
            self.set_receptiveness_score(score)
        elif any(w in f for w in FEEDBACK_POSITIVE_WORDS):
            score += 1.0
            self.set_receptiveness_score(score)

    def evaluate_context(self, aria, active_window_title):
        if not active_window_title:
            return None

        # Update ActiveContext
        context = ActiveContext()
        context.active_window = active_window_title

        score = self.get_receptiveness_score()
        if score < 3.0:
            print(f"[Governor] Receptiveness score is {score:.1f} (< 3.0). Proactive alert suppressed.")
            return None

        current_time = int(time.time())
        window_lower = active_window_title.lower()

        # 1. Gaming check
        is_gaming = any(g in window_lower for g in ["valorant", "minecraft", "steam"])
        if is_gaming and (current_time - self.last_alert_time) > self.COOLDOWN:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT title, timestamp FROM life_calendar 
                    WHERE event_type = 'academic_exam' AND timestamp > ?
                    ORDER BY timestamp ASC LIMIT 1
                """, (current_time,))
                exam = cursor.fetchone()
                if exam and (exam[1] - current_time) <= 3 * 86400:
                    self.last_alert_time = current_time
                    aria._last_proactive_warning_time = time.time()
                    days_left = max(1, int((exam[1] - current_time) / 86400))
                    
                    alert_phrase = (
                        f"Chinmay, I notice you are opening a leisure track. However, our calendar "
                        f"shows your '{exam[0]}' exam is approaching in {days_left} days. "
                        f"Active Academic Guard recommends jumping back onto problem-solving reviews tonight."
                    )
                    aria.safe_speak(alert_phrase)
                    aria.episodic_memory.record(
                        username="chinmaya",
                        event_text=f"Proactive alert: Warned user about gaming before exam '{exam[0]}'.",
                        importance=0.7,
                        source="observed"
                    )
                    return alert_phrase
            except Exception as err:
                print(f"[Governor] Query error: {err}")
            finally:
                conn.close()

        # 2. Coding check
        is_coding = any(c in window_lower for c in ["vs code", "visual studio code"])
        if is_coding:
            if not getattr(aria, "workspace_welcome_greeted", False):
                aria.workspace_welcome_greeted = True
                proj_name = "ARIA"
                welcome = f"Welcome back to your workspace, Chinmay. Resuming our development path on the '{proj_name}' project."
                aria.safe_speak(welcome)
                return welcome

        return None
