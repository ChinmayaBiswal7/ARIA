import sqlite3
import os
import time
import json
import re
import datetime

REPO_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(REPO_PATH, "aria_memory.db")

DAILY_DECAY         = 0.995   # per day, unreinforced vectors
MIN_WEIGHT          = 0.10    # floor
MAX_WEIGHT          = 0.95    # cap
GITHUB_DELTA        = 0.03
CODEFORCES_DELTA    = 0.06    # on rating increase + recent tags
CAREER_INTERVIEW    = +0.07
CAREER_REJECTED     = -0.03
CAREER_GHOSTED      = -0.01
USAGE_FOCUS_DELTA   = 0.02    # focus intensity only
VOICE_DELTA         = +0.05   # weak evidence
MULTI_SIGNAL_BONUS  = 1.5     # if >=2 sources agree within 7 days
NOTIFY_THRESHOLD    = 0.10    # minimum abs(delta) to notify
CONFIDENCE_NOTIFY   = 0.75    # OR if confidence crosses this

class AriaLearningCore:
    """
    Phase U: Continuous Learning Engine.
    Manages user profile vectors, ledger logs, and current focus tracking.
    Fuses multiple signals to adjust vector weights and confidence levels.
    """
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_schema()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self._get_connection() as conn:
            # 1. user_profile_vectors
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_profile_vectors (
                    vector_group TEXT NOT NULL,
                    vector_key   TEXT NOT NULL,
                    vector_weight   REAL DEFAULT 0.5,
                    confidence      REAL DEFAULT 0.5,
                    signal_count    INTEGER DEFAULT 0,
                    last_updated    INTEGER NOT NULL,
                    last_reinforced INTEGER NOT NULL,
                    PRIMARY KEY (vector_group, vector_key)
                )
            """)
            # 2. profile_learning_ledger
            conn.execute("""
                CREATE TABLE IF NOT EXISTS profile_learning_ledger (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    vector_group TEXT,
                    vector_key   TEXT,
                    delta        REAL,
                    new_weight   REAL,
                    source       TEXT,
                    description  TEXT,
                    timestamp    INTEGER NOT NULL
                )
            """)
            # 3. current_focus
            conn.execute("""
                CREATE TABLE IF NOT EXISTS current_focus (
                    topic           TEXT PRIMARY KEY,
                    intensity       REAL DEFAULT 0.5,
                    first_observed  INTEGER NOT NULL,
                    last_reinforced INTEGER NOT NULL
                )
            """)
            conn.commit()

    def run_daily_decay(self):
        """
        Applies DAILY_DECAY to vectors that have not been reinforced in the last 24 hours (86400s).
        Decays focus topic intensities in current_focus and deletes stale ones.
        """
        now = int(time.time())
        cutoff = now - 86400
        
        with self._get_connection() as conn:
            # 1. Decay user profile vectors
            vectors = conn.execute("""
                SELECT vector_group, vector_key, vector_weight, confidence 
                FROM user_profile_vectors 
                WHERE last_reinforced < ?
            """, (cutoff,)).fetchall()
            
            for vec in vectors:
                group, key, old_weight, confidence = vec["vector_group"], vec["vector_key"], vec["vector_weight"], vec["confidence"]
                new_weight = max(MIN_WEIGHT, old_weight * DAILY_DECAY)
                delta = new_weight - old_weight
                
                if abs(delta) > 0.0001:
                    conn.execute("""
                        UPDATE user_profile_vectors
                        SET vector_weight = ?, last_updated = ?
                        WHERE vector_group = ? AND vector_key = ?
                    """, (new_weight, now, group, key))
                    
                    conn.execute("""
                        INSERT INTO profile_learning_ledger (vector_group, vector_key, delta, new_weight, source, description, timestamp)
                        VALUES (?, ?, ?, ?, 'DECAY', 'Stale vector daily decay', ?)
                    """, (group, key, delta, new_weight, now))
            
            # 2. Decay focus topics
            foci = conn.execute("SELECT topic, intensity FROM current_focus WHERE last_reinforced < ?", (cutoff,)).fetchall()
            for focus in foci:
                topic = focus["topic"]
                new_intensity = focus["intensity"] * 0.95
                if new_intensity < 0.1:
                    conn.execute("DELETE FROM current_focus WHERE topic = ?", (topic,))
                else:
                    conn.execute("""
                        UPDATE current_focus 
                        SET intensity = ?, last_reinforced = ? 
                        WHERE topic = ?
                    """, (new_intensity, now, topic))
            conn.commit()

    def ingest_github_signal(self, aria, kg):
        """
        Ingests language and technology signals from the KnowledgeGraph nodes updated in the last 24 hours.
        """
        projects = kg.get_nodes_by_type("project")
        if not projects:
            return

        def parse_recency(last_commit_str):
            if not last_commit_str or last_commit_str == "unknown":
                return 0.1
            last_commit_str = last_commit_str.lower()
            if "second" in last_commit_str or "minute" in last_commit_str or "hour" in last_commit_str:
                return 1.0
            if "day" in last_commit_str:
                match = re.search(r'(\d+)', last_commit_str)
                if match:
                    days = int(match.group(1))
                    return max(0.5, 1.0 - (days * 0.05))
                return 0.9
            if "week" in last_commit_str:
                match = re.search(r'(\d+)', last_commit_str)
                if match:
                    weeks = int(match.group(1))
                    return max(0.1, 0.5 - (weeks * 0.1))
                return 0.4
            return 0.1

        for project in projects:
            props_str = project.get("properties", "{}")
            try:
                props = json.loads(props_str)
            except Exception:
                props = {}

            last_commit = props.get("last_commit", "unknown")
            recency = parse_recency(last_commit)
            
            # We only signal positive reinforce if project is active (recency >= 0.5)
            if recency >= 0.5:
                languages = props.get("languages", [])
                for lang in languages:
                    self._apply_signal(
                        aria=aria,
                        vector_group="LANGUAGES",
                        vector_key=lang.lower(),
                        delta=GITHUB_DELTA,
                        source="GITHUB",
                        description=f"Active project {project['name']} uses {lang}"
                    )
                
                # Check for machine learning strength
                if "machine_learning" in props.get("tags", []):
                    self._apply_signal(
                        aria=aria,
                        vector_group="STRENGTHS",
                        vector_key="machine_learning",
                        delta=GITHUB_DELTA,
                        source="GITHUB",
                        description=f"Active ML project {project['name']} commits"
                    )

    def ingest_codeforces_signal(self, aria, cf_stats):
        """
        Ingests competitive programming strength signals based on Codeforces stats.
        Only bumps strengths if rating has increased.
        """
        if not cf_stats or "error" in cf_stats:
            return

        username = cf_stats.get("username")
        rating = cf_stats.get("rating", 0)
        recent_tags = cf_stats.get("recent_tags", [])

        # Fetch previous CF rating from profile vectors
        prev_rating = 0
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT vector_weight FROM user_profile_vectors 
                WHERE vector_group = 'CAREER' AND vector_key = 'codeforces_rating'
            """).fetchone()
            if row:
                prev_rating = int(row["vector_weight"] * 3000) # De-normalize

        # Store new normalized rating
        normalized_rating = min(1.0, rating / 3000.0)
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO user_profile_vectors (vector_group, vector_key, vector_weight, confidence, last_updated, last_reinforced)
                VALUES ('CAREER', 'codeforces_rating', ?, 1.0, ?, ?)
            """, (normalized_rating, int(time.time()), int(time.time())))
            conn.commit()

        # Check if rating went up
        if rating > prev_rating:
            # Bump CP strength
            self._apply_signal(
                aria=aria,
                vector_group="STRENGTHS",
                vector_key="competitive_programming",
                delta=CODEFORCES_DELTA,
                source="CODEFORCES",
                description=f"Codeforces rating increased from {prev_rating} to {rating}"
            )
            # Bump specific tag strengths
            for tag in recent_tags:
                self._apply_signal(
                    aria=aria,
                    vector_group="STRENGTHS",
                    vector_key=tag.lower(),
                    delta=CODEFORCES_DELTA,
                    source="CODEFORCES",
                    description=f"Solved recent CF problems tagged: {tag}"
                )

    def ingest_career_signal(self, aria, role_type, outcome):
        """
        Ingests career progression/application outcomes.
        """
        role_type = role_type.lower()
        outcome = outcome.upper()
        
        mapping = {
            "INTERVIEW": CAREER_INTERVIEW,
            "OFFER": CAREER_INTERVIEW,
            "REJECTED": CAREER_REJECTED,
            "GHOSTED": CAREER_GHOSTED
        }
        
        delta = mapping.get(outcome)
        if delta is not None:
            self._apply_signal(
                aria=aria,
                vector_group="CAREER",
                vector_key=f"{role_type}_match",
                delta=delta,
                source="CAREER",
                description=f"Application outcome for {role_type}: {outcome}"
            )

    def ingest_usage_signal(self, topics):
        """
        Ingests ARIA usage patterns (frequent queries/topics).
        Bumps topic focus intensity inside the current_focus table.
        """
        now = int(time.time())
        with self._get_connection() as conn:
            for topic in topics:
                topic = topic.strip().title()
                row = conn.execute("SELECT intensity FROM current_focus WHERE topic = ?", (topic,)).fetchone()
                if row:
                    new_intensity = min(1.0, row["intensity"] + USAGE_FOCUS_DELTA)
                    conn.execute("""
                        UPDATE current_focus 
                        SET intensity = ?, last_reinforced = ?
                        WHERE topic = ?
                    """, (new_intensity, now, topic))
                else:
                    conn.execute("""
                        INSERT INTO current_focus (topic, intensity, first_observed, last_reinforced)
                        VALUES (?, 0.5, ?, ?)
                    """, (topic, now, now))
            conn.commit()

    def ingest_voice_signal(self, aria, concept):
        """
        Ingests explicit voice signal declarations from the user.
        """
        self._apply_signal(
            aria=aria,
            vector_group="STRENGTHS",
            vector_key=concept.lower(),
            delta=VOICE_DELTA,
            source="VOICE",
            description=f"User explicitly declared skill in voice message"
        )

    def _apply_signal(self, aria, vector_group, vector_key, delta, source, description):
        """
        Processes a single signal weight adjustment. Performs multi-signal fusion,
        handles conflicts, saves to SQLite, and alerts the user if changes are significant.
        """
        now = int(time.time())
        seven_days_ago = now - 7 * 86400
        
        with self._get_connection() as conn:
            # Fetch current vector properties
            vector = conn.execute("""
                SELECT vector_weight, confidence, signal_count 
                FROM user_profile_vectors 
                WHERE vector_group = ? AND vector_key = ?
            """, (vector_group, vector_key)).fetchone()
            
            if vector:
                current_weight = vector["vector_weight"]
                current_confidence = vector["confidence"]
                signal_count = vector["signal_count"]
            else:
                current_weight = 0.5
                current_confidence = 0.5
                signal_count = 0
            
            # Check for multi-signal fusion & conflicts in the ledger
            # We look for entries in the last 7 days from other sources
            recent_logs = conn.execute("""
                SELECT delta, source FROM profile_learning_ledger
                WHERE vector_group = ? AND vector_key = ? AND timestamp >= ? AND source != ? AND source != 'DECAY'
            """, (vector_group, vector_key, seven_days_ago, source)).fetchall()
            
            effective_delta = delta
            new_confidence = current_confidence
            conflict = False
            agreement = False
            agreeing_sources = []
            
            for log in recent_logs:
                log_delta = log["delta"]
                log_source = log["source"]
                
                # Check for sign conflict
                if log_delta * delta < 0:
                    conflict = True
                    break
                elif log_delta * delta > 0:
                    agreement = True
                    agreeing_sources.append(log_source)
            
            if conflict:
                # Conflicting signals -> no change to weight, drop confidence
                new_confidence = max(0.10, current_confidence - 0.10)
                conn.execute("""
                    INSERT OR REPLACE INTO user_profile_vectors 
                    (vector_group, vector_key, vector_weight, confidence, signal_count, last_updated, last_reinforced)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (vector_group, vector_key, current_weight, new_confidence, signal_count + 1, now, now))
                
                conn.execute("""
                    INSERT INTO profile_learning_ledger (vector_group, vector_key, delta, new_weight, source, description, timestamp)
                    VALUES (?, ?, 0.0, ?, ?, ?, ?)
                """, (vector_group, vector_key, current_weight, source, f"Aborted: Conflict with recent signal from {log_source}", now))
                conn.commit()
                return
                
            if agreement:
                # Agreement bonus
                effective_delta = delta * MULTI_SIGNAL_BONUS
                new_confidence = min(0.95, current_confidence + 0.15)
                description += f" (Agreement bonus applied; agreed with {', '.join(agreeing_sources)})"
            else:
                # Single source update
                new_confidence = min(0.95, current_confidence + 0.05)
                
            new_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, current_weight + effective_delta))
            
            # Save updated vector
            conn.execute("""
                INSERT OR REPLACE INTO user_profile_vectors 
                (vector_group, vector_key, vector_weight, confidence, signal_count, last_updated, last_reinforced)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (vector_group, vector_key, new_weight, new_confidence, signal_count + 1, now, now))
            
            # Log to ledger
            conn.execute("""
                INSERT INTO profile_learning_ledger (vector_group, vector_key, delta, new_weight, source, description, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (vector_group, vector_key, effective_delta, new_weight, source, description, now))
            conn.commit()
            
            # Notify user if change is significant
            self.notify_if_significant(aria, vector_key, effective_delta, current_weight, new_weight, current_confidence, new_confidence)

    def notify_if_significant(self, aria, vector_key, delta, old_weight, new_weight, old_conf, new_conf):
        """
        Sends speaking alert if delta exceeds NOTIFY_THRESHOLD or confidence crosses CONFIDENCE_NOTIFY.
        """
        should_notify = False
        reason = ""
        
        if abs(delta) >= NOTIFY_THRESHOLD:
            should_notify = True
            reason = f"significant change of {delta:+.2f}"
        elif old_conf < CONFIDENCE_NOTIFY <= new_conf:
            should_notify = True
            reason = f"confidence crossed threshold {CONFIDENCE_NOTIFY}"
            
        if should_notify and aria:
            msg = f"Learning update: key '{vector_key}' is now at {new_weight:.2f} (confidence {new_conf:.2f}) due to {reason}."
            print(f"[AriaLearningCore Alert] {msg}")
            if hasattr(aria, "safe_speak"):
                aria.safe_speak(msg)

    def get_profile_snapshot(self):
        """
        Returns all vectors and ledger logs formatted for API consumption.
        """
        snapshot = {
            "strengths": {},
            "languages": {},
            "career_confidence": {},
            "domains": {},
            "recent_changes": [],
            "profile_version": datetime.date.today().strftime("%Y-%m-%d")
        }
        
        with self._get_connection() as conn:
            # 1. Fetch vectors
            rows = conn.execute("SELECT * FROM user_profile_vectors").fetchall()
            for r in rows:
                gp = r["vector_group"]
                key = r["vector_key"]
                wt = r["vector_weight"]
                conf = r["confidence"]
                
                # Format to percentage value (0-100)
                val = round(wt * 100, 1)
                
                if gp == "STRENGTHS":
                    snapshot["strengths"][key] = val
                elif gp == "LANGUAGES":
                    snapshot["languages"][key] = val
                elif gp == "CAREER":
                    snapshot["career_confidence"][key] = val
                elif gp == "DOMAINS":
                    snapshot["domains"][key] = val
            
            # 2. Fetch recent ledger logs (last 10 changes)
            logs = conn.execute("""
                SELECT vector_key, delta, new_weight, source, description, timestamp 
                FROM profile_learning_ledger 
                ORDER BY timestamp DESC LIMIT 10
            """).fetchall()
            
            for l in logs:
                snapshot["recent_changes"].append({
                    "vector_key": l["vector_key"],
                    "delta": f"{l['delta']:+.2f}",
                    "new_weight": round(l["new_weight"], 2),
                    "source": l["source"],
                    "description": l["description"],
                    "timestamp": l["timestamp"]
                })
                
        return snapshot

    def get_current_focus(self, n=5):
        """
        Returns top-N focus topics sorted by intensity descending.
        """
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT topic, intensity FROM current_focus 
                ORDER BY intensity DESC LIMIT ?
            """, (n,)).fetchall()
            return [{"topic": r["topic"], "intensity": round(r["intensity"], 2)} for r in rows]
