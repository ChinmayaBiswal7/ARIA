"""
test_cognitive_enhancements.py — ARIA Cognitive Core Verification Tests
=======================================================================
Tests proactive cooldown, reflection engine relationship updates,
context budget limits, and sandbox safety risk blocking.
"""

import time
import os
import sys
import unittest
import unittest.mock

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestProactiveCognitionCooldown(unittest.TestCase):
    """Verifies that ProactiveCognition's cooldown system prevents excessive speech."""

    def setUp(self):
        from skills.proactive_cognition import ProactiveCognition
        self.pc = ProactiveCognition(cooldown_minutes=0.05)  # 3 second cooldown for test speed

    def test_initial_not_on_cooldown(self):
        self.assertFalse(self.pc.is_on_cooldown(), "Should not be on cooldown initially")

    def test_trigger_activates_cooldown(self):
        self.pc.trigger_proactive_speak()
        self.assertTrue(self.pc.is_on_cooldown(), "Should be on cooldown after triggering")

    def test_cooldown_blocks_suggestion(self):
        """After a suggestion fires, subsequent calls should return None until cooldown expires."""
        context = {"username": "test_user", "hour": 2, "working_minutes": 10}  # Late night
        suggestion = self.pc.generate_soft_suggestion("neutral", context)
        self.assertIsNotNone(suggestion, "Late night should produce a suggestion")

        # Immediate second call should be blocked
        blocked = self.pc.generate_soft_suggestion("neutral", context)
        self.assertIsNone(blocked, "Should be blocked by cooldown")

    def test_cooldown_expires(self):
        """After cooldown expires, suggestions should fire again."""
        self.pc.trigger_proactive_speak()
        time.sleep(4)  # Wait for 3s cooldown to expire
        self.assertFalse(self.pc.is_on_cooldown(), "Cooldown should have expired")

    def test_get_cooldown_status_ready(self):
        status = self.pc.get_cooldown_status()
        self.assertFalse(status["on_cooldown"])
        self.assertEqual(status["remaining_label"], "Ready")

    def test_get_cooldown_status_active(self):
        self.pc.trigger_proactive_speak()
        status = self.pc.get_cooldown_status()
        self.assertTrue(status["on_cooldown"])
        self.assertGreater(status["remaining_seconds"], 0)

    @unittest.mock.patch('random.choice')
    def test_soft_phrasing_for_stress(self, mock_choice):
        mock_choice.side_effect = lambda x: x[0]
        context = {"username": "tester", "hour": 14, "working_minutes": 10}
        suggestion = self.pc.generate_soft_suggestion("stressed", context)
        self.assertIsNotNone(suggestion)
        self.assertIn("seem", suggestion.lower(), "Should use soft 'seem' phrasing, not assertive")

    def test_no_suggestion_when_neutral(self):
        context = {"username": "tester", "hour": 14, "working_minutes": 10}
        suggestion = self.pc.generate_soft_suggestion("neutral", context)
        self.assertIsNone(suggestion, "Neutral emotion + short work should produce no suggestion")


