"""
skills/proactive_cognition.py — ARIA Proactive Cognition Safeguards
==================================================================
Manages background reasoning triggers, low battery, stretch breaks,
and dynamically adjusts proactive speaking cooldowns using an engagement backoff multiplier.
"""

import time
import datetime
from typing import Dict, Any, Optional

class ProactiveCognition:
    def __init__(self, cooldown_minutes: int = 15):
        self.cooldown_seconds = cooldown_minutes * 60.0
        self.last_proactive_speak_time = 0.0
        self.last_suggestion_text = ""
        self.cooldown_multiplier = 1.0

    def is_on_cooldown(self, is_emotional: bool = False) -> bool:
        """Returns True if the cooldown period (adjusted by multiplier) is active."""
        actual_cooldown = self.cooldown_seconds * self.cooldown_multiplier
        if is_emotional:
            # Emotional suggestion cooldown: max 3 minutes (180s) to react to emotional needs promptly
            actual_cooldown = min(180.0, actual_cooldown)
        return (time.time() - self.last_proactive_speak_time) < actual_cooldown

    def get_cooldown_remaining(self, is_emotional: bool = False) -> float:
        """Returns remaining cooldown seconds (0 if not on cooldown)."""
        actual_cooldown = self.cooldown_seconds * self.cooldown_multiplier
        if is_emotional:
            actual_cooldown = min(180.0, actual_cooldown)
        remaining = actual_cooldown - (time.time() - self.last_proactive_speak_time)
        return max(0.0, remaining)

    def trigger_proactive_speak(self):
        """Resets the last proactive speech timestamp."""
        self.last_proactive_speak_time = time.time()

    def get_cooldown_status(self) -> Dict[str, Any]:
        """Returns cooldown status dict for dashboard telemetry."""
        on_cd = self.is_on_cooldown()
        remaining = self.get_cooldown_remaining()
        return {
            "on_cooldown": on_cd,
            "remaining_seconds": round(remaining, 1),
            "remaining_label": f"{int(remaining // 60)}m {int(remaining % 60)}s" if on_cd else "Ready",
            "last_suggestion": self.last_suggestion_text or "None",
            "cooldown_multiplier": self.cooldown_multiplier
        }

    def log_user_engagement(self, feedback: str):
        """
        Adjusts the cooldown multiplier based on user engagement feedback.
        Negative feedback (e.g. 'stop', 'be quiet') doubles the cooldown multiplier.
        Positive feedback (e.g. 'thanks', 'sure') resets it to 1.0.
        """
        from skills.command_patterns import FEEDBACK_NEGATIVE_WORDS, FEEDBACK_POSITIVE_WORDS
        f = feedback.lower().strip()

        old_mult = self.cooldown_multiplier
        if any(w in f for w in FEEDBACK_NEGATIVE_WORDS):
            # Double multiplier up to 16.0 (approx 4 hours for a 15-min base)
            self.cooldown_multiplier = min(16.0, self.cooldown_multiplier * 2.0)
            print(f"[ProactiveCognition] Negative feedback detected: '{feedback}'. Cooldown multiplier increased: {old_mult}x -> {self.cooldown_multiplier}x")
            
            # Log to audit log
            try:
                from skills.memory_manager import MemoryManager
                MemoryManager().log_cognition_audit(
                    "PROACTIVE_COOLDOWN_BACKOFF",
                    f"Increased proactive cooldown multiplier due to negative user feedback.",
                    {"feedback": feedback, "old_multiplier": old_mult, "new_multiplier": self.cooldown_multiplier}
                )
            except Exception:
                pass
        elif any(w in f for w in FEEDBACK_POSITIVE_WORDS):
            self.cooldown_multiplier = 1.0
            print(f"[ProactiveCognition] Positive feedback detected: '{feedback}'. Cooldown multiplier reset to 1.0x")
            try:
                from skills.memory_manager import MemoryManager
                MemoryManager().log_cognition_audit(
                    "PROACTIVE_COOLDOWN_RESET",
                    "Reset proactive cooldown multiplier to 1.0x due to positive user feedback.",
                    {"feedback": feedback}
                )
            except Exception:
                pass

    def generate_soft_suggestion(self, emotion: str, context: Dict[str, Any]) -> Optional[str]:
        """
        Formulates a soft suggestion rather than aggressive emotional analysis.
        Follows 'emotion uncertainty' rules.
        """
        is_emotional = emotion in ["sad", "stressed", "anxious", "frustrated", "tired", "angry"]
        if self.is_on_cooldown(is_emotional=is_emotional):
            return None

        username = context.get("username", "friend")
        now_hour = context.get("hour", 12)
        working_minutes = context.get("working_minutes", 0)

        # 1. Late Night working check
        if now_hour >= 23 or now_hour < 5:
            self.trigger_proactive_speak()
            suggestion = f"You seem to be working quite late, {username}? Don't forget to get some rest."
            self.last_suggestion_text = suggestion
            return suggestion

        # 2. Inferred emotion check (with soft phrasing)
        if emotion == "sad":
            self.trigger_proactive_speak()
            suggestion = f"You seem a bit down today, {username}? Is there anything I can help you with?"
            self.last_suggestion_text = suggestion
            return suggestion
        elif emotion in ["stressed", "anxious", "frustrated"]:
            self.trigger_proactive_speak()
            import random
            STRESS_RESPONSES = [
                f"You seem a bit stressed, {username}? Perhaps a short break would help clear your mind.",
                f"Everything alright, {username}? You've seemed a bit tense lately.",
                f"Hey {username}, noticed you seem stressed. I'm here if you need anything.",
                f"I've noticed you seem quite stressed lately, {username}. Is everything okay?",
                None,
                None,
                None,
            ]
            suggestion = random.choice(STRESS_RESPONSES)
            self.last_suggestion_text = suggestion or ""
            return suggestion
        elif emotion == "tired":
            self.trigger_proactive_speak()
            suggestion = f"You seem a bit tired? Maybe it's time to take a breather."
            self.last_suggestion_text = suggestion
            return suggestion
        elif emotion == "angry":
            self.trigger_proactive_speak()
            suggestion = f"You seem a bit upset, {username}? Let me know if you want to talk or if there is something I can handle for you."
            self.last_suggestion_text = suggestion
            return suggestion

        # 3. Continuous working break check
        if working_minutes >= 45:
            self.trigger_proactive_speak()
            suggestion = f"It looks like you've been working for {working_minutes} minutes. Should we stretch for a minute?"
            self.last_suggestion_text = suggestion
            return suggestion

        return None

    def generate_idle_memory_suggestion(self, aria_instance, username) -> Optional[str]:
        """
        Formulates a proactive follow-up question based on the user's recent tasks 
        retrieved from episodic memory when the user is idle.
        """
        try:
            # Query recent episodic memories (e.g. 15 events)
            recent_episodes = aria_instance.episodic_memory.get_recent(username=username, n=15)
            if not recent_episodes:
                return None

            import time
            lines = []
            for ep in reversed(recent_episodes):
                ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(ep.get("timestamp", 0.0)))
                lines.append(f"[{ts}] {ep.get('event_text', '')}")
            history_str = "\n".join(lines)

            system_instruction = (
                "You are ARIA, a proactive AI assistant. You notice the user is idle and want to check in "
                "on a recent task, project, or topic they were working on based on past episodes.\n"
                "Identify a recent topic (e.g. debugging, building, configuring, learning) and ask a "
                "natural, friendly question to follow up on it. Keep it under 20 words. Examples:\n"
                "- 'Did you manage to get that Firebase voice pipeline working?'\n"
                "- 'Were you able to resolve the issue with the face recognition loop?'\n"
                "If there is no clear technical task or project, or if the episodes are just greeting/idle talk, "
                "do NOT make anything up; return exactly the word: 'NONE'."
            )
            prompt = f"Recent episodic history:\n{history_str}\n\nAsk a follow-up question about the latest task or return 'NONE'."

            if aria_instance.brain:
                res = aria_instance.brain.think_raw(prompt, system_instruction=system_instruction)
                if res and res.strip() and res.strip().upper() != "NONE" and len(res.strip()) > 5:
                    return res.strip()
        except Exception as e:
            print(f"[ProactiveCognition] Error generating idle memory suggestion: {e}")
        return None

    def run_background_check(self, aria_instance) -> Optional[str]:
        """
        High-level method called by _run_background_scheduler on each iteration.
        Checks for silence preferences and confidence thresholds before suggesting.
        """
        try:
            # 0. Check Convergence Overrides (Silent mode / low receptiveness)
            try:
                from skills.intelligence_convergence_hub import AriaIntelligenceConvergenceHub
                overrides = AriaIntelligenceConvergenceHub().generate_convergence_overrides()
                if overrides.get("interaction_mode") == "SILENT":
                    print("[ProactiveCognition] Low receptiveness detected. Silent mode active. Suppressing suggestions.")
                    return None
            except Exception as e:
                print(f"[ProactiveCognition] Silent override check error: {e}")

            # 1. Check Guest Mode (silence proactively in guest mode)
            username = getattr(aria_instance, "known_user", None) or "friend"
            if username.lower() == "guest":
                return None

            # 2. Check silence_preferred preference
            try:
                from skills.memory_manager import MemoryManager
                prefs = MemoryManager().get_preferences(username)
                if prefs.get("silence_preferred") == "yes":
                    # User requested silence
                    return None
            except Exception:
                pass

            # Gather context
            now = datetime.datetime.now()
            hour = now.hour
            
            # Calculate working minutes since ARIA started
            start_time = getattr(aria_instance, "start_time", time.time())
            working_minutes = int((time.time() - start_time) / 60.0)

            # Check if user has been idle/inactive for at least 15 minutes (900s)
            # AND the user is present in front of the screen
            last_interaction = getattr(aria_instance, "last_interaction_time", 0.0)
            time_since_last_interaction = time.time() - last_interaction
            presence = getattr(aria_instance, "presence_state", "USER_LEFT")
            
            # If the user is present/engaged and has been idle for a while (e.g. > 15 minutes)
            if presence in ["USER_ENGAGED", "USER_PRESENT", "OWNER_ACTIVE"] and time_since_last_interaction > 900.0:
                if not self.is_on_cooldown(is_emotional=False):
                    idle_suggestion = self.generate_idle_memory_suggestion(aria_instance, username)
                    if idle_suggestion:
                        self.trigger_proactive_speak()
                        self.last_suggestion_text = idle_suggestion
                        return idle_suggestion

            # Get latest inferred emotion from episodic memory (if available)
            emotion = "neutral"
            emotion_confidence = 1.0
            try:
                episodic = getattr(aria_instance, "episodic_memory", None)
                if episodic:
                    recent = episodic.get_recent(username=username, n=1)
                    if recent and len(recent) > 0:
                        emotion = recent[0].get("emotion", "neutral")
                        emotion_confidence = recent[0].get("confidence", 1.0)
            except Exception:
                pass

            # Check cooldown, taking into account whether it's an emotional state
            is_emotional = emotion in ["sad", "stressed", "anxious", "frustrated", "tired", "angry"]
            if self.is_on_cooldown(is_emotional=is_emotional):
                return None

            # Proactive confidence threshold check:
            # If we inferred an emotion but our confidence is low (e.g. < 0.65), do not speak proactively.
            if emotion != "neutral" and emotion_confidence < 0.65:
                # Low confidence in the emotion inference, keep silent
                return None

            context = {
                "username": username,
                "hour": hour,
                "working_minutes": working_minutes
            }

            suggestion = self.generate_soft_suggestion(emotion, context)
            return suggestion

        except Exception as e:
            print(f"[ProactiveCognition] Background check error: {e}")
            return None
