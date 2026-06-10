import sqlite3
import json
import time
from typing import Any, Optional, Dict
from skills.agent_status import get_db_connection

class AriaBlackboard:
    """
    Persistent, SQLite-backed inter-agent blackboard.
    Supports topic categorization and automatic TTL (Time-To-Live) expiration.
    """
    def publish(self, topic: str, key: str, value: Any, source: str, ttl_hours: int = 24):
        now = int(time.time())
        expires_at = now + (ttl_hours * 3600) if ttl_hours else None
        value_json = json.dumps(value)
        
        with get_db_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO blackboard_store (topic, key, value, source, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (topic.lower().strip(), key.lower().strip(), value_json, source, now, expires_at))
            conn.commit()
        print(f"[Blackboard] Published key '{key}' under topic '{topic}' (source: {source}, TTL: {ttl_hours}h)")

        # P9.5: Blackboard-to-EventBus Bridge
        try:
            from skills.event_bus import EventBus
            EventBus().publish("BLACKBOARD_PUBLISHED", {
                "topic": topic.lower().strip(),
                "key": key.lower().strip(),
                "value": value,
                "source": source
            })
        except Exception as eb_err:
            print(f"[Blackboard] EventBus bridge failed: {eb_err}")

    def read(self, topic: str, key: str) -> Optional[Any]:
        self.clean_expired()
        now = int(time.time())
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT value, expires_at FROM blackboard_store 
                WHERE topic = ? AND key = ?
            """, (topic.lower().strip(), key.lower().strip()))
            row = cursor.fetchone()
            if row:
                value_json, expires_at = row
                if expires_at and expires_at < now:
                    return None
                try:
                    return json.loads(value_json)
                except Exception:
                    return value_json
        return None

    def get_all(self, topic: str = None) -> Dict[str, Any]:
        self.clean_expired()
        now = int(time.time())
        results = {}
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if topic:
                cursor.execute("""
                    SELECT key, value, source, updated_at, expires_at 
                    FROM blackboard_store 
                    WHERE topic = ?
                """, (topic.lower().strip(),))
                rows = cursor.fetchall()
            else:
                cursor.execute("""
                    SELECT topic, key, value, source, updated_at, expires_at 
                    FROM blackboard_store
                """)
                rows = cursor.fetchall()
            
            for row in rows:
                if topic:
                    key, val, src, updated, expires = row
                    t = topic.lower().strip()
                else:
                    t, key, val, src, updated, expires = row
                
                if expires and expires < now:
                    continue
                    
                try:
                    parsed_val = json.loads(val)
                except Exception:
                    parsed_val = val
                    
                if t not in results:
                    results[t] = {}
                results[t][key] = {
                    "value": parsed_val,
                    "source": src,
                    "updated_at": updated,
                    "expires_at": expires
                }
        return results

    def clean_expired(self):
        now = int(time.time())
        try:
            with get_db_connection() as conn:
                conn.execute("DELETE FROM blackboard_store WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
                conn.commit()
        except Exception as e:
            print(f"[Blackboard] Error cleaning expired entries: {e}")
