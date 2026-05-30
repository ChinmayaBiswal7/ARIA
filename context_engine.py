"""
context_engine.py — Conversational Context Engine
==================================================

Tracks active context across turns to enable follow-up resolution.
Maintains state about browser pages, searches, tasks, and user interactions.
"""

import time
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, asdict
from collections import deque


@dataclass
class ContextSnapshot:
    """Represents a snapshot of the conversation context."""
    timestamp: float
    turn_index: int
    intent: str
    user_input: str
    system_response: str
    browser_state: Optional[Dict] = None
    active_task: Optional[str] = None
    search_query: Optional[str] = None
    extracted_data: Optional[str] = None  # OCR/WebText/Search results
    metadata: Optional[Dict] = None


class ConversationalContextEngine:
    """
    Maintains a stack of active contexts from the current conversation.
    
    Example:
        - User: "Who am I?" -> Triggers face recognition
        - Context: {type: "identity", mode: "face_recognition", ...}
        
        - User: "Summarize the result" -> Resolves to face recognition result
        - Engine looks back -> finds identity context -> summarizes
    """

    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.context_stack: deque = deque(maxlen=max_history)
        self.current_context: Optional[ContextSnapshot] = None
        self.turn_index: int = 0

    def push_context(
        self,
        intent: str,
        user_input: str,
        system_response: str = "",
        browser_state: Optional[Dict] = None,
        active_task: Optional[str] = None,
        search_query: Optional[str] = None,
        extracted_data: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> ContextSnapshot:
        """
        Push a new context onto the stack.
        Called after each system turn.
        """
        snapshot = ContextSnapshot(
            timestamp=time.time(),
            turn_index=self.turn_index,
            intent=intent,
            user_input=user_input,
            system_response=system_response,
            browser_state=browser_state,
            active_task=active_task,
            search_query=search_query,
            extracted_data=extracted_data,
            metadata=metadata,
        )

        self.context_stack.append(snapshot)
        self.current_context = snapshot
        self.turn_index += 1

        print(
            f"[ContextEngine] Context #{self.turn_index}: {intent} | "
            f"Active for {len(str(system_response))} chars"
        )

        return snapshot

    def get_active_context(self) -> Optional[ContextSnapshot]:
        """Get the most recent context."""
        return self.current_context

    def get_previous_contexts(self, limit: int = 5) -> List[ContextSnapshot]:
        """Get the N most recent contexts (excluding current)."""
        contexts = list(self.context_stack)
        if self.current_context:
            # Remove current if it's in the stack
            contexts = [c for c in contexts if c.turn_index != self.current_context.turn_index]
        return contexts[-limit:]

    def find_context_by_intent(self, intent: str, limit: int = 3) -> List[ContextSnapshot]:
        """Find recent contexts matching a specific intent."""
        matches = [c for c in self.context_stack if c.intent == intent]
        return matches[-limit:]

    def find_browser_context(self) -> Optional[ContextSnapshot]:
        """Find the most recent browser/search context."""
        for context in reversed(self.context_stack):
            if context.browser_state or context.search_query or context.metadata.get("browser_active"):
                return context
        return None

    def find_identity_context(self) -> Optional[ContextSnapshot]:
        """Find the most recent identity/face recognition context."""
        for context in reversed(self.context_stack):
            if context.intent == "identity":
                return context
        return None

    def resolve_reference(self, pronoun: str, lookback_limit: int = 5) -> Optional[ContextSnapshot]:
        """
        Resolve a pronoun/reference to a previous context.
        
        Examples:
        - "it" -> last active task/search
        - "that" -> previous result
        - "there" -> browser page
        """
        pronoun_lower = pronoun.lower().strip()

        # Direct reference mapping
        if pronoun_lower in ["it", "that", "this"]:
            # Return most recent context with extracted data or result
            for context in reversed(self.context_stack):
                if context.extracted_data or context.system_response:
                    return context
            return self.current_context

        if pronoun_lower in ["there", "page", "tab", "browser"]:
            return self.find_browser_context()

        if pronoun_lower in ["me", "myself", "i"]:
            return self.find_identity_context()

        if pronoun_lower in ["result", "results", "outcome"]:
            # Return most recent non-chat context with output
            for context in reversed(self.context_stack):
                if context.system_response and len(context.system_response) > 20:
                    return context
            return self.current_context

        return None

    def get_follow_up_context(self) -> Optional[Dict]:
        """
        Get context needed to resolve the current follow-up query.
        Returns metadata suitable for routing/processing.
        """
        if not self.current_context:
            return None

        active = self.get_active_context()
        if not active:
            return None

        return {
            "previous_intent": active.intent,
            "previous_result": active.system_response,
            "browser_state": active.browser_state,
            "search_query": active.search_query,
            "extracted_data": active.extracted_data,
            "task_name": active.active_task,
            "time_since_last_turn": time.time() - active.timestamp,
            "metadata": active.metadata or {},
        }

    def reset(self):
        """Clear all context history."""
        self.context_stack.clear()
        self.current_context = None
        self.turn_index = 0
        print("[ContextEngine] Context history cleared.")

    def get_history_string(self, num_turns: int = 5) -> str:
        """Get a readable summary of recent context history."""
        recent = list(self.context_stack)[-num_turns:]
        lines = ["=== CONTEXT HISTORY ==="]
        for i, ctx in enumerate(recent, 1):
            lines.append(
                f"{i}. [{ctx.intent}] User: '{ctx.user_input[:40]}...' | "
                f"Response: '{ctx.system_response[:40]}...'"
            )
        return "\n".join(lines)

    def debug_dump(self) -> str:
        """Return detailed debug information about current context state."""
        active = self.get_active_context()
        history = self.get_history_string(3)

        debug_info = f"""
[ContextEngine DEBUG]
Turn Index: {self.turn_index}
Current Intent: {active.intent if active else "None"}
Current Input: {active.user_input[:60] if active else "None"}
Stack Size: {len(self.context_stack)}/{self.max_history}

{history}
"""
        return debug_info


# ─────────────────────────────────────────────────────────────────────────────
# Simple test
if __name__ == "__main__":
    engine = ConversationalContextEngine()

    print("=" * 60)
    print("CONVERSATIONAL CONTEXT ENGINE TEST")
    print("=" * 60)

    # Simulate a conversation
    engine.push_context(
        intent="identity",
        user_input="Who am I?",
        system_response="I see you are Chinmay based on face recognition.",
        metadata={"face_recognition": True},
    )

    engine.push_context(
        intent="search",
        user_input="Search for Python tutorials",
        system_response="Here are the top Python tutorials...",
        search_query="Python tutorials",
        extracted_data="Tutorial 1: Intro to Python...",
    )

    # Now test follow-up resolution
    print("\n--- Testing Follow-up Resolution ---")
    print("Query: 'Summarize the result'")
    
    context = engine.resolve_reference("result")
    if context:
        print(f"Resolved to: {context.intent} - '{context.system_response[:50]}'")

    print(f"\nContext History:\n{engine.get_history_string()}")
    print(f"\nDebug Info:\n{engine.debug_dump()}")
