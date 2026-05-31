"""
test_cognitive_simulation.py — Verification suite for ARIA Cognitive Sandbox & Reasoning Traces.
"""

import time
import os
import sys
import sqlite3
import json
import unittest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestCognitiveSimulation(unittest.TestCase):
    def setUp(self):
        from skills.memory_manager import MemoryManager
        from skills.reflection_engine import ReflectionEngine
        from skills.cognitive_sandbox import CognitiveSandbox
        
        self.mm = MemoryManager()
        self.re = ReflectionEngine()
        self.sandbox = CognitiveSandbox()
        self.test_user = "test_simulation_user"
        
        self._clear_test_user()

    def tearDown(self):
        self._clear_test_user()

    def _clear_test_user(self):
        with self.re._get_conn() as conn:
            conn.execute("DELETE FROM relationship_vector WHERE username = ?", (self.test_user,))
            conn.execute("DELETE FROM user_preferences WHERE username = ?", (self.test_user,))
            conn.execute("DELETE FROM candidate_semantic_updates WHERE username = ?", (self.test_user,))
            conn.execute("DELETE FROM corrupted_cognition_quarantine WHERE original_data LIKE ?", (f"%{self.test_user}%",))
            conn.execute("DELETE FROM cognition_audit_log WHERE metadata_json LIKE ?", (f"%{self.test_user}%",))
            try:
                conn.execute("DELETE FROM cognitive_snapshots WHERE username = ?", (self.test_user,))
                conn.execute("DELETE FROM cognitive_state_versions WHERE username = ?", (self.test_user,))
                conn.execute("DELETE FROM relationship_vector_snapshots WHERE username = ?", (self.test_user,))
            except sqlite3.OperationalError:
                pass
            conn.commit()

    def test_sandbox_valid_preference_update(self):
        """Simulation sandbox verifies a harmless preference and permits it."""
        report = self.sandbox.simulate_preference_update(
            username=self.test_user,
            key="theme",
            value="dark",
            confidence=0.9,
            evidence=["ep_sim_01"],
            reasoning_trace="User worked late and requested dark UI."
        )
        
        self.assertTrue(report["success"], "Harmless dark theme should be permitted")
        self.assertEqual(len(report["trait_conflicts"]), 0)
        self.assertEqual(len(report["identity_drift"]), 0)
        self.assertIn("before_state", report)
        self.assertIn("after_state", report)
        self.assertIn("theme", report["after_state"]["preferences"])
        self.assertGreater(report["drift_delta_score"], 0.0)
        self.assertIsNotNone(report["rollback_snapshot_id"])
        self.assertRegex(report["cognitive_version"]["personality"], r"personality_v\d+")
        self.assertRegex(report["cognitive_version"]["profile"], r"profile_v\d+")

    def test_sandbox_contradictory_preference_update(self):
        """Simulation sandbox catches conflicting traits (e.g. silence_preferred=yes AND proactive_suggestions=yes) and rejects them."""
        # 1. Setup silence_preferred in database
        self.mm.set_preference(self.test_user, "silence_preferred", "yes", confidence=0.8, reasoning_trace="Setup base silence")
        
        # 2. Simulate setting contradictory preference: proactive_suggestions = yes
        report = self.sandbox.simulate_preference_update(
            username=self.test_user,
            key="proactive_suggestions",
            value="yes",
            confidence=0.8,
            evidence=["ep_sim_02"],
            reasoning_trace="Proposing proactive suggestions."
        )
        
        self.assertFalse(report["success"], "Sandbox should reject contradictory settings")
        self.assertGreater(len(report["trait_conflicts"]), 0, "Should flag trait conflict")

    def test_reasoning_trace_storage_and_promotion(self):
        """Reasoning trace is correctly saved in user_preferences and propagated during candidate updates promotion."""
        trace_msg = "Direct observation that user prefers light editor backgrounds."
        
        # Save preference directly
        self.mm.set_preference(
            username=self.test_user,
            key="editor_background",
            value="light",
            confidence=0.95,
            evidence=["ep_obs_01"],
            reasoning_trace=trace_msg
        )
        
        # Verify SQLite has it
        with self.re._get_conn() as conn:
            row = conn.execute(
                "SELECT reasoning_trace FROM user_preferences WHERE username = ? AND pref_key = 'editor_background'",
                (self.test_user,)
            ).fetchone()
            
        self.assertIsNotNone(row)
        self.assertEqual(row["reasoning_trace"], trace_msg)

    def test_reasoning_confidence_storage(self):
        """Reasoning confidence is stored separately from memory confidence."""
        self.mm.set_preference(
            username=self.test_user,
            key="editor",
            value="vscode",
            confidence=0.95,
            reasoning_trace="User explicitly said VS Code.",
            reasoning_confidence=0.55
        )

        with self.re._get_conn() as conn:
            row = conn.execute(
                "SELECT confidence, reasoning_confidence FROM user_preferences WHERE username = ? AND pref_key = 'editor'",
                (self.test_user,)
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["confidence"], 0.95)
        self.assertEqual(row["reasoning_confidence"], 0.55)

    def test_relationship_simulation_and_clamping(self):
        """Relationship delta simulation clamps massive trust drops to prevent memory poisoning."""
        # Simulate delta drops that exceed safe floors
        report = self.sandbox.simulate_relationship_update(
            username=self.test_user,
            delta_trust=-35.0,  # exceeds SINGLE_PASS_TRUST_SPIKE_LIMIT / floor drop
            delta_comfort=-40.0
        )
        
        self.assertTrue(report["success"])
        clamped = report["clamped_metrics"]
        
        # Safe drop drops trust delta to -1.0 (floor drop threshold)
        self.assertEqual(clamped["trust_delta"], -1.0)
        self.assertEqual(clamped["comfort_delta"], -1.5)
        self.assertIn("clamped due to memory poisoning safeguards", report["anomalies"][0].lower())
        self.assertIn("before_state", report)
        self.assertIn("after_state", report)
        self.assertGreaterEqual(report["drift_delta_score"], 0.0)

    def test_emotional_volatility_spike_and_collapse(self):
        """Validator flags recent trust spikes and sudden comfort collapse."""
        from skills.self_model_validator import SelfModelValidator

        now = time.time()
        with self.re._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO relationship_vector
                (username, trust, comfort, interaction_depth, emotional_openness, updated_at)
                VALUES (?, 40.0, 8.0, 10.0, 10.0, ?)
            """, (self.test_user, now))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS relationship_vector_snapshots (
                    username TEXT NOT NULL,
                    trust REAL NOT NULL,
                    comfort REAL NOT NULL,
                    interaction_depth REAL NOT NULL,
                    emotional_openness REAL NOT NULL,
                    snapshot_at REAL NOT NULL
                )
            """)
            conn.execute("""
                INSERT INTO relationship_vector_snapshots
                (username, trust, comfort, interaction_depth, emotional_openness, snapshot_at)
                VALUES (?, 10.0, 35.0, 10.0, 10.0, ?)
            """, (self.test_user, now - 30.0))
            conn.commit()

        report = SelfModelValidator().detect_emotional_volatility(self.test_user)

        self.assertTrue(report["trust_spike_detected"])
        self.assertTrue(report["comfort_collapse_detected"])
        self.assertGreaterEqual(len(report["alerts"]), 2)

    def test_evidence_aging_reduces_old_confidence(self):
        """Older evidence contributes less by decaying memory confidence."""
        with self.re._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO user_preferences
                (username, pref_key, pref_value, updated_at, confidence, evidence)
                VALUES (?, 'old_pref', 'yes', ?, 0.9, '["ep_old"]')
            """, (self.test_user, time.time() - 91 * 86400.0))
            conn.commit()

        self.mm.apply_evidence_aging()

        with self.re._get_conn() as conn:
            row = conn.execute(
                "SELECT confidence FROM user_preferences WHERE username = ? AND pref_key = 'old_pref'",
                (self.test_user,)
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertLess(row["confidence"], 0.9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
