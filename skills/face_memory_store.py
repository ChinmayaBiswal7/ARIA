"""
skills/face_memory_store.py — Persistent FAISS-backed Face Vector Store for ARIA
=============================================================================
Manages local face embeddings index using FAISS L2 distance flat indexes.
Allows zero-retraining registration of new people and profile updates.
"""

import os
import json
import numpy as np

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False


class AriaFaceMemoryStore:
    def __init__(self, db_dir: str = "data/face_memory", dimension: int = 1280):
        self.db_dir = db_dir
        self.dimension = dimension
        self.index_path = os.path.join(self.db_dir, "face_index.faiss")
        self.metadata_path = os.path.join(self.db_dir, "face_metadata.json")
        
        self.index = None
        self.metadata = []  # list of dicts mapping index IDs to details e.g., [{"name": "Chinmaya", "timestamp": 12345}]
        
        # Ensure directories exist
        if not os.path.exists(self.db_dir):
            os.makedirs(self.db_dir, exist_ok=True)

        self.load()

    def load(self) -> bool:
        """Loads FAISS index and metadata mappings from disk."""
        if not FAISS_AVAILABLE:
            print("[FaceMemoryStore] FAISS not available. Vector store disabled.")
            return False

        try:
            # Load metadata mapping
            if os.path.exists(self.metadata_path):
                with open(self.metadata_path, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
            else:
                self.metadata = []

            # Load index
            if os.path.exists(self.index_path):
                self.index = faiss.read_index(self.index_path)
                print(f"[FaceMemoryStore] Loaded FAISS index containing {self.index.ntotal} faces.")
            else:
                self.index = faiss.IndexFlatL2(self.dimension)
                print(f"[FaceMemoryStore] Created new empty FAISS index (dimension: {self.dimension}).")
            return True
        except Exception as e:
            print(f"[FaceMemoryStore] Load error: {e}")
            self.index = faiss.IndexFlatL2(self.dimension)
            self.metadata = []
            return False

    def save(self) -> bool:
        """Saves current FAISS index and metadata map to disk."""
        if not FAISS_AVAILABLE or self.index is None:
            return False

        try:
            # Save metadata
            with open(self.metadata_path, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, indent=2)

            # Save FAISS index
            faiss.write_index(self.index, self.index_path)
            return True
        except Exception as e:
            print(f"[FaceMemoryStore] Save error: {e}")
            return False

    def add_face(self, name: str, embedding: list) -> bool:
        """Adds a new face embedding to the store and commits to disk."""
        if not FAISS_AVAILABLE or self.index is None or embedding is None:
            return False

        try:
            if len(embedding) != self.dimension:
                print(f"[FaceMemoryStore] Error: Embedding size mismatch. Expected {self.dimension}, got {len(embedding)}")
                return False

            import time
            # Convert embedding to numpy array
            vector = np.array([embedding], dtype=np.float32)
            
            # Add to FAISS index
            self.index.add(vector)
            
            # Add to metadata
            self.metadata.append({
                "name": name,
                "timestamp": int(time.time())
            })
            
            # Commit changes
            self.save()
            print(f"[FaceMemoryStore] Successfully added new face angle for '{name}' to index.")
            return True
        except Exception as e:
            print(f"[FaceMemoryStore] Error adding face: {e}")
            return False

    def search_face(self, embedding: list, threshold: float = 0.50, k: int = 5) -> dict:
        """
        Searches the FAISS index for the closest matching face embedding.
        Returns a dict: {"name": str, "confidence": float, "matches": list}
        """
        if not FAISS_AVAILABLE or self.index is None or embedding is None or self.index.ntotal == 0:
            return {"name": "Unknown", "confidence": 0.0, "matches": []}

        try:
            vector = np.array([embedding], dtype=np.float32)
            distances, indices = self.index.search(vector, k)
            
            matches = []
            for i, idx in enumerate(indices[0]):
                if idx != -1 and idx < len(self.metadata):
                    meta = self.metadata[idx]
                    # Convert L2 distance to confidence score mapping (where 0.0 distance -> 1.0 confidence)
                    # For normalized vectors, L2 distance is in range [0, 2]
                    dist = float(distances[0][i])
                    confidence = max(0.0, 1.0 - (dist / 2.0))
                    
                    matches.append({
                        "name": meta["name"],
                        "confidence": confidence,
                        "distance": dist,
                        "timestamp": meta["timestamp"]
                    })
            
            if not matches:
                return {"name": "Unknown", "confidence": 0.0, "matches": []}

            # Aggregate scores per name to find best consensus
            scores = {}
            for match in matches:
                name = match["name"]
                scores[name] = scores.get(name, 0.0) + match["confidence"]

            best_name = max(scores, key=scores.get)
            best_matches = [m for m in matches if m["name"] == best_name]
            best_confidence = best_matches[0]["confidence"] if best_matches else 0.0

            # If top match confidence is below standard user threshold, label as Unknown
            if best_confidence < threshold:
                return {"name": "Unknown", "confidence": best_confidence, "matches": matches}

            return {"name": best_name, "confidence": best_confidence, "matches": matches}

        except Exception as e:
            print(f"[FaceMemoryStore] Face search error: {e}")
            return {"name": "Unknown", "confidence": 0.0, "matches": []}

    def clear(self):
        """Clears all vectors and metadata in the store."""
        if not FAISS_AVAILABLE:
            return
        self.index = faiss.IndexFlatL2(self.dimension)
        self.metadata = []
        self.save()
        print("[FaceMemoryStore] Index and metadata cleared successfully.")

    def get_all_vectors_for_name(self, name: str) -> list:
        """Reconstructs all registered vectors for a specific person from the FAISS index."""
        if not FAISS_AVAILABLE or self.index is None:
            return []
        
        vectors = []
        name_lower = name.lower().strip()
        for idx, meta in enumerate(self.metadata):
            if meta["name"].lower().strip() == name_lower:
                try:
                    vector = self.index.reconstruct(idx)
                    vectors.append(np.array(vector, dtype=np.float32))
                except Exception as e:
                    print(f"[FaceMemoryStore] Vector reconstruction error for index {idx}: {e}")
        return vectors
