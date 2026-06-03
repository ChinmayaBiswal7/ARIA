"""
skills/executor_runtime.py — ARIA Executor Runtime
====================================================

Deterministic action execution layer, fully separated from LLM planning.

Responsibilities:
  - Receive a single ActionData dict from the Planner
  - Dispatch to the correct tool (browser, filesystem, etc.)
  - Enforce per-action timeouts
  - Classify failures into the structured taxonomy
  - Return (success: bool, observation: str, failure_type: str | None)

What this layer must NOT do:
  - Call the LLM / Brain
  - Decide what action to take next
  - Manage task-level state (that stays in ActiveTask / AgentPlanner)

Design goal: fully unit-testable without a running LLM or browser.

Future extension points:
  - BrowserExecutor (current)
  - FilesystemExecutor
  - VoiceExecutor
  - 3DSceneExecutor
  All share the same execute() interface.
"""

import time
import threading
from typing import Optional, Tuple

from skills.event_bus import EventBus, ARIAEvents

_bus = EventBus()


# ─── Failure taxonomy ─────────────────────────────────────────────────────────

class FailureType:
    TIMEOUT    = "FAILED_TIMEOUT"
    NETWORK    = "FAILED_NETWORK"
    PERMISSION = "FAILED_PERMISSION"
    PARSE      = "FAILED_PARSE"
    CANCELLED  = "FAILED_CANCELLED"
    UNKNOWN    = "FAILED_UNKNOWN"

    @staticmethod
    def classify(error_msg: str) -> str:
        """Classify a raw error string into the structured failure taxonomy."""
        msg = error_msg.lower()
        if any(w in msg for w in ["timeout", "timed out", "deadline"]):
            return FailureType.TIMEOUT
        if any(w in msg for w in ["network", "dns", "unreachable", "offline", "connection"]):
            return FailureType.NETWORK
        if any(w in msg for w in ["permission", "denied", "access", "forbidden", "unauthorized"]):
            return FailureType.PERMISSION
        if any(w in msg for w in ["parse", "json", "invalid", "syntax", "decode"]):
            return FailureType.PARSE
        if any(w in msg for w in ["cancel", "abort", "interrupt"]):
            return FailureType.CANCELLED
        return FailureType.UNKNOWN


# ─── ExecutionResult ──────────────────────────────────────────────────────────

class ExecutionResult:
    """
    Strongly-typed result returned by ExecutorRuntime.execute().
    The Planner reads this to decide the next action — it never interprets
    raw strings or exceptions directly.
    """

    __slots__ = ("success", "observation", "failure_type", "duration")

    def __init__(
        self,
        success: bool,
        observation: str,
        failure_type: Optional[str] = None,
        duration: float = 0.0,
    ):
        self.success      = success
        self.observation  = observation
        self.failure_type = failure_type   # None if success
        self.duration     = duration

    def __repr__(self) -> str:
        if self.success:
            return f"ExecutionResult(OK, {self.observation[:60]!r}, {self.duration:.2f}s)"
        return f"ExecutionResult(FAIL/{self.failure_type}, {self.observation[:60]!r})"


# ─── ExecutorRuntime ──────────────────────────────────────────────────────────

