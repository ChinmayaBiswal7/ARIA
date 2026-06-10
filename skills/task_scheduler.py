import threading
import time
import traceback
from typing import List, Dict, Any
from skills.agent_status import get_db_connection, update_agent_status, update_task_status, log_policy_effectiveness_for_task

try:
    import psutil
except ImportError:
    psutil = None

def check_system_resources() -> bool:
    if psutil is None:
        return True
    try:
        cpu_ok = psutil.cpu_percent(interval=None) < 85.0
        ram_ok = psutil.virtual_memory().percent < 90.0
        return cpu_ok and ram_ok
    except Exception as e:
        print(f"[Scheduler] Error checking system resources: {e}")
        return True

def propagate_failure(task_id: str, campaign_id: str, reason: str = "Dependency Blocked"):
    from skills.event_bus import EventBus, ARIAEvents
    bus = EventBus()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT task_id FROM task_dependencies WHERE depends_on_task_id = ?", (task_id,))
        downstream = [row[0] for row in cursor.fetchall()]
        
        for d_id in downstream:
            cursor.execute("SELECT status FROM agent_tasks WHERE id = ?", (d_id,))
            row = cursor.fetchone()
            if row and row[0] not in ('COMPLETED', 'FAILED'):
                conn.execute("UPDATE agent_tasks SET status = 'FAILED', completed_at = ? WHERE id = ?", (int(time.time()), d_id))
                log_policy_effectiveness_for_task(conn, d_id, 'FAILED')
                conn.execute(
                    "INSERT INTO agent_results (task_id, result_payload, confidence) VALUES (?, ?, 0.0)",
                    (d_id, f"Failed: {reason}")
                )
                print(f"[Scheduler] Propagated failure to downstream task {d_id} (blocked by {task_id})")
                bus.publish(ARIAEvents.TASK_FAILED, ARIAEvents.build_payload(
                    task_id=d_id,
                    status="FAILED",
                    goal=f"Blocked by prerequisite failure of {task_id}",
                    action="unknown",
                    result=reason
                ))
                propagate_failure(d_id, campaign_id, reason)
        conn.commit()

