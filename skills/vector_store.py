import os
import json
import hashlib
import time
from typing import List, Dict, Any

try:
    import numpy as np
    import faiss
except ImportError:
    np = None
    faiss = None

class AriaVectorStore:
    def __init__(self, db_dir: str = "data/knowledge_vault"):
        self.db_dir = db_dir
        self.index_path = os.path.join(db_dir, "index.faiss")
        self.chunks_path = os.path.join(db_dir, "chunk_store.json")
        self.registry_path = os.path.join(db_dir, "file_registry.json")
        
        self.index = None
        self.chunks: List[Dict[str, Any]] = []
        self.registry: Dict[str, Dict[str, Any]] = {}
        
        # Ensure directories exist
        if not os.path.exists(self.db_dir):
            os.makedirs(self.db_dir)

    def load(self) -> bool:
        """Loads index, chunks, and file registry from disk."""
        if faiss is None or np is None:
            return False
            
        try:
            # Load registry
            if os.path.exists(self.registry_path):
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    self.registry = json.load(f)
                    
            # Load chunks
            if os.path.exists(self.chunks_path):
                with open(self.chunks_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.chunks = data.get("chunks", [])
                    
            # Load FAISS index
            if os.path.exists(self.index_path):
                self.index = faiss.read_index(self.index_path)
                print(f"[VectorStore] FAISS index loaded with {self.index.ntotal} vectors.")
                return True
            else:
                self.index = faiss.IndexFlatL2(384)
                print("[VectorStore] Created a new empty FAISS L2 flat index.")
                return True
        except Exception as e:
            print(f"[VectorStore] Error loading database: {e}")
            return False

    def save(self) -> bool:
        """Saves current state, FAISS index, and registry to disk."""
        if faiss is None or self.index is None:
            return False
            
        try:
            # Save registry
            with open(self.registry_path, "w", encoding="utf-8") as f:
                json.dump(self.registry, f, indent=2)
                
            # Save chunks
            with open(self.chunks_path, "w", encoding="utf-8") as f:
                json.dump({"chunks": self.chunks}, f, indent=2)
                
            # Save FAISS index
            faiss.write_index(self.index, self.index_path)
            print(f"[VectorStore] Saved FAISS index with {self.index.ntotal} vectors.")
            return True
        except Exception as e:
            print(f"[VectorStore] Error saving database: {e}")
            return False

    def get_file_hash(self, file_path: str) -> str:
        """Computes MD5 hash of file content."""
        hasher = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                buf = f.read(65536)
                while len(buf) > 0:
                    hasher.update(buf)
                    buf = f.read(65536)
            return hasher.hexdigest()
        except Exception as e:
            print(f"[VectorStore] Hash error for {file_path}: {e}")
            return ""

    def update_index_from_chunks(self):
        """Rebuilds the FAISS L2 index in memory using current list of chunks and their cached embeddings."""
        if faiss is None or np is None:
            return
            
        self.index = faiss.IndexFlatL2(384)
        if not self.chunks:
            return
            
        try:
            embeddings_np = np.array([c["embedding"] for c in self.chunks], dtype=np.float32)
            self.index.add(embeddings_np)
            print(f"[VectorStore] Rebuilt FAISS index with {self.index.ntotal} chunks.")
        except Exception as e:
            print(f"[VectorStore] Rebuild index error: {e}")

    def add_document_chunks(self, file_path: str, new_chunks: List[Dict[str, Any]], embeddings: List[List[float]]):
        """Adds or updates chunks for a specific file, caching embeddings inside the JSON store."""
        basename = os.path.basename(file_path)
        
        # Remove existing chunks for this file
        self.chunks = [c for c in self.chunks if c["source"] != basename]
        
        # Add new chunks with embeddings attached
        for i, chunk in enumerate(new_chunks):
            chunk["embedding"] = embeddings[i]
            self.chunks.append(chunk)

    def remove_document(self, file_path: str):
        """Removes a document and its chunks from index and registry."""
        basename = os.path.basename(file_path)
        self.chunks = [c for c in self.chunks if c["source"] != basename]
        if basename in self.registry:
            del self.registry[basename]

    def search(self, query_embedding: List[float], k=4) -> List[Dict[str, Any]]:
        """Finds top k nearest neighbors for query embedding."""
        if self.index is None or not self.chunks or np is None:
            return []
            
        try:
            query_vector = np.array([query_embedding], dtype=np.float32)
            distances, indices = self.index.search(query_vector, k)
            
            results = []
            for i, idx in enumerate(indices[0]):
                if idx != -1 and idx < len(self.chunks):
                    chunk = self.chunks[idx].copy()
                    # Exclude raw float list from search results to keep prints clean
                    if "embedding" in chunk:
                        del chunk["embedding"]
                    chunk["score"] = float(distances[0][i])
                    results.append(chunk)
            return results
        except Exception as e:
            print(f"[VectorStore] Search query error: {e}")
            return []
