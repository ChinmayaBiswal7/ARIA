import threading
import time
import traceback
from skills.agent_registry import registry
from skills.agent_status import update_agent_status, update_agent_heartbeat, update_task_status, get_db_connection
from skills.event_bus import EventBus, ARIAEvents

class AriaWorkerAgent(threading.Thread):
    def __init__(self, task_meta: dict, on_finished_callback=None):
        super().__init__()
        self.task_meta = task_meta
        self.on_finished_callback = on_finished_callback
        self.daemon = True
        self.name = f"Worker-{task_meta['agent_name']}-{task_meta['id']}"
        self._heartbeat_stop_event = threading.Event()
        self._bus = EventBus()

    def run(self):
        tid = self.task_meta["id"]
        agent_name = self.task_meta["agent_name"]
        desc = self.task_meta["task_description"]
        target = self.task_meta["target"]
        
        # Publish task started event
        self._bus.publish(ARIAEvents.TASK_STARTED, ARIAEvents.build_payload(
            task_id=tid,
            status="RUNNING",
            goal=desc,
            action=agent_name
        ))

        # Update DB statuses
        now = int(time.time())
        update_task_status(tid, "RUNNING", started_at=now)
        update_agent_status(agent_name, "RUNNING", current_task=desc)

        # Start heartbeat update loop in background
        heartbeat_thread = threading.Thread(target=self._run_heartbeat_loop, name=f"Heartbeat-{agent_name}", daemon=True)
        heartbeat_thread.start()

        print(f"[Worker-{agent_name}] Starting task {tid}: {desc} (target: {target})")

        success = False
        result_str = ""
        try:
            agent = registry.get(agent_name)
            if not agent:
                raise ValueError(f"Agent '{agent_name}' not registered.")

            # Run the agent check BaseAgent type
            from skills.base_agent import BaseAgent
            if isinstance(agent, BaseAgent):
                payload = {"target": target}
                result_str = agent.run(
                    task_id=tid,
                    task_description=desc,
                    payload=payload,
                    campaign_id=self.task_meta.get("campaign_id")
                )
            else:
                result_str = agent.run(target, desc)
            success = True
        except Exception as e:
            result_str = f"Error: {str(e)}\nTraceback: {traceback.format_exc()}"
            print(f"[Worker-{agent_name}] Task {tid} failed: {e}")
        finally:
            # Stop heartbeat thread
            self._heartbeat_stop_event.set()
            heartbeat_thread.join(timeout=1.0)

            # Record completion state
            comp_time = int(time.time())
            status_str = "COMPLETED" if success else "FAILED"
            update_task_status(tid, status_str, completed_at=comp_time)
            
            # Save results to DB
            with get_db_connection() as conn:
                conn.execute(
                    "INSERT INTO agent_results (task_id, result_payload, confidence) VALUES (?, ?, ?)",
                    (tid, result_str, 1.0 if success else 0.0)
                )
                conn.commit()

            # Set agent status back to idle
            update_agent_status(agent_name, "IDLE")

            # Publish event
            evt_type = ARIAEvents.TASK_COMPLETED if success else ARIAEvents.TASK_FAILED
            self._bus.publish(evt_type, ARIAEvents.build_payload(
                task_id=tid,
                status=status_str,
                goal=desc,
                action=agent_name,
                result=result_str[:200]
            ))

            if self.on_finished_callback:
                try:
                    self.on_finished_callback(tid, success, result_str)
                except Exception as cb_err:
                    print(f"[Worker-{agent_name}] Error in finish callback: {cb_err}")

    def _run_heartbeat_loop(self):
        agent_name = self.task_meta["agent_name"]
        while not self._heartbeat_stop_event.is_set():
            try:
                update_agent_heartbeat(agent_name)
            except Exception as e:
                print(f"[Heartbeat-{agent_name}] Error updating heartbeat: {e}")
            for _ in range(50):
                if self._heartbeat_stop_event.is_set():
                    break
                time.sleep(0.1)