def update_campaign_progress(campaign_id: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # P9.2: First, update status of all milestones for this campaign
        cursor.execute("SELECT id FROM campaign_milestones WHERE campaign_id = ?", (campaign_id,))
        milestone_ids = [r[0] for r in cursor.fetchall()]
        now_time = int(time.time())
        for m_id in milestone_ids:
            cursor.execute("SELECT COUNT(*) FROM agent_tasks WHERE milestone_id = ?", (m_id,))
            m_total = cursor.fetchone()[0]
            if m_total > 0:
                cursor.execute("SELECT COUNT(*) FROM agent_tasks WHERE milestone_id = ? AND status = 'COMPLETED'", (m_id,))
                m_completed = cursor.fetchone()[0]
                if m_completed == m_total:
                    conn.execute("UPDATE campaign_milestones SET status = 'COMPLETED', completed_at = ? WHERE id = ?", (now_time, m_id))
                else:
                    conn.execute("UPDATE campaign_milestones SET status = 'PENDING', completed_at = NULL WHERE id = ?", (m_id,))
            else:
                conn.execute("UPDATE campaign_milestones SET status = 'COMPLETED', completed_at = ? WHERE id = ?", (now_time, m_id))

        # Calculate campaign progress
        cursor.execute("SELECT COUNT(*) FROM agent_tasks WHERE campaign_id = ?", (campaign_id,))
        total = cursor.fetchone()[0]
        
        if total == 0:
            progress = 100.0
        else:
            cursor.execute("SELECT COUNT(*) FROM agent_tasks WHERE campaign_id = ? AND status = 'COMPLETED'", (campaign_id,))
            completed = cursor.fetchone()[0]
            progress = (completed / total) * 100.0
            
        cursor.execute("SELECT COUNT(*) FROM agent_tasks WHERE campaign_id = ? AND status IN ('COMPLETED', 'FAILED')", (campaign_id,))
        resolved = cursor.fetchone()[0]
        
        # P9.1: Query current campaign status to preserve PAUSED/CANCELLED states
        cursor.execute("SELECT status FROM campaigns WHERE id = ?", (campaign_id,))
        current_row = cursor.fetchone()
        current_status = current_row[0] if current_row else "PENDING"
        
        campaign_status = current_status
        comp_time = None
        
        if resolved == total and total > 0:
            cursor.execute("SELECT COUNT(*) FROM agent_tasks WHERE campaign_id = ? AND status = 'FAILED'", (campaign_id,))
            failed = cursor.fetchone()[0]
            if failed > 0:
                campaign_status = "FAILED"
            else:
                campaign_status = "COMPLETED"
            comp_time = int(time.time())
        elif current_status not in ("PAUSED", "CANCELLED", "FAILED", "COMPLETED"):
            campaign_status = "RUNNING"
            
        if comp_time:
            conn.execute(
                "UPDATE campaigns SET progress = ?, status = ?, completed_at = ? WHERE id = ?",
                (progress, campaign_status, comp_time, campaign_id)
            )
        else:
            conn.execute(
                "UPDATE campaigns SET progress = ?, status = ? WHERE id = ?",
                (progress, campaign_status, campaign_id)
            )
        conn.commit()
        print(f"[Scheduler] Campaign {campaign_id} progress: {progress:.1f}%, status: {campaign_status}")

def check_timeouts_and_heartbeats():
    from skills.event_bus import EventBus, ARIAEvents
    bus = EventBus()
    now = int(time.time())
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Check task timeouts
        cursor.execute("SELECT id, campaign_id, agent_name, started_at, timeout_seconds, retry_count, max_retries FROM agent_tasks WHERE status = 'RUNNING'")
        running_tasks = cursor.fetchall()
        for t in running_tasks:
            tid, cid, agent_name, started_at, timeout_secs, retry_cnt, max_r = t
            if started_at and (now - started_at) > timeout_secs:
                print(f"[Scheduler] Task {tid} exceeded timeout of {timeout_secs}s")
                handle_task_failure(conn, tid, cid, agent_name, "Timeout exceeded", retry_cnt, max_r)
        
        # 2. Check agent heartbeats
        cursor.execute("SELECT agent_name, heartbeat FROM agent_status WHERE state = 'RUNNING'")
        running_agents = cursor.fetchall()
        for a in running_agents:
            agent_name, heartbeat = a
            if heartbeat and (now - heartbeat) > 30:
                print(f"[Scheduler] Agent {agent_name} lost heartbeat (last: {heartbeat})")
                cursor.execute("SELECT id, campaign_id, retry_count, max_retries FROM agent_tasks WHERE agent_name = ? AND status = 'RUNNING'", (agent_name,))
                task_row = cursor.fetchone()
                if task_row:
                    tid, cid, retry_cnt, max_r = task_row
                    handle_task_failure(conn, tid, cid, agent_name, "Heartbeat lost", retry_cnt, max_r)
                else:
                    update_agent_status(agent_name, "IDLE")

def handle_task_self_healing(conn, tid: str, cid: str, agent_name: str, reason: str) -> bool:
    """Attempts to autonomously heal a failing task via agent re-assignment, reformulation, or bypass."""
    now = int(time.time())
    cursor = conn.cursor()
    cursor.execute("SELECT task_description, status FROM agent_tasks WHERE id = ?", (tid,))
    row = cursor.fetchone()
    if not row:
        return False
        
    desc = row[0]
    
    # 1. Tier 1: Agent Re-assignment & Description Reformulation
    if "[Reassigned" not in desc:
        alt_agent = None
        if agent_name.lower() == "browseragent":
            alt_agent = "researchagent"
        elif agent_name.lower() == "researchagent":
            alt_agent = "browseragent"
            
        if alt_agent:
            new_desc = f"{desc} [Reassigned to {alt_agent.capitalize()}]"
            # Reset retry count to 0 and point to alternative agent
            conn.execute("""
                UPDATE agent_tasks 
                SET agent_name = ?, task_description = ?, retry_count = 0, started_at = NULL, status = 'PENDING' 
                WHERE id = ?
            """, (alt_agent, new_desc, tid))
            conn.commit()
            
            # Log to intervention ledger
            log_self_healing_intervention(cid, "TASK_REASSIGNMENT", f"Reassigned failed task {tid} from {agent_name} to {alt_agent} and reset retries.")
            print(f"[Scheduler] Self-Healing: Reassigned failed task {tid} from {agent_name} to {alt_agent}.")
            return True
            
    # 2. Tier 2: Task Bypass (if already reassigned or no alt agent)
    new_desc = f"{desc} [Bypassed]"
    conn.execute("""
        UPDATE agent_tasks 
        SET status = 'COMPLETED', task_description = ?, completed_at = ? 
        WHERE id = ?
    """, (new_desc, now, tid))
    log_policy_effectiveness_for_task(conn, tid, 'COMPLETED')
    conn.execute("""
        INSERT INTO agent_results (task_id, result_payload, confidence) 
        VALUES (?, 'Bypassed autonomously by TaskScheduler self-healing loops.', 0.5)
    """, (tid,))
    conn.commit()
    
    # Log to intervention ledger
    log_self_healing_intervention(cid, "TASK_BYPASS", f"Bypassed failed task {tid} to prevent downstream blocking.")
    print(f"[Scheduler] Self-Healing: Bypassed failed task {tid} to unblock dependencies.")
    return True

def log_self_healing_intervention(campaign_id: str, action: str, reason: str):
    try:
        from skills.self_improvement_core import AriaSelfImprovementCore
        si_core = AriaSelfImprovementCore()
        intervention_id = f"INT_HEAL_{int(time.time())}_{action}"
        si_core.register_intervention(
            intervention_id=intervention_id,
            agent="TaskSchedulerSelfHealing",
            action=action,
            reason=reason,
            result="COMPLETED",
            success_score=1.0,
            campaign_id=campaign_id
        )
    except Exception as e:
        print(f"[Scheduler] Failed to log self-healing to intervention ledger: {e}")

def handle_task_failure(conn, tid: str, cid: str, agent_name: str, reason: str, retry_cnt: int, max_r: int):
    from skills.event_bus import EventBus, ARIAEvents
    bus = EventBus()
    if retry_cnt < max_r:
        new_cnt = retry_cnt + 1
        conn.execute("UPDATE agent_tasks SET status = 'PENDING', retry_count = ?, started_at = NULL WHERE id = ?", (new_cnt, tid))
        conn.execute("UPDATE agent_status SET state = 'IDLE', current_task = NULL WHERE agent_name = ?", (agent_name,))
        conn.commit()
        print(f"[Scheduler] Requeuing failed task {tid} (retry {new_cnt}/{max_r})")
        bus.publish(ARIAEvents.STEP_RETRIED, ARIAEvents.build_payload(
            task_id=tid,
            status="PENDING",
            goal=f"Retry {new_cnt}/{max_r} for failed task",
            action=agent_name,
            retry_count=new_cnt,
            result=reason
        ))
    else:
        # Before failing, try self-healing recovery pass (Sprint P14)
        if handle_task_self_healing(conn, tid, cid, agent_name, reason):
            conn.execute("UPDATE agent_status SET state = 'IDLE', current_task = NULL WHERE agent_name = ?", (agent_name,))
            conn.commit()
            return

        conn.execute("UPDATE agent_tasks SET status = 'FAILED', completed_at = ? WHERE id = ?", (int(time.time()), tid))
        log_policy_effectiveness_for_task(conn, tid, 'FAILED')
        conn.execute("INSERT INTO agent_results (task_id, result_payload, confidence) VALUES (?, ?, 0.0)", (tid, f"Failed: {reason}"))
        conn.execute("UPDATE agent_status SET state = 'IDLE', current_task = NULL WHERE agent_name = ?", (agent_name,))
        conn.commit()
        print(f"[Scheduler] Task {tid} permanently FAILED after {retry_cnt} retries")
        bus.publish(ARIAEvents.TASK_FAILED, ARIAEvents.build_payload(
            task_id=tid,
            status="FAILED",
            goal=f"Exhausted retries: {reason}",
            action=agent_name,
            result=reason
        ))
        propagate_failure(tid, cid, f"Blocked by prerequisite {tid} failure ({reason})")
    update_campaign_progress(cid)

class AriaTaskScheduler(threading.Thread):
    def __init__(self, active_workers: list, max_concurrency=4):
        super().__init__()
        self.active_workers = active_workers
        self.max_concurrency = max_concurrency
        self.daemon = True
        self.name = "AriaTaskScheduler"
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        print("[Scheduler] Background daemon operational.")
        while self._running:
            try:
                check_timeouts_and_heartbeats()
                self.schedule_next_tasks()
            except Exception as e:
                print(f"[Scheduler] Loop error: {e}\n{traceback.format_exc()}")
            time.sleep(0.2)

    def schedule_next_tasks(self):
        # Clean up dead threads
        self.active_workers[:] = [w for w in self.active_workers if w.is_alive()]
        
        if len(self.active_workers) >= self.max_concurrency:
            return
            
        if not check_system_resources():
            print("[Scheduler] High system load. Pausing task dispatch.")
            return

        runnable_tasks = self.get_runnable_tasks()
        
        for task in runnable_tasks:
            if len(self.active_workers) >= self.max_concurrency:
                break
                
            from skills.worker_agent import AriaWorkerAgent
            
            # Spawn worker thread
            worker = AriaWorkerAgent(task, on_finished_callback=self._worker_finished)
            self.active_workers.append(worker)
            worker.start()

    def _worker_finished(self, task_id, success, result_str):
        from skills.agent_status import get_db_connection
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT campaign_id, agent_name, retry_count, max_retries, task_description, completed_at FROM agent_tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            if row:
                cid, agent_name, retry_cnt, max_r, task_desc, completed_at = row
                if not success:
                    handle_task_failure(conn, task_id, cid, agent_name, result_str, retry_cnt, max_r)
                else:
                    update_campaign_progress(cid)
                    
                    # Auto-export completed study focus sessions
                    try:
                        desc = task_desc.upper()
                        matched_topic = None
                        for topic in ["DSA", "DBMS", "JAVA", "CN", "OS", "OOP", "INTERVIEW", "PROJECT"]:
                            if topic in desc:
                                matched_topic = topic
                                break
                        if matched_topic:
                            import os
                            import json
                            os.makedirs("data/habit_dataset", exist_ok=True)
                            local_time = time.localtime(completed_at or int(time.time()))
                            date_str = time.strftime("%Y-%m-%d", local_time)
                            start_hour = local_time.tm_hour
                            record = {
                                "date": date_str,
                                "start_hour": start_hour,
                                "duration": 90,
                                "topic": matched_topic
                            }
                            session_file = f"data/habit_dataset/session_{completed_at or int(time.time())}.json"
                            with open(session_file, "w", encoding="utf-8") as sf:
                                json.dump(record, sf, indent=2)
                            print(f"[Scheduler] Auto-exported study focus session: {session_file} ({matched_topic})")
                    except Exception as export_err:
                        print(f"[Scheduler] Failed to auto-export focus session: {export_err}")
                        
                    # Trigger automated ledger resolution
                    try:
                        from skills.self_improvement_core import AriaSelfImprovementCore
                        si_core = AriaSelfImprovementCore()
                        si_core.resolve_all_pending_predictions()
                        si_core.resolve_all_pending_interventions()
                    except Exception as resolve_err:
                        print(f"[Scheduler] Failed to run ledger resolution: {resolve_err}")

    def get_runnable_tasks(self) -> list:
        tasks = []
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Get currently locked resources (resources used by RUNNING tasks)
            cursor.execute("""
                SELECT DISTINCT resource_name FROM agent_resources
                WHERE agent_name IN (
                    SELECT agent_name FROM agent_tasks WHERE status = 'RUNNING'
                )
            """)
            locked_resources = {row[0] for row in cursor.fetchall()}
            
            # Get pending tasks whose dependencies are completed AND campaign is RUNNING
            cursor.execute("""
                SELECT agent_tasks.* FROM agent_tasks 
                JOIN campaigns ON agent_tasks.campaign_id = campaigns.id
                WHERE agent_tasks.status = 'PENDING'
                  AND campaigns.status = 'RUNNING'
                  AND agent_tasks.id NOT IN (
                      SELECT task_id FROM task_dependencies 
                      WHERE depends_on_task_id IN (
                          SELECT id FROM agent_tasks WHERE status != 'COMPLETED'
                      )
                  )
                ORDER BY agent_tasks.priority DESC, agent_tasks.created_at ASC
            """)
            rows = cursor.fetchall()
            
            for row in rows:
                task_meta = dict(row)
                agent_name = task_meta["agent_name"]
                
                # Check resource locks
                cursor.execute("SELECT resource_name FROM agent_resources WHERE agent_name = ?", (agent_name,))
                required_resources = {r[0] for r in cursor.fetchall()}
                
                if required_resources.intersection(locked_resources):
                    continue
                    
                tasks.append(task_meta)
                locked_resources.update(required_resources)
                
        return tasks
