import os
import re
import json
import time
from brain import Brain
from skills.agent_orchestrator import AriaMultiAgentOrchestrator
from skills.agent_status import get_db_connection

class AgentCoordinator:
    def __init__(self, aria):
        self.aria = aria
        self.brain = aria.brain if aria else Brain()

    def coordinate_campaign(self, goal_text):
        print(f"[Coordinator] Campaign created: {goal_text}")
        
        # Wave 2 Skill Trust Integration: retrieve current trust matrix and dynamic penalties
        trust_matrix_str = ""
        try:
            from skills.intelligence_convergence_hub import AriaIntelligenceConvergenceHub
            hub = AriaIntelligenceConvergenceHub()
            matrix = hub.compile_converged_intelligence_matrix()
            overrides = hub.generate_convergence_overrides()
            penalties = overrides.get("skill_routing_penalties", {})
            
            lines = []
            lines.append("== ACTIVE AGENT TRUST RATINGS & ROUTING PENALTIES ==")
            for name, score in matrix.get("skill_trust_matrix", {}).items():
                penalty_label = penalties.get(name, "Normal")
                lines.append(f"- Agent/Skill '{name}': Trust Rating {score:.2f} [{penalty_label}]")
            trust_matrix_str = "\n".join(lines) + "\n\n"
        except Exception:
            pass

        # Decompose the goal using LLM/Brain
        prompt = (
            f"You are the central Agent Coordinator for ARIA.\n"
            f"Decompose the user's multi-action goal into a graph of subtasks to execute in parallel.\n"
            f"Goal: '{goal_text}'\n\n"
            f"{trust_matrix_str}"
            f"For each subtask, determine:\n"
            f"1. A unique string 'id' (e.g. 'task_1', 'task_2').\n"
            f"2. A short descriptive 'task_name'.\n"
            f"3. Which agent should handle it ('CareerAgent', 'GitHubAgent', 'NewsAgent', 'BrowserAgent'). Note: If an agent has a low trust rating (< 0.60), route tasks to other alternative agents if possible.\n"
            f"4. Parameters needed ('target').\n"
            f"5. 'priority': integer between 1 (lowest) and 10 (highest).\n"
            f"6. 'timeout_seconds': integer default 120 (use 600 for coding tasks).\n"
            f"7. 'depends_on': list of other task 'id' strings that must complete before this task can start.\n\n"
            f"You MUST output exactly a JSON object with fields 'campaign_goal' and 'tasks'.\n"
            f"Do not include markdown formatting (like ```json). Return raw JSON only.\n"
            f"Example:\n"
            f"{{\n"
            f'  "campaign_goal": "Search AI internships, check GitHub status and summarize latest AI news",\n'
            f'  "tasks": [\n'
            f'    {{"id": "task_1", "task_name": "Search AI internships", "agent_name": "CareerAgent", "target": "AI internships", "priority": 7, "timeout_seconds": 120, "depends_on": []}},\n'
            f'    {{"id": "task_2", "task_name": "Check GitHub status", "agent_name": "GitHubAgent", "target": "chinmaya", "priority": 5, "timeout_seconds": 120, "depends_on": []}},\n'
            f'    {{"id": "task_3", "task_name": "Summarize latest AI news", "agent_name": "NewsAgent", "target": "latest AI news", "priority": 5, "timeout_seconds": 120, "depends_on": []}}\n'
            f'  ]\n'
            f"}}"
        )
        
        tasks = []
        try:
            raw_res = self.brain.think(prompt).strip()
            match = re.search(r"(\{.*\})", raw_res, re.DOTALL)
            if match:
                raw_res = match.group(1).strip()
            plan = json.loads(raw_res)
            tasks = plan.get("tasks", [])
        except Exception as e:
            print(f"[Coordinator] Failed to decompose via LLM: {e}. Falling back to default list.")
            # Fallback decomposition
            tasks = []
            if "internship" in goal_text.lower() or "job" in goal_text.lower():
                tasks.append({"id": "task_1", "task_name": "Search AI internships", "agent_name": "CareerAgent", "target": "AI internships", "priority": 7, "timeout_seconds": 120, "depends_on": []})
            if "github" in goal_text.lower():
                tasks.append({"id": "task_2", "task_name": "Check GitHub status", "agent_name": "GitHubAgent", "target": "chinmaya", "priority": 5, "timeout_seconds": 120, "depends_on": []})
            if "news" in goal_text.lower():
                tasks.append({"id": "task_3", "task_name": "Summarize latest AI news", "agent_name": "NewsAgent", "target": "latest AI news", "priority": 5, "timeout_seconds": 120, "depends_on": []})
        
        # Verify cycles
        if self._has_cycle(tasks):
            print("[Coordinator] Dependency cycle detected. Clearing depends_on constraints for safety.")
            for t in tasks:
                t["depends_on"] = []

        # Normalize fields
        for t in tasks:
            agent = t.get("agent_name") or t.get("agent_type") or t.get("agent") or "BrowserAgent"
            if "career" in agent.lower():
                agent = "CareerAgent"
            elif "github" in agent.lower():
                agent = "GitHubAgent"
            elif "news" in agent.lower():
                agent = "NewsAgent"
            elif "browser" in agent.lower():
                agent = "BrowserAgent"
            t["agent_name"] = agent
            
            t["task_description"] = t.get("task_description") or t.get("task_name") or t.get("task") or "Run task"
            t["target"] = t.get("target") or t.get("query") or ""
            t["priority"] = int(t.get("priority", 5))
            t["timeout_seconds"] = int(t.get("timeout_seconds", 120))
            t["depends_on"] = t.get("depends_on", [])

        # Start active task if present
        task_manager = getattr(self.aria.brain if self.aria else None, "semantic_router", None)
        if task_manager:
            task_manager = getattr(task_manager, "task_manager", None)
        active_task = None
        if task_manager:
            active_task = task_manager.start_task(f"Campaign: {goal_text}")

        # Submit to orchestrator
        orchestrator = AriaMultiAgentOrchestrator()
        campaign_id = orchestrator.submit_campaign(goal_text, tasks)
        
        # Poll progress until completed or failed
        print(f"[Coordinator] Waiting for campaign {campaign_id} to finish...")
        while True:
            status_meta = orchestrator.get_campaign_status(campaign_id)
            status = status_meta["status"]
            progress = status_meta["progress"]
            
            print(f"[Coordinator] Campaign {campaign_id}: {progress:.1f}% ({status})")
            if status in ("COMPLETED", "FAILED"):
                break
            time.sleep(2.0)

        # Collect final results from DB
        results_summary = []
        results_summary.append(f"Campaign: {goal_text} ({campaign_id})")
        results_summary.append("=" * 50)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, agent_name, task_description, status 
                FROM agent_tasks 
                WHERE campaign_id = ? 
                ORDER BY created_at ASC
            """, (campaign_id,))
            campaign_tasks = cursor.fetchall()
            
            for t_row in campaign_tasks:
                tid, agent_name, desc, status = t_row
                cursor.execute("SELECT result_payload FROM agent_results WHERE task_id = ?", (tid,))
                res_row = cursor.fetchone()
                payload = res_row[0] if res_row else "No output payload recorded."
                
                results_summary.append(f"[{status}] {desc} ({agent_name.upper()}):")
                results_summary.append(f"  {payload}")
                results_summary.append("-" * 50)

        summary_content = "\n".join(results_summary)
        orchestrator.add_campaign_artifact(campaign_id, "SUMMARY", summary_content)
        
        if active_task:
            if status == "COMPLETED":
                active_task.complete_task()
            else:
                active_task.cancel_task()

        return summary_content

    def _has_cycle(self, tasks: list) -> bool:
        adj = {}
        for t in tasks:
            adj[t["id"]] = t.get("depends_on", [])
        
        visited = {}
        for t in tasks:
            visited[t["id"]] = 0
            
        def dfs(node):
            if visited.get(node) == 1:
                return True
            if visited.get(node) == 2:
                return False
                
            visited[node] = 1
            for neighbor in adj.get(node, []):
                if neighbor in visited:  # Only visit neighbors that are tasks in this campaign
                    if dfs(neighbor):
                        return True
            visited[node] = 2
            return False
            
        for t in tasks:
            if visited[t["id"]] == 0:
                if dfs(t["id"]):
                    return True
        return False
