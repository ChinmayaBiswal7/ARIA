"""
skills/drift_detector.py -- Phase 5B: Goal Drift Detector
==========================================================
Scans the project timeline ledger in SQLite across multiple capture types
(Git, System, User logs) to identify neglected or stalled projects.
Fully cp1252 safe.
"""

import os
import sqlite3
import time


class AriaDriftDetector:
    def __init__(self, db_path=None):
        repo_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = db_path or os.path.join(repo_path, "aria_memory.db")

    def analyze_drift(self, threshold_days=7) -> list:
        if not os.path.exists(self.db_path):
            return []

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            current_time = int(time.time())
            seconds_in_day = 86400

            # Grab the absolute latest activity stamp per tracked project/goal
            cursor.execute("""
                SELECT project_name, MAX(timestamp), source 
                FROM project_timeline 
                GROUP BY project_name
            """)
            rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            print(f"[DriftDetector] DB query failed: {e}")
            return []

        drift_reports = []
        for name, last_seen, source in rows:
            days_idle = (current_time - last_seen) / seconds_in_day
            if days_idle >= threshold_days:
                drift_reports.append({
                    "entity": name,
                    "days_idle": round(days_idle, 1),
                    "last_tracked_via": source or "Unknown"
                })

        return drift_reports
