"""
skills/priority_engine.py — Phase 4D: Project Priority Ranking Engine
=======================================================================
Calculates a ranked priority list from aria_projects.json using:

    Impact   (1–10): How much does this project matter to the overall goal?
    Urgency  (1–10): How time-sensitive is this right now?
    Blocking (1–10): Are other projects or systems blocked waiting on this?

Composite Priority Score = (impact × 0.40) + (urgency × 0.40) + (blocking × 0.20)

These scores can be embedded in aria_projects.json as a "priority" sub-dict,
or auto-inferred from project state (blockers list, pending tasks, last_worked_on).

Usage:
    from skills.priority_engine import PriorityEngine
    engine = PriorityEngine()

    # Get ranked list with scores
    ranked = engine.get_ranked_projects()
    for p in ranked:
        print(p["project"], p["priority_score"], p["reason"])

    # Get formatted briefing string (for LLM injection)
    briefing = engine.get_priority_briefing()
"""

import os
import json
import time

REPO_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS_FILE = os.path.join(REPO_PATH, "aria_projects.json")


def _auto_infer_impact(project_name: str, project: dict) -> float:
    """
    Auto-infers impact (1–10) from the number of pending tasks,
    tools involved, and keywords in the project name.
    Falls back to stored value if present.
    """
    stored = project.get("priority", {}).get("impact")
    if stored:
        return float(stored)

    score = 5.0  # baseline

    # More pending tasks → higher impact (up to +2)
    pending = len(project.get("pending_tasks", []))
    score += min(2.0, pending * 0.5)

    # More tools → higher impact (up to +1)
    tools = len(project.get("associated_tools", []))
    score += min(1.0, tools * 0.25)

    # Keywords that suggest high-impact
    high_impact_kw = ["android", "core", "voice", "brain", "integration", "app"]
    name_lower = project_name.lower()
    if any(kw in name_lower for kw in high_impact_kw):
        score += 1.5

    return min(10.0, score)


def _auto_infer_urgency(project: dict) -> float:
    """
    Auto-infers urgency (1–10) from:
    - Days since last_worked_on (stale → high urgency)
    - Presence of blockers
    - Project status
    Falls back to stored value if present.
    """
    stored = project.get("priority", {}).get("urgency")
    if stored:
        return float(stored)

    score = 5.0  # baseline

    # Days since last worked on
    last_worked = project.get("last_worked_on", "")
    if last_worked:
        try:
            last_ts = time.mktime(time.strptime(last_worked, "%Y-%m-%d"))
            days_since = (time.time() - last_ts) / 86400
            # Stale for 3+ days → higher urgency
            score += min(3.0, days_since * 0.5)
        except Exception:
            pass

    # Active blockers → high urgency
    blockers = project.get("blockers", [])
    if blockers:
        score += min(2.0, len(blockers) * 1.5)

    # Status keywords
    status = project.get("status", "").lower()
    if "block" in status:
        score += 2.0
    elif "complete" in status or "done" in status:
        score = max(1.0, score - 3.0)  # Less urgent if done

    return min(10.0, score)


def _auto_infer_blocking(project: dict, all_projects: dict) -> float:
    """
    Auto-infers blocking coefficient (1–10) by checking if other projects
    reference this one in their pending tasks or blockers.
    Falls back to stored value if present.
    """
    stored = project.get("priority", {}).get("blocking")
    if stored:
        return float(stored)

    # Count how many other projects reference this project's tasks/name
    blocking_count = 0
    # (Simple heuristic: not currently cross-referencing, so use pending task count
    #  as a proxy for blocking potential)
    pending_count = len(project.get("pending_tasks", []))
    blocking_count = min(5, pending_count)

    score = 1.0 + blocking_count
    return min(10.0, score)


def _composite_score(impact: float, urgency: float, blocking: float) -> float:
    """Returns the weighted composite priority score."""
    return round((impact * 0.40) + (urgency * 0.40) + (blocking * 0.20), 2)


