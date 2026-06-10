import sqlite3
import time
import os
from typing import Dict, Any, List

DB_PATH = "aria_orchestrator.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def update_agent_status(agent_name: str, state: str, current_task: str = None):
    with get_db_connection() as conn:
        now = int(time.time())
        conn.execute("""
            INSERT INTO agent_status (agent_name, state, current_task, started_at, heartbeat)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(agent_name) DO UPDATE SET
                state = excluded.state,
                current_task = excluded.current_task,
                started_at = excluded.started_at,
                heartbeat = excluded.heartbeat
        """, (agent_name, state, current_task, now if state == 'RUNNING' else None, now))
        conn.commit()

def update_agent_heartbeat(agent_name: str):
    with get_db_connection() as conn:
        now = int(time.time())
        conn.execute("""
            UPDATE agent_status SET heartbeat = ? WHERE agent_name = ?
        """, (now, agent_name))
        conn.commit()

def log_policy_effectiveness_for_task(conn, task_id: str, status: str):
    if status not in ('COMPLETED', 'FAILED'):
        return
    try:
        # Check if policy effectiveness ledger table exists
        cursor_check = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='policy_effectiveness_ledger'")
        if not cursor_check.fetchone():
            return
            
        cursor = conn.execute("SELECT campaign_id, agent_name, task_description FROM agent_tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        if row:
            camp_id = row["campaign_id"]
            agent_name = row["agent_name"]
            task_desc = row["task_description"]
            desc_lower = task_desc.lower()
            
            outcome_success = 1 if status == 'COMPLETED' else 0
            
            from skills.learning_engine import AriaLongTermLearningEngine
            engine = AriaLongTermLearningEngine(DB_PATH)
            for kw in ["spring", "docker", "java", "dsa", "dbms"]:
                if kw in desc_lower or kw == agent_name.lower():
                    policy_id = f"POL_DUR_{kw.upper()}"
                    val, pol_status = engine.fetch_calibrated_value(policy_id, 1.0)
                    if pol_status != "DEFAULT":
                        now = int(time.time())
                        conn.execute("""
                            INSERT INTO policy_effectiveness_ledger (policy_id, applied_at, campaign_id, task_id, outcome_success, notes)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (policy_id, now, camp_id, task_id, outcome_success, f"Task status updated to {status}. Base duration scaled by {val} ({pol_status})"))
                        
                        conn.execute("""
                            UPDATE system_operational_policies
                            SET last_applied = ?
                            WHERE policy_id = ?
                        """, (now, policy_id))
                        break
    except Exception as e:
        print(f"[AgentStatus] Error in log_policy_effectiveness_for_task: {e}")

def update_task_status(task_id: str, status: str, started_at: int = None, completed_at: int = None):
    with get_db_connection() as conn:
        if started_at is not None and completed_at is not None:
            conn.execute("""
                UPDATE agent_tasks 
                SET status = ?, started_at = ?, completed_at = ?
                WHERE id = ?
            """, (status, started_at, completed_at, task_id))
        elif started_at is not None:
            conn.execute("""
                UPDATE agent_tasks 
                SET status = ?, started_at = ?
                WHERE id = ?
            """, (status, started_at, task_id))
        elif completed_at is not None:
            conn.execute("""
                UPDATE agent_tasks 
                SET status = ?, completed_at = ?
                WHERE id = ?
            """, (status, completed_at, task_id))
        else:
            conn.execute("""
                UPDATE agent_tasks 
                SET status = ?
                WHERE id = ?
            """, (status, task_id))
        
        # Log policy effectiveness if completed/failed
        log_policy_effectiveness_for_task(conn, task_id, status)
        conn.commit()

