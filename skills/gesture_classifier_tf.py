"""
skills/gesture_classifier_tf.py — TensorFlow Hand Landmark Gesture MLP Classifier for ARIA
========================================================================================
Translates raw 21 MediaPipe hand landmarks (63 features) into scale-invariant, translation-invariant
inputs, and feeds them into a trained Keras MLP to classify gestures.
"""

import os
import numpy as np

try:
    import tensorflow as tf
    from tensorflow.keras.models import Sequential, load_model
    from tensorflow.keras.layers import Dense, Dropout, BatchNormalization
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False


class AriaGestureClassifierTF:
    CLASSES = ["OK_SIGN", "FIST", "V_SIGN", "L_SIGN", "UNKNOWN"]

    def __init__(self, model_path: str = "models/gesture_classifier.h5"):
        self.model_path = model_path
        self.model = None
        self.load()

    def load(self) -> bool:
        """Loads the gesture classifier model from disk."""
        if not TF_AVAILABLE:
            return False

        if os.path.exists(self.model_path):
            try:
                self.model = load_model(self.model_path)
                print(f"[GestureClassifierTF] Loaded custom MLP model: {self.model_path}")
                return True
            except Exception as e:
                print(f"[GestureClassifierTF] Error loading model: {e}")
                
        # If no model found, we will initialize a default architecture
        self.model = self._build_default_model()
        return False

    def _build_default_model(self):
        """Creates a default gesture classifier MLP structure."""
        if not TF_AVAILABLE:
            return None
        model = Sequential([
            Dense(64, input_shape=(63,), activation='relu'),
            BatchNormalization(),
            Dropout(0.2),
            Dense(32, activation='relu'),
            BatchNormalization(),
            Dropout(0.2),
            Dense(len(self.CLASSES), activation='softmax')
        ])
        model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])
        return model

    @staticmethod
    def normalize_landmarks(landmarks) -> list:
        """
        Translates wrist (landmark 0) to origin and scales all landmarks uniformly.
        Accepts landmarks as a list of objects with x, y, z attributes.
        Returns a flat list of 63 normalized coordinates.
        """
        if not landmarks or len(landmarks) < 21:
            return [0.0] * 63

        # 1. Translate wrist to (0, 0, 0)
        wrist = landmarks[0]
        translated = []
        for lm in landmarks:
            translated.append([lm.x - wrist.x, lm.y - wrist.y, lm.z - wrist.z])

        # 2. Find max distance from wrist to determine scale factor
        max_dist = 0.001
        for pt in translated:
            dist = np.linalg.norm(pt)
            if dist > max_dist:
                max_dist = dist

        # 3. Scale uniformly
        normalized = []
        for pt in translated:
            normalized.extend([pt[0] / max_dist, pt[1] / max_dist, pt[2] / max_dist])

        return normalized

    def predict(self, landmarks) -> tuple:
        """
        Predicts gesture class.
        Returns a tuple: (class_label: str, confidence: float)
        """
        if not TF_AVAILABLE or self.model is None or not os.path.exists(self.model_path):
            return "UNKNOWN", 0.0

        try:
            flat_features = self.normalize_landmarks(landmarks)
            x = np.array([flat_features], dtype=np.float32)
            
            # Predict
            predictions = self.model.predict(x, verbose=0)[0]
            best_idx = int(np.argmax(predictions))
            best_conf = float(predictions[best_idx])
            
            return self.CLASSES[best_idx], best_conf
        except Exception as e:
            print(f"[GestureClassifierTF] Prediction error: {e}")
            return "UNKNOWN", 0.0
