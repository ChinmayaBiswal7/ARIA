"""
skills/episodic_memory.py — ARIA Episodic Memory
==================================================

Stores discrete life events (what happened, when, how it felt, how important).
Enhanced with memory confidence, sources, and retention tiers.

Decay Model (Tiered):
  - temporary: deleted after 1 day.
  - weekly: archived after 7 days.
  - permanent: decays according to standard retention formula:
      retention = importance * 0.6 + emotional_weight * 0.3 + recency * 0.1
      < 0.25 → archive (compress to one-line summary)
      < 0.10 → delete  (truly forgotten)
"""

import sqlite3
import json
import time
import uuid
import threading
from typing import List, Optional, Tuple, Dict, Any

DB_PATH = "aria_memory.db"
_lock = threading.Lock()


# ─── Schema ──────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodic_events (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL,
    event_text      TEXT NOT NULL,
    emotion         TEXT DEFAULT 'neutral',
    importance      REAL DEFAULT 0.5,
    emotional_weight REAL DEFAULT 0.3,
    timestamp       REAL NOT NULL,
    archived        INTEGER DEFAULT 0,
    archive_summary TEXT,
    confidence      REAL DEFAULT 1.0,
    source          TEXT DEFAULT 'observed',
    retention_tier  TEXT DEFAULT 'permanent'
);
CREATE INDEX IF NOT EXISTS idx_episodic_user ON episodic_events(username, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_episodic_emotion ON episodic_events(username, emotion);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema():
    with _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS episodic_events (
            id              TEXT PRIMARY KEY,
            username        TEXT NOT NULL,
            event_text      TEXT NOT NULL,
            emotion         TEXT DEFAULT 'neutral',
            importance      REAL DEFAULT 0.5,
            emotional_weight REAL DEFAULT 0.3,
            timestamp       REAL NOT NULL,
            archived        INTEGER DEFAULT 0,
            archive_summary TEXT
        );
        """)
        # Schema migration
        cursor = c.cursor()
        cursor.execute("PRAGMA table_info(episodic_events)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        if "confidence" not in existing_cols:
            c.execute("ALTER TABLE episodic_events ADD COLUMN confidence REAL DEFAULT 1.0")
        if "source" not in existing_cols:
            c.execute("ALTER TABLE episodic_events ADD COLUMN source TEXT DEFAULT 'observed'")
        if "retention_tier" not in existing_cols:
            c.execute("ALTER TABLE episodic_events ADD COLUMN retention_tier TEXT DEFAULT 'permanent'")

        c.execute("CREATE INDEX IF NOT EXISTS idx_episodic_user ON episodic_events(username, timestamp DESC);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_episodic_emotion ON episodic_events(username, emotion);")
        c.commit()


_ensure_schema()


# ─── EpisodicMemory ──────────────────────────────────────────────────────────

class EpisodicMemory:
    """
    Records and retrieves discrete life events for a user.
    """

    _instance = None
    _cls_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._cls_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._chroma = None
                inst._chroma_col = None
                inst._init_chroma()
                cls._instance = inst
            return cls._instance

    def _init_chroma(self):
        try:
            import chromadb, os
            chroma_dir = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "chroma_db")
            client = chromadb.PersistentClient(path=chroma_dir)
            self._chroma_col = client.get_or_create_collection(
                name="aria_episodes",
                metadata={"hnsw:space": "cosine"}
            )
            print("[EpisodicMemory] ChromaDB episodic collection ready.")
        except Exception as e:
            print(f"[EpisodicMemory] ChromaDB init failed (degraded mode): {e}")

    # ── Write ─────────────────────────────────────────────────────────────

    def score_importance_heuristically(self, event_text: str, emotion: str) -> Tuple[float, float]:
        """Calculates dynamic importance and emotional weight using keyword patterns."""
        importance = 0.5
        emotional_weight = 0.3
        
        text_lower = event_text.lower()
        
        # Keywords indicating system errors or task blocks
        if any(w in text_lower for w in ["fail", "error", "block", "stuck", "exception", "refused", "denied"]):
            importance = 0.8
            emotional_weight = 0.6
            
        # Keywords indicating critical operations
        if any(w in text_lower for w in ["password", "credential", "auth", "token", "secret", "login", "registry", "shutdown"]):
            importance = 0.9
            emotional_weight = 0.4
            
        # Ephemeral interactions
        if any(w in text_lower for w in ["weather", "hello", "greet", "joke", "time", "date", "battery"]):
            importance = 0.2
            emotional_weight = 0.1
            
        # Map emotions to weights
        if emotion in ["stressed", "anxious", "sad", "frustrated"]:
            emotional_weight = min(1.0, emotional_weight + 0.3)
        elif emotion in ["excited", "happy"]:
            emotional_weight = min(1.0, emotional_weight + 0.2)
            
        return importance, emotional_weight

    def record(
        self,
        username: str,
        event_text: str,
        emotion: str = "neutral",
        importance: Optional[float] = None,
        emotional_weight: Optional[float] = None,
        confidence: float = 1.0,
        source: str = "observed",
        retention_tier: str = "permanent",
    ) -> str:
        """
        Record a new episodic event.

        Args:
            username:         Who this event belongs to
            event_text:       Human-readable description of what happened
            emotion:          Detected/inferred emotion
            importance:       0.0–1.0 objective importance
            emotional_weight: 0.0–1.0 subjective emotional weight
            confidence:       0.0-1.0 degree of memory certainty (for uncertain memories)
            source:           "inferred", "user_explicit", "observed", "reflected"
            retention_tier:   "temporary", "weekly", "permanent", "archived"

        Returns:
            Event ID (UUID)
        """
        if importance is None or emotional_weight is None:
            calc_imp, calc_emo = self.score_importance_heuristically(event_text, emotion)
            importance = importance if importance is not None else calc_imp
            emotional_weight = emotional_weight if emotional_weight is not None else calc_emo

        # Set default retention tier heuristically if temporary keywords are present
        if retention_tier == "permanent" and importance < 0.3:
            retention_tier = "temporary"

        event_id  = str(uuid.uuid4())
        now       = time.time()
        username  = username.lower().strip()

        with _lock:
            with _conn() as c:
                c.execute(
                    """INSERT INTO episodic_events
                       (id, username, event_text, emotion, importance,
                        emotional_weight, timestamp, archived, confidence, source, retention_tier)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
                    (event_id, username, event_text, emotion,
                     importance, emotional_weight, now, confidence, source, retention_tier)
                )

        # Mirror to ChromaDB for semantic recall
        if self._chroma_col:
            try:
                self._chroma_col.add(
                    documents=[event_text],
                    metadatas=[{
                        "username": username,
                        "emotion":  emotion,
                        "importance": importance,
                        "emotional_weight": emotional_weight,
                        "timestamp": now,
                        "confidence": confidence,
                        "source": source,
                        "retention_tier": retention_tier,
                    }],
                    ids=[event_id],
                )
            except Exception as e:
                print(f"[EpisodicMemory] ChromaDB add failed: {e}")

        # Emit MEMORY_UPDATED event
        try:
            from skills.event_bus import EventBus, ARIAEvents
            EventBus().publish(ARIAEvents.MEMORY_UPDATED, ARIAEvents.build_payload(
                extra={"memory_type": "episodic", "username": username,
                       "event_id": event_id, "emotion": emotion, "source": source, "confidence": confidence}
            ))
        except Exception:
            pass

        print(f"[EpisodicMemory] Recorded [{emotion}|{importance:.1f}|{retention_tier}]: {event_text[:60]}")
        return event_id

    # ── Read ──────────────────────────────────────────────────────────────

    def recall(
        self,
        username: str,
        query: str,
        limit: int = 5,
        emotion_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Semantically recall episodes relevant to a query.
        """
        username = username.lower().strip()

        # ChromaDB semantic recall
        if self._chroma_col:
            try:
                where = {"username": username}
                if emotion_filter:
                    where["emotion"] = emotion_filter
                results = self._chroma_col.query(
                    query_texts=[query],
                    n_results=min(limit, 10),
                    where=where,
                )
                hits = []
                if results and results.get("documents"):
                    docs  = results["documents"][0]
                    metas = results["metadatas"][0]
                    dists = results.get("distances", [[0.0] * len(docs)])[0]
                    ids   = results["ids"][0]
                    for doc, meta, dist, eid in zip(docs, metas, dists, ids):
                        hits.append({
                            "id":              eid,
                            "event_text":      doc,
                            "emotion":         meta.get("emotion", "neutral"),
                            "importance":      meta.get("importance", 0.5),
                            "emotional_weight": meta.get("emotional_weight", 0.3),
                            "timestamp":       meta.get("timestamp", 0.0),
                            "confidence":      meta.get("confidence", 1.0),
                            "source":          meta.get("source", "observed"),
                            "retention_tier":  meta.get("retention_tier", "permanent"),
                            "similarity":      round(1.0 - dist, 3),
                        })
                return hits
            except Exception as e:
                print(f"[EpisodicMemory] ChromaDB recall failed: {e}")

        # SQLite keyword fallback
        return self._sqlite_recall(username, query, limit, emotion_filter)

    def get_recent(
        self,
        username: str,
        n: int = 10,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get the N most recent episodes for a user."""
        username = username.lower().strip()
        archived_clause = "" if include_archived else "AND archived = 0"
        with _conn() as c:
            rows = c.execute(
                f"""SELECT id, event_text, emotion, importance, emotional_weight, timestamp, confidence, source, retention_tier
                    FROM episodic_events
                    WHERE username = ? {archived_clause}
                    ORDER BY timestamp DESC LIMIT ?""",
                (username, n)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Memory Decay & Tier Enforcement ───────────────────────────────────

    def decay_pass(self, username: str, now: Optional[float] = None) -> Dict[str, int]:
        """
        Run a memory decay scoring pass enforcing retention tiers.
        """
        now       = now or time.time()
        username  = username.lower().strip()
        stats     = {"archived": 0, "deleted": 0, "retained": 0}

        with _lock:
            with _conn() as c:
                rows = c.execute(
                    """SELECT id, event_text, importance, emotional_weight, timestamp, retention_tier
                       FROM episodic_events
                       WHERE username = ? AND archived = 0""",
                    (username,)
                ).fetchall()

                for row in rows:
                    eid = row["id"]
                    age_seconds = now - row["timestamp"]
                    age_days = age_seconds / 86400.0
                    tier = row["retention_tier"] or "permanent"

                    if tier == "temporary":
                        # temporary: delete after 1 day
                        if age_days >= 1.0:
                            c.execute("DELETE FROM episodic_events WHERE id = ?", (eid,))
                            if self._chroma_col:
                                try:
                                    self._chroma_col.delete(ids=[eid])
                                except Exception:
                                    pass
                            stats["deleted"] += 1
                        else:
                            stats["retained"] += 1

                    elif tier == "weekly":
                        # weekly: archive after 7 days
                        if age_days >= 7.0:
                            summary = row["event_text"][:80] + "…" if len(row["event_text"]) > 80 else row["event_text"]
                            c.execute(
                                """UPDATE episodic_events
                                   SET archived = 1, archive_summary = ?
                                   WHERE id = ?""",
                                (f"[weekly-archived] {summary}", eid)
                            )
                            stats["archived"] += 1
                        else:
                            stats["retained"] += 1

                    else:  # permanent / default
                        recency     = max(0.0, 1.0 - (age_days / 90.0))
                        retention   = (row["importance"] * 0.6
                                       + row["emotional_weight"] * 0.3
                                       + recency * 0.1)

                        if retention < 0.10:
                            # Truly forgotten — delete
                            c.execute("DELETE FROM episodic_events WHERE id = ?", (eid,))
                            if self._chroma_col:
                                try:
                                    self._chroma_col.delete(ids=[eid])
                                except Exception:
                                    pass
                            stats["deleted"] += 1

                        elif retention < 0.25:
                            # Archive — compress to one-line summary
                            summary = row["event_text"][:80] + "…" if len(row["event_text"]) > 80 else row["event_text"]
                            c.execute(
                                """UPDATE episodic_events
                                   SET archived = 1, archive_summary = ?
                                   WHERE id = ?""",
                                (f"[decay-archived] {summary}", eid)
                            )
                            stats["archived"] += 1
                        else:
                            stats["retained"] += 1

        print(f"[EpisodicMemory] Decay pass: {stats}")
        return stats

    # ── Summarization / Weekly Compression ─────────────────────────────────

    def compress_old_episodes(self, username: str):
        """Weekly/daily task to compress faded archived memories into rolling summaries."""
        username = username.lower().strip()
        with _lock:
            with _conn() as c:
                # Select archived rows to aggregate
                rows = c.execute(
                    """SELECT id, event_text, timestamp FROM episodic_events
                       WHERE username = ? AND archived = 1""",
                    (username,)
                ).fetchall()
                
                if len(rows) > 10:
                    summary_lines = []
                    ids_to_delete = []
                    for row in rows:
                        ts_str = time.strftime("%Y-%m-%d", time.localtime(row["timestamp"]))
                        summary_lines.append(f"[{ts_str}] {row['event_text']}")
                        ids_to_delete.append(row["id"])
                    
                    aggregated_summary = "Aggregated faded memory: " + " | ".join(summary_lines[:20])
                    
                    # Store as a single permanent consolidated memory block
                    cons_id = str(uuid.uuid4())
                    c.execute(
                        """INSERT INTO episodic_events
                           (id, username, event_text, emotion, importance, emotional_weight,
                            timestamp, archived, confidence, source, retention_tier)
                           VALUES (?, ?, ?, 'neutral', 0.6, 0.2, ?, 0, 1.0, 'reflected', 'permanent')""",
                        (cons_id, username, aggregated_summary, time.time())
                    )
                    
                    # Clean up the single ones
                    for eid in ids_to_delete:
                        c.execute("DELETE FROM episodic_events WHERE id = ?", (eid,))
                        if self._chroma_col:
                            try:
                                self._chroma_col.delete(ids=[eid])
                            except Exception:
                                pass
                                
                    print(f"[EpisodicMemory] Compressed {len(ids_to_delete)} archived memories into aggregated block.")

    # ── Summarization ─────────────────────────────────────────────────────

    def build_context_string(self, username: str, query: str = "", limit: int = 5) -> str:
        """
        Build a prompt-injectable context string of relevant recent episodes.
        """
        username = username.lower().strip()

        if query:
            episodes = self.recall(username, query, limit=limit)
        else:
            episodes = self.get_recent(username, n=limit)

        if not episodes:
            return ""

        lines = ["[Recent Episodes ARIA Remembers:"]
        for ep in episodes:
            ts   = time.strftime("%b %d", time.localtime(ep.get("timestamp", 0)))
            emo  = ep.get("emotion", "neutral")
            text = ep.get("event_text", "")
            lines.append(f"  • {ts} [{emo}]: {text}")
        lines.append("]")
        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────────

    def _sqlite_recall(
        self,
        username: str,
        query: str,
        limit: int,
        emotion_filter: Optional[str],
    ) -> List[Dict]:
        """Keyword overlap fallback when ChromaDB is unavailable."""
        emotion_clause = f"AND emotion = '{emotion_filter}'" if emotion_filter else ""
        with _conn() as c:
            rows = c.execute(
                f"""SELECT id, event_text, emotion, importance, emotional_weight, timestamp, confidence, source, retention_tier
                    FROM episodic_events
                    WHERE username = ? {emotion_clause} AND archived = 0
                    ORDER BY timestamp DESC LIMIT 50""",
                (username,)
            ).fetchall()

        query_words = set(query.lower().split())
        scored = []
        for row in rows:
            text_words = set(row["event_text"].lower().split())
            overlap    = len(query_words & text_words)
            if overlap > 0:
                sim = overlap / float(len(query_words) + len(text_words) - overlap)
                scored.append((sim, dict(row)))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:limit]]
