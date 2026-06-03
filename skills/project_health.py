"""
skills/project_health.py — Phase 4C: Project Health Score Calculator
======================================================================
Calculates a 0–100 health score for each project using four dimensions:

    Activity Score  (0–25) — How recently and frequently has work happened?
    Momentum Score  (0–25) — What % of tasks are completed?
    Clarity Score   (0–25) — Is there a clear focus and next action?
    Risk Score      (0–25) — Are there active blockers pulling the score down?

The composite health score = Activity + Momentum + Clarity - Risk (clamped to [0, 100]).

Usage:
    from skills.project_health import ProjectHealthCalculator
    calc = ProjectHealthCalculator()
    score_info = calc.score_project("ARIA_Android_App")
    print(score_info["score"])      # e.g. 78
    print(score_info["summary"])    # "Strong momentum, one active blocker."

    all_scores = calc.score_all_projects()
"""

import os
import json
import time
import sqlite3

REPO_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS_FILE = os.path.join(REPO_PATH, "aria_projects.json")
DB_PATH = os.path.join(REPO_PATH, "aria_memory.db")

# --- Scoring constants ---
MAX_ACTIVITY_SCORE = 25
MAX_MOMENTUM_SCORE = 25
MAX_CLARITY_SCORE  = 25
MAX_RISK_PENALTY   = 25


