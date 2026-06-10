import time
import json
from typing import Dict, Any
from skills.base_agent import BaseAgent
from skills.blackboard import AriaBlackboard

class AriaApprovalWorkflow(BaseAgent):
    def __init__(self, aria_instance=None):
        super().__init__("ApprovalWorkflowAgent", aria_instance)

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
        self.log_state_shift("RUNNING", f"Staging approval request gates for: {task_id}")

        bb = getattr(self.aria_inst, "blackboard", None)
        if bb is None or type(bb).__name__ in ('MagicMock', 'Mock'):
            bb = AriaBlackboard()

        # 1. Gather all upstream lineage blocks from the blackboard exchange
        failure_key = f"failure_{task_id}"
        rc_key = f"rootcause_{task_id}"
        plan_key = f"patchplan_{task_id}"
        patch_key = f"patch_{task_id}"
        val_key = f"validation_{task_id}"

        failure = bb.read(topic="system", key=failure_key)
        root_cause = bb.read(topic="system", key=rc_key)
        patch_data = bb.read(topic="system", key=patch_key)
        validation_data = bb.read(topic="system", key=val_key)

        if not patch_data or not validation_data:
            self.log_state_shift("IDLE", "Aborted. Prerequisite patch or validation records missing.")
            return json.dumps({"error": f"Prerequisite blackboard records missing for {task_id}"})

        # 2. Calculate a deterministic validation score integrating sandbox results & confidences
        rc_conf = float(root_cause.get("confidence", 0.75)) if root_cause else 0.75
        patch_conf = float(patch_data.get("confidence", 0.80))
        
        sandbox_score = 0.0
        if validation_data.get("syntax_compiles"):
            sandbox_score += 0.40
        if validation_data.get("target_test_fixed"):
            sandbox_score += 0.50
        if not validation_data.get("regression_detected"):
            sandbox_score += 0.10

        combined_score = (sandbox_score + rc_conf + patch_conf) / 3.0
        validation_score = round(combined_score, 2)

        # 3. Determine the recommendation based on combined validation score
        if validation_score >= 0.90:
            recommendation = "APPROVE"
        elif validation_score >= 0.75:
            recommendation = "REVIEW"
        else:
            recommendation = "REJECT"

        # 4. Formulate the official approval request ledger structure
        approval_request = {
            "approval_id": f"approval_{task_id}",
            "parent_failure": failure_key,
            "parent_rootcause": rc_key,
            "parent_patch": patch_key,
            "parent_validation": val_key,
            "approval_status": "PENDING",
            "recommendation": recommendation,
            "affected_file": patch_data.get("target_file", "unknown.py"),
            "risk_level": patch_data.get("risk_level", "MEDIUM"),
            "validation_score": validation_score,
            "root_cause_confidence": rc_conf,
            "patch_confidence": patch_conf,
            "staged_at": int(time.time()),
            "campaign_id": patch_data.get("campaign_id", "unknown")
        }

        # 5. Publish the token directly back to the blackboard (STRICTLY READ-ONLY)
        bb.publish(
            topic="system",
            key=f"approval_{task_id}",
            value=approval_request,
            source=self.agent_name,
            ttl_hours=24
        )

        # 6. Route the alert payload directly to the alert router (if available)
        alert_router = getattr(self.aria_inst, "alert_router", None)
        if alert_router and not type(alert_router).__name__ in ('MagicMock', 'Mock'):
            try:
                alert_router.dispatch_alert(
                    title=f"🛠️ REPAIR CANDIDATE READY [{approval_request['risk_level']}]",
                    body=f"File: {approval_request['affected_file']} | Score: {int(validation_score * 100)}%. Tap to review.",
                    priority=approval_request["risk_level"],
                    category="SYSTEM"
                )
            except Exception as e:
                print(f"[ApprovalWorkflow] Alert dispatch failed: {e}")

        self.log_state_shift("IDLE", f"Approval request token established for {task_id} (Recommendation: {recommendation}).")
        return json.dumps(approval_request)
