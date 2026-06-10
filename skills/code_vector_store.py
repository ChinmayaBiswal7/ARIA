import os
import json
from typing import List, Dict, Any

try:
    import numpy as np
    import faiss
except ImportError:
    np = None
    faiss = None

class AriaCodeVectorStore:
    def __init__(self, db_dir: str = "data"):
        self.db_dir = db_dir
        self.index_file = os.path.join(db_dir, "code_index.faiss")
        self.meta_file = os.path.join(db_dir, "code_metadata.json")
        self.symbols_file = os.path.join(db_dir, "code_symbols.json")
        self.registry_file = os.path.join(db_dir, "code_file_registry.json")
        
        self.index = None
        self.chunk_store: List[Dict[str, Any]] = []
        self.symbol_index: Dict[str, str] = {}
        self.registry: Dict[str, Dict[str, Any]] = {}
        
        # Ensure database directory exists
        if not os.path.exists(self.db_dir):
            os.makedirs(self.db_dir)
            
        if faiss is not None:
            self.index = faiss.IndexFlatL2(384)

    def load_store(self) -> bool:
        """Loads index, chunks, symbols, and registry from disk."""
        if faiss is None:
            return False
            
        try:
            # Load registry
            if os.path.exists(self.registry_file):
                with open(self.registry_file, "r", encoding="utf-8") as f:
                    self.registry = json.load(f)
                    
            # Load chunk store
            if os.path.exists(self.meta_file):
                with open(self.meta_file, "r", encoding="utf-8") as f:
                    self.chunk_store = json.load(f)
                    
            # Load symbols
            if os.path.exists(self.symbols_file):
                with open(self.symbols_file, "r", encoding="utf-8") as f:
                    self.symbol_index = json.load(f)
                    
            # Load FAISS index
            if os.path.exists(self.index_file):
                self.index = faiss.read_index(self.index_file)
                print(f"[CodeVectorStore] FAISS code index loaded with {self.index.ntotal} vectors.")
                return True
            else:
                self.index = faiss.IndexFlatL2(384)
                print("[CodeVectorStore] Created a new empty FAISS L2 flat code index.")
                return True
        except Exception as e:
            print(f"[CodeVectorStore] Error loading database: {e}")
            return False

    def serialize_store(self) -> bool:
        """Saves current index, registry, chunks, and symbols to disk."""
        if faiss is None or self.index is None:
            return False
            
        try:
            # Save registry
            with open(self.registry_file, "w", encoding="utf-8") as f:
                json.dump(self.registry, f, indent=2)
                
            # Save chunks
            with open(self.meta_file, "w", encoding="utf-8") as f:
                json.dump(self.chunk_store, f, indent=2)
                
            # Save symbols
            with open(self.symbols_file, "w", encoding="utf-8") as f:
                json.dump(self.symbol_index, f, indent=2)
                
            # Save FAISS index
            faiss.write_index(self.index, self.index_file)
            print(f"[CodeVectorStore] Saved FAISS code index with {self.index.ntotal} vectors.")
            return True
        except Exception as e:
            print(f"[CodeVectorStore] Error saving database: {e}")
            return False

    def add_nodes(self, new_nodes: List[Dict[str, Any]], embeddings: List[List[float]]):
        """Adds nodes and caches their embeddings inside the chunk store."""
        # Append new nodes with embeddings attached
        for i, node in enumerate(new_nodes):
            node["embedding"] = embeddings[i]
            self.chunk_store.append(node)
            
            # Map symbol index
            n_type = node.get("type")
            n_name = node.get("name")
            if n_type in ("CLASS", "FUNCTION", "ASYNC_FUNCTION"):
                self.symbol_index[n_name] = node["file"]
            elif n_type == "METHOD":
                self.symbol_index[f"{node['class']}.{n_name}"] = node["file"]

    def remove_file_nodes(self, rel_path: str):
        """Removes all nodes matching a specific file relative path from chunks and symbol index."""
        # Filter chunks
        self.chunk_store = [c for c in self.chunk_store if c["file"] != rel_path]
        
        # Clean symbol index
        self.symbol_index = {k: v for k, v in self.symbol_index.items() if v != rel_path}

    def rebuild_faiss_index(self):
        """Rebuilds the FAISS index in memory using cached chunk embeddings."""
        if faiss is None or np is None:
            return
            
        self.index = faiss.IndexFlatL2(384)
        # Filter out nodes without embeddings (e.g. FILE_DEPS)
        embeddable_nodes = [c for c in self.chunk_store if "embedding" in c]
        if not embeddable_nodes:
            return
            
        try:
            embeddings_np = np.array([c["embedding"] for c in embeddable_nodes], dtype=np.float32)
            self.index.add(embeddings_np)
            print(f"[CodeVectorStore] Rebuilt FAISS code index with {self.index.ntotal} vectors.")
        except Exception as e:
            print(f"[CodeVectorStore] Rebuild code index error: {e}")

    def search_code(self, query_embedding: List[float], k: int = 3) -> List[Dict[str, Any]]:
        """Searches the nearest AST nodes using vector search."""
        if self.index is None or not self.chunk_store or np is None:
            return []
            
        try:
            # Filter chunk store to get map from FAISS index index back to chunk index
            embeddable_nodes = [c for c in self.chunk_store if "embedding" in c]
            if not embeddable_nodes:
                return []
                
            query_vector = np.array([query_embedding], dtype=np.float32)
            distances, indices = self.index.search(query_vector, k)
            
            results = []
            for i, idx in enumerate(indices[0]):
                if idx != -1 and idx < len(embeddable_nodes):
                    chunk = embeddable_nodes[idx].copy()
                    if "embedding" in chunk:
                        del chunk["embedding"]
                    chunk["score"] = float(distances[0][i])
                    results.append(chunk)
            return results
        except Exception as e:
            print(f"[CodeVectorStore] Search code error: {e}")
            return []

    def lookup_symbol(self, symbol_name: str) -> str:
        """Instant exact lookup matching class, function, or class.method name."""
        return self.symbol_index.get(symbol_name, "")
