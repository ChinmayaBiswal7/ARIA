"""
skills/routing_policy.py - deterministic routing and tool-arming policy.

LLMs can propose language understanding, but tool execution is authorized by
explicit runtime policy so casual conversation cannot escalate into actions.
"""

import re
from dataclasses import dataclass
from typing import Dict, Optional


ROUTING_HIERARCHY = [
    "repair",
    "chat",
    "identity",
    "memory",
    "followup",
    "browser",
    "search",
]

CONVERSATIONAL_INTENTS = {"chat", "identity", "memory"}
TOOL_INTENTS = {"browser", "search"}

TOOL_CONFIDENCE_THRESHOLD = 0.85
SEARCH_CONFIDENCE_THRESHOLD = 0.85
BROWSER_CONFIDENCE_THRESHOLD = 0.85

CONVERSATIONAL_PATTERNS = [
    r"^(hi|hello|hey|yo|good morning|good afternoon|good evening)\b",
    r"\b(how are you|how r you|how are u|how is it going|how's it going|what's up|whats up)\b",
    r"\b(thank you|thanks|nice|cool|great|awesome|okay|ok)\b",
    r"\b(i am fine|i'm fine|i feel|are you okay|do you feel|you there)\b",
    r"\b(who are you|what are you|tell me about yourself)\b",
    r"\b(see you|bye|goodbye|talk later|see ya)\b",
]

EXPLICIT_SEARCH_PREFIXES = [
    "search google for ",
    "google search for ",
    "google search ",
    "search for ",
    "look up ",
    "google ",
    "search ",
]

LIVE_INFO_CUES = [
    "cricket result",
    "ipl score",
    "live score",
    "match stats",
    "match result",
    "latest news",
    "current news",
    "weather today",
    "today's weather",
    "stock price",
    "share price",
    "crypto price",
    "current price",
]

ACTIONABLE_EXECUTION_CUES = [
    "open",
    "search",
    "shop",
    "show me",
    "find",
    "go to",
    "navigate",
    "click",
    "type",
    "fill",
    "play",
    "run",
    "automate",
    "order",
]


@dataclass(frozen=True)
class ToolArmingDecision:
    armed: bool
    reason: str
    confidence: float
    threshold: float
    tool: Optional[str] = None

    def as_dict(self) -> Dict:
        return {
            "armed": self.armed,
            "reason": self.reason,
            "confidence": self.confidence,
            "threshold": self.threshold,
            "tool": self.tool,
        }


def is_conversational_utterance(user_input: str) -> bool:
    query = (user_input or "").lower().strip()
    return any(re.search(pattern, query) for pattern in CONVERSATIONAL_PATTERNS)


def looks_like_information_question(user_input: str) -> bool:
    """
    Returns True if the query looks like a general knowledge or information request,
    rather than an explicit browser control command.
    """
    query = (user_input or "").lower().strip()
    
    # If it contains explicit task tracking verbs/words, it is NOT an informational question
    task_keywords = ["track", "remind", "remember", "plan", "todo", "goal", "schedule", "automate", "buy", "order"]
    if any(kw in query for kw in task_keywords):
        return False
        
    # If it has explicit search prefixes (like "search google for"), it is a tool request
    for prefix in EXPLICIT_SEARCH_PREFIXES:
        if query.startswith(prefix):
            return False
            
    # If it contains a live info cue, it is a tool request (live web search)
    if has_live_info_cue(user_input):
        return False

    # Standard question words/phrases indicating information requests
    info_patterns = [
        r"\b(what|who|when|where|why|how|which)\b",
        r"\b(do you know|tell me|explain|describe|info|information)\b",
        r"\b(is it|does it|are there|is there|should i)\b",
        r"\b(can you tell|can u tell|do u know)\b"
    ]
    if any(re.search(pat, query) for pat in info_patterns):
        return True
        
    # Also, if it has no action/browser verbs like "open", "click", "go to", "search google"
    # and is just a multi-word noun phrase like "IPL cricket match" or "Virat Kohli"
    action_verbs = ["open", "click", "go to", "navigate", "search", "google", "look up"]
    if len(query.split()) > 1 and not any(verb in query for verb in action_verbs):
        return True
        
    return False