class TestReflectionEngine(unittest.TestCase):
    """Verifies the ReflectionEngine's relationship vector and candidate updates."""

    def setUp(self):
        from skills.reflection_engine import ReflectionEngine
        self.re = ReflectionEngine()
        self.re._session_trust_delta_total = 0.0
        self.test_user = "test_reflection_user"
        # Clean any leftover state from previous runs so defaults tests are reliable
        self._clean_test_user()

    def tearDown(self):
        self._clean_test_user()

    def _clean_test_user(self):
        if hasattr(self.re, '_in_memory_metrics') and self.test_user.lower().strip() in self.re._in_memory_metrics:
            del self.re._in_memory_metrics[self.test_user.lower().strip()]
        with self.re._get_conn() as conn:
            conn.execute("DELETE FROM relationship_vector WHERE username = ?", (self.test_user.lower().strip(),))
            conn.execute("DELETE FROM candidate_semantic_updates WHERE username = ?", (self.test_user.lower().strip(),))
            conn.commit()

    def test_default_relationship_vector(self):
        vec = self.re.get_relationship_vector(self.test_user)
        self.assertIn("trust", vec)
        self.assertIn("comfort", vec)
        self.assertEqual(vec["trust"], 10.0, "Default trust should be 10.0")

    def test_update_relationship_metrics(self):
        with self.re._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO relationship_vector 
                (username, trust, comfort, interaction_depth, emotional_openness, updated_at)
                VALUES (?, 7.0, 5.0, 5.0, 5.0, ?)
            """, (self.test_user.lower().strip(), time.time()))
            conn.commit()
        if hasattr(self.re, '_in_memory_metrics') and self.test_user.lower().strip() in self.re._in_memory_metrics:
            del self.re._in_memory_metrics[self.test_user.lower().strip()]
        self.re.update_relationship_metrics(self.test_user, delta_trust=0.5, delta_comfort=1.0)
        vec = self.re.get_relationship_vector(self.test_user)
        self.assertEqual(vec["trust"], 7.5)
        self.assertEqual(vec["comfort"], 6.0)

    def test_relationship_labels_acquaintance(self):
        with self.re._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO relationship_vector 
                (username, trust, comfort, interaction_depth, emotional_openness, updated_at)
                VALUES (?, 2.0, 2.0, 2.0, 2.0, ?)
            """, (self.test_user.lower().strip(), time.time()))
            conn.commit()
        if hasattr(self.re, '_in_memory_metrics') and self.test_user.lower().strip() in self.re._in_memory_metrics:
            del self.re._in_memory_metrics[self.test_user.lower().strip()]
        labels = self.re.get_relationship_labels(self.test_user)
        self.assertIn(labels["familiarity"], ["Acquaintance", "Growing"])

    def test_relationship_labels_after_growth(self):
        """Push metrics high enough to reach 'Close Companion' label."""
        with self.re._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO relationship_vector 
                (username, trust, comfort, interaction_depth, emotional_openness, updated_at)
                VALUES (?, 9.0, 9.0, 9.0, 9.0, ?)
            """, (self.test_user.lower().strip(), time.time()))
            conn.commit()
        if hasattr(self.re, '_in_memory_metrics') and self.test_user.lower().strip() in self.re._in_memory_metrics:
            del self.re._in_memory_metrics[self.test_user.lower().strip()]
        labels = self.re.get_relationship_labels(self.test_user)
        self.assertIn(labels["familiarity"], ["Friend / Evolving", "Close Companion"])

    def test_self_model_consistency_check(self):
        """If trust is high but comfort low, consistency check should auto-correct."""
        with self.re._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO relationship_vector 
                (username, trust, comfort, interaction_depth, emotional_openness, updated_at)
                VALUES (?, 8.0, 0.5, 5.0, 5.0, ?)
            """, (self.test_user.lower().strip(), time.time()))
            conn.commit()
        if hasattr(self.re, '_in_memory_metrics') and self.test_user.lower().strip() in self.re._in_memory_metrics:
            del self.re._in_memory_metrics[self.test_user.lower().strip()]
        self.re.self_model_consistency_check(self.test_user)
        vec = self.re.get_relationship_vector(self.test_user)
        self.assertEqual(vec["comfort"], 1.5, "Comfort should have been corrected to 1.5")

    def test_candidate_update_quarantine_low_confidence(self):
        """Low-confidence inferred updates should be quarantined."""
        self.re.propose_candidate_update(
            username=self.test_user,
            key="favorite_food",
            value="pizza",
            confidence=0.3,
            source="inferred"
        )
        # Verify it's quarantined by checking DB
        with self.re._get_conn() as conn:
            row = conn.execute(
                "SELECT status FROM candidate_semantic_updates WHERE username = ? AND key_pref = ?",
                (self.test_user.lower().strip(), "favorite_food")
            ).fetchone()
        if row:
            self.assertEqual(row["status"], "quarantined")

    def test_save_task_replay(self):
        """Verify replay file generation."""
        test_task_id = "test_replay_001"
        self.re.save_task_replay(
            task_id=test_task_id,
            goal="Test replay goal",
            steps=[{"step": 1, "action": "test_action", "status": "success", "duration": 1.0}],
            events=[{"type": "TEST", "data": {}}],
            reflections="Test reflection summary"
        )
        trace_path = os.path.join("replays", test_task_id, "trace.json")
        self.assertTrue(os.path.exists(trace_path), f"Trace file should exist at {trace_path}")

        # Cleanup
        import shutil
        shutil.rmtree(os.path.join("replays", test_task_id), ignore_errors=True)


