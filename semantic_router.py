"""
semantic_router.py — Semantic Intent Router
============================================

Orchestrates intent classification, context tracking, and reference resolution.
This is the main entry point for the new conversational intelligence layer.

Usage in brain.py:
    from semantic_router import SemanticRouter
    router = SemanticRouter()
    
    # Before processing user input:
    routing_decision = router.route(user_input, has_image=False)
    
    if routing_decision["intent"] == "identity":
        # Trigger face recognition + memory
        ...
    elif routing_decision["intent"] == "followup":
        # Resolve reference and reuse previous context
        ...
"""

from intent_classifier import IntentClassifier
from context_engine import ConversationalContextEngine
from query_normalizer import QueryNormalizer
from skills.routing_policy import evaluate_tool_arming
from typing import Dict, Optional, Any


class SemanticRouter:
    """
    Main router that coordinates all semantic understanding components.
    """

    def __init__(self):
        self.classifier = IntentClassifier()
        self.context_engine = ConversationalContextEngine(max_history=15)
        self.normalizer = QueryNormalizer()
        from active_task_manager import ActiveTaskManager
        self.task_manager = ActiveTaskManager()

    def route(
        self,
        user_input: str,
        has_image: bool = False,
        user_name: Optional[str] = None,
        skip_repair: bool = False,
    ) -> Dict[str, Any]:
        """
        Main routing function. Call this BEFORE processing user input in brain.py.
        
        Returns routing decision with:
        - intent: Classification of the query (identity, followup, search, etc)
        - normalized_query: Grammar-corrected query
        - action_type: What action to take (identity_check, resolve_reference, web_search, etc)
        - context: Active context for this request
        - skip_web_search: Whether to block web search
        - needs_face_recognition: Whether to trigger face recognition
        
        Example:
        routing = router.route("who am i?")
        if routing["needs_face_recognition"]:
            face_result = recognize_face()
        """
        
        if not user_input:
            return self._empty_routing()

        # ── STEP 1: Normalize Query ────────────────────────────────────────────
        normalized, norm_log = self.normalizer.normalize(user_input)
        norm_confidence = self.normalizer.get_confidence_in_normalization(user_input, normalized)
        
        if normalized != user_input:
            print(f"[SemanticRouter] Query normalized: '{user_input}' -> '{normalized}'")
            print(f"  Confidence: {norm_confidence:.2f}")

        # ── STEP 2: Classify Intent ───────────────────────────────────────────
        intent, intent_confidence = self.classifier.classify(normalized, skip_repair=skip_repair)
        intent_meta = self.classifier.get_intent_metadata(intent)

        print(f"[SemanticRouter] Intent: {intent} (confidence: {intent_confidence:.2f})")

        # ── STEP 4: Resolve References and Ambiguities ────────────────────────
        resolved_context = None
        resolved_object = None
        resolved_step = None
        
        if intent == "followup":
            # Extract pronoun/reference
            pronoun = self._extract_pronoun(normalized)
            if pronoun:
                # 1. Resolve through conversational history
                resolved_context = self.context_engine.resolve_reference(pronoun)
                # 2. Resolve through Active Task objects
                resolved_object = self.task_manager.resolve_object_reference(pronoun)
                # 3. Resolve through Active Task steps
                resolved_step = self.task_manager.resolve_step_reference(pronoun)
                
                print(f"[SemanticRouter] Followup pronoun '{pronoun}':")
                if resolved_context:
                    print(f"  -> Conversational Context intent: {resolved_context.intent}")
                if resolved_object:
                    print(f"  -> Task Object Resolved: {resolved_object.type}[{resolved_object.id}] = {resolved_object.name}")
                if resolved_step:
                    print(f"  -> Task Step Resolved: {resolved_step.action} {resolved_step.target or ''}")

        # Check active browser context status
        browser_active = False
        try:
            from skills.browser_skill import BrowserSkill
            browser_active = BrowserSkill().is_browser_active()
        except Exception:
            pass

        has_valid_context = bool(resolved_context or resolved_object or resolved_step or self.task_manager.get_active_task() or browser_active)
        
        if intent == "followup" and not has_valid_context:
            if normalized.strip().lower() in {"yes", "no", "yep", "nah", "sure", "correct", "wrong", "confirm", "ok", "okay"}:
                intent = "chat"
                intent_confidence = 0.95
                intent_meta = self.classifier.get_intent_metadata(intent)

        tool_arming = evaluate_tool_arming(
            intent,
            intent_confidence,
            normalized,
            has_valid_context=has_valid_context,
            explicit_tool_signal=intent_meta.get("allow_web_search", False) or intent_meta.get("check_browser_first", False),
        )

        # ── Handle Active Task Graph Tracking ──────────────────────────
        # If we have a new search/browser action, start/resume a task graph representation
        if (intent in ["search", "browser"] or (intent == "followup" and not self.task_manager.get_active_task())) and self.should_create_task(normalized, intent, tool_arming.reason):
            site = self._extract_site(normalized)
            self.task_manager.start_task(goal=normalized, site=site, user_input=user_input)

        routing_decision = {
            # Input metadata
            "original_query": user_input,
            "normalized_query": normalized,
            "normalization_confidence": norm_confidence,
            
            # Intent information
            "intent": intent,
            "intent_confidence": intent_confidence,
            "intent_metadata": intent_meta,
            
            # Action directives
            "action_type": self._get_action_type(intent, resolved_context),
            "skip_web_search": intent == "chat" or intent_meta.get("no_web_search", False),
            "needs_face_recognition": intent_meta.get("needs_face_recognition", False),
            "needs_memory": intent_meta.get("needs_memory", False),
            "needs_context": intent_meta.get("needs_context", False),
            "check_browser_first": intent_meta.get("check_browser_first", False),
            "allow_web_search": intent_meta.get("allow_web_search", False),
            "tool_arming": tool_arming.as_dict(),
            "tool_armed": tool_arming.armed,
            "tool_arm_reason": tool_arming.reason,
            "requires_clarification": intent in ["search", "browser", "followup"] and not tool_arming.armed and tool_arming.reason in [
                "low_tool_confidence",
                "followup_without_valid_context",
                "missing_explicit_search_signal",
                "missing_browser_context_or_signal",
            ],
            
            # Context & Reference information
            "active_context": self.context_engine.get_active_context(),
            "previous_contexts": self.context_engine.get_previous_contexts(limit=3),
            "resolved_reference": resolved_context,
            "resolved_object": resolved_object,
            "resolved_step": resolved_step,
            "follow_up_context": self.context_engine.get_follow_up_context() if intent == "followup" else None,
            
            # Debug info
            "debug": {
                "normalization_log": norm_log,
                "context_history": self.context_engine.get_history_string(2),
                "task_dump": self.task_manager.debug_dump() if self.task_manager.get_active_task() else "No active task graph"
            },
        }

        return routing_decision

    def update_context(
        self,
        routing_decision: Dict,
        system_response: str,
        browser_state: Optional[Dict] = None,
        search_query: Optional[str] = None,
        extracted_data: Optional[str] = None,
    ):
        """
        Call this AFTER the system generates a response to update context tracking.
        """
        intent = routing_decision.get("intent", "chat")
        user_input = routing_decision.get("original_query", "")

        self.context_engine.push_context(
            intent=intent,
            user_input=user_input,
            system_response=system_response,
            browser_state=browser_state,
            search_query=search_query,
            extracted_data=extracted_data,
            metadata={
                "skip_web_search": routing_decision.get("skip_web_search", False),
                "browser_active": bool(browser_state),
            },
        )

        # Update Active Task Graph steps and objects
        active_task = self.task_manager.get_active_task()
        if active_task:
            if "failed" in system_response.lower() or "error" in system_response.lower():
                active_task.fail_task(reason=system_response)
            else:
                active_task.complete_step(result=system_response)

            # Ingest browser state elements if available
            if browser_state:
                if "url" in browser_state:
                    active_task.site = browser_state["url"]
                
                from active_task_manager import TaskObject
                # Ingest links
                for i, link in enumerate(browser_state.get("links", [])):
                    if link.get("is_visible_in_viewport"):
                        active_task.add_object(TaskObject(
                            id=link.get("aria_id"),
                            type="link",
                            name=link.get("text", "") or "link",
                            url=link.get("href"),
                            position=i
                        ))
                # Ingest buttons
                for i, btn in enumerate(browser_state.get("buttons", [])):
                    if btn.get("is_visible_in_viewport"):
                        active_task.add_object(TaskObject(
                            id=btn.get("aria_id"),
                            type="button",
                            name=btn.get("text", "") or "button",
                            position=i
                        ))
                # Ingest inputs
                for i, inp_el in enumerate(browser_state.get("inputs", [])):
                    if inp_el.get("is_visible_in_viewport"):
                        active_task.add_object(TaskObject(
                            id=inp_el.get("aria_id"),
                            type="input",
                            name=inp_el.get("text", "") or inp_el.get("placeholder", "") or "input",
                            position=i
                        ))
                # Ingest cards/results
                for i, card in enumerate(browser_state.get("cards", [])):
                    if card.get("is_visible_in_viewport"):
                        active_task.add_object(TaskObject(
                            id=card.get("aria_id"),
                            type="result",
                            name=card.get("text", "") or "result",
                            position=i
                        ))

    # ─────────────────────────────────────────────────────────────────────────

    def should_create_task(self, query: str, intent: str, tool_arming_reason: str) -> bool:
        """
        Only start a task graph if it's a real browser automation, planning,
        tracking, or reminder task. Pure informational queries should not become tasks.
        """
        if tool_arming_reason == "informational_query":
            return False
            
        query_lower = query.lower().strip()
        
        # Explicit task verbs/words
        task_keywords = ["track", "remind", "remember", "plan", "todo", "goal", "schedule", "automate", "buy", "order"]
        if any(kw in query_lower for kw in task_keywords):
            return True
            
        # Browser control/navigation tasks
        from skills.routing_policy import is_actionable_execution_request
        if intent == "browser" and is_actionable_execution_request(query):
            return True
            
        return False

    def _extract_site(self, query: str) -> Optional[str]:
        """Extract domain names from queries for site tracking."""
        query_lower = query.lower()
        for domain in ["amazon", "youtube", "wikipedia", "google", "github", "stackoverflow"]:
            if domain in query_lower:
                return f"{domain}.com"
        return None

    def _extract_pronoun(self, query: str) -> Optional[str]:
        """Extract the main pronoun/reference from a followup query."""
        query_lower = query.lower()
        
        # Map of pronouns to canonical forms
        pronoun_map = {
            "that one": "that",
            "first one": "first",
            "second one": "second",
            "third one": "third",
            "last one": "last",
            "other one": "other",
            "go back": "previous",
            "previous step": "previous",
            "it": "it",
            "that": "that",
            "this": "this",
            "there": "there",
            "them": "them",
            "page": "page",
            "tab": "page",
            "browser": "browser",
            "result": "result",
            "results": "result",
            "outcome": "result",
            "me": "me",
            "myself": "me",
            "i": "me",
        }
        
        for pronoun, canonical in pronoun_map.items():
            if pronoun in query_lower:
                return canonical
        
        return None

    def _get_action_type(self, intent: str, resolved_context=None) -> str:
        """Map intent to a specific action type."""
        action_map = {
            "repair": "handle_repair",
            "identity": "identity_check_and_memory",
            "memory": "recall_memory",
            "followup": "resolve_reference_and_answer",
            "search": "web_search",
            "browser": "extract_browser_context_and_answer",
            "chat": "general_chat",
        }
        return action_map.get(intent, "general_chat")

    def _empty_routing(self) -> Dict:
        """Return a default routing when input is empty."""
        return {
            "original_query": "",
            "normalized_query": "",
            "intent": "chat",
            "intent_confidence": 0.0,
            "action_type": "general_chat",
            "skip_web_search": False,
            "needs_face_recognition": False,
            "active_context": None,
            "debug": {"error": "Empty input"},
        }

    def reset_context(self):
        """Clear all conversation context."""
        self.context_engine.reset()
        self.task_manager.end_active_task(complete=False)
        print("[SemanticRouter] Conversation context reset.")


