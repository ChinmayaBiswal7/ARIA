import sqlite3
import json
import time
from typing import Dict, Any, List

from skills.base_agent import BaseAgent

class AriaVisionMemoryAgent(BaseAgent):
    def __init__(self, aria_instance=None, db_path: str = "aria_orchestrator.db"):
        super().__init__("VisionMemoryAgent", aria_instance)
        self.db_path = db_path
        self._pending_additions = {}
        self._pending_removals = {}
        self._initialize_historical_tables()

    def _initialize_historical_tables(self):
        """Creates the persistent visual event timeline tables inside the DB."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                # 1. Transactional Event Ledger
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS vision_event_timeline (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT,
                        entity_name TEXT,
                        confidence REAL,
                        timestamp INTEGER
                    )
                """)
                # 2. Lifetime Tracking Analytics Table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS entity_lifetimes (
                        entity_name TEXT PRIMARY KEY,
                        first_seen INTEGER,
                        last_seen INTEGER,
                        total_observations INTEGER
                    )
                """)
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"[VisionMemoryAgent] Database initialization error: {e}")

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        self.log_state_shift("RUNNING", "Running visual memory V2 sweep...")

        current_objects: List[str] = payload.get("current_objects", [])
        current_people: List[str] = payload.get("current_people", [])
        confidences: Dict[str, float] = payload.get("confidences", {})
        now = int(time.time())

        # Collect and filter active entities from payload
        detected_map = {}
        
        # 1. Process Objects (confidence >= 0.60)
        for label in current_objects:
            conf = confidences.get(label, 0.60)
            if conf >= 0.60:
                detected_map[label] = conf
                
        # 2. Process People (default to 0.90 confidence)
        for person in current_people:
            detected_map[person] = 0.90

        detected_labels = set(detected_map.keys())

        # Reconstruct last confirmed state from event history
        confirmed_state = self._get_latest_confirmed_state()
        confirmed_labels = set(confirmed_state.keys())

        # Check if database is completely empty (first run baseline initialization)
        is_initial = False
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM vision_event_timeline")
                count = cursor.fetchone()[0]
                if count == 0:
                    is_initial = True
            finally:
                conn.close()
        except Exception:
            is_initial = True

        if is_initial:
            if not detected_map:
                self._log_event("OBJECT_APPEARED", "none", 0.0, now)
            else:
                for label, conf in detected_map.items():
                    event_type = self._determine_event_type(label, is_appeared=True)
                    self._log_event(event_type, label, conf, now)
                    
            delta_payload = {
                "state_changed": False,
                "event": "INITIAL",
                "items_added": [],
                "items_removed": [],
                "current_snapshot": [{"label": k, "confidence": v} for k, v in detected_map.items()],
                "timestamp": now
            }
            self.log_state_shift("IDLE", "Initial baseline visual timeline sweep recorded.")
            return json.dumps(delta_payload)

        items_added = []
        items_removed = []

        # 1. Evaluate pending additions (require 3 consecutive frames)
        for label in detected_labels:
            if label not in confirmed_labels:
                self._pending_additions[label] = self._pending_additions.get(label, 0) + 1
                self._pending_removals.pop(label, None)
                if self._pending_additions[label] >= 3:
                    conf = detected_map[label]
                    event_type = self._determine_event_type(label, is_appeared=True)
                    self._log_event(event_type, label, conf, now)
                    items_added.append((label, conf))
                    self._pending_additions.pop(label, None)
            else:
                self._pending_additions.pop(label, None)
                self._pending_removals.pop(label, None)

        # 2. Evaluate pending removals (require 3 consecutive missing frames)
        for label in confirmed_labels:
            if label not in detected_labels:
                self._pending_removals[label] = self._pending_removals.get(label, 0) + 1
                self._pending_additions.pop(label, None)
                if self._pending_removals[label] >= 3:
                    event_type = self._determine_event_type(label, is_appeared=False)
                    self._log_event(event_type, label, 0.0, now)
                    items_removed.append(label)
                    self._pending_removals.pop(label, None)
            else:
                self._pending_additions.pop(label, None)
                self._pending_removals.pop(label, None)

        # Update lifetime statistics for entities that are still present
        for label in detected_labels:
            if label in confirmed_labels:
                try:
                    conn = sqlite3.connect(self.db_path)
                    try:
                        conn.execute("""
                            UPDATE entity_lifetimes 
                            SET last_seen = ?, total_observations = total_observations + 1 
                            WHERE entity_name = ?
                        """, (now, label))
                        conn.commit()
                    finally:
                        conn.close()
                except Exception as e:
                    print(f"[VisionMemoryAgent] Lifetime update error: {e}")

        # Clean up stale pending tracking states
        for label in list(self._pending_additions.keys()):
            if label not in detected_labels:
                self._pending_additions.pop(label, None)
        for label in list(self._pending_removals.keys()):
            if label in detected_labels:
                self._pending_removals.pop(label, None)

        state_changed = len(items_added) > 0 or len(items_removed) > 0
        if state_changed:
            updated_state = self._get_latest_confirmed_state()
            delta_payload = {
                "state_changed": True,
                "items_added": [{"label": k, "confidence": v} for k, v in items_added],
                "items_removed": items_removed,
                "current_snapshot": [{"label": k, "confidence": v} for k, v in updated_state.items()],
                "timestamp": now
            }

            # Publish updated timeline state to Blackboard
            try:
                from skills.blackboard import AriaBlackboard
                blackboard = AriaBlackboard()
                blackboard.publish(
                    topic="vision",
                    key="room_delta",
                    value=delta_payload,
                    source=self.agent_name,
                    ttl_hours=24
                )
            except Exception as e:
                print(f"[VisionMemoryAgent] Error publishing room_delta to Blackboard: {e}")

            # Dispatch workspace alerts
            self._dispatch_workspace_alerts(items_added, items_removed)
            print(f"[VisionMemoryAgent] V2 Timeline Delta: added={items_added}, removed={items_removed}")
        else:
            delta_payload = {
                "state_changed": False,
                "items_added": [],
                "items_removed": [],
                "current_snapshot": [{"label": k, "confidence": v} for k, v in confirmed_state.items()],
                "timestamp": now
            }

        self.log_state_shift("IDLE", f"Visual sweep complete. Changed: {state_changed}")
        return json.dumps(delta_payload)

    def _determine_event_type(self, entity_name: str, is_appeared: bool) -> str:
        """Determines event prefix (PERSON vs OBJECT) using registered profiles database."""
        try:
            from skills.person_profile_manager import AriaPersonProfileManager
            profile_manager = AriaPersonProfileManager()
            is_person = profile_manager.get_profile(entity_name) is not None
        except Exception:
            is_person = False

        action = "APPEARED" if is_appeared else "REMOVED" if not is_person else "LEFT"
        prefix = "PERSON" if is_person else "OBJECT"
        return f"{prefix}_{action}"

    def _log_event(self, event_type: str, entity_name: str, confidence: float, timestamp: int) -> int:
        """Commits timeline transaction to SQLite and triggers Blackboard event broadcast."""
        event_id = 0
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    "INSERT INTO vision_event_timeline (event_type, entity_name, confidence, timestamp) VALUES (?, ?, ?, ?)",
                    (event_type, entity_name, confidence, timestamp)
                )
                event_id = cursor.lastrowid
                
                # Update entity lifetimes
                if "APPEARED" in event_type:
                    conn.execute("""
                        INSERT INTO entity_lifetimes (entity_name, first_seen, last_seen, total_observations)
                        VALUES (?, ?, ?, 1)
                        ON CONFLICT(entity_name) DO UPDATE SET last_seen = ?, total_observations = total_observations + 1
                    """, (entity_name, timestamp, timestamp, timestamp))
                else:
                    conn.execute("""
                        UPDATE entity_lifetimes SET last_seen = ? WHERE entity_name = ?
                    """, (timestamp, entity_name))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"[VisionMemoryAgent] Database log event error: {e}")
            return 0

        # Broadcast distinct event details on Blackboard
        try:
            from skills.blackboard import AriaBlackboard
            blackboard = AriaBlackboard()
            event_payload = {
                "event_id": event_id,
                "event_type": event_type,
                "entity_name": entity_name,
                "confidence": confidence,
                "timestamp": timestamp
            }
            blackboard.publish(
                topic="vision",
                key=f"timeline_event_{event_id}",
                value=event_payload,
                source=self.agent_name,
                ttl_hours=24
            )
        except Exception as e:
            print(f"[VisionMemoryAgent] Blackboard event publish error: {e}")

        return event_id

    def _get_latest_confirmed_state(self) -> Dict[str, float]:
        """Reconstructs the active room state from the transactional event timeline."""
        confirmed = {}
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    "SELECT event_type, entity_name, confidence FROM vision_event_timeline ORDER BY id ASC"
                )
                for event_type, name, conf in cursor.fetchall():
                    if "APPEARED" in event_type:
                        if name != "none":
                            confirmed[name] = conf
                    elif "REMOVED" in event_type or "LEFT" in event_type:
                        confirmed.pop(name, None)
            finally:
                conn.close()
        except Exception as e:
            print(f"[VisionMemoryAgent] Error reconstructing confirmed state: {e}")
        return confirmed

    def _dispatch_workspace_alerts(self, items_added: list, items_removed: list):
        aria = self.aria
        if aria and hasattr(aria, "alert_router") and aria.alert_router:
            added_labels = [k for k, v in items_added]
            if added_labels:
                try:
                    aria.alert_router.dispatch_alert(
                        title="📱 WORKSPACE UPDATE",
                        body=f"Environment layout shifted: added {', '.join(added_labels)}.",
                        priority="LOW",
                        category="VISION"
                    )
                except Exception:
                    pass

    def query_what_changed(self) -> str:
        """Returns visual timeline summary showing recent appearance/removal changes."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    "SELECT event_type, entity_name, confidence, timestamp FROM vision_event_timeline "
                    "ORDER BY id DESC LIMIT 10"
                )
                rows = cursor.fetchall()
            finally:
                conn.close()
            
            if not rows:
                return "My visual timeline memory is currently empty, Chinmaya."

            log_entries = []
            for event_type, name, conf, ts in rows:
                time_str = time.strftime('%H:%M:%S', time.localtime(ts))
                if "APPEARED" in event_type:
                    log_entries.append(f"- [{time_str}] {name} appeared (confidence: {conf*100:.0f}%)")
                elif "LEFT" in event_type:
                    log_entries.append(f"- [{time_str}] {name} left")
                else:
                    log_entries.append(f"- [{time_str}] {name} was removed")

            return "Recent visual timeline updates:\n" + "\n".join(log_entries)
        except Exception as e:
            return f"Error querying what changed: {e}"

    def query_when_appear(self, item_label: str) -> str:
        """Finds when a specific entity appeared in the timeline."""
        item_label = item_label.lower().strip()
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    "SELECT timestamp, event_type, confidence FROM vision_event_timeline "
                    "WHERE LOWER(entity_name) = ? AND event_type LIKE '%APPEARED' "
                    "ORDER BY id DESC LIMIT 1", (item_label,)
                )
                row = cursor.fetchone()
            finally:
                conn.close()
            
            if not row:
                return f"My timeline has no record of a {item_label} appearing in your workspace, Chinmaya."

            timestamp, event_type, confidence = row
            time_str = time.strftime('%H:%M:%S', time.localtime(timestamp))
            elapsed_sec = int(time.time() - timestamp)
            
            return f"The {item_label} appeared at {time_str} ({self._format_duration(elapsed_sec)} ago) with confidence {confidence * 100:.0f}%."
        except Exception as e:
            return f"Error searching timeline: {e}"

    def query_when_removed(self, item_label: str) -> str:
        """Finds when an item was removed/left the workspace."""
        item_label = item_label.lower().strip()
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    "SELECT timestamp, event_type FROM vision_event_timeline "
                    "WHERE LOWER(entity_name) = ? AND (event_type LIKE '%REMOVED' OR event_type LIKE '%LEFT') "
                    "ORDER BY id DESC LIMIT 1", (item_label,)
                )
                row = cursor.fetchone()
            finally:
                conn.close()
            
            if not row:
                return f"My timeline has no record of a {item_label} being removed from your workspace, Chinmaya."

            timestamp, event_type = row
            time_str = time.strftime('%H:%M:%S', time.localtime(timestamp))
            elapsed_sec = int(time.time() - timestamp)
            action = "was removed" if "REMOVED" in event_type else "left"

            return f"The {item_label} {action} at {time_str} ({self._format_duration(elapsed_sec)} ago)."
        except Exception as e:
            return f"Error searching timeline: {e}"

    def query_duration(self, entity_name: str) -> str:
        """Calculates tracked lifetime durations for a person or object."""
        entity_name = entity_name.lower().strip()
        
        # Check current confirmed presence
        current_state = self._get_latest_confirmed_state()
        is_present = entity_name in [k.lower() for k in current_state.keys()]
        
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    "SELECT first_seen, last_seen, total_observations FROM entity_lifetimes WHERE LOWER(entity_name) = ?",
                    (entity_name,)
                )
                row = cursor.fetchone()
            finally:
                conn.close()
            
            if not row:
                return f"I don't have any tracking records for '{entity_name}' in my visual memory, Chinmaya."
            
            first_seen, last_seen, total_obs = row
            now = int(time.time())
            
            if is_present:
                # Calculate time elapsed since last appearance
                conn = sqlite3.connect(self.db_path)
                try:
                    cursor = conn.execute(
                        "SELECT timestamp FROM vision_event_timeline "
                        "WHERE LOWER(entity_name) = ? AND event_type LIKE '%APPEARED' "
                        "ORDER BY id DESC LIMIT 1", (entity_name,)
                    )
                    ts_row = cursor.fetchone()
                finally:
                    conn.close()
                start_ts = ts_row[0] if ts_row else first_seen
                duration_sec = now - start_ts
                return f"The {entity_name} is currently present and has been on the desk for {self._format_duration(duration_sec)}."
            else:
                # Calculate duration of the last tracked presence block
                conn = sqlite3.connect(self.db_path)
                try:
                    cursor = conn.execute(
                        "SELECT event_type, timestamp FROM vision_event_timeline "
                        "WHERE LOWER(entity_name) = ? ORDER BY id DESC LIMIT 2", (entity_name,)
                    )
                    rows = cursor.fetchall()
                finally:
                    conn.close()
                
                if len(rows) >= 2:
                    last_event, last_ts = rows[0]
                    prior_event, prior_ts = rows[1]
                    if "APPEARED" in prior_event and ("REMOVED" in last_event or "LEFT" in last_event):
                        duration_sec = last_ts - prior_ts
                        action = "was removed" if "REMOVED" in last_event else "left"
                        return f"The {entity_name} was present for {self._format_duration(duration_sec)} before it {action}."
                
                # General duration statistics
                duration_sec = last_seen - first_seen
                return f"The {entity_name} was tracked for a total duration of {self._format_duration(duration_sec)} over {total_obs} observation updates."
        except Exception as e:
            return f"Error retrieving tracking duration: {e}"

    def query_show_last_changes(self, limit: int = 10) -> str:
        return self.query_what_changed()

    def _format_duration(self, seconds: int) -> str:
        """Formats seconds into human-readable time spans."""
        if seconds < 60:
            return f"{seconds} seconds"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} minutes"
        hours = minutes // 60
        mins = minutes % 60
        if hours < 24:
            return f"{hours} hours and {mins} minutes"
        days = hours // 24
        hrs = hours % 24
        return f"{days} days, {hrs} hours and {mins} minutes"
