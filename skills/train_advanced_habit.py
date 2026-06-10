import os
import sqlite3
import time
import numpy as np
from typing import Dict, Any
from skills.advanced_habit_network import AriaAdvancedHabitNetwork

class AriaAdvancedHabitTrainer:
    def __init__(self, network_instance: AriaAdvancedHabitNetwork):
        self.network = network_instance

    def trigger_continuous_retraining(self) -> Dict[str, Any]:
        """Audits the dataset gate and runs an on-device optimization sweep."""
        gate_passed, stats = self.network.evaluate_maturity_gate()
        
        if not gate_passed:
            return {
                "status": "DATASET_MATURITY_GATE_LOCKED",
                "message": "Continuous retraining paused. Collecting baseline routine data.",
                "stats": stats
            }

        # Check if TF/Keras model is compiled
        if self.network.model is None:
            return {
                "status": "ERROR",
                "message": "TensorFlow/Keras model not compiled. Cannot train.",
                "stats": stats
            }

        x_train, y_prob, y_metrics = self._extract_training_matrices_from_ledger()
        
        if len(x_train) == 0:
            return {
                "status": "ERROR", 
                "message": "No vectorized training samples available in the ledger.",
                "stats": stats
            }

        # Local CPU training optimization pass loops
        try:
            self.network.model.fit(
                x_train,
                {"session_probability": y_prob, "duration_and_topic": y_metrics},
                epochs=10,
                batch_size=16,
                verbose=0
            )
            self.network.model.save(self.network.model_path)
            print(f"[AdvancedHabitTrainer] Successfully retrained model on {len(x_train)} samples.")
        except Exception as e:
            return {
                "status": "ERROR",
                "message": f"Training failed: {e}",
                "stats": stats
            }
        
        return {
            "status": "SUCCESS_RETRAINED",
            "message": f"GRU model successfully retrained over {len(x_train)} historical outcome vectors.",
            "stats": stats
        }

    def _extract_training_matrices_from_ledger(self):
        x_list, y_p, y_m = [], [], []
        
        try:
            with sqlite3.connect(self.network.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT prediction_text, actual_outcome, accuracy_score, timestamp 
                    FROM prediction_ledger WHERE accuracy_score IS NOT NULL
                """)
                rows = cursor.fetchall()
        except Exception as e:
            print(f"[AdvancedHabitTrainer] Error loading training data: {e}")
            rows = []

        for row in rows:
            pred_text = row["prediction_text"]
            actual = row["actual_outcome"]
            score = row["accuracy_score"]
            ts = row["timestamp"]
            
            # Formulate sample feature vectors natively
            lt = time.localtime(ts)
            
            # Map previous topic ID (DBMS=1, JAVA=2, CN=3, etc.)
            topics = ["DSA", "DBMS", "JAVA", "CN", "OS", "OOP", "INTERVIEW", "PROJECT"]
            topic_id = 1.0
            if pred_text in topics:
                topic_id = float(topics.index(pred_text))
            
            # Extract feature matrix for this prediction snapshot
            features = self.network.extract_advanced_feature_matrix(
                day=lt.tm_wday, 
                hour=lt.tm_hour, 
                weekend_flag=(1 if lt.tm_wday >= 5 else 0),
                prev_dur=90.0, 
                topic_id=int(topic_id)
            )
            
            # Map verification arrays: features is shape (1, 1, 10), get raw 10 features
            x_list.append(features[0][0])
            y_p.append([float(score)])  # Target probability: 1.0 for success, 0.0 for mismatch/failure
            
            # Duration and topic index target metrics
            actual_topic_idx = 1.0
            if actual in topics:
                actual_topic_idx = float(topics.index(actual))
            y_m.append([90.0, actual_topic_idx])

        if not x_list:
            return np.array([]), np.array([]), np.array([])

        # Reshape for GRU input format: [Samples, TimeSteps=1, Features=10]
        return (
            np.array(x_list, dtype="float32")[:, np.newaxis, :],
            np.array(y_p, dtype="float32"),
            np.array(y_m, dtype="float32")
        )
