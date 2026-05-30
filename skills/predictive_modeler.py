import os
import sqlite3
import threading

class PredictiveModeler:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(PredictiveModeler, cls).__new__(cls)
                cls._instance.db_path = "aria_memory.db"
            return cls._instance

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def estimate_outcome(self, strategy_key):
        """
        Predicts strategy performance metrics before execution:
        - success_probability: Float (0.0 to 1.0)
        - expected_latency: Float (seconds)
        - failure_risk: Float (0.0 to 1.0)
        """
        strategy_key = strategy_key.strip().lower()
        
        success_count = 0
        failure_count = 0
        weight = 1.0
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT success_count, failure_count, weight FROM strategy_weights WHERE strategy_key = ?",
                    (strategy_key,)
                )
                row = cursor.fetchone()
                if row:
                    success_count, failure_count, weight = row
        except Exception:
            pass

        # 1. Success Probability
        total_runs = success_count + failure_count
        if total_runs > 0:
            success_prob = success_count / total_runs
        else:
            # Baseline assumptions based on strategy category
            if strategy_key in ["click", "open"]:
                success_prob = 0.92
            elif strategy_key in ["type", "write"]:
                success_prob = 0.88
            elif strategy_key in ["search", "google"]:
                success_prob = 0.90
            else:
                success_prob = 0.85

        # 2. Expected Latency prediction
        # Query activity_log for average response times if available
        avg_lat = 0.0
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Lookup latency from completed episodes if strategy matched
                cursor.execute(
                    "SELECT AVG(length(steps_json)*0.01) FROM episodic_memory WHERE goal LIKE ?",
                    (f"%{strategy_key}%",)
                )
                res = cursor.fetchone()
                if res and res[0] is not None:
                    avg_lat = float(res[0])
        except Exception:
            pass

        if avg_lat <= 0.0:
            # Fallback expected latencies
            lat_map = {
                "click": 1.2,
                "open": 3.8,
                "type": 1.8,
                "write": 2.2,
                "search": 4.5,
                "default": 2.5
            }
            avg_lat = lat_map.get(strategy_key, lat_map["default"])

        # 3. Expected Failure Risk & Recovery Cost
        fail_risk = 1.0 - success_prob
        # Recovery cost increases with historical failure counts
        recovery_cost = min(0.1 + (failure_count * 0.15), 1.0)
        
        risk_level = "LOW"
        if fail_risk > 0.4 or recovery_cost > 0.6:
            risk_level = "HIGH"
        elif fail_risk > 0.2:
            risk_level = "MEDIUM"

        return {
            "strategy": strategy_key,
            "success_prob": round(success_prob, 2),
            "expected_latency": round(avg_lat, 2),
            "fail_risk": round(fail_risk, 2),
            "recovery_cost": round(recovery_cost, 2),
            "risk_level": risk_level
        }
