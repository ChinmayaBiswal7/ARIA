"""
memory_manager.py — Unified Memory & Face Embedding Manager for ARIA
=====================================================================
Combines SQLite, VectorMemory, FaceEmbedder, and Firebase Firestore
to manage ARIA's memory sub-systems.

MEMORY SEGREGATION ARCHITECTURE
------------------------------
To prevent context pollution, hallucinated recalls, and recursive confusion,
ARIA divides memory into four distinct architectural tiers:

1. Conversational Memory (Ephemeral, dialogue-only):
   - Scope: Turn-by-turn dialogue history of the current chat session.
   - Storage: Maintained in ConversationalContextEngine and Brain.chat_history.
   - Policy: Lightweight, sliding context window, strictly pruned, never persisted.

2. Episodic Task Memory (Task execution paths):
   - Scope: Logs of executed goals, parent-child hierarchies, steps, durations, and outcomes.
   - Storage: Tracked in ActiveTaskManager and task trace logs.
   - Policy: Persisted to capture what happened, why, and how long it took. Used for retrospective planning.

3. Semantic Memory (Distilled facts & profiles):
   - Scope: Distilled user preferences, habits, face embeddings, and long-term knowledge.
   - Storage: Persisted locally in SQLite and VectorMemory (ChromaDB), synchronized to Firebase Firestore.
   - Policy: Never stores raw conversational dialogue, only distilled/extracted key facts.

4. Tool State (Transient environment state):
   - Scope: Current page URL, browser DOM snapshots, visible interactable elements, and input values.
   - Storage: Transiently stored in BrowserSkill.page_state.
   - Policy: Purged completely on browser close or task termination.
"""

import os
import json
import time
import sqlite3
import threading

try:
    from skills.face_embedder import FaceEmbedder
except Exception as e:
    FaceEmbedder = None
    print(f"[MemoryManager] FaceEmbedder unavailable: {e}")

try:
    from skills.vector_memory import VectorMemory
except Exception as e:
    VectorMemory = None
    print(f"[MemoryManager] VectorMemory unavailable: {e}")

try:
    from skills.scene_memory import SceneMemory
except Exception as e:
    SceneMemory = None
    print(f"[MemoryManager] SceneMemory unavailable: {e}")

DB_PATH = "aria_memory.db"
SERVICE_ACCOUNT_PATH = "serviceAccountKey.json"

class MemoryManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(MemoryManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.embedder = FaceEmbedder() if FaceEmbedder else None
        self.vector_mem = VectorMemory() if VectorMemory else None
        self.db_path = DB_PATH
        self.scene_mem = SceneMemory(self.vector_mem, self.db_path) if SceneMemory and self.vector_mem else None
        
        # Cache for face recognition
        self.known_faces = {}  # username -> embedding vector
        self.last_face_log_time = 0.0
        self.last_face_match_user = None
        self.last_face_update_time = 0.0
        
        self.firestore = None
        self._init_sqlite()
        self._init_firebase()
        self.reload_face_embeddings()
        self._initialized = True

    def _init_sqlite(self):
        """Ensure SQLite has local tables for face embeddings, sync status, safeguards, and audit logs."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS face_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                embedding_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                pref_key TEXT NOT NULL,
                pref_value TEXT NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(username, pref_key)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cognition_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                description TEXT NOT NULL,
                metadata_json TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS corrupted_cognition_quarantine (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                table_name TEXT NOT NULL,
                original_data TEXT NOT NULL,
                error_msg TEXT NOT NULL
            )
        """)
        conn.commit()

        # Database schema migrations
        cursor.execute("PRAGMA table_info(user_preferences)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        if "confidence" not in existing_cols:
            cursor.execute("ALTER TABLE user_preferences ADD COLUMN confidence REAL DEFAULT 1.0")
        if "evidence" not in existing_cols:
            cursor.execute("ALTER TABLE user_preferences ADD COLUMN evidence TEXT DEFAULT '[]'")
        if "unresolved_ambiguity" not in existing_cols:
            cursor.execute("ALTER TABLE user_preferences ADD COLUMN unresolved_ambiguity INTEGER DEFAULT 0")
        if "reasoning_trace" not in existing_cols:
            cursor.execute("ALTER TABLE user_preferences ADD COLUMN reasoning_trace TEXT")
        if "reasoning_confidence" not in existing_cols:
            cursor.execute("ALTER TABLE user_preferences ADD COLUMN reasoning_confidence REAL DEFAULT 1.0")
        conn.commit()
        conn.close()

    def log_cognition_audit(self, event_type: str, description: str, metadata: dict = None):
        """Logs cognitive adjustments, contradictions, or safety actions to the audit log."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO cognition_audit_log (timestamp, event_type, description, metadata_json)
                VALUES (?, ?, ?, ?)
            """, (time.time(), event_type, description, json.dumps(metadata or {})))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[MemoryManager] Audit log write failure: {e}")

    def validate_and_heal_database(self):
        """
        Scans tables for malformed values, NaNs, empty rows, or out-of-bound variables.
        Moves corrupted data to quarantine rather than deleting silently, and repairs state.
        """
        print("[Cognitive Safeguards] Running database validation and self-healing pass...")
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 1. Validate relationship_vector
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='relationship_vector'")
            if cursor.fetchone():
                rows = cursor.execute("SELECT * FROM relationship_vector").fetchall()
                for r in rows:
                    username = r["username"]
                    corrupt = False
                    details = {}
                    for col in ["trust", "comfort", "interaction_depth", "emotional_openness"]:
                        val = r[col]
                        # Check NaN, None, or out-of-bounds
                        if val is None or str(val).lower() == "nan" or not (0.0 <= float(val) <= 10.0):
                            corrupt = True
                            details[col] = val
                    
                    if corrupt:
                        # Move to quarantine
                        cursor.execute("""
                            INSERT INTO corrupted_cognition_quarantine (timestamp, table_name, original_data, error_msg)
                            VALUES (?, ?, ?, ?)
                        """, (time.time(), "relationship_vector", json.dumps(dict(r)), f"Invalid bounds/NaN metrics: {details}"))
                        # Reset to defaults
                        cursor.execute("""
                            INSERT OR REPLACE INTO relationship_vector 
                            (username, trust, comfort, interaction_depth, emotional_openness, updated_at)
                            VALUES (?, 10.0, 10.0, 10.0, 10.0, ?)
                        """, (username, time.time()))
                        self.log_cognition_audit(
                            "DATABASE_HEALING", 
                            f"Healed relationship_vector for user '{username}' due to out-of-bounds/NaN metrics.",
                            {"original": dict(r), "errors": details}
                        )

            # 2. Validate user_preferences
            rows = cursor.execute("SELECT * FROM user_preferences").fetchall()
            for r in rows:
                row_id = r["id"]
                corrupt = False
                err_msg = ""
                
                # Check empty key/val
                if not r["pref_key"] or not r["pref_value"]:
                    corrupt = True
                    err_msg = "Empty preference key or value."
                
                # Check confidence NaN
                conf = r["confidence"]
                if conf is None or str(conf).lower() == "nan" or not (0.0 <= float(conf) <= 1.0):
                    # We can heal this in-place
                    cursor.execute("UPDATE user_preferences SET confidence = 1.0 WHERE id = ?", (row_id,))
                    self.log_cognition_audit("DATABASE_HEALING", f"Healed user_preference id={row_id} with invalid confidence {conf} to 1.0")
                
                # Check evidence JSON format
                evidence = r["evidence"]
                try:
                    json.loads(evidence or "[]")
                except Exception:
                    cursor.execute("UPDATE user_preferences SET evidence = '[]' WHERE id = ?", (row_id,))
                    self.log_cognition_audit("DATABASE_HEALING", f"Healed user_preference id={row_id} with malformed evidence JSON.")

                if corrupt:
                    cursor.execute("""
                        INSERT INTO corrupted_cognition_quarantine (timestamp, table_name, original_data, error_msg)
                        VALUES (?, ?, ?, ?)
                    """, (time.time(), "user_preferences", json.dumps(dict(r)), err_msg))
                    cursor.execute("DELETE FROM user_preferences WHERE id = ?", (row_id,))
                    self.log_cognition_audit(
                        "DATABASE_HEALING", 
                        f"Quarantined and deleted corrupt user_preference id={row_id} for user '{r['username']}'.",
                        dict(r)
                    )

            # 3. Validate candidate_semantic_updates
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='candidate_semantic_updates'")
            if cursor.fetchone():
                rows = cursor.execute("SELECT * FROM candidate_semantic_updates").fetchall()
                for r in rows:
                    cand_id = r["id"]
                    conf = r["confidence"]
                    if conf is None or str(conf).lower() == "nan" or not (0.0 <= float(conf) <= 1.0):
                        cursor.execute("UPDATE candidate_semantic_updates SET confidence = 0.5 WHERE id = ?", (cand_id,))
                        self.log_cognition_audit("DATABASE_HEALING", f"Healed candidate update '{cand_id}' confidence to 0.5.")
                    
                    occ = r["occurrences"]
                    if occ is None or int(occ) < 1:
                        cursor.execute("UPDATE candidate_semantic_updates SET occurrences = 1 WHERE id = ?", (cand_id,))
                        self.log_cognition_audit("DATABASE_HEALING", f"Healed candidate update '{cand_id}' occurrences count to 1.")

            conn.commit()
            conn.close()
            print("[Cognitive Safeguards] Database validation complete. Status: Healthy.")
        except Exception as e:
            print(f"[Cognitive Safeguards] Self-healing process failed: {e}")

    def _init_firebase(self):
        """Initialize Firebase Admin SDK if serviceAccountKey is present."""
        if os.path.exists(SERVICE_ACCOUNT_PATH):
            try:
                import firebase_admin
                from firebase_admin import credentials, firestore
                
                if not firebase_admin._apps:
                    cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
                    firebase_admin.initialize_app(cred)
                self.firestore = firestore.client()
                print("[MemoryManager] Firebase SDK active for Memory Sync.")
            except Exception as e:
                print(f"[MemoryManager] Firebase initialization failed: {e}")

    # --- Face Recognition & Embeddings ---
    def reload_face_embeddings(self):
        """Load face embeddings from Firebase, falling back to SQLite if offline."""
        loaded = {}
        
        # 1. Try Firebase First
        if self.firestore:
            try:
                docs = self.firestore.collection("faces").stream()
                for doc in docs:
                    data = doc.to_dict()
                    emb = data.get("embedding")
                    if emb:
                        normalized_id = doc.id.strip().strip('.').lower()
                        # Auto-migrate single embedding (1D) to cluster list format
                        if isinstance(emb, list) and len(emb) > 0:
                            if isinstance(emb[0], (int, float)):
                                cluster = [{"embedding": emb, "added_at": time.time()}]
                            else:
                                cluster = emb
                        else:
                            cluster = emb
                        loaded[normalized_id] = cluster
                
                # Update SQLite local cache with Firebase data
                if loaded:
                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()
                    for user, cluster in loaded.items():
                        cursor.execute("""
                            INSERT OR REPLACE INTO face_embeddings (username, embedding_json, updated_at)
                            VALUES (?, ?, ?)
                        """, (user, json.dumps(cluster), time.time()))
                    conn.commit()
                    conn.close()
                    self.known_faces = loaded
                    print(f"[MemoryManager] Loaded {len(loaded)} faces from Firebase.")
            except Exception as e:
                print(f"[MemoryManager] Firebase face load failed: {e}. Trying SQLite cache...")
 
        # 2. SQLite Fallback
        if not self.known_faces:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT username, embedding_json FROM face_embeddings")
                rows = cursor.fetchall()
                conn.close()
                
                for user, emb_json in rows:
                    normalized_user = user.strip().strip('.').lower()
                    emb_parsed = json.loads(emb_json)
                    if isinstance(emb_parsed, list) and len(emb_parsed) > 0:
                        if isinstance(emb_parsed[0], (int, float)):
                            cluster = [{"embedding": emb_parsed, "added_at": time.time()}]
                        else:
                            cluster = emb_parsed
                    else:
                        cluster = emb_parsed
                    loaded[normalized_user] = cluster
                self.known_faces = loaded
                print(f"[MemoryManager] Loaded {len(loaded)} faces from SQLite cache.")
            except Exception as e:
                print(f"[MemoryManager] SQLite face load failed: {e}")

        # 3. Sync to ChromaDB face collection
        if self.known_faces and self.vector_mem and self.vector_mem.faces_collection:
            try:
                for user, cluster in self.known_faces.items():
                    for i, entry in enumerate(cluster):
                        v = entry["embedding"]
                        self.vector_mem.faces_collection.upsert(
                            embeddings=[v],
                            metadatas=[{"username": user}],
                            ids=[f"{user}_{i}"]
                        )
                print(f"[MemoryManager] Synced cluster face embeddings to ChromaDB.")
            except Exception as e:
                print(f"[MemoryManager] Failed to sync face embeddings to ChromaDB: {e}")

    def save_face_embedding(self, username, image_array=None, embedding=None):
        """Extract or accept face embedding / cluster, save to Firebase, SQLite, and ChromaDB, and update memory cache."""
        emb = embedding if embedding is not None else (self.embedder.get_embedding(image_array) if self.embedder and image_array is not None else None)
        if not emb:
            print("[MemoryManager] Could not extract or receive face embedding.")
            return False

        normalized_user = username.strip().strip('.').lower()
        now = time.time()

        # If it's a single 1D embedding, build or update the cluster
        if isinstance(emb, list) and len(emb) > 0 and isinstance(emb[0], (int, float)):
            existing_cluster = self.known_faces.get(normalized_user) or []
            # Check duplicate check distance < 0.08 (similarity >= 0.92 to any existing member)
            is_redundant = False
            for entry in existing_cluster:
                saved = entry["embedding"]
                if self.embedder:
                    sim = self.embedder.cosine_similarity(emb, saved)
                    if sim >= 0.92:
                        is_redundant = True
                        break
            if is_redundant and len(existing_cluster) > 0:
                print(f"[FaceLearning] Skip duplicate storage for '{normalized_user}' (already exists in cluster)")
                return True
            
            cluster = list(existing_cluster)
            if len(cluster) >= 8:
                cluster.sort(key=lambda x: x["added_at"])
                removed = cluster.pop(0)
                print(f"[FaceLearning] Cluster full for '{normalized_user}'. Replaced oldest embedding added at {removed['added_at']}")
            cluster.append({
                "embedding": emb,
                "added_at": now
            })
            emb_to_save = cluster
        else:
            # It's already a cluster
            emb_to_save = emb

        # 1. Save to SQLite
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO face_embeddings (username, embedding_json, updated_at)
                VALUES (?, ?, ?)
            """, (normalized_user, json.dumps(emb_to_save), now))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[MemoryManager] SQLite face save failed: {e}")

        # 2. Save to Firebase
        if self.firestore:
            try:
                self.firestore.collection("faces").document(normalized_user).set({
                    "embedding": emb_to_save,
                    "updated_at": now
                })
                print(f"[MemoryManager] Successfully synced face for '{normalized_user}' to Firebase.")
            except Exception as e:
                print(f"[MemoryManager] Firebase face save failed: {e}")

        # 3. Save to ChromaDB face collection
        if self.vector_mem and self.vector_mem.faces_collection:
            try:
                # Upsert each cluster member with a unique ID
                for i, entry in enumerate(emb_to_save):
                    v = entry["embedding"]
                    self.vector_mem.faces_collection.upsert(
                        embeddings=[v],
                        metadatas=[{"username": normalized_user}],
                        ids=[f"{normalized_user}_{i}"]
                    )
                print(f"[MemoryManager] Saved face cluster for '{normalized_user}' to ChromaDB.")
            except Exception as e:
                print(f"[MemoryManager] ChromaDB face save failed: {e}")

        # Update cache
        self.known_faces[normalized_user] = emb_to_save
        return True

    def add_face_embedding_to_cluster(self, username, current_emb, similarity):
        """Adds a new face embedding vector to the user's cluster (up to 8 items) if it captures a new condition (sufficiently different)."""
        normalized_user = username.strip().strip('.').lower()
 
        # Cooldown guard: 30 seconds
        now = time.time()
        if now - getattr(self, "last_face_update_time", 0.0) < 30.0:
            return False
 
        # Threshold check: Access / Learning threshold (>= 0.65)
        if similarity < 0.65:
            print(f"[FaceLearning] User={normalized_user} Similarity={similarity:.3f} Skipped (below 0.65 threshold)")
            return False
 
        # Retrieve the user's current cluster
        existing_cluster = self.known_faces.get(normalized_user) or []
        
        # Check duplicate check distance < 0.08 (similarity >= 0.92 to any existing member)
        is_redundant = False
        for entry in existing_cluster:
            saved = entry["embedding"]
            if self.embedder:
                sim = self.embedder.cosine_similarity(current_emb, saved)
                if sim >= 0.92:
                    is_redundant = True
                    break
        
        if is_redundant and len(existing_cluster) > 0:
            print(f"[FaceLearning] User={normalized_user} Similarity={similarity:.3f} Skipped (redundant, already represented in cluster)")
            return False
 
        # L2-normalize the incoming embedding vector before saving
        try:
            import numpy as np
            cur_np = np.array(current_emb)
            norm = np.linalg.norm(cur_np)
            if norm > 0:
                cur_np = cur_np / norm
            current_emb = cur_np.tolist()
        except Exception as e:
            print(f"[MemoryManager] Embedding normalization failed: {e}")
 
        # Update cluster list
        cluster = list(existing_cluster)
        if len(cluster) >= 8:
            cluster.sort(key=lambda x: x["added_at"])
            removed = cluster.pop(0)
            print(f"[FaceLearning] Cluster full for '{normalized_user}'. Replaced oldest embedding added at {removed['added_at']}")
 
        cluster.append({
            "embedding": current_emb,
            "added_at": now
        })
        
        print(f"[FaceLearning] User={normalized_user} Similarity={similarity:.3f} Cluster size={len(cluster)}/8. Added new embedding condition.")
        self.last_face_update_time = now
        return self.save_face_embedding(normalized_user, embedding=cluster)
 
 
    def identify_user(self, image_array=None, threshold=0.63, return_confidence=False, embedding=None, is_already_cropped=False):
        """Identify user based on face embedding cosine similarity using ChromaDB or fallback."""
        current_emb = embedding if embedding is not None else (self.embedder.get_embedding(image_array, is_already_cropped=is_already_cropped) if self.embedder and image_array is not None else None)
        if not current_emb:
            return ("Unknown", 0.0) if return_confidence else "Unknown"
 
        # 1. Try ChromaDB query first
        if self.vector_mem and self.vector_mem.faces_collection:
            try:
                results = self.vector_mem.faces_collection.query(
                    query_embeddings=[current_emb],
                    n_results=1
                )
                if results and 'ids' in results and results['ids'] and results['ids'][0]:
                    best_match_id = results['ids'][0][0]
                    dist = results['distances'][0][0]
                    sim = 1.0 - dist
                    
                    # Extract username from metadata if available
                    best_match_meta = results['metadatas'][0][0] if ('metadatas' in results and results['metadatas'] and results['metadatas'][0]) else None
                    best_match = best_match_meta.get("username", best_match_id) if best_match_meta else best_match_id
                    
                    # Clean/normalize
                    best_match_normalized = best_match.strip().strip('.').lower()
                    
                    # Remove trailing underscore suffixes e.g. chinmay_0 -> chinmay
                    if "_" in best_match_normalized:
                        parts = best_match_normalized.rsplit("_", 1)
                        if parts[1].isdigit():
                            best_match_normalized = parts[0]
                    
                    now = time.time()
                    if best_match_normalized != self.last_face_match_user or (now - self.last_face_log_time) >= 5.0:
                        print(f"[MemoryManager] ChromaDB face match: '{best_match_normalized}' with similarity: {sim:.3f}")
                        self.last_face_match_user = best_match_normalized
                        self.last_face_log_time = now
 
                    if sim >= threshold:
                        print(f"[FaceRec] Match={best_match_normalized} Similarity={sim:.3f}")
                        return (best_match_normalized, sim) if return_confidence else best_match_normalized
                    else:
                        print(f"[FaceRec] No match Similarity={sim:.3f}")
                else:
                    print("[FaceRec] No match Similarity=0.000")
                return ("Unknown", 0.0) if return_confidence else "Unknown"
            except Exception as e:
                print(f"[MemoryManager] ChromaDB face query error: {e}. Falling back to manual search...")
 
        # 2. Manual SQLite/cache fallback
        if not self.known_faces:
            print("[FaceRec] No match Similarity=0.000")
            return ("Unknown", 0.0) if return_confidence else "Unknown"
 
        best_match = "Unknown"
        best_sim = 0.0
 
        for user, cluster in self.known_faces.items():
            if not self.embedder:
                continue
            # Support both cluster lists and legacy single 1D vectors
            if isinstance(cluster, list) and len(cluster) > 0 and isinstance(cluster[0], (int, float)):
                sim = self.embedder.cosine_similarity(current_emb, cluster)
                if sim > best_sim:
                    best_sim = sim
                    best_match = user
            else:
                for entry in cluster:
                    saved_emb = entry["embedding"]
                    sim = self.embedder.cosine_similarity(current_emb, saved_emb)
                    if sim > best_sim:
                        best_sim = sim
                        best_match = user
 
        now = time.time()
        best_match_normalized = best_match.strip().strip('.').lower()
        if best_match_normalized != self.last_face_match_user or (now - self.last_face_log_time) >= 5.0:
            print(f"[MemoryManager] Best face match (fallback): '{best_match_normalized}' with similarity: {best_sim:.3f}")
            self.last_face_match_user = best_match_normalized
            self.last_face_log_time = now
 
        if best_sim >= threshold:
            print(f"[FaceRec] Match={best_match_normalized} Similarity={best_sim:.3f}")
            return (best_match_normalized, best_sim) if return_confidence else best_match_normalized
        
        print(f"[FaceRec] No match Similarity={best_sim:.3f}")
        return ("Unknown", 0.0) if return_confidence else "Unknown"

    # --- Preferences & Habits Sync ---
    def set_preference(self, username, key, value, confidence=1.0, evidence=None, reasoning_trace=None, reasoning_confidence=1.0):
        """Save a preference locally and push to Firebase, verifying safeguards."""
        username = username.strip().strip('.').lower()
        key = key.strip().lower()
        now = time.time()
        
        evidence_json = json.dumps(evidence or [])

        # Guest Mode check
        if username == "guest":
            print(f"[MemoryManager] Guest Mode active. Restricting profile write for key '{key}'.")
            return

        sim_report = None

        # Cognitive Sandbox Pre-Commit Simulation Safeguard
        try:
            from skills.cognitive_sandbox import CognitiveSandbox
            sandbox = CognitiveSandbox()
            sim_report = sandbox.simulate_preference_update(
                username=username,
                key=key,
                value=str(value),
                confidence=confidence,
                evidence=evidence,
                reasoning_trace=reasoning_trace
            )
            if not sim_report["success"]:
                try:
                    from dashboard import CognitionState
                    CognitionState.sandbox_simulation = sim_report
                    CognitionState.drift_delta_score = sim_report.get("drift_delta_score", 0.0)
                    CognitionState.emotional_volatility = sim_report.get("emotional_volatility", {})
                    CognitionState.simulated_anomalies_quarantined += max(1, len(sim_report.get("anomalies", [])))
                    CognitionState.cognitive_version = sim_report.get("cognitive_version", CognitionState.cognitive_version)
                except Exception:
                    pass
                # Proposed update causes trait conflicts, identity drift, or other validation issues! Reject and quarantine!
                from skills.reflection_engine import ReflectionEngine
                ReflectionEngine().propose_candidate_update(
                    username=username,
                    key=key,
                    value=str(value),
                    confidence=confidence,
                    source="quarantined_by_sandbox",
                    evidence=evidence,
                    reasoning_trace=reasoning_trace
                )
                self.log_cognition_audit(
                    "SANDBOX_REJECTION",
                    f"Preference '{key}' rejected by Cognitive Simulation Sandbox due to validation issues.",
                    {
                        "username": username,
                        "key": key,
                        "value": str(value),
                        "drift_delta_score": sim_report.get("drift_delta_score", 0.0),
                        "anomalies": sim_report.get("anomalies", []),
                        "trait_conflicts": sim_report.get("trait_conflicts", []),
                        "identity_drift": sim_report.get("identity_drift", []),
                        "emotional_volatility": sim_report.get("emotional_volatility", {})
                    }
                )
                print(f"[Cognitive Sandbox] Proposed update rejected by sandbox. Quarantining. Anomalies: {sim_report.get('anomalies', [])}")
                return
            try:
                from dashboard import CognitionState
                CognitionState.sandbox_simulation = sim_report
                CognitionState.drift_delta_score = sim_report.get("drift_delta_score", 0.0)
                CognitionState.emotional_volatility = sim_report.get("emotional_volatility", {})
                CognitionState.cognitive_version = sim_report.get("cognitive_version", {})
            except Exception:
                pass
        except Exception as sandbox_err:
            print(f"[MemoryManager] Cognitive Sandbox simulation error or skipped: {sandbox_err}")

        # Rollback snapshot fallback if sandbox was unavailable.
        if not sim_report or not sim_report.get("rollback_snapshot_id"):
            try:
                from skills.cognitive_sandbox import CognitiveSandbox
                CognitiveSandbox().save_cognitive_snapshot(username, label=f"preference_pre_update:{key}")
            except Exception as snapshot_err:
                print(f"[MemoryManager] Rollback snapshot skipped: {snapshot_err}")

        # Contradiction Detection Safeguard
        try:
            from skills.reflection_engine import ReflectionEngine
            re = ReflectionEngine()
            is_contradict, reason = re.detect_contradiction(username, key, str(value))
            if is_contradict:
                # Flag current belief as unresolved ambiguity
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE user_preferences 
                    SET unresolved_ambiguity = 1 
                    WHERE username = ? AND pref_key = ?
                """, (username, key))
                conn.commit()
                conn.close()

                # Save conflicting candidate in quarantine
                re.propose_candidate_update(
                    username=username,
                    key=key,
                    value=str(value),
                    confidence=confidence,
                    source="user_explicit",
                    reasoning_trace=reasoning_trace
                )

                self.log_cognition_audit(
                    "CONTRADICTION_DETECTED",
                    f"Contradiction detected for key '{key}'. Old belief kept but flagged as unresolved. New belief quarantined.",
                    {"username": username, "key": key, "offered_value": str(value), "reason": reason}
                )
                print(f"[Cognitive Safeguards] Contradiction detected on key '{key}': {reason}. Quarantining.")
                return
        except Exception as e:
            print(f"[MemoryManager] Contradiction detection skipped: {e}")

        # SQLite write
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO user_preferences 
                (username, pref_key, pref_value, updated_at, confidence, evidence, unresolved_ambiguity, reasoning_trace, reasoning_confidence)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            """, (username, key, str(value), now, confidence, evidence_json, reasoning_trace, reasoning_confidence))
            conn.commit()
            conn.close()
            
            # Log successful write
            self.log_cognition_audit(
                "PREFERENCE_UPDATED",
                f"Updated preference '{key}' to '{value}' with confidence {confidence:.2f}.",
                {
                    "username": username,
                    "key": key,
                    "value": str(value),
                    "confidence": confidence,
                    "evidence": evidence or [],
                    "reasoning_trace": reasoning_trace,
                    "reasoning_confidence": reasoning_confidence,
                    "rollback_snapshot_id": sim_report.get("rollback_snapshot_id") if sim_report else None,
                    "drift_delta_score": sim_report.get("drift_delta_score") if sim_report else None,
                    "cognitive_version": sim_report.get("cognitive_version") if sim_report else None
                }
            )
        except Exception as e:
            print(f"[MemoryManager] SQLite pref save error: {e}")

        # Firebase write
        if self.firestore:
            try:
                # Store inside subcollection under user
                self.firestore.collection("users").document(username).collection("preferences").document(key).set({
                    "value": str(value),
                    "updated_at": now,
                    "confidence": confidence,
                    "evidence": evidence or [],
                    "reasoning_trace": reasoning_trace,
                    "reasoning_confidence": reasoning_confidence
                })
            except Exception as e:
                print(f"[MemoryManager] Firebase pref save error: {e}")

    def get_preferences(self, username):
        """Get all preferences for a user."""
        username = username.strip().strip('.').lower()
        prefs = {}

        # Try SQLite
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT pref_key, pref_value FROM user_preferences WHERE username = ?", (username,))
            rows = cursor.fetchall()
            conn.close()
            for k, v in rows:
                prefs[k] = v
        except Exception as e:
            print(f"[MemoryManager] SQLite pref fetch error: {e}")
        return prefs

    # --- Conversation Logs ---
    def log_interaction(self, username, user_msg, assist_reply):
        """Log conversation turn for semantic analysis."""
        username = username.strip().strip('.').lower()
        now = time.time()

        # Sanitize logs using SecurityGuard
        try:
            from skills.security_guard import SecurityGuard
            guard = SecurityGuard()
            user_msg = guard.sanitize_memory_text(user_msg)
            assist_reply = guard.sanitize_memory_text(assist_reply)
        except Exception as se:
            print(f"[MemoryManager] Log sanitization failed: {se}")

        # SQLite
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO conversation_history (username, role, content, timestamp)
                VALUES (?, ?, ?, ?)
            """, (username, "user", user_msg, now))
            cursor.execute("""
                INSERT INTO conversation_history (username, role, content, timestamp)
                VALUES (?, ?, ?, ?)
            """, (username, "assistant", assist_reply, now))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[MemoryManager] SQLite history log error: {e}")

        # Firebase
        if self.firestore:
            try:
                self.firestore.collection("conversations").add({
                    "username": username,
                    "user_message": user_msg,
                    "assistant_response": assist_reply,
                    "timestamp": now
                })
            except Exception as e:
                print(f"[MemoryManager] Firebase history log error: {e}")

        # Add key interaction to Vector Memory semantic storage
        if "favorite" in user_msg.lower() or "like" in user_msg.lower() or "remember" in user_msg.lower():
            try:
                if self.vector_mem:
                    self.vector_mem.add_memory(
                        text=f"User stated: {user_msg}",
                        category="personal_fact",
                        metadata={"username": username}
                    )
            except Exception as e:
                print(f"[MemoryManager] Semantic logging failed: {e}")

    # --- Context Injection Generator ---
    def get_injected_context(self, username, query):
        """Retrieve related memories, preferences, and details to inject into prompt."""
        username = username.strip().strip('.').lower()
        parts = []

        # 1. User Preferences
        prefs = self.get_preferences(username)
        if prefs:
            pref_str = ", ".join([f"{k}: {v}" for k, v in prefs.items()])
            parts.append(f"[User Preferences: {pref_str}]")

        # 2. Semantic memories
        try:
            semantic_matches = self.vector_mem.semantic_search(query, limit=2) if self.vector_mem else []
            if semantic_matches:
                matches_str = "\n".join([f"- {text}" for sim, text, cat in semantic_matches if sim > 0.45])
                if matches_str:
                    parts.append(f"[Relevant User Knowledge & Memories:\n{matches_str}]")
        except Exception as e:
            print(f"[MemoryManager] Semantic lookup failed: {e}")

        # 3. Episodic memories
        try:
            from skills.episodic_memory import EpisodicMemory
            episodes_str = EpisodicMemory().build_context_string(username, query, limit=3)
            if episodes_str:
                parts.append(episodes_str)
        except Exception as e:
            print(f"[MemoryManager] Episodic context lookup failed: {e}")

        return "\n".join(parts)

    def apply_evidence_aging(self):
        """Reduces the effective weight of old evidence. Evidence older than 30 days
        contributes 50% less. Evidence older than 90 days contributes 80% less.
        This is reflected by decaying the confidence proportionally."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            now = time.time()
            audit_events = []
            rows = cursor.execute(
                "SELECT id, updated_at, confidence, evidence FROM user_preferences WHERE confidence > 0.1"
            ).fetchall()
            for r in rows:
                age_days = (now - r['updated_at']) / 86400.0
                if age_days >= 90.0:
                    aging_factor = 0.2  # 80% reduction
                elif age_days >= 30.0:
                    aging_factor = 0.5  # 50% reduction
                else:
                    continue  # No aging needed
                aged_confidence = max(0.1, r['confidence'] * aging_factor)
                if aged_confidence < r['confidence']:
                    cursor.execute(
                        "UPDATE user_preferences SET confidence = ? WHERE id = ?",
                        (aged_confidence, r['id'])
                    )
                    audit_events.append(
                        (
                            'EVIDENCE_AGING',
                            f"Evidence aged for preference id={r['id']}: confidence {r['confidence']:.2f} -> {aged_confidence:.2f} (age: {age_days:.0f} days)",
                            {'id': r['id'], 'old_confidence': r['confidence'], 'new_confidence': aged_confidence, 'age_days': age_days}
                        )
                    )
            conn.commit()
            conn.close()
            for event_type, description, metadata in audit_events:
                self.log_cognition_audit(event_type, description, metadata)
            print('[MemoryManager] Evidence aging pass complete.')
        except Exception as e:
            print(f'[MemoryManager] Evidence aging failed: {e}')
