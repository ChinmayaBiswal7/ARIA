import os
import json
import sqlite3
import numpy as np
import threading

class DummyEmbeddingFunction:
    def __call__(self, input):
        return [[] for _ in input]
    def name(self):
        return "default"


class VectorMemory:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(VectorMemory, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, db_path="aria_memory.db"):
        if self._initialized:
            return
        self.db_path = db_path
        self.model = None
        self._model_lock = threading.Lock()
        
        self.chroma_client = None
        self.memories_collection = None
        self.faces_collection = None
        
        self._init_db()
        self._init_chroma()
        self._initialized = True

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS semantic_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text_content TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                category TEXT,
                metadata TEXT
            )
        """)
        conn.commit()
        conn.close()

    def _init_chroma(self):
        try:
            import chromadb
            # Create a persistent directory for ChromaDB
            chroma_dir = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "chroma_db")
            self.chroma_client = chromadb.PersistentClient(path=chroma_dir)
            # Create or get semantic memories collection
            # Cosine space is optimal for cosine similarity comparison
            self.memories_collection = self.chroma_client.get_or_create_collection(
                name="aria_memories",
                metadata={"hnsw:space": "cosine"}
            )
            # Create or get face embeddings collection
            self.faces_collection = self.chroma_client.get_or_create_collection(
                name="aria_faces",
                embedding_function=DummyEmbeddingFunction(),
                metadata={"hnsw:space": "cosine"}
            )
            print("[VectorMemory] ChromaDB persistent client and collections initialized.")
        except Exception as e:
            print(f"[VectorMemory] Failed to initialize ChromaDB: {e}")

    def _lazy_init(self):
        with self._model_lock:
            if self.model is None:
                try:
                    # Load sentence-transformers in a thread-safe manner as a fallback
                    from sentence_transformers import SentenceTransformer
                    self.model = SentenceTransformer('all-MiniLM-L6-v2')
                    print("[VectorMemory] Local sentence-transformer loaded.")
                except Exception as e:
                    # Don't print huge error stack, just note that it failed
                    pass

    def add_memory(self, text, category="general", metadata=None):
        """
        Add a semantic memory. Saves to ChromaDB for fast vector search,
        and SQLite for persistent structured logging/backup.
        """
        # 1. Save to ChromaDB
        chroma_success = False
        if self.memories_collection:
            try:
                import uuid
                doc_id = str(uuid.uuid4())
                meta = {"category": category}
                if metadata:
                    for k, v in metadata.items():
                        # ChromaDB metadata values must be simple types: str, int, float, bool
                        if isinstance(v, (str, int, float, bool)):
                            meta[k] = v
                        else:
                            meta[k] = str(v)
                
                self.memories_collection.add(
                    documents=[text.strip()],
                    metadatas=[meta],
                    ids=[doc_id]
                )
                chroma_success = True
            except Exception as e:
                print(f"[VectorMemory] ChromaDB add error: {e}")

        # 2. Save to SQLite (as backup / structured logger)
        self._lazy_init()
        vector = []
        if self.model:
            try:
                vector = self.model.encode(text).tolist()
            except Exception as e:
                print(f"[VectorMemory] Local encoding failed: {e}")
            
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO semantic_embeddings (text_content, embedding_json, category, metadata) VALUES (?, ?, ?, ?)",
                (text.strip(), json.dumps(vector), category, json.dumps(metadata or {}))
            )
            conn.commit()
            conn.close()
            sqlite_success = True
        except Exception as e:
            print(f"[VectorMemory] SQLite add error: {e}")
            sqlite_success = False

        return chroma_success or sqlite_success

    def semantic_search(self, query, limit=3):
        """
        Perform semantic search using ChromaDB. Falls back to SQLite cosine similarity
        or keyword overlap search if ChromaDB is unavailable.
        """
        # 1. Try ChromaDB semantic search first
        if self.memories_collection:
            try:
                results = self.memories_collection.query(
                    query_texts=[query],
                    n_results=limit
                )
                hits = []
                if results and 'documents' in results and results['documents']:
                    docs = results['documents'][0]
                    ids = results['ids'][0]
                    distances = results['distances'][0] if 'distances' in results else [0.0] * len(docs)
                    metadatas = results['metadatas'][0] if 'metadatas' in results else [{}] * len(docs)
                    
                    for i in range(len(docs)):
                        # Cosine distance = distance
                        # Cosine similarity = 1.0 - distance
                        sim = 1.0 - distances[i]
                        text = docs[i]
                        meta = metadatas[i] or {}
                        cat = meta.get("category", "general")
                        hits.append((sim, text, cat))
                return hits
            except Exception as e:
                print(f"[VectorMemory] ChromaDB query failed: {e}. Falling back...")

        # 2. SQLite / local model fallback search
        self._lazy_init()
        
        # Fallback to Keyword Search if model is offline or has no encoding capability
        if not self.model:
            try:
                results = []
                query_words = set(query.lower().split())
                if not query_words:
                    return []
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT text_content, category FROM semantic_embeddings")
                rows = cursor.fetchall()
                conn.close()
                
                for text, cat in rows:
                    text_words = set(text.lower().split())
                    overlap = len(query_words.intersection(text_words))
                    if overlap > 0:
                        sim = overlap / float(len(query_words) + len(text_words) - overlap)
                        results.append((sim, text, cat))
                results.sort(key=lambda x: x[0], reverse=True)
                return results[:limit]
            except Exception as e:
                print(f"[VectorMemory] Keyword fallback search error: {e}")
                return []

        try:
            query_vector = np.array(self.model.encode(query))
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT text_content, embedding_json, category FROM semantic_embeddings")
            rows = cursor.fetchall()
            conn.close()

            results = []
            for text, emb_json, cat in rows:
                emb_list = json.loads(emb_json)
                if not emb_list:  # Skip cached empty fallback embeddings
                    continue
                emb = np.array(emb_list)
                if query_vector.shape != emb.shape:
                    continue
                sim = np.dot(query_vector, emb) / (np.linalg.norm(query_vector) * np.linalg.norm(emb) + 1e-9)
                results.append((sim, text, cat))

            # Sort by similarity descending
            results.sort(key=lambda x: x[0], reverse=True)
            return results[:limit]
        except Exception as e:
            print(f"[VectorMemory] SQLite/local search error: {e}")
            return []
