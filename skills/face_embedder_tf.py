"""
skills/face_embedder_tf.py — TensorFlow MobileNetV2-based Face Embedding Extractor for ARIA
========================================================================================
Extracts robust 1280-dimensional face embeddings using a local pre-trained MobileNetV2
feature extraction network. Extremely robust to lighting changes, expressions, and angles.
"""

import os
import cv2
import numpy as np

try:
    import tensorflow as tf
    from tensorflow.keras.applications.mobilenet_v2 import MobileNetV2, preprocess_input
    from tensorflow.keras.models import Model
    from tensorflow.keras.layers import GlobalAveragePooling2D
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False


class AriaFaceEmbedderTF:
    _model_instance = None
    _lock_model = True

    def __init__(self, debug_mode=False):
        self.debug_mode = debug_mode
        self._init_tf_model()

    @property
    def face_cascade(self):
        try:
            return cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        except Exception:
            return None

    def _init_tf_model(self):
        """Lazy loads the pre-trained MobileNetV2 model once to conserve memory."""
        if not TF_AVAILABLE:
            print("[FaceEmbedderTF] WARNING: TensorFlow not available. Embedding generation will be disabled.")
            return

        if AriaFaceEmbedderTF._model_instance is None:
            try:
                # Load pre-trained MobileNetV2 without dense classifier head
                base_model = MobileNetV2(
                    input_shape=(96, 96, 3),
                    include_top=False,
                    weights='imagenet',
                    pooling='avg'
                )
                AriaFaceEmbedderTF._model_instance = base_model
                print("[FaceEmbedderTF] Pre-trained MobileNetV2 face feature model initialized.")
            except Exception as e:
                print(f"[FaceEmbedderTF] Failed to load MobileNetV2 weights: {e}")
                AriaFaceEmbedderTF._model_instance = None

    def extract_face_crop(self, image_array, is_already_cropped=False) -> np.ndarray:
        """Detects the largest face crop and returns as a BGR image."""
        if image_array is None or not hasattr(image_array, "shape") or len(image_array.shape) < 2:
            return None

        # Convert to grayscale for Haar Cascades
        if len(image_array.shape) == 3:
            gray = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
            bgr = image_array
        else:
            gray = image_array
            bgr = cv2.cvtColor(image_array, cv2.COLOR_GRAY2BGR)

        h, w = gray.shape[:2]
        if w < 40 or h < 40:
            return None

        if is_already_cropped:
            # If already cropped, convert crop back to color if grayscale
            if len(image_array.shape) == 2:
                return cv2.cvtColor(image_array, cv2.COLOR_GRAY2BGR)
            return image_array

        cascade = self.face_cascade
        if cascade is None or cascade.empty():
            return None

        try:
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
        except Exception as e:
            print(f"[FaceEmbedderTF] Face detection error: {e}")
            return None

        if faces is None or len(faces) == 0:
            return None

        # Grab largest face region
        faces = sorted(faces, key=lambda x: x[2] * x[3], reverse=True)
        x, y, fw, fh = faces[0]
        return bgr[y:y+fh, x:x+fw]

    def get_embedding(self, image_array, is_already_cropped=False) -> list:
        """Generates a 1280-dimensional L2-normalized feature embedding vector."""
        if not TF_AVAILABLE or AriaFaceEmbedderTF._model_instance is None:
            return None

        face_crop = self.extract_face_crop(image_array, is_already_cropped=is_already_cropped)
        if face_crop is None:
            return None

        try:
            # Resize to 96x96 expected by MobileNetV2
            resized = cv2.resize(face_crop, (96, 96), interpolation=cv2.INTER_AREA)
            
            # Convert to float and preprocess (normalize pixels using ImageNet standards)
            x = np.expand_dims(resized.astype(np.float32), axis=0)
            x = preprocess_input(x)

            # Extract feature vector: shape (1, 1280)
            features = AriaFaceEmbedderTF._model_instance.predict(x, verbose=0)[0]

            # L2 normalize so cosine similarity equals dot product
            norm = np.linalg.norm(features)
            if norm > 0:
                features = features / norm

            if self.debug_mode:
                print("[FaceEmbedderTF] Feature embedding generated successfully.")
            return features.tolist()

        except Exception as e:
            print(f"[FaceEmbedderTF] Embedding generation error: {e}")
            return None
