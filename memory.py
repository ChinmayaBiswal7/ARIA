import json
import os
import cv2
import numpy as np
import time

FACE_REC_AVAILABLE = True

class FaceMemory:
    """
    Manages face recognition memory completely offline.
    Uses zero-dependency FaceEmbedder and MemoryManager to persist embeddings in SQLite and Firebase.
    """

    def __init__(self, memory_dir="face_memory"):
        from skills.memory_manager import MemoryManager
        self.memory_manager = MemoryManager()
        # No shared face_cascade to prevent cross-thread C++ crashes
        pass

    @property
    def face_cascade(self):
        try:
            return cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        except Exception:
            return None

    def detect_faces(self, gray, scale_factor=1.3, min_neighbors=5, min_size=(30, 30)):
        try:
            cascade = self.face_cascade
            if cascade is None or cascade.empty():
                return []
            return cascade.detectMultiScale(gray, scaleFactor=scale_factor, minNeighbors=min_neighbors, minSize=min_size)
        except Exception as e:
            print(f"[FaceMemory] Face detection error: {e}")
            return []

    def add_face(self, name, image_array=None, embedding=None):
        return self.memory_manager.save_face_embedding(name, image_array, embedding)

    def identify_face(self, image_array):
        return self.memory_manager.identify_user(image_array)

    def forget(self, name):
        normalized_user = name.strip().strip('.').lower()
        if normalized_user in self.memory_manager.known_faces:
            del self.memory_manager.known_faces[normalized_user]
            # SQLite delete
            try:
                import sqlite3
                conn = sqlite3.connect(self.memory_manager.db_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM face_embeddings WHERE username = ?", (normalized_user,))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"[FaceMemory] SQLite delete error: {e}")
            # Firebase delete
            if self.memory_manager.firestore:
                try:
                    self.memory_manager.firestore.collection("faces").document(normalized_user).delete()
                except Exception as e:
                    print(f"[FaceMemory] Firebase delete error: {e}")
            # ChromaDB delete
            if self.memory_manager.vector_mem.faces_collection:
                try:
                    self.memory_manager.vector_mem.faces_collection.delete(ids=[normalized_user])
                    print(f"[FaceMemory] Deleted '{normalized_user}' face embedding from ChromaDB.")
                except Exception as e:
                    print(f"[FaceMemory] ChromaDB face delete error: {e}")
            return True
        return False

    def list_known(self):
        return list(self.memory_manager.known_faces.keys())
