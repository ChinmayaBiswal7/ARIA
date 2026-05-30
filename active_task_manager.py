"""
active_task_manager.py — Active Task Graph Engine
==================================================

Tracks structured task continuity across conversation turns.
Maintains: goal, current site, step, referenced objects, last result.

This enables ARIA to understand context like:
- "Open that second result"
- "Go back to the previous step"
- "No, the other one"
- "Continue with the next item"

Event Bus Integration:
  Every state transition publishes a typed ARIAEvents event.
  Events are OBSERVATIONAL only — subscribers must not mutate task state.
"""

import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

# Import lazily-safe: EventBus is a singleton so import at module level is fine
try:
    from skills.event_bus import EventBus, ARIAEvents
    _bus = EventBus()
except ImportError:
    _bus = None  # Graceful degradation if event_bus not available
    ARIAEvents = None


def _emit(event_type: str, **kwargs) -> None:
    """Publish a typed event. No-op if EventBus is unavailable."""
    if _bus and ARIAEvents:
        _bus.publish(event_type, ARIAEvents.build_payload(**kwargs))


@dataclass
class TaskObject:
    """Represents an object referenced in a task."""
    id: str
    type: str  # "result", "element", "tab", "file", "app"
    name: str
    description: Optional[str] = None
    position: Optional[int] = None  # For "first", "second", etc.
    url: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class TaskStep:
    """Represents a step in the active task."""
    step_number: int
    action: str  # "search", "click", "read", "summarize", etc.
    target: Optional[str] = None  # What we're acting on
    status: str = "pending"  # pending, in_progress, completed, failed
    result: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration: Optional[float] = None
    max_retries: int = 3
    retry_count: int = 0
    retry_reason: Optional[str] = None

    def start(self):
        self.start_time = time.time()
        self.status = "in_progress"

    def complete(self, result: Optional[str] = None):
        self.end_time = time.time()
        if self.start_time:
            self.duration = self.end_time - self.start_time
        self.status = "completed"
        self.result = result

    def fail(self, reason: Optional[str] = None):
        self.end_time = time.time()
        if self.start_time:
            self.duration = self.end_time - self.start_time
        self.status = "failed"
        self.result = reason

    def record_retry(self, reason: str):
        self.retry_count += 1
        self.retry_reason = reason


