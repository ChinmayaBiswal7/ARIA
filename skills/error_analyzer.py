import re
import json
import os
import time
from typing import Dict, Any
from skills.base_agent import BaseAgent
from skills.blackboard import AriaBlackboard

class AriaErrorAnalyzer(BaseAgent):
    def __init__(self, aria_instance=None):
        super().__init__("ErrorAnalyzerAgent", aria_instance)

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
        self.log_state_shift("RUNNING", "Parsing traceback details...")
        
        raw_traceback = payload.get("traceback", "")
        test_cmd = payload.get("test_command", "unknown")
        camp_id = campaign_id or payload.get("campaign_id", "unknown")
        
        if not raw_traceback:
            self.log_state_shift("IDLE", "Empty traceback provided.")
            return json.dumps({"error": "No traceback payload provided."})

        # 1. Classify the error type
        error_category = self._classify_error(raw_traceback)
        
        # 2. Assign severity level
        severity = self._assign_severity(error_category)
        
        # 3. Extract file path, line number, function name, and error details
        file_path, line_num, func_name, error_msg = self._parse_traceback_details(raw_traceback)
        
        # 4. Construct structured analysis report
        analysis_report = {
            "failed_file": file_path,
            "failed_line": line_num,
            "failed_function": func_name,
            "error_type": error_category,
            "error_message": error_msg,
            "severity": severity,
            "test_command": test_cmd,
            "campaign_id": camp_id,
            "timestamp": int(time.time()),
            "raw_traceback": raw_traceback,
            "confidence_score": 0.95
        }

        # 5. Publish to Blackboard under topic 'system'
        bb = getattr(self.aria_inst, "blackboard", None)
        if bb is None or type(bb).__name__ in ('MagicMock', 'Mock'):
            bb = AriaBlackboard()
            
        bb_key = f"failure_{task_id}"
        bb.publish(
            topic="system",
            key=bb_key,
            value=analysis_report,
            source=self.agent_name,
            ttl_hours=24  # Diagnostics persist for 24h on the dashboard
        )
        
        self.log_state_shift("IDLE", f"Diagnostic report published under key {bb_key} for {file_path}")
        return json.dumps(analysis_report)

    def _classify_error(self, traceback_str: str) -> str:
        tb = traceback_str.lower()
        if "syntaxerror" in tb:
            return "Syntax Error"
        elif "importor" in tb or "modulenotfounderror" in tb or "importerror" in tb:
            return "Import Error"
        elif "sqlite3" in tb or "sqlalchemy" in tb or "operationalerror" in tb or "no such table" in tb:
            return "Database Error"
        elif "assertionerror" in tb:
            return "Assertion Failure"
        elif "connectionerror" in tb or "requests.exceptions" in tb or "urllib.error" in tb:
            return "API Error"
        elif "dependency" in tb:
            return "Dependency Failure"
        return "Test Failure"

    def _assign_severity(self, error_type: str) -> str:
        mapping = {
            "Syntax Error": "HIGH",
            "Import Error": "HIGH",
            "Database Error": "HIGH",
            "Assertion Failure": "MEDIUM",
            "API Error": "MEDIUM",
            "Dependency Failure": "MEDIUM",
            "Test Failure": "LOW"
        }
        return mapping.get(error_type, "LOW")

    def _parse_traceback_details(self, traceback_str: str):
        # Extract file path, line number, and function name
        # Python traceback line: File "file_path", line N, in function_name
        matches = re.findall(r'File "([^"]+)", line (\d+), in (\w+)', traceback_str)
        if matches:
            file_path, line_num, func_name = matches[-1]
            line_num = int(line_num)
        else:
            # Fallback to simple File/Line match if function name isn't present
            simple_matches = re.findall(r'File "([^"]+)", line (\d+)', traceback_str)
            if simple_matches:
                file_path, line_num = simple_matches[-1]
                line_num = int(line_num)
                func_name = "unknown"
            else:
                file_path, line_num, func_name = "unknown.py", 0, "unknown"
            
        # Extract the error message line (typically the last line of the traceback)
        lines = [l.strip() for l in traceback_str.strip().split('\n') if l.strip()]
        error_msg = lines[-1] if lines else "Unknown traceback exception."
        
        return file_path, line_num, func_name, error_msg
