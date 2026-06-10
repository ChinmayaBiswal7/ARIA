import os
import re
import json
import time
import difflib
from typing import Dict, Any, List
from skills.base_agent import BaseAgent
from skills.blackboard import AriaBlackboard

VALID_TAXONOMY = {
    "MISSING_INITIALIZATION", "NULL_REFERENCE", "IMPORT_FAILURE",
    "API_CONTRACT_MISMATCH", "TYPE_MISMATCH", "LOGIC_ERROR",
    "CONFIGURATION_ERROR", "DATABASE_ERROR"
}

class AriaRootCauseAnalyzer(BaseAgent):
    def __init__(self, aria_instance=None):
        super().__init__("RootCauseAnalyzerAgent", aria_instance)

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
            
        # Try resolving relative to project root
        repo_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        p = os.path.join(repo_path, file_path)
        if os.path.exists(p):
            return os.path.abspath(p)
            
        # Try finding by basename in the project
        basename = os.path.basename(file_path)
        for root, dirs, files in os.walk(repo_path):
            if "__pycache__" in root or ".git" in root or ".gemini" in root:
                continue
            if basename in files:
                return os.path.abspath(os.path.join(root, basename))
                
        return file_path

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        self.log_state_shift("RUNNING", "Reading failure report from blackboard...")
        
        bb = getattr(self.aria_inst, "blackboard", None)
        if bb is None or type(bb).__name__ in ('MagicMock', 'Mock'):
            bb = AriaBlackboard()
            
        # 1. Fetch failure details from blackboard system topic
        failure_key = f"failure_{task_id}"
        failure = bb.read(topic="system", key=failure_key)
        if not failure:
            failure = payload.get("failure_details")
            
        if not failure:
            self.log_state_shift("IDLE", f"No failure details found for key: {failure_key}")
            return json.dumps({"error": "No failure analysis details available."})

        raw_file = failure["failed_file"]
        failed_file = self._resolve_file_path(raw_file)
        failed_line = failure["failed_line"]
        failed_func = failure["failed_function"]
        error_type = failure["error_type"]
        error_msg = failure["error_message"]
        raw_tb = failure["raw_traceback"]

        # 2. Deterministic Static Pre-Analysis
        evidence, pre_findings = self._run_static_checks(failed_file, failed_line, error_msg)

        # 3. Read surrounding source context
        source_context = self._get_source_context(failed_file, failed_line)

        # 4. Query LLM for Root Cause Reasoning
        prompt = f"""
        You are the Root Cause Analysis Agent for ARIA.
        Analyze the following python code failure:
        
        File: {failed_file}
        Line: {failed_line}
        Function: {failed_func}
        Exception: {error_msg}
        
        == STATIC CHECKS FINDINGS ==
        {json.dumps(pre_findings)}
        
        == SOURCE CODE CONTEXT ==
        {source_context}
        
        Select a root cause category from this exact list:
        {list(VALID_TAXONOMY)}
        
        Provide the response as exactly a raw JSON object (no markdown block formatting).
        Schema:
        {{
            "root_cause": "Short human description of the root cause issue",
            "confidence": 0.85,
            "fix_category": "SELECTED_CATEGORY",
            "recommended_strategy": "Concrete strategy to repair this category",
            "llm_evidence": [
                "Citations from source code illustrating why this issue occurs"
            ]
        }}
        """
        
        try:
            raw_res = self.aria_inst.brain.think(prompt).strip()
            # Clean JSON formatting
            match = re.search(r"(\{.*\})", raw_res, re.DOTALL)
            clean = match.group(1).strip() if match else raw_res.strip()
            data = json.loads(clean)
            
            # Reconstruct and Normalize Taxonomy & Evidence
            fix_cat = data.get("fix_category", "").upper().strip().replace(" ", "_")
            if fix_cat not in VALID_TAXONOMY:
                fix_cat = "LOGIC_ERROR"
                
            # Merge static evidence with LLM evidence
            total_evidence = evidence + data.get("llm_evidence", [])
            confidence = float(data.get("confidence", 0.75))
            if pre_findings.get("static_typo_detected"):
                confidence = max(confidence, 0.95)
                
            diagnosis = {
                "failed_file": failed_file,
                "failed_line": failed_line,
                "failed_function": failed_func,
                "error_type": error_type,
                "error_message": error_msg,
                "root_cause": data.get("root_cause", "Unspecified logic error."),
                "confidence": round(confidence, 2),
                "fix_category": fix_cat,
                "recommended_strategy": data.get("recommended_strategy", "Review logic flow."),
                "evidence": total_evidence,
                "timestamp": int(time.time()),
                "campaign_id": failure.get("campaign_id", "unknown")
            }
            
            # 5. Publish to Blackboard topic 'system'
            rc_key = f"rootcause_{task_id}"
            bb.publish(
                topic="system",
                key=rc_key,
                value=diagnosis,
                source=self.agent_name,
                ttl_hours=24
            )
            
            self.log_state_shift("IDLE", f"Root cause filed under key {rc_key} (Category: {fix_cat})")
            return json.dumps(diagnosis)
            
        except Exception as e:
            fallback = {
                "failed_file": failed_file,
                "failed_line": failed_line,
                "failed_function": failed_func,
                "error_type": error_type,
                "error_message": error_msg,
                "root_cause": f"Logic error in test suite execution. Analyzer failed: {e}",
                "confidence": 0.50,
                "fix_category": "LOGIC_ERROR",
                "recommended_strategy": "Examine raw traceback logs.",
                "evidence": evidence + [f"Analyzer failed with error: {e}"],
                "timestamp": int(time.time()),
                "campaign_id": failure.get("campaign_id", "unknown")
            }
            rc_key = f"rootcause_{task_id}"
            bb.publish(topic="system", key=rc_key, value=fallback, source=self.agent_name, ttl_hours=24)
            self.log_state_shift("IDLE", f"Fallback diagnosis filed under key {rc_key}")
            return json.dumps(fallback)

    def _run_static_checks(self, file_path: str, failed_line: int, error_msg: str) -> tuple:
        evidence = []
        findings = {"static_typo_detected": False}
        
        if not os.path.exists(file_path):
            return evidence, findings
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            if failed_line <= len(lines):
                bad_line = lines[failed_line - 1].strip()
                
                # Check for NameError / AttributeError typos
                # Extract words/identifiers on the failing line
                identifiers = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', bad_line)
                
                # Scan entire file for candidates to detect typos
                all_words = set()
                for line in lines:
                    for w in re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', line):
                        all_words.add(w)
                        
                for ident in identifiers:
                    if ident in ("self", "import", "def", "return", "class", "if", "for", "in", "None", "True", "False", "print", "range", "list", "dict", "str", "int", "float"):
                        continue
                    # Find similar words in the file (spelling similarities)
                    similars = difflib.get_close_matches(ident, all_words, n=2, cutoff=0.85)
                    # Filter out exact matches
                    similars = [s for s in similars if s != ident]
                    if similars:
                        findings["static_typo_detected"] = True
                        findings["suggested_ident_corrections"] = similars
                        evidence.append(f"Static Typo Match: Variable '{ident}' on line {failed_line} is close to {similars} elsewhere in the file.")
                        
                # Check constructor attributes initialization
                constructor_attrs = set()
                in_init = False
                for line in lines:
                    if "def __init__" in line:
                        in_init = True
                        continue
                    elif in_init and "def " in line:
                        in_init = False
                    if in_init:
                        m = re.findall(r'self\.([a-zA-Z0-9_]+)', line)
                        for attr in m:
                            constructor_attrs.add(attr)
                            
                # Check if attribute referenced on bad_line is missing from constructor
                missing_attrs = []
                for attr in re.findall(r'self\.([a-zA-Z0-9_]+)', bad_line):
                    if attr not in constructor_attrs:
                        missing_attrs.append(attr)
                if missing_attrs:
                    findings["missing_constructor_init"] = missing_attrs
                    evidence.append(f"Missing Initialization: self.{', self.'.join(missing_attrs)} is referenced on line {failed_line} but is never defined in constructor __init__.")
                    
        except Exception as e:
            findings["checks_error"] = str(e)
            
        return evidence, findings

    def _get_source_context(self, file_path: str, failed_line: int, margin: int = 10) -> str:
        if not os.path.exists(file_path):
            return "[Context Error] Source file not found."
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            start = max(1, failed_line - margin)
            end = min(len(lines), failed_line + margin)
            
            context = []
            for i in range(start, end + 1):
                prefix = "=> " if i == failed_line else "   "
                context.append(f"{prefix}{i:03d}: {lines[i-1].rstrip()}")
            return "\n".join(context)
        except Exception as e:
            return f"[Context Error] Failed to read source: {e}"
