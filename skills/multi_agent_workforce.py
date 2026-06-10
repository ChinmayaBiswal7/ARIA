import os
import json
import time
import sqlite3
import uuid
from typing import Dict, Any, List, Tuple

class AriaCollaborativeWorkforceManager:
    def __init__(self, aria_instance, db_path: str = "aria_orchestrator.db"):
        self.aria = aria_instance
        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        """Initializes tables for workforce coordination and artifact tracking."""
        if not self.db_path:
            return
        try:
            from contextlib import closing
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS workforce_sessions (
                        id TEXT PRIMARY KEY,
                        campaign_id TEXT,
                        participating_agents TEXT, -- JSON array
                        tasks_generated INTEGER,
                        success_score REAL,
                        review_score REAL,
                        timestamp INTEGER
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS workforce_artifacts (
                        id TEXT PRIMARY KEY,
                        workforce_session_id TEXT,
                        agent_name TEXT,
                        confidence REAL,
                        output_json TEXT,
                        timestamp INTEGER
                    )
                """)
                # Dynamic Migration (Sprint P19): Add columns if they do not exist
                for col, col_type in [("domain_keyword", "TEXT"), ("task_category", "TEXT"), ("execution_time_ms", "INTEGER")]:
                    try:
                        conn.execute(f"ALTER TABLE workforce_sessions ADD COLUMN {col} {col_type}")
                    except sqlite3.OperationalError:
                        pass  # Column already exists
                conn.commit()
        except Exception as e:
            print(f"[WorkforceManager] Database initialization failed: {e}")

    def wait_for_tokens(self, keys: List[Tuple[str, str]], timeout: int = 10) -> Dict[str, Any]:
        """Component P15: Periodically polls the Blackboard until all listed (topic, key) pairs are ready."""
        from skills.blackboard import AriaBlackboard
        blackboard = AriaBlackboard()
        start_time = time.time()
        results = {}
        
        while time.time() - start_time < timeout:
            missing = False
            for topic, key in keys:
                val = blackboard.read(topic, key)
                if val is None:
                    missing = True
                    break
                else:
                    results[f"{topic}/{key}"] = val
            if not missing:
                return results
            time.sleep(0.1)
        return results

    def coordinate_parallel_campaign_pass(self, campaign_id: str, milestone_id: str, broad_goal: str) -> Dict[str, Any]:
        """Component P15: Spawns specialized agents dynamically, executes reviews, and logs sessions."""
        session_id = f"SESS_{uuid.uuid4().hex[:6].upper()}"
        print(f"[WorkforceManager] Starting collaborative group session {session_id} for goal: '{broad_goal}'")
        start_time = time.time()

        # Extract domain and category (Sprint P19)
        domain_keyword, task_category = self._extract_domain_and_category(broad_goal)

        # 1. Dynamic Agent Capability Discovery (Grounded by Workforce Optimizer)
        try:
            from skills.workforce_optimizer import AriaWorkforceOptimizer
            optimizer = AriaWorkforceOptimizer(self.db_path)
            
            from skills.agent_registry import registry
            default_agents = registry.get_capable_agents(broad_goal)
            
            participating_agents = optimizer.select_optimal_team(domain_keyword, task_category, default_agents)
        except Exception as opt_err:
            print(f"[WorkforceManager] Optimizer failed, using defaults: {opt_err}")
            from skills.agent_registry import registry
            participating_agents = registry.get_capable_agents(broad_goal)
            
        print(f"[WorkforceManager] Running workforce allocation with agents: {participating_agents}")

        from skills.blackboard import AriaBlackboard
        blackboard = AriaBlackboard()

        # 2. Stage 1: Run CareerAgent if participating
        has_career = "careeragent" in participating_agents
        career_key = f"{session_id}/careeragent"
        if has_career:
            career_payload = {"goal": broad_goal, "mode": "GAP_ANALYSIS"}
            self._dispatch_to_workforce(registry, "careeragent", career_payload, career_key, session_id, campaign_id)

        # 3. Stage 2: Peer-Review & Parallel Run
        # If career agent published gaps, pass them to ResearchAgent to review against market trends
        research_key = f"{session_id}/researchagent"
        has_research = "researchagent" in participating_agents
        if has_research:
            # Retrieve CareerAgent's output from the namespaced key
            career_output = blackboard.read("workforce", career_key)
            career_gaps = career_output.get("data") if career_output else "Java Backend Engineering"
            
            research_payload = {
                "query": f"Review and validate hiring trends for: {career_gaps}. Confirm ifSpring Boot REST APIs are requested."
            }
            self._dispatch_to_workforce(registry, "researchagent", research_payload, research_key, session_id, campaign_id)

        # Run other agents (like HabitIntelligenceAgent) in parallel
        for agent_name in participating_agents:
            if agent_name in ("careeragent", "researchagent"):
                continue
            agent_key = f"{session_id}/{agent_name}"
            payload = {"request": "GET_PREDICTED_FOCUS_BUDGET", "goal": broad_goal}
            self._dispatch_to_workforce(registry, agent_name, payload, agent_key, session_id, campaign_id)

        # 4. Synchronize via Blackboard using wait_for_tokens
        expected_keys = [("workforce", f"{session_id}/{agent}") for agent in participating_agents]
        token_results = self.wait_for_tokens(expected_keys, timeout=12)

        # 5. Extract Outputs & Confidence Scores
        aggregated_context = {}
        total_confidence = 0.0
        valid_agents_count = 0
        review_score = 1.0  # Peer-review agreement index

        for agent in participating_agents:
            t_key = f"workforce/{session_id}/{agent}"
            token = token_results.get(t_key)
            if token:
                data = token.get("data")
                conf = float(token.get("confidence", 0.90))
                aggregated_context[agent] = {
                    "data": data,
                    "confidence": conf
                }
                total_confidence += conf
                valid_agents_count += 1
                
                # Write to workforce_artifacts
                self._record_workforce_artifact(session_id, agent, conf, data)
                
        # Compute review score: if CareerAgent and ResearchAgent output conflict or align
        if "careeragent" in aggregated_context and "researchagent" in aggregated_context:
            res_data = str(aggregated_context["researchagent"]["data"]).lower()
            if "spring boot" in res_data or "api" in res_data:
                review_score = 0.95  # High agreement
            else:
                review_score = 0.70  # Modest alignment

        avg_confidence = (total_confidence / valid_agents_count) if valid_agents_count > 0 else 0.90

        # 6. Peer-Review Synthesis via PlannerAgent
        final_plan_json = self._execute_planner_peer_review(broad_goal, aggregated_context, avg_confidence, review_score)

        # 7. Inject Synthesized Tasks to campaign matrix
        injected_tasks = self._inject_collaborative_task_graph(campaign_id, milestone_id, final_plan_json)

        # 8. Log workforce session (Sprint P19)
        execution_time_ms = int((time.time() - start_time) * 1000)
        self._record_workforce_session(
            session_id=session_id, 
            campaign_id=campaign_id, 
            agents=participating_agents, 
            tasks_count=len(injected_tasks), 
            review_score=review_score,
            domain_keyword=domain_keyword,
            task_category=task_category,
            execution_time_ms=execution_time_ms
        )

        return {
            "status": "COLLABORATION_SUCCESS",
            "campaign_id": campaign_id,
            "session_id": session_id,
            "sources_coordinated": participating_agents,
            "tasks_generated_count": len(injected_tasks),
            "injected_task_ids": injected_tasks,
            "review_score": review_score,
            "execution_duration_ms": execution_time_ms
        }

    def _dispatch_to_workforce(self, registry, agent_name: str, payload: dict, blackboard_key: str, session_id: str, campaign_id: str):
        """Helper to invoke registry wrappers and write outputs to the Blackboard."""
        wrapper = registry.get(agent_name)
        if not wrapper:
            return
        
        try:
            task_id = f"WF_{agent_name.upper()[:4]}_{session_id[5:]}"
            res_str = wrapper.run(task_id, f"Workforce session task for {agent_name}", payload, campaign_id)
            
            # Parse output format dynamically
            try:
                res_obj = json.loads(res_str)
                confidence = res_obj.get("confidence") or res_obj.get("metadata", {}).get("confidence", 0.90)
                data = res_obj.get("report") or res_obj.get("data") or res_obj
            except Exception:
                confidence = 0.90
                data = res_str

            from skills.blackboard import AriaBlackboard
            AriaBlackboard().publish(
                topic="workforce",
                key=blackboard_key,
                value={
                    "agent": agent_name,
                    "data": data,
                    "confidence": confidence,
                    "timestamp": int(time.time())
                },
                source="WorkforceManager",
                ttl_hours=24
            )
        except Exception as e:
            print(f"[WorkforceManager] Failed to dispatch agent '{agent_name}': {e}")

    def _execute_planner_peer_review(self, goal: str, context: dict, avg_confidence: float, review_score: float) -> str:
        """Invokes the planner agent to synthesize aggregated workforce tokens into a final plan."""
        prompt = f"""
        You are ARIA's master PlannerAgent running a collaborative workforce synthesis pass.
        Synthesize the raw inputs compiled concurrently by our specialized sub-agents below into a highly precise, executable task list.
        
        == HIGH LEVEL GOAL ==
        {goal}
        
        == WORKFORCE TELEMETRY (Confidence Score Weighted) ==
        Average Group Confidence: {avg_confidence:.2f}
        Peer-Review Agreement Score: {review_score:.2f}
        
        Sub-Agent Context Blocks:
        {json.dumps(context, indent=2)}
        
        Generate a valid, clean JSON structure matching this exact design contract:
        {{
            "tasks": [
                {{"target": "CodingAgent", "desc": "Build secure Spring REST API architecture endpoints"}},
                {{"target": "LearningAgent", "desc": "Study Spring Security session filters documentation"}}
            ]
        }}
        """
        if hasattr(self.aria, "brain") and self.aria.brain:
            try:
                # Use brain to think
                return self.aria.brain.think(prompt)
            except Exception:
                pass
        return json.dumps({"tasks": [
            {"target": "CodingAgent", "desc": "Complete Spring Boot REST baseline endpoints project."},
            {"target": "LearningAgent", "desc": "Review notes matching career gap data."}
        ]})

    def _inject_collaborative_task_graph(self, campaign_id: str, milestone_id: str, raw_plan_json: str) -> List[str]:
        """Injects the synthesized multi-agent task graph directly into the orchestrator tasks database."""
        injected_ids = []
        try:
            plan_data = json.loads(raw_plan_json)
            tasks = plan_data.get("tasks", [])
        except Exception:
            return injected_ids

        try:
            from contextlib import closing
            with closing(sqlite3.connect(self.db_path)) as conn:
                for t in tasks:
                    t_id = f"TSK_WF_{uuid.uuid4().hex[:6].upper()}"
                    agent = t.get("target", "LearningAgent")
                    desc = t.get("desc", "Task description blueprint.")
                    
                    conn.execute("""
                        INSERT INTO agent_tasks (id, milestone_id, campaign_id, agent_name, task_description, priority, status, created_at)
                        VALUES (?, ?, ?, ?, ?, 8, 'PENDING', ?)
                    """, (t_id, milestone_id, campaign_id, agent.lower(), desc, int(time.time())))
                    injected_ids.append(t_id)
                conn.commit()
        except Exception as e:
            print(f"[WorkforceManager] Failed to inject task graph: {e}")
        return injected_ids

    def _extract_domain_and_category(self, goal: str) -> Tuple[str, str]:
        goal_lower = goal.lower()
        
        # 1. Domain extraction
        supported_domains = ["java", "spring", "dbms", "dsa", "docker", "aws", "security", "career", "resume", "interview"]
        domain = "general"
        for d in supported_domains:
            if d in goal_lower:
                domain = d
                break
                
        # 2. Category extraction
        category = "GENERAL"
        if any(k in goal_lower for k in ["interview", "prep", "placement", "mock"]):
            category = "INTERVIEW"
        elif any(k in goal_lower for k in ["resume", "apply", "cv", "portfolio", "profile"]):
            category = "RESUME"
        elif any(k in goal_lower for k in ["project", "build", "deploy", "docker", "aws", "endpoint"]):
            category = "PROJECT"
        elif any(k in goal_lower for k in ["study", "learn", "revise", "read", "normal form"]):
            category = "LEARNING"
            
        return domain, category

    def _record_workforce_session(self, session_id: str, campaign_id: str, agents: List[str], tasks_count: int, review_score: float, domain_keyword: str = "general", task_category: str = "GENERAL", execution_time_ms: int = 0):
        try:
            from contextlib import closing
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO workforce_sessions (id, campaign_id, participating_agents, tasks_generated, success_score, review_score, timestamp, domain_keyword, task_category, execution_time_ms)
                    VALUES (?, ?, ?, ?, 1.0, ?, ?, ?, ?, ?)
                """, (session_id, campaign_id, json.dumps(sorted(agents)), tasks_count, review_score, int(time.time()), domain_keyword.upper(), task_category.upper(), execution_time_ms))
                conn.commit()
        except Exception as e:
            print(f"[WorkforceManager] Failed to write session to ledger: {e}")

    def _record_workforce_artifact(self, session_id: str, agent_name: str, confidence: float, data: Any):
        try:
            from contextlib import closing
            artifact_id = f"ART_{agent_name.upper()[:4]}_{uuid.uuid4().hex[:6].upper()}"
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    INSERT INTO workforce_artifacts (id, workforce_session_id, agent_name, confidence, output_json, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (artifact_id, session_id, agent_name, confidence, json.dumps(data), int(time.time())))
                conn.commit()
        except Exception as e:
            print(f"[WorkforceManager] Failed to write artifact to ledger: {e}")
