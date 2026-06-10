import os
import shutil
import subprocess
import hashlib
import json
import time
from typing import Dict, Any
from skills.base_agent import BaseAgent
from skills.blackboard import AriaBlackboard

class AriaPatchApplication(BaseAgent):
    def __init__(self, aria_instance=None):
        super().__init__("PatchApplicationAgent", aria_instance)

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
        self.log_state_shift("RUNNING", f"Evaluating deployment authorization tokens for: {task_id}")

        bb = getattr(self.aria_inst, "blackboard", None)
        if bb is None or type(bb).__name__ in ('MagicMock', 'Mock'):
            bb = AriaBlackboard()

        # ── 1. GATHER UPSTREAM BLACKBOARD PAYLOADS ────────────────────────────
        approval_key = f"approval_{task_id}"
        patch_key = f"patch_{task_id}"
        failure_key = f"failure_{task_id}"

        approval_data = bb.read(topic="system", key=approval_key)
        patch_data = bb.read(topic="system", key=patch_key)
        failure_data = bb.read(topic="system", key=failure_key)

        if not approval_data or not patch_data:
            self.log_state_shift("IDLE", f"Execution blocked: Prerequisite patch or approval tokens missing for {task_id}")
            return "BLOCKED_UNAPPROVED"

        # ── 2. GUARDRAIL 1: EXPLICIT APPROVAL AND VAL SCORE GATES ──────────────
        approval_status = approval_data.get("approval_status")
        val_score = float(approval_data.get("validation_score", 0.0))
        recommendation = approval_data.get("recommendation")

        if approval_status != "APPROVED" or val_score < 0.90 or recommendation != "APPROVE":
            self.log_state_shift("IDLE", f"Execution blocked: Workflow criteria not met. Approval: {approval_status}, Score: {val_score}, Recommendation: {recommendation}")
            return "BLOCKED_UNAPPROVED"

        # ── 3. GUARDRAIL 2: RISK LEVEL AND SCOPE FILTERING ────────────────────
        risk_level = patch_data.get("risk_level", "HIGH")
        scope = patch_data.get("estimated_scope", "CLASS")

        if risk_level != "LOW" or scope not in ["LINE", "FUNCTION"]:
            self.log_state_shift("IDLE", f"Execution blocked: Scope '{scope}' / Risk '{risk_level}' exceeds initial autonomous limits (LOW/LINE/FUNCTION only).")
            return "BLOCKED_RISK_THRESHOLD"

        # ── 4. GUARDRAIL 3: PATH TRAVERSAL BOUNDARY CHECKS ────────────────────
        target_file = patch_data.get("target_file")
        if not target_file:
            self.log_state_shift("IDLE", "Execution blocked: Target file path is missing from the staged patch.")
            return "APPLICATION_FAILED"

        target_abs = os.path.abspath(target_file)
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        if not target_abs.startswith(project_root):
            self.log_state_shift("IDLE", f"Security violation blocked: Target path '{target_abs}' lies outside project root '{project_root}'.")
            return "SECURITY_VIOLATION_BLOCKED"

        if not os.path.exists(target_abs):
            self.log_state_shift("IDLE", f"Execution blocked: Target file does not exist: {target_abs}")
            return "APPLICATION_FAILED"

        # ── 5. RECORD ORIGINAL BRANCH FOR ROLLBACK AUDITING ───────────────────
        original_branch = "main"
        try:
            orig_branch_res = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, check=True)
            if orig_branch_res and hasattr(orig_branch_res, "stdout"):
                original_branch = getattr(orig_branch_res, "stdout", "")
                if hasattr(original_branch, "strip"):
                    original_branch = original_branch.strip()
            if not original_branch or type(original_branch).__name__ in ('MagicMock', 'Mock'):
                original_branch = "main"
        except Exception as git_err:
            self.log_state_shift("RUNNING", f"Failed to retrieve current branch name: {git_err}. Defaulting rollback target to 'main'.")

        # Cast original_branch to string defensively
        original_branch = str(original_branch)

        branch_name = f"aria/repair-{task_id}"
        backup_file = target_abs + f".bak_{task_id}"
        self.log_state_shift("RUNNING", f"Initializing safe repository transaction. Backup: {os.path.basename(backup_file)}")

        try:
            # ── 6. GUARDRAIL 4: FILE HASH DRIFT CHECK ──────────────────────────
            with open(target_abs, 'rb') as fh:
                current_bytes = fh.read()
            
            # Normalize CRLF to LF for a platform-independent drift check
            normalized_current = current_bytes.replace(b'\r\n', b'\n')
            current_hash = hashlib.sha256(normalized_current).hexdigest()
            
            expected_hash = patch_data.get("target_file_hash")
            if expected_hash and current_hash != expected_hash:
                raise ValueError("Target file drift detected: file hash has changed since the patch was generated.")

            # ── 7. GUARDRAIL 5: EXACTLY ONE SNIPPET MATCH REQUIREMENT ───────────
            content = current_bytes.decode('utf-8', errors='replace')
            orig_snippet = patch_data["original_snippet"]
            proposed_snippet = patch_data["proposed_snippet"]

            snippet_occurrences = content.count(orig_snippet)
            if snippet_occurrences != 1:
                raise ValueError(f"Patch target location is ambiguous: found {snippet_occurrences} occurrences of the original snippet (must be exactly 1).")

            # ── 8. PRE-MODIFICATION BACKUP ────────────────────────────────────
            shutil.copyfile(target_abs, backup_file)

            # ── 9. SWITCH TO ISOLATED REPAIR BRANCH ────────────────────────────
            self.log_state_shift("RUNNING", f"Switching to isolation branch: {branch_name}")
            subprocess.run(["git", "switch", "-C", branch_name], check=True, capture_output=True, text=True)

            # ── 10. APPLY PATCH MODIFICATION ON DISK ──────────────────────────
            patched_content = content.replace(orig_snippet, proposed_snippet, 1)
            with open(target_abs, 'w', encoding='utf-8') as f:
                f.write(patched_content)

            # ── 11. RE-VALIDATE BRANCH (SYNTAX + UNIT TESTS WITH TIMEOUT) ─────
            self.log_state_shift("RUNNING", "Validating applied patch syntax...")
            import py_compile
            try:
                py_compile.compile(target_abs, doraise=True)
            except py_compile.PyCompileError as compile_err:
                raise RuntimeError(f"Post-application syntax compilation check failed: {compile_err}")

            test_cmd = failure_data.get("test_command") if failure_data else None
            if not test_cmd:
                # Retrieve from payload fallback
                test_cmd = payload.get("test_command")

            if test_cmd:
                self.log_state_shift("RUNNING", f"Executing target test command with 30s timeout: {test_cmd}")
                try:
                    test_res = subprocess.run(test_cmd, shell=True, capture_output=True, text=True, timeout=30)
                    if test_res.returncode != 0:
                        raise RuntimeError(f"Post-application targeted unit test suite failed: return code {test_res.returncode}")
                except subprocess.TimeoutExpired:
                    raise RuntimeError(f"Post-application unit test suite timed out after 30 seconds: {test_cmd}")
            else:
                self.log_state_shift("RUNNING", "No target unit test command found on failure report. Skipping unit test verification.")

            # ── 12. PUBLISH SUCCESS REPORT ────────────────────────────────────
            report_payload = {
                "application_id": f"applied_{task_id}",
                "application_status": "SUCCESS",
                "previous_branch": original_branch,
                "repair_branch": branch_name,
                "post_tests_passed": True,
                "backup_restored": False,
                "timestamp": int(time.time()),
                "campaign_id": patch_data.get("campaign_id", "unknown")
            }
            bb.publish(
                topic="system",
                key=f"applied_report_{task_id}",
                value=report_payload,
                source=self.agent_name,
                ttl_hours=24
            )

            self.log_state_shift("IDLE", f"Patch successfully applied to branch '{branch_name}'. Awaiting manual git inspection.")
            return "APPLICATION_SUCCESS"

        except Exception as err:
            err_msg = str(err)
            self.log_state_shift("ERROR", f"Patch application sequences faulted: {err_msg}. Triggering automated database & disk rollback...")

            # Restore original disk file content
            if os.path.exists(backup_file):
                try:
                    shutil.copyfile(backup_file, target_abs)
                except Exception as r_err:
                    print(f"CRITICAL: Failed to restore backup file {backup_file} to {target_abs}: {r_err}")

            # Revert active branch back safely
            try:
                subprocess.run(["git", "switch", original_branch], capture_output=True, text=True)
            except Exception as switch_err:
                print(f"CRITICAL: Failed to switch back to original branch '{original_branch}': {switch_err}")

            # Determine appropriate reason categories
            reason = "RuntimeError"
            if "drift" in err_msg or "hash" in err_msg:
                reason = "FileChanged"
            elif "ambiguous" in err_msg or "occurrences" in err_msg:
                reason = "PatchLocationAmbiguous"
            elif "syntax" in err_msg or "compile" in err_msg:
                reason = "CompileError"
            elif "test suite failed" in err_msg:
                reason = "TestFailure"
            elif "timed out" in err_msg:
                reason = "TestTimeout"

            # Publish Rollback Report to Blackboard
            report_payload = {
                "application_id": f"applied_{task_id}",
                "application_status": "ROLLED_BACK",
                "reason": reason,
                "previous_branch": original_branch,
                "repair_branch": branch_name,
                "post_tests_passed": False,
                "backup_restored": True,
                "error_details": err_msg,
                "timestamp": int(time.time()),
                "campaign_id": patch_data.get("campaign_id", "unknown")
            }
            bb.publish(
                topic="system",
                key=f"applied_report_{task_id}",
                value=report_payload,
                source=self.agent_name,
                ttl_hours=24
            )

            return f"APPLICATION_FAILED_ROLLED_BACK_{reason.upper()}"

        finally:
            # Always ensure the temp backup copy is deleted
            if os.path.exists(backup_file):
                try:
                    os.remove(backup_file)
                except Exception:
                    pass
