import threading
try:
    import numpy as np
    from sentence_transformers import SentenceTransformer
except ImportError:
    np = None
    SentenceTransformer = None

class AriaEmbeddingEngine:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AriaEmbeddingEngine, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.model = None
        self._model_lock = threading.Lock()
        self._initialized = True

    def _lazy_init(self):
        """Thread-safe lazy initialization of the sentence transformer model."""
        with self._model_lock:
            if self.model is None and SentenceTransformer is not None:
                try:
                    # Load the fast 384-dimensional all-MiniLM-L6-v2 model
                    self.model = SentenceTransformer("all-MiniLM-L6-v2")
                    print("[EmbeddingEngine] Pre-trained all-MiniLM-L6-v2 model loaded successfully.")
                except Exception as e:
                    print(f"[EmbeddingEngine] Model load error: {e}")

    def get_embeddings(self, texts: list) -> list:
        """Encodes list of texts into embeddings (list of float lists)."""
        self._lazy_init()
        if self.model is None or np is None:
            return []
            
        try:
            # Generate vectors as float32 numpy array, then convert to list
            embeddings_np = self.model.encode(texts, convert_to_numpy=True).astype("float32")
            return embeddings_np.tolist()
        except Exception as e:
            print(f"[EmbeddingEngine] Encoding error: {e}")
            return []

    def get_embedding(self, text: str) -> list:
        """Encodes a single text string."""
        res = self.get_embeddings([text])
        return res[0] if res else []