def extract_explicit_search_query(user_input: str) -> Optional[str]:
    query_lower = (user_input or "").lower().strip()
    for prefix in EXPLICIT_SEARCH_PREFIXES:
        if query_lower.startswith(prefix):
            query = user_input[len(prefix):].strip()
            return query or None
    return None


def has_live_info_cue(user_input: str) -> bool:
    query_lower = (user_input or "").lower().strip()
    return any(cue in query_lower for cue in LIVE_INFO_CUES)


def is_actionable_execution_request(user_input: str) -> bool:
    """Detects immediate action requests so they do not get stored as goals."""
    query_lower = (user_input or "").lower().strip()
    if any(cue in query_lower for cue in ACTIONABLE_EXECUTION_CUES):
        return True
    shopping_or_site_cues = ["amazon", "youtube", "google", "browser", "website", "keyboard", "keyboards"]
    if any(site in query_lower for site in shopping_or_site_cues):
        return True
    if "buy" in query_lower and any(cue in query_lower for cue in ["can you", "open", "search", "shop", "amazon"]):
        return True
    return False


def is_site_action_request(user_input: str) -> bool:
    """Detect explicit site-scoped actions before generic follow-up resolution."""
    query_lower = (user_input or "").lower().strip()
    site_terms = ["amazon", "youtube", "google", "flipkart"]
    action_terms = ["search", "open", "find", "buy", "shop", "look for", "show me"]
    correction_terms = ["not normal search", "not google", "inside", "in ", "on "]
    return (
        any(site in query_lower for site in site_terms)
        and any(action in query_lower for action in action_terms + correction_terms)
    )


def tool_threshold(intent: str) -> float:
    if intent == "search":
        return SEARCH_CONFIDENCE_THRESHOLD
    if intent == "browser":
        return BROWSER_CONFIDENCE_THRESHOLD
    return TOOL_CONFIDENCE_THRESHOLD


def evaluate_tool_arming(
    intent: str,
    confidence: float,
    user_input: str,
    *,
    has_valid_context: bool = False,
    explicit_tool_signal: bool = False,
) -> ToolArmingDecision:
    """Authorizes or blocks tool execution with deterministic policy."""
    if intent in CONVERSATIONAL_INTENTS or is_conversational_utterance(user_input):
        return ToolArmingDecision(False, "conversation_guard", confidence, tool_threshold(intent))

    if intent == "repair":
        return ToolArmingDecision(False, "repair_is_control_flow", confidence, tool_threshold(intent))

    if intent == "followup" and not has_valid_context:
        return ToolArmingDecision(False, "followup_without_valid_context", confidence, tool_threshold(intent))

    if intent not in TOOL_INTENTS:
        return ToolArmingDecision(False, "not_a_tool_intent", confidence, tool_threshold(intent))

    threshold = tool_threshold(intent)
    if intent in TOOL_INTENTS and looks_like_information_question(user_input):
        return ToolArmingDecision(False, "informational_query", confidence, threshold, intent)

    if confidence < threshold:
        return ToolArmingDecision(False, "low_tool_confidence", confidence, threshold, intent)

    if intent == "search" and not (explicit_tool_signal or extract_explicit_search_query(user_input) or has_live_info_cue(user_input)):
        return ToolArmingDecision(False, "missing_explicit_search_signal", confidence, threshold, intent)

    if intent == "browser" and not (explicit_tool_signal or has_valid_context):
        return ToolArmingDecision(False, "missing_browser_context_or_signal", confidence, threshold, intent)

    return ToolArmingDecision(True, "explicit_high_confidence_tool_intent", confidence, threshold, intent)
