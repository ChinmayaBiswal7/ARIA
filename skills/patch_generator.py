import os
import re
import json
import time
from typing import Dict, Any, List
from skills.base_agent import BaseAgent
from skills.blackboard import AriaBlackboard

class AriaPatchGenerator(BaseAgent):
    def __init__(self, aria_instance=None):
        super().__init__("PatchGeneratorAgent", aria_instance)

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
        self.log_state_shift("RUNNING", "Fetching diagnosis and patch plan from blackboard...")
        
        bb = getattr(self.aria_inst, "blackboard", None)
        if bb is None or type(bb).__name__ in ('MagicMock', 'Mock'):
            bb = AriaBlackboard()
            
        # 1. Fetch failure, rootcause, and patchplan reports
        failure = bb.read(topic="system", key=f"failure_{task_id}")
        root_cause = bb.read(topic="system", key=f"rootcause_{task_id}")
        patch_plan = bb.read(topic="system", key=f"patchplan_{task_id}")
        
        if not failure or not root_cause or not patch_plan:
            self.log_state_shift("IDLE", "Missing diagnostics, root cause, or patch plan.")
            return json.dumps({"error": "Missing dependency blackboard data (failure, rootcause, or patchplan)."})

        failed_file = root_cause["failed_file"]
        failed_line = root_cause["failed_line"]
        error_msg = root_cause["error_message"]
        cause_desc = root_cause["root_cause"]
        fix_cat = root_cause["fix_category"]
        
        edit_type = patch_plan["edit_type"]
        target_func = patch_plan["target_function"]
        target_loc = patch_plan["target_location"]
        plan_goal = patch_plan["goal"]

        # 2. Read source code context
        if not os.path.exists(failed_file):
            self.log_state_shift("IDLE", f"Failed file not found: {failed_file}")
            return json.dumps({"error": f"Failing file does not exist: {failed_file}"})

        try:
            import hashlib
            with open(failed_file, 'rb') as fh:
                file_bytes = fh.read()
            
            # Normalize CRLF to LF for a platform-independent hash
            normalized_bytes = file_bytes.replace(b'\r\n', b'\n')
            file_hash = hashlib.sha256(normalized_bytes).hexdigest()
            
            # Decode using utf-8 with replacement for parsing text lines
            content_str = file_bytes.decode('utf-8', errors='replace')
            lines = content_str.splitlines(keepends=True)
            
            start = max(1, failed_line - 15)
            end = min(len(lines), failed_line + 15)
            code_context = "".join(lines[start-1:end])
        except Exception as e:
            self.log_state_shift("IDLE", f"Failed to read file context: {e}")
            return json.dumps({"error": f"Failed to read file context: {e}"})

        # 3. Query LLM to write the code replacement
        prompt = f"""
        You are the Patch Generator Agent for ARIA.
        Write a precise code patch to execute the structural repair plan:
        
        Exception: {error_msg}
        Root Cause: {cause_desc}
        Category: {fix_cat}
        
        == STRUCTURAL FIX PLAN ==
        Edit Type: {edit_type}
        Target Function: {target_func}
        Target Location: {target_loc}
        Goal: {plan_goal}
        
        == CODE CONTEXT (Lines {start}-{end}) ==
        {code_context}
        
        Provide the response as exactly a raw JSON object (no markdown block formatting).
        Schema:
        {{
            "original_snippet": "The precise lines of code to modify, matching existing spacing/indentation exactly",
            "proposed_snippet": "The new replacement lines of code implementing the fix",
            "affected_lines": [
                {failed_line}
            ],
            "llm_confidence": 0.80,
            "rationale": "Short description of the patch rationale"
        }}
        """
        
        try:
            raw_res = self.aria_inst.brain.think(prompt).strip()
            match = re.search(r"(\{.*\})", raw_res, re.DOTALL)
            clean = match.group(1).strip() if match else raw_res.strip()
            data = json.loads(clean)
            
            # Reconstruct and Normalize JSON keys (to handle brain._clean() underscore strips)
            orig = data.get("original_snippet") or data.get("originalsnippet") or ""
            prop = data.get("proposed_snippet") or data.get("proposedsnippet") or ""
            affected_lines = data.get("affected_lines") or data.get("affectedlines") or [failed_line]
            llm_conf = float(data.get("llm_confidence") or data.get("llmconfidence") or 0.80)
            rationale = data.get("rationale", "")
            
            # 4. Calculate Confidence Source breakdown
            rc_conf = float(root_cause.get("confidence", 0.75))
            # Determine static check confidence: 0.90 if we successfully detected typos/missing constructor fields
            has_static_evidence = any("Static" in ev or "Missing" in ev for ev in root_cause.get("evidence", []))
            static_conf = 0.90 if has_static_evidence else 0.60
            
            combined_conf = (rc_conf + static_conf + llm_conf) / 3.0
            
            # 5. Evaluate Risk Level deterministically based on estimated_scope
            scope = (patch_plan.get("estimated_scope") or "LINE").upper().strip()
            scope_risk_matrix = {"LINE": "LOW", "FUNCTION": "MEDIUM", "CLASS": "HIGH", "MODULE": "CRITICAL"}
            risk_level = scope_risk_matrix.get(scope, "HIGH")
                
            patch_proposal = {
                "patch_id": f"patch_{task_id}",
                "parent_rootcause": f"rootcause_{task_id}",
                "parent_failure": f"failure_{task_id}",
                "target_file": failed_file,
                "target_file_hash": file_hash,
                "patch_type": edit_type,
                "estimated_scope": scope,
                "original_snippet": orig,
                "proposed_snippet": prop,
                "affected_lines": affected_lines,
                "confidence": round(combined_conf, 2),
                "confidence_source": {
                    "root_cause": round(rc_conf, 2),
                    "static_checks": round(static_conf, 2),
                    "llm_patch": round(llm_conf, 2)
                },
                "risk_level": risk_level,
                "rationale": rationale,
                "timestamp": int(time.time()),
                "campaign_id": failure.get("campaign_id", "unknown")
            }
            
            # 6. Publish to Blackboard topic 'system'
            patch_key = f"patch_{task_id}"
            bb.publish(
                topic="system",
                key=patch_key,
                value=patch_proposal,
                source=self.agent_name,
                ttl_hours=24
            )
            
            self.log_state_shift("IDLE", f"Patch proposal staged under key {patch_key} (Risk: {risk_level})")
            return json.dumps(patch_proposal)
            
        except Exception as e:
            self.log_state_shift("IDLE", f"Failed to generate patch: {e}")
            return json.dumps({"error": f"Failed to generate patch candidate: {e}"})
