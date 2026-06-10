"""
skills/personal_coach.py — Sprint P8: Personal AI Coach Agent for ARIA
======================================================================
Actively monitors active campaigns and tasks, computes deterministic progress/schedule risks,
monitors habits and predictions, and schedules proactive daily briefings and weekly reviews.
"""

import sqlite3
import json
import time
import os
import re
import threading
from typing import Dict, Any, List

from skills.base_agent import BaseAgent


class AriaPersonalCoach(BaseAgent):
    def __init__(self, aria_instance, db_path: str = "aria_orchestrator.db"):
        super().__init__("PersonalCoachAgent", aria_instance)
        self.db_path = db_path
        self._running = True
        self._thread = threading.Thread(target=self._background_loop, name="PersonalCoachBackground", daemon=True)
        self._thread.start()
        print("[PersonalCoach] Background daemon active (schedules morning/evening/weekly loops).")

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        self.log_state_shift("RUNNING", f"Executing coach request: {task_description}")
        
        brief_type = payload.get("type", "daily_brief")
        if brief_type not in ("daily_brief", "evening_review", "weekly_review"):
            brief_type = "daily_brief"
            
        brief = self.run_briefing_flow(brief_type)
        
        self.log_state_shift("IDLE", f"Coach request complete. Type: {brief_type}")
        return brief

    def stop(self):
        self._running = False
        if self._thread:
            try:
                self._thread.join(timeout=1.0)
            except Exception:
                pass
            print("[PersonalCoach] Background daemon stopped.")

    def _background_loop(self):
        tick_seconds = 600  # 10 minutes
        
        while self._running:
            try:
                self.check_and_trigger_scheduled_briefs(time.time())
            except Exception as e:
                print(f"[PersonalCoach] Background scheduler error: {e}")
                
            # Sleep in 1-second chunks to exit quickly if thread is stopped
            for _ in range(tick_seconds):
                if not self._running:
                    break
                time.sleep(1)

    def check_and_trigger_scheduled_briefs(self, current_time: float):
        lt = time.localtime(current_time)
        
        # Morning Brief: >= 08:00
        if lt.tm_hour >= 8:
            date_str = time.strftime("%Y_%m_%d", lt)
            key = f"daily_brief_{date_str}"
            from skills.blackboard import AriaBlackboard
            blackboard = AriaBlackboard()
            if blackboard.read("coach", key) is None:
                print(f"[PersonalCoach] Running scheduled Morning Brief for {date_str}...")
                self.run_briefing_flow("daily_brief", current_time)
                
        # Evening Review: >= 22:00
        if lt.tm_hour >= 22:
            date_str = time.strftime("%Y_%m_%d", lt)
            key = f"evening_review_{date_str}"
            from skills.blackboard import AriaBlackboard
            blackboard = AriaBlackboard()
            if blackboard.read("coach", key) is None:
                print(f"[PersonalCoach] Running scheduled Evening Review for {date_str}...")
                self.run_briefing_flow("evening_review", current_time)
                
        # Weekly Review: Sunday >= 21:00
        if lt.tm_wday == 6 and lt.tm_hour >= 21:
            week_str = time.strftime("%Y_w%U", lt)
            key = f"weekly_review_{week_str}"
            from skills.blackboard import AriaBlackboard
            blackboard = AriaBlackboard()
            if blackboard.read("coach", key) is None:
                print(f"[PersonalCoach] Running scheduled Weekly Review for {week_str}...")
                self.run_briefing_flow("weekly_review", current_time)

    def get_active_campaign_metrics(self) -> List[Dict[str, Any]]:
        """
        Connects to SQLite to query active campaigns and tasks,
        calculates progress, schedule risk, and priority scores.
        """
        conn = None
        campaign_metrics = []
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check for column availability to support backward-compatibility
            cursor.execute("PRAGMA table_info(campaigns)")
            campaign_cols = [r[1] for r in cursor.fetchall()]
            has_camp_created_at = "created_at" in campaign_cols
            has_camp_progress = "progress" in campaign_cols
            
            cursor.execute("PRAGMA table_info(agent_tasks)")
            task_cols = [r[1] for r in cursor.fetchall()]
            has_task_created_at = "created_at" in task_cols
            
            camp_select = "id, goal_text, status"
            if has_camp_created_at:
                camp_select += ", created_at"
            if has_camp_progress:
                camp_select += ", progress"
                
            cursor.execute(f"SELECT {camp_select} FROM campaigns WHERE status NOT IN ('COMPLETED', 'FAILED')")
            campaign_rows = cursor.fetchall()
            
            now = time.time()
            for row in campaign_rows:
                camp_id = row[0]
                goal_text = row[1]
                status = row[2]
                
                created_at = now
                if has_camp_created_at:
                    created_idx = camp_select.split(", ").index("created_at")
                    created_at = row[created_idx] if row[created_idx] is not None else now
                
                task_select = "status"
                if has_task_created_at:
                    task_select += ", created_at"
                    
                cursor.execute(f"SELECT {task_select} FROM agent_tasks WHERE campaign_id = ?", (camp_id,))
                tasks = cursor.fetchall()
                
                total_tasks = len(tasks)
                completed_tasks = sum(1 for t in tasks if t[0] == 'COMPLETED')
                
                # overdue tasks: pending/running created > 2 days ago (172800s)
                overdue_tasks = 0
                if has_task_created_at:
                    overdue_tasks = sum(
                        1 for t in tasks 
                        if t[0] in ('PENDING', 'RUNNING') and t[1] is not None and (now - t[1]) > 172800
                    )
                
                progress = completed_tasks / total_tasks if total_tasks > 0 else 1.0
                schedule_risk = overdue_tasks / total_tasks if total_tasks > 0 else 0.0
                
                # coach_score = (progress * 0.7) + ((1.0 - schedule_risk) * 0.3)
                coach_score = (progress * 0.7) + ((1.0 - schedule_risk) * 0.3)
                
                # deadline_weight from goal_text parsing
                duration_secs = 90 * 86400  # Default 90 days
                match_m = re.search(r'(\d+)\s*month', goal_text, re.IGNORECASE)
                match_w = re.search(r'(\d+)\s*week', goal_text, re.IGNORECASE)
                match_d = re.search(r'(\d+)\s*day', goal_text, re.IGNORECASE)
                if match_m:
                    duration_secs = int(match_m.group(1)) * 30 * 86400
                elif match_w:
                    duration_secs = int(match_w.group(1)) * 7 * 86400
                elif match_d:
                    duration_secs = int(match_d.group(1)) * 86400
                    
                time_elapsed = now - created_at
                if time_elapsed < 0:
                    time_elapsed = 0
                    
                if duration_secs <= 0:
                    deadline_weight = 1.0
                else:
                    deadline_weight = min(1.0, max(0.0, time_elapsed / duration_secs))
                    
                progress_gap = 1.0 - progress
                # priority_score = (deadline_weight * 0.5) + (schedule_risk * 0.3) + (progress_gap * 0.2)
                priority_score = (deadline_weight * 0.5) + (schedule_risk * 0.3) + (progress_gap * 0.2)
                
                campaign_metrics.append({
                    "id": camp_id,
                    "goal_text": goal_text,
                    "status": status,
                    "created_at": created_at,
                    "total_tasks": total_tasks,
                    "completed_tasks": completed_tasks,
                    "overdue_tasks": overdue_tasks,
                    "progress": progress,
                    "schedule_risk": schedule_risk,
                    "coach_score": coach_score,
                    "deadline_weight": deadline_weight,
                    "progress_gap": progress_gap,
                    "priority_score": priority_score
                })
        except Exception as e:
            print(f"[PersonalCoach] Error querying campaign metrics: {e}")
        finally:
            if conn:
                conn.close()
                
        # Sort campaigns by priority_score descending
        campaign_metrics.sort(key=lambda x: x["priority_score"], reverse=True)
        return campaign_metrics

    def run_briefing_flow(self, brief_type: str, timestamp: float = None) -> str:
        if timestamp is None:
            timestamp = time.time()
            
        lt = time.localtime(timestamp)
        date_str = time.strftime("%Y_%m_%d", lt)
        week_str = time.strftime("%Y_w%U", lt)
        
        # 1. Fetch metrics
        campaign_metrics = self.get_active_campaign_metrics()
        
        # Read/query habit prediction
        from skills.blackboard import AriaBlackboard
        blackboard = AriaBlackboard()
        
        habit_prediction = blackboard.read("habits", "habit_prediction")
        if not habit_prediction:
            from skills.agent_registry import registry
            wrapper = registry.get("neuralhabitengineagent")
            if wrapper:
                try:
                    forecast_str = wrapper.run("TSK_PRED", "predict habits", {})
                    habit_prediction = json.loads(forecast_str)
                    blackboard.publish("habits", "habit_prediction", habit_prediction, self.agent_name, ttl_hours=24)
                except Exception as e:
                    print(f"[PersonalCoach] Failed to generate habit prediction fallback: {e}")
                    
        # Read/query weekly analytics
        weekly_analytics = blackboard.read("habits", "weekly_analytics")
        if not weekly_analytics:
            from skills.agent_registry import registry
            wrapper = registry.get("habitintelligenceagent")
            if wrapper:
                try:
                    analytics_str = wrapper.run("TSK_ANALYTICS", "get analytics", {})
                    report = json.loads(analytics_str)
                    weekly_analytics = report.get("analytics")
                    if weekly_analytics:
                        blackboard.publish("habits", "weekly_analytics", weekly_analytics, self.agent_name, ttl_hours=24)
                except Exception as e:
                    print(f"[PersonalCoach] Failed to generate weekly analytics fallback: {e}")
                    
        # Fetch completed and slipped tasks for context
        completed_today = []
        slipped_tasks = []
        
        start_of_today = int(time.mktime(time.struct_time((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))))
        now = time.time()
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("PRAGMA table_info(agent_tasks)")
            task_cols = [r[1] for r in cursor.fetchall()]
            has_task_completed_at = "completed_at" in task_cols
            has_task_created_at = "created_at" in task_cols
            
            # Completed today
            if has_task_completed_at:
                cursor.execute("""
                    SELECT campaign_id, agent_name, task_description, completed_at 
                    FROM agent_tasks 
                    WHERE status = 'COMPLETED' AND completed_at >= ?
                """, (start_of_today,))
                for r in cursor.fetchall():
                    completed_today.append({
                        "campaign_id": r[0],
                        "agent_name": r[1],
                        "task_description": r[2],
                        "completed_at": r[3]
                    })
            else:
                cursor.execute("""
                    SELECT campaign_id, agent_name, task_description 
                    FROM agent_tasks 
                    WHERE status = 'COMPLETED'
                """)
                for r in cursor.fetchall():
                    completed_today.append({
                        "campaign_id": r[0],
                        "agent_name": r[1],
                        "task_description": r[2],
                        "completed_at": now
                    })
                
            # Slipped / pending
            task_select = "campaign_id, agent_name, task_description"
            if has_task_created_at:
                task_select += ", created_at"
                
            cursor.execute(f"""
                SELECT {task_select}
                FROM agent_tasks 
                WHERE status IN ('PENDING', 'RUNNING')
            """)
            for r in cursor.fetchall():
                created_val = now
                if has_task_created_at:
                    created_val = r[3] if r[3] is not None else now
                slipped_tasks.append({
                    "campaign_id": r[0],
                    "agent_name": r[1],
                    "task_description": r[2],
                    "created_at": created_val
                })
                
            conn.close()
        except Exception as e:
            print(f"[PersonalCoach] Error fetching tasks for brief: {e}")
            
        # 2. Construct prompts
        prompt = ""
        sys_instruction = ""
        
        if brief_type == "daily_brief":
            sys_instruction = (
                "You are ARIA's Personal AI Coach, a proactive and lightweight executive manager. "
                "Your goal is to synthesize the user's campaign metrics, task progress, and habit forecasts into a daily morning brief. "
                "Make recommendations on actions to take. Do NOT execute tasks yourself. "
                "Always begin with a header and state clearly 'Today's Top Priority: [Campaign Name]' and the 'Reason: [Reason why it is top priority based on scores]'. "
                "Keep your response in structured, beautiful markdown. Be motivating, concise, and professional."
            )
            
            prompt = (
                f"Here is the daily status context for compile on date {date_str}:\n\n"
                f"Active Campaigns:\n{json.dumps(campaign_metrics, indent=2)}\n\n"
                f"Neural Habit Prediction:\n{json.dumps(habit_prediction, indent=2)}\n\n"
                f"Weekly Focus Analytics:\n{json.dumps(weekly_analytics, indent=2)}\n\n"
                f"Slipped Tasks from Yesterday:\n{json.dumps(slipped_tasks, indent=2)}\n\n"
                f"Generate today's morning coaching brief."
            )
            
        elif brief_type == "evening_review":
            sys_instruction = (
                "You are ARIA's Personal AI Coach. Synthesize the user's accomplishments (tasks completed today) and slipped tasks "
                "into a supportive, coaching evening review. Propose adjustments for tomorrow to maintain momentum. "
                "Do NOT execute any actions directly. "
                "Keep it concise, high-impact, and formatted in clean markdown."
            )
            
            prompt = (
                f"Here is the evening review context for compile on date {date_str}:\n\n"
                f"Tasks Completed Today:\n{json.dumps(completed_today, indent=2)}\n\n"
                f"Tasks Slipped/Pending for Tomorrow:\n{json.dumps(slipped_tasks, indent=2)}\n\n"
                f"Active Campaigns:\n{json.dumps(campaign_metrics, indent=2)}\n\n"
                f"Generate this evening's coaching review."
            )
            
        elif brief_type == "weekly_review":
            sys_instruction = (
                "You are ARIA's Personal AI Coach. Aggregated weekly productivity statistics, focus habits, and campaign progress "
                "into a comprehensive Sunday weekly review. Highlight momentum, achievements, neglected areas, "
                "and outline strategic adjustments for the upcoming week. "
                "Keep it professional, structured, and in clean markdown."
            )
            
            prompt = (
                f"Here is the Sunday weekly review context for week {week_str}:\n\n"
                f"Weekly Analytics:\n{json.dumps(weekly_analytics, indent=2)}\n\n"
                f"Campaign Progress/Metrics:\n{json.dumps(campaign_metrics, indent=2)}\n\n"
                f"Tasks Completed this Week:\n{json.dumps(completed_today, indent=2)}\n\n"
                f"Generate this Sunday's weekly executive coaching review."
            )
            
        # 3. Call model (with fallbacks)
        brief_content = self.generate_via_gemini(prompt, sys_instruction)
        if not brief_content:
            # Ultimate offline fallback
            brief_content = self.generate_offline_brief_fallback(
                brief_type, campaign_metrics, weekly_analytics, habit_prediction, completed_today, slipped_tasks
            )
            
        # 4. Publish to Blackboard
        if brief_type == "daily_brief":
            blackboard.publish("coach", f"daily_brief_{date_str}", brief_content, self.agent_name, ttl_hours=72)
            blackboard.publish("coach", "daily_brief", brief_content, self.agent_name, ttl_hours=24)
            
            # Phone alert for daily brief
            aria = self.aria
            if aria and hasattr(aria, "alert_router") and aria.alert_router:
                try:
                    top_campaign = campaign_metrics[0]["goal_text"] if campaign_metrics else "General Focus"
                    aria.alert_router.dispatch_alert(
                        title="🧘‍♂️ ARIA Morning Briefing Ready",
                        body=f"Today's Top Priority: {top_campaign}. View details in coach dashboard.",
                        priority="HIGH",
                        category="COACH"
                    )
                except Exception as e:
                    print(f"[PersonalCoach] Failed to dispatch morning alert: {e}")
                    
        elif brief_type == "evening_review":
            blackboard.publish("coach", f"evening_review_{date_str}", brief_content, self.agent_name, ttl_hours=72)
            blackboard.publish("coach", "evening_review", brief_content, self.agent_name, ttl_hours=24)
            
        elif brief_type == "weekly_review":
            blackboard.publish("coach", f"weekly_review_{week_str}", brief_content, self.agent_name, ttl_hours=168)
            blackboard.publish("coach", "weekly_review", brief_content, self.agent_name, ttl_hours=168)
            
        return brief_content

    def generate_via_gemini(self, prompt: str, system_instruction: str) -> str:
        # 1. Try Vertex AI via AriaVertexBridge
        try:
            from skills.vertex_bridge import AriaVertexBridge
            bridge = AriaVertexBridge()
            if bridge.initialized:
                res = bridge.generate(prompt=prompt, system_instruction=system_instruction, model_type="pro")
                if res and res != "I'm ready. Tell me what to open, search, or automate.":
                    return res
        except Exception as e:
            print(f"[PersonalCoach] AriaVertexBridge failed: {e}")

        # 2. Try direct google.generativeai with api_key.txt
        try:
            if os.path.exists("api_key.txt"):
                with open("api_key.txt", "r") as f:
                    key = f.read().strip()
                if key:
                    import google.generativeai as genai
                    genai.configure(api_key=key)
                    model = genai.GenerativeModel(
                        model_name="gemini-2.5-flash",
                        system_instruction=system_instruction
                    )
                    response = model.generate_content(prompt)
                    if response and response.text:
                        return response.text.strip()
        except Exception as e:
            print(f"[PersonalCoach] Direct google.generativeai failed: {e}")

        return ""

    def generate_offline_brief_fallback(self, brief_type: str, campaign_metrics: list, weekly_analytics: dict, 
                                       habit_prediction: dict, completed_today: list, slipped_tasks: list) -> str:
        lines = []
        if brief_type == "daily_brief":
            lines.append("# ARIA Daily Coaching Brief")
            lines.append(f"Date: {time.strftime('%A, %B %d, %Y')}\n")
            
            if campaign_metrics:
                top = campaign_metrics[0]
                lines.append(f"**Today's Top Priority:** {top['goal_text']}")
                lines.append(f"**Reason:** Highest priority score ({top['priority_score']:.2f}) based on deadline pressure ({top['deadline_weight']:.2f}) and schedule risk ({top['schedule_risk']:.2f}).\n")
                
                lines.append("## Campaign Status & Scores")
                for c in campaign_metrics:
                    lines.append(f"- **Goal:** {c['goal_text']}")
                    lines.append(f"  - Coach Score: {c['coach_score']:.2f} (Progress: {c['progress']*100:.0f}%, Risk: {c['schedule_risk']*100:.0f}%)")
                    lines.append(f"  - Tasks: {c['completed_tasks']} completed / {c['total_tasks']} total ({c['overdue_tasks']} overdue)")
                lines.append("")
            else:
                lines.append("No active campaigns found today.\n")
                
            if habit_prediction:
                lines.append("## Habit Forecast")
                lines.append(f"- **Predicted Topic:** {habit_prediction.get('predicted_topic', 'Study')}")
                lines.append(f"- **Expected Duration:** {habit_prediction.get('expected_duration', 90)} minutes")
                lines.append(f"- **Confidence:** {habit_prediction.get('confidence', 0.0)*100:.0f}%")
                if habit_prediction.get("recommended_resources"):
                    recs = ", ".join(habit_prediction["recommended_resources"])
                    lines.append(f"- **Recommended Resources:** {recs}")
                lines.append("")
                
            if weekly_analytics:
                lines.append("## Weekly Focus Trends")
                lines.append(f"- **Productivity Score:** {weekly_analytics.get('productivity_score', 0)}/100")
                lines.append(f"- **Total Focus Time:** {weekly_analytics.get('total_focus_minutes', 0)} minutes")
                lines.append(f"- **Active Days:** {weekly_analytics.get('active_days_count', 0)}/7")
                
        elif brief_type == "evening_review":
            lines.append("# ARIA Evening Coaching Review")
            lines.append(f"Date: {time.strftime('%A, %B %d, %Y')}\n")
            
            lines.append("## Accomplishments Today")
            if completed_today:
                for t in completed_today:
                    lines.append(f"- [x] **{t['agent_name']}:** {t['task_description']}")
            else:
                lines.append("- No tasks were completed today.")
            lines.append("")
            
            lines.append("## Slipped / Remaining Tasks")
            if slipped_tasks:
                for t in slipped_tasks:
                    lines.append(f"- [ ] **{t['agent_name']}:** {t['task_description']} (Slipped to tomorrow)")
            else:
                lines.append("- No tasks slipped to tomorrow. Great job!")
            lines.append("")
            
            lines.append("## Coach Advice")
            if slipped_tasks:
                lines.append("Tomorrow is a fresh start. Focus on the slipped tasks first thing in the morning to regain momentum.")
            else:
                lines.append("Incredible job today! Rest up and recharge for tomorrow.")
                
        elif brief_type == "weekly_review":
            lines.append("# ARIA Weekly Coaching Review")
            lines.append(f"Week: {time.strftime('%Y_w%U')}\n")
            
            if weekly_analytics:
                lines.append("## Weekly Focus Metrics")
                lines.append(f"- **Overall Productivity Rating:** {weekly_analytics.get('productivity_score', 0)}/100")
                lines.append(f"- **Total Time Spent At Desk:** {weekly_analytics.get('total_focus_minutes', 0)} minutes")
                lines.append(f"- **Daily Consistency:** {weekly_analytics.get('active_days_count', 0)} out of 7 days active")
                lines.append("")
                
            if campaign_metrics:
                lines.append("## Campaign Achievements")
                for c in campaign_metrics:
                    lines.append(f"- **{c['goal_text']}:**")
                    lines.append(f"  - Progress: {c['progress']*100:.0f}% (Score: {c['coach_score']:.2f})")
                    lines.append(f"  - Risk Assessment: {c['schedule_risk']*100:.0f}% schedule risk")
                lines.append("")
                
            lines.append("## Weekly Coaching Synthesis")
            lines.append("Review your habits from this week. Adjust focus topics, manage pending blockers early, and set clear goals for the next week.")
            
        return "\n".join(lines)
