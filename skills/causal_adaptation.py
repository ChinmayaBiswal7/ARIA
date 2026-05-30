import sqlite3
import threading

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