class ActiveTask:
    """
    Represents an active task being worked on.
    
    Example:
        task = ActiveTask(
            goal="Find Python documentation",
            site="github.com/python",
            user_input="Search for list comprehension"
        )
        task.add_step(action="search", target="list comprehension")
        task.add_object(TaskObject(id="r1", type="result", name="List Comprehensions Guide"))
    """

    def __init__(self, goal: str, site: Optional[str] = None, user_input: str = "", parent_id: Optional[str] = None):
        import uuid
        self.task_id = str(uuid.uuid4())
        self.parent_id = parent_id
        self.goal = goal
        self.site = site  # e.g., "github.com", "stackoverflow.com", "google.com"
        self.initial_input = user_input
        self.created_at = time.time()
        self.last_updated = time.time()
        self.start_time = time.time()
        self.end_time = None
        self.duration = None

        self.steps: List[TaskStep] = []
        self.objects: Dict[str, TaskObject] = {}  # id -> object
        self.current_step_index = -1
        self.result = None
        self.status = "CREATED"  # CREATED, QUEUED, RUNNING, WAITING, INTERRUPTED, COMPLETED, FAILED, CANCELLED

    def add_step(
        self,
        action: str,
        target: Optional[str] = None,
        status: str = "in_progress",
    ) -> TaskStep:
        """Add a new step to the task."""
        step = TaskStep(
            step_number=len(self.steps),
            action=action,
            target=target,
            status=status,
        )
        if status == "in_progress":
            step.start()
        self.steps.append(step)
        self.current_step_index = len(self.steps) - 1
        self.last_updated = time.time()
        print(f"[ActiveTask] Step {step.step_number}: {action} {target or ''}")
        _emit(ARIAEvents.STEP_STARTED, task_id=self.task_id, step_id=step.step_number, action=action,
              status=step.status)
        return step

    def complete_step(self, result: Optional[str] = None):
        """Mark current step as completed."""
        if 0 <= self.current_step_index < len(self.steps):
            step = self.steps[self.current_step_index]
            step.complete(result)
            self.last_updated = time.time()
            print(f"[ActiveTask] Step {self.current_step_index} completed (duration: {step.duration:.2f}s)")
            _emit(ARIAEvents.STEP_COMPLETED, task_id=self.task_id, step_id=step.step_number,
                  action=step.action, result=result, duration=step.duration)

    def add_object(self, obj: TaskObject) -> TaskObject:
        """Add a referenced object (result, element, tab, etc.)."""
        self.objects[obj.id] = obj
        self.last_updated = time.time()
        print(f"[ActiveTask] Object added: {obj.type}[{obj.id}] = {obj.name}")
        return obj

    def get_object(self, obj_id: str) -> Optional[TaskObject]:
        """Get an object by ID."""
        return self.objects.get(obj_id)

    def get_object_by_position(self, position: int) -> Optional[TaskObject]:
        """Get object by position (1st, 2nd, 3rd, etc.)."""
        objects_list = list(self.objects.values())
        if 0 <= position < len(objects_list):
            return objects_list[position]
        return None

    def get_object_by_type(self, obj_type: str) -> List[TaskObject]:
        """Get all objects of a specific type."""
        return [obj for obj in self.objects.values() if obj.type == obj_type]

    def set_result(self, result: str):
        """Set the overall task result."""
        self.result = result
        self.last_updated = time.time()
        print(f"[ActiveTask] Result set: {result[:100]}")

    def start_running(self):
        """Transition task to RUNNING status."""
        self.status = "RUNNING"
        self.last_updated = time.time()
        print(f"[ActiveTask] Task running: {self.goal}")
        _emit(ARIAEvents.TASK_STARTED, task_id=self.task_id, goal=self.goal, status=self.status)

    def pause_task(self):
        """Pause task execution (transitions to INTERRUPTED)."""
        self.status = "INTERRUPTED"
        self.last_updated = time.time()
        print(f"[ActiveTask] Task interrupted: {self.goal}")
        _emit(ARIAEvents.TASK_INTERRUPTED, task_id=self.task_id, goal=self.goal, status=self.status)

    def resume_task(self):
        """Resume task execution (transitions back to RUNNING)."""
        self.status = "RUNNING"
        self.last_updated = time.time()
        print(f"[ActiveTask] Task resumed: {self.goal}")
        _emit(ARIAEvents.TASK_RESUMED, task_id=self.task_id, goal=self.goal, status=self.status)

    def wait_task(self):
        """Put task in waiting state."""
        self.status = "WAITING"
        self.last_updated = time.time()
        print(f"[ActiveTask] Task waiting: {self.goal}")
        _emit(ARIAEvents.TASK_WAITING, task_id=self.task_id, goal=self.goal, status=self.status)

    def cancel_task(self):
        """Cancel task execution."""
        self.status = "CANCELLED"
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
        self.last_updated = time.time()
        print(f"[ActiveTask] Task cancelled: {self.goal}")
        _emit(ARIAEvents.TASK_CANCELLED, task_id=self.task_id, goal=self.goal, status=self.status, duration=self.duration)

    def complete_task(self):
        """Mark task as completed."""
        self.status = "COMPLETED"
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
        self.last_updated = time.time()
        print(f"[ActiveTask] Task completed: {self.goal}")
        _emit(ARIAEvents.TASK_COMPLETED, task_id=self.task_id, goal=self.goal, status=self.status,
              result=self.result, duration=self.duration)

    def fail_task(self, reason: str = "", failure_type: str = "FAILED_UNKNOWN"):
        """Mark task as failed with structured failure type."""
        self.status = "FAILED"
        # Extract structured failure type from reason if already present
        for ft in ["FAILED_TIMEOUT", "FAILED_NETWORK", "FAILED_PERMISSION", "FAILED_PARSE", "FAILED_CANCELLED", "FAILED_UNKNOWN"]:
            if reason.startswith(f"[{ft}]"):
                self.result = reason
                break
        else:
            self.result = f"[{failure_type}] {reason}" if reason else failure_type
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
        self.last_updated = time.time()
        print(f"[ActiveTask] Task failed: {self.goal} ({self.result})")
        _emit(ARIAEvents.TASK_FAILED, task_id=self.task_id, goal=self.goal, status=self.status,
              result=self.result, failure_type=failure_type, duration=self.duration)

    def abandon_task(self, reason: str = ""):
        """Mark task as abandoned (maps to CANCELLED)."""
        self.cancel_task()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "task_id": self.task_id,
            "parent_id": self.parent_id,
            "goal": self.goal,
            "site": self.site,
            "initial_input": self.initial_input,
            "status": self.status,
            "steps": [asdict(s) for s in self.steps],
            "objects": {k: asdict(v) for k, v in self.objects.items()},
            "current_step": self.current_step_index,
            "result": self.result,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
        }

    def get_summary(self) -> str:
        """Get a human-readable summary of the task."""
        lines = [
            f"Goal: {self.goal}",
            f"Status: {self.status}",
            f"Site: {self.site or 'N/A'}",
            f"Steps completed: {sum(1 for s in self.steps if s.status == 'completed')}/{len(self.steps)}",
            f"Objects referenced: {len(self.objects)}",
        ]
        if self.result:
            lines.append(f"Result: {self.result[:80]}")
        return "\n".join(lines)

    def get_trace_graph(self) -> str:
        """Return structured timing and execution tree for task observability."""
        duration_str = f"{self.duration:.2f}s" if self.duration else f"{time.time() - self.start_time:.2f}s (running)"
        lines = [
            f"Task: {self.goal} [ID: {self.task_id}]" + (f" (Parent: {self.parent_id})" if self.parent_id else ""),
            f" ├── Status: {self.status}",
            f" ├── Duration: {duration_str}",
            f" └── Steps Graph:"
        ]
        
        for i, step in enumerate(self.steps):
            branch = " └── " if i == len(self.steps) - 1 else " ├── "
            step_dur = f"({step.duration:.2f}s)" if step.duration else "(running)" if step.status == "in_progress" else ""
            retry_str = f" [Retries: {step.retry_count}]" if step.retry_count > 0 else ""
            lines.append(
                f"     {branch}Step {step.step_number}: {step.action} {step.target or ''} -> {step.status} {step_dur}{retry_str}"
            )
            if step.result:
                lines.append(f"          Result: {step.result[:100]}...")
            if step.retry_reason:
                lines.append(f"          Retry Reason: {step.retry_reason}")
                
        return "\n".join(lines)


