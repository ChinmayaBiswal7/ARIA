"""
query_normalizer.py — Query Normalization Engine
=================================================

Fixes weak STT output and normalizes queries for intent classification.
Handles grammar errors, missing punctuation, common STT artifacts.
"""

import re
from typing import Tuple


class QueryNormalizer:
    """
    Normalizes user input before intent classification.
    
    Fixes:
    - Grammatical errors ("who i am" → "who am i")
    - Missing punctuation
    - Common STT artifacts
    - Capitalization inconsistencies
    - Extra whitespace
    """

    # Grammar correction patterns: (incorrect_pattern, correct_replacement)
    # NOTE: Order matters! More specific patterns should come first.
    GRAMMAR_FIXES = [
        # Identity patterns (most specific, handle first)
        (r"\bwho\s+i\s+am\b", "who am i"),
        (r"\bwho\s+is\s+i\b", "who am i"),
        (r"\bwho\s+is\s+this\b", "who is this"),  # Keep as "who is this", don't change to "who am i"
        (r"\bwho\s+are\s+you\b", "who are you"),
        
        # Do you know me patterns
        (r"\bdo\s+you\s+know\s+me\b", "do you know me"),
        (r"\bdo\s+u\s+know\s+me\b", "do you know me"),
        
        # Can you identify/recognize patterns
        (r"\bcan\s+you\s+identify\s+me\b", "identify me"),
        (r"\bcan\s+u\s+identify\s+me\b", "identify me"),
        (r"\bcan\s+you\s+recognize\s+me\b", "recognize me"),
        (r"\bcan\s+u\s+recognize\s+me\b", "recognize me"),
        
        # What is my name patterns
        (r"\bwhat\s+is\s+my\s+name\b", "what is my name"),
        (r"\bwhat's?\s+my\s+name\b", "what is my name"),
        
        # Identify me
        (r"\bidentify\s+me\b", "identify me"),
        
        # Recognize me
        (r"\brecognize\s+me\b", "recognize me"),

        # Summarize patterns
        (r"\bsummarize\s+it\b", "summarize it"),
        (r"\bsummarize\s+the\s+result\b", "summarize the result"),
        (r"\bsummary\b", "summarize"),
        (r"\bsummarise\b", "summarize"),

        # Open patterns
        (r"\bopen\s+it\b", "open it"),
        (r"\bopen\s+that\b", "open that"),
        (r"\bopen\s+the\s+page\b", "open the page"),

        # Search patterns
        (r"\bsearch\s+for\s+it\b", "search for it"),
        (r"\bsearch\s+that\b", "search that"),

        # Read patterns
        (r"\bread\s+it\b", "read it"),
        (r"\bread\s+the\s+page\b", "read the page"),
        (r"\bread\s+what\b", "read what"),

        # Tell me about patterns
        (r"\btell\s+me\s+about\s+it\b", "tell me about it"),
        (r"\btell\s+me\s+about\s+that\b", "tell me about that"),

        # Explain patterns
        (r"\bexplain\s+it\b", "explain it"),
        (r"\bexplain\s+that\b", "explain that"),

        # Typo/STT corrections
        (r"\bdisble\b", "disable"),
        (r"\bdiable\b", "disable"),
        (r"\bdeactivte\b", "deactivate"),
        (r"\bgestre\b", "gesture"),
        (r"\bgestur\b", "gesture"),
        (r"\bcontorls\b", "controls"),
        (r"\bcontrls\b", "controls"),
        (r"\bwrkng\b", "working"),
        (r"\bremng\b", "remaining"),
        (r"\boyher\b", "other"),
        (r"\bavce\b", "active"),

        # Generic cleanups (apply last, less risky)
        (r"\bi\s+am\s+looking\s+for\b", "search for"),
    ]

    # Common STT artifacts to remove
    STT_ARTIFACTS = [
        r"\buh\s+",
        r"\bumm?\s+",
        r"\berm\s+",
        r"\berrr\s+",
        r"\blike\s+",  # Often inserted by STT
    ]

    # Accent normalization (common misrecognitions)
    # NOTE: Removed "who is" -> "who am i" because it breaks "who is this"
    # The grammar fixes already handle these cases properly
    ACCENT_FIXES = [
        (r"\bwho\s+i\s+is\b", "who am i"),  # Only fix double "is" case
    ]

    # Shorthand expansions
    SHORTHAND_EXPANSIONS = [
        (r"\bu\b", "you"),
        (r"\br\b", "are"),
        (r"\bwt\b", "what"),
        (r"\bpls\b", "please"),
        (r"\bthx\b", "thanks"),
        (r"\basap\b", "as soon as possible"),
    ]

    def __init__(self):
        # Compile all patterns for speed
        self.grammar_patterns = [(re.compile(p, re.IGNORECASE), r) for p, r in self.GRAMMAR_FIXES]
        self.artifact_patterns = [re.compile(p, re.IGNORECASE) for p in self.STT_ARTIFACTS]
        self.accent_patterns = [(re.compile(p, re.IGNORECASE), r) for p, r in self.ACCENT_FIXES]
        self.shorthand_patterns = [(re.compile(p, re.IGNORECASE), r) for p, r in self.SHORTHAND_EXPANSIONS]

    def normalize(self, user_input: str) -> Tuple[str, str]:
        """
        Normalize input and return (normalized_query, changes_log).
        
        Returns:
            Tuple of (normalized_string, log_of_changes)
        """
        if not user_input or not isinstance(user_input, str):
            return "", "Empty input"

        original = user_input
        query = user_input.strip()
        changes = []

        # Step 1: Remove leading/trailing whitespace and extra spaces
        query = re.sub(r"\s+", " ", query).strip()
        if query != original:
            changes.append("Removed extra whitespace")

        # Step 2: Remove STT artifacts
        for pattern in self.artifact_patterns:
            if pattern.search(query):
                query = pattern.sub("", query)
                changes.append("Removed STT artifacts")
                break

        # Step 3: Expand shorthand
        for pattern, replacement in self.shorthand_patterns:
            if pattern.search(query):
                query = pattern.sub(replacement, query)
                changes.append(f"Expanded shorthand")

        # Step 4: Fix accents/misrecognitions
        for pattern, replacement in self.accent_patterns:
            if pattern.search(query):
                query = pattern.sub(replacement, query)
                changes.append(f"Fixed accent/misrecognition")

        # Step 5: Apply grammar fixes
        for pattern, replacement in self.grammar_patterns:
            before = query
            query = pattern.sub(replacement, query)
            if before != query:
                changes.append(f"Grammar: '{before.strip()}' -> '{query.strip()}'")

        # Step 6: Ensure proper capitalization for sentence start
        if query and not query[0].isupper():
            query = query[0].upper() + query[1:]
            changes.append("Capitalized first letter")

        # Step 7: Add terminal punctuation if missing and it looks like a question
        if query and query[-1] not in "?.!":
            if any(q in query.lower() for q in ["who", "what", "when", "where", "why", "how", "do you", "can you", "is"]):
                query = query + "?"
                changes.append("Added question mark")
            # For commands, add period
            elif any(c in query.lower() for c in ["open", "search", "read", "summarize", "click"]):
                query = query + "."
                changes.append("Added period")

        # Final cleanup
        query = query.strip()

        log = " -> ".join(changes) if changes else "No changes"
        return query, log

    def get_confidence_in_normalization(self, original: str, normalized: str) -> float:
        """
        Return confidence (0.0-1.0) that the normalization is correct.
        Lower confidence if major changes were made.
        """
        if original == normalized:
            return 1.0

        # Minor changes (punctuation, whitespace) = high confidence
        if original.lower() == normalized.lower():
            return 0.95

        # Moderate changes (grammar fixes) = medium confidence
        if len(original.split()) == len(normalized.split()):
            return 0.85

        # Major changes = lower confidence
        return 0.7


# ─────────────────────────────────────────────────────────────────────────────
# Test
if __name__ == "__main__":
    normalizer = QueryNormalizer()

    print("=" * 70)
    print("QUERY NORMALIZATION TEST")
    print("=" * 70)

    test_queries = [
        "who i am",
        "who is this",
        "whos my name",
        "what is my name",
        "do u know me",
        "can you identify me",
        "recognize me",
        "summarize the result",
        "open it",
        "umm can u search for python",
        "errr like search that",
        "tell me about it",
        "read the page",
        "what's on my screen",
        "hello how are you",
    ]

    for query in test_queries:
        normalized, log = normalizer.normalize(query)
        confidence = normalizer.get_confidence_in_normalization(query, normalized)
        print(f"\nOriginal:   '{query}'")
        print(f"Normalized: '{normalized}'")
        print(f"Log: {log}")
        print(f"Confidence: {confidence:.2f}")
