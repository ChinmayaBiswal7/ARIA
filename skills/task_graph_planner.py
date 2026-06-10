import json
import time
from typing import Dict, Any, List, Tuple
from skills.base_agent import BaseAgent
from skills.blackboard import AriaBlackboard
from skills.strategic_memory_engine import AriaStrategicMemoryEngine

class AriaTaskGraphPlanner(BaseAgent):
    def __init__(self, aria_instance=None, db_path=None):
        super().__init__("PlanningAgent", aria_instance)
        self.blackboard = AriaBlackboard()
        from skills.agent_status import DB_PATH
        self.db_path = db_path or DB_PATH
        self.memory_engine = AriaStrategicMemoryEngine(self.db_path)

    @property
    def aria_inst(self):
        if self.aria is None:
            try:
                from skills.agent_orchestrator import AriaMultiAgentOrchestrator
                self.aria = AriaMultiAgentOrchestrator().aria
            except Exception:
                pass
        return self.aria

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        self.log_state_shift("RUNNING", f"Compiling structured task graph for objective: '{payload.get('goal')}'")
        
        user_goal = payload.get("goal", "")
        if not user_goal:
            user_goal = task_description
            
        research_context = payload.get("research_context", "No supplemental background context compiled.")

        # Strict JSON Schema using standard uppercase types for Vertex AI validation config
        task_graph_schema = {
            "type": "OBJECT",
            "properties": {
                "goal": {"type": "STRING"},
                "milestones": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "id": {"type": "STRING"},
                            "title": {"type": "STRING"},
                            "description": {"type": "STRING"}
                        },
                        "required": ["id", "title", "description"]
                    }
                },
                "tasks": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "id": {"type": "STRING"},
                            "description": {"type": "STRING"},
                            "priority": {"type": "STRING"}, # 'HIGH', 'MEDIUM', 'LOW'
                            "agent_target": {"type": "STRING"}, # 'BrowserAgent', 'CodingAgent', etc.
                            "depends_on": {
                                "type": "ARRAY",
                                "items": {"type": "STRING"}
                            },
                            "milestone_id": {"type": "STRING"}
                        },
                        "required": ["id", "description", "priority", "agent_target", "depends_on"]
                    }
                }
            },
            "required": ["goal", "milestones", "tasks"]
        }

        # Compile experience matrix using the Strategic Memory Engine
        experience_matrix = self.memory_engine.compile_experience_matrix(user_goal)

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
            trust_matrix_str = "\n".join(lines)
        except Exception:
            trust_matrix_str = "No active agent trust ratings recorded."

        planner_prompt = f"""
        You are ARIA's core architectural Planning Agent driven by Vertex AI.
        Deconstruct the user's high-level goal into an explicit sequence of structured milestones and dependent tasks.
        Map each task to an appropriate agent target (e.g. BrowserAgent, CareerAgent, LearningAgent, CodingAgent, ResearchAgent).
        Ensure tasks reference their corresponding milestone_id if they belong to a milestone.
        Ensure task priority is strictly one of: 'HIGH', 'MEDIUM', or 'LOW'.
        
        You must optimize this plan by learning directly from our historical production metrics below.
        
        == USER HIGHEST GOAL ==
        {user_goal}
        
        == BACKGROUND CONTEXT MATRIX ==
        {research_context}
        
        {trust_matrix_str}
        
        == REAL HISTORICAL TASK METRICS ==
        {json.dumps(experience_matrix['task_success_and_failures'])}
        
        == HIGH-PERFORMING WORKFORCE TEAMS ==
        {json.dumps(experience_matrix['high_performing_teams'])}
        
        == LATEST WEEKLY REFLECTION DIRECTIVES ==
        {json.dumps(experience_matrix['reflection_directives'])}

        == PROVEN BEHAVIORAL INTERVENTIONS ==
        {json.dumps(experience_matrix['proven_behavioral_interventions'])}

        == KNOWN PREREQUISITES & DEPENDENCY GAPS ==
        {json.dumps(experience_matrix['known_prerequisites'])}
        
        Constraints: Prioritize task structures with proven high success rates. Avoid path configurations that previously led to high failure rates. Assign work to high-performing agent teams. Do not repeat known dependency failures. If an agent (e.g. BrowserAgent) has a low trust rating (< 0.60), apply a routing penalty: route to alternative agents (e.g., CodingAgent, ResearchAgent) if the task can be accomplished via code or search.
        
        Analyze constraints carefully. Output a pristine JSON tree following the requested schema rules exactly.
        """

        try:
            aria_ctx = self.aria_inst
            raw_json_output = ""
            
            if aria_ctx and hasattr(aria_ctx, "brain"):
                raw_json_output = aria_ctx.brain.think_vertex(
                    prompt=planner_prompt,
                    enforce_json_schema=task_graph_schema,
                    model_type="pro"
                )
            else:
                # Offline/Local fallback logic to construct a dummy valid response structure
                raw_json_output = json.dumps({
                    "goal": user_goal,
                    "milestones": [
                        {"id": "M1", "title": "Initial Preparation", "description": "Gather information and build basics"}
                    ],
                    "tasks": [
                        {"id": "T1", "description": "Research requirements", "priority": "HIGH", "agent_target": "ResearchAgent", "depends_on": [], "milestone_id": "M1"}
                    ]
                })

            # Parse plan structure
            try:
                structured_plan = json.loads(raw_json_output)
            except json.JSONDecodeError as decode_err:
                self.log_state_shift("ERROR", f"Vertex output was not valid JSON: {decode_err}")
                return json.dumps({"status": "INVALID_PLAN", "error": f"JSON decoding failed: {decode_err}"})

            # Run plan validation
            is_valid, validation_error, confidence = self.validate_and_score_plan(structured_plan)
            
            if not is_valid:
                self.log_state_shift("ERROR", f"Plan validation failed: {validation_error}")
                return json.dumps({
                    "status": "INVALID_PLAN",
                    "error": validation_error,
                    "plan": structured_plan
                })

            # Add execution and metadata params to the valid plan dict
            structured_plan["plan_id"] = f"taskplan_{task_id}"
            structured_plan["parent_task"] = task_id
            structured_plan["execution_mode"] = "DRY_RUN"
            structured_plan["planner_confidence"] = confidence

            # Schedule and allocate tasks based on daily focus budget constraints (P17)
            try:
                from skills.resource_manager import AriaResourceManager
                resource_manager = AriaResourceManager(self.db_path)
                campaign_priorities = payload.get("campaign_priorities") or {task_id: 10}
                allocation = resource_manager.schedule_and_allocate_tasks(
                    campaign_id=task_id,
                    proposed_tasks=structured_plan.get("tasks", []),
                    campaign_priorities=campaign_priorities
                )
                structured_plan["resource_allocation"] = allocation
            except Exception as res_err:
                print(f"[{self.agent_name}] Failed to run resource allocation checks: {res_err}")

            # Run future simulations and forecast comparisons (P18)
            try:
                from skills.simulation_engine import AriaSimulationEngine
                sim_engine = AriaSimulationEngine(self.db_path)
                simulation_results = sim_engine.run_future_projections(
                    campaign_id=task_id,
                    base_goal=structured_plan.get("goal", user_goal),
                    proposed_tasks=structured_plan.get("tasks", [])
                )
                structured_plan["simulation_results"] = simulation_results
            except Exception as sim_err:
                print(f"[{self.agent_name}] Failed to run future simulations: {sim_err}")

            # Publish to Blackboard under 'system' topic
            self.blackboard.publish(
                topic="system",
                key=f"taskplan_{task_id}",
                value=structured_plan,
                source=self.agent_name,
                ttl_hours=24
            )

            # Trigger alert router to notify HUD/dashboard if available
            if aria_ctx and hasattr(aria_ctx, "alert_router") and aria_ctx.alert_router:
                try:
                    aria_ctx.alert_router.dispatch_alert(
                        title="📋 NEW CAMPAIGN PLAN STAGED",
                        body=f"Goal: {structured_plan['goal']} | Tasks: {len(structured_plan['tasks'])}. Review required.",
                        priority="MEDIUM",
                        category="SYSTEM"
                    )
                except Exception as alert_err:
                    print(f"[{self.agent_name}] Failed to dispatch alert: {alert_err}")

            self.log_state_shift("IDLE", f"Plan staged safely on Blackboard for {task_id}. Execution suspended for human review.")
            return json.dumps({"status": "SUCCESS", "plan": structured_plan})

        except Exception as e:
            self.log_state_shift("ERROR", f"Task planning matrix sequence faulted: {str(e)}")
            return json.dumps({"status": "FAILED", "error": str(e)})

    def validate_and_score_plan(self, plan: Dict[str, Any]) -> Tuple[bool, str, float]:
        """
        Validates the plan structure and computes a deterministic confidence score.
        Returns (is_valid, error_message, confidence_score).
        """
        # 1. Schema Score Check (40%)
        schema_score = 1.0
        errors = []
        
        if not isinstance(plan, dict):
            return False, "Plan is not a JSON object", 0.0
            
        if "goal" not in plan or not isinstance(plan["goal"], str) or not plan["goal"].strip():
            schema_score -= 0.3
            errors.append("Missing or empty 'goal'")
        if "milestones" not in plan or not isinstance(plan["milestones"], list):
            schema_score -= 0.3
            errors.append("Missing or malformed 'milestones' list")
        if "tasks" not in plan or not isinstance(plan["tasks"], list):
            schema_score -= 0.4
            errors.append("Missing or malformed 'tasks' list")
            
        schema_score = max(0.0, schema_score)
        
        if errors:
            return False, "; ".join(errors), 0.0
            
        milestones = plan["milestones"]
        tasks = plan["tasks"]
        
        # Check milestones structure
        milestone_ids = set()
        for idx, m in enumerate(milestones):
            if not isinstance(m, dict):
                return False, f"Milestone at index {idx} is not an object", 0.0
            if not all(k in m for k in ("id", "title", "description")):
                return False, f"Milestone at index {idx} is missing required fields (id, title, description)", 0.0
            m_id = m["id"]
            if not isinstance(m_id, str) or not m_id.strip():
                return False, f"Milestone at index {idx} has an empty or invalid id", 0.0
            if m_id in milestone_ids:
                return False, f"Duplicate milestone id found: {m_id}", 0.0
            milestone_ids.add(m_id)
            
        # Check tasks structure
        task_ids = set()
        for idx, t in enumerate(tasks):
            if not isinstance(t, dict):
                return False, f"Task at index {idx} is not an object", 0.0
            required_task_keys = ("id", "description", "priority", "agent_target", "depends_on")
            if not all(k in t for k in required_task_keys):
                missing = [k for k in required_task_keys if k not in t]
                return False, f"Task at index {idx} is missing required fields: {missing}", 0.0
            t_id = t["id"]
            if not isinstance(t_id, str) or not t_id.strip():
                return False, f"Task at index {idx} has an empty or invalid id", 0.0
            if t_id in task_ids:
                return False, f"Duplicate task id found: {t_id}", 0.0
            task_ids.add(t_id)
            
            # Priority check
            if t["priority"] not in ("HIGH", "MEDIUM", "LOW"):
                return False, f"Task {t_id} has invalid priority: {t['priority']}. Must be HIGH, MEDIUM, or LOW.", 0.0
                
            # depends_on check
            if not isinstance(t["depends_on"], list):
                return False, f"Task {t_id} depends_on is not a list", 0.0
                
        # 2. Dependency Quality Check (30%)
        dependency_score = 1.0
        dep_errors = []
        total_deps = 0
        invalid_deps = 0
        
        for t in tasks:
            t_id = t["id"]
            for dep in t["depends_on"]:
                if not isinstance(dep, str):
                    invalid_deps += 1
                    dep_errors.append(f"Task {t_id} has a non-string dependency")
                    continue
                total_deps += 1
                if dep == t_id:
                    invalid_deps += 1
                    dep_errors.append(f"Task {t_id} depends on itself")
                elif dep not in task_ids:
                    invalid_deps += 1
                    dep_errors.append(f"Task {t_id} depends on non-existent task {dep}")
                    
        if invalid_deps > 0:
            dependency_score = max(0.0, 1.0 - (invalid_deps * 0.2))
            return False, "; ".join(dep_errors), 0.0
            
        # 3. Cycle Detection (20%)
        cycle_score = 1.0
        if task_ids:
            adj = {t["id"]: t["depends_on"] for t in tasks}
            visited = {}  # 0: unvisited, 1: visiting, 2: visited
            has_cycle = False
            
            def dfs(node):
                nonlocal has_cycle
                visited[node] = 1
                for neighbor in adj.get(node, []):
                    if neighbor in adj:
                        if visited.get(neighbor, 0) == 1:
                            has_cycle = True
                            return
                        elif visited.get(neighbor, 0) == 0:
                            dfs(neighbor)
                            if has_cycle:
                                return
                visited[node] = 2
                
            for t_id in task_ids:
                if visited.get(t_id, 0) == 0:
                    dfs(t_id)
                    if has_cycle:
                        break
                        
            if has_cycle:
                cycle_score = 0.0
                return False, "Circular dependency cycle detected in tasks", 0.0
                
        # 4. Milestone Coverage (10%)
        milestone_score = 1.0
        total_tasks = len(tasks)
        covered_tasks = 0
        for t in tasks:
            m_id = t.get("milestone_id")
            if m_id:
                if m_id in milestone_ids:
                    covered_tasks += 1
                else:
                    return False, f"Task {t['id']} references non-existent milestone {m_id}", 0.0
            else:
                # Task doesn't belong to a milestone (which is valid, but decreases score)
                pass
                
        if total_tasks > 0:
            milestone_score = covered_tasks / total_tasks
            
        # Calculate weighted confidence
        confidence = (
            schema_score * 0.4 +
            dependency_score * 0.3 +
            cycle_score * 0.2 +
            milestone_score * 0.1
        )
        confidence = round(confidence, 2)
        
        return True, "", confidence