class ActiveTaskManager:
    """
    Manages the current active task and task history.
    
    Enables conversational agents to maintain task continuity:
    - "Open that result" -> knows what "that result" is
    - "Go back to step 2" -> can navigate task history
    - "What was the second item?" -> can retrieve specific objects
    """

    def __init__(self, max_concurrent_tasks: int = 1):
        self.active_task: Optional[ActiveTask] = None
        self.task_history: List[ActiveTask] = []
        self.max_concurrent = max_concurrent_tasks

    def start_task(self, goal: str, site: Optional[str] = None, user_input: str = "", parent_id: Optional[str] = None) -> ActiveTask:
        """Start a new task."""
        # Save previous task to history if exists
        if self.active_task and self.active_task.status in ["ACTIVE", "RUNNING", "CREATED", "WAITING"]:
            self.active_task.abandon_task("New task started")
            self.task_history.append(self.active_task)

        # Create new task
        self.active_task = ActiveTask(goal=goal, site=site, user_input=user_input, parent_id=parent_id)
        self.active_task.start_running()
        print(f"[TaskManager] Started task: {goal}")
        return self.active_task

    def get_active_task(self) -> Optional[ActiveTask]:
        """Get the current active task."""
        return self.active_task

    def end_active_task(self, complete: bool = True):
        """End the current active task."""
        if self.active_task:
            if complete:
                self.active_task.complete_task()
            self.task_history.append(self.active_task)
            self.active_task = None

    def get_last_task(self, index: int = 1) -> Optional[ActiveTask]:
        """Get a previous task from history (1 = most recent)."""
        if index > 0 and index <= len(self.task_history):
            return self.task_history[-index]
        return None

    def resume_previous_task(self) -> Optional[ActiveTask]:
        """Resume the most recent previous task."""
        if self.task_history:
            task = self.task_history.pop()
            task.status = "ACTIVE"
            self.active_task = task
            print(f"[TaskManager] Resumed task: {task.goal}")
            return task
        return None

    # ── Task Object Reference Resolution ───────────────────────────────────
    def resolve_object_reference(self, ref: str, reference_timeout: float = 120.0) -> Optional[TaskObject]:
        """
        Resolve a pronoun or object reference with reference expiration.
        
        Examples:
        - "that" -> last added object
        - "the second one" -> 2nd object
        - "the first result" -> first result-type object
        - "the previous item" -> item before current
        """
        if not self.active_task:
            return None

        ref_clean = ref.strip()
        ref_lower = ref_clean.lower()
        now = time.time()

        # Helper to check if object is not expired
        def is_valid(obj: TaskObject) -> bool:
            return (now - obj.timestamp) <= reference_timeout

        # Check direct ID match first
        if ref_clean in self.active_task.objects:
            obj = self.active_task.objects[ref_clean]
            return obj if is_valid(obj) else None

        # Direct references
        if ref_lower in ["it", "that", "this", "the last one", "it"]:
            # Return most recently added object (if not expired)
            valid_objs = [v for v in self.active_task.objects.values() if is_valid(v)]
            if valid_objs:
                return valid_objs[-1]
            return None

        # Positional references (first, second, third, etc.)
        position_map = {
            "first": 0, "1st": 0, "1": 0,
            "second": 1, "2nd": 1, "2": 1,
            "third": 2, "3rd": 2, "3": 2,
            "fourth": 3, "4th": 3, "4": 3,
            "fifth": 4, "5th": 4, "5": 4,
        }

        for pos_word, pos_index in position_map.items():
            if pos_word in ref_lower:
                obj = self.active_task.get_object_by_position(pos_index)
                if obj and is_valid(obj):
                    return obj

        # Type-based references
        if "result" in ref_lower:
            results = [obj for obj in self.active_task.get_object_by_type("result") if is_valid(obj)]
            if results:
                return results[0]

        if "tab" in ref_lower:
            tabs = [obj for obj in self.active_task.get_object_by_type("tab") if is_valid(obj)]
            if tabs:
                return tabs[0]

        if "link" in ref_lower:
            results = [obj for obj in self.active_task.get_object_by_type("link") if is_valid(obj)]
            if results:
                return results[0]

        # Fallback: try partial name matching
        for obj in self.active_task.objects.values():
            if ref_lower in obj.name.lower() and is_valid(obj):
                return obj

        return None

    def resolve_step_reference(self, ref: str) -> Optional[TaskStep]:
        """Resolve a step reference like 'go back to step 2'."""
        if not self.active_task:
            return None

        ref_lower = ref.lower()

        # "previous step", "last step"
        if any(w in ref_lower for w in ["previous", "last", "back"]):
            if self.active_task.current_step_index > 0:
                return self.active_task.steps[self.active_task.current_step_index - 1]
            return None

        # "next step"
        if "next" in ref_lower:
            if self.active_task.current_step_index < len(self.active_task.steps) - 1:
                return self.active_task.steps[self.active_task.current_step_index + 1]
            return None

        # Numbered references: "step 2", "step 1"
        import re
        match = re.search(r"step\s+(\d+)", ref_lower)
        if match:
            step_num = int(match.group(1)) - 1
            if 0 <= step_num < len(self.active_task.steps):
                return self.active_task.steps[step_num]

        return None

    # ── Debugging ──────────────────────────────────────────────────────────
    def debug_dump(self) -> str:
        """Return detailed debug information."""
        if not self.active_task:
            return "[TaskManager] No active task"

        task = self.active_task
        lines = [
            "[TaskManager DEBUG]",
            f"Goal: {task.goal}",
            f"Status: {task.status}",
            f"Site: {task.site or 'N/A'}",
            f"\nSteps ({len(task.steps)} total):",
        ]

        for step in task.steps:
            status_icon = "✓" if step.status == "completed" else "⏳" if step.status == "in_progress" else "○"
            lines.append(f"  {status_icon} Step {step.step_number}: {step.action} {step.target or ''}")

        lines.append(f"\nObjects ({len(task.objects)} total):")
        for i, obj in enumerate(task.objects.values(), 1):
            lines.append(f"  {i}. [{obj.type}] {obj.name} (id: {obj.id})")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Test
