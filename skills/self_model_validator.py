"""
skills/self_model_validator.py — ARIA Self-Model Consistency Validator
======================================================================

Validates ARIA's internal self-model for:
  1. Trait conflicts — contradictory personality/preference flags
  2. Emotional instability — rapid or extreme mood swings in episodic record
  3. Memory poisoning resistance — prevents a single emotional episode from
     permanently distorting personality or trust
  4. Identity drift detection — monitors cumulative shifts in core traits

The validator runs as a lightweight pass after each reflection cycle and can
also be triggered manually for audit / diagnostic purposes.

All issues are quarantined and logged — NEVER silently corrected.
"""

import sqlite3
import json
import time
import threading
from typing import Dict, Any, List, Tuple, Optional

DB_PATH = "aria_memory.db"
_lock = threading.Lock()

# ── Configurable thresholds ──────────────────────────────────────────────────

# If trust changes by more than this in a single reflection pass, it is flagged
SINGLE_PASS_TRUST_SPIKE_LIMIT = 1.5
SINGLE_PASS_COMFORT_SPIKE_LIMIT = 2.0

# Emotional instability: if the last N episodes contain more than this many
# extreme emotion swings, flag instability
EMOTION_WINDOW = 10
EMOTION_SWING_THRESHOLD = 4   # >4 swings in 10 episodes = unstable

# Memory poisoning: a single negative episode cannot drop trust by more than this
MEMORY_POISON_TRUST_FLOOR_DROP = 1.0
MEMORY_POISON_COMFORT_FLOOR_DROP = 1.5

# Identity drift: if a core trait flips >2 times within 30 days, flag drift
IDENTITY_DRIFT_WINDOW_DAYS = 30
IDENTITY_DRIFT_MAX_FLIPS = 2

# Emotional volatility: rapid metric changes in 24h
TRUST_VOLATILITY_THRESHOLD = 2.0
COMFORT_VOLATILITY_THRESHOLD = 2.5
RECENT_TRUST_SPIKE_THRESHOLD = 1.5
RECENT_COMFORT_COLLAPSE_THRESHOLD = -1.5
RECENT_VOLATILITY_WINDOW = 6

EXTREME_EMOTIONS = {"rage", "terror", "panic", "manic", "euphoric", "despair"}
POSITIVE_EMOTIONS = {"happy", "excited", "calm", "content", "grateful"}
NEGATIVE_EMOTIONS = {"sad", "angry", "anxious", "stressed", "frustrated", "tired"}

# Core personality trait keys in user_preferences that define identity
CORE_TRAIT_KEYS = [
    "communication_style",
    "humor_preference",
    "response_length",
    "formality",
    "proactive_suggestions",
    "silence_preferred",
]

# Identity anchor traits — these resist drift more strongly than regular traits.
# If these flip, it is a CRITICAL alert, not just a warning.
IDENTITY_ANCHOR_TRAITS = [
    "communication_style",
    "formality",
]


