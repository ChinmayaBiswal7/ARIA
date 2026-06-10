"""
skills/chief_of_staff_agent.py — Sprint P10: Chief of Staff Agent for ARIA
==========================================================================
Operates as the top-level autonomous brain of ARIA. Continuously monitors
campaigns, habits, and coach briefs, executes safety validator guards, and
autonomously deploys strategic adjustments to the task execution graph.
"""

import json
import time
import os
import threading
from typing import Dict, Any, List

# ── P24: Executive Brain (Shadow Mode) ──────────────────────────────────────
_EXECUTIVE_BRAIN_ENABLED = True   # set False to disable shadow mode without code changes

from skills.base_agent import BaseAgent
from skills.blackboard import AriaBlackboard
from skills.event_bus import EventBus
from skills.agent_status import get_db_connection

class AriaChiefOfStaffAgent(BaseAgent):
    def __init__(self, aria_instance=None):
        super().__init__("ChiefOfStaffAgent", aria_instance)
        self.blackboard = AriaBlackboard()
        self.bus = EventBus()
        self._running = True
        try:
            from skills.agent_status import get_db_connection
            with get_db_connection() as _conn:
                self.db_path = _conn.execute("PRAGMA database_list").fetchone()[2]
        except Exception:
            self.db_path = "aria_orchestrator.db"
        self._thread = threading.Thread(target=self._background_loop, name="ChiefOfStaffBackground", daemon=True)
        self._thread.start()
        print("[ChiefOfStaff] Autonomous executive monitoring loop active (15-minute cycle).")

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        self.log_state_shift("RUNNING", f"Initiating strategic review pass: {task_id}")
        
        # 1. Fetch reality context from the Blackboard and SQLite
        weekly_analytics = self.blackboard.read("habits", "weekly_analytics") or {}
        habit_prediction = self.blackboard.read("habits", "habit_prediction") or {}
        daily_brief = self.blackboard.read("coach", "daily_brief") or ""
        active_campaigns = self._get_active_campaign_telemetry()
        target_campaign_id = active_campaigns[0]["id"] if active_campaigns else None

        # 1b. Fetch Life OS state and overall life load constraints
        life_state = "NORMAL"
        overall_life_load = 0.0
        try:
            from skills.personal_os_reasoning import PersonalOSReasoningEngine
            pos = PersonalOSReasoningEngine(db_path=self.db_path)
            pressures = pos.compute_systemic_pressures()
            life_state = pressures.get("life_state", "NORMAL")
            overall_life_load = pressures.get("overall_life_load", 0.0)
        except Exception as e:
            print(f"[ChiefOfStaff] Failed to compute Life OS pressures: {e}")

        # If overall life load is critical or in recovery/burnout state, we throttle/suppress autonomous loops
        auto_approved = []
        remediations = []
        opp_proposals = []

        if life_state in ("BURNOUT_RISK_MODE", "RECOVERY_MODE") or overall_life_load > 0.85:
            print(f"[ChiefOfStaff] SAFE-MODE ACTIVE (LifeState: {life_state}, Load: {overall_life_load}). Throttling autonomous loop approvals, sweeps, and remediations.")
            self.log_state_shift("IDLE", f"Safe-mode active. Suppressing autonomous loops. Load: {overall_life_load}")
            return json.dumps({
                "status": "SAFE_MODE_ACTIVE",
                "campaign_id": target_campaign_id,
                "confidence": 0.0,
                "reasoning": f"System in safe-mode due to high load {overall_life_load} ({life_state}).",
                "executed": [],
                "rejected": []
            })

        # Run Autonomous Executive Operations (P14 updates)
        auto_approved = self._run_autonomous_approvals(weekly_analytics, daily_brief)
        
        # Remediations loop disabled during EXAM_MODE to protect user study focus
        if life_state != "EXAM_MODE":
            remediations = self._run_autonomous_remediations()
        else:
            print("[ChiefOfStaff] EXAM_MODE active. Suppressing generic background remediation sweeps.")

        # Run Opportunity Discovery (P21 updates)
        opp_proposals = self._check_new_opportunities()

        # 2. Evaluate Executive Confidence Threshold
        confidence, risk_reasons = self._calculate_executive_confidence(
            weekly_analytics, habit_prediction, daily_brief, active_campaigns
        )
        print(f"[ChiefOfStaff] Calculated Executive Confidence Score: {confidence:.2f} (Reasons: {risk_reasons})")

        # 3. Call Vertex AI to formulate executive recommendations
        actions_to_take = []
        strategic_reasoning = "System operating within nominal constraints."
        target_campaign_id = None
        
        if active_campaigns:
            target_campaign_id = active_campaigns[0]["id"]
            
        if active_campaigns:
            # Vertex JSON schema mapping
            decision_schema = {
                "type": "OBJECT",
                "properties": {
                    "strategic_reasoning": {"type": "STRING"},
                    "actions": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "action_type": {"type": "STRING"}, # 'INJECT_TASK', 'RAISE_PRIORITY', 'TRIGGER_AGENT'
                                "target_agent": {"type": "STRING"}, # 'BrowserAgent', 'ResearchAgent', etc.
                                "payload_description": {"type": "STRING"},
                                "priority": {"type": "STRING"}, # 'HIGH', 'MEDIUM', 'LOW'
                                "dependencies": {
                                    "type": "ARRAY",
                                    "items": {"type": "STRING"}
                                }
                            },
                            "required": ["action_type", "target_agent", "payload_description", "priority"]
                        }
                    }
                },
                "required": ["strategic_reasoning", "actions"]
            }

            planner_prompt = f"""
            You are ARIA's core Chief of Staff Agent.
            Analyze the following operational reality vectors and formulate executive interventions if required.
            
            == ACTIVE CAMPAIGNS ==
            {json.dumps(active_campaigns)}
            
            == COACH RISK ANALYSIS ==
            {daily_brief}
            
            == USER TELEMETRY & PREDICTIONS ==
            Weekly Habits: {json.dumps(weekly_analytics)}
            Prediction: {json.dumps(habit_prediction)}
            
            Determine if any intervention (injecting tasks, triggering agent research/checks, raising priority weights) is strategic.
            """

            try:
                from skills.vertex_bridge import AriaVertexBridge
                bridge = AriaVertexBridge()
                if bridge.initialized:
                    res_raw = bridge.generate(prompt=planner_prompt, enforce_json_schema=decision_schema, model_type="pro")
                    decision = json.loads(res_raw)
                    strategic_reasoning = decision.get("strategic_reasoning", "")
                    actions_to_take = decision.get("actions", [])
            except Exception as e:
                print(f"[ChiefOfStaff] Vertex call failed: {e}. Falling back to default rules.")
                # Local Rule Fallback: If campaign overdue is present, trigger Research and boost Priority
                if "CAMPAIGN_OVERDUE" in risk_reasons:
                    strategic_reasoning = "Overdue task triggers localized priority boost fallback."
                    actions_to_take = [
                        {"action_type": "RAISE_PRIORITY", "target_agent": "orchestrator", "payload_description": "Boost priority", "priority": "HIGH"},
                        {"action_type": "TRIGGER_AGENT", "target_agent": "researchagent", "payload_description": "Gather requirements context", "priority": "MEDIUM"}
                    ]

        # 4. Filter, Budget & Execute Actions
        executed_actions = []
        rejected_actions = []
        
        if confidence >= 0.75 and actions_to_take and target_campaign_id:
            # Load budget
            budget = self._get_daily_budget()
            
            for action in actions_to_take:
                # Validation check
                is_valid, reason = self._validate_action(target_campaign_id, action)
                if not is_valid:
                    rejected_actions.append({"action": action, "reason": f"Validator rejected: {reason}"})
                    continue
                    
                # Budget check
                a_type = action["action_type"].upper()
                if a_type == "RAISE_PRIORITY":
                    if budget["priority_boosts"] >= 5:
                        rejected_actions.append({"action": action, "reason": "Priority boost budget exceeded"})
                        continue
                    budget["priority_boosts"] += 1
                elif a_type == "TRIGGER_AGENT":
                    if budget["agent_triggers"] >= 10:
                        rejected_actions.append({"action": action, "reason": "Agent trigger budget exceeded"})
                        continue
                    budget["agent_triggers"] += 1
                elif a_type == "INJECT_TASK":
                    if budget["task_injections"] >= 3:
                        rejected_actions.append({"action": action, "reason": "Task injection budget exceeded"})
                        continue
                    budget["task_injections"] += 1
                    
                # Action is valid and within budget -> Execute
                success = self._execute_action(target_campaign_id, action, confidence, strategic_reasoning)
                if success:
                    executed_actions.append(action)
                else:
                    rejected_actions.append({"action": action, "reason": "Execution failure"})
            
            # Save updated budget
            self._save_daily_budget(budget)
        else:
            # Gated below 0.75 or no campaigns: publish recommendation only
            if actions_to_take and target_campaign_id:
                recommendations = {
                    "campaign_id": target_campaign_id,
                    "confidence": confidence,
                    "reasoning": strategic_reasoning,
                    "proposed_actions": actions_to_take,
                    "timestamp": int(time.time())
                }
                self.blackboard.publish("coach", "cos_recommendations", recommendations, self.agent_name, ttl_hours=24)
                print(f"[ChiefOfStaff] Confidence ({confidence:.2f}) < 0.75. Recommendations staged on Blackboard.")

        # Derive final CoS directive and domain for comparison and shadow logging
        if life_state in ("BURNOUT_RISK_MODE", "RECOVERY_MODE") or overall_life_load > 0.85:
            cos_directive = "DEFER_ALL"
            cos_domain    = "GENERAL"
        elif not executed_actions:
            cos_directive = "MAINTAIN_IDLE"
            cos_domain    = "GENERAL"
        else:
            top_action    = executed_actions[0]
            cos_directive = top_action.get("action_type", "MAINTAIN_IDLE").upper()
            cos_domain    = (
                top_action.get("payload_description", "GENERAL").split()[0].upper()
            )

        # ── P24 Stage 2: Blackboard Advisory Mismatch Check ───────────────
        try:
            advisory = self.blackboard.read("executive", "brain_advisory")
            if advisory and isinstance(advisory, dict):
                adv_dir = advisory.get("directive", "").upper()
                adv_dom = advisory.get("domain", "").upper()
                adv_just = advisory.get("justification", "")
                
                if adv_dir != cos_directive or adv_dom != cos_domain:
                    warning_msg = (
                        f"[ChiefOfStaff] [WARNING] Mismatch with Executive Brain advisory! "
                        f"CoS chose: {cos_directive}/{cos_domain} | "
                        f"Brain advised: {adv_dir}/{adv_dom}. Justification: {adv_just}"
                    )
                    print(warning_msg)
                    
                    # Record mismatch warning inside cos_action_history
                    history = self.blackboard.read("coach", "cos_action_history") or []
                    history.append({
                        "timestamp": int(time.time()),
                        "campaign": target_campaign_id or "GENERAL",
                        "campaign_id": target_campaign_id or "GENERAL",
                        "action": "ALIGNMENT_WARNING",
                        "description": warning_msg,
                        "reason": f"Brain advised {adv_dir}/{adv_dom}",
                        "confidence": confidence
                    })
                    if len(history) >= 100:
                        history.pop(0)
                    self.blackboard.publish("coach", "cos_action_history", history, self.agent_name, ttl_hours=720)
        except Exception as adv_exc:
            print(f"[ChiefOfStaff] Error checking blackboard advisory: {adv_exc}")

        # 5. Save Executive Memory Log
        self.log_state_shift("IDLE", f"Review complete. Executed: {len(executed_actions)} | Rejected: {len(rejected_actions)}")

        # ── P24 Stage 1: Shadow Brain observation (non-blocking, zero side-effects) ──
        if _EXECUTIVE_BRAIN_ENABLED:
            self._shadow_observe(
                life_state      = life_state,
                executed_actions= executed_actions,
                confidence      = confidence,
            )

        return json.dumps({
            "status": "SUCCESS",
            "campaign_id": target_campaign_id,
            "confidence": confidence,
            "reasoning": strategic_reasoning,
            "executed": executed_actions,
            "rejected": rejected_actions
        })

    def stop(self):
        self._running = False
        if self._thread:
            try:
                self._thread.join(timeout=1.0)
            except Exception:
                pass
            print("[ChiefOfStaff] Autonomous review daemon thread terminated.")

    # ── P24 Stage 1: Shadow Brain observer ──────────────────────────────────
    def _shadow_observe(
        self,
        life_state: str,
        executed_actions: list,
        confidence: float,
    ) -> None:
        """
        Non-blocking shadow pass.  Determines the dominant CoS directive and
        domain from the executed action list, then fires AriaExecutiveBrain.observe().
        Any exception is silently caught — this must never break the CoS loop.
        """
        try:
            # Derive the dominant directive/domain from what CoS actually executed.
            # If nothing was executed, label as MAINTAIN_IDLE.
            if not executed_actions:
                cos_directive = "MAINTAIN_IDLE"
                cos_domain    = "GENERAL"
            else:
                top_action    = executed_actions[0]
                cos_directive = top_action.get("action_type", "MAINTAIN_IDLE").upper()
                cos_domain    = (
                    top_action.get("payload_description", "GENERAL").split()[0].upper()
                )

            # Determine appropriate event trigger label
            if life_state in ("BURNOUT_RISK_MODE", "RECOVERY_MODE"):
                event_source = "LIFE_OS_SHIFT"
            elif life_state == "EXAM_MODE":
                event_source = "EXAM_PREP_GUARD"
            elif confidence >= 0.75 and executed_actions:
                event_source = "CAMPAIGN_BLOCKER" if "BLOCKER" in cos_directive else "DAILY_REVIEW"
            else:
                event_source = "DAILY_REVIEW"

            # Resolve the db_path used by CoS (inherits from agent_status)
            try:
                from skills.agent_status import get_db_connection
                import sqlite3
                with get_db_connection() as _conn:
                    db_path = _conn.execute("PRAGMA database_list").fetchone()[2]
            except Exception:
                db_path = "aria_orchestrator.db"

            from skills.executive_brain import AriaExecutiveBrain
            brain = AriaExecutiveBrain(self.aria, db_path)
            brain.observe(
                event_source  = event_source,
                cos_directive = cos_directive,
                cos_domain    = cos_domain,
                cos_risk      = 0.25,   # default; will improve in Stage 2 with sim data
                cos_roi       = round(confidence, 2),
            )
        except Exception as exc:
            print(f"[ChiefOfStaff] P24 shadow pass warning (non-fatal): {exc}")

    def _background_loop(self):
        tick_seconds = 900  # 15 minutes
        while self._running:
            try:
                # Run autonomous cycle step
                self.run(f"COS_{int(time.time())}", "Autonomous review cycle run", {})
            except Exception as e:
                print(f"[ChiefOfStaff] Autonomous review pass failed: {e}")
                
            # Sleep in chunks to allow fast exit
            for _ in range(tick_seconds):
                if not self._running:
                    break
                time.sleep(1)

    # ── Telemetry & Queries ──────────────────────────────────────────────────
    def _get_active_campaign_telemetry(self) -> List[Dict[str, Any]]:
        campaign_metrics = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, goal_text, status, progress FROM campaigns WHERE status = 'RUNNING'")
                rows = cursor.fetchall()
                for r in rows:
                    campaign_metrics.append({
                        "id": r[0],
                        "goal_text": r[1],
                        "status": r[2],
                        "progress": r[3]
                    })
        except Exception as e:
            print(f"[ChiefOfStaff] Error querying active campaigns: {e}")
        return campaign_metrics

    def _calculate_executive_confidence(self, weekly_analytics: dict, habit_prediction: dict, daily_brief: str, active_campaigns: list) -> tuple:
        confidence = 0.0
        reasons = []
        
        # 1. Risk detected in coach brief (+0.3)
        if "risk" in daily_brief.lower() or "overdue" in daily_brief.lower():
            confidence += 0.3
            reasons.append("RISK_DETECTED")
            
        # 2. Campaign overdue (+0.3)
        overdue_present = False
        now = time.time()
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) FROM agent_tasks 
                    WHERE status IN ('PENDING', 'RUNNING') 
                      AND (started_at IS NULL OR (? - started_at) > 172800)
                      AND campaign_id IN (SELECT id FROM campaigns WHERE status = 'RUNNING')
                """, (now,))
                if cursor.fetchone()[0] > 0:
                    overdue_present = True
        except Exception:
            pass
            
        if overdue_present:
            confidence += 0.3
            reasons.append("CAMPAIGN_OVERDUE")
            
        # 3. Habit score decline (+0.2)
        prod_score = weekly_analytics.get("productivity_score", 100)
        if prod_score < 75:
            confidence += 0.2
            reasons.append("HABIT_DECLINE")
            
        # 4. Neural Prediction high confidence skip (+0.2)
        predicted_skip = False
        if habit_prediction:
            prob = habit_prediction.get("probability", 0.0)
            topic = habit_prediction.get("predicted_topic", "Study")
            # If low study probability or explicit skip prediction
            if prob < 0.40 or topic.lower() == "skip":
                predicted_skip = True
                
        if predicted_skip:
            confidence += 0.2
            reasons.append("SKIP_FORECAST")
            
        return min(1.0, confidence), reasons

    # ── Rule Validator Safety Guards ──────────────────────────────────────────
    def _validate_action(self, campaign_id: str, action: dict) -> tuple:
        a_type = action.get("action_type", "").upper()
        target_agent = action.get("target_agent", "").strip()
        desc = action.get("payload_description", "").strip()
        
        if not a_type or not target_agent:
            return False, "Missing action_type or target_agent"

        # Check campaign exists and is active
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT status FROM campaigns WHERE id = ?", (campaign_id,))
                row = cursor.fetchone()
                if not row:
                    return False, f"Campaign {campaign_id} does not exist"
                if row[0] not in ("RUNNING", "PENDING"):
                    return False, f"Campaign is in inactive status: {row[0]}"

                if a_type == "INJECT_TASK":
                    # Max 3 injected tasks check (daily constraint)
                    cursor.execute("""
                        SELECT COUNT(*) FROM agent_tasks 
                        WHERE campaign_id = ? 
                          AND id LIKE 'TSK_INJECT_%'
                          AND created_at >= ?
                    """, (campaign_id, int(time.time()) - 86400))
                    injected_count = cursor.fetchone()[0]
                    if injected_count >= 3:
                        return False, "Daily limit of 3 task injections exceeded for this campaign"
                        
                    # Duplicate check
                    cursor.execute("""
                        SELECT COUNT(*) FROM agent_tasks 
                        WHERE campaign_id = ? AND task_description = ?
                    """, (campaign_id, desc))
                    if cursor.fetchone()[0] > 0:
                        return False, "Duplicate task description already exists in campaign"
        except Exception as e:
            return False, f"DB error during validation: {e}"

        return True, "Valid"

    # ── Daily Budget Management ──────────────────────────────────────────────
    def _get_daily_budget(self) -> dict:
        today_str = time.strftime("%Y-%m-%d")
        budget = self.blackboard.read("coach", "cos_daily_budget")
        
        # Reset budget if empty or key corresponds to a different date
        if not budget or budget.get("date") != today_str:
            budget = {
                "date": today_str,
                "priority_boosts": 0,
                "agent_triggers": 0,
                "task_injections": 0,
                "auto_approvals": 0,
                "research_triggers": 0
            }
        else:
            # Backwards compatibility check
            if "auto_approvals" not in budget:
                budget["auto_approvals"] = 0
            if "research_triggers" not in budget:
                budget["research_triggers"] = 0
        return budget

    def _save_daily_budget(self, budget: dict):
        self.blackboard.publish("coach", "cos_daily_budget", budget, self.agent_name, ttl_hours=48)

    # ── Action Execution ──────────────────────────────────────────────────────
    def _execute_action(self, campaign_id: str, action: dict, confidence: float, reasoning: str) -> bool:
        a_type = action["action_type"].upper()
        target = action["target_agent"].lower()
        desc = action["payload_description"]
        
        success = False
        try:
            if a_type == "RAISE_PRIORITY":
                # Boost priority of pending campaign tasks via EventBus notification
                self.bus.publish("COACH_ADJUSTMENT", {
                    "campaign_id": campaign_id,
                    "action": "increase_priority"
                })
                success = True
            elif a_type == "TRIGGER_AGENT":
                # Fire decoupled trigger on Blackboard for the target agent
                # The agent itself or coordinator will monitor
                self.blackboard.publish("chief_of_staff", f"trigger_{target}", {
                    "task_description": desc,
                    "campaign_id": campaign_id,
                    "triggered_at": int(time.time())
                }, self.agent_name, ttl_hours=12)
                success = True
            elif a_type == "INJECT_TASK":
                # Call inject_task directly if orchestrator instance is available
                # Import safely to avoid cycles
                from skills.agent_orchestrator import AriaMultiAgentOrchestrator
                orch = AriaMultiAgentOrchestrator()
                
                # Fetch first milestone in campaign to place task under, or let it float
                m_id = None
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id FROM campaign_milestones WHERE campaign_id = ? LIMIT 1", (campaign_id,))
                    m_row = cursor.fetchone()
                    if m_row:
                        m_id = m_row[0]
                        
                task_data = {
                    "agent_name": target,
                    "task_description": desc,
                    "priority": action.get("priority", "MEDIUM"),
                    "milestone_id": m_id
                }
                deps = action.get("dependencies", [])
                
                injected_task_id = orch.inject_task(campaign_id=campaign_id, task_data=task_data, dependency_ids=deps)
                desc = f"{desc} | Injected Task ID: {injected_task_id}"
                success = True
                
            if success:
                # Log action to Executive Memory (coach/cos_action_history)
                self._record_executive_memory(campaign_id, a_type, desc, reasoning, confidence)
                
                # Log to the self-improvement intervention ledger
                try:
                    from skills.self_improvement_core import AriaSelfImprovementCore
                    si_core = AriaSelfImprovementCore()
                    intervention_id = f"INT_COS_{int(time.time())}_{a_type}"
                    si_core.register_intervention(
                        intervention_id=intervention_id,
                        agent="ChiefOfStaffAgent",
                        action=a_type,
                        reason=desc,
                        result="PENDING",
                        success_score=None,
                        campaign_id=campaign_id
                    )
                    print(f"[ChiefOfStaff] Registered intervention {intervention_id} in SQLite ledger.")
                except Exception as si_err:
                    print(f"[ChiefOfStaff] Failed to log intervention in SQLite: {si_err}")
                
        except Exception as e:
            print(f"[ChiefOfStaff] Execution failed for action {a_type} targeting {target}: {e}")
            success = False
            
        return success

    def _record_executive_memory(self, campaign_id: str, action_type: str, description: str, reasoning: str, confidence: float):
        history = self.blackboard.read("coach", "cos_action_history") or []
        
        # Enforce rolling history boundary (max 100 entries)
        if len(history) >= 100:
            history.pop(0)
            
        history.append({
            "timestamp": int(time.time()),
            "campaign": campaign_id,
            "campaign_id": campaign_id,
            "action": action_type,
            "description": description,
            "reason": reasoning,
            "confidence": confidence
        })
        self.blackboard.publish("coach", "cos_action_history", history, self.agent_name, ttl_hours=720) # 30 days history persistence

    def _run_autonomous_approvals(self, weekly_analytics: dict, daily_brief: str) -> List[str]:
        """Component P14: Auto-promotes high-confidence plans to active status using multi-factor gating."""
        approved_ids = []
        staged_plans = []
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, goal_text FROM campaigns WHERE status = 'DRY_RUN_PENDING'")
                for r in cursor.fetchall():
                    staged_plans.append({"id": r[0], "goal_text": r[1]})
        except Exception as e:
            print(f"[ChiefOfStaff] Error querying staged plans: {e}")
            
        if not staged_plans:
            return approved_ids

        budget = self._get_daily_budget()
        auto_approvals_today = budget.get("auto_approvals", 0)

        for plan in staged_plans:
            campaign_id = plan["id"]
            if auto_approvals_today >= 2:
                print(f"[ChiefOfStaff] Auto-approval daily limit of 2 exceeded.")
                break

            # Read planner confidence published by the task planner
            plan_metadata = self.blackboard.read("planner", f"taskplan_{campaign_id}") or {}
            planner_confidence = float(plan_metadata.get("planner_confidence", 0.0))

            # Compute campaign risk penalties (calculate risk threshold)
            campaign_risk, _ = self._calculate_executive_confidence(weekly_analytics, {}, daily_brief, [])
            cos_score = 1.0 - campaign_risk
            
            # User productivity/habit trend weight
            habit_score = float(weekly_analytics.get("productivity_score", 100)) / 100.0

            # Multi-factor Governed Promotion Formula
            approval_score = (planner_confidence * 0.4) + (cos_score * 0.3) + (habit_score * 0.3)
            print(f"[ChiefOfStaff] Evaluating auto-approval for {campaign_id}: Combined Score = {approval_score:.2f} (Planner={planner_confidence:.2f}, CoS={cos_score:.2f}, Habits={habit_score:.2f})")

            if approval_score >= 0.92:
                try:
                    with get_db_connection() as conn:
                        conn.execute("UPDATE campaigns SET status = 'RUNNING' WHERE id = ?", (campaign_id,))
                        # Staged tasks wait in DRY_RUN_HOLD status; transition to active PENDING
                        conn.execute("UPDATE agent_tasks SET status = 'PENDING' WHERE campaign_id = ? AND status = 'DRY_RUN_HOLD'", (campaign_id,))
                        conn.commit()
                        
                    # Log successful override to the unified intervention ledger
                    from skills.self_improvement_core import AriaSelfImprovementCore
                    si_core = AriaSelfImprovementCore()
                    intervention_id = f"INT_COS_{int(time.time())}_AUTO_APPROVAL"
                    si_core.register_intervention(
                        intervention_id=intervention_id,
                        agent="ChiefOfStaffAgent",
                        action="CAMPAIGN_AUTO_APPROVAL",
                        reason=f"Promoted campaign {campaign_id} based on combined approval score of {approval_score:.2f} (Planner: {planner_confidence:.2f}, CoS: {cos_score:.2f}, Habits: {habit_score:.2f}).",
                        result="PENDING",
                        success_score=None,
                        campaign_id=campaign_id
                    )
                    
                    auto_approvals_today += 1
                    budget["auto_approvals"] = auto_approvals_today
                    self._save_daily_budget(budget)
                    approved_ids.append(campaign_id)
                    print(f"[ChiefOfStaff] AUTONOMOUS PROMOTION: Staged plan {campaign_id} has been activated.")
                except Exception as ex:
                    print(f"[ChiefOfStaff] Failed to auto-promote staged campaign {campaign_id}: {ex}")
        return approved_ids

    def _run_autonomous_remediations(self) -> List[str]:
        """Component P14: Detects Knowledge Graph dependency failures and deploys remediation workers under cooldown rules."""
        triggered_remediations = []
        gaps = []
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT target_node, source_node FROM knowledge_graph_edges WHERE relationship IN ('BLOCKED_BY', 'WEAK_AREA')")
                for r in cursor.fetchall():
                    gaps.append({"skill": r[0], "goal": r[1]})
        except Exception as e:
            print(f"[ChiefOfStaff] Error querying Knowledge Graph gaps: {e}")
            
        if not gaps:
            return triggered_remediations

        budget = self._get_daily_budget()
        research_triggers_today = budget.get("research_triggers", 0)

        for gap in gaps:
            skill = gap["skill"]
            if research_triggers_today >= 5:
                print(f"[ChiefOfStaff] Research trigger daily limit of 5 exceeded.")
                break

            # 12-Hour Cooldown Safeguard Check
            now = int(time.time())
            cooldown_period = 43200  # 12 hours
            recent_trigger = False
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT COUNT(*) FROM intervention_ledger 
                        WHERE action = 'REMEDIATION_AGENT_TRIGGER' 
                          AND reason LIKE ? 
                          AND timestamp >= ?
                    """, (f"%{skill}%", now - cooldown_period))
                    if cursor.fetchone()[0] > 0:
                        recent_trigger = True
            except Exception as e:
                print(f"[ChiefOfStaff] Error querying cooldown interval: {e}")

            if recent_trigger:
                print(f"[ChiefOfStaff] Remediation for weak skill '{skill}' is on active 12-hour cooldown. Skipping.")
                continue

            # Deploy Remediation Worker autonomously
            try:
                # Import orchestrator safely
                from skills.agent_orchestrator import AriaMultiAgentOrchestrator
                orch = AriaMultiAgentOrchestrator()

                # Associate task with active campaign matching goal
                campaign_id = None
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id FROM campaigns WHERE goal_text LIKE ? OR id = ? LIMIT 1", (f"%{gap['goal']}%", gap['goal']))
                    row = cursor.fetchone()
                    if row:
                        campaign_id = row[0]
                    else:
                        cursor.execute("SELECT id FROM campaigns WHERE status = 'RUNNING' LIMIT 1")
                        row = cursor.fetchone()
                        if row:
                            campaign_id = row[0]

                if campaign_id:
                    task_data = {
                        "agent_name": "researchagent",
                        "task_description": f"Research remediation for weak area: {skill}",
                        "priority": 8
                    }
                    orch.inject_task(campaign_id=campaign_id, task_data=task_data)
                    
                    # Log trigger to intervention ledger
                    from skills.self_improvement_core import AriaSelfImprovementCore
                    si_core = AriaSelfImprovementCore()
                    intervention_id = f"INT_COS_{int(time.time())}_REMEDIATION"
                    si_core.register_intervention(
                        intervention_id=intervention_id,
                        agent="ChiefOfStaffAgent",
                        action="REMEDIATION_AGENT_TRIGGER",
                        reason=f"Auto-deployed ResearchAgent remediation task for weak area: {skill}",
                        result="PENDING",
                        success_score=None,
                        campaign_id=campaign_id
                    )
                    
                    research_triggers_today += 1
                    budget["research_triggers"] = research_triggers_today
                    self._save_daily_budget(budget)
                    triggered_remediations.append(skill)
                    print(f"[ChiefOfStaff] AUTONOMOUS REMEDIATION: Research task successfully injected for skill '{skill}' on campaign {campaign_id}.")
            except Exception as ex:
                print(f"[ChiefOfStaff] Failed to trigger remediation for weak area '{skill}': {ex}")

        return triggered_remediations

    def _check_new_opportunities(self) -> List[Dict[str, Any]]:
        """Component P21: Scans, scores, and registers proactive opportunity proposals."""
        proposals = []
        try:
            from skills.opportunity_discovery import AriaOpportunityDiscoveryEngine
            from skills.agent_status import DB_PATH
            
            engine = AriaOpportunityDiscoveryEngine(DB_PATH)
            # 1. Perform nightly expired cleanup
            engine.nightly_opportunity_cleanup()
            
            # 2. Run opportunity evaluation
            proposals = engine.evaluate_and_score_opportunities(self.aria_instance)
            
            # 3. Publish proposals to the Blackboard under 'system' topic for HUD visibility
            if proposals:
                self.blackboard.publish(
                    topic="system",
                    key="opportunity_proposals",
                    value={"timestamp": int(time.time()), "proposals": proposals},
                    source="ChiefOfStaffAgent"
                )
                print(f"[ChiefOfStaff] Discovered and staged {len(proposals)} opportunity proposals.")
                
                # 4. Automate Opportunity Readiness Campaigns generation for recommended listings
                for p in proposals:
                    if p.get("recommended") == "YES" and p.get("missing_skills"):
                        self._stage_opportunity_readiness_campaign(p)
        except Exception as e:
            print(f"[ChiefOfStaff] Error checking new opportunities: {e}")
        return proposals

    def _stage_opportunity_readiness_campaign(self, opp: Dict[str, Any]):
        """Component P21: Autonomously creates and stages an Opportunity Readiness Campaign for approval."""
        opp_id = opp["opportunity_id"]
        title = opp["title"]
        missing = opp["missing_skills"]
        
        if not missing:
            return
            
        campaign_goal = f"Readiness Preparation for {title} ({opp['provider']})"
        campaign_id = f"CMP_READINESS_{opp_id.upper()}"
        
        # Check if campaign already exists to avoid duplication
        try:
            with get_db_connection() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM campaigns WHERE id = ?", (campaign_id,))
                if cursor.fetchone()[0] > 0:
                    return # Already staged or active
        except Exception:
            pass

        now = int(time.time())
        try:
            with get_db_connection() as conn:
                # Insert campaign in staged status
                conn.execute(
                    "INSERT INTO campaigns (id, goal_text, status, created_at) VALUES (?, ?, 'DRY_RUN_PENDING', ?)",
                    (campaign_id, campaign_goal, now)
                )
                
                # Insert milestones and tasks for each missing skill
                for idx, skill in enumerate(missing):
                    milestone_id = f"MS_{campaign_id}_M{idx}"
                    conn.execute("""
                        INSERT INTO campaign_milestones (id, campaign_id, title, description, status, created_at)
                        VALUES (?, ?, ?, ?, 'PENDING', ?)
                    """, (milestone_id, campaign_id, f"Learn {skill}", f"Acquire required skill: {skill}", now))
                    
                    task_id = f"TSK_{campaign_id}_T{idx}"
                    conn.execute("""
                        INSERT INTO agent_tasks 
                        (id, campaign_id, agent_name, task_description, target, priority, status, created_at, milestone_id)
                        VALUES (?, ?, 'researchagent', ?, ?, 8, 'DRY_RUN_HOLD', ?, ?)
                    """, (task_id, campaign_id, f"Research and study core concepts of {skill}", skill, now, milestone_id))
                
                # Insert final mock interviews / evaluation milestone
                final_m_id = f"MS_{campaign_id}_FINAL"
                conn.execute("""
                    INSERT INTO campaign_milestones (id, campaign_id, title, description, status, created_at)
                    VALUES (?, ?, ?, ?, 'PENDING', ?)
                """, (final_m_id, campaign_id, "Mock Interview and Review", f"Verify preparation for {title}", now))
                
                final_t_id = f"TSK_{campaign_id}_FINAL"
                conn.execute("""
                    INSERT INTO agent_tasks 
                    (id, campaign_id, agent_name, task_description, target, priority, status, created_at, milestone_id)
                    VALUES (?, ?, 'careeragent', ?, ?, 9, 'DRY_RUN_HOLD', ?, ?)
                """, (final_t_id, campaign_id, f"Conduct mock interview simulation for {title}", title, now, final_m_id))
                
                conn.commit()
            print(f"[ChiefOfStaff] Successfully staged opportunity readiness campaign: {campaign_id}")
        except Exception as e:
            print(f"[ChiefOfStaff] Error staging readiness campaign: {e}")
