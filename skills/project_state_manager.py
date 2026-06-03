"""
skills/project_state_manager.py -- Phase 4B: Project State API with Auto-Logging
==================================================================================
Provides a unified API to update aria_projects.json AND automatically log
the change as a timeline event. This is the single source of truth for project
mutations so that every change creates a timeline record.

Usage:
    from skills.project_state_manager import ProjectStateManager
    psm = ProjectStateManager()

    # Mark a task complete
    psm.complete_task("ARIA_Android_App", "Native Android STT")

    # Update current focus
    psm.update_focus("ARIA_Android_App", "Face confidence tuning")

    # Add a blocker
    psm.add_blocker("ARIA_Android_App", "Android SDK missing libcurl dependency")

    # Log a milestone manually
    psm.log_milestone("ARIA_Android_App", "Phase 4 Chief of Staff architecture complete")
"""

import os
import json
import time

REPO_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS_FILE = os.path.join(REPO_PATH, "aria_projects.json")


class ProjectStateManager:
    """Manages project state in aria_projects.json and auto-logs timeline events."""

    def _load(self) -> dict:
        """Loads aria_projects.json, returning the parsed dict."""
        if not os.path.exists(PROJECTS_FILE):
            return {"active_projects": {}}
        with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data: dict):
        """Saves the given dict back to aria_projects.json."""
        with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _get_project(self, project_name: str) -> dict:
        """Returns the project dict, raising KeyError if not found."""
        data = self._load()
        projects = data.get("active_projects", {})
        if project_name not in projects:
            raise KeyError(f"Project '{project_name}' not found in aria_projects.json")
        return projects[project_name]

    def _log(self, project_name: str, event_type: str, description: str,
              importance: int = 6, source: str = "ProjectStateManager", metadata: dict = None):
        """Logs an event to the project_timeline table in SQLite."""
        try:
            from skills.memory_skill import MemorySkill
            MemorySkill().log_timeline_event(
                project_name=project_name,
                event_type=event_type,
                description=description,
                source=source,
                importance=importance,
                metadata=metadata
            )
        except Exception as e:
            print(f"[ProjectStateManager] Timeline log failed: {e}")

    # ----------------------------------------------------------------------
    # Task Management
    # ----------------------------------------------------------------------

    def complete_task(self, project_name: str, task_name: str) -> str:
        """Moves a task from pending_tasks to completed_tasks, logs the event."""
        data = self._load()
        project = data["active_projects"].get(project_name)
        if not project:
            return f"Project '{project_name}' not found."
        
        pending = project.get("pending_tasks", [])
        completed = project.get("completed_tasks", [])
        
        task_name_str = task_name["task_name"] if isinstance(task_name, dict) else task_name

        match_task = None
        for t in pending:
            name = t["task_name"] if isinstance(t, dict) else t
            if name.lower() == task_name_str.lower():
                match_task = t
                break
        
        if match_task is not None:
            pending.remove(match_task)
            clean_name = match_task["task_name"] if isinstance(match_task, dict) else match_task
            if clean_name not in completed:
                completed.append(clean_name)
            project["pending_tasks"] = pending
            project["completed_tasks"] = completed
            project["last_worked_on"] = time.strftime("%Y-%m-%d")
            data["active_projects"][project_name] = project
            self._save(data)
            msg = f"Task completed: '{clean_name}'"
            
            # Check for next action
            next_action = project.get("next_action", "").strip()
            meta = {"task": clean_name}
            if next_action and next_action.lower() not in ["none", "unknown", ""]:
                meta["next_action"] = next_action
                
            self._log(project_name, "task_completed", msg, importance=8,
                      metadata=meta)
            
            # Update decision_history for matching pending tasks
            try:
                import sqlite3
                db_path = os.path.join(REPO_PATH, "aria_memory.db")
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE decision_history 
                    SET status = 'completed', completed_at = ? 
                    WHERE project_name = ? AND task_name = ? AND status = 'pending'
                """, (int(time.time()), project_name, clean_name))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"[ProjectStateManager] Failed to update decision history: {e}")
                
            print(f"[ProjectStateManager] [OK] {project_name}: {msg}")
            return msg
        elif task_name in completed:
            return f"Task '{task_name}' was already completed."
        else:
            return f"Task '{task_name}' not found in pending tasks for '{project_name}'."

    def add_task(self, project_name: str, task_name: str, estimated_hours: float = 5, is_blocking: bool = False, impact: int = None) -> str:
        """Adds a new pending task to the project."""
        data = self._load()
        project = data["active_projects"].get(project_name)
        if not project:
            return f"Project '{project_name}' not found."
        
        pending = project.get("pending_tasks", [])
        
        # If task_name is a dict, extract its values, fallback to parameters
        if isinstance(task_name, dict):
            task_name_str = task_name.get("task_name", "Unnamed Task")
            estimated_hours = task_name.get("estimated_hours", estimated_hours)
            is_blocking = task_name.get("is_blocking", is_blocking)
            impact = task_name.get("impact", impact)
        else:
            task_name_str = task_name

        exists = False
        for t in pending:
            name = t["task_name"] if isinstance(t, dict) else t
            if name.lower() == task_name_str.lower():
                exists = True
                break
        
        if not exists:
            task_obj = {
                "task_name": task_name_str,
                "estimated_hours": estimated_hours,
                "is_blocking": is_blocking
            }
            if impact is not None:
                task_obj["impact"] = impact
            pending.append(task_obj)
            project["pending_tasks"] = pending
            project["last_worked_on"] = time.strftime("%Y-%m-%d")
            data["active_projects"][project_name] = project
            self._save(data)
            msg = f"New task added: '{task_name_str}'"
            self._log(project_name, "task_added", msg, importance=5,
                      metadata={
                          "task": task_name_str,
                          "estimated_hours": estimated_hours,
                          "is_blocking": is_blocking
                      })
            print(f"[ProjectStateManager] + {project_name}: {msg}")
            return msg
        return f"Task '{task_name_str}' already exists."

    # ----------------------------------------------------------------------
    # Focus & Status Updates
    # ----------------------------------------------------------------------

    def update_focus(self, project_name: str, new_focus: str) -> str:
        """Updates the current_focus field and logs the shift."""
        data = self._load()
        project = data["active_projects"].get(project_name)
        if not project:
            return f"Project '{project_name}' not found."
        
        old_focus = project.get("current_focus", "None")
        project["current_focus"] = new_focus
        project["last_worked_on"] = time.strftime("%Y-%m-%d")
        data["active_projects"][project_name] = project
        self._save(data)
        
        msg = f"Focus shifted from '{old_focus}' -> '{new_focus}'"
        self._log(project_name, "focus_shift", msg, importance=7,
                  metadata={"from": old_focus, "to": new_focus})
        print(f"[ProjectStateManager] [FOCUS] {project_name}: {msg}")
        return msg

    def update_session_summary(self, project_name: str, summary: str, next_action: str = None) -> str:
        """Updates last_session_summary (and optionally next_action)."""
        data = self._load()
        project = data["active_projects"].get(project_name)
        if not project:
            return f"Project '{project_name}' not found."
        
        project["last_session_summary"] = summary
        if next_action:
            project["next_action"] = next_action
        project["last_worked_on"] = time.strftime("%Y-%m-%d")
        data["active_projects"][project_name] = project
        self._save(data)
        
        self._log(project_name, "session_summary", summary, importance=6)
        return "Session summary updated."

    def set_status(self, project_name: str, status: str) -> str:
        """Updates the project status (e.g., 'In Progress', 'Blocked', 'Complete')."""
        data = self._load()
        project = data["active_projects"].get(project_name)
        if not project:
            return f"Project '{project_name}' not found."
        
        old_status = project.get("status", "Unknown")
        project["status"] = status
        data["active_projects"][project_name] = project
        self._save(data)
        
        importance = 9 if "block" in status.lower() or "complete" in status.lower() else 6
        msg = f"Status changed from '{old_status}' -> '{status}'"
        self._log(project_name, "status_change", msg, importance=importance,
                  metadata={"from": old_status, "to": status})
        return msg

    # ----------------------------------------------------------------------
    # Blockers
    # ----------------------------------------------------------------------

    def add_blocker(self, project_name: str, blocker_description: str) -> str:
        """Logs a blocker event and updates the blockers list."""
        data = self._load()
        project = data["active_projects"].get(project_name)
        if not project:
            return f"Project '{project_name}' not found."
        
        blockers = project.get("blockers", [])
        if blocker_description not in blockers:
            blockers.append(blocker_description)
        project["blockers"] = blockers
        data["active_projects"][project_name] = project
        self._save(data)
        
        msg = f"BLOCKER: {blocker_description}"
        self._log(project_name, "blocker_added", msg, importance=9,
                  metadata={"blocker": blocker_description})
        print(f"[ProjectStateManager] [BLOCKER] {project_name}: {msg}")
        return msg

    def resolve_blocker(self, project_name: str, blocker_description: str) -> str:
        """Removes a blocker and logs its resolution."""
        data = self._load()
        project = data["active_projects"].get(project_name)
        if not project:
            return f"Project '{project_name}' not found."
        
        blockers = project.get("blockers", [])
        if blocker_description in blockers:
            blockers.remove(blocker_description)
            project["blockers"] = blockers
            data["active_projects"][project_name] = project
            self._save(data)
            msg = f"Blocker resolved: '{blocker_description}'"
            self._log(project_name, "blocker_resolved", msg, importance=8,
                      metadata={"blocker": blocker_description})
            print(f"[ProjectStateManager] [OK] {project_name}: {msg}")
            return msg
        return f"Blocker '{blocker_description}' not found in project."

    # ----------------------------------------------------------------------
    # Milestones & New Projects
    # ----------------------------------------------------------------------

    def log_milestone(self, project_name: str, milestone: str, importance: int = 9) -> str:
        """Logs a major milestone event to the timeline."""
        self._log(project_name, "milestone", milestone, importance=importance,
                  metadata={"milestone": milestone})
        print(f"[ProjectStateManager] [MILESTONE] {project_name}: MILESTONE -- {milestone}")
        return f"Milestone logged: '{milestone}'"

    def create_project(self, project_name: str, focus: str, tools: list = None,
                       pending_tasks: list = None) -> str:
        """Creates a new project entry in aria_projects.json and logs it."""
        data = self._load()
        if project_name in data.get("active_projects", {}):
            return f"Project '{project_name}' already exists."
        
        normalized_pending = []
        for t in (pending_tasks or []):
            if isinstance(t, str):
                normalized_pending.append({
                    "task_name": t,
                    "estimated_hours": 5,
                    "is_blocking": False
                })
            else:
                normalized_pending.append(t)

        data.setdefault("active_projects", {})[project_name] = {
            "status": "In Progress",
            "current_focus": focus,
            "associated_tools": tools or [],
            "pending_tasks": normalized_pending,
            "completed_tasks": [],
            "blockers": [],
            "last_worked_on": time.strftime("%Y-%m-%d"),
            "last_session_summary": "Project created.",
            "next_action": focus
        }
        self._save(data)
        msg = f"Project '{project_name}' created. Focus: {focus}"
        self._log(project_name, "project_started", msg, importance=10,
                  metadata={"focus": focus, "tools": tools})
        print(f"[ProjectStateManager] [LAUNCH] {msg}")
        return msg

    # ----------------------------------------------------------------------
    # Read Helpers
    # ----------------------------------------------------------------------

    def get_all_projects(self) -> dict:
        """Returns the full active_projects dict."""
        return self._load().get("active_projects", {})

    def get_project_blockers(self, project_name: str) -> list:
        """Returns the list of active blockers for a project."""
        data = self._load()
        project = data.get("active_projects", {}).get(project_name, {})
        return project.get("blockers", [])
