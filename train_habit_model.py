"""
train_habit_model.py — Off-line Training Pipeline for ARIA Habit Predictor
=========================================================================
Loads focus session logs, formats features with weekend flags, performs negative sampling,
trains the multi-output Keras model, and logs accuracy metadata.
"""

import os
import json
import glob
import time
import numpy as np

# Ensure TensorFlow warnings are clean
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

try:
    import tensorflow as tf
    TF_AVAILABLE = True
except ImportError:
    tf = None
    TF_AVAILABLE = False

# Topic Mapping Definitions
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


def build_habit_model():
    """Creates and compiles the Keras multi-output network."""
    inputs = tf.keras.Input(shape=(5,), name="features")
    
    # Shared Dense base layers
    x = tf.keras.layers.Dense(32, activation="relu")(inputs)
    x = tf.keras.layers.Dense(16, activation="relu")(x)
    
    # Branching output heads
    prob_out = tf.keras.layers.Dense(1, activation="sigmoid", name="probability")(x)
    duration_out = tf.keras.layers.Dense(1, activation="relu", name="duration")(x)
    topic_out = tf.keras.layers.Dense(len(TOPIC_MAP), activation="softmax", name="topic")(x)
    
    model = tf.keras.Model(inputs=inputs, outputs=[prob_out, duration_out, topic_out])
    
    model.compile(
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
            "duration": "mae",
            "topic": "accuracy"
        }
    )
    return model


def check_dataset_readiness(dataset_dir: str = "data/habit_dataset") -> tuple:
    """Verifies that the dataset satisfies training gates (100 sessions AND 14 days)."""
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
            
    days_covered = len(unique_days)
    is_ready = (total_sessions >= 100) and (days_covered >= 14)
    return is_ready, total_sessions, days_covered


