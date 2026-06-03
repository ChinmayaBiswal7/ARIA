"""
face_embedder.py — Zero-dependency face embedding extractor for ARIA
=====================================================================
Uses OpenCV and NumPy to extract normalized face embeddings.
Allows robust face recognition without heavy C++ libraries like dlib or deepface.
"""

import cv2
import numpy as np

class FaceEmbedder:
    def __init__(self, debug_mode=False):
        # No shared face_cascade to prevent cross-thread C++ crashes
        self.debug_mode = debug_mode

    @property
    def face_cascade(self):
        try:
            return cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        except Exception:
            return None

    def extract_face_roi(self, image_array, is_already_cropped=False):
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

        if is_already_cropped:
            face_crop = gray
        else:
            # Detect faces
            try:
                cascade = self.face_cascade
                if cascade is None or cascade.empty():
                    return None
                faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
            except cv2.error as e:
                print(f"[FaceEmbedder] OpenCV face detection error: {e}")
                return None
            except Exception as e:
                print(f"[FaceEmbedder] Unexpected face detection error: {e}")
                return None

            if faces is None or len(faces) == 0:
                if self.debug_mode:
                    # Print diagnostics
                    print(f"[FaceRec/Diagnostics] Faces detected: 0 | Frame size: {gray.shape} | Brightness: {gray.mean():.1f}")
                    # Save a failed frame to disk to inspect what is seen
                    try:
                        import os, time
                        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        out_dir = os.path.join(base_dir, "failed_face_frames")
                        os.makedirs(out_dir, exist_ok=True)
                        # Clean up old files if they exceed 10 to protect disk space
                        existing_files = sorted(
                            [os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.startswith("failed_face_") and f.endswith(".jpg")],
                            key=os.path.getmtime
                        )
                        while len(existing_files) >= 10:
                            try:
                                os.remove(existing_files.pop(0))
                            except Exception:
                                pass
                        img_path = os.path.join(out_dir, f"failed_face_{int(time.time() * 1000)}.jpg")
                        cv2.imwrite(img_path, image_array)
                        print(f"[FaceRec/Diagnostics] Saved failed face frame to: {img_path}")
                    except Exception as save_err:
                        print(f"[FaceRec/Diagnostics] Failed to save failed frame: {save_err}")
                return None

            # Print diagnostics on success
            if self.debug_mode:
                print(f"[FaceRec/Diagnostics] Faces detected: {len(faces)} | Frame size: {gray.shape} | Brightness: {gray.mean():.1f}")

            # Select the largest face detected
            faces = sorted(faces, key=lambda x: x[2] * x[3], reverse=True)
            x, y, w, h = faces[0]
            face_crop = gray[y:y+h, x:x+w]

        # Resize to fixed size for uniform features
        face_resized = cv2.resize(face_crop, (64, 64), interpolation=cv2.INTER_AREA)

        # Equalize histogram to make it robust to lighting changes
        face_equalized = cv2.equalizeHist(face_resized)

        return face_equalized

    def get_embedding(self, image_array, is_already_cropped=False):
        """Extract a 4096-dimensional normalized vector representation of the face."""
        face_roi = self.extract_face_roi(image_array, is_already_cropped=is_already_cropped)
        if face_roi is None:
            if self.debug_mode:
                print(f"[FaceRec] Detection failed (cropped={is_already_cropped})")
            return None

        # Normalize pixel values to range [0, 1]
        flat_vector = face_roi.flatten().astype(np.float32) / 255.0

        # L2 normalize the vector so that dot product equals cosine similarity
        norm = np.linalg.norm(flat_vector)
        if norm > 0:
            flat_vector = flat_vector / norm

        if self.debug_mode:
            print(f"[FaceRec] Embedding generated (cropped={is_already_cropped})")
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
