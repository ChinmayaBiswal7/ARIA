"""
skills/runtime_capabilities.py - ARIA runtime capability registry.

Optional browser, desktop, vision, audio, and live-service dependencies are
treated as explicit capabilities so the cognitive core can degrade cleanly.
"""

from __future__ import annotations

import importlib.util
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


FULL_RUNTIME = "FULL_RUNTIME"
HEADLESS_COGNITION = "HEADLESS_COGNITION"
SAFE_MODE = "SAFE_MODE"
MINIMAL_MODE = "MINIMAL_MODE"

AVAILABLE = "AVAILABLE"
DEGRADED = "DEGRADED"
UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class RecoveryPolicy:
    """Suggested recovery behavior for a missing or degraded runtime capability."""

    action: str
    retry_after_seconds: Optional[int] = None
    fallback_mode: Optional[str] = None
    user_visible: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "retry_after_seconds": self.retry_after_seconds,
            "fallback_mode": self.fallback_mode,
            "user_visible": self.user_visible,
        }


@dataclass(frozen=True)
class CapabilityHealth:
    """Richer capability state for cognition, telemetry, and recovery."""

    name: str
    available: bool
    status: str
    confidence: float
    checked_at: Optional[float]
    missing_dependencies: List[str]
    recovery_policy: RecoveryPolicy

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "status": self.status,
            "confidence": self.confidence,
            "checked_at": self.checked_at,
            "missing_dependencies": list(self.missing_dependencies),
            "recovery_policy": self.recovery_policy.as_dict(),
        }


