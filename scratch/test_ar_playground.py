# -*- coding: utf-8 -*-
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.append(os.getcwd())

from skills.ar_playground import ARPlayground, generate_tone, MEDIAPIPE_AVAILABLE

class TestARPlayground(unittest.TestCase):
    def test_tone_synthesis(self):
        """Verify dynamic audio generation returns a Pygame Sound object."""
        # Initialize pygame mixer in headless mode if not initialized
        import pygame
        if not pygame.mixer.get_init():
            try:
                pygame.mixer.init(frequency=44100, size=-16, channels=2)
            except Exception:
                pass
        
        sound = generate_tone(440.0, duration=0.1)
        if pygame.mixer.get_init():
            self.assertIsNotNone(sound, "Tone synthesis failed.")
            self.assertIsInstance(sound, pygame.mixer.Sound, "Synthesized tone is not a pygame Sound object.")
        else:
            print("Pygame mixer not initialized (headless/no audio card). Skipping Sound instance check.")

    def test_mode_switching(self):
        """Verify ARPlayground mode state changes correctly."""
        ap = ARPlayground(frame_provider=lambda: None)
        
        # Test default mode
        self.assertEqual(ap._mode, "wand")
        
        # Test voice trigger switches
        ap.set_mode("flowers")
        self.assertEqual(ap._mode, "flowers")
        
        ap.set_mode("piano")
        self.assertEqual(ap._mode, "piano")
        
        ap.set_mode("pet")
        self.assertEqual(ap._mode, "pet")
        
        ap.set_mode("magic")
        self.assertEqual(ap._mode, "wand")

        ap.set_mode("drawing")
        self.assertEqual(ap._mode, "drawing")

        ap.set_mode("physics")
        self.assertEqual(ap._mode, "physics")

        ap.set_mode("face")
        self.assertEqual(ap._mode, "face")

        ap.set_mode("pose")
        self.assertEqual(ap._mode, "pose")

        ap.set_mode("whiteboard")
        self.assertEqual(ap._mode, "whiteboard")

        ap.set_mode("object")
        self.assertEqual(ap._mode, "object")

    def test_canvas_clearing(self):
        """Verify clear_canvas erases particles and flowers."""
        ap = ARPlayground(frame_provider=lambda: None)
        ap.particles.append({"pos": [1, 2]})
        ap.flowers.append({"pos": [3, 4]})
        
        self.assertEqual(len(ap.particles), 1)
        self.assertEqual(len(ap.flowers), 1)
        
        ap.clear_canvas()
        self.assertEqual(len(ap.particles), 0)
        self.assertEqual(len(ap.flowers), 0)

    @patch("skills.ar_playground._mp_vision.HandLandmarker.create_from_options")
    def test_start_stop(self, mock_create):
        """Verify start and stop thread states."""
        ap = ARPlayground(frame_provider=lambda: None)
        
        # Mock running state
        ap._running = False
        with patch.object(ap, "_loop") as mock_loop:
            # If MediaPipe isn't available, start() returns False immediately
            if not MEDIAPIPE_AVAILABLE:
                res = ap.start()
                self.assertFalse(res)
            else:
                # Mock models path check to return True
                with patch("os.path.exists", return_value=True):
                    res = ap.start()
                    self.assertTrue(res)
                    self.assertTrue(ap._running)
                    ap.stop()
                    self.assertFalse(ap._running)

    def test_modes_processing_with_landmarks(self):
        """Verify all AR modes process dummy hand landmarks without raising exceptions."""
        from skills.ar_playground import DummyHandLandmarks
        import numpy as np

        class MockLandmark:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        # Create 21 mock landmarks
        mock_raw_lm = [MockLandmark(0.5, 0.5) for _ in range(21)]
        wrapped_lm = DummyHandLandmarks(mock_raw_lm)
        wrapped_lm_list = [wrapped_lm]

        ap = ARPlayground(frame_provider=lambda: None)
        dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)

        # Iterate through all modes and invoke _update_and_draw to ensure no crash occurs
        for mode in ["wand", "flowers", "piano", "pet", "drawing", "physics", "face", "pose", "whiteboard", "object", "ar3d"]:
            ap.set_mode(mode)
            try:
                ap._update_and_draw(dummy_frame, wrapped_lm, 1280, 720, False, wrapped_lm_list)
            except Exception as e:
                self.fail(f"Mode '{mode}' failed processing with landmarks: {e}")

if __name__ == "__main__":
    unittest.main()