if __name__ == "__main__":
    print("=" * 70)
    print("ACTIVE TASK MANAGER TEST")
    print("=" * 70)

    manager = ActiveTaskManager()

    # Start a task
    task = manager.start_task(
        goal="Find Python documentation",
        site="github.com",
        user_input="Search for list comprehension",
    )

    # Add steps
    task.add_step(action="search", target="list comprehension")
    task.add_object(
        TaskObject(id="r1", type="result", name="List Comprehensions - Official Python Docs", position=1)
    )
    task.complete_step("Found documentation page")

    task.add_step(action="read", target="documentation")
    task.add_object(
        TaskObject(id="r2", type="result", name="PEP 255 - Generator-Based List Comprehensions", position=2)
    )

    print(f"\n{manager.debug_dump()}")

    # Test reference resolution
    print("\n--- Reference Resolution Tests ---")
    print(f"Resolve 'that': {manager.resolve_object_reference('that')}")
    print(f"Resolve 'first': {manager.resolve_object_reference('first')}")
    print(f"Resolve 'second': {manager.resolve_object_reference('second')}")
    print(f"Resolve 'result': {manager.resolve_object_reference('result')}")

    # Test step reference
    print(f"\nResolve 'previous step': {manager.resolve_step_reference('previous step')}")
    print(f"Resolve 'step 1': {manager.resolve_step_reference('step 1')}")

    print(f"\n{task.get_summary()}")
