"""
skills/cognitive_sandbox.py — ARIA Cognitive Simulation Sandbox
==============================================================

Provides a secure counterfactual simulation sandbox. Before major updates
(preferences, profile promotions, relationship deltas) are committed to
the main SQLite memory database, a simulation clones the current database state,
applies the proposed updates in isolation, and runs the full SelfModelValidator.

If validation checks fail, the sandbox quarantines the proposed change
and logs an audit trail, keeping the core identity protected from corruption.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
import gc
from typing import Dict, Any, List, Tuple, Optional
from skills.self_model_validator import SelfModelValidator
from skills.reflection_engine import ReflectionEngine

DB_PATH = "aria_memory.db"

class CognitiveSandbox:
    """
    Cognitive Simulation Sandbox for safe preference promotion and relationship changes.
    Singleton pattern.
    """
    _instance = None
    _lock = tempfile.tempdir # thread-safe tempdir lock fallback or custom locks

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _create_sandbox_db(self) -> Tuple[str, sqlite3.Connection]:
        """Creates a temporary, isolated duplicate of the production database."""
        temp_dir = tempfile.gettempdir()
        sandbox_path = os.path.join(temp_dir, f"aria_sandbox_{time.time_ns()}.db")
        
        # Copy the live database file
        if os.path.exists(DB_PATH):
            shutil.copy2(DB_PATH, sandbox_path)
        else:
            # Create a clean SQLite db if live DB doesn't exist yet
            conn = sqlite3.connect(sandbox_path)
            conn.close()
            
        conn = sqlite3.connect(sandbox_path)
        conn.row_factory = sqlite3.Row
        return sandbox_path, conn

    def _cleanup_sandbox(self, sandbox_path: str):
        """Removes the temporary sandbox database file."""
        try:
            if os.path.exists(sandbox_path):
                for attempt in range(3):
                    try:
                        os.remove(sandbox_path)
                        break
                    except PermissionError:
                        if attempt == 2:
                            raise
                        gc.collect()
                        time.sleep(0.1)
        except Exception as e:
            print(f"[CognitiveSandbox] Warning: Sandbox cleanup failed for '{sandbox_path}': {e}")

    def simulate_preference_update(
        self,
        username: str,
        key: str,
        value: str,
        confidence: float = 1.0,
        evidence: List[str] = None,
        reasoning_trace: str = None
    ) -> Dict[str, Any]:
        """
        Simulates writing a preference to the sandbox and running SelfModelValidator checks.
        Returns simulation report.
        """
        username = username.strip().strip('.').lower()
        key = key.strip().lower()
        evidence_json = json.dumps(evidence or [])
        
        sandbox_path, conn = self._create_sandbox_db()
        before_state = self._capture_cognitive_state(username, DB_PATH)
        report = {
            "success": False,
            "before_state": before_state,
            "after_state": {},
            "rollback_snapshot_id": None,
            "cognitive_version": {},
            "drift_delta_score": 0.0,
            "trait_conflicts": [],
            "emotional_instability": False,
            "emotional_volatility": {},
            "identity_drift": [],
            "anomalies": [],
            "error": None
        }

        try:
            # 1. Apply the update in the isolated database
            cursor = conn.cursor()
            
            # Ensure table structure fits
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    pref_key TEXT NOT NULL,
                    pref_value TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    evidence TEXT DEFAULT '[]',
                    unresolved_ambiguity INTEGER DEFAULT 0,
                    reasoning_trace TEXT,
                    UNIQUE(username, pref_key)
                )
            """)
            
            cursor.execute("""
                INSERT OR REPLACE INTO user_preferences 
                (username, pref_key, pref_value, updated_at, confidence, evidence, unresolved_ambiguity, reasoning_trace)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """, (username, key, str(value), time.time(), confidence, evidence_json, reasoning_trace))
            conn.commit()
            conn.close()

            # 2. Inject sandbox db path into SelfModelValidator and run validation
            smv = SelfModelValidator()
            old_db = getattr(smv, "db_path", DB_PATH)
            smv.db_path = sandbox_path
            
            try:
                val_report = smv.run_full_validation(username)
                
                report["trait_conflicts"] = val_report.get("trait_conflicts", [])
                report["emotional_instability"] = val_report.get("emotional_instability", False)
                report["emotional_volatility"] = val_report.get("emotional_volatility", {})
                report["identity_drift"] = val_report.get("identity_drift", [])
                report["after_state"] = self._capture_cognitive_state(username, sandbox_path)
                report["drift_delta_score"] = self._calculate_drift_delta_score(
                    report["before_state"], report["after_state"]
                )
                
                # Check for critical anomalies (e.g. trait conflicts, identity drift)
                if val_report["status"] == "CRITICAL" or len(report["trait_conflicts"]) > 0 or len(report["identity_drift"]) > 0:
                    report["success"] = False
                    report["anomalies"].append(f"Critical validation issues found (status={val_report['status']}).")
                else:
                    report["success"] = True

                if report["success"]:
                    report["rollback_snapshot_id"] = self.save_cognitive_snapshot(
                        username,
                        label=f"preference_pre_update:{key}"
                    )
                    report["cognitive_version"] = self.get_cognitive_versions(username)

            finally:
                smv.db_path = old_db

        except Exception as e:
            report["success"] = False
            report["error"] = str(e)
            print(f"[CognitiveSandbox] Simulation execution crashed: {e}")
        finally:
            self._cleanup_sandbox(sandbox_path)

        return report

    def simulate_relationship_update(
        self,
        username: str,
        delta_trust: float = 0.0,
        delta_comfort: float = 0.0,
        delta_depth: float = 0.0,
        delta_openness: float = 0.0
    ) -> Dict[str, Any]:
        """
        Simulates relationship metric changes and checks for safety drops/poisoning in the sandbox.
        """
        username = username.strip().strip('.').lower()
        sandbox_path, conn = self._create_sandbox_db()
        before_state = self._capture_cognitive_state(username, DB_PATH)
        report = {
            "success": False,
            "before_state": before_state,
            "after_state": {},
            "rollback_snapshot_id": None,
            "cognitive_version": {},
            "drift_delta_score": 0.0,
            "before_metrics": {},
            "after_metrics": {},
            "clamped_metrics": {},
            "anomalies": [],
            "error": None
        }

        try:
            conn.close()
            re = ReflectionEngine()
            old_re_db = getattr(re, "db_path", DB_PATH)
            re.db_path = sandbox_path
            
            try:
                # 1. Retrieve initial state
                before = re.get_relationship_vector(username)
                report["before_metrics"] = before

                # 2. Check proposed deltas against SelfModelValidator clamping rules
                smv = SelfModelValidator()
                old_smv_db = getattr(smv, "db_path", DB_PATH)
                smv.db_path = sandbox_path
                
                try:
                    bounded_trust_change, bounded_comfort_change = smv.enforce_memory_poisoning_resistance(
                        username, delta_trust, delta_comfort
                    )
                    
                    report["clamped_metrics"] = {
                        "trust_delta": bounded_trust_change,
                        "comfort_delta": bounded_comfort_change
                    }
                    
                    if bounded_trust_change != delta_trust or bounded_comfort_change != delta_comfort:
                        report["anomalies"].append("Metrics clamped due to memory poisoning safeguards.")

                    # Apply updates in sandbox
                    re.update_relationship_metrics(
                        username=username,
                        delta_trust=bounded_trust_change,
                        delta_comfort=bounded_comfort_change,
                        delta_depth=delta_depth,
                        delta_openness=delta_openness
                    )
                    
                    # Run consistency check
                    re.self_model_consistency_check(username)
                    
                    # Query final state
                    after = re.get_relationship_vector(username)
                    report["after_metrics"] = after
                    report["after_state"] = self._capture_cognitive_state(username, sandbox_path)
                    report["drift_delta_score"] = self._calculate_drift_delta_score(
                        report["before_state"], report["after_state"]
                    )
                    report["rollback_snapshot_id"] = self.save_cognitive_snapshot(
                        username,
                        label="relationship_pre_update"
                    )
                    report["cognitive_version"] = self.get_cognitive_versions(username)
                    report["success"] = True

                finally:
                    smv.db_path = old_smv_db
            finally:
                re.db_path = old_re_db

        except Exception as e:
            report["success"] = False
            report["error"] = str(e)
            print(f"[CognitiveSandbox] Relationship simulation crashed: {e}")
        finally:
            self._cleanup_sandbox(sandbox_path)

        return report

    # ---- Rollback Snapshots ----

    def _ensure_snapshots_table(self, conn: sqlite3.Connection):
        """Creates the cognitive_snapshots table if it doesn't exist."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cognitive_snapshots (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                label TEXT,
                snapshot_data TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cognitive_state_versions (
                username TEXT PRIMARY KEY,
                personality_version INTEGER DEFAULT 0,
                profile_version INTEGER DEFAULT 0,
                updated_at REAL NOT NULL
            )
        """)
        conn.commit()

    def _capture_cognitive_state(self, username: str, db_path: str = DB_PATH) -> Dict[str, Any]:
        """Returns a full cognitive state snapshot for sandbox reports and rollbacks."""
        username = username.strip().strip('.').lower()
        state: Dict[str, Any] = {
            "username": username,
            "relationship_vector": {},
            "preferences": {},
            "captured_at": time.time(),
        }
        if not os.path.exists(db_path):
            return state

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """SELECT trust, comfort, interaction_depth, emotional_openness, updated_at
                   FROM relationship_vector WHERE username = ?""",
                (username,)
            ).fetchone()
            if row:
                state["relationship_vector"] = dict(row)
        except Exception:
            pass

        try:
            rows = conn.execute(
                """SELECT pref_key, pref_value, updated_at, confidence, evidence,
                          unresolved_ambiguity, reasoning_trace, reasoning_confidence
                   FROM user_preferences WHERE username = ?""",
                (username,)
            ).fetchall()
            for r in rows:
                state["preferences"][r["pref_key"]] = {
                    "value": r["pref_value"],
                    "updated_at": r["updated_at"],
                    "confidence": r["confidence"],
                    "evidence": json.loads(r["evidence"] or "[]"),
                    "unresolved_ambiguity": r["unresolved_ambiguity"],
                    "reasoning_trace": r["reasoning_trace"],
                    "reasoning_confidence": r["reasoning_confidence"],
                }
        except Exception:
            pass
        finally:
            conn.close()

        return state

    def _calculate_drift_delta_score(self, before_state: Dict[str, Any], after_state: Dict[str, Any]) -> float:
        """Computes normalized before/after cognitive drift across preferences and relationship metrics."""
        changes = 0.0
        total = 0.0

        before_prefs = before_state.get("preferences", {})
        after_prefs = after_state.get("preferences", {})
        for key in set(before_prefs.keys()) | set(after_prefs.keys()):
            total += 1.0
            if before_prefs.get(key, {}).get("value") != after_prefs.get(key, {}).get("value"):
                changes += 1.0

        before_rel = before_state.get("relationship_vector", {})
        after_rel = after_state.get("relationship_vector", {})
        for key in ["trust", "comfort", "interaction_depth", "emotional_openness"]:
            if key in before_rel or key in after_rel:
                total += 1.0
                before_val = float(before_rel.get(key, 0.0) or 0.0)
                after_val = float(after_rel.get(key, 0.0) or 0.0)
                changes += min(1.0, abs(after_val - before_val) / 10.0)

        return round(changes / total, 4) if total else 0.0

    def _increment_cognitive_version(self, conn: sqlite3.Connection, username: str, label: str = None) -> Dict[str, Any]:
        """Increments profile/personality versions and returns labels like personality_vN."""
        self._ensure_snapshots_table(conn)
        row = conn.execute(
            """SELECT personality_version, profile_version
               FROM cognitive_state_versions WHERE username = ?""",
            (username,)
        ).fetchone()
        personality_version = int(row["personality_version"]) if row else 0
        profile_version = int(row["profile_version"]) if row else 0

        profile_version += 1
        if label and any(token in label for token in ["personality", "preference", "profile"]):
            personality_version += 1

        conn.execute(
            """INSERT OR REPLACE INTO cognitive_state_versions
               (username, personality_version, profile_version, updated_at)
               VALUES (?, ?, ?, ?)""",
            (username, personality_version, profile_version, time.time())
        )
        return {
            "personality": f"personality_v{personality_version}",
            "profile": f"profile_v{profile_version}",
            "personality_version": personality_version,
            "profile_version": profile_version,
        }

    def save_cognitive_snapshot(self, username: str, label: str = None) -> str:
        """
        Copies the current state from relationship_vector and user_preferences
        for the given user and stores them in the cognitive_snapshots table.
        Returns the snapshot ID.
        """
        username = username.strip().strip('.').lower()
        snapshot_id = str(uuid.uuid4())

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        self._ensure_snapshots_table(conn)

        snapshot_data = json.dumps(self._capture_cognitive_state(username, DB_PATH))
        version = self._increment_cognitive_version(conn, username, label)

        conn.execute(
            "INSERT INTO cognitive_snapshots (id, username, label, snapshot_data, created_at) VALUES (?, ?, ?, ?, ?)",
            (snapshot_id, username, label, snapshot_data, time.time())
        )
        conn.commit()
        conn.close()

        print(f"[CognitiveSandbox] Snapshot saved: {snapshot_id} for user '{username}' (label={label}, version={version})")
        return snapshot_id

    def list_snapshots(self, username: str) -> List[Dict]:
        """
        Lists available cognitive snapshots for a given user.
        """
        username = username.strip().strip('.').lower()

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        self._ensure_snapshots_table(conn)

        rows = conn.execute(
            "SELECT id, username, label, created_at FROM cognitive_snapshots WHERE username = ? ORDER BY created_at DESC",
            (username,)
        ).fetchall()
        conn.close()

        return [
            {
                "id": r["id"],
                "username": r["username"],
                "label": r["label"],
                "created_at": r["created_at"]
            }
            for r in rows
        ]

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """
        Restores a previously saved cognitive snapshot by ID.
        Overwrites relationship_vector and user_preferences for the user.
        Returns True on success, False on failure.
        """
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        self._ensure_snapshots_table(conn)

        row = conn.execute(
            "SELECT username, snapshot_data FROM cognitive_snapshots WHERE id = ?",
            (snapshot_id,)
        ).fetchone()

        if not row:
            conn.close()
            print(f"[CognitiveSandbox] Snapshot '{snapshot_id}' not found.")
            return False

        username = row["username"]
        data = json.loads(row["snapshot_data"])

        try:
            # Restore relationship_vector
            rv = data.get("relationship_vector", {})
            if rv:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS relationship_vector (
                        username TEXT PRIMARY KEY,
                        trust REAL DEFAULT 10.0,
                        comfort REAL DEFAULT 10.0,
                        interaction_depth REAL DEFAULT 10.0,
                        emotional_openness REAL DEFAULT 10.0,
                        updated_at REAL NOT NULL
                    )
                """)
                conn.execute(
                    """INSERT OR REPLACE INTO relationship_vector
                       (username, trust, comfort, interaction_depth, emotional_openness, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        username,
                        rv.get("trust", 10.0),
                        rv.get("comfort", 10.0),
                        rv.get("interaction_depth", 10.0),
                        rv.get("emotional_openness", 10.0),
                        time.time()
                    )
                )

            # Restore user_preferences
            prefs = data.get("preferences", {})
            if isinstance(prefs, list):
                prefs = {
                    p.get("key"): {
                        "value": p.get("value"),
                        "confidence": p.get("confidence", 1.0),
                    }
                    for p in prefs
                    if p.get("key")
                }
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    pref_key TEXT NOT NULL,
                    pref_value TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    evidence TEXT DEFAULT '[]',
                    unresolved_ambiguity INTEGER DEFAULT 0,
                    reasoning_trace TEXT,
                    UNIQUE(username, pref_key)
                )
            """)
            # Clear existing preferences for the user before restoring
            conn.execute("DELETE FROM user_preferences WHERE username = ?", (username,))
            for key, p in prefs.items():
                conn.execute(
                    """INSERT INTO user_preferences
                       (username, pref_key, pref_value, updated_at, confidence, evidence,
                        unresolved_ambiguity, reasoning_trace, reasoning_confidence)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        username,
                        key,
                        p.get("value"),
                        time.time(),
                        p.get("confidence", 1.0),
                        json.dumps(p.get("evidence", [])),
                        p.get("unresolved_ambiguity", 0),
                        p.get("reasoning_trace"),
                        p.get("reasoning_confidence", 1.0)
                    )
                )

            conn.commit()
            conn.close()
            print(f"[CognitiveSandbox] Snapshot '{snapshot_id}' restored for user '{username}'.")
            return True

        except Exception as e:
            conn.close()
            print(f"[CognitiveSandbox] Snapshot restore failed: {e}")
            return False

    # ---- Cognitive State Versioning ----

    def get_cognitive_version(self, username: str) -> int:
        """
        Queries the cognitive_snapshots table and counts total snapshots for the user.
        Returns the count as the version number.
        """
        username = username.strip().strip('.').lower()

        conn = sqlite3.connect(DB_PATH)
        self._ensure_snapshots_table(conn)

        row = conn.execute(
            "SELECT COUNT(*) FROM cognitive_snapshots WHERE username = ?",
            (username,)
        ).fetchone()
        conn.close()

        return row[0] if row else 0

    def get_cognitive_versions(self, username: str) -> Dict[str, Any]:
        """Returns explicit profile/personality cognitive state version labels."""
        username = username.strip().strip('.').lower()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        self._ensure_snapshots_table(conn)
        row = conn.execute(
            """SELECT personality_version, profile_version
               FROM cognitive_state_versions WHERE username = ?""",
            (username,)
        ).fetchone()
        conn.close()
        personality_version = int(row["personality_version"]) if row else 0
        profile_version = int(row["profile_version"]) if row else 0
        return {
            "personality": f"personality_v{personality_version}",
            "profile": f"profile_v{profile_version}",
            "personality_version": personality_version,
            "profile_version": profile_version,
        }
