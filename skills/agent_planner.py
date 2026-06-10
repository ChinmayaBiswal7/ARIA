"""
skills/agent_planner.py — ARIA Agent Planner
=============================================

Pure LLM reasoning loop. Separated from execution concerns.

Architecture:
    AgentPlanner (this file)
        ↓  produces ActionData dict each iteration
    ExecutorRuntime (executor_runtime.py)
        ↓  dispatches action, enforces timeouts, classifies failures
    ExecutionResult (success, observation, failure_type, duration)
        ↓  fed back into next LLM prompt as "last_observation"

What AgentPlanner is responsible for:
  - Building the LLM prompt with full context
  - Parsing the LLM JSON response (with fallback)
  - Termination guard logic (loop detection, step cap)
  - ActiveTask step recording and retry accounting
  - Publishing STEP_RETRIED and USER_INTERRUPT events

What AgentPlanner must NOT do:
  - Call browser APIs directly
  - Classify failure types (that's ExecutorRuntime / FailureType.classify)
  - Make assumptions about execution success without ExecutionResult
"""

import json
import time
import re
from brain import Brain
from skills.event_bus import EventBus, ARIAEvents

_bus = EventBus()


class AgentPlanner:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(AgentPlanner, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, brain=None):
        if self._initialized:
            return
        self.brain      = brain if brain else Brain()
        self.max_steps  = 6
        self.history: list = []
        self.cancel_task   = False
        self._initialized  = True

    # ─────────────────────────────────────────────────────────────────────
    # Main entry point
    # ─────────────────────────────────────────────────────────────────────

    def run_task(self, goal: str, speak_callback=None) -> str:
        """
        Execute a high-level goal using a ReAct (Reason + Act) loop.

        Each iteration:
          1. Read current page state
          2. Build a rich LLM prompt
          3. Parse the returned ActionData JSON
          4. Record the step in the ActiveTask graph
          5. Delegate execution to ExecutorRuntime
          6. Feed the typed ExecutionResult back into the next prompt

        Returns a human-readable completion or failure string.
        """
        from skills.browser_skill import BrowserSkill
        from skills.executor_runtime import ExecutorRuntime

        # ── Setup ─────────────────────────────────────────────────────────
        browser = BrowserSkill()
        if not browser.page:
            print("[AgentPlanner] Starting headed Playwright browser...")
            browser.start_browser()

        executor = ExecutorRuntime(browser=browser, brain=self.brain)

        current_step    = 0
        last_observation = "Browser started."
        self.history     = []
        last_action: str | None = None

        # Attach to the active task graph if one exists
        active_task = None
        if self.brain.semantic_router:
            active_task = self.brain.semantic_router.task_manager.get_active_task()
            if active_task:
                active_task.start_running()

        if speak_callback:
            speak_callback(f"Starting planning and execution for goal: {goal}")

        # ── ReAct loop ────────────────────────────────────────────────────
        while current_step < self.max_steps:

            # ── Cancellation check ────────────────────────────────────────
            if self.cancel_task:
                print("[AgentPlanner] Cancellation requested. Aborting.")
                self.cancel_task = False
                if active_task:
                    active_task.cancel_task()
                _bus.publish(ARIAEvents.USER_INTERRUPT, ARIAEvents.build_payload(
                    task_id=active_task.task_id if active_task else None,
                    status="CANCELLED", goal=goal,
                ))
                return "Task execution was stopped by your request."

            current_step += 1

            # ── Refresh page state ─────────────────────────────────────────
            if browser.page:
                try:
                    browser._update_page_state()
                except Exception as e:
                    print(f"[AgentPlanner] Failed to update page state: {e}")

            current_url, page_text, page_elements_summary = self._read_page(browser)

            print(f"\n[AgentPlanner] --- Step {current_step} ---")
            print(f"[AgentPlanner] URL: {current_url}")
            print(f"[AgentPlanner] Page snippet: {page_text[:200].strip()}")

            # ── LLM: decide next action ────────────────────────────────────
            prompt         = self._build_prompt(goal, current_step, current_url,
                                                last_observation, page_text,
                                                page_elements_summary)
            response_raw   = self.brain.think_raw(prompt)
            action_data    = self._parse_action(response_raw)

            action = action_data.get("action", "wait")
            thought = action_data.get("thought", "Determining next step...")

            print(f"[AgentPlanner] Thought: {thought}")
            print(f"[AgentPlanner] Action:  {action_data}")

            # ── ActiveTask: step recording + retry awareness ───────────────
            task_step = None
            if active_task:
                step_target = (
                    action_data.get("target")
                    or action_data.get("url")
                    or action_data.get("value")
                    or ""
                )
                last_step = active_task.steps[-1] if active_task.steps else None
                if (last_step
                        and last_step.action == action
                        and last_step.status == "failed"):
                    # Retry: update the SAME node, don't duplicate the graph
                    last_step.record_retry(
                        reason=f"Failed in previous turn: {last_observation}"
                    )
                    _bus.publish(ARIAEvents.STEP_RETRIED, ARIAEvents.build_payload(
                        task_id=active_task.task_id,
                        step_id=last_step.step_number,
                        action=action,
                        retry_count=last_step.retry_count,
                        result=last_observation[:120],
                    ))
                    task_step = last_step
                    task_step.start()
                else:
                    task_step = active_task.add_step(action=action, target=step_target)

            # ── Termination guards (before execution) ─────────────────────
            if last_action == "summarize" or action == "finish":
                print(f"[AgentPlanner] Termination: last={last_action}, current={action}")
                explanation = action_data.get("explanation", "Task completed successfully.")
                if active_task:
                    active_task.complete_step(result=explanation)
                    active_task.complete_task()
                if speak_callback:
                    speak_callback("Objective satisfied. Completing task.")
                return f"Task completed successfully. {explanation}"

            # Hard loop breaker for low-information actions
            if action == last_action and action in ("scroll", "wait"):
                print(f"[AgentPlanner] Loop detected: '{action}' repeated. Forcing finish.")
                if active_task:
                    active_task.complete_step(result="Loop detected, forcing finish.")
                    active_task.complete_task()
                return f"Task completed: Stopped after repeating action '{action}'."

            # Announce action to user
            if speak_callback:
                speak_callback(self._get_action_announcement(action_data))

            last_action = action

            # ── Delegate to ExecutorRuntime ────────────────────────────────
            result = executor.execute(
                action_data,
                task_id=active_task.task_id if active_task else None,
                step_id=task_step.step_number if task_step else None,
            )
            last_observation = result.observation

            # Speak summarize output
            if action == "summarize" and result.success and speak_callback:
                speak_callback(f"Here is my summary: {result.observation}")

            # ── ActiveTask: record outcome ─────────────────────────────────
            if active_task:
                if result.success:
                    active_task.complete_step(result=result.observation)
                else:
                    if task_step:
                        task_step.fail(reason=result.observation)

                    # Check retry budget
                    if task_step and task_step.retry_count >= task_step.max_retries:
                        ftype = result.failure_type or "FAILED_UNKNOWN"
                        active_task.fail_task(
                            reason=f"Step '{action}' failed too many times: {result.observation}",
                            failure_type=ftype,
                        )
                        return (
                            f"Task failed: Step '{action}' exceeded retry budget. "
                            f"[{ftype}] {result.observation}"
                        )

            print(f"[AgentPlanner] Observation: {last_observation}")

            # Log step to local history for prompt context
            self.history.append({
                "step":        current_step,
                "thought":     thought,
                "action":      action_data,
                "observation": last_observation,
                "success":     result.success,
                "duration":    f"{result.duration:.2f}s",
            })

            time.sleep(1.5)

        # ── Step cap exceeded ──────────────────────────────────────────────
        if active_task and active_task.status not in ("COMPLETED", "FAILED", "CANCELLED"):
            active_task.fail_task(
                reason="Reached maximum step limit before completion.",
                failure_type="FAILED_TIMEOUT",
            )
        return "Task stopped: Reached maximum step limit before completion."

    # ─────────────────────────────────────────────────────────────────────
    # Page reading helpers
    # ─────────────────────────────────────────────────────────────────────

    def _read_page(self, browser) -> tuple[str, str, str]:
        """Extract current URL, page text, and visible elements summary."""
        current_url = browser.page.url if browser.page else "No page open"
        page_text   = ""
        elements    = ""

        if not browser.page:
            return current_url, page_text, elements

        try:
            page_text = browser.page.evaluate("document.body.innerText")[:1500]
        except Exception:
            page_text = "Could not extract page text."

        try:
            visible = []
            for cat in ("inputs", "buttons", "links", "cards"):
                for el in browser.page_state.get(cat, []):
                    if not el.get("is_visible_in_viewport"):
                        continue
                    snippet = el.get("text", "")[:50]
                    aria_id = el.get("aria_id", "")
                    if cat == "links":
                        visible.append(
                            f"- Link [{aria_id}]: '{snippet}' (URL: {el.get('href','')[:40]})"
                        )
                    elif cat == "inputs":
                        visible.append(
                            f"- Input [{aria_id}]: '{snippet}' (placeholder: '{el.get('placeholder','')}')"
                        )
                    elif cat == "buttons":
                        visible.append(f"- Button [{aria_id}]: '{snippet}'")
                    elif cat == "cards":
                        visible.append(f"- Card [{aria_id}]: '{snippet}'")
            if visible:
                elements = "Visible Interactive Elements:\n" + "\n".join(visible[:20])
        except Exception:
            pass

        return current_url, page_text, elements

    # ─────────────────────────────────────────────────────────────────────
    # Prompt construction
    # ─────────────────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        goal: str,
        current_step: int,
        current_url: str,
        last_observation: str,
        page_text: str,
        page_elements_summary: str,
    ) -> str:
        # Wave 2 Skill Trust Routing Integration
        trust_warnings = ""
        try:
            from skills.intelligence_convergence_hub import AriaIntelligenceConvergenceHub
            hub = AriaIntelligenceConvergenceHub()
            overrides = hub.generate_convergence_overrides()
            penalties = overrides.get("skill_routing_penalties", {})
            avoid_skills = overrides.get("avoid_skills", [])
            
            lines = []
            if avoid_skills:
                lines.append("== ACTIVE ROUTING PENALTY WARNINGS ==")
                for skill in avoid_skills:
                    penalty = penalties.get(skill, "Penalized")
                    lines.append(f"- Action/Skill '{skill}': Status [{penalty}]. Avoid using if alternative paths exist.")
                lines.append("If browser actions keep failing, consider using 'finish' to suggest a command-line fallback or manual intervention.")
                lines.append("")
                trust_warnings = "\n".join(lines)
        except Exception as e:
            print(f"[AgentPlanner] Error loading trust warning overrides: {e}")

        return (
            f"You are the executive planning core of ARIA. Your high-level goal is: '{goal}'\n\n"
            f"{trust_warnings}"
            f"Current Step: {current_step}/{self.max_steps}\n"
            f"Current URL: {current_url}\n"
            f"Last Action Observation: {last_observation}\n\n"
            f"{page_elements_summary}\n\n"
            f"Visible Webpage Snippet:\n---\n{page_text}\n---\n\n"
            f"Choose the single best action to execute next. You must output exactly one JSON object. "
            f"Do not include any markdown format tags (like ```json). Return raw JSON text only.\n\n"
            f"CRITICAL TERMINATION RULES — YOU MUST FOLLOW THESE:\n"
            f"1. If the requested information has already been gathered or the user's goal has been completed, "
            f"you MUST immediately choose the 'finish' action.\n"
            f"2. Do NOT repeat searches, summaries, or clicks once the objective is satisfied.\n"
            f"3. NEVER repeat the same action twice in a row (e.g. do not call 'summarize' twice).\n"
            f"4. If you have already summarized the page, choose 'finish' next.\n"
            f"5. If you are unsure what to do next, choose 'finish'.\n\n"
            f"Format Required:\n"
            f"{{\n"
            f'  "thought": "Your step-by-step reasoning...",\n'
            f'  "action": "navigate" | "click" | "fill" | "press_key" | "scroll" | "wait" | "summarize" | "finish",\n'
            f'  "url": "URL_STRING" (only for "navigate"),\n'
            f'  "target": "TEXT_OR_SELECTOR_OR_ARIA_ID" (only for "click" and "fill". '
            f'Prefer ARIA IDs like "button_0" or "input_1" if listed above for high reliability),\n'
            f'  "value": "VALUE_TO_TYPE" (only for "fill"),\n'
            f'  "key": "KEY_NAME" (only for "press_key", e.g., "Enter"),\n'
            f'  "direction": "down" | "up" (only for "scroll"),\n'
            f'  "seconds": NUMBER (only for "wait"),\n'
            f'  "explanation": "Summary of achievements or final answer" (only for "summarize" and "finish")\n'
            f"}}\n\n"
            f"What is the next action JSON?"
        )

    # ─────────────────────────────────────────────────────────────────────
    # JSON parsing
    # ─────────────────────────────────────────────────────────────────────

    def _parse_action(self, response_raw: str) -> dict:
        """Parse LLM response into an ActionData dict, with fallback."""
        clean = response_raw.strip()

        # Try regex extraction first (most reliable)
        match = re.search(r"(\{.*\})", clean, re.DOTALL)
        if match:
            clean = match.group(1).strip()
        else:
            # Strip markdown fences
            for marker in ("```json", "```"):
                if clean.startswith(marker):
                    clean = clean[len(marker):]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()

        try:
            return json.loads(clean)
        except Exception as parse_err:
            print(f"[AgentPlanner] JSON parse failed: {parse_err}. Using rule-based fallback.")
            return self._fallback_parse_action(clean)

    def _fallback_parse_action(self, text: str) -> dict:
        """Rule-based extraction when the LLM doesn't return clean JSON."""
        t = text.lower()
        if "navigate" in t or "go to" in t:
            urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
            url  = urls[0] if urls else "https://www.google.com"
            return {"action": "navigate", "url": url, "thought": "Navigating (fallback)."}
        if "click" in t:
            parts  = text.split("click", 1)
            target = (
                parts[1].replace('"', "").replace("'", "").replace("{", "").replace("}", "").strip()
                if len(parts) > 1 else ""
            )
            return {"action": "click", "target": target, "thought": "Clicking (fallback)."}
        if "fill" in t or "type" in t:
            return {"action": "fill", "target": "search", "value": "query",
                    "thought": "Typing (fallback)."}
        if "scroll" in t:
            return {"action": "scroll", "direction": "down" if "down" in t else "up",
                    "thought": "Scrolling (fallback)."}
        if "finish" in t or "done" in t or "complete" in t:
            return {"action": "finish", "explanation": "Task completed (fallback).",
                    "thought": "Finishing (fallback)."}
        return {"action": "wait", "seconds": 2.0, "thought": "Waiting (fallback)."}

    # ─────────────────────────────────────────────────────────────────────
    # Voice announcement helper
    # ─────────────────────────────────────────────────────────────────────

    def _get_action_announcement(self, action_data: dict) -> str:
        """Return a user-friendly voice string for the upcoming action."""
        action = action_data.get("action", "")
        if action == "navigate":
            url = action_data.get("url", "").replace("https://", "").replace("http://", "").replace("www.", "")
            return f"Navigating to {url}."
        if action == "click":
            return f"Clicking on {action_data.get('target')}."
        if action == "fill":
            return f"Entering text into {action_data.get('target')}."
        if action == "press_key":
            return f"Pressing the {action_data.get('key')} key."
        if action == "scroll":
            return f"Scrolling {action_data.get('direction')}."
        if action == "wait":
            return "Waiting for page elements to load."
        if action == "summarize":
            return "Analyzing and summarizing the current page."
        if action == "finish":
            return "Finishing task orchestration."
        return "Preparing the next step."
