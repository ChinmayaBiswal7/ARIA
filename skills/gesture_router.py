import time
from typing import Dict, Any
from skills.blackboard import AriaBlackboard

class AriaGestureRouter:
    def __init__(self, aria_instance=None):
        self.aria = aria_instance
        self.blackboard = AriaBlackboard()

    @property
    def aria_inst(self):
        if self.aria is None:
            try:
                from skills.agent_orchestrator import AriaMultiAgentOrchestrator
                self.aria = AriaMultiAgentOrchestrator().aria
            except Exception:
                pass
        return self.aria

    def process_latest_perception_tick(self) -> str:
        """Inspects the blackboard whiteboard state and fires workflow actions."""
        # 1. Read latest gesture state
        gesture_data = self.blackboard.read(topic="vision", key="gesture_state")
        if not gesture_data or gesture_data.get("confidence", 0) < 0.80:
            return "NO_ACTION"

        gesture = gesture_data.get("gesture")
        if gesture == "UNKNOWN":
            return "NO_ACTION"

        print(f"[GestureRouter] Processing physical action directive token: {gesture}")

        # 2. Scan blackboard for any pending approval tasks under topic 'system'
        system_topic = self.blackboard.get_all("system")
        pending_approvals = []
        for key, data in system_topic.get("system", {}).items():
            if key.startswith("approval_"):
                val = data.get("value")
                if isinstance(val, dict) and val.get("approval_status") == "PENDING":
                    pending_approvals.append(val)

        if not pending_approvals and gesture != "OPEN_PALM":
            return "NO_PENDING_APPROVALS"

        now = time.time()
        aria_ctx = self.aria_inst

        # ── MAP DIRECTIVES STRAIGHT INTO THE PERCEPTION ROUTER ───────────
        if gesture == "THUMBS_UP":
            # Process double-confirmation approval gate
            for app in pending_approvals:
                app_id = app["approval_id"]
                confirm_key = f"pending_confirm_{app_id}"
                confirm_data = self.blackboard.read(topic="system", key=confirm_key)

                if not confirm_data:
                    # Stage pending confirmation with a timestamp
                    self.blackboard.publish(
                        topic="system",
                        key=confirm_key,
                        value={"timestamp": now},
                        source="GestureRouter",
                        ttl_hours=1
                    )
                    if aria_ctx and hasattr(aria_ctx, "_speak"):
                        aria_ctx._speak("Thumbs up detected. Show another thumbs up within three seconds to approve.")
                    print(f"[GestureRouter] Staged pending confirm for {app_id}")
                else:
                    # Second Thumbs Up: check elapsed confirmation window
                    elapsed = now - confirm_data.get("timestamp", 0)
                    if elapsed <= 3.0:
                        # Double thumbs-up confirmed! Transition status to APPROVED
                        app["approval_status"] = "APPROVED"
                        app["approved_at"] = int(now)
                        app["approved_by"] = "gesture"

                        self.blackboard.publish(
                            topic="system",
                            key=app_id,
                            value=app,
                            source="GestureRouter",
                            ttl_hours=24
                        )
                        # Clean up pending confirm key
                        self.blackboard.publish(topic="system", key=confirm_key, value=None, source="GestureRouter", ttl_hours=0)

                        if aria_ctx and hasattr(aria_ctx, "_speak"):
                            aria_ctx._speak("Action confirmed and approved.")
                        print(f"[GestureRouter] Approved approval token {app_id} via double thumbs-up.")
                    else:
                        # Confirmation window expired: treat as new first Thumbs Up
                        self.blackboard.publish(
                            topic="system",
                            key=confirm_key,
                            value={"timestamp": now},
                            source="GestureRouter",
                            ttl_hours=1
                        )
                        if aria_ctx and hasattr(aria_ctx, "_speak"):
                            aria_ctx._speak("Confirmation timed out. Show thumbs up again to confirm.")
                        print(f"[GestureRouter] Confirmation expired. Re-staged confirm for {app_id}")
            return "WORKFLOW_ACTION_APPROVED"

        elif gesture == "THUMBS_DOWN":
            # Immediately reject pending approval tasks
            for app in pending_approvals:
                app_id = app["approval_id"]
                app["approval_status"] = "REJECTED"
                app["rejected_at"] = int(now)
                app["rejected_by"] = "gesture"

                self.blackboard.publish(
                    topic="system",
                    key=app_id,
                    value=app,
                    source="GestureRouter",
                    ttl_hours=24
                )
                # Clean up any pending confirm
                confirm_key = f"pending_confirm_{app_id}"
                self.blackboard.publish(topic="system", key=confirm_key, value=None, source="GestureRouter", ttl_hours=0)

                if aria_ctx and hasattr(aria_ctx, "_speak"):
                    aria_ctx._speak("Action rejected.")
                print(f"[GestureRouter] Rejected approval token {app_id} via thumbs-down.")
            return "WORKFLOW_ACTION_REJECTED"

        elif gesture == "OPEN_PALM":
            # Instantly freeze the orchestrator campaign thread loops
            paused_any = False

            # 1. Update SQLite DB campaign and tasks statuses
            try:
                from skills.agent_status import get_db_connection
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id FROM campaigns WHERE status = 'RUNNING'")
                    running = cursor.fetchall()
                    if running:
                        conn.execute("UPDATE campaigns SET status = 'PAUSED' WHERE status = 'RUNNING'")
                        conn.execute("UPDATE agent_tasks SET status = 'INTERRUPTED' WHERE status = 'RUNNING'")
                        conn.commit()
                        paused_any = True
            except Exception as e:
                print(f"[GestureRouter] DB update campaign pause failed: {e}")

            # 2. Stop task scheduler loop
            if aria_ctx and hasattr(aria_ctx, "orchestrator") and aria_ctx.orchestrator:
                if hasattr(aria_ctx.orchestrator, "scheduler") and aria_ctx.orchestrator.scheduler:
                    aria_ctx.orchestrator.scheduler.stop()
                    paused_any = True

            if paused_any:
                if aria_ctx and hasattr(aria_ctx, "_speak"):
                    aria_ctx._speak("Campaign paused.")
                print("[GestureRouter] Paused active campaign scheduler and set DB campaigns to PAUSED.")
                return "WORKFLOW_CAMPAIGN_PAUSED"

        return "NO_ACTION"
