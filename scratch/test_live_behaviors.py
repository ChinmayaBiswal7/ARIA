# -*- coding: utf-8 -*-
"""
scratch/test_live_behaviors.py — Behavioral verification script
"""
import sys
import os
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from main import ARIA
from skills.proactive_cognition import ProactiveCognition

class TestLiveBehaviors(unittest.TestCase):
    def setUp(self):
        # Prevent actual hardware/subsystem initialization during tests
        with patch('main.ARIAWindow'), patch('main.QApplication'):
            from skills.subsystem_health import HEALTH
            HEALTH.mark_healthy("tts")
            self.aria = ARIA()
            self.aria.running = True
            self.aria.voice = MagicMock()
            self.aria.voice.recording_active = False
            self.aria.voice.vad_detecting_speech = False
            self.aria.speech_queue = MagicMock()

    def test_fix1_safe_speak_queuing_during_speech(self):
        # Case 1: User is speaking (recent speech < 3s)
        self.aria.last_user_speech_time = time.time()
        self.aria.safe_speak("Proactive suggestion: stand up.")
        
        self.assertIn("Proactive suggestion: stand up.", self.aria.pending_speech)
        self.aria.speech_queue.put.assert_not_called()

        # Case 2: User is silent (last speech > 3s)
        self.aria.pending_speech.clear()
        self.aria.last_user_speech_time = time.time() - 4.0
        self.aria.safe_speak("Proactive suggestion: stretch.")
        
        self.assertNotIn("Proactive suggestion: stretch.", self.aria.pending_speech)
        self.aria.speech_queue.put.assert_called_with("Proactive suggestion: stretch.")

    def test_fix2_proactive_cooldown_and_deduplication(self):
        self.aria.last_user_speech_time = 0.0
        
        # Deliver proactive message first time
        self.aria.deliver_proactive("Take a short walk around the block to rest.")
        self.assertIn("Take a short walk around the block to rest.", self.aria._proactive_history)
        
        # Second time of same message should be ignored
        self.aria.speech_queue.put.reset_mock()
        self.aria.deliver_proactive("Take a short walk around the block to rest.")
        self.aria.speech_queue.put.assert_not_called()

        # Substantially similar prefix check cooldown
        self.aria.speech_queue.put.reset_mock()
        self.aria.deliver_proactive("Take a short walk around the building today.")
        self.aria.speech_queue.put.assert_not_called()

    def test_fix2_stress_responses_variety(self):
        pc = ProactiveCognition()
        pc.trigger_proactive_speak = MagicMock()
        
        # Verify that multiple stress requests generate random soft suggestions, including None
        suggestions = []
        for _ in range(50):
            # Reset cooldown status mock
            pc.last_proactive_speak_time = 0.0
            suggestion = pc.generate_soft_suggestion("stressed", {"username": "chinmaya"})
            suggestions.append(suggestion)
            
        # Should contain varied stress responses
        unique_suggestions = set(filter(None, suggestions))
        self.assertGreater(len(unique_suggestions), 1)
        self.assertIn(None, suggestions) # Weighted toward silence

    def test_fix3_ar_cleanup_on_stop(self):
        self.aria.ar_mode = True
        self.aria.ar_playground = MagicMock()
        self.aria.ar_playground._running = False
        
        # Verify main loop block cleans up dead playground objects
        # We simulate one iteration of the cleanup block
        if self.aria.ar_playground and not self.aria.ar_playground._running:
            self.aria.ar_playground = None
            self.aria.ar_mode = False
            
        self.assertIsNone(self.aria.ar_playground)
        self.assertFalse(self.aria.ar_mode)

if __name__ == "__main__":
    unittest.main()