def run_training_pipeline(dataset_dir: str = "data/habit_dataset", models_dir: str = "models", epochs: int = 30) -> bool:
    """Loads dataset files, prepares positive & negative samples, trains model, and saves files."""
    if not TF_AVAILABLE:
        print("[TrainingPipeline] Error: TensorFlow is not installed in the environment.")
        return False

    is_ready, total_sessions, days_covered = check_dataset_readiness(dataset_dir)
    if not is_ready:
        print(f"[TrainingPipeline] Gate Not Satisfied: Sessions = {total_sessions}/100, Days = {days_covered}/14. Dormant state preserved.")
        return False

    # 1. Load files chronologically
    search_path = os.path.join(dataset_dir, "session_*.json")
    file_list = glob.glob(search_path)
    
    def get_ts(filepath):
        try:
            basename = os.path.basename(filepath)
            ts_part = basename.replace("session_", "").replace(".json", "")
            return int(ts_part)
        except ValueError:
            return 0

    file_list.sort(key=get_ts)
    
    sessions_data = []
    for f in file_list:
        try:
            with open(f, "r", encoding="utf-8") as file:
                data = json.load(file)
            sessions_data.append(data)
        except Exception:
            continue

    if len(sessions_data) < 2:
        print("[TrainingPipeline] Error: Insufficient valid session data to sequence features.")
        return False

    # 2. Build feature vectors and target labels
    X = []
    y_prob = []
    y_dur = []
    y_topic = []

    # Map daily session records to identify busy hours (to avoid overlapping negative samples)
    day_busy_hours = {}
    for s in sessions_data:
        date_str = s.get("date", "")
        start_h = s.get("start_hour", 0)
        dur_h = int(np.ceil(s.get("duration", 0) / 60.0))
        if date_str:
            if date_str not in day_busy_hours:
                day_busy_hours[date_str] = set()
            for h in range(start_h, start_h + dur_h + 1):
                day_busy_hours[date_str].add(h % 24)

    for i in range(1, len(sessions_data)):
        curr_sess = sessions_data[i]
        prev_sess = sessions_data[i - 1]
        
        date_str = curr_sess.get("date", "")
        start_hour = int(curr_sess.get("start_hour", 12))
        duration = float(curr_sess.get("duration", 60.0))
        topic = curr_sess.get("topic", "DBMS").upper().strip()
        topic_idx = TOPIC_MAP.get(topic, TOPIC_MAP["DBMS"])

        # Determine day of week from date_str or current timestamp fallback
        try:
            struct_t = time.strptime(date_str, "%Y-%m-%d")
            day_of_week = float(struct_t.tm_wday)
        except Exception:
            day_of_week = 0.0
            
        is_weekend = 1.0 if day_of_week >= 5.0 else 0.0
        
        prev_duration = float(prev_sess.get("duration", 0.0))
        prev_topic = prev_sess.get("topic", "DBMS").upper().strip()
        prev_topic_idx = float(TOPIC_MAP.get(prev_topic, TOPIC_MAP["DBMS"]))

        # A. Positive Sample (Study Started)
        pos_features = [day_of_week, float(start_hour), is_weekend, prev_duration, prev_topic_idx]
        X.append(pos_features)
        y_prob.append(1.0)
        y_dur.append(duration)
        y_topic.append(topic_idx)

        # B. Negative Sample (Study did NOT start)
        # Select a random hour on the same day not in busy hours
        busy = day_busy_hours.get(date_str, set())
        neg_hour = None
        for h in [8, 10, 14, 16, 23, 2, 4]:  # candidate non-study hours
            if h not in busy:
                neg_hour = float(h)
                break
        if neg_hour is None:
            # Fallback distance heuristic
            neg_hour = float((start_hour + 12) % 24)

        neg_features = [day_of_week, neg_hour, is_weekend, prev_duration, prev_topic_idx]
        X.append(neg_features)
        y_prob.append(0.0)
        y_dur.append(0.0)
        y_topic.append(prev_topic_idx)  # assume prev topic holds as target baseline

    X_np = np.array(X, dtype=np.float32)
    y_prob_np = np.array(y_prob, dtype=np.float32)
    y_dur_np = np.array(y_dur, dtype=np.float32)
    y_topic_np = np.array(y_topic, dtype=np.int32)

    # 3. Build and Fit Model
    print(f"[TrainingPipeline] Training model with {len(X_np)} samples...")
    model = build_habit_model()
    
    history = model.fit(
        X_np,
        {
            "probability": y_prob_np,
            "duration": y_dur_np,
            "topic": y_topic_np
        },
        epochs=epochs,
        batch_size=8,
        validation_split=0.2,
        verbose=1
    )

    # 4. Save model files
    os.makedirs(models_dir, exist_ok=True)
    model_path = os.path.join(models_dir, "habit_predictor.keras")
    model_bak_path = os.path.join(models_dir, "habit_predictor.keras.bak")
    
    try:
        model.save(model_path)
        model.save(model_bak_path)
        print(f"[TrainingPipeline] Saved trained model to {model_path} and backup.")
    except Exception as e:
        print(f"[TrainingPipeline] Error saving keras model: {e}")
        return False

    # 5. Extract training validation metrics & save metadata
    # Keras logs metric history under val_<head_name>_<metric_name> or val_<metric_name>
    h_dict = history.history
    
    # Find accuracy keys
    val_prob_acc_keys = [k for k in h_dict.keys() if "val" in k and "prob" in k and "acc" in k]
    val_prob_acc = float(h_dict[val_prob_acc_keys[0]][-1]) if val_prob_acc_keys else 1.0
    
    val_topic_acc_keys = [k for k in h_dict.keys() if "val" in k and "topic" in k and "acc" in k]
    val_topic_acc = float(h_dict[val_topic_acc_keys[0]][-1]) if val_topic_acc_keys else 1.0
    
    val_duration_mae_keys = [k for k in h_dict.keys() if "val" in k and "dur" in k and "mae" in k]
    val_duration_mae = float(h_dict[val_duration_mae_keys[0]][-1]) if val_duration_mae_keys else 0.0

    meta = {
        "trained_at": int(time.time()),
        "sessions": total_sessions,
        "days": days_covered,
        "accuracy": val_topic_acc,
        "val_probability_accuracy": val_prob_acc,
        "val_topic_accuracy": val_topic_acc,
        "duration_mae": val_duration_mae
    }

    meta_path = os.path.join(models_dir, "habit_predictor_meta.json")
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        print(f"[TrainingPipeline] Saved performance metadata to {meta_path}")
    except Exception as e:
        print(f"[TrainingPipeline] Failed to write training metadata: {e}")

    return True


if __name__ == "__main__":
    import sys
    data_dir = "data/habit_dataset"
    if len(sys.argv) > 1:
        data_dir = sys.argv[1]
    
    run_training_pipeline(dataset_dir=data_dir)
