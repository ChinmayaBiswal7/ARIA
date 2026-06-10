import subprocess
import json
from typing import Dict, Any
from skills.base_agent import BaseAgent

class AriaTestRunner(BaseAgent):
    def __init__(self, aria_instance=None):
        super().__init__("TestRunnerAgent", aria_instance)

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        self.log_state_shift("RUNNING", f"Executing test command: {task_description}")
        test_cmd = payload.get("test_command", "python -m unittest")
        cwd = payload.get("cwd", ".")
        
        # Execute test runner subprocess
        result = subprocess.run(test_cmd, shell=True, capture_output=True, text=True, cwd=cwd)
        
        if result.returncode == 0:
            self.log_state_shift("IDLE", "Test suite completed successfully.")
            return json.dumps({"status": "SUCCESS", "output": result.stdout})
            
        # Test failed! Capture output and execute read-only error analyzer
        self.log_state_shift("RUNNING", "Test failure detected. Triggering Error Analyzer...")
        
        traceback_output = ""
        if result.stderr.strip():
            traceback_output += result.stderr.strip()
        if result.stdout.strip():
            if traceback_output:
                traceback_output += "\n"
            traceback_output += result.stdout.strip()
            
        try:
            from skills.error_analyzer import AriaErrorAnalyzer
            analyzer = AriaErrorAnalyzer(self.aria)
            analysis_json = analyzer.run(
                task_id=task_id,  # Map key to failure_<task_id>
                task_description=f"Analyze failure in {test_cmd}",
                payload={
                    "traceback": traceback_output,
                    "test_command": test_cmd,
                    "campaign_id": campaign_id
                },
                campaign_id=campaign_id
            )
            analysis = json.loads(analysis_json)
            self.log_state_shift("IDLE", f"Test failure logged. Severity: {analysis.get('severity')}")
            return json.dumps({
                "status": "FAILED",
                "test_command": test_cmd,
                "return_code": result.returncode,
                "traceback": traceback_output,
                "analysis": analysis
            })
        except Exception as e:
            self.log_state_shift("IDLE", f"Test failure logged but analysis execution failed: {e}")
            return json.dumps({
                "status": "FAILED",
                "test_command": test_cmd,
                "return_code": result.returncode,
                "traceback": traceback_output,
                "error_triggering_analyzer": str(e)
            })
