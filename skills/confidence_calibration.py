import sqlite3
import threading
import time

class ConfidenceCalibrationEngine:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ConfidenceCalibrationEngine, cls).__new__(cls)
                cls._instance.db_path = "aria_memory.db"
                cls._instance.calibration_factor = 1.0
                cls._instance._init_db()
            return cls._instance

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS confidence_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL,
                    predicted_confidence REAL NOT NULL,
                    outcome TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()

    def log_confidence_prediction(self, task, predicted_confidence, outcome):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO confidence_history (task, predicted_confidence, outcome, timestamp) VALUES (?, ?, ?, ?)",
                (task, predicted_confidence, outcome, time.strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()
            
        self.recalibrate()

    def recalibrate(self):
        """
        Recalibrates the confidence scaling factor:
        - Compares predicted confidence vs actual success outcomes over the last 10 tasks.
        - If overconfident (high prediction, low success), scale factor decays.
        - If calibrated, scale factor restores towards 1.0.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT predicted_confidence, outcome FROM confidence_history ORDER BY id DESC LIMIT 10")
                rows = cursor.fetchall()
                
            if len(rows) < 3:
                return  # Awaiting more data
                
            avg_pred = sum(r[0] for r in rows) / len(rows)
            successes = sum(1 for r in rows if r[1] == "success")
            actual_success_rate = successes / len(rows)
            
            # Calibration gap detection
            gap = avg_pred - actual_success_rate
            
            with self._lock:
                if gap > 0.20:
                    # Overconfident gap detected -> scale down
                    self.calibration_factor = max(self.calibration_factor * 0.85, 0.40)
                    print(f"[ConfidenceCalibrator] Overconfidence detected (gap: {gap:.2f}). Decaying scaling factor to {self.calibration_factor:.2f}")
                elif gap < -0.10:
                    # Underconfident gap detected -> boost factor slightly
                    self.calibration_factor = min(self.calibration_factor * 1.05, 1.20)
                else:
                    # Calibrated -> slowly decay/restore back to 1.0
                    if self.calibration_factor < 1.0:
                        self.calibration_factor = min(self.calibration_factor + 0.02, 1.0)
                    elif self.calibration_factor > 1.0:
                        self.calibration_factor = max(self.calibration_factor - 0.02, 1.0)
        except Exception as e:
            print(f"[ConfidenceCalibrator] Recalibration error: {e}")

    def get_calibrated_confidence(self, raw_confidence):
        with self._lock:
            return round(max(min(raw_confidence * self.calibration_factor, 1.0), 0.0), 2)
