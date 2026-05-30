import threading
import time

class AttentionManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AttentionManager, cls).__new__(cls)
                cls._instance.focus_priority = 0  # 0: Idle, 2: Low-Task, 3: Normal-Task, 4: High-Alert
                cls._instance.pending_notifications = []
                cls._instance.interrupted_task = None
                cls._instance._lock = threading.Lock()
            return cls._instance

    def evaluate_event(self, event_type, data):
        """
        Prioritizes incoming events:
        - Priority 4 (Critical): Battery critical, System errors.
        - Priority 3 (High): Due reminders, session checkpoints.
        - Priority 2 (Medium): Task execution logs, normal updates.
        - Priority 1 (Low): Stretch break suggestions, background completions.
        """
        prio_map = {
            "low_battery": 4,
            "system_error": 4,
            "reminder": 3,
            "session_resume": 3,
            "task_step": 2,
            "break_suggestion": 1,
            "telemetry_log": 1
        }
        
        event_prio = prio_map.get(event_type, 1)
        
        with self._lock:
            if event_prio >= self.focus_priority or self.focus_priority == 0:
                # Event is high priority enough to handle/speak immediately
                return "execute"
            else:
                # Event is lower priority than current focus; batch silently
                self.pending_notifications.append({
                    "time": time.strftime("%H:%M:%S"),
                    "type": event_type,
                    "data": data
                })
                # Cap pending notifications
                if len(self.pending_notifications) > 20:
                    self.pending_notifications.pop(0)
                return "batch"

    def set_focus(self, priority):
        with self._lock:
            self.focus_priority = priority

    def get_pending_summary(self):
        with self._lock:
            if not self.pending_notifications:
                return "No pending notifications."
            summary = f"Triaged Notifications ({len(self.pending_notifications)} pending):\n"
            for n in self.pending_notifications:
                summary += f"- [{n['type'].upper()}]: {n['data']}\n"
            return summary

    def clear_pending(self):
        with self._lock:
            self.pending_notifications.clear()
