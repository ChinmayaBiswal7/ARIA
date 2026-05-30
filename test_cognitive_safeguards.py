"""
test_cognitive_safeguards.py — verification suite for ARIA cognitive safeguards.
==================================================================================
Tests:
1. Database Self-Healing (moves corrupted data to quarantine, heals in-place).
2. Reflection Grounding & Evidence Links (grounded facts vs hallucinated).
3. Relationship Decay & Inertia (trust/comfort decays slower with more memories).
4. Proactive Cooldown Back-off (cooldown multiplier scales with user negative reaction).
5. Identity Isolation / Guest Mode (ensures guest interactions don't leak to profile).
"""

import time
import os
import sys
import sqlite3
import json
import unittest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestCognitiveSafeguards(unittest.TestCase):
    def setUp(self):
        from skills.memory_manager import MemoryManager
        from skills.reflection_engine import ReflectionEngine
        from skills.proactive_cognition import ProactiveCognition
        
        self.mm = MemoryManager()
        self.re = ReflectionEngine()
        self.pc = ProactiveCognition(cooldown_minutes=1)
        self.test_user = "test_safeguard_user"
        
        # Clear out test database items if any
        self._clear_test_user()

    def tearDown(self):
        self._clear_test_user()

    def _clear_test_user(self):
        with self.re._get_conn() as conn:
            conn.execute("DELETE FROM relationship_vector WHERE username = ?", (self.test_user,))
            conn.execute("DELETE FROM user_preferences WHERE username = ?", (self.test_user,))
            conn.execute("DELETE FROM candidate_semantic_updates WHERE username = ?", (self.test_user,))
            conn.execute("DELETE FROM corrupted_cognition_quarantine WHERE original_data LIKE ?", (f"%{self.test_user}%",))
            conn.commit()

    def test_database_self_healing_out_of_bounds(self):
        """Out-of-bound relationship vector metrics are quarantined and set to default 10.0."""
        # Insert a corrupt out-of-bounds row
        with self.re._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO relationship_vector 
                (username, trust, comfort, interaction_depth, emotional_openness, updated_at)
                VALUES (?, 150.0, -10.0, 50.0, 999.0, ?)
            """, (self.test_user, time.time()))
            conn.commit()

        # Run database validation
        self.mm.validate_and_heal_database()

        # Check healed values
        vec = self.re.get_relationship_vector(self.test_user)
        self.assertEqual(vec["trust"], 10.0, "Should reset to default 10.0")
        self.assertEqual(vec["comfort"], 10.0, "Should reset to default 10.0")
        self.assertEqual(vec["emotional_openness"], 10.0, "Should reset to default 10.0")

        # Check quarantine log
        with self.re._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM corrupted_cognition_quarantine WHERE table_name = 'relationship_vector' AND original_data LIKE ?",
                (f"%{self.test_user}%",)
            ).fetchone()
        self.assertIsNotNone(row, "Corrupted row should be logged to quarantine table")

    def test_reflection_grounding_validation(self):
        """Proposed candidates with no grounding in recent episodes should be skipped."""
        # Setup recent episodes - no mention of 'dark theme'
        recent_episodes = [
            {"id": "ep1", "event_text": "User prefers Python for writing code in VS Code.", "emotion": "neutral", "importance": 0.5}
        ]
        
        # Manually trigger reflection parser
        # We search for "programming_language = python" (present) and "theme = dark" (not present)
        # Verify that pattern match requires keyword overlap with the episode text.
        self.re._run_reflection(self.test_user, recent_episodes, [])
        
        # Check candidate updates database
        with self.re._get_conn() as conn:
            python_row = conn.execute(
                "SELECT * FROM candidate_semantic_updates WHERE username = ? AND key_pref = 'programming_language'",
                (self.test_user,)
            ).fetchone()
            dark_row = conn.execute(
                "SELECT * FROM candidate_semantic_updates WHERE username = ? AND key_pref = 'theme' AND val_pref = 'dark'",
                (self.test_user,)
            ).fetchone()

        self.assertIsNotNone(python_row, "Python programming language should be extracted and proposed")
        self.assertIsNone(dark_row, "Unreferenced 'dark' theme should be skipped (failed grounding)")

    def test_promoted_evidence_links(self):
        """Promoted preferences should carry evidence links back to source episodes."""
        episode_ids = ["ep_source_101", "ep_source_202"]
        self.mm.set_preference(self.test_user, "theme", "dark", confidence=0.9, evidence=episode_ids)

        # Query user_preferences table
        with self.re._get_conn() as conn:
            row = conn.execute(
                "SELECT evidence, confidence FROM user_preferences WHERE username = ? AND pref_key = 'theme'",
                (self.test_user,)
            ).fetchone()
        
        self.assertIsNotNone(row)
        ev_list = json.loads(row["evidence"])
        self.assertEqual(ev_list, episode_ids, "Evidence links should match source episodes")
        self.assertEqual(row["confidence"], 0.9)

    def test_relationship_decay_and_inertia(self):
        """Relationship decay should occur, but be scaled down (inertia) when more memories are present."""
        # 1. Test case: User with no memories (high decay)
        with self.re._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO relationship_vector 
                (username, trust, comfort, interaction_depth, emotional_openness, updated_at)
                VALUES (?, 50.0, 50.0, 50.0, 50.0, ?)
            """, (self.test_user, time.time() - 86400.0 * 2))  # 2 days ago
            conn.commit()

        # Run reflection pass to trigger decay
        self.re._run_reflection(self.test_user, [], [])
        vec_no_mem = self.re.get_relationship_vector(self.test_user)

        # 2. Test case: User with 5 memories (low decay due to high inertia)
        self._clear_test_user()
        with self.re._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO relationship_vector 
                (username, trust, comfort, interaction_depth, emotional_openness, updated_at)
                VALUES (?, 50.0, 50.0, 50.0, 50.0, ?)
            """, (self.test_user, time.time() - 86400.0 * 2))  # 2 days ago
            
            # Add 5 highly confident memories to increase inertia
            for i in range(5):
                conn.execute("""
                    INSERT INTO user_preferences (username, pref_key, pref_value, updated_at, confidence)
                    VALUES (?, ?, ?, ?, 0.9)
                """, (self.test_user, f"key_{i}", f"val_{i}", time.time()))
            conn.commit()

        # Run reflection pass to trigger decay
        self.re._run_reflection(self.test_user, [], [])
        vec_with_mem = self.re.get_relationship_vector(self.test_user)

        # Compare: trust decay with memories should be LESS than trust decay without memories
        decay_no_mem = 50.0 - vec_no_mem["trust"]
        decay_with_mem = 50.0 - vec_with_mem["trust"]
        
        self.assertGreater(decay_no_mem, 0)
        self.assertGreater(decay_with_mem, 0)
        self.assertGreater(decay_no_mem, decay_with_mem, "Decay should be slower when memory inertia is present")

    def test_proactive_cooldown_backoff(self):
        """Negative user feedback should increase the proactive cooldown multiplier, positive should reset it."""
        self.assertEqual(self.pc.cooldown_multiplier, 1.0)

        # Negative feedback: double the multiplier
        self.pc.log_user_engagement("shut up ARIA, be quiet")
        self.assertEqual(self.pc.cooldown_multiplier, 2.0)

        # Consecutive negative feedback: double again
        self.pc.log_user_engagement("please stop talking")
        self.assertEqual(self.pc.cooldown_multiplier, 4.0)

        # Positive feedback: reset to 1.0
        self.pc.log_user_engagement("thank you, that was helpful")
        self.assertEqual(self.pc.cooldown_multiplier, 1.0)

    def test_guest_mode_identity_isolation(self):
        """Guest mode interactions should not save preferences to sqlite profile."""
        # Try to save preference for 'guest'
        self.mm.set_preference("guest", "theme", "light")
        
        # Verify it wasn't written to SQLite user_preferences
        with self.re._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM user_preferences WHERE username = 'guest'"
            ).fetchone()
        self.assertIsNone(row, "Guest preference should not be saved in user_preferences profile")


if __name__ == "__main__":
    unittest.main(verbosity=2)
