"""
skills/reflection_engine.py — ARIA Reflection Engine
===================================================

Analyzes recent interactions asynchronously to extract high-level learnings,
tracks the relationship vector, proposes candidate updates, checks for contradictions,
and quarantines low-confidence inferences.
"""

import sqlite3
import json
import time
import os
import threading
from typing import Dict, Any, List, Tuple, Optional

DB_PATH = "aria_memory.db"
_lock = threading.Lock()

class ReflectionEngine:
    _instance = None
    _cls_lock = threading.Lock()
    MAX_REFLECTION_DEPTH = 3

    def __new__(cls, *args, **kwargs):
        with cls._cls_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._reflection_depth = 0
                inst._init_db()
                cls._instance = inst
            return cls._instance

    def _get_conn(self) -> sqlite3.Connection:
        db = getattr(self, "db_path", DB_PATH)
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            # Relationship Metrics (Vector)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS relationship_vector (
                    username TEXT PRIMARY KEY,
                    trust REAL DEFAULT 10.0,
                    comfort REAL DEFAULT 10.0,
                    interaction_depth REAL DEFAULT 10.0,
                    emotional_openness REAL DEFAULT 10.0,
                    updated_at REAL NOT NULL
                )
            """)
            # Candidate Semantic Updates
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS candidate_semantic_updates (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    key_pref TEXT NOT NULL,
                    val_pref TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT DEFAULT 'pending_validation',
                    contradiction_flag INTEGER DEFAULT 0,
                    occurrences INTEGER DEFAULT 1,
                    updated_at REAL NOT NULL
                )
            """)
            conn.commit()

            # Schema migration
            cursor.execute("PRAGMA table_info(candidate_semantic_updates)")
            cols = {row[1] for row in cursor.fetchall()}
            if "evidence" not in cols:
                cursor.execute("ALTER TABLE candidate_semantic_updates ADD COLUMN evidence TEXT DEFAULT '[]'")
            if "reasoning_trace" not in cols:
                cursor.execute("ALTER TABLE candidate_semantic_updates ADD COLUMN reasoning_trace TEXT")
            if "reasoning_confidence" not in cols:
                cursor.execute("ALTER TABLE candidate_semantic_updates ADD COLUMN reasoning_confidence REAL DEFAULT 1.0")
            conn.commit()

    # ── Relationship Vector API ──────────────────────────────────────────

    def get_relationship_vector(self, username: str) -> Dict[str, float]:
        username = username.lower().strip()
        if not hasattr(self, '_in_memory_metrics'):
            self._in_memory_metrics = {}
        if username in self._in_memory_metrics:
            return self._in_memory_metrics[username]

        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT trust, comfort, interaction_depth, emotional_openness FROM relationship_vector WHERE username = ?",
                (username,)
            ).fetchone()
        
        if row:
            metrics = dict(row)
        else:
            # Insert defaults once in DB
            now = time.time()
            with _lock:
                with self._get_conn() as conn:
                    conn.execute(
                        """INSERT OR IGNORE INTO relationship_vector 
                           (username, trust, comfort, interaction_depth, emotional_openness, updated_at)
                           VALUES (?, 10.0, 10.0, 10.0, 10.0, ?)""",
                        (username, now)
                    )
                    conn.commit()
            metrics = {"trust": 10.0, "comfort": 10.0, "interaction_depth": 10.0, "emotional_openness": 10.0}
        
        self._in_memory_metrics[username] = metrics
        return metrics

    def update_relationship_metrics(self, username: str, delta_trust: float = 0.0, delta_comfort: float = 0.0, delta_depth: float = 0.0, delta_openness: float = 0.0, hostile: bool = False):
        username = username.lower().strip()
        metrics = self.get_relationship_vector(username)
        
        # Enforce trust floor of 7.0 (under normal circumstances, but 0.0 if hostile)
        floor = 0.0 if hostile else 7.0
        new_trust = max(floor, min(10.0, metrics["trust"] + delta_trust))
        new_comfort = max(0.0, min(10.0, metrics["comfort"] + delta_comfort))
        new_depth = max(0.0, min(10.0, metrics["interaction_depth"] + delta_depth))
        new_openness = max(0.0, min(10.0, metrics["emotional_openness"] + delta_openness))
        
        metrics["trust"] = new_trust
        metrics["comfort"] = new_comfort
        metrics["interaction_depth"] = new_depth
        metrics["emotional_openness"] = new_openness

    def persist_relationship_metrics(self, username: str):
        """Save the in-memory relationship metrics to SQLite database. Call on clean shutdown."""
        username = username.lower().strip()
        if hasattr(self, '_in_memory_metrics') and username in self._in_memory_metrics:
            metrics = self._in_memory_metrics[username]
            now = time.time()
            with _lock:
                with self._get_conn() as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO relationship_vector
                           (username, trust, comfort, interaction_depth, emotional_openness, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (username, metrics["trust"], metrics["comfort"], metrics["interaction_depth"], metrics["emotional_openness"], now)
                    )
                    conn.commit()
            print(f"[ReflectionEngine] Persisted relationship metrics for user '{username}': {metrics}")

    def get_relationship_labels(self, username: str) -> Dict[str, str]:
        """Provides human-readable soft labels for dashboard mapping."""
        metrics = self.get_relationship_vector(username)
        
        # Soft label for familiarity (combination of trust & comfort)
        fam_score = (metrics["trust"] + metrics["comfort"]) / 2.0
        if fam_score >= 8.0:
            fam_label = "Close Companion"
        elif fam_score >= 5.0:
            fam_label = "Friend / Evolving"
        elif fam_score >= 2.5:
            fam_label = "Growing"
        else:
            fam_label = "Acquaintance"
            
        # Soft label for interaction depth
        depth = metrics["interaction_depth"]
        if depth >= 7.5:
            depth_label = "Deep"
        elif depth >= 4.0:
            depth_label = "Medium"
        else:
            depth_label = "Surface-level"
            
        return {
            "familiarity": fam_label,
            "interaction_depth": depth_label
        }

    # ── Semantic Updates & Contradiction/Quarantine ───────────────────────

    def detect_contradiction(self, username: str, key: str, proposed_value: str) -> Tuple[bool, str]:
        """Checks proposed semantic updates against existing preferences/personal notes."""
        username = username.lower().strip()
        key = key.lower().strip()
        proposed_value_lower = proposed_value.lower().strip()

        with self._get_conn() as conn:
            # 1. Check SQLite user_preferences
            cursor = conn.cursor()
            cursor.execute(
                "SELECT pref_value FROM user_preferences WHERE username = ? AND pref_key = ?",
                (username, key)
            )
            row = cursor.fetchone()
            if row:
                existing_val = row[0].lower().strip()
                # Simple contradiction rules (e.g. yes/no, different names, opposites)
                if (existing_val == "yes" and proposed_value_lower == "no") or (existing_val == "no" and proposed_value_lower == "yes"):
                    return True, f"Direct preference conflict: key '{key}' already set to '{row[0]}'."
                if existing_val != proposed_value_lower:
                    # Let's flag warning if setting contradicts
                    return True, f"Value mismatch: key '{key}' is already '{row[0]}' but proposing '{proposed_value}'."

            # 2. Check general personal notes for opposites
            cursor.execute(
                "SELECT content FROM personal_notes WHERE category = ? AND status = 'active'",
                (key,)
            )
            notes = cursor.fetchall()
            for (note_content,) in notes:
                n_lower = note_content.lower()
                if "not" in proposed_value_lower and proposed_value_lower.replace("not", "").strip() in n_lower:
                    return True, f"Semantic contradiction with note: '{note_content}'"
                if "not" in n_lower and n_lower.replace("not", "").strip() in proposed_value_lower:
                    return True, f"Semantic contradiction with note: '{note_content}'"

        return False, ""

    def propose_candidate_update(self, username: str, key: str, value: str, confidence: float, source: str, evidence: List[str] = None, reasoning_trace: str = None, reasoning_confidence: float = 1.0):
        """Proposes a candidate semantic update instead of writing to profile directly."""
        username = username.lower().strip()
        key = key.lower().strip()
        evidence_json = json.dumps(evidence or [])
        
        # Check for contradictions first
        is_contradiction, reason = self.detect_contradiction(username, key, value)
        
        status = "pending_validation"
        contradiction_flag = 0
        if is_contradiction:
            status = "quarantined"
            contradiction_flag = 1
            print(f"[ReflectionEngine] Contradiction detected: {reason}. Quarantining.")
        elif confidence < 0.6 and source == "inferred":
            # Low confidence inferred update goes into Hallucination Quarantine
            status = "quarantined"
            print(f"[ReflectionEngine] Low confidence inferred memory. Quarantining in hallucination quarantine.")
 
        cand_id = f"{username}_{key}_{hash(value)}"
        now = time.time()
        
        with _lock:
            with self._get_conn() as conn:
                # Check if candidate already exists
                row = conn.execute(
                    "SELECT occurrences, status, evidence, reasoning_trace FROM candidate_semantic_updates WHERE id = ?",
                    (cand_id,)
                ).fetchone()
                
                if row:
                    occurrences = row["occurrences"] + 1
                    # Merge evidence
                    old_ev = json.loads(row["evidence"] or "[]")
                    new_ev = list(set(old_ev + (evidence or [])))
                    evidence_json = json.dumps(new_ev)
                    
                    # Carry forward or merge reasoning trace
                    saved_trace = row["reasoning_trace"] or reasoning_trace
 
                    # If it receives support multiple times, we can promote it
                    new_status = row["status"]
                    if new_status == "pending_validation" and occurrences >= 3:
                        new_status = "validated"
                        print(f"[ReflectionEngine] Candidate '{key}' validated with {occurrences} occurrences. Promoting to profile.")
                        self._promote_to_profile(username, key, value, confidence, new_ev, saved_trace, reasoning_confidence)
                        
                    conn.execute(
                        """UPDATE candidate_semantic_updates 
                           SET occurrences = ?, status = ?, updated_at = ?, evidence = ?,
                               reasoning_trace = ?, reasoning_confidence = ?
                           WHERE id = ?""",
                        (occurrences, new_status, now, evidence_json, saved_trace, reasoning_confidence, cand_id)
                    )
                else:
                    conn.execute(
                        """INSERT INTO candidate_semantic_updates 
                           (id, username, key_pref, val_pref, source, confidence, status, contradiction_flag, occurrences, updated_at, evidence, reasoning_trace, reasoning_confidence)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                        (cand_id, username, key, value, source, confidence, status, contradiction_flag, now, evidence_json, reasoning_trace, reasoning_confidence)
                    )
                conn.commit()
 
    def _promote_to_profile(self, username: str, key: str, value: str, confidence: float = 1.0, evidence: List[str] = None, reasoning_trace: str = None, reasoning_confidence: float = 1.0):
        """Writes validated candidates directly into profile tables using MemoryManager."""
        try:
            from skills.memory_manager import MemoryManager
            mm = MemoryManager()
            mm.set_preference(username, key, value, confidence=confidence, evidence=evidence, reasoning_trace=reasoning_trace, reasoning_confidence=reasoning_confidence)
            print(f"[ReflectionEngine] Promoted preference key='{key}' value='{value}' to user preferences via MemoryManager.")
        except Exception as e:
            print(f"[ReflectionEngine] Failed to promote preference to MemoryManager: {e}")

    # ── Asynchronous Retrospective Reflection ─────────────────────────────

    def reflect_asynchronously(self, username: str, recent_episodes: List[Dict[str, Any]], recent_task_results: List[Dict[str, Any]]):
        """Launches the reflection loop in a low priority background thread."""
        def run():
            try:
                # Set lower thread priority if possible (Windows/Python doesn't expose it easily, we just yield/sleep)
                time.sleep(0.5)
                self._run_reflection(username, recent_episodes, recent_task_results)
            except Exception as e:
                print(f"[ReflectionEngine] Background reflection failed: {e}")
                
        t = threading.Thread(target=run, daemon=True)
        t.start()

    def _run_reflection(self, username: str, recent_episodes: List[Dict[str, Any]], recent_task_results: List[Dict[str, Any]]):
        """Evaluates failures, updates relationship vector, checks consistency, decays stale states, and extracts grounded facts."""
        if self._reflection_depth >= self.MAX_REFLECTION_DEPTH:
            print(f"[ReflectionEngine] Max reflection depth ({self.MAX_REFLECTION_DEPTH}) reached. Skipping to prevent recursion.")
            return
        self._reflection_depth += 1
        try:
            self._run_reflection_inner(username, recent_episodes, recent_task_results)
        finally:
            self._reflection_depth -= 1

    def _run_reflection_inner(self, username: str, recent_episodes: List[Dict[str, Any]], recent_task_results: List[Dict[str, Any]]):
        """Inner reflection logic, guarded by recursion depth limiter."""
        print(f"[ReflectionEngine] Running retrospective reflection safeguards pass for '{username}'...")
        
        # 1. Retrieve relationship inertia (count of high-importance memories)
        num_important_memories = 0
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM user_preferences WHERE username = ? AND confidence >= 0.8",
                    (username.lower().strip(),)
                )
                row = cursor.fetchone()
                if row:
                    num_important_memories = row[0]
        except Exception as e:
            print(f"[ReflectionEngine] Failed to query preference count for inertia: {e}")

        # Scale decay down: more memories = higher inertia
        inertia = 1.0 / (1.0 + 0.1 * num_important_memories)

        # 2. Relationship Decay: apply soft 1-3% drift per 24 hours of inactivity
        now = time.time()
        metrics = self.get_relationship_vector(username)
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT updated_at FROM relationship_vector WHERE username = ?", (username.lower().strip(),))
                row = cursor.fetchone()
                if row:
                    elapsed_seconds = now - row[0]
                    if elapsed_seconds >= 86400.0:
                        elapsed_days = elapsed_seconds / 86400.0
                        
                        # 1% trust decay
                        delta_trust = -0.1 * elapsed_days * inertia
                        # 3% other metrics decay
                        delta_comfort = -0.3 * elapsed_days * inertia
                        delta_depth = -0.3 * elapsed_days * inertia
                        delta_openness = -0.3 * elapsed_days * inertia

                        print(f"[ReflectionEngine] Applying relationship decay for '{username}' (inertia: {inertia:.2f}, days: {elapsed_days:.2f})")
                        self.update_relationship_metrics(
                            username=username,
                            delta_trust=delta_trust,
                            delta_comfort=delta_comfort,
                            delta_depth=delta_depth,
                            delta_openness=delta_openness
                        )
                        
                        from skills.memory_manager import MemoryManager
                        MemoryManager().log_cognition_audit(
                            "RELATIONSHIP_DECAY",
                            f"Decayed relationship metrics for user '{username}' due to inactivity.",
                            {"elapsed_days": elapsed_days, "inertia": inertia}
                        )
        except Exception as decay_err:
            print(f"[ReflectionEngine] Inactivity decay calculation failure: {decay_err}")

        # 3. Update relationship metrics based on recent interaction sentiments
        sentiment_delta = 0.0
        depth_delta = 0.05 # Speaking increases depth
        
        for ep in recent_episodes:
            emo = ep.get("emotion", "neutral")
            if emo in ["happy", "excited"]:
                sentiment_delta += 0.05
            elif emo in ["stressed", "anxious", "sad"]:
                sentiment_delta -= 0.01
                
        # Raw deltas before memory poisoning clamping
        raw_trust_change = max(-0.5, min(0.5, sentiment_delta))
        raw_comfort_change = max(-0.5, min(0.5, sentiment_delta * 0.5))

        # Memory Poisoning Resistance: clamp per-pass deltas via SelfModelValidator
        try:
            from skills.self_model_validator import SelfModelValidator
            smv = SelfModelValidator()
            bounded_trust_change, bounded_comfort_change = smv.enforce_memory_poisoning_resistance(
                username, raw_trust_change, raw_comfort_change
            )
        except Exception as _smv_err:
            print(f"[ReflectionEngine] SelfModelValidator unavailable: {_smv_err}")
            bounded_trust_change, bounded_comfort_change = raw_trust_change, raw_comfort_change

        # Check if user interactions are hostile
        hostile = False
        for ep in recent_episodes:
            text = ep.get("event_text", "").lower()
            if any(w in text for w in ["stupid", "idiot", "dumb", "useless", "fool", "hate you", "shut up", "trash", "garbage"]):
                hostile = True
                break

        self.update_relationship_metrics(
            username=username,
            delta_trust=bounded_trust_change,
            delta_comfort=bounded_comfort_change,
            delta_depth=depth_delta,
            delta_openness=0.02 if sentiment_delta > 0 else 0.0,
            hostile=hostile
        )
        
        # 4. Strategy reinforcement weight updates
        for task in recent_task_results:
            goal = task.get("goal", "")
            success = task.get("outcome") == "success"
            steps = task.get("steps", [])
            
            from skills.memory_skill import MemorySkill
            skill = MemorySkill()
            for step in steps:
                action = step.get("action", "")
                if action:
                    skill.record_strategy_outcome(action, success=success)

        # 5. Preference Confidence Decay over time (1% per day for stale preferences)
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, pref_key, pref_value, updated_at, confidence FROM user_preferences WHERE username = ?",
                    (username.lower().strip(),)
                )
                prefs = cursor.fetchall()
                for pref in prefs:
                    pref_id = pref["id"]
                    key = pref["pref_key"]
                    val = pref["pref_value"]
                    p_updated = pref["updated_at"]
                    p_conf = pref["confidence"]
                    
                    elapsed_days = (now - p_updated) / 86400.0
                    if elapsed_days >= 7.0:
                        decayed_conf = max(0.0, p_conf - (0.01 * elapsed_days))
                        if decayed_conf < 0.4 and p_conf >= 0.4:
                            # Flag unresolved ambiguity and move to quarantined candidate updates
                            cursor.execute("UPDATE user_preferences SET confidence = ?, unresolved_ambiguity = 1 WHERE id = ?", (decayed_conf, pref_id))
                            self.propose_candidate_update(
                                username=username,
                                key=key,
                                value=val,
                                confidence=decayed_conf,
                                source="stale_decay",
                                evidence=["stale_confidence_decay"]
                            )
                            from skills.memory_manager import MemoryManager
                            MemoryManager().log_cognition_audit(
                                "PREFERENCE_CONFIDENCE_DECAY",
                                f"Preference '{key}' confidence decayed to {decayed_conf:.2f} due to staleness. Flagged unresolved.",
                                {"pref_key": key, "old_confidence": p_conf, "new_confidence": decayed_conf}
                            )
                        else:
                            cursor.execute("UPDATE user_preferences SET confidence = ? WHERE id = ?", (decayed_conf, pref_id))
                conn.commit()
        except Exception as pref_decay_err:
            print(f"[ReflectionEngine] Preference confidence decay failed: {pref_decay_err}")

        # 6. Heuristic pattern-based fact extraction with grounding validation
        import re
        patterns = [
            (r"(?:user|i)\s+(?:prefer|likes|prefers|loves)\s+([a-zA-Z0-9_\-\s]{2,15})\s+over\s+([a-zA-Z0-9_\-\s]{2,15})", "preference"),
            (r"(?:user|i)\s+(?:prefer|likes|prefers|loves|uses)\s+([a-zA-Z0-9_\-\s]{2,20})", "preference"),
            (r"(?:favorite|fav)\s+(?:editor|language|theme|color|tool)\s+is\s+([a-zA-Z0-9_\-\s]{2,20})", "preference"),
        ]
        
        for ep in recent_episodes:
            text = ep.get("event_text", "")
            ep_id = ep.get("id")
            if not text or not ep_id:
                continue
                
            for pattern, cat in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    if isinstance(match, tuple):
                        val = match[0].strip().lower()
                        key = "programming_language"
                    else:
                        val = match.strip().lower()
                        if any(w in val for w in ["dark", "light", "theme"]):
                            key = "theme"
                        elif any(w in val for w in ["vscode", "vim", "nano", "sublime"]):
                            key = "editor"
                        elif any(w in val for w in ["python", "javascript", "golang", "c++", "rust"]):
                            key = "programming_language"
                        else:
                            key = "general_preference"
                    
                    # Reflection Grounding Validation Check
                    val_words = set(val.split())
                    text_words = set(text.lower().split())
                    if not (val_words & text_words):
                        print(f"[ReflectionEngine] Grounding verification FAILED for '{key}'='{val}'. Hallucinated fact. Skipping.")
                        continue
                        
                    # Propose candidate update with evidence links and reasoning trace
                    trace = f"Extracted from episode {ep_id}: '{text}' via pattern match."
                    self.propose_candidate_update(
                        username=username,
                        key=key,
                        value=val,
                        confidence=0.8,
                        source="reflected",
                        evidence=[ep_id],
                        reasoning_trace=trace,
                        reasoning_confidence=0.6
                    )

        # 7. Self-Model Consistency Check (relationship vector bounds)
        self.self_model_consistency_check(username)

        # 8. Full Self-Model Validation (trait conflicts, instability, drift)
        try:
            from skills.self_model_validator import SelfModelValidator
            SelfModelValidator().run_full_validation_async(username)
        except Exception as _smv_err:
            print(f"[ReflectionEngine] SelfModelValidator async launch failed: {_smv_err}")

    def self_model_consistency_check(self, username: str):
        """Ensures relationship metrics are strictly bounded, limits trust/comfort growth, and checks personality traits."""
        username = username.lower().strip()
        metrics = self.get_relationship_vector(username)
        
        # 1. Enforce strict boundaries [0.0, 10.0]
        trust = max(0.0, min(10.0, metrics["trust"]))
        comfort = max(0.0, min(10.0, metrics["comfort"]))
        depth = max(0.0, min(10.0, metrics["interaction_depth"]))
        openness = max(0.0, min(10.0, metrics["emotional_openness"]))

        # 2. Scale down comfort & openness if trust is low
        if trust < 3.0:
            if comfort > max(3.0, trust) or openness > max(3.0, trust):
                comfort = min(comfort, max(3.0, trust))
                openness = min(openness, max(3.0, trust))
                print(f"[ReflectionEngine] Consistency Check: Trust is critically low ({trust:.1f}). Comfort/Openness capped to prevent identity fragmentation.")

        # 3. Correct trust vs comfort discrepancy
        if trust > 5.0 and comfort < 1.5:
            comfort = 1.5
            print("[ReflectionEngine] Consistency Check: Trust is high but comfort is low. Adjusting comfort upward to prevent fragmentation.")

        # Update if changed in-memory
        if trust != metrics["trust"] or comfort != metrics["comfort"] or depth != metrics["interaction_depth"] or openness != metrics["emotional_openness"]:
            metrics["trust"] = trust
            metrics["comfort"] = comfort
            metrics["interaction_depth"] = depth
            metrics["emotional_openness"] = openness

    # ── Task Replay File Storage ──────────────────────────────────────────

    def save_task_replay(self, task_id: str, goal: str, steps: List[Dict[str, Any]], events: List[Dict[str, Any]], reflections: str):
        """Saves a replay package to /replays/task_id/ directory."""
        base_dir = os.path.join("replays", task_id)
        try:
            os.makedirs(base_dir, exist_ok=True)
            
            # 1. Save trace.json (goal + step details)
            with open(os.path.join(base_dir, "trace.json"), "w", encoding="utf-8") as f:
                json.dump({"task_id": task_id, "goal": goal, "steps": steps}, f, indent=2)
                
            # 2. Save events.json (all runtime ticker events)
            with open(os.path.join(base_dir, "events.json"), "w", encoding="utf-8") as f:
                json.dump(events, f, indent=2)
                
            # 3. Save reflections.json
            with open(os.path.join(base_dir, "reflections.json"), "w", encoding="utf-8") as f:
                json.dump({"reflections": reflections}, f, indent=2)
                
            print(f"[ReflectionEngine] Saved complete task replay to '{base_dir}'.")
        except Exception as e:
            print(f"[ReflectionEngine] Failed to save task replay: {e}")
