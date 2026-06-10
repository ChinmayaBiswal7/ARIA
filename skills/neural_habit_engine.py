"""
skills/neural_habit_engine.py — Neural Habit Intelligence Engine for ARIA
========================================================================
Implements a multi-output Keras model that predicts study sessions, durations, and topics.
Integrates validation split metrics, weekend feature flags, Knowledge RAG suggestions,
and prediction history archival. Runs rule-based fallback when model is dormant.
"""

import os
import json
import glob
import time
import numpy as np
from typing import Dict, Any, List

from skills.base_agent import BaseAgent

try:
    import tensorflow as tf
    TF_AVAILABLE = True
except ImportError:
    tf = None
    TF_AVAILABLE = False


class AriaNeuralHabitEngine(BaseAgent):
    TOPIC_MAP = {
        "DSA": 0,
        "DBMS": 1,
        "JAVA": 2,
        "CN": 3,
        "OS": 4,
        "OOP": 5,
        "INTERVIEW": 6,
        "PROJECT": 7
    }
    REVERSE_TOPIC_MAP = {v: k for k, v in TOPIC_MAP.items()}

    def __init__(self, aria_instance, model_path: str = "models/habit_predictor.keras", dataset_dir: str = "data/habit_dataset"):
        super().__init__("NeuralHabitEngineAgent", aria_instance)
        self.model_path = model_path
        self.dataset_dir = dataset_dir
        self.model = None
        
        self.build_model()
        self.load_model()

    def build_model(self):
        """Constructs the multi-output Keras model architecture."""
        if not TF_AVAILABLE:
            print("[NeuralHabitEngine] TensorFlow not available. Cannot build model.")
            return

        try:
            inputs = tf.keras.Input(shape=(5,), name="features")
            
            # Shared dense representation
            x = tf.keras.layers.Dense(32, activation="relu")(inputs)
            x = tf.keras.layers.Dense(16, activation="relu")(x)
            
            # Outputs
            prob_out = tf.keras.layers.Dense(1, activation="sigmoid", name="probability")(x)
            duration_out = tf.keras.layers.Dense(1, activation="relu", name="duration")(x)
            topic_out = tf.keras.layers.Dense(len(self.TOPIC_MAP), activation="softmax", name="topic")(x)
            
            self.model = tf.keras.Model(inputs=inputs, outputs=[prob_out, duration_out, topic_out])
            
            self.model.compile(
                optimizer="adam",
                loss={
                    "probability": "binary_crossentropy",
                    "duration": "mse",
                    "topic": "sparse_categorical_crossentropy"
                },
                loss_weights={
                    "probability": 1.0,
                    "duration": 0.01,
                    "topic": 1.0
                },
                metrics={
                    "probability": "accuracy",
                    "topic": "accuracy"
                }
            )
            print("[NeuralHabitEngine] Model architecture compiled successfully.")
        except Exception as e:
            print(f"[NeuralHabitEngine] Error building Keras model: {e}")

    def load_model(self) -> bool:
        """Loads the habit predictor model from disk if it exists."""
        if not TF_AVAILABLE:
            return False

        if os.path.exists(self.model_path):
            try:
                self.model = tf.keras.models.load_model(self.model_path)
                print(f"[NeuralHabitEngine] Loaded trained model from {self.model_path}")
                return True
            except Exception as e:
                print(f"[NeuralHabitEngine] Error loading model: {e}")
        return False

    def get_latest_session_metrics(self) -> tuple:
        """Scans the habit dataset to extract metrics of the latest completed session."""
        dataset_dir = self.dataset_dir
        search_path = os.path.join(dataset_dir, "session_*.json")
        file_list = glob.glob(search_path)
        
        if not file_list:
            return 0.0, "DBMS"

        # Sort files by timestamp in the filename
        def get_ts(filepath):
            try:
                basename = os.path.basename(filepath)
                ts_part = basename.replace("session_", "").replace(".json", "")
                return int(ts_part)
            except ValueError:
                return 0

        file_list.sort(key=get_ts, reverse=True)
        latest_file = file_list[0]

        try:
            with open(latest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            duration = float(data.get("duration", 0.0))
            topic = data.get("topic", "DBMS").upper().strip()
            return duration, topic
        except Exception:
            return 0.0, "DBMS"

    def get_dataset_stats(self) -> tuple:
        """Compiles total sessions and unique days covered from files directly."""
        dataset_dir = self.dataset_dir
        search_path = os.path.join(dataset_dir, "session_*.json")
        file_list = glob.glob(search_path)
        total_sessions = len(file_list)
        unique_days = set()
        
        for f in file_list:
            try:
                with open(f, "r", encoding="utf-8") as file:
                    data = json.load(file)
                if "date" in data:
                    unique_days.add(data["date"])
            except Exception:
                continue
        return total_sessions, len(unique_days)

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        self.log_state_shift("RUNNING", "Generating study habit forecast...")
        
        # Determine prediction inputs based on current local time
        now_struct = time.localtime()
        day_of_week = float(now_struct.tm_wday)
        hour_of_day = float(now_struct.tm_hour)
        is_weekend = 1.0 if day_of_week >= 5.0 else 0.0
        
        prev_duration, prev_topic = self.get_latest_session_metrics()
        prev_topic_id = float(self.TOPIC_MAP.get(prev_topic, self.TOPIC_MAP["DBMS"]))
        
        features = [day_of_week, hour_of_day, is_weekend, prev_duration, prev_topic_id]
        
        forecast = self.generate_habit_forecast(features)
        
        self.log_state_shift("IDLE", f"Forecast compiled. Predicted topic: {forecast['predicted_topic']}.")
        return json.dumps(forecast)

    def generate_habit_forecast(self, features: List[float]) -> Dict[str, Any]:
        """Runs the neural model prediction, or falls back to rules if untrained."""
        total_sessions, days_covered = self.get_dataset_stats()
        
        # Confidence base: data collection fraction
        min_sessions = 100
        min_days = 14
        data_confidence = min(total_sessions / min_sessions, days_covered / min_days)
        
        # Default fallback values for outputs
        probability = 0.75
        expected_duration = 90
        predicted_topic = "DBMS"
        is_trained = False
        model_quality = 1.0
        
        # Load metadata if exists
        meta_path = "models/habit_predictor_meta.json"
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                # Penalty is based on validation accuracy from retraining run
                model_quality = meta.get("val_topic_accuracy", meta.get("val_accuracy", meta.get("accuracy", 1.0)))
            except Exception:
                pass

        # Check if model exists and loaded
        if self.model is not None and os.path.exists(self.model_path):
            try:
                x = np.array([features], dtype=np.float32)
                prob_pred, dur_pred, topic_preds = self.model.predict(x, verbose=0)
                
                probability = float(prob_pred[0][0])
                expected_duration = int(np.round(dur_pred[0][0]))
                topic_idx = int(np.argmax(topic_preds[0]))
                predicted_topic = self.REVERSE_TOPIC_MAP.get(topic_idx, "DBMS")
                is_trained = True
            except Exception as e:
                print(f"[NeuralHabitEngine] Prediction error: {e}. Falling back to rule-based.")
        
        # Fallback heuristic if untrained
        if not is_trained:
            # Query recent topic keyword matches from conversational agent
            try:
                from skills.agent_registry import registry
                habit_intelligence_wrapper = registry.get("habitintelligenceagent")
                if habit_intelligence_wrapper and habit_intelligence_wrapper.agent:
                    predicted_topic = habit_intelligence_wrapper.agent._determine_active_study_topic()
            except Exception:
                pass
                
            # Average duration fallback
            dataset_dir = self.dataset_dir
            search_path = os.path.join(dataset_dir, "session_*.json")
            file_list = glob.glob(search_path)
            durations = []
            for f in file_list:
                try:
                    with open(f, "r", encoding="utf-8") as file:
                        data = json.load(file)
                    durations.append(float(data.get("duration", 90.0)))
                except Exception:
                    continue
            if durations:
                expected_duration = int(np.mean(durations))

        # Calculate final penalized confidence
        confidence = float(data_confidence * model_quality)
        
        # Query Knowledge RAG matching predicted topic
        recommendations = self.get_rag_recommendations(predicted_topic)
        
        forecast = {
            "predicted_probability": probability,
            "expected_duration": expected_duration,
            "predicted_topic": predicted_topic,
            "confidence": confidence,
            "model_quality": model_quality,
            "is_trained": is_trained,
            "recommended_resources": recommendations
        }
        
        # Store prediction history
        self.archive_prediction(forecast)
        
        return forecast

    def archive_prediction(self, forecast: Dict[str, Any]):
        """Saves current study session forecast to prediction history archive and registers it in prediction_ledger."""
        predictions_dir = "data/habit_predictions"
        os.makedirs(predictions_dir, exist_ok=True)
        
        timestamp = int(time.time())
        pred_id = f"PRED_HABIT_{timestamp}"
        record = {
            "timestamp": timestamp,
            "prediction_id": pred_id,
            "predicted_topic": forecast["predicted_topic"],
            "predicted_duration": forecast["expected_duration"],
            "predicted_probability": forecast["predicted_probability"],
            "confidence": forecast["confidence"],
            "actual_topic": None,
            "actual_duration": None
        }
        
        pred_file = os.path.join(predictions_dir, f"prediction_{timestamp}.json")
        try:
            with open(pred_file, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)
        except Exception as e:
            print(f"[NeuralHabitEngine] Failed to write prediction archive: {e}")

        try:
            from skills.self_improvement_core import AriaSelfImprovementCore
            si_core = AriaSelfImprovementCore()
            si_core.register_system_prediction(pred_id, forecast["predicted_topic"].upper())
            print(f"[NeuralHabitEngine] Registered prediction {pred_id} in prediction_ledger: {forecast['predicted_topic'].upper()}")
        except Exception as e:
            print(f"[NeuralHabitEngine] Failed to register prediction in SQLite ledger: {e}")

    def get_rag_recommendations(self, topic: str, k: int = 3) -> List[str]:
        """Queries the Knowledge RAG vector store for document recommendations matching the topic."""
        recommendations = []
        try:
            from skills.embedding_engine import AriaEmbeddingEngine
            from skills.vector_store import AriaVectorStore
            
            vault_dir = "data/knowledge_vault"
            if not os.path.exists(vault_dir):
                return [f"{topic}_Unit1_Notes.pdf", f"{topic}_Revision_Sheet.pdf"]
                
            encoder = AriaEmbeddingEngine()
            vector_store = AriaVectorStore(vault_dir)
            if not vector_store.load():
                return [f"{topic}_Unit1_Notes.pdf", f"{topic}_Revision_Sheet.pdf"]
                
            query_embedding = encoder.get_embedding(topic)
            if query_embedding:
                chunks = vector_store.search(query_embedding, k=10)
                seen_sources = set()
                for chunk in chunks:
                    source_path = chunk.get("source")
                    if source_path:
                        basename = os.path.basename(source_path)
                        if basename not in seen_sources:
                            seen_sources.add(basename)
                            recommendations.append(basename)
                            if len(recommendations) >= k:
                                break
        except Exception as e:
            print(f"[NeuralHabitEngine] RAG recommendation retrieval failed: {e}")
            
        if not recommendations:
            recommendations = [f"{topic}_Unit1_Notes.pdf", f"{topic}_Revision_Sheet.pdf"]
        return recommendations
