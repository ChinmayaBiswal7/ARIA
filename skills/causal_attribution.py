import sqlite3
import threading
import time

class CausalAttributionEngine:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CausalAttributionEngine, cls).__new__(cls)
                cls._instance.db_path = "aria_memory.db"
                cls._instance._init_db()
            return cls._instance

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS causal_attributions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL,
                    failed_action TEXT NOT NULL,
                    assigned_cause TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()

    def analyze_failure_cause(self, task, failed_action, error_message, latency=0.0, interrupted=False, load_score=0.1):
        """
        Deduces the root cause of execution failure:
        - user_interruption: Task halted by low battery alert or user speech trigger.
        - latency: CPU stress, memory constraints, or network lag caused task timeout.
        - ui: OCR mismatch, target element coordinates moved, or page loading took too long.
        - planner: LLM generated invalid tag formats or incorrect task routing path.
        - environment: Operational system, network connection, or window focus lost.
        - tool: Underlying click/type tool driver threw direct exceptions.
        """
        error_lower = str(error_message).lower()
        action_lower = str(failed_action).lower()
        
        # 1. Deduce cause
        if interrupted:
            cause = "user_interruption"
            explanation = "Task execution was explicitly halted by an attention alert or user interruption."
        elif load_score > 0.85 or latency > 10.0:
            cause = "latency"
            explanation = f"System metrics indicate extreme execution delay (latency: {latency:.2f}s, load: {load_score:.2f}) causing timeouts."
        elif any(x in error_lower for x in ["not found", "ocr", "coordinate", "element", "visible", "stuck"]):
            cause = "ui"
            explanation = "Visual or OCR matching failed to ground the target element on the current screen viewport."
        elif any(x in error_lower for x in ["json", "invalid tag", "parse", "format", "prompt", "model"]):
            cause = "planner"
            explanation = "The planning brain generated invalid command syntax or incorrect task routing decisions."
        elif any(x in error_lower for x in ["connection", "socket", "timeout", "network", "offline"]):
            cause = "environment"
            explanation = "Underlying network connection dropped or focus on target application was lost."
        else:
            cause = "tool"
            explanation = f"The action driver for '{failed_action}' raised an execution-level script error."

        # 2. Record to database
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO causal_attributions (task, failed_action, assigned_cause, explanation, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (task, failed_action, cause, explanation, time.strftime("%Y-%m-%d %H:%M:%S"))
                )
                conn.commit()
        except Exception as e:
            print(f"[CausalAttribution] Database insert error: {e}")

        return {
            "cause": cause,
            "explanation": explanation
        }


class CausalAdaptationEngine:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CausalAdaptationEngine, cls).__new__(cls)
                cls._instance.db_path = "aria_memory.db"
                cls._instance._init_db()
            return cls._instance

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS causal_attributions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL,
                    failed_action TEXT NOT NULL,
                    assigned_cause TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()

    def get_adaptation_remediations(self):
        """
        Queries the last logged failure cause and yields targeted policy remedies:
        - planner: Enforces direct step restriction.
        - ui: Enforces coordinate fallback and visual OCR wait buffers.
        - latency: Throttles execution and inserts longer wait steps.
        - environment: Sleep retries.
        - tool: Decreases skill trust and diverts flow.
        - user_interruption: Cuts down autonomy mode to safe verification.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT assigned_cause, failed_action FROM causal_attributions ORDER BY id DESC LIMIT 1")
                row = cursor.fetchone()
                
            if not row:
                return None
                
            cause, failed_action = row
            
            remedies = {
                "planner": {
                    "action": "Enforce strict JSON schema boundaries and plan smaller, simpler action goals (max 3 steps). Avoid long nested routing.",
                    "tag": "PLANNER OPTIMIZATION"
                },
                "ui": {
                    "action": "Avoid absolute coordinates. Instead, search using visual UI keyword anchors and wait 3.0 seconds for screen stabilization.",
                    "tag": "UI GROUNDING ADAPTATION"
                },
                "latency": {
                    "action": "Throttle execution speed. Insert explicit wait/sleep actions before checking screen updates.",
                    "tag": "LATENCY MITIGATION"
                },
                "environment": {
                    "action": "Sleep for 5.0 seconds to wait for network stabilization and target window focus recovery.",
                    "tag": "ENVIRONMENT STABILIZATION"
                },
                "tool": {
                    "action": f"Avoid using the failed tool '{failed_action}' if alternatives exist. Divert execution to command-line shell scripts.",
                    "tag": "TOOL DRIVER CORRECTION"
                },
                "user_interruption": {
                    "action": "Reduce autonomy status. Proactively ask for confirmation before executing subsequent actions.",
                    "tag": "USER CONTROL INTERRUPT"
                }
            }
            
            remedy = remedies.get(cause, {
                "action": "General policy review. Run verification tests.",
                "tag": "GENERAL POLICY"
            })
            
            return {
                "cause": cause,
                "failed_action": failed_action,
                "remedy_action": remedy["action"],
                "tag": remedy["tag"]
            }
        except Exception as e:
            print(f"[CausalAdaptation] Remediation query error: {e}")
            return None
