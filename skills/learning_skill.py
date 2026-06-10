"""
skills/learning_skill.py — Study Preparation and Cognitive Orchestration Skill
=============================================================================
Manages syllabus parsing, notes retrieval, study guide compilation, and revision reminders.
"""

import json
import re
import os
import sqlite3
import datetime
from skills.active_context import ActiveContext

class AriaLearningSkill:
    def __init__(self, db_path="aria_memory.db"):
        self.db_path = db_path

    def fetch_notes(self, target: str) -> str:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT content FROM personal_notes WHERE status = 'active' AND (content LIKE ? OR category LIKE ?)",
                (f"%{target}%", f"%{target}%")
            )
            rows = cursor.fetchall()
            conn.close()
            return "\n".join([r[0] for r in rows])
        except Exception as e:
            print(f"[LearningSkill] Failed to query notes: {e}")
            return ""

    def compile_study_sheet(self, aria, target: str, notes_content: str, search_content: str) -> str:
        summary_prompt = (
            f"Create a concise, structured study/revision guide about: '{target}'.\n\n"
            f"Personal Notes Context:\n{notes_content[:1000]}\n\n"
            f"Web Search Context:\n{search_content[:1500]}\n\n"
            "Synthesize this context into high-yield bullet points. Limit to 300 words. No markdown fences."
        )
        summary_text = aria.brain.think(summary_prompt)
        os.makedirs("scratch", exist_ok=True)
        file_name = f"{target.replace(' ', '_').lower()}_study_guide.md"
        file_path = os.path.join("scratch", file_name)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(summary_text or "No content generated.")
        return file_name

    def orchestrate_study_goal(self, aria, goal_text: str) -> str:
        # 1. Update ActiveContext
        context = ActiveContext()
        context.current_goal = goal_text
        
        # 2. Decompose Goal
        prompt = (
            f"You are the central Cognitive Planner for ARIA. The user has a high-level goal: '{goal_text}'.\n"
            "Decompose this goal into a list of 3-5 structured subtasks that can be executed or scheduled.\n"
            "Each subtask should belong to one of these types:\n"
            "- 'search': to look up information on the web (e.g. syllabus, topics).\n"
            "- 'notes': to search personal notes for related study materials.\n"
            "- 'summarize': to generate a final summary sheet combining information.\n"
            "- 'reminder': to schedule a review time or revision deadline.\n\n"
            "You MUST output exactly one JSON object with fields 'goal', 'priority', and 'steps'.\n"
            "Each step must be an object with fields 'subtask_name', 'type', 'target', and 'scheduled_delay_seconds'.\n"
            "Do not include markdown tags like ```json. Return raw JSON text only.\n\n"
            "Example Format:\n"
            "{\n"
            '  "goal": "DBMS exam prep",\n'
            '  "priority": "high",\n'
            '  "steps": [\n'
            '    {"subtask_name": "Retrieve DBMS notes", "type": "notes", "target": "DBMS notes", "scheduled_delay_seconds": null},\n'
            '    {"subtask_name": "Search DBMS syllabus", "type": "search", "target": "DBMS syllabus", "scheduled_delay_seconds": null},\n'
            '    {"subtask_name": "Compile study guide", "type": "summarize", "target": "DBMS", "scheduled_delay_seconds": null},\n'
            '    {"subtask_name": "Schedule revision", "type": "reminder", "target": "Review DBMS guide", "scheduled_delay_seconds": 86400}\n'
            '  ]\n'
            "}"
        )

        try:
            print("[LearningSkill] Generating structured execution plan...")
            response = aria.brain.think(prompt)
            if not response:
                aria.safe_speak("Failed to generate a plan.")
                return "Failed to generate plan."

            # Parse JSON
            clean = response.strip()
            match = re.search(r"(\{.*\})", clean, re.DOTALL)
            if match:
                clean = match.group(1).strip()
            else:
                for marker in ("```json", "```"):
                    if clean.startswith(marker):
                        clean = clean[len(marker):]
                if clean.endswith("```"):
                    clean = clean[:-3]
                clean = clean.strip()

            plan_data = json.loads(clean)
            context.last_plan = plan_data
            
            steps = plan_data.get("steps", [])
            goal = plan_data.get("goal", goal_text)
            
            # Start ActiveTask graph
            task_manager = getattr(aria.brain, "semantic_router", None)
            if task_manager:
                task_manager = getattr(task_manager, "task_manager", None)
            
            active_task = None
            if task_manager:
                active_task = task_manager.start_task(goal)

            aria.safe_speak(f"Drafted a {plan_data.get('priority', 'normal')} priority plan with {len(steps)} steps. I will execute them now.")
            
            notes_content = ""
            search_content = ""
            
            for i, step in enumerate(steps):
                st_name = step.get("subtask_name")
                st_type = step.get("type")
                st_target = step.get("target")
                
                print(f"[LearningSkill] Step {i+1}: {st_name} ({st_type})")
                
                # Add step to graph
                task_step = None
                if active_task:
                    task_step = active_task.add_step(action=st_type, target=st_target)
                
                try:
                    if st_type == "notes":
                        notes_content = self.fetch_notes(st_target)
                        outcome = f"Fetched notes context: {len(notes_content)} characters found."
                        
                    elif st_type == "search":
                        search_content = aria.search_and_read(st_target)
                        outcome = f"Scraped search results: {len(search_content)} characters."
                        
                    elif st_type == "summarize":
                        file_name = self.compile_study_sheet(aria, st_target, notes_content, search_content)
                        outcome = f"Study guide generated and saved to scratch/{file_name}."
                        aria.safe_speak(f"I compiled a study sheet and saved it as {file_name} in your scratch folder.")
                        
                    elif st_type == "reminder":
                        delay = step.get("scheduled_delay_seconds") or 86400
                        due_time = (datetime.datetime.now() + datetime.timedelta(seconds=delay))
                        due_date_str = due_time.strftime("%Y-%m-%d")
                        due_time_str = due_time.strftime("%H:%M")
                        
                        aria.memory_skill.add_reminder(st_name, due_date=due_date_str, due_at=due_time_str)
                        outcome = f"Reminder set for {due_date_str} at {due_time_str}."
                        aria.safe_speak(f"Set a reminder to {st_name} for tomorrow.")
                        
                    else:
                        outcome = "Unknown step type skipped."
                        
                    # Complete step in graph
                    if active_task and task_step:
                        active_task.complete_step(result=outcome)
                        
                except Exception as step_err:
                    print(f"[LearningSkill] Error executing step '{st_name}': {step_err}")
                    if active_task and task_step:
                        task_step.fail(reason=str(step_err))
            
            if active_task:
                active_task.complete_task()
                
            aria.safe_speak("Goal orchestration complete. All tasks executed successfully.")
            return "Orchestration complete."

        except Exception as e:
            print(f"[LearningSkill] Goal orchestration failed: {e}")
            aria.safe_speak("Failed to execute goal orchestration.")
            return "Orchestration failed."