def _generate_reason(project: dict, impact: float, urgency: float, blocking: float,
                     composite: float) -> str:
    """Generates a one-line human reason for the priority score."""
    reasons = []

    if urgency >= 8:
        reasons.append("high urgency")
    elif urgency >= 6:
        reasons.append("moderate urgency")

    if impact >= 8:
        reasons.append("high-impact")
    
    blockers = project.get("blockers", [])
    if blockers:
        reasons.append(f"{len(blockers)} blocker(s)")

    pending = len(project.get("pending_tasks", []))
    if pending > 0:
        reasons.append(f"{pending} task(s) pending")

    focus = project.get("current_focus", "")
    if focus and focus.lower() not in ["none", ""]:
        reasons.append(f"focus: {focus}")

    if not reasons:
        reasons.append("standard priority")

    return "; ".join(reasons).capitalize()


class PriorityEngine:
    """Ranks projects by composite priority score."""

    def _load_projects(self) -> dict:
        if not os.path.exists(PROJECTS_FILE):
            return {}
        with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("active_projects", {})

    def score_project(self, project_name: str, project: dict, all_projects: dict) -> dict:
        """Returns a priority dict for a single project."""
        impact   = _auto_infer_impact(project_name, project)
        urgency  = _auto_infer_urgency(project)
        blocking = _auto_infer_blocking(project, all_projects)
        composite = _composite_score(impact, urgency, blocking)
        reason = _generate_reason(project, impact, urgency, blocking, composite)

        return {
            "project":        project_name,
            "priority_score": composite,
            "impact":         impact,
            "urgency":        urgency,
            "blocking":       blocking,
            "reason":         reason,
            "focus":          project.get("current_focus", "Unknown"),
            "status":         project.get("status", "Unknown"),
            "blockers":       project.get("blockers", [])
        }

    def get_ranked_projects(self) -> list:
        """Returns all projects sorted by priority_score descending."""
        all_projects = self._load_projects()
        if not all_projects:
            return []

        ranked = []
        for name, details in all_projects.items():
            ranked.append(self.score_project(name, details, all_projects))

        ranked.sort(key=lambda x: x["priority_score"], reverse=True)
        return ranked

    def get_top_priority(self) -> dict:
        """Returns the single highest-priority project."""
        ranked = self.get_ranked_projects()
        return ranked[0] if ranked else {}

    def get_priority_briefing(self) -> str:
        """
        Returns a formatted multi-line string for LLM system prompt injection.
        Example output:
            == PRIORITY ENGINE — RANKED PROJECTS ==
            #1 ARIA_Android_App (Score: 8.2) — high urgency; focus: Native Android STT
            #2 ARIA_Core (Score: 6.4) — moderate urgency; 3 task(s) pending
        """
        ranked = self.get_ranked_projects()
        if not ranked:
            return ""

        lines = ["== PRIORITY ENGINE — RANKED PROJECTS =="]
        for i, p in enumerate(ranked, 1):
            blocker_note = f" ⛔ {len(p['blockers'])} blocker(s)" if p["blockers"] else ""
            lines.append(
                f"#{i} {p['project']} (Priority: {p['priority_score']}/10){blocker_note}"
                f"\n     Reason: {p['reason']}"
            )
        return "\n".join(lines)

    def update_project_priority(self, project_name: str, impact: int, urgency: int,
                                 blocking: int) -> str:
        """
        Manually sets priority overrides in aria_projects.json.
        These take precedence over auto-inferred values.
        """
        if not os.path.exists(PROJECTS_FILE):
            return "aria_projects.json not found."

        with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if project_name not in data.get("active_projects", {}):
            return f"Project '{project_name}' not found."

        data["active_projects"][project_name]["priority"] = {
            "impact":   max(1, min(10, impact)),
            "urgency":  max(1, min(10, urgency)),
            "blocking": max(1, min(10, blocking))
        }

        with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        composite = _composite_score(impact, urgency, blocking)
        return f"Priority updated for '{project_name}': Impact={impact}, Urgency={urgency}, Blocking={blocking} → Score={composite}"
