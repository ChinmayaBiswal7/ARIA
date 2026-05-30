"""
face_embedder.py — Zero-dependency face embedding extractor for ARIA
=====================================================================
Uses OpenCV and NumPy to extract normalized face embeddings.
Allows robust face recognition without heavy C++ libraries like dlib or deepface.
"""

import cv2
import numpy as np

class FaceEmbedder:
    def __init__(self):
        # No shared face_cascade to prevent cross-thread C++ crashes
        pass

    @property
    def face_cascade(self):
        try:
            return cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        except Exception:
            return None

    def extract_face_roi(self, image_array):
        """Detect face, crop it, resize to 64x64, equalize histogram, and normalize."""
        if image_array is None or not hasattr(image_array, "shape") or len(image_array.shape) < 2:
            return None

        # Convert to grayscale
        if len(image_array.shape) == 3:
            gray = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
        else:
            gray = image_array

        h, w = gray.shape[:2]
        if w < 40 or h < 40:
            return None

        # Detect faces
        try:
            cascade = self.face_cascade
            if cascade is None or cascade.empty():
                return None
            faces = cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(40, 40))
        except cv2.error as e:
            print(f"[FaceEmbedder] OpenCV face detection error: {e}")
            return None
        except Exception as e:
            print(f"[FaceEmbedder] Unexpected face detection error: {e}")
            return None
        if faces is None or len(faces) == 0:
            return None

        # Select the largest face detected
        faces = sorted(faces, key=lambda x: x[2] * x[3], reverse=True)
        x, y, w, h = faces[0]
        face_crop = gray[y:y+h, x:x+w]

        # Resize to fixed size for uniform features
        face_resized = cv2.resize(face_crop, (64, 64), interpolation=cv2.INTER_AREA)

        # Equalize histogram to make it robust to lighting changes
        face_equalized = cv2.equalizeHist(face_resized)

        return face_equalized

    def get_embedding(self, image_array):
        """Extract a 4096-dimensional normalized vector representation of the face."""
        face_roi = self.extract_face_roi(image_array)
        if face_roi is None:
            return None

        # Normalize pixel values to range [0, 1]
        flat_vector = face_roi.flatten().astype(np.float32) / 255.0

        # L2 normalize the vector so that dot product equals cosine similarity
        norm = np.linalg.norm(flat_vector)
        if norm > 0:
            flat_vector = flat_vector / norm

        return flat_vector.tolist()

    @staticmethod
    def cosine_similarity(v1, v2):
        """Calculate cosine similarity between two vector lists."""
        a = np.array(v1)
        b = np.array(v2)
        dot_product = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot_product / (norm_a * norm_b))
