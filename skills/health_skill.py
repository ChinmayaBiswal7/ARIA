import sqlite3
import datetime
import time
import os

DB_PATH = "aria_memory.db"

class HealthSkill:
    """Manages SQLite storage and summaries for daily fitness and health metrics synced from Health Connect."""
    
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Initializes the health_data SQLite table if it does not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS health_data (
                    date TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    steps INTEGER DEFAULT 0,
                    calories REAL DEFAULT 0.0,
                    sleep_hours REAL DEFAULT 0.0,
                    sleep_quality TEXT DEFAULT 'Unknown',
                    heart_rate INTEGER DEFAULT 0,
                    spo2 REAL DEFAULT 0.0
                )
            """)
            conn.commit()

    def save_fitness_metrics(self, steps=0, calories=0.0, sleep_hours=0.0, sleep_quality="Unknown", heart_rate=0, spo2=0.0, timestamp=None):
        """Saves daily fitness metrics. Merges incoming data with existing records for the same day to prevent overwrites of non-zero stats."""
        if timestamp is None:
            timestamp = time.time()

        # Get local date string YYYY-MM-DD
        date_str = datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if we already have data for today to merge
            cursor.execute("""
                SELECT steps, calories, sleep_hours, sleep_quality, heart_rate, spo2 
                FROM health_data WHERE date = ?
            """, (date_str,))
            existing = cursor.fetchone()

            if existing:
                # Merge logic: if incoming is zero or empty, but DB has non-zero, keep DB value
                db_steps, db_calories, db_sleep, db_quality, db_hr, db_spo2 = existing
                
                if steps == 0 and db_steps > 0:
                    steps = db_steps
                if calories == 0.0 and db_calories > 0.0:
                    calories = db_calories
                if sleep_hours == 0.0 and db_sleep > 0.0:
                    sleep_hours = db_sleep
                if (sleep_quality == "Unknown" or not sleep_quality) and db_quality != "Unknown":
                    sleep_quality = db_quality
                if heart_rate == 0 and db_hr > 0:
                    heart_rate = db_hr
                if spo2 == 0.0 and db_spo2 > 0.0:
                    spo2 = db_spo2

            cursor.execute("""
                INSERT OR REPLACE INTO health_data (date, timestamp, steps, calories, sleep_hours, sleep_quality, heart_rate, spo2)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (date_str, timestamp, steps, float(calories), float(sleep_hours), sleep_quality, heart_rate, float(spo2)))
            conn.commit()
            
        return f"Successfully saved health data for {date_str}."

    def get_latest_metrics(self):
        """Fetches the latest day's health records."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM health_data ORDER BY date DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def get_recent_history(self, limit=7):
        """Fetches historical records sorted by date descending."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM health_data ORDER BY date DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_rolling_biometric_stats(self, limit_days=7) -> dict:
        """Computes rolling averages for sleep and activity metrics from health_data."""
        history = self.get_recent_history(limit=limit_days)
        if not history:
            return {
                "rolling_sleep_avg": 7.5,
                "sleep_debt": 0.0,
                "rolling_steps_avg": 5000
            }
        
        sleep_hours_list = [h["sleep_hours"] for h in history if h.get("sleep_hours") is not None]
        steps_list = [h["steps"] for h in history if h.get("steps") is not None]
        
        rolling_sleep_avg = sum(sleep_hours_list) / len(sleep_hours_list) if sleep_hours_list else 7.5
        rolling_steps_avg = sum(steps_list) / len(steps_list) if steps_list else 5000
        
        # Cumulative sleep debt against a standard 7.5-hour target per night
        expected_sleep = len(history) * 7.5
        actual_sleep = sum([h.get("sleep_hours") or 0.0 for h in history])
        sleep_debt = max(0.0, round(expected_sleep - actual_sleep, 2))
        
        return {
            "rolling_sleep_avg": round(rolling_sleep_avg, 2),
            "sleep_debt": sleep_debt,
            "rolling_steps_avg": int(rolling_steps_avg)
        }

    def generate_summary(self):
        """Generates a text summary of the latest health status to inject into ARIA's prompt context."""
        latest = self.get_latest_metrics()
        if not latest:
            return "No health or fitness data synced yet."

        history = self.get_recent_history(limit=5)
        
        # Build prompt context string
        summary_lines = []
        summary_lines.append("== USER FITNESS & HEALTH DATA (Health Connect Sync) ==")
        
        # Today / Latest stats
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        is_today = latest["date"] == today_str
        day_label = "Today" if is_today else f"Latest ({latest['date']})"
        
        summary_lines.append(f"{day_label}:")
        summary_lines.append(f"  - Steps: {latest['steps']:,} steps")
        summary_lines.append(f"  - Active Calories: {latest['calories']:.1f} kcal")
        summary_lines.append(f"  - Sleep: {latest['sleep_hours']:.1f} hrs (Quality: {latest['sleep_quality']})")
        summary_lines.append(f"  - Heart Rate: {latest['heart_rate']} bpm (average/latest)")
        summary_lines.append(f"  - SpO2 (Oxygen Level): {latest['spo2']:.1f}%")
        
        if len(history) > 1:
            summary_lines.append("\nRecent History:")
            for h in history[1:]:
                summary_lines.append(
                    f"  - {h['date']}: {h['steps']:,} steps | {h['calories']:.0f} kcal | "
                    f"Sleep: {h['sleep_hours']:.1f} hrs ({h['sleep_quality']}) | HR: {h['heart_rate']} bpm"
                )
                
        return "\n".join(summary_lines)
