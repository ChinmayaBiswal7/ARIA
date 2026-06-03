"""
skills/weekly_review.py -- Phase 5C: Sunday Weekly Review Analyzer
==================================================================
Compiles rolling 7-day project velocity trends, accomplishments, active blockers,
and highlights momentum winners and most neglected projects.
Fully cp1252 safe.
"""

import os
import json
import sqlite3
import time


class AriaWeeklyReview:
    def __init__(self, db_path=None, json_path=None):
        repo_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = db_path or os.path.join(repo_path, "aria_memory.db")
        self.json_path = json_path or os.path.join(repo_path, "aria_projects.json")

    def load_active_projects(self) -> list:
        if not os.path.exists(self.json_path):
            return []
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                return list(json.load(f).get("active_projects", {}).keys())
        except Exception:
            return []

    def compile_weekly_report(self) -> str:
        active_projects = self.load_active_projects()
        if not active_projects:
            return "== WEEKLY EXECUTIVE REVIEW ==\nNo active projects configured."

        one_week_ago = int(time.time()) - (7 * 86400)
        completed_tasks = []
        new_blockers = []
        project_activity = {name: {"events": 0, "completed": 0} for name in active_projects}

        if os.path.exists(self.db_path):
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # Fetch recent events
                cursor.execute("""
                    SELECT project_name, event_type, description, timestamp
                    FROM project_timeline 
                    WHERE timestamp > ?
                """, (one_week_ago,))
                events = cursor.fetchall()
                conn.close()

                for proj_name, event_type, desc, ts in events:
                    if proj_name in project_activity:
                        project_activity[proj_name]["events"] += 1
                        if event_type == "task_completed":
                            project_activity[proj_name]["completed"] += 1
                            completed_tasks.append((proj_name, desc))
                        elif event_type == "blocker_added":
                            new_blockers.append((proj_name, desc))
            except Exception as e:
                return f"== WEEKLY EXECUTIVE REVIEW ==\nFailed to compile velocity reports: {e}"

        # Determine winner and loser
        # Sort projects by activity events descending
        activity_sorted = sorted(project_activity.items(), key=lambda x: x[1]["events"], reverse=True)
        
        winner_name, winner_stats = activity_sorted[0]
        winner = winner_name if winner_stats["events"] > 0 else None
        
        # Neglected (lowest events)
        loser_name, loser_stats = activity_sorted[-1]
        loser = loser_name if (loser_name != winner or len(activity_sorted) > 1) else None

        # Build output review string
        report = "== SUNDAY EXECUTIVE WEEKLY REVIEW ==\n"
        
        # Accomplishments section
        report += "Accomplishments This Week:\n"
        if completed_tasks:
            for proj, desc in completed_tasks:
                report += f"  [OK] [{proj}] {desc}\n"
        else:
            report += "  - No tasks checked off this week.\n"

        # Blockers section
        report += "\nActive Bottlenecks & Risks:\n"
        if new_blockers:
            for proj, desc in new_blockers:
                report += f"  [BLOCKER] [{proj}] {desc}\n"
        else:
            report += "  - Clean sheet. No new bottlenecks logged.\n"

        # Momentum leaders/laggards
        report += "\nVelocity & Momentum Analysis:\n"
        if winner:
            report += f"  - Momentum Winner: {winner} (+{winner_stats['events']} updates, {winner_stats['completed']} completed tasks)\n"
        else:
            report += "  - Momentum Winner: None (No updates logged this week)\n"

        if loser:
            report += f"  - Most Neglected:  {loser} ({loser_stats['events']} updates this week)\n"

        return report
