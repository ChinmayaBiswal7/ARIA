"""
skills/executor_queue.py — ARIA Executor Queue & Priority Scheduler
=====================================================================
Manages prioritized execution queue for tasks, implements cooperative cancellation
checks, and avoids task starvation via priority aging.
"""

import time
import heapq
import threading
from typing import Dict, Any, List, Optional, Tuple

class TaskItem:
    def __init__(self, task_id: str, goal: str, priority: int, agent_name: Optional[str] = None, target: Optional[str] = None):
        self.task_id = task_id
        self.goal = goal
        self.base_priority = priority  # 1 (Highest) to 10 (Lowest)
        self.creation_time = time.time()
        self.wait_ticks = 0
        self.cancelled = False
        self.running = False
        self.agent_name = agent_name
        self.target = target

    @property
    def dynamic_priority(self) -> float:
        """
        Priority Aging:
        Every tick the task waits in the queue reduces its priority number (making it higher priority).
        This guarantees low-priority tasks won't starve indefinitely.
        """
        age_bonus = self.wait_ticks * 0.5
        return max(1.0, float(self.base_priority) - age_bonus)

    def __lt__(self, other: 'TaskItem') -> bool:
        # Heapq sorts by lowest value first (highest dynamic priority first)
        if self.dynamic_priority != other.dynamic_priority:
            return self.dynamic_priority < other.dynamic_priority
        return self.creation_time < other.creation_time


class ExecutorQueue:
    def __init__(self):
        self._queue: List[TaskItem] = []
        self._lock = threading.Lock()
        self._active_task: Optional[TaskItem] = None

    def add_task(self, task_id: str, goal: str, priority: int = 5, agent_name: Optional[str] = None, target: Optional[str] = None) -> TaskItem:
        """Adds a task to the queue."""
        item = TaskItem(task_id, goal, priority, agent_name, target)
        with self._lock:
            heapq.heappush(self._queue, item)
            print(f"[ExecutorQueue] Enqueued task '{goal}' (priority: {priority}, id: {task_id})")
        return item

    def get_next_task(self) -> Optional[TaskItem]:
        """
        Pulls the next highest priority task.
        Ages all remaining tasks to prevent starvation.
        """
        with self._lock:
            if not self._queue:
                return None
                
            # Pop high priority task
            next_task = heapq.heappop(self._queue)
            
            # Age remaining tasks
            for task in self._queue:
                task.wait_ticks += 1
                
            # Re-heapify queue since dynamic priorities changed
            heapq.heapify(self._queue)
            
            self._active_task = next_task
            next_task.running = True
            print(f"[ExecutorQueue] Dequeued task: '{next_task.goal}' (dynamic priority: {next_task.dynamic_priority:.1f})")
            return next_task

    def cancel_task(self, task_id: str) -> bool:
        """
        Triggers cooperative cancellation.
        Marks target task as cancelled.
        """
        with self._lock:
            # Check active task
            if self._active_task and self._active_task.task_id == task_id:
                self._active_task.cancelled = True
                print(f"[ExecutorQueue] Flagged active task {task_id} for cooperative cancellation.")
                return True
                
            # Check queued tasks
            for task in self._queue:
                if task.task_id == task_id:
                    task.cancelled = True
                    print(f"[ExecutorQueue] Flagged queued task {task_id} for cooperative cancellation.")
                    return True
        return False

    def finish_active_task(self):
        """Clears the active task pointer when finished."""
        with self._lock:
            if self._active_task:
                print(f"[ExecutorQueue] Finished active task: '{self._active_task.goal}'")
                self._active_task.running = False
                self._active_task = None

    def get_active_task(self) -> Optional[TaskItem]:
        return self._active_task

    def get_queue_snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "task_id": t.task_id,
                    "goal": t.goal,
                    "base_priority": t.base_priority,
                    "dynamic_priority": round(t.dynamic_priority, 1),
                    "cancelled": t.cancelled,
                    "agent_name": t.agent_name,
                    "target": t.target
                }
                for t in sorted(self._queue)
            ]
