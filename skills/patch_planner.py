import os
import re
import json
import time
from typing import Dict, Any
from skills.base_agent import BaseAgent
from skills.blackboard import AriaBlackboard

class AriaPatchPlanner(BaseAgent):
    def __init__(self, aria_instance=None):
        super().__init__("PatchPlannerAgent", aria_instance)

    @property
    def aria_inst(self):
        if self.aria is None:
            try:
                from skills.agent_orchestrator import AriaMultiAgentOrchestrator
                self.aria = AriaMultiAgentOrchestrator().aria
            except Exception:
                pass
        return self.aria

    def _resolve_file_path(self, file_path: str) -> str:
        if not file_path:
            return ""
        if os.path.exists(file_path):
            return os.path.abspath(file_path)
        repo_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        p = os.path.join(repo_path, file_path)
        if os.path.exists(p):
            return os.path.abspath(p)
        basename = os.path.basename(file_path)
        for root, dirs, files in os.walk(repo_path):
            if "__pycache__" in root or ".git" in root or ".gemini" in root:
                continue
            if basename in files:
                return os.path.abspath(os.path.join(root, basename))
        return file_path

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        self.log_state_shift("RUNNING", "Fetching root cause diagnosis from blackboard...")
        
        bb = getattr(self.aria_inst, "blackboard", None)
        if bb is None or type(bb).__name__ in ('MagicMock', 'Mock'):
            bb = AriaBlackboard()
            
        # 1. Fetch root cause report
        rc_key = f"rootcause_{task_id}"
        root_cause = bb.read(topic="system", key=rc_key)
        if not root_cause:
            root_cause = payload.get("root_cause_details")
            
        if not root_cause:
            self.log_state_shift("IDLE", f"Missing root cause data for key {rc_key}")
            return json.dumps({"error": "Missing root cause analysis details."})

        failed_file = self._resolve_file_path(root_cause["failed_file"])
        failed_line = root_cause["failed_line"]
        error_msg = root_cause["error_message"]
        cause_desc = root_cause["root_cause"]
        fix_cat = root_cause["fix_category"]
        strategy = root_cause["recommended_strategy"]
        failed_func = root_cause["failed_function"]

        # 2. Ingest source code context
        if not os.path.exists(failed_file):
            self.log_state_shift("IDLE", f"Failed file not found: {failed_file}")
            return json.dumps({"error": f"Failing file does not exist: {failed_file}"})

        try:
            with open(failed_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            start = max(1, failed_line - 15)
            end = min(len(lines), failed_line + 15)
            code_context = "".join(lines[start-1:end])
        except Exception as e:
            self.log_state_shift("IDLE", f"Failed to read file context: {e}")
            return json.dumps({"error": f"Failed to read file context: {e}"})

        # 3. Query LLM to formulate structural repair plan
        prompt = f"""
        You are the Patch Planner Agent for ARIA.
        Design a structural repair plan for this python code failure:
        
        Exception: {error_msg}
        Root Cause: {cause_desc}
        Category: {fix_cat}
        Strategy: {strategy}
        Failing Line: {failed_line}
        Failing Function: {failed_func}
        
        == CODE CONTEXT (Lines {start}-{end}) ==
        {code_context}
        
        Formulate a plan outlining how to resolve this failure. You MUST select an edit_type from: "REPLACE", "INSERT", or "DELETE".
        Provide the response as exactly a raw JSON object (no markdown block formatting).
        Schema:
        {{
            "edit_type": "REPLACE | INSERT | DELETE",
            "target_function": "{failed_func}",
            "target_location": "Detailed description of line numbers or logical anchors where the fix should go",
            "estimated_scope": "LINE | FUNCTION | CLASS | MODULE",
            "goal": "Clear structural description of what the patch will accomplish"
        }}
        """
        
        try:
            raw_res = self.aria_inst.brain.think(prompt).strip()
            match = re.search(r"(\{.*\})", raw_res, re.DOTALL)
            clean = match.group(1).strip() if match else raw_res.strip()
            data = json.loads(clean)
            
            edit_type = data.get("edit_type", "REPLACE").upper().strip()
            if edit_type not in ("REPLACE", "INSERT", "DELETE"):
                edit_type = "REPLACE"
                
            scope = (data.get("estimated_scope") or data.get("estimatedscope") or "LINE").upper().strip()
            if scope not in ("LINE", "FUNCTION", "CLASS", "MODULE"):
                scope = "LINE"
                
            plan = {
                "plan_id": f"patchplan_{task_id}",
                "parent_rootcause": f"rootcause_{task_id}",
                "parent_failure": f"failure_{task_id}",
                "failed_file": failed_file,
                "failed_line": failed_line,
                "edit_type": edit_type,
                "estimated_scope": scope,
                "target_function": data.get("target_function", failed_func),
                "target_location": data.get("target_location", f"Line {failed_line}"),
                "goal": data.get("goal", "Resolve logic exception."),
                "timestamp": int(time.time()),
                "campaign_id": root_cause.get("campaign_id", "unknown")
            }
            
            # 4. Publish to Blackboard topic 'system'
            plan_key = f"patchplan_{task_id}"
            bb.publish(
                topic="system",
                key=plan_key,
                value=plan,
                source=self.agent_name,
                ttl_hours=24
            )
            
            self.log_state_shift("IDLE", f"Patch plan created under key {plan_key}")
            return json.dumps(plan)
            
        except Exception as e:
            self.log_state_shift("IDLE", f"Failed to generate patch plan: {e}")
            return json.dumps({"error": f"Failed to generate patch plan: {e}"})