class SelfModelValidator:
    """
    Validates ARIA's self-model for internal consistency, emotional stability,
    and resistance to memory poisoning. Singleton pattern — one instance per process.
    """

    _instance = None
    _cls_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._cls_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                cls._instance = inst
            return cls._instance

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        db = getattr(self, "db_path", DB_PATH)
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    def _log_audit(self, event_type: str, description: str, metadata: dict = None):
        try:
            from skills.memory_manager import MemoryManager
            MemoryManager().log_cognition_audit(event_type, description, metadata or {})
        except Exception as e:
            print(f"[SelfModelValidator] Audit log write failed: {e}")

    def _quarantine(self, table_name: str, original_data: dict, error_msg: str):
        try:
            with _lock:
                with self._get_conn() as conn:
                    conn.execute(
                        """INSERT INTO corrupted_cognition_quarantine
                           (timestamp, table_name, original_data, error_msg)
                           VALUES (?, ?, ?, ?)""",
                        (time.time(), table_name, json.dumps(original_data), error_msg)
                    )
                    conn.commit()
        except Exception as e:
            print(f"[SelfModelValidator] Quarantine write failed: {e}")

    # ── 1. Trait Conflict Detector ────────────────────────────────────────────

    def detect_trait_conflicts(self, username: str) -> List[Dict[str, Any]]:
        """
        Scans user_preferences for logically contradictory pairs and flags them
        as unresolved_ambiguity without overwriting.

        Returns list of conflict records.
        """
        username = username.lower().strip()
        conflicts = []

        CONFLICT_RULES: List[Tuple[str, str, str, str]] = [
            # (key_a, val_a, key_b, val_b) — these two together are contradictory
            ("silence_preferred", "yes", "proactive_suggestions", "yes"),
            ("formality", "very_casual", "formality", "very_formal"),
            ("response_length", "brief", "response_length", "verbose"),
            ("humor_preference", "none", "humor_preference", "frequent"),
        ]

        try:
            with self._get_conn() as conn:
                rows = conn.execute(
                    "SELECT pref_key, pref_value FROM user_preferences WHERE username = ?",
                    (username,)
                ).fetchall()

            prefs: Dict[str, str] = {r["pref_key"]: r["pref_value"].lower().strip() for r in rows}

            for key_a, val_a, key_b, val_b in CONFLICT_RULES:
                if prefs.get(key_a) == val_a and prefs.get(key_b) == val_b:
                    conflict = {
                        "type": "TRAIT_CONFLICT",
                        "key_a": key_a, "val_a": val_a,
                        "key_b": key_b, "val_b": val_b,
                    }
                    conflicts.append(conflict)
                    print(
                        f"[SelfModelValidator] Trait conflict: "
                        f"'{key_a}'='{val_a}' conflicts with '{key_b}'='{val_b}' for user '{username}'"
                    )
                    # Flag both keys as unresolved ambiguity (do NOT delete)
                    with _lock:
                        with self._get_conn() as conn:
                            conn.execute(
                                """UPDATE user_preferences
                                   SET unresolved_ambiguity = 1
                                   WHERE username = ? AND pref_key IN (?, ?)""",
                                (username, key_a, key_b)
                            )
                            conn.commit()
                    self._log_audit(
                        "TRAIT_CONFLICT_DETECTED",
                        f"Conflicting traits detected for '{username}': "
                        f"'{key_a}'='{val_a}' vs '{key_b}'='{val_b}'. Both flagged as ambiguous.",
                        conflict
                    )

        except Exception as e:
            print(f"[SelfModelValidator] Trait conflict detection failed: {e}")

        return conflicts

    # ── 2. Emotional Instability Detector ─────────────────────────────────────

    def detect_emotional_instability(self, username: str) -> bool:
        """
        Checks the recent episodic record for rapid mood swings.
        Returns True if instability is detected.
        """
        username = username.lower().strip()
        try:
            with self._get_conn() as conn:
                # episodic_events table stores episodes with an 'emotion' column
                rows = conn.execute(
                    """SELECT emotion FROM episodic_events
                       WHERE username = ?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (username, EMOTION_WINDOW)
                ).fetchall()

            if not rows:
                return False

            emotions = [r["emotion"] for r in rows if r["emotion"]]

            # Count polarity swings: positive to negative or vice versa
            swing_count = 0
            for i in range(1, len(emotions)):
                prev_pos = emotions[i - 1] in POSITIVE_EMOTIONS
                prev_neg = emotions[i - 1] in NEGATIVE_EMOTIONS
                curr_pos = emotions[i] in POSITIVE_EMOTIONS
                curr_neg = emotions[i] in NEGATIVE_EMOTIONS
                if (prev_pos and curr_neg) or (prev_neg and curr_pos):
                    swing_count += 1

            if swing_count >= EMOTION_SWING_THRESHOLD:
                print(
                    f"[SelfModelValidator] Emotional instability detected for '{username}': "
                    f"{swing_count} swings in last {len(emotions)} episodes."
                )
                self._log_audit(
                    "EMOTIONAL_INSTABILITY_DETECTED",
                    f"User '{username}' shows {swing_count} emotion polarity swings "
                    f"in the last {len(emotions)} episodes.",
                    {"swing_count": swing_count, "recent_emotions": emotions}
                )
                return True

        except Exception as e:
            print(f"[SelfModelValidator] Emotional instability check failed: {e}")

        return False

    # ── 3. Memory Poisoning Resistance ───────────────────────────────────────

    def enforce_memory_poisoning_resistance(self, username: str, proposed_trust_delta: float, proposed_comfort_delta: float) -> Tuple[float, float]:
        """
        Clamps the effect a single emotional episode can have on relationship metrics.
        Prevents runaway trust erosion or comfort collapse from a single bad event.

        Returns (safe_trust_delta, safe_comfort_delta)
        """
        safe_trust = max(-MEMORY_POISON_TRUST_FLOOR_DROP, min(SINGLE_PASS_TRUST_SPIKE_LIMIT, proposed_trust_delta))
        safe_comfort = max(-MEMORY_POISON_COMFORT_FLOOR_DROP, min(SINGLE_PASS_COMFORT_SPIKE_LIMIT, proposed_comfort_delta))

        if safe_trust != proposed_trust_delta:
            print(
                f"[SelfModelValidator] Memory poisoning resistance: trust delta clamped "
                f"{proposed_trust_delta:+.2f} -> {safe_trust:+.2f} for '{username}'"
            )
            self._log_audit(
                "MEMORY_POISON_CLAMPED",
                f"Trust delta for '{username}' was clamped to prevent memory poisoning.",
                {
                    "username": username,
                    "proposed_trust_delta": proposed_trust_delta,
                    "safe_trust_delta": safe_trust,
                    "proposed_comfort_delta": proposed_comfort_delta,
                    "safe_comfort_delta": safe_comfort,
                }
            )

        if safe_comfort != proposed_comfort_delta:
            print(
                f"[SelfModelValidator] Memory poisoning resistance: comfort delta clamped "
                f"{proposed_comfort_delta:+.2f} -> {safe_comfort:+.2f} for '{username}'"
            )

        return safe_trust, safe_comfort

    # ── 4. Identity Drift Detector ─────────────────────────────────────────────

    def detect_identity_drift(self, username: str) -> List[Dict[str, Any]]:
        """
        Scans the cognition_audit_log for core trait flip events within the
        drift detection window. Flags traits that have flipped too many times.

        Returns list of drift records.
        """
        username = username.lower().strip()
        drift_records = []
        window_start = time.time() - (IDENTITY_DRIFT_WINDOW_DAYS * 86400.0)

        try:
            with self._get_conn() as conn:
                rows = conn.execute(
                    """SELECT description, metadata_json, timestamp
                       FROM cognition_audit_log
                       WHERE event_type = 'PREFERENCE_UPDATED'
                         AND timestamp >= ?
                       ORDER BY timestamp ASC""",
                    (window_start,)
                ).fetchall()

            # Count value flips per core trait key for this user
            trait_history: Dict[str, List[str]] = {}
            for row in rows:
                try:
                    meta = json.loads(row["metadata_json"] or "{}")
                    if meta.get("username", "").lower() != username:
                        continue
                    key = meta.get("key", "")
                    value = meta.get("value", "")
                    if key in CORE_TRAIT_KEYS:
                        if key not in trait_history:
                            trait_history[key] = []
                        trait_history[key].append(value)
                except Exception:
                    continue

            for trait_key, history in trait_history.items():
                # Count flip count (adjacent different values)
                flips = sum(1 for i in range(1, len(history)) if history[i] != history[i - 1])
                if flips > IDENTITY_DRIFT_MAX_FLIPS:
                    is_anchor = trait_key in IDENTITY_ANCHOR_TRAITS
                    record = {
                        "type": "IDENTITY_DRIFT",
                        "trait": trait_key,
                        "flip_count": flips,
                        "history": history,
                        "window_days": IDENTITY_DRIFT_WINDOW_DAYS,
                    }
                    if is_anchor:
                        record["anchor_violation"] = True
                        record["severity"] = "CRITICAL"
                    drift_records.append(record)

                    severity_tag = "CRITICAL ANCHOR" if is_anchor else "WARNING"
                    print(
                        f"[SelfModelValidator] [{severity_tag}] Identity drift on trait '{trait_key}' for '{username}': "
                        f"{flips} flips in {IDENTITY_DRIFT_WINDOW_DAYS} days. History: {history}"
                    )
                    self._quarantine(
                        "cognition_audit_log",
                        record,
                        f"Identity drift on core trait '{trait_key}' ({flips} flips in {IDENTITY_DRIFT_WINDOW_DAYS}d)"
                    )
                    self._log_audit(
                        "IDENTITY_DRIFT_DETECTED",
                        f"Core trait '{trait_key}' for user '{username}' has drifted "
                        f"{flips} times in {IDENTITY_DRIFT_WINDOW_DAYS} days.",
                        record
                    )
                    if is_anchor:
                        self._log_audit(
                            "IDENTITY_ANCHOR_VIOLATION",
                            f"CRITICAL: Identity anchor trait '{trait_key}' for user '{username}' "
                            f"has flipped {flips} times in {IDENTITY_DRIFT_WINDOW_DAYS} days. "
                            f"Anchor traits must remain stable.",
                            record
                        )
                    # Flag the preference as ambiguous but do NOT delete
                    with _lock:
                        with self._get_conn() as conn:
                            conn.execute(
                                """UPDATE user_preferences
                                   SET unresolved_ambiguity = 1
                                   WHERE username = ? AND pref_key = ?""",
                                (username, trait_key)
                            )
                            conn.commit()

        except Exception as e:
            print(f"[SelfModelValidator] Identity drift detection failed: {e}")

        return drift_records

    # ── 5. Emotional Volatility Detector ────────────────────────────────────

    def _ensure_snapshot_table(self, conn: sqlite3.Connection):
        """Lazily create the relationship_vector_snapshots table if it doesn't exist."""
        conn.execute(
            """CREATE TABLE IF NOT EXISTS relationship_vector_snapshots (
                   username TEXT NOT NULL,
                   trust REAL NOT NULL,
                   comfort REAL NOT NULL,
                   interaction_depth REAL NOT NULL,
                   emotional_openness REAL NOT NULL,
                   snapshot_at REAL NOT NULL
               )"""
        )
        conn.commit()

    def detect_emotional_volatility(self, username: str) -> Dict[str, Any]:
        """
        Detects rapid trust/comfort changes over the last 24 hours by comparing
        the current relationship_vector to the most recent snapshot.

        Returns a dict with:
          trust_volatile, comfort_volatile, trust_delta_24h, comfort_delta_24h
        """
        username = username.lower().strip()
        default_trust = 10.0
        default_comfort = 10.0
        result: Dict[str, Any] = {
            "trust_volatile": False,
            "comfort_volatile": False,
            "trust_spike_detected": False,
            "comfort_collapse_detected": False,
            "trust_delta_24h": 0.0,
            "comfort_delta_24h": 0.0,
            "max_recent_trust_jump": 0.0,
            "max_recent_comfort_drop": 0.0,
            "alerts": [],
        }

        audit_events = []
        try:
            with self._get_conn() as conn:
                self._ensure_snapshot_table(conn)

                # Fetch current relationship vector
                rv_row = conn.execute(
                    """SELECT trust, comfort, interaction_depth, emotional_openness
                       FROM relationship_vector WHERE username = ?""",
                    (username,)
                ).fetchone()

                if not rv_row:
                    return result

                current_trust = float(rv_row["trust"])
                current_comfort = float(rv_row["comfort"])
                current_depth = float(rv_row["interaction_depth"])
                current_openness = float(rv_row["emotional_openness"])

                # Fetch most recent snapshot within 24h
                cutoff_24h = time.time() - 86400.0
                snap = conn.execute(
                    """SELECT trust, comfort
                       FROM relationship_vector_snapshots
                       WHERE username = ? AND snapshot_at >= ?
                       ORDER BY snapshot_at ASC LIMIT 1""",
                    (username, cutoff_24h)
                ).fetchone()

                if snap:
                    prev_trust = float(snap["trust"])
                    prev_comfort = float(snap["comfort"])
                else:
                    # No recent snapshot — fall back to current values to avoid startup spikes
                    prev_trust = current_trust
                    prev_comfort = current_comfort

                trust_delta = current_trust - prev_trust
                comfort_delta = current_comfort - prev_comfort

                result["trust_delta_24h"] = trust_delta
                result["comfort_delta_24h"] = comfort_delta
                result["trust_volatile"] = abs(trust_delta) > TRUST_VOLATILITY_THRESHOLD
                result["comfort_volatile"] = abs(comfort_delta) > COMFORT_VOLATILITY_THRESHOLD

                recent_rows = conn.execute(
                    """SELECT trust, comfort
                       FROM relationship_vector_snapshots
                       WHERE username = ?
                       ORDER BY snapshot_at DESC LIMIT ?""",
                    (username, RECENT_VOLATILITY_WINDOW)
                ).fetchall()
                timeline = [(float(r["trust"]), float(r["comfort"])) for r in reversed(recent_rows)]
                timeline.append((current_trust, current_comfort))
                trust_jumps = [timeline[i][0] - timeline[i - 1][0] for i in range(1, len(timeline))]
                comfort_deltas = [timeline[i][1] - timeline[i - 1][1] for i in range(1, len(timeline))]
                max_trust_jump = max(trust_jumps) if trust_jumps else 0.0
                max_comfort_drop = min(comfort_deltas) if comfort_deltas else 0.0

                result["max_recent_trust_jump"] = max_trust_jump
                result["max_recent_comfort_drop"] = max_comfort_drop
                result["trust_spike_detected"] = max_trust_jump > RECENT_TRUST_SPIKE_THRESHOLD
                result["comfort_collapse_detected"] = max_comfort_drop < RECENT_COMFORT_COLLAPSE_THRESHOLD
                if result["trust_spike_detected"]:
                    result["alerts"].append({
                        "type": "TRUST_SPIKE",
                        "delta": max_trust_jump,
                        "threshold": RECENT_TRUST_SPIKE_THRESHOLD,
                    })
                if result["comfort_collapse_detected"]:
                    result["alerts"].append({
                        "type": "COMFORT_COLLAPSE",
                        "delta": max_comfort_drop,
                        "threshold": RECENT_COMFORT_COLLAPSE_THRESHOLD,
                    })

                # Insert new snapshot
                conn.execute(
                    """INSERT INTO relationship_vector_snapshots
                       (username, trust, comfort, interaction_depth, emotional_openness, snapshot_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (username, current_trust, current_comfort, current_depth, current_openness, time.time())
                )
                conn.commit()

                if result["trust_volatile"]:
                    print(
                        f"[SelfModelValidator] Trust volatility detected for '{username}': "
                        f"delta={trust_delta:+.2f} in 24h (threshold={TRUST_VOLATILITY_THRESHOLD})"
                    )
                    audit_events.append(
                        (
                            "EMOTIONAL_VOLATILITY_TRUST",
                            f"Trust spike for '{username}': {trust_delta:+.2f} in 24h.",
                            {"username": username, "trust_delta": trust_delta,
                             "prev_trust": prev_trust, "current_trust": current_trust}
                        )
                    )

                if result["comfort_volatile"]:
                    print(
                        f"[SelfModelValidator] Comfort volatility detected for '{username}': "
                        f"delta={comfort_delta:+.2f} in 24h (threshold={COMFORT_VOLATILITY_THRESHOLD})"
                    )
                    audit_events.append(
                        (
                            "EMOTIONAL_VOLATILITY_COMFORT",
                            f"Comfort collapse for '{username}': {comfort_delta:+.2f} in 24h.",
                            {"username": username, "comfort_delta": comfort_delta,
                             "prev_comfort": prev_comfort, "current_comfort": current_comfort}
                        )
                    )

                if result["trust_spike_detected"]:
                    audit_events.append(
                        (
                            "EMOTIONAL_VOLATILITY_TRUST_SPIKE",
                            f"Recent trust spike for '{username}': {max_trust_jump:+.2f}.",
                            {"username": username, "max_recent_trust_jump": max_trust_jump}
                        )
                    )

                if result["comfort_collapse_detected"]:
                    audit_events.append(
                        (
                            "EMOTIONAL_VOLATILITY_COMFORT_COLLAPSE",
                            f"Recent comfort collapse for '{username}': {max_comfort_drop:+.2f}.",
                            {"username": username, "max_recent_comfort_drop": max_comfort_drop}
                        )
                    )

        except Exception as e:
            print(f"[SelfModelValidator] Emotional volatility detection failed: {e}")

        for event_type, description, metadata in audit_events:
            self._log_audit(event_type, description, metadata)

        return result

    # ── 6. Long-Term Personality Coherence Check ─────────────────────────────

    def check_long_term_coherence(self, username: str) -> List[Dict[str, Any]]:
        """
        Scans cognition_audit_log for PREFERENCE_UPDATED events over the last
        90 days and detects systematic directional drift (e.g. a trait value
        changing in the same direction across 3+ updates).

        Returns a list of coherence warnings.
        """
        username = username.lower().strip()
        warnings: List[Dict[str, Any]] = []
        window_start = time.time() - (90 * 86400.0)

        try:
            with self._get_conn() as conn:
                rows = conn.execute(
                    """SELECT description, metadata_json, timestamp
                       FROM cognition_audit_log
                       WHERE event_type = 'PREFERENCE_UPDATED'
                         AND timestamp >= ?
                       ORDER BY timestamp ASC""",
                    (window_start,)
                ).fetchall()

            # Group value transitions per pref_key for this user
            trait_transitions: Dict[str, List[str]] = {}
            for row in rows:
                try:
                    meta = json.loads(row["metadata_json"] or "{}")
                    if meta.get("username", "").lower() != username:
                        continue
                    key = meta.get("key", "")
                    value = meta.get("value", "")
                    if key:
                        if key not in trait_transitions:
                            trait_transitions[key] = []
                        trait_transitions[key].append(value)
                except Exception:
                    continue

            for trait_key, values in trait_transitions.items():
                # Deduplicate consecutive identical values
                unique_steps = [values[0]]
                for v in values[1:]:
                    if v != unique_steps[-1]:
                        unique_steps.append(v)

                # A systematic directional drift is 3+ distinct consecutive changes
                if len(unique_steps) >= 3:
                    warning = {
                        "type": "LONG_TERM_COHERENCE_DRIFT",
                        "trait": trait_key,
                        "step_count": len(unique_steps),
                        "value_progression": unique_steps,
                        "window_days": 90,
                    }
                    warnings.append(warning)
                    print(
                        f"[SelfModelValidator] Long-term coherence drift on '{trait_key}' "
                        f"for '{username}': {len(unique_steps)}-step drift -> {unique_steps}"
                    )
                    self._log_audit(
                        "LONG_TERM_COHERENCE_DRIFT",
                        f"Trait '{trait_key}' for '{username}' shows systematic "
                        f"{len(unique_steps)}-step directional drift over 90 days.",
                        warning
                    )

        except Exception as e:
            print(f"[SelfModelValidator] Long-term coherence check failed: {e}")

        return warnings

    # ── 7. Full Validation Pass ───────────────────────────────────────────────

    def run_full_validation(self, username: str) -> Dict[str, Any]:
        """
        Runs all validation checks for a user in sequence and returns a
        consolidated report dict. Safe to call from background threads.

        Report structure:
        {
          "username": str,
          "timestamp": float,
          "trait_conflicts": [...],
          "emotional_instability": bool,
          "identity_drift": [...],
          "issues_total": int,
          "status": "OK" | "WARNING" | "CRITICAL"
        }
        """
        print(f"[SelfModelValidator] Running full self-model validation for '{username}'...")

        trait_conflicts = self.detect_trait_conflicts(username)
        emotional_instability = self.detect_emotional_instability(username)
        identity_drift = self.detect_identity_drift(username)
        emotional_volatility = self.detect_emotional_volatility(username)
        long_term_coherence = self.check_long_term_coherence(username)

        # Count issues — volatility flags count as 1 each
        volatility_issues = (
            (1 if emotional_volatility.get("trust_volatile") else 0)
            + (1 if emotional_volatility.get("comfort_volatile") else 0)
            + (1 if emotional_volatility.get("trust_spike_detected") else 0)
            + (1 if emotional_volatility.get("comfort_collapse_detected") else 0)
        )
        # Anchor violations in drift records force CRITICAL
        has_anchor_violation = any(r.get("anchor_violation") for r in identity_drift)

        issues_total = (
            len(trait_conflicts)
            + (1 if emotional_instability else 0)
            + len(identity_drift)
            + volatility_issues
            + len(long_term_coherence)
        )

        if issues_total == 0:
            status = "OK"
        elif has_anchor_violation:
            status = "CRITICAL"
        elif issues_total <= 2:
            status = "WARNING"
        else:
            status = "CRITICAL"

        report = {
            "username": username,
            "timestamp": time.time(),
            "trait_conflicts": trait_conflicts,
            "emotional_instability": emotional_instability,
            "identity_drift": identity_drift,
            "emotional_volatility": emotional_volatility,
            "long_term_coherence": long_term_coherence,
            "issues_total": issues_total,
            "status": status,
        }

        if status != "OK":
            self._log_audit(
                "SELF_MODEL_VALIDATION_RESULT",
                f"Self-model validation for '{username}' completed with status: {status}. "
                f"{issues_total} issue(s) found.",
                {
                    "trait_conflicts_count": len(trait_conflicts),
                    "emotional_instability": emotional_instability,
                    "identity_drift_count": len(identity_drift),
                    "emotional_volatility": emotional_volatility,
                    "long_term_coherence_count": len(long_term_coherence),
                    "status": status,
                }
            )

        print(
            f"[SelfModelValidator] Validation complete for '{username}': "
            f"status={status}, issues={issues_total}"
        )
        if status != "OK":
            if trait_conflicts:
                print(f"[SelfModelValidator]   - Trait conflicts ({len(trait_conflicts)}): "
                      + ", ".join(f"{c['key_a']}={c['val_a']} vs {c['key_b']}={c['val_b']}" for c in trait_conflicts))
            if emotional_instability:
                print(f"[SelfModelValidator]   - Emotional instability: True")
            if identity_drift:
                for d in identity_drift:
                    print(f"[SelfModelValidator]   - Identity drift on '{d['trait']}': "
                          f"{d['flip_count']} flips | history={d.get('history', [])[-5:]}")
            if emotional_volatility.get("trust_volatile"):
                print(f"[SelfModelValidator]   - Trust volatility: delta={emotional_volatility['trust_delta_24h']:+.2f} in 24h")
            if emotional_volatility.get("comfort_volatile"):
                print(f"[SelfModelValidator]   - Comfort volatility: delta={emotional_volatility['comfort_delta_24h']:+.2f} in 24h")
            if emotional_volatility.get("trust_spike_detected"):
                print(f"[SelfModelValidator]   - Trust spike: max_jump={emotional_volatility['max_recent_trust_jump']:+.2f}")
            if emotional_volatility.get("comfort_collapse_detected"):
                print(f"[SelfModelValidator]   - Comfort collapse: max_drop={emotional_volatility['max_recent_comfort_drop']:+.2f}")
            if long_term_coherence:
                for w in long_term_coherence:
                    print(f"[SelfModelValidator]   - Long-term drift on '{w['trait']}': "
                          f"{w['step_count']}-step progression={w.get('value_progression', [])}")
        return report

    def run_full_validation_async(self, username: str):
        """Launches full validation in a low-priority background thread."""
        def _run():
            try:
                time.sleep(0.3)
                self.run_full_validation(username)
            except Exception as e:
                print(f"[SelfModelValidator] Async validation failed: {e}")

        t = threading.Thread(target=_run, daemon=True)
        t.start()
