"""
skills/subsystem_health.py — ARIA Live Subsystem Health Monitor
===============================================================
Tracks the RUNTIME health of each physical subsystem (camera, tts, browser,
vision, llm, automation, object_detection) based on actual execution outcomes.

Unlike RuntimeCapabilities (which checks if Python modules are *installed*),
this module tracks whether subsystems are actually *working* at runtime:

  HEALTHY     — operating normally, no recent failures
  DEGRADED    — operating with reduced capability (e.g. camera slow, TTS hoarse)
  RECOVERING  — a restart / re-init is in progress after a failure
  FAILED      — completely unavailable, all retries exhausted
  UNKNOWN     — not yet initialized (startup state)

A global singleton `HEALTH` is exported so any module can read/update state
without import cycles.

Thread-safe. Zero external dependencies.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional


# ── State constants ──────────────────────────────────────────────────────────
HEALTHY    = "HEALTHY"
DEGRADED   = "DEGRADED"
RECOVERING = "RECOVERING"
FAILED     = "FAILED"
UNKNOWN    = "UNKNOWN"

# Subsystem names (canonical)
SUBSYSTEM_CAMERA           = "camera"
SUBSYSTEM_VISION           = "vision"
SUBSYSTEM_TTS              = "tts"
SUBSYSTEM_BROWSER          = "browser"
SUBSYSTEM_AUTOMATION       = "automation"
SUBSYSTEM_LLM              = "llm"
SUBSYSTEM_OBJECT_DETECTION = "object_detection"
SUBSYSTEM_FIREBASE         = "firebase"
SUBSYSTEM_MICROPHONE       = "microphone"

# All known subsystems (for full snapshot)
ALL_SUBSYSTEMS = [
    SUBSYSTEM_CAMERA,
    SUBSYSTEM_VISION,
    SUBSYSTEM_TTS,
    SUBSYSTEM_BROWSER,
    SUBSYSTEM_AUTOMATION,
    SUBSYSTEM_LLM,
    SUBSYSTEM_OBJECT_DETECTION,
    SUBSYSTEM_FIREBASE,
    SUBSYSTEM_MICROPHONE,
]


class SubsystemState:
    """Holds the live state for one subsystem."""

    def __init__(self, name: str):
        self.name = name
        self.status: str = UNKNOWN
        self.reason: str = ""
        self.failure_count: int = 0
        self.last_success_at: Optional[float] = None
        self.last_failure_at: Optional[float] = None
        self.last_updated_at: float = time.time()
        self.recovery_probe: Optional[Callable[[], bool]] = None  # Called on retry
        self.cooldown_until: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "failure_count": self.failure_count,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "last_updated_at": self.last_updated_at,
            "on_cooldown": time.time() < self.cooldown_until,
            "cooldown_remaining_s": max(0.0, self.cooldown_until - time.time()),
        }

    def is_available(self) -> bool:
        """HEALTHY and DEGRADED are considered available; RECOVERING depends on cooldown."""
        if self.status in (HEALTHY, DEGRADED):
            return True
        if self.status == RECOVERING:
            return time.time() >= self.cooldown_until  # available if retry window passed
        return False  # FAILED or UNKNOWN


class SubsystemHealthMonitor:
    """
    Thread-safe registry of live subsystem health states.

    Usage
    -----
    from skills.subsystem_health import HEALTH, HEALTHY, DEGRADED, FAILED

    # On successful init:
    HEALTH.mark_healthy("camera")

    # On OpenCV crash:
    HEALTH.mark_degraded("camera", "OpenCV C++ exception — cascade reloaded")

    # On complete failure:
    HEALTH.mark_failed("browser", "Playwright not responding after 3 retries")

    # Check before using:
    if HEALTH.is_available("tts"):
        voice.speak(text)
    else:
        print(f"[TTS FAILED] {text}")
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._states: Dict[str, SubsystemState] = {
            name: SubsystemState(name) for name in ALL_SUBSYSTEMS
        }

    # ── State mutators ────────────────────────────────────────────────────────

    def mark_healthy(self, name: str, reason: str = "") -> None:
        """Mark subsystem as fully operational."""
        with self._lock:
            state = self._get_or_create(name)
            was_failed = state.status in (FAILED, DEGRADED, RECOVERING)
            state.status = HEALTHY
            state.reason = reason
            state.last_success_at = time.time()
            state.last_updated_at = time.time()
            if was_failed and state.failure_count > 0:
                state.failure_count = 0  # reset on recovery
        if was_failed:
            print(f"[HealthMonitor] [OK] {name.upper()} recovered -> HEALTHY. {reason}")

    def mark_degraded(self, name: str, reason: str = "", increment_failure: bool = True) -> None:
        """Mark subsystem as operational but with reduced capability."""
        with self._lock:
            state = self._get_or_create(name)
            state.status = DEGRADED
            state.reason = reason
            state.last_failure_at = time.time()
            state.last_updated_at = time.time()
            if increment_failure:
                state.failure_count += 1
        print(f"[HealthMonitor] [WARN] {name.upper()} -> DEGRADED. {reason}")

    def mark_failed(self, name: str, reason: str = "", cooldown_seconds: float = 60.0) -> None:
        """Mark subsystem as completely unavailable. Sets a recovery cooldown."""
        with self._lock:
            state = self._get_or_create(name)
            state.status = FAILED
            state.reason = reason
            state.failure_count += 1
            state.last_failure_at = time.time()
            state.last_updated_at = time.time()
            state.cooldown_until = time.time() + cooldown_seconds
        print(f"[HealthMonitor] [FAIL] {name.upper()} -> FAILED. {reason} (cooldown {cooldown_seconds:.0f}s)")

    def mark_recovering(self, name: str, reason: str = "", probe: Optional[Callable[[], bool]] = None) -> None:
        """Mark subsystem as attempting recovery. Optionally provide a probe callable."""
        with self._lock:
            state = self._get_or_create(name)
            state.status = RECOVERING
            state.reason = reason
            state.last_updated_at = time.time()
            if probe is not None:
                state.recovery_probe = probe
        print(f"[HealthMonitor] [RETRY] {name.upper()} -> RECOVERING. {reason}")

    def mark_unknown(self, name: str) -> None:
        """Reset subsystem to UNKNOWN (not yet initialized)."""
        with self._lock:
            state = self._get_or_create(name)
            state.status = UNKNOWN
            state.reason = ""
            state.last_updated_at = time.time()

    # ── Queries ───────────────────────────────────────────────────────────────

    def is_available(self, name: str) -> bool:
        """Returns True if subsystem is HEALTHY or DEGRADED (usable)."""
        with self._lock:
            return self._states.get(name, SubsystemState(name)).is_available()

    def get_status(self, name: str) -> str:
        """Returns the current status string for a subsystem."""
        with self._lock:
            return self._states.get(name, SubsystemState(name)).status

    def get_state(self, name: str) -> SubsystemState:
        """Returns the full state object (a copy-safe dict via as_dict)."""
        with self._lock:
            return self._states.get(name, SubsystemState(name))

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """Returns a snapshot of all subsystem states as plain dicts."""
        with self._lock:
            return {name: state.as_dict() for name, state in self._states.items()}

    def get_failed(self) -> list:
        """Returns names of all FAILED subsystems."""
        with self._lock:
            return [n for n, s in self._states.items() if s.status == FAILED]

    def get_degraded(self) -> list:
        """Returns names of all DEGRADED subsystems."""
        with self._lock:
            return [n for n, s in self._states.items() if s.status == DEGRADED]

    def degradation_summary(self) -> str:
        """Human-readable one-liner for ARIA to announce degraded capabilities."""
        with self._lock:
            failed = [n for n, s in self._states.items() if s.status == FAILED]
            degraded = [n for n, s in self._states.items() if s.status == DEGRADED]
        parts = []
        if failed:
            parts.append("unavailable: " + ", ".join(failed))
        if degraded:
            parts.append("reduced: " + ", ".join(degraded))
        return "; ".join(parts) if parts else ""

    def all_healthy(self) -> bool:
        """True only if every tracked subsystem is HEALTHY."""
        with self._lock:
            return all(s.status == HEALTHY for s in self._states.values())

    # ── Recovery scheduling ───────────────────────────────────────────────────

    def attempt_recovery(self, name: str) -> bool:
        """
        If the subsystem has a recovery probe and the cooldown has elapsed,
        run the probe. Returns True if recovery succeeded.
        """
        with self._lock:
            state = self._states.get(name)
            if state is None or state.recovery_probe is None:
                return False
            if time.time() < state.cooldown_until:
                return False
            probe = state.recovery_probe

        # Run probe outside the lock to avoid deadlocks
        try:
            success = probe()
        except Exception as e:
            success = False
            print(f"[HealthMonitor] Recovery probe for {name} raised: {e}")

        if success:
            self.mark_healthy(name, "Recovery probe succeeded")
        else:
            self.mark_failed(name, "Recovery probe failed", cooldown_seconds=120.0)
        return success

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_or_create(self, name: str) -> SubsystemState:
        """Must be called with self._lock held."""
        if name not in self._states:
            self._states[name] = SubsystemState(name)
        return self._states[name]


# ── Global singleton ──────────────────────────────────────────────────────────
HEALTH = SubsystemHealthMonitor()
