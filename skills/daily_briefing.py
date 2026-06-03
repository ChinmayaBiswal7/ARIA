"""
skills/daily_briefing.py — Phase 4E: Chief of Staff Daily Briefing
====================================================================
Synthesizes all Chief of Staff data into a structured verbal briefing
that ARIA delivers each morning (or on demand).

The briefing covers:
  1. Date & top-priority project
  2. Project health snapshot (all active projects)
  3. Ranked priority list with reasons
  4. Recent timeline momentum (last 3 events per project)
  5. Today's recommended actions (pending tasks from top project)
  6. Active blockers that need resolution

Usage:
    from skills.daily_briefing import DailyBriefing
    briefing = DailyBriefing()
    text = briefing.generate()   # Returns the full briefing as a string
    print(text)
"""

import os
import json
import time
import sqlite3

REPO_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS_FILE = os.path.join(REPO_PATH, "aria_projects.json")
DB_PATH = os.path.join(REPO_PATH, "aria_memory.db")


def _load_projects() -> dict:
    if not os.path.exists(PROJECTS_FILE):
        return {}
    with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("active_projects", {})


def _get_recent_timeline_events(project_name: str, limit: int = 3) -> list:
    """Returns the most recent timeline events for a project."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT datetime(timestamp, 'unixepoch', 'localtime'), event_type, description, importance
            FROM project_timeline
            WHERE project_name = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (project_name, limit))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"[DailyBriefing] DB error: {e}")
        return []


def _format_project_section(project_name: str, project: dict,
                              health_score: dict, priority: dict,
                              events: list) -> str:
    """Formats a single project's section of the briefing."""
    lines = []
    lines.append(f"▶ {project_name}")
    lines.append(f"  Health: {health_score.get('score', '?')}/100 (Grade {health_score.get('grade', '?')}) — {health_score.get('summary', '')}")
    lines.append(f"  Priority Score: {priority.get('priority_score', '?')}/10 — {priority.get('reason', '')}")
    lines.append(f"  Current Focus: {project.get('current_focus', 'None')}")
    
    pending = project.get("pending_tasks", [])
    if pending:
        pending_names = [t["task_name"] if isinstance(t, dict) else t for t in pending]
        lines.append(f"  Pending Tasks: {', '.join(pending_names[:3])}" + (" ..." if len(pending_names) > 3 else ""))
    
    blockers = project.get("blockers", [])
    if blockers:
        lines.append(f"  ⛔ BLOCKERS: {'; '.join(blockers)}")

    if events:
        lines.append("  Recent Timeline:")
        for ts_str, event_type, desc, importance in reversed(events):
            lines.append(f"    [{ts_str}] {event_type}: {desc[:80]}")
    
    return "\n".join(lines)


class DailyBriefing:
    """Generates the Chief of Staff daily briefing."""

    def generate(self, owner_name: str = "Chinmay") -> str:
        """
        Builds and returns the full text briefing. This string is designed
        to be read aloud by ARIA's TTS system.
        """
        from skills.project_health import ProjectHealthCalculator
        from skills.priority_engine import PriorityEngine

        # Load all data
        projects = _load_projects()
        if not projects:
            return f"Good morning, {owner_name}. I have no active projects to report on today."

        health_calc = ProjectHealthCalculator()
        priority_engine = PriorityEngine()

        health_scores = {name: health_calc.score_project(name) for name in projects}
        ranked_projects = priority_engine.get_ranked_projects()

        # Build header
        today_str = time.strftime("%A, %B %d, %Y")
        now_hour = time.localtime().tm_hour
        if now_hour < 12:
            greeting = "Good morning"
        elif now_hour < 18:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"

        top_project = ranked_projects[0] if ranked_projects else None

        lines = []
        lines.append(f"{greeting}, {owner_name}. Today is {today_str}.")
        lines.append("")

        # Top priority callout
        if top_project:
            lines.append(
                f"Your highest priority right now is {top_project['project'].replace('_', ' ')}. "
                f"Priority score: {top_project['priority_score']}/10. "
                f"Reason: {top_project['reason']}."
            )
            lines.append("")

        # Project sections
        lines.append("─── Project Status ───")
        for pr in ranked_projects:
            name = pr["project"]
            project_data = projects.get(name, {})
            health = health_scores.get(name, {"score": 0, "grade": "?", "summary": ""})
            events = _get_recent_timeline_events(name, limit=2)
            lines.append("")
            lines.append(_format_project_section(name, project_data, health, pr, events))

        lines.append("")
        lines.append("─── Today's Recommended Actions ───")

        # Recommendations from top priority project
        if top_project:
            name = top_project["project"]
            project_data = projects.get(name, {})
            pending = project_data.get("pending_tasks", [])
            next_action = project_data.get("next_action", "")
            
            if next_action and next_action.lower() not in ["none", ""]:
                lines.append(f"  1. {next_action}")
            
            pending_names = [t["task_name"] if isinstance(t, dict) else t for t in pending]
            for i, task in enumerate(pending_names[:3], start=2 if next_action else 1):
                lines.append(f"  {i}. {task}")

        # Blocker summary across all projects
        all_blockers = []
        for name, proj in projects.items():
            for blocker in proj.get("blockers", []):
                all_blockers.append(f"{name.replace('_', ' ')}: {blocker}")

        if all_blockers:
            lines.append("")
            lines.append("─── Active Blockers Requiring Attention ───")
            for b in all_blockers:
                lines.append(f"  ⛔ {b}")

        lines.append("")
        lines.append("That's your briefing for today. Ready to work when you are.")
        return "\n".join(lines)

    def generate_short(self, owner_name: str = "Chinmay") -> str:
        """
        Generates a concise verbal-only briefing suitable for TTS without
        markdown formatting — natural speech version.
        """
        from skills.project_health import ProjectHealthCalculator
        from skills.priority_engine import PriorityEngine

        projects = _load_projects()
        if not projects:
            return f"Good morning, {owner_name}. No active projects found."

        health_calc = ProjectHealthCalculator()
        priority_engine = PriorityEngine()
        ranked = priority_engine.get_ranked_projects()

        today_str = time.strftime("%A, %B %d")
        now_hour = time.localtime().tm_hour
        greeting = "Good morning" if now_hour < 12 else ("Good afternoon" if now_hour < 18 else "Good evening")

        parts = [f"{greeting}, {owner_name}. Today is {today_str}."]

        if ranked:
            top = ranked[0]
            top_name = top["project"].replace("_", " ")
            parts.append(
                f"Your top priority today is {top_name}, with a priority score of "
                f"{top['priority_score']} out of 10. {top['reason']}."
            )

        # Health summary
        for p in ranked:
            name = p["project"]
            h = health_calc.score_project(name)
            project_data = projects.get(name, {})
            pending_count = len(project_data.get("pending_tasks", []))
            blockers = project_data.get("blockers", [])
            focus = project_data.get("current_focus", "unknown")

            part = f"{name.replace('_', ' ')} is at {h['score']} out of 100 health. Current focus: {focus}."
            if pending_count:
                part += f" {pending_count} task(s) remaining."
            if blockers:
                part += f" Warning: {len(blockers)} active blocker(s)."
            parts.append(part)

        # Next action
        if ranked:
            top_data = projects.get(ranked[0]["project"], {})
            next_action = top_data.get("next_action", "")
            if next_action and next_action.lower() not in ["none", ""]:
                parts.append(f"Recommended first action: {next_action}")

        parts.append("That's your briefing. I'm ready when you are.")
        return " ".join(parts)
