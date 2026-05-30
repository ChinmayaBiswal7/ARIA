"""
skills/event_bus.py — ARIA Event Bus
=====================================

Singleton publish/subscribe event bus for decoupled system-wide coordination.

Design rules:
  - Events are OBSERVATIONAL only. Subscribers must NOT mutate planner state.
  - All payloads are strictly typed via build_payload() to prevent event chaos.
  - Wildcard subscriptions ("*") receive every event for tracing/dashboards.

Usage:
    bus = EventBus()
    bus.subscribe(ARIAEvents.TASK_STARTED, my_handler)
    bus.publish(ARIAEvents.TASK_STARTED, ARIAEvents.build_payload(task_id="..."))
"""

import threading
import time
from typing import Any, Callable, Dict, List, Optional


# ─── Typed Event Constants ────────────────────────────────────────────────────

class ARIAEvents:
    """Canonical event type strings for the ARIA runtime."""

    # Task lifecycle
    TASK_CREATED     = "TASK_CREATED"
    TASK_QUEUED      = "TASK_QUEUED"
    TASK_STARTED     = "TASK_STARTED"
    TASK_COMPLETED   = "TASK_COMPLETED"
    TASK_FAILED      = "TASK_FAILED"
    TASK_CANCELLED   = "TASK_CANCELLED"
    TASK_INTERRUPTED = "TASK_INTERRUPTED"
    TASK_RESUMED     = "TASK_RESUMED"
    TASK_WAITING     = "TASK_WAITING"

    # Step lifecycle
    STEP_STARTED   = "STEP_STARTED"
    STEP_COMPLETED = "STEP_COMPLETED"
    STEP_FAILED    = "STEP_FAILED"
    STEP_RETRIED   = "STEP_RETRIED"

    # Memory & context
    MEMORY_UPDATED = "MEMORY_UPDATED"

    # User signals
    USER_INTERRUPT = "USER_INTERRUPT"

    @staticmethod
    def build_payload(
        task_id: Optional[str] = None,
        step_id: Optional[int] = None,
        status: Optional[str] = None,
        goal: Optional[str] = None,
        action: Optional[str] = None,
        result: Optional[str] = None,
        failure_type: Optional[str] = None,
        retry_count: Optional[int] = None,
        duration: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build a strictly typed event payload.
        Only known keys are allowed; use `extra` for one-off metadata.
        Keeps payloads consistent and prevents free-form dict sprawl.
        """
        payload: Dict[str, Any] = {
            "task_id":      task_id,
            "step_id":      step_id,
            "status":       status,
            "goal":         goal,
            "action":       action,
            "result":       result,
            "failure_type": failure_type,
            "retry_count":  retry_count,
            "duration":     duration,
            "timestamp":    time.time(),
        }
        # Drop None values to keep payloads clean
        payload = {k: v for k, v in payload.items() if v is not None}
        if extra:
            payload.update(extra)
        return payload


# ─── EventBus ─────────────────────────────────────────────────────────────────

class EventBus:
    """
    Thread-safe singleton event bus.

    Subscribers register callbacks per event type (or "*" for all events).
    Callbacks receive the full event envelope:
        {
            "time": "HH:MM:SS",
            "type": "TASK_STARTED",
            "data": { ...ARIAEvents.build_payload() result... }
        }

    WARNING: Do NOT let callbacks mutate planner/task state. Events are
    observational. Bidirectional coupling leads to recursion hell.
    """

    _instance: Optional["EventBus"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._listeners: Dict[str, List[Callable]] = {}
                inst._history: List[Dict] = []
                inst._history_lock = threading.Lock()
                inst._max_history = 200
                cls._instance = inst
            return cls._instance

    # ── Subscribe ──────────────────────────────────────────────────────────

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Register a callback for a specific event type (or '*' for all)."""
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        if callback not in self._listeners[event_type]:
            self._listeners[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Remove a previously registered callback."""
        if event_type in self._listeners:
            try:
                self._listeners[event_type].remove(callback)
            except ValueError:
                pass

    # ── Publish ────────────────────────────────────────────────────────────

    def publish(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        """
        Publish an event to all registered subscribers.
        Always use ARIAEvents.build_payload() to construct `data`.
        """
        envelope = {
            "time": time.strftime("%H:%M:%S"),
            "type": event_type,
            "data": data or {},
        }

        # Append to bounded history
        with self._history_lock:
            self._history.append(envelope)
            if len(self._history) > self._max_history:
                self._history.pop(0)

        # Notify specific subscribers
        for cb in self._listeners.get(event_type, []):
            self._safe_call(cb, envelope, event_type)

        # Notify wildcard subscribers (e.g. dashboard trace listener)
        for cb in self._listeners.get("*", []):
            self._safe_call(cb, envelope, "*")

    def _safe_call(self, callback: Callable, envelope: Dict, label: str) -> None:
        try:
            callback(envelope)
        except Exception as e:
            print(f"[EventBus] Subscriber error on '{label}': {e}")

    # ── History ────────────────────────────────────────────────────────────

    def get_history(self, event_type: Optional[str] = None) -> List[Dict]:
        """Return event history, optionally filtered by type."""
        with self._history_lock:
            if event_type:
                return [e for e in self._history if e["type"] == event_type]
            return list(self._history)

    def clear_history(self) -> None:
        with self._history_lock:
            self._history.clear()

    def get_stats(self) -> Dict[str, int]:
        """Return per-event-type counts from history."""
        with self._history_lock:
            counts: Dict[str, int] = {}
            for e in self._history:
                counts[e["type"]] = counts.get(e["type"], 0) + 1
            return counts