@dataclass
class RuntimeCapabilities:
    """Lazy, cached view of the optional systems available in this process."""

    _cache: Dict[str, bool] = field(default_factory=dict, init=False)
    _checked_at_by_capability: Dict[str, float] = field(default_factory=dict, init=False)
    _last_snapshot: Dict[str, bool] = field(default_factory=dict, init=False)
    _checked_at: Optional[float] = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    _MODULES = {
        "cv2": "cv2",
        "numpy": "numpy",
        "playwright": "playwright.sync_api",
        "pyautogui": "pyautogui",
        "firebase_admin": "firebase_admin",
        "pyttsx3": "pyttsx3",
        "pygame": "pygame",
        "ollama": "ollama",
        "chromadb": "chromadb",
    }

    _RECOVERY_POLICIES = {
        "browser_runtime": RecoveryPolicy(
            action="retry_browser_init",
            retry_after_seconds=30,
            fallback_mode=HEADLESS_COGNITION,
            user_visible=True,
        ),
        "desktop_control": RecoveryPolicy(
            action="disable_desktop_actions",
            retry_after_seconds=60,
            fallback_mode=SAFE_MODE,
            user_visible=True,
        ),
        "vision_runtime": RecoveryPolicy(
            action="disable_proactive_vision",
            retry_after_seconds=60,
            fallback_mode=HEADLESS_COGNITION,
            user_visible=True,
        ),
        "firebase_runtime": RecoveryPolicy(
            action="use_local_only_sync",
            retry_after_seconds=120,
            fallback_mode=SAFE_MODE,
            user_visible=False,
        ),
        "voice_runtime": RecoveryPolicy(
            action="use_text_only_output",
            retry_after_seconds=60,
            fallback_mode=SAFE_MODE,
            user_visible=True,
        ),
        "vector_memory": RecoveryPolicy(
            action="use_sqlite_keyword_fallback",
            retry_after_seconds=120,
            fallback_mode=SAFE_MODE,
            user_visible=False,
        ),
        "local_model_runtime": RecoveryPolicy(
            action="use_local_parser_fallback",
            retry_after_seconds=120,
            fallback_mode=SAFE_MODE,
            user_visible=False,
        ),
    }

    def _has_module(self, capability: str) -> bool:
        with self._lock:
            if capability not in self._cache:
                module_name = self._MODULES[capability]
                try:
                    self._cache[capability] = importlib.util.find_spec(module_name) is not None
                except (ImportError, ModuleNotFoundError, ValueError):
                    self._cache[capability] = False
                checked_at = time.time()
                self._checked_at = checked_at
                self._checked_at_by_capability[capability] = checked_at
            return self._cache[capability]

    def refresh(self) -> Dict[str, bool]:
        """Re-checks all capability probes and returns the latest snapshot."""
        with self._lock:
            self._cache.clear()
            self._checked_at_by_capability.clear()
        return self.snapshot()

    @property
    def has_cv2(self) -> bool:
        return self._has_module("cv2")

    @property
    def has_numpy(self) -> bool:
        return self._has_module("numpy")

    @property
    def has_playwright(self) -> bool:
        return self._has_module("playwright")

    @property
    def has_audio(self) -> bool:
        return self._has_module("pyttsx3") or self._has_module("pygame")

    @property
    def has_firebase(self) -> bool:
        return self._has_module("firebase_admin")

    @property
    def has_desktop_control(self) -> bool:
        return self._has_module("pyautogui")

    @property
    def has_voice_synthesis(self) -> bool:
        return self._has_module("pyttsx3")

    @property
    def has_ollama(self) -> bool:
        return self._has_module("ollama")

    @property
    def has_vector_store(self) -> bool:
        return self._has_module("chromadb")

    @property
    def has_vision(self) -> bool:
        return self.has_cv2 and self.has_numpy

    @property
    def degradation_mode(self) -> str:
        """Returns the current broad runtime mode."""
        if self.has_vision and self.has_playwright and self.has_audio and self.has_firebase and self.has_desktop_control:
            return FULL_RUNTIME
        if self.has_numpy and not (self.has_playwright or self.has_desktop_control or self.has_audio):
            return HEADLESS_COGNITION
        if self.has_numpy:
            return SAFE_MODE
        return MINIMAL_MODE

    def snapshot(self) -> Dict[str, bool]:
        """Returns a cached capability snapshot with stable public keys."""
        return {
            "has_cv2": self.has_cv2,
            "has_numpy": self.has_numpy,
            "has_playwright": self.has_playwright,
            "has_audio": self.has_audio,
            "has_firebase": self.has_firebase,
            "has_desktop_control": self.has_desktop_control,
            "has_voice_synthesis": self.has_voice_synthesis,
            "has_ollama": self.has_ollama,
            "has_vector_store": self.has_vector_store,
            "has_vision": self.has_vision,
        }

    def _dependency_health(
        self,
        name: str,
        dependencies: Dict[str, bool],
        recovery_policy: RecoveryPolicy,
        degraded_confidence: float = 0.41,
    ) -> CapabilityHealth:
        missing = [dep for dep, available in dependencies.items() if not available]
        available_count = len(dependencies) - len(missing)
        if not missing:
            status = AVAILABLE
            confidence = 0.92
            available = True
        elif available_count > 0:
            status = DEGRADED
            confidence = degraded_confidence
            available = False
        else:
            status = UNAVAILABLE
            confidence = 0.05
            available = False

        checked_times = [
            self._checked_at_by_capability.get(dep)
            for dep in dependencies
            if self._checked_at_by_capability.get(dep) is not None
        ]
        checked_at = max(checked_times) if checked_times else self._checked_at
        return CapabilityHealth(
            name=name,
            available=available,
            status=status,
            confidence=confidence,
            checked_at=checked_at,
            missing_dependencies=missing,
            recovery_policy=recovery_policy,
        )

    def health(self, name: str) -> CapabilityHealth:
        """Returns confidence/status/recovery metadata for a named capability."""
        if name == "browser_runtime":
            return self._dependency_health(
                name,
                {"playwright": self.has_playwright},
                self._RECOVERY_POLICIES[name],
            )
        if name == "desktop_control":
            return self._dependency_health(
                name,
                {"pyautogui": self.has_desktop_control},
                self._RECOVERY_POLICIES[name],
            )
        if name == "vision_runtime":
            return self._dependency_health(
                name,
                {"cv2": self.has_cv2, "numpy": self.has_numpy},
                self._RECOVERY_POLICIES[name],
            )
        if name == "firebase_runtime":
            return self._dependency_health(
                name,
                {"firebase_admin": self.has_firebase},
                self._RECOVERY_POLICIES[name],
            )
        if name == "voice_runtime":
            return self._dependency_health(
                name,
                {"pyttsx3": self.has_voice_synthesis},
                self._RECOVERY_POLICIES[name],
            )
        if name == "vector_memory":
            return self._dependency_health(
                name,
                {"chromadb": self.has_vector_store},
                self._RECOVERY_POLICIES[name],
            )
        if name == "local_model_runtime":
            return self._dependency_health(
                name,
                {"ollama": self.has_ollama},
                self._RECOVERY_POLICIES[name],
            )
        raise KeyError(f"Unknown runtime capability: {name}")

    def health_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """Returns rich health state for all first-class runtime capabilities."""
        names = [
            "browser_runtime",
            "desktop_control",
            "vision_runtime",
            "firebase_runtime",
            "voice_runtime",
            "vector_memory",
            "local_model_runtime",
        ]
        return {name: self.health(name).as_dict() for name in names}

    def recovery_policies(self) -> Dict[str, Dict[str, Any]]:
        return {name: policy.as_dict() for name, policy in self._RECOVERY_POLICIES.items()}

    def unavailable(self) -> List[str]:
        return [name for name, enabled in self.snapshot().items() if not enabled]

    def cognition_context(self) -> str:
        """Compact text ARIA can inject into reasoning context."""
        unavailable = self.unavailable()
        if not unavailable:
            return "Runtime capabilities: full runtime available."
        readable = ", ".join(k.replace("has_", "").replace("_", " ") for k in unavailable)
        degraded = [
            f"{name}={health['status']}({health['confidence']:.2f})"
            for name, health in self.health_snapshot().items()
            if health["status"] != AVAILABLE
        ]
        health_summary = "; ".join(degraded)
        return f"Runtime capabilities: {self.degradation_mode}. Unavailable: {readable}. Health: {health_summary}."

    def emit_change_events(self) -> List[Dict[str, str]]:
        """
        Emits CAPABILITY_LOST/CAPABILITY_RESTORED events when availability changes.
        Returns emitted event dicts for tests and dashboards.
        """
        current = self.refresh()
        events = []
        if not self._last_snapshot:
            self._last_snapshot = current
            return events

        for key, available in current.items():
            previous = self._last_snapshot.get(key)
            if previous is None or previous == available:
                continue
            event_type = "CAPABILITY_RESTORED" if available else "CAPABILITY_LOST"
            event = {"type": event_type, "capability": key}
            events.append(event)
            try:
                from skills.event_bus import EventBus
                EventBus().emit(event_type, {"capability": key})
            except Exception:
                pass

        self._last_snapshot = current
        return events


CAPABILITIES = RuntimeCapabilities()
