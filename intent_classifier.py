"""
intent_classifier.py — Advanced Intent Classification Engine
=============================================================

Classifies user input into specific intents with priority ordering.
Handles identity queries, conversational context, and web searches properly.
"""

import re
import numpy as np
from typing import Dict, Tuple, Optional
from skills.routing_policy import CONVERSATIONAL_PATTERNS, has_live_info_cue, is_site_action_request


class IntentClassifier:
    """
    Multi-tier intent classifier that recognizes:
    - Identity/Memory intents (who am i, what is my name, do you know me)
    - Summarization intents (summarize this, what did you get)
    - Follow-up intents (it, that, there, yes, no, etc)
    - Search intents (actual web searches)
    - Chat intents (general conversation)
    """
    # Tier 0: CONVERSATIONAL REPAIRS (highest priority)
    REPAIR_PATTERNS = [
        r'\b(no wait|hold on|wait a second|wait a minute|no wait|i mean|actually|no i meant|no no i meant|actually i meant|stop stop|wait wait|no no|cancel that|stop this|nevermind that)\b',
        r'^(no|wait|actually|meant|stop)\b',
    ]

    # Tier 0.5: CONVERSATIONAL / SMALLTALK GUARD
    CONVERSATIONAL_PATTERNS = CONVERSATIONAL_PATTERNS

    # Tier 1: IDENTITY INTENTS (highest priority)
    IDENTITY_PATTERNS = [
        r'\b(who am i|who is this|who\'s there|who are you talking to|do you know me|can you recognize me|recognize me)\b',
        r'\b(what is my name|what\'s my name|my name)\b',
        r'\b(who am i\?|who is in front of you|who do you see|who do you see in front)\b',
        r'\b(am i|identify me|who\'s speaking|who is speaking)\b',
        r'\b(face recognition|identify|identify me|recognize|who\?)\b',
    ]

    # Tier 2: MEMORY/CONTEXT INTENTS
    MEMORY_PATTERNS = [
        r'\b(remember when|do you remember|what did i tell you|recall|what do you know about me|what have i said)\b',
        r'\b(my history|my past|what have i done|my activities|what i\'ve done)\b',
    ]

    # Tier 3: FOLLOW-UP INTENTS (reference resolution)
    FOLLOWUP_PATTERNS = [
        r'\b(summarize (it|that|the result|this|what you got)|summarize)\b',
        r'\b(open (it|that|the (first |second |third |last )?result|link|this))\b',
        r'\b(click (it|that|there))\b',
        r'\b(read (it|that|this)|read the result|read what you got)\b',
        r'\b(search (it|that|this)|search for (it|that|this))\b',
        r'\b(tell me about (it|that|this)|explain (it|that|this))\b',
        r'\b(show (it|that|me))\b',
        r'\b(yes|no|confirm|correct|wrong|not that)\b',
        r'\b(that one|the first one|the second one|the third one|the last one|the other one|not this|not that)\b',
        r'\b(go back there|go back to the previous step|go back)\b',
        r'\b(open it|open that|click that one|select the second one)\b',
    ]

    # Tier 4: SEARCH INTENTS (explicit web search)
    SEARCH_PATTERNS = [
        r'\b(google|search|find|look up|lookup)\b',
        r'\b(latest|news|current|score|weather|stock|price|cricket|match)\b',
    ]

    # Tier 5: BROWSER CONTEXT INTENTS
    BROWSER_PATTERNS = [
        r'\b(what\'s on|what is on|read the page|what\'s on the page|page content|web page|website)\b',
        r'\b(tab|browser|current page|active page)\b',
    ]

    # Tier 6: CAREER INTENTS
    CAREER_PATTERNS = [
        r'\b(career|job list|bookmark job|codeforces stats|analyze match|resume match|github stats)\b',
    ]

    # ML Prototype Phrases for Sentence Similarity
    PROTOTYPE_PHRASES = {
        "repair": [
            "no wait", "hold on", "wait a second", "wait a minute", "i mean", "actually",
            "no i meant", "stop stop", "wait wait", "cancel that", "stop this", "nevermind that",
            "cancel the action", "please stop", "hold on a moment"
        ],
        "identity": [
            "who am i", "who is this", "who are you talking to", "do you know me", "can you recognize me",
            "what is my name", "what's my name", "who is in front of you", "who do you see", "who do you see in front",
            "am i", "identify me", "who is speaking", "who is speaking now", "do you remember my name",
            "check my identity", "tell me who I am", "do you see me"
        ],
        "memory": [
            "remember when", "do you remember", "what did i tell you", "recall", "what do you know about me",
            "what have i said", "my history", "my past", "what have i done", "my activities", "what i've done",
            "what did we talk about", "remember", "look up my preferences", "what is stored in my memory"
        ],
        "followup": [
            "summarize it", "summarize that", "summarize the result", "open it", "open that", "click it",
            "click that", "click there", "read it", "read that", "read the result", "search it", "search that",
            "tell me about it", "explain it", "show it", "yes", "no", "confirm", "correct", "wrong",
            "that one", "the first one", "the second one", "the last one", "go back", "go back there",
            "click the link", "open the first result", "click the first option"
        ],
        "search": [
            "google", "search for", "find out", "look up", "news today", "latest score", "weather forecast",
            "cricket match", "current price", "search the web", "search online", "what is the latest news",
            "find information about", "look up online"
        ],
        "browser": [
            "what's on the screen", "read the page", "what is on the page", "web page content", "website text",
            "active tab", "browser tab", "read current website", "view the current webpage", "what is in the browser"
        ],
        "career": [
            "show my career list", "bookmark job", "analyze match for", "resume matching",
            "get codeforces stats", "my job applications", "add job to list"
        ],
    }

    def __init__(self):
        self.compiled_patterns = {
            "repair": [re.compile(p, re.IGNORECASE) for p in self.REPAIR_PATTERNS],
            "conversation": [re.compile(p, re.IGNORECASE) for p in self.CONVERSATIONAL_PATTERNS],
            "identity": [re.compile(p, re.IGNORECASE) for p in self.IDENTITY_PATTERNS],
            "memory": [re.compile(p, re.IGNORECASE) for p in self.MEMORY_PATTERNS],
            "followup": [re.compile(p, re.IGNORECASE) for p in self.FOLLOWUP_PATTERNS],
            "search": [re.compile(p, re.IGNORECASE) for p in self.SEARCH_PATTERNS],
            "browser": [re.compile(p, re.IGNORECASE) for p in self.BROWSER_PATTERNS],
            "career": [re.compile(p, re.IGNORECASE) for p in self.CAREER_PATTERNS],
        }

        # Initialize ML model from ChromaDB's DefaultEmbeddingFunction
        self.use_ml = False
        try:
            import chromadb.utils.embedding_functions as ef
            self.embedding_function = ef.DefaultEmbeddingFunction()
            
            # Pre-compute prototype embeddings
            self.prototype_embeddings = {}
            for intent, phrases in self.PROTOTYPE_PHRASES.items():
                embs = self.embedding_function(phrases)
                self.prototype_embeddings[intent] = [np.array(e) for e in embs]
            
            self.use_ml = True
            print("[IntentClassifier] ML-based similarity classifier initialized successfully.")
        except Exception as e:
            print(f"[IntentClassifier] Failed to initialize ML similarity classifier (using regex fallback): {e}")

    def classify(self, user_input: str, skip_repair: bool = False) -> Tuple[str, float]:
        """
        Classify input into intent category.
        Returns: (intent_type, confidence_score)
        """
        if not user_input or not isinstance(user_input, str):
            return "chat", 0.0

        query = user_input.strip().lower()

        # Step 1: conversational guard (fast check for smalltalk/greetings)
        for pattern in self.compiled_patterns["conversation"]:
            if pattern.search(query):
                print(f"[IntentClassifier/Guard] '{user_input[:50]}' -> chat (confidence: 0.95, conversational guard)")
                return "chat", 0.95

        # Step 1.5: conversational repair guard
        if not skip_repair:
            for pattern in self.compiled_patterns["repair"]:
                match = pattern.search(query)
                if match:
                    matched_text = match.group(0)
                    confidence = 0.98 if len(matched_text.split()) > 1 or matched_text in ["actually", "meant"] else 0.85
                    print(f"[IntentClassifier/Guard] '{user_input[:50]}' -> repair (confidence: {confidence:.2f}, repair guard)")
                    return "repair", confidence

        # Step 2: explicit site action request guard
        if is_site_action_request(user_input):
            print(f"[IntentClassifier/Guard] '{user_input[:50]}' -> search (confidence: 0.92, explicit site action)")
            return "search", 0.92

        # Whitelist obvious job/career search intents to bypass low confidence and clarification
        job_keywords = ["internship", "job", "career", "placement", "opening", "vacancy"]
        if any(kw in query for kw in job_keywords):
            # Verify it's not a conversational/identity/memory query first
            is_conversational = any(pattern.search(query) for pattern in self.compiled_patterns["conversation"])
            is_identity = any(pattern.search(query) for pattern in self.compiled_patterns["identity"])
            is_memory = any(pattern.search(query) for pattern in self.compiled_patterns["memory"])
            
            if not (is_conversational or is_identity or is_memory):
                print(f"[IntentClassifier/Whitelist] '{user_input[:50]}' contains job/career keyword -> search (confidence: 0.95)")
                return "search", 0.95

        # Step 3: ML Similarity Classification (if available)
        if self.use_ml:
            try:
                query_emb = np.array(self.embedding_function([query])[0])
                
                best_intent = None
                max_similarity = -1.0
                
                for intent, emb_list in self.prototype_embeddings.items():
                    if skip_repair and intent == "repair":
                        continue
                    for emb in emb_list:
                        # Cosine similarity
                        sim = np.dot(query_emb, emb) / (np.linalg.norm(query_emb) * np.linalg.norm(emb) + 1e-9)
                        if sim > max_similarity:
                            max_similarity = sim
                            best_intent = intent
                
                if max_similarity >= 0.45:
                    confidence = min(0.99, float(max_similarity * 1.1))
                    print(f"[IntentClassifier/ML] '{user_input[:50]}' -> {best_intent} (similarity: {max_similarity:.3f}, confidence: {confidence:.2f})")
                    return best_intent, confidence
                    
                print(f"[IntentClassifier/ML] Best match ({best_intent}: {max_similarity:.3f}) below threshold. Falling back to regex.")
            except Exception as e:
                print(f"[IntentClassifier/ML] Classification failed: {e}. Falling back to regex.")

        # Step 4: Regex-based fallback
        for intent_type in ["repair", "identity", "memory", "followup", "browser", "search", "career"]:
            if skip_repair and intent_type == "repair":
                continue
            patterns = self.compiled_patterns[intent_type]
            for pattern in patterns:
                match = pattern.search(query)
                if match:
                    matched_text = match.group(0)
                    if intent_type == "repair":
                        confidence = 0.98 if len(matched_text.split()) > 1 or matched_text in ["actually", "meant"] else 0.85
                    elif intent_type == "identity":
                        if query in ["who am i", "what is my name", "do you know me", "recognize me"]:
                            confidence = 0.99
                        elif len(query.split()) > 2:
                            confidence = 0.92
                        else:
                            confidence = 0.70
                    elif intent_type == "memory":
                        confidence = 0.90 if len(query.split()) > 2 else 0.75
                    elif intent_type == "followup":
                        if any(w in query for w in ["second", "first", "last", "that one", "go back"]):
                            confidence = 0.88
                        elif query in ["yes", "no", "correct"]:
                            confidence = 0.65
                        else:
                            confidence = 0.80
                    elif intent_type == "browser":
                        confidence = 0.85 if "page" in query or "browser" in query else 0.75
                    elif intent_type == "search":
                        if any(w in query for w in ["google", "search for", "find out"]) or has_live_info_cue(query):
                            confidence = 0.90
                        else:
                            confidence = 0.75
                    elif intent_type == "career":
                        confidence = 0.95
                    else:
                        confidence = 0.80

                    print(f"[IntentClassifier/Regex] '{user_input[:50]}' -> {intent_type} (confidence: {confidence:.2f})")
                    return intent_type, confidence

        # Default to chat
        return "chat", 0.30

    def get_intent_metadata(self, intent_type: str) -> Dict:
        """Return metadata about the intent for routing decisions."""
        metadata = {
            "repair": {
                "needs_context": True,
                "no_web_search": True,
                "priority": 0,
            },
            "identity": {
                "needs_face_recognition": True,
                "needs_memory": True,
                "no_web_search": True,
                "priority": 1,
            },
            "memory": {
                "needs_memory": True,
                "no_web_search": True,
                "priority": 2,
            },
            "followup": {
                "needs_context": True,
                "needs_reference_resolution": True,
                "priority": 3,
            },
            "browser": {
                "needs_active_context": True,
                "check_browser_first": True,
                "priority": 4,
            },
            "search": {
                "allow_web_search": True,
                "priority": 5,
            },
            "chat": {
                "general_chat": True,
                "no_web_search": True,
                "priority": 6,
            },
            "career": {
                "needs_memory": True,
                "no_web_search": True,
                "priority": 7,
            },
        }
        return metadata.get(intent_type, {})


# ─────────────────────────────────────────────────────────────────────────────
# Simple test
if __name__ == "__main__":
    classifier = IntentClassifier()

    test_queries = [
        "Who am I?",
        "who i am",  # Grammatically weak STT output
        "What is my name?",
        "Do you know me?",
        "Summarize the result",
        "Open it",
        "Click that",
        "Search for Python tutorials",
        "What's the weather today?",
        "Hello, how are you?",
        "Remember when I asked you about Python?",
        "Read the page",
        "Tell me about that",
    ]

    print("=" * 60)
    print("INTENT CLASSIFICATION TEST")
    print("=" * 60)

    for query in test_queries:
        intent, confidence = classifier.classify(query)
        metadata = classifier.get_intent_metadata(intent)
        print(f"\nQuery: '{query}'")
        print(f"  → Intent: {intent} (confidence: {confidence:.2f})")
        print(f"  → Metadata: {metadata}")