# ─────────────────────────────────────────────────────────────────────────────
# Integration helpers for brain.py

def should_skip_web_search(routing_decision: Dict) -> bool:
    """Helper: Check if web search should be skipped."""
    return routing_decision.get("skip_web_search", False)


def should_trigger_face_recognition(routing_decision: Dict) -> bool:
    """Helper: Check if face recognition should be triggered."""
    return routing_decision.get("needs_face_recognition", False)


def get_reference_context(routing_decision: Dict) -> Optional[str]:
    """
    Helper: Get the context from a resolved reference.
    Useful for answering followups like 'summarize that'.
    """
    resolved = routing_decision.get("resolved_reference")
    if resolved:
        return resolved.system_response
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Test
if __name__ == "__main__":
    router = SemanticRouter()

    print("=" * 70)
    print("SEMANTIC ROUTER INTEGRATION TEST")
    print("=" * 70)

    # Test Scenario 1: Identity query
    print("\n--- Scenario 1: Identity Query ---")
    routing = router.route("Who am I?")
    print(f"Intent: {routing['intent']}")
    print(f"Skip Web Search: {routing['skip_web_search']}")
    print(f"Needs Face Recognition: {routing['needs_face_recognition']}")

    # Simulate system response and update context
    router.update_context(
        routing,
        system_response="Based on face recognition, you are Chinmay.",
    )

    # Test Scenario 2: Followup query
    print("\n--- Scenario 2: Follow-up Query (Summarize the result) ---")
    routing2 = router.route("Summarize the result")
    print(f"Intent: {routing2['intent']}")
    print(f"Action Type: {routing2['action_type']}")
    print(f"Resolved Reference: {routing2['resolved_reference'].intent if routing2['resolved_reference'] else 'None'}")
    print(f"Context History:\n{routing2['debug']['context_history']}")

    # Test Scenario 3: Search query
    print("\n--- Scenario 3: Search Query ---")
    routing3 = router.route("Search for Python tutorials")
    print(f"Intent: {routing3['intent']}")
    print(f"Allow Web Search: {routing3['intent_metadata'].get('allow_web_search')}")

    # Test Scenario 4: Grammar correction demo
    print("\n--- Scenario 4: Grammar Correction ---")
    routing4 = router.route("who i am")  # Weak STT output
    print(f"Original: 'who i am'")
    print(f"Normalized: '{routing4['normalized_query']}'")
    print(f"Intent: {routing4['intent']}")
