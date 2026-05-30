"""
skills/context_budget.py — Context Budget Manager for ARIA
==========================================================
Prioritizes and trims memory context before injecting it into the system prompt.
Considers recency, emotional importance, unresolved goals, repeated references,
and semantic similarity rather than just raw cosine similarity.
"""

import time
from typing import List, Dict, Any, Optional

class ContextBudgetManager:
    """
    Manages the budget of injected memories into the LLM context prompt.
    Enforces limits on tokens/characters while sorting memories by multidimensional relevance.
    """

    def __init__(self, max_characters: int = 1500):
        self.max_characters = max_characters
        # Track repeated memory hits for frequency scoring
        self.memory_access_counts: Dict[str, int] = {}

    def score_and_select_memories(
        self,
        episodes: List[Dict[str, Any]],
        semantic_memories: List[Dict[str, Any]],
        current_goal: Optional[str] = None,
        max_chars: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Scores both episodic and semantic memories based on:
        - Recency
        - Emotional Importance (importance * 0.6 + emotional_weight * 0.4)
        - Unresolved goals relationship
        - Repeated references / frequency of access
        - Similarity score
        
        Trims the list to fit within max_chars.
        """
        limit = max_chars or self.max_characters
        candidates = []
        now = time.time()

        # Combine episodes and semantic memories into unified candidates
        # Format of unified candidate:
        # {
        #   "id": str,
        #   "text": str,
        #   "source": str, # "episodic" or "semantic"
        #   "timestamp": float,
        #   "importance": float,
        #   "emotional_weight": float,
        #   "similarity": float,
        #   "metadata": dict
        # }

        for ep in episodes:
            eid = ep.get("id") or str(ep.get("timestamp", now))
            self.memory_access_counts[eid] = self.memory_access_counts.get(eid, 0) + 1
            candidates.append({
                "id": eid,
                "text": ep.get("event_text", ""),
                "source": "episodic",
                "timestamp": ep.get("timestamp", now),
                "importance": ep.get("importance", 0.5),
                "emotional_weight": ep.get("emotional_weight", 0.3),
                "similarity": ep.get("similarity", 0.7),
                "metadata": ep
            })

        for sem in semantic_memories:
            # Semantic memories format from VectorMemory: (sim, text, cat)
            # Or if it's a dict: {"text": text, "similarity": sim, "category": cat}
            text = sem.get("text", "") if isinstance(sem, dict) else (sem[1] if isinstance(sem, tuple) and len(sem) > 1 else "")
            sim = sem.get("similarity", 0.6) if isinstance(sem, dict) else (sem[0] if isinstance(sem, tuple) else 0.6)
            cat = sem.get("category", "") if isinstance(sem, dict) else (sem[2] if isinstance(sem, tuple) and len(sem) > 2 else "")
            
            sid = f"sem_{hash(text)}"
            self.memory_access_counts[sid] = self.memory_access_counts.get(sid, 0) + 1
            candidates.append({
                "id": sid,
                "text": text,
                "source": "semantic",
                "timestamp": now - 3600 * 24,  # Assume 1 day ago if unknown
                "importance": 0.6 if "pref" in cat.lower() else 0.4,
                "emotional_weight": 0.2,
                "similarity": sim,
                "metadata": {"category": cat}
            })

        scored_candidates = []
        for cand in candidates:
            # 1. Recency score (1.0 for now, decays over 7 days)
            age_seconds = max(0.0, now - cand["timestamp"])
            age_days = age_seconds / (3600 * 24)
            recency_score = max(0.0, 1.0 - (age_days / 7.0))

            # 2. Emotional Importance score
            emotional_imp = (cand["importance"] * 0.6) + (cand["emotional_weight"] * 0.4)

            # 3. Unresolved Goal relationship score
            goal_relation = 0.0
            if current_goal:
                goal_words = set(current_goal.lower().split())
                cand_words = set(cand["text"].lower().split())
                overlap = len(goal_words & cand_words)
                if overlap > 0:
                    goal_relation = min(1.0, overlap / len(goal_words))

            # 4. Repeated references / frequency score
            freq_count = self.memory_access_counts.get(cand["id"], 1)
            freq_score = min(1.0, freq_count / 10.0)

            # 5. Composite score calculation
            # Weights: Recency (0.3), Emotional Importance (0.25), Goal Relation (0.25), Similarity (0.15), Frequency (0.05)
            comp_score = (
                (recency_score * 0.30) +
                (emotional_imp * 0.25) +
                (goal_relation * 0.25) +
                (cand["similarity"] * 0.15) +
                (freq_score * 0.05)
            )

            scored_candidates.append((comp_score, cand))

        # Sort by composite score descending
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        # Select candidates within the character budget limit
        selected = []
        current_chars = 0
        for score, cand in scored_candidates:
            cand_len = len(cand["text"])
            if current_chars + cand_len + 5 > limit:
                continue
            selected.append(cand)
            current_chars += cand_len + 5

        return selected

    def build_prompt_context(self, selected_memories: List[Dict[str, Any]]) -> str:
        """Constructs a clean system prompt string from selected memories."""
        if not selected_memories:
            return ""

        lines = ["== COGNITIVE CONTEXT MEMORY HIT(S) =="]
        for m in selected_memories:
            source_lbl = f"[{m['source'].upper()}]"
            lines.append(f"- {source_lbl} {m['text']}")
        return "\n".join(lines)