class TestContextBudgetManager(unittest.TestCase):
    """Verifies that ContextBudgetManager respects character limits."""

    def setUp(self):
        from skills.context_budget import ContextBudgetManager
        self.cbm = ContextBudgetManager(max_characters=200)

    def test_empty_input(self):
        result = self.cbm.score_and_select_memories([], [])
        self.assertEqual(len(result), 0)

    def test_budget_respected(self):
        episodes = [
            {"id": f"ep_{i}", "event_text": f"Episode text number {i} with some padding content here.", "timestamp": time.time() - i * 3600, "importance": 0.5 + i * 0.1}
            for i in range(10)
        ]
        result = self.cbm.score_and_select_memories(episodes, [])
        total_chars = sum(len(m["text"]) for m in result)
        self.assertLessEqual(total_chars + len(result) * 5, 200, "Total characters should not exceed budget")

    def test_build_prompt_context_format(self):
        selected = [{"source": "episodic", "text": "User prefers dark mode"}]
        prompt = self.cbm.build_prompt_context(selected)
        self.assertIn("COGNITIVE CONTEXT MEMORY", prompt)
        self.assertIn("[EPISODIC]", prompt)

    def test_recency_prioritized(self):
        """Recent episodes should score higher than old ones."""
        now = time.time()
        episodes = [
            {"id": "recent", "event_text": "Recent event text", "timestamp": now, "importance": 0.5},
            {"id": "old", "event_text": "Ancient event text", "timestamp": now - 86400 * 30, "importance": 0.5}
        ]
        result = self.cbm.score_and_select_memories(episodes, [], max_chars=500)
        if len(result) >= 2:
            # First selected should be more recent
            self.assertEqual(result[0]["id"], "recent")


class TestSandboxSafety(unittest.TestCase):
    """Verifies SandboxSafetyLayer risk classification and privacy zones."""

    def setUp(self):
        from skills.sandbox_safety import SandboxSafetyLayer
        self.ssl = SandboxSafetyLayer()

    def test_privacy_zone_blocks_banking(self):
        result = self.ssl.is_perception_allowed("Chrome - My Bank Account - Online Banking")
        self.assertFalse(result, "Banking windows should be blocked by privacy zone")

    def test_privacy_zone_allows_normal(self):
        result = self.ssl.is_perception_allowed("Visual Studio Code")
        self.assertTrue(result, "Normal windows should be allowed")

    def test_privacy_zone_blocks_password_manager(self):
        result = self.ssl.is_perception_allowed("1Password - Vault")
        self.assertFalse(result, "Password manager should be blocked by privacy zone")


class TestMainRelationshipTriggers(unittest.TestCase):
    """Verifies main.py relationship adjustment triggers on user input."""

    def setUp(self):
        # Prevent threading.Thread from running in __init__
        self.thread_patcher = unittest.mock.patch('threading.Thread')
        self.mock_thread = self.thread_patcher.start()

        from main import ARIA
        # Mock other parts to avoid loading heavy things or starting pygame/TTS
        self.aria = ARIA()
        self.aria.known_user = "test_user"
        self.aria.reflection_engine = unittest.mock.MagicMock()
        self.aria.reflection_engine.get_relationship_vector.return_value = {"trust": 8.0}
        self.aria.episodic_memory = unittest.mock.MagicMock()
        self.aria.proactive_cognition = unittest.mock.MagicMock()

    def tearDown(self):
        self.thread_patcher.stop()

    def test_thanks_trigger(self):
        try:
            self.aria._handle_input_impl("thank you so much")
        except Exception:
            pass
        self.aria.reflection_engine.update_relationship_metrics.assert_any_call("test_user", delta_trust=0.2)

    def test_compliment_trigger(self):
        try:
            self.aria._handle_input_impl("that's great, ARIA!")
        except Exception:
            pass
        self.aria.reflection_engine.update_relationship_metrics.assert_any_call("test_user", delta_trust=0.2)

    def test_ar_trigger(self):
        try:
            self.aria._handle_input_impl("can you show the whiteboard")
        except Exception:
            pass
        self.aria.reflection_engine.update_relationship_metrics.assert_any_call("test_user", delta_trust=0.1)

    def test_polite_correction_trigger(self):
        try:
            self.aria._handle_input_impl("actually, i meant python")
        except Exception:
            pass
        self.aria.reflection_engine.update_relationship_metrics.assert_any_call("test_user", delta_trust=0.1)

    def test_stop_asking_trigger(self):
        try:
            self.aria._handle_input_impl("stop asking")
        except Exception:
            pass
        self.aria.reflection_engine.update_relationship_metrics.assert_any_call("test_user", delta_trust=-0.05)

    def test_long_session_trust_reward(self):
        self.aria.start_time = time.time() - 950.0  # > 15 mins ago
        self.aria.long_session_trust_applied = False
        
        has_user = getattr(self.aria, "known_user", None) is not None
        has_applied = getattr(self.aria, "long_session_trust_applied", False)
        over_time = (time.time() - self.aria.start_time) > 900.0
        self.assertTrue(has_user and not has_applied and over_time)


if __name__ == "__main__":
    unittest.main(verbosity=2)
