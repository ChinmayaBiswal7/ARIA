import sqlite3
import threading

class RuntimeModeProfiler:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(RuntimeModeProfiler, cls).__new__(cls)
                cls._instance.db_path = "aria_memory.db"
                cls._instance.current_profile = "AUTONOMOUS"
            return cls._instance

    def evaluate_profile(self, load_score=0.1, recent_success_rate=1.0):
        """
        Evaluates system parameters to select the dynamic runtime profile:
        - MINIMAL: High load/timeouts -> limit steps, bypass high-resource vision.
        - CONSERVATIVE: Recent failures -> mandate confirmations (safe mode).
        - EXPLORATION: High stability, low load -> test alternative paths.
        - AUTONOMOUS: Default stable operation.
        """
        # 1. Fetch recent success rate from db if not provided
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT outcome FROM activity_log ORDER BY id DESC LIMIT 5")
                rows = cursor.fetchall()
                if rows:
                    succs = sum(1 for r in rows if r[0] == "success")
                    recent_success_rate = succs / len(rows)
        except Exception:
            pass

        # 2. Select profile
        with self._lock:
            old_profile = self.current_profile
            
            if load_score > 0.75:
                self.current_profile = "MINIMAL"
            elif recent_success_rate < 0.60:
                self.current_profile = "CONSERVATIVE"
            elif recent_success_rate > 0.90 and load_score < 0.30:
                self.current_profile = "EXPLORATION"
            else:
                self.current_profile = "AUTONOMOUS"
                
            transitioned = (old_profile != self.current_profile)
            return {
                "profile": self.current_profile,
                "transitioned": transitioned,
                "previous_profile": old_profile
            }