class ExecutorRuntime:
    """
    Deterministic action executor for the ARIA browser skill.

    Instantiated once per planning session (or reused across steps).
    The browser instance is injected at construction time so this class
    remains independently testable.

    Usage:
        executor = ExecutorRuntime(browser=browser_skill)
        result = executor.execute(action_data, task_id="...", step_id=0)
    """

    # Per-action timeout limits (seconds).  Override via ACTION_TIMEOUTS.
    ACTION_TIMEOUTS = {
        "navigate":  20.0,
        "click":     10.0,
        "fill":      10.0,
        "press_key":  5.0,
        "scroll":     5.0,
        "wait":      30.0,   # user-requested wait, bounded
        "summarize": 30.0,
        "finish":     2.0,
    }
    DEFAULT_TIMEOUT = 15.0

    def __init__(self, browser, brain=None):
        """
        Args:
            browser: BrowserSkill instance (provides navigate, click, fill, etc.)
            brain:   Brain instance (needed for summarize action only)
        """
        self.browser = browser
        self.brain   = brain

    # ── Public interface ───────────────────────────────────────────────────

    def execute(
        self,
        action_data: dict,
        task_id: Optional[str] = None,
        step_id: Optional[int] = None,
    ) -> ExecutionResult:
        """
        Execute a single action dict produced by the Planner.

        Args:
            action_data: Dict with keys: action, url, target, value, key,
                         direction, seconds, explanation, thought
            task_id:     UUID of the parent task (for event payloads)
            step_id:     Step index within the task (for event payloads)

        Returns:
            ExecutionResult with success, observation, failure_type, duration
        """
        action  = action_data.get("action", "wait")
        timeout = self.ACTION_TIMEOUTS.get(action, self.DEFAULT_TIMEOUT)
        t_start = time.time()

        result = self._dispatch_with_timeout(action_data, action, timeout)
        result.duration = time.time() - t_start
        # NOTE: STEP_COMPLETED / STEP_FAILED events are published by ActiveTask
        # and AgentPlanner to enforce single-publisher-per-event discipline.
        # The executor's job is only to return a typed ExecutionResult.
        return result

    # ── Internal dispatch ──────────────────────────────────────────────────

    def _dispatch_with_timeout(
        self, action_data: dict, action: str, timeout: float
    ) -> ExecutionResult:
        """Run the action synchronously on the current thread to avoid thread-switching issues with Playwright/greenlet."""
        try:
            observation = self._dispatch(action_data, action)
        except Exception as e:
            err_str = str(e)
            ftype   = FailureType.classify(err_str)
            return ExecutionResult(
                success=False,
                observation=f"Exception during '{action}': {err_str}",
                failure_type=ftype,
            )

        if not observation:
            observation = f"No observation from '{action}'."

        # Heuristic: treat "failed" / "error" in browser skill responses as failures
        obs_lower = observation.lower()
        if any(w in obs_lower for w in ["failed", "error", "could not", "unable to"]):
            return ExecutionResult(
                success=False,
                observation=observation,
                failure_type=FailureType.classify(observation),
            )

        return ExecutionResult(success=True, observation=observation)

    def _dispatch(self, action_data: dict, action: str) -> str:
        """
        Pure action dispatch — no retries, no timeouts, no state management.
        Returns a human-readable observation string.
        Raises on unexpected exceptions (caught by _dispatch_with_timeout).
        """
        b = self.browser

        if action == "finish":
            return action_data.get("explanation", "Task finished.")

        if action == "summarize":
            if not self.brain:
                return "Cannot summarize: no Brain instance provided to ExecutorRuntime."
            summary     = b.summarize_page(self.brain)
            explanation = action_data.get("explanation", "")
            if explanation:
                return f"Page summarized: {summary}. {explanation}"
            return f"Page summarized: {summary}"

        if action == "navigate":
            url = action_data.get("url", "")
            if not url:
                return "Navigate failed: no URL provided."
            return b.navigate(url)

        if action == "click":
            target = action_data.get("target", "")
            if not target:
                return "Click failed: no target provided."
            return b.click_element(target)

        if action == "fill":
            target = action_data.get("target", "")
            value  = action_data.get("value", "")
            return b.fill_element(target, value)

        if action == "press_key":
            key = action_data.get("key", "Enter")
            if b.page:
                b.page.keyboard.press(key)
                return f"Pressed key '{key}'."
            return "Press key failed: no active page."

        if action == "scroll":
            direction = action_data.get("direction", "down")
            return b.scroll(direction)

        if action == "wait":
            raw_seconds = action_data.get("seconds", 2.0)
            # Bound user-requested waits to 20s max
            seconds = min(float(raw_seconds), 20.0)
            time.sleep(seconds)
            return f"Waited {seconds:.1f}s."

        return f"Unknown action '{action}' — skipped."
