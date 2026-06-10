"""
skills/adaptive_person_memory.py — Self-improving Face Recognition Profile Learner for ARIA
========================================================================================
Maintains and grows face profiles over time by intercepting high-confidence verifications,
filtering for image quality and vector novelty, and writing back learned embeddings.
"""

import sqlite3
import time
import os
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None


class AriaAdaptivePersonMemory:
    def __init__(self, db_path: str = "aria_orchestrator.db", face_store_instance=None):
        self.db_path = db_path
        self.face_store = face_store_instance
        self.max_daily_embeddings = 10
        
        # Confirmation queues to prevent learning on single-frame noise
        self._consecutive_counts = {}  # maps name -> count
        self._consecutive_embeddings = {}  # maps name -> list of embeddings
        self._consecutive_crops = {}  # maps name -> list of face crops
        
        self._ensure_evolution_schemas()

    def _ensure_evolution_schemas(self):
        """Creates evolutionary tracking schemas inside SQLite db."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS person_profile_evolution (
                        person_name TEXT PRIMARY KEY,
                        captured_angles_count INTEGER DEFAULT 1,
                        lighting_conditions INTEGER DEFAULT 1,
                        recognition_count INTEGER DEFAULT 1,
                        last_seen_timestamp INTEGER,
                        average_confidence REAL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS confidence_history_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        person_name TEXT,
                        logged_confidence REAL,
                        timestamp INTEGER
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS vision_event_timeline (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT,
                        entity_name TEXT,
                        confidence REAL,
                        timestamp INTEGER
                    )
                """)
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"[AdaptivePersonMemory] Schema setup error: {e}")

    def evaluate_and_learn_face(self, person_name: str, embedding: list, face_roi: np.ndarray, match_confidence: float) -> dict:
        """
        Processes a matching face frame. If the person has been consecutively recognized
        3 times, runs quality and novelty filters to determine if the embedding should be learned.
        """
        if self.face_store is None:
            return {"status": "SKIPPED_NO_STORE", "reason": "Face FAISS store instance is not linked."}

        now = int(time.time())
        person_name = person_name.strip()
        
        # Log validation confidence to track accuracy curves
        self._log_confidence(person_name, match_confidence, now)

        # Learning trigger rule 1: must be high confidence
        if match_confidence < 0.90:
            self._consecutive_counts.pop(person_name, None)
            self._consecutive_embeddings.pop(person_name, None)
            self._consecutive_crops.pop(person_name, None)
            return {"status": "SKIPPED_LOW_CONFIDENCE", "reason": f"Match confidence below threshold: {match_confidence:.2f}"}

        # Step 1: Manage Confirmation Queue (Require 3 consecutive verifications)
        self._consecutive_counts[person_name] = self._consecutive_counts.get(person_name, 0) + 1
        
        if person_name not in self._consecutive_embeddings:
            self._consecutive_embeddings[person_name] = []
        if person_name not in self._consecutive_crops:
            self._consecutive_crops[person_name] = []
            
        self._consecutive_embeddings[person_name].append(embedding)
        self._consecutive_crops[person_name].append(face_roi)

        if self._consecutive_counts[person_name] < 3:
            return {"status": "PENDING_CONFIRMATION", "count": self._consecutive_counts[person_name]}

        # We met 3 consecutive confirmations! Pull the middle frame's sample to evaluate
        eval_embedding = self._consecutive_embeddings[person_name][1]
        eval_crop = self._consecutive_crops[person_name][1]
        
        # Reset queue counters
        self._consecutive_counts.pop(person_name, None)
        self._consecutive_embeddings.pop(person_name, None)
        self._consecutive_crops.pop(person_name, None)

        # Step 2: Quality Gates (Size, Brightness, Blur)
        quality_ok, quality_reason = self.check_quality(eval_crop)
        if not quality_ok:
            return {"status": "SKIPPED_POOR_QUALITY", "reason": quality_reason}

        # Step 3: Daily Learning Cap Guardrail
        if self._is_daily_cap_reached(person_name, now):
            return {"status": "SKIPPED_DAILY_CAP_REACHED", "reason": f"Maximum of {self.max_daily_embeddings} daily additions reached."}

        # Step 4: Fully Adaptive Novelty Checks
        is_novel, min_dist, novelty_reason = self.check_novelty(person_name, eval_embedding)
        if not is_novel:
            # Not novel enough, but we increment recognition counts
            self._increment_profile_metrics(person_name, now, new_angle_found=False, brightness_val=int(np.mean(eval_crop)))
            return {"status": "SKIPPED_DUPLICATE_ANGLE", "reason": novelty_reason}

        # Step 5: Save Face embedding and update Profile Evolution
        success = self.face_store.add_face(person_name, eval_embedding)
        if success:
            brightness_val = int(np.mean(eval_crop))
            self._increment_profile_metrics(person_name, now, new_angle_found=True, brightness_val=brightness_val)
            
            # Log EVENT_PROFILE_EVOLVED in vision timeline DB and Blackboard
            event_id = self._log_timeline_evolved_event(person_name, match_confidence, now)
            
            return {
                "status": "LEARNING_SUCCESS_EMBEDDING_ADDED", 
                "person": person_name, 
                "min_distance": min_dist, 
                "event_id": event_id
            }

        return {"status": "SKIPPED_STORE_ERROR", "reason": "Failed to append vector to FAISS."}

    def check_quality(self, face_roi: np.ndarray) -> tuple:
        """Enforces blur, sizing, and brightness constraints on the raw crop image."""
        if face_roi is None or not hasattr(face_roi, "shape"):
            return False, "Face region array is empty or corrupt."

        h, w = face_roi.shape[:2]
        
        # 1. Size constraint
        if h < 80 or w < 80:
            return False, f"Crop size is too small: {w}x{h}px. Needs >= 80x80px."

        # Convert to grayscale if color
        if len(face_roi.shape) == 3:
            gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY) if cv2 else np.mean(face_roi, axis=2).astype(np.uint8)
        else:
            gray = face_roi

        # 2. Brightness checks
        mean_brightness = int(np.mean(gray))
        if mean_brightness < 40 or mean_brightness > 220:
            return False, f"Lighting is poor. Brightness value: {mean_brightness} (needs [40, 220])."

        # 3. Blur score checks (Laplacian variance)
        if cv2 is not None:
            blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
            if blur_score < 100.0:
                return False, f"Image is blurry. Laplacian variance: {blur_score:.1f} (needs >= 100.0)."
        else:
            # Fallback if cv2 is not loaded
            pass

        return True, "Quality checks passed."

    def check_novelty(self, name: str, embedding: list) -> tuple:
        """Determines if the embedding represents a novel angle using adaptive distance statistics."""
        existing_vectors = self.face_store.get_all_vectors_for_name(name)
        
        if not existing_vectors:
            return True, 0.0, "First baseline angle registered."

        new_vec = np.array(embedding, dtype=np.float32)

        # 1. Compute minimum distance to any existing vector
        distances_to_existing = [float(np.linalg.norm(new_vec - vec)) for vec in existing_vectors]
        min_dist = min(distances_to_existing)

        # 2. Calculate adaptive thresholds based on pairwise variance
        if len(existing_vectors) == 1:
            # If only 1 existing vector, we default duplication threshold to 0.20
            is_novel = min_dist >= 0.20 and min_dist <= 0.65
            if not is_novel:
                return False, min_dist, f"Too close to existing single vector. Distance: {min_dist:.2f} (needs >= 0.20)."
            return True, min_dist, f"Sufficiently different from first vector. Distance: {min_dist:.2f}."

        # Compute all pairwise distances among existing vectors
        pairwise_dists = []
        for i in range(len(existing_vectors)):
            for j in range(i + 1, len(existing_vectors)):
                pairwise_dists.append(float(np.linalg.norm(existing_vectors[i] - existing_vectors[j])))

        mean_pairwise = float(np.mean(pairwise_dists)) if pairwise_dists else 0.25
        std_pairwise = float(np.std(pairwise_dists)) if (pairwise_dists and len(pairwise_dists) > 1) else (0.15 * mean_pairwise)

        # Ensure std_pairwise is not zero to avoid division/boundary collapse
        if std_pairwise < 1e-4:
            std_pairwise = 0.15 * mean_pairwise

        # Fully adaptive thresholds:
        # Novel if distance to closest vector is within [mean - 1.0 * std, mean + 2.0 * std]
        lower_bound = mean_pairwise - 1.0 * std_pairwise
        upper_bound = mean_pairwise + 2.0 * std_pairwise

        is_novel = min_dist >= lower_bound and min_dist <= upper_bound
        
        if not is_novel:
            if min_dist < lower_bound:
                reason = f"Duplicate view. Distance {min_dist:.2f} is below adaptive lower bound {lower_bound:.2f}."
            else:
                reason = f"Outlier view. Distance {min_dist:.2f} is above adaptive upper bound {upper_bound:.2f}."
            return False, min_dist, reason

        return True, min_dist, f"Novel angle verified. Distance {min_dist:.2f} is within bounds [{lower_bound:.2f}, {upper_bound:.2f}]."

    def _is_daily_cap_reached(self, name: str, timestamp: int) -> bool:
        """Checks if the user has reached the daily limit of learned embeddings."""
        today_start = timestamp - (timestamp % 86400)
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM vision_event_timeline "
                    "WHERE LOWER(entity_name) = ? AND event_type = 'PERSON_PROFILE_EVOLVED' AND timestamp >= ?",
                    (name.lower().strip(), today_start)
                )
                count = cursor.fetchone()[0]
                return count >= self.max_daily_embeddings
            finally:
                conn.close()
        except Exception as e:
            print(f"[AdaptivePersonMemory] Daily cap check error: {e}")
            return False

    def _increment_profile_metrics(self, name: str, timestamp: int, new_angle_found: bool, brightness_val: int):
        """Updates the profile completeness registry metrics."""
        angle_delta = 1 if new_angle_found else 0
        
        # Simple lighting condition heuristic: bin brightness into 3 lighting zones (dark, medium, bright)
        light_zone = 1 if brightness_val < 80 else 2 if brightness_val < 160 else 3
        
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                # Query if lighting zone count is already initialized
                cursor = conn.execute("SELECT lighting_conditions FROM person_profile_evolution WHERE person_name = ?", (name,))
                row = cursor.fetchone()
                
                # Dynamic lighting conditions update: if we learn a new lighting condition range
                light_delta = 0
                if row:
                    current_lights = row[0]
                    # Simulate adding to distinct lighting condition clusters
                    if new_angle_found and current_lights < light_zone:
                        light_delta = 1
                
                conn.execute("""
                    INSERT INTO person_profile_evolution (person_name, captured_angles_count, lighting_conditions, recognition_count, last_seen_timestamp, average_confidence)
                    VALUES (?, ?, ?, 1, ?, 0.95)
                    ON CONFLICT(person_name) DO UPDATE SET
                        captured_angles_count = captured_angles_count + ?,
                        lighting_conditions = MAX(lighting_conditions, lighting_conditions + ?),
                        recognition_count = recognition_count + 1,
                        last_seen_timestamp = ?
                """, (name, 1 + angle_delta, light_zone, timestamp, angle_delta, light_delta, timestamp))
                conn.commit()
                
                # Also sync profile registry sample count
                from skills.person_profile_manager import AriaPersonProfileManager
                pm = AriaPersonProfileManager()
                pm.register_person(name)
                if new_angle_found:
                    pm.increment_face_count(name)
            finally:
                conn.close()
        except Exception as e:
            print(f"[AdaptivePersonMemory] Metrics update error: {e}")

    def _log_confidence(self, name: str, confidence: float, timestamp: int):
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    "INSERT INTO confidence_history_logs (person_name, logged_confidence, timestamp) VALUES (?, ?, ?)",
                    (name, confidence, timestamp)
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"[AdaptivePersonMemory] Log confidence error: {e}")

    def _log_timeline_evolved_event(self, name: str, confidence: float, timestamp: int) -> int:
        """Logs profile evolution events to the visual timeline and publishes to Blackboard."""
        event_id = 0
        event_type = "PERSON_PROFILE_EVOLVED"
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    "INSERT INTO vision_event_timeline (event_type, entity_name, confidence, timestamp) VALUES (?, ?, ?, ?)",
                    (event_type, name, confidence, timestamp)
                )
                event_id = cursor.lastrowid
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"[AdaptivePersonMemory] Database log evolution event error: {e}")
            return 0

        # Broadcast update on Blackboard
        try:
            from skills.blackboard import AriaBlackboard
            blackboard = AriaBlackboard()
            event_payload = {
                "event_id": event_id,
                "event_type": event_type,
                "entity_name": name,
                "confidence": confidence,
                "timestamp": timestamp
            }
            blackboard.publish(
                topic="vision",
                key=f"timeline_event_{event_id}",
                value=event_payload,
                source="AdaptivePersonMemory",
                ttl_hours=24
            )
        except Exception as e:
            print(f"[AdaptivePersonMemory] Blackboard broadcast error: {e}")

        return event_id