def _get_timeline_events(project_name: str, days: int = 14) -> list:
    """Returns timeline events for a project within the past `days` days."""
    cutoff = int(time.time()) - days * 86400
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, event_type, importance
            FROM project_timeline
            WHERE project_name = ? AND timestamp >= ?
            ORDER BY timestamp DESC
        """, (project_name, cutoff))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"[ProjectHealth] DB error: {e}")
        return []


def _score_activity(events: list) -> tuple:
    """
    Returns (score, explanation) for activity dimension.
    Rewards: recency of last event + number of events in past 14 days.
    """
    if not events:
        return (0, "No activity in the last 14 days.")

    now = int(time.time())
    most_recent_ts = max(e[0] for e in events)
    days_since = (now - most_recent_ts) / 86400

    # Recency: 0 = today → 15 points; 7 days → 8 points; 14+ → 0 points
    recency_score = max(0, 15 - int(days_since * 15 / 14))

    # Frequency: 1 event → 2 pts, 5+ events → 10 pts
    freq_score = min(10, len(events) * 2)

    score = min(MAX_ACTIVITY_SCORE, recency_score + freq_score)
    explanation = f"{len(events)} event(s) in last 14 days, last {days_since:.1f}d ago."
    return (score, explanation)


def _score_momentum(project: dict) -> tuple:
    """
    Returns (score, explanation) for momentum dimension.
    Based on ratio of completed / (completed + pending) tasks.
    """
    completed = len(project.get("completed_tasks", []))
    pending   = len(project.get("pending_tasks", []))
    total     = completed + pending

    if total == 0:
        return (MAX_MOMENTUM_SCORE // 2, "No tasks defined; assuming neutral momentum.")

    ratio = completed / total
    score = int(ratio * MAX_MOMENTUM_SCORE)
    explanation = f"{completed}/{total} tasks complete ({int(ratio * 100)}%)."
    return (score, explanation)


def _score_clarity(project: dict) -> tuple:
    """
    Returns (score, explanation) for clarity dimension.
    Rewards having a non-empty current_focus and next_action.
    """
    score = 0
    parts = []

    focus = project.get("current_focus", "").strip()
    if focus and focus.lower() not in ["none", "unknown", ""]:
        score += 15
        parts.append(f"Focus: '{focus}'")
    else:
        parts.append("No current focus set.")

    next_action = project.get("next_action", "").strip()
    if next_action and next_action.lower() not in ["none", "unknown", ""]:
        score += 10
        parts.append(f"Next action defined.")
    else:
        parts.append("No next action set.")

    return (min(MAX_CLARITY_SCORE, score), " ".join(parts))


def _score_risk(project: dict, events: list) -> tuple:
    """
    Returns (penalty, explanation) for risk dimension.
    Penalizes for: active blockers + recent blocker events + no work in 7+ days.
    """
    penalty = 0
    parts = []

    # Active blockers from project data
    blockers = project.get("blockers", [])
    if blockers:
        blocker_penalty = min(15, len(blockers) * 8)
        penalty += blocker_penalty
        parts.append(f"{len(blockers)} active blocker(s).")

    # Check for unresolved blocker events in timeline (blockers logged but not resolved)
    recent_blocker_events = [e for e in events if e[1] == "blocker_added"]
    recent_resolve_events = [e for e in events if e[1] == "blocker_resolved"]
    net_blockers = max(0, len(recent_blocker_events) - len(recent_resolve_events))
    if net_blockers > 0 and not blockers:
        penalty += min(10, net_blockers * 5)
        parts.append(f"{net_blockers} unresolved blocker event(s) in timeline.")

    # Stale: no activity for 7+ days
    now = int(time.time())
    if events:
        most_recent_ts = max(e[0] for e in events)
        days_stale = (now - most_recent_ts) / 86400
    else:
        days_stale = 999

    if days_stale >= 7:
        stale_penalty = min(10, int(days_stale / 7) * 5)
        penalty += stale_penalty
        parts.append(f"Stale: no activity for {days_stale:.0f} days.")

    if not parts:
        parts.append("No risks detected.")

    return (min(MAX_RISK_PENALTY, penalty), " ".join(parts))


class ProjectHealthCalculator:
    """Calculates health scores for projects in aria_projects.json."""

    def score_project(self, project_name: str) -> dict:
        """
        Returns a dict with:
            score       (int 0–100)
            grade       (str: A/B/C/D/F)
            activity    (int)
            momentum    (int)
            clarity     (int)
            risk        (int, penalty)
            summary     (str)
            details     (dict with per-dimension explanations)
        """
        # Load project data
        try:
            with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
                all_projects = json.load(f).get("active_projects", {})
        except Exception:
            all_projects = {}

        project = all_projects.get(project_name, {})
        events = _get_timeline_events(project_name, days=14)

        activity_score, activity_exp = _score_activity(events)
        momentum_score, momentum_exp = _score_momentum(project)
        clarity_score,  clarity_exp  = _score_clarity(project)
        risk_penalty,   risk_exp     = _score_risk(project, events)

        raw_score = activity_score + momentum_score + clarity_score - risk_penalty
        score = max(0, min(100, raw_score))

        # Grade
        if score >= 85:
            grade = "A"
        elif score >= 70:
            grade = "B"
        elif score >= 55:
            grade = "C"
        elif score >= 40:
            grade = "D"
        else:
            grade = "F"

        # Generate a concise summary sentence
        blockers = project.get("blockers", [])
        pending  = project.get("pending_tasks", [])
        summary_parts = []
        if score >= 80:
            summary_parts.append("Project is in excellent shape.")
        elif score >= 60:
            summary_parts.append("Project is progressing well.")
        elif score >= 40:
            summary_parts.append("Project needs attention.")
        else:
            summary_parts.append("Project is at risk.")

        if blockers:
            summary_parts.append(f"{len(blockers)} blocker(s) active.")
        if pending:
            summary_parts.append(f"{len(pending)} task(s) remaining.")

        return {
            "project":  project_name,
            "score":    score,
            "grade":    grade,
            "activity": activity_score,
            "momentum": momentum_score,
            "clarity":  clarity_score,
            "risk":     risk_penalty,
            "summary":  " ".join(summary_parts),
            "details": {
                "activity": activity_exp,
                "momentum": momentum_exp,
                "clarity":  clarity_exp,
                "risk":     risk_exp
            }
        }

    def score_all_projects(self) -> list:
        """Returns a list of score dicts for all active projects, sorted by score descending."""
        try:
            with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
                all_projects = json.load(f).get("active_projects", {})
        except Exception:
            return []

        results = []
        for project_name in all_projects:
            results.append(self.score_project(project_name))

        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def get_health_context_string(self) -> str:
        """Returns a formatted string of all project health scores for LLM injection."""
        scores = self.score_all_projects()
        if not scores:
            return ""

        lines = ["== PROJECT HEALTH SCORES =="]
        for s in scores:
            lines.append(
                f"- {s['project']}: {s['score']}/100 (Grade {s['grade']}) — {s['summary']}"
            )
        return "\n".join(lines)
