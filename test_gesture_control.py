import unittest
from unittest.mock import MagicMock
import sys
import os
import time

# Ensure root folder is in sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from skills.gesture_control import GestureController, _dist

class MockLandmark:
    def __init__(self, x, y, z=0.0):
        self.x = x
        self.y = y
        self.z = z

class TestGestureControl(unittest.TestCase):
    def setUp(self):
        # Mock frame provider callback
        self.frame_provider = MagicMock(return_value=None)
        self.callback = MagicMock()
        
        # Instantiate controller under mock (bypassing model check in start, but we directly test landmark processing)
        # We need to temporarily mock MEDIAPIPE_AVAILABLE if not available, but since it is imported we can just mock options
        self.controller = GestureController(frame_provider=self.frame_provider, callback=self.callback)

    def _create_base_landmarks(self):
        # 21 landmarks. Standard position where they are folded (close to middle MCP = landmark 9)
        # Landmark 0: wrist (0.5, 0.8)
        # Landmark 9: middle MCP (0.5, 0.5)
        # Folded fingers should be close to middle MCP
        lm = [MockLandmark(0.5, 0.8) for _ in range(21)]
        lm[0] = MockLandmark(0.5, 0.8) # Wrist
        lm[9] = MockLandmark(0.5, 0.5) # Middle MCP
        
        # Fold other fingers (tips close to 9)
        lm[8] = MockLandmark(0.5, 0.51)  # Index tip
        lm[12] = MockLandmark(0.5, 0.52) # Middle tip
        lm[16] = MockLandmark(0.5, 0.53) # Ring tip
        lm[20] = MockLandmark(0.5, 0.54) # Pinky tip
        
        # Bases/MCPs of index, middle, ring, pinky
        lm[5] = MockLandmark(0.4, 0.55)  # Index base
        lm[6] = MockLandmark(0.4, 0.52)
        lm[10] = MockLandmark(0.5, 0.56) # Middle base
        lm[14] = MockLandmark(0.6, 0.55) # Ring base
        lm[18] = MockLandmark(0.7, 0.54) # Pinky base
        
        # Thumb MCP is landmark 2. Thumb tip is 4.
        lm[2] = MockLandmark(0.3, 0.6)
        lm[3] = MockLandmark(0.25, 0.55)
        lm[4] = MockLandmark(0.2, 0.5)
        
        return lm

    def test_thumbs_up_detection(self):
        lm = self._create_base_landmarks()
        
        # For Thumbs Up:
        # 1. Fold other fingers (done in _create_base_landmarks: index_dist, etc. are small)
        # 2. Thumb is open: fingers[0] = True
        # 3. Tip lm[4].y < lm[2].y (tip is higher/smaller y than MCP)
        # 4. Extended thumb: distance from tip to MCP/MCP9 is large
        lm[4] = MockLandmark(0.2, 0.2) # Tip far up
        lm[2] = MockLandmark(0.3, 0.5) # Base MCP
        
        fingers = [True, False, False, False, False]
        now = time.time()
        
        # Test detection directly
        res = self.controller._check_high_level_events(lm, fingers, now)
        
        self.assertTrue(res)
        self.callback.assert_called_once_with("GESTURE_CONFIRM")

    def test_thumbs_down_detection(self):
        lm = self._create_base_landmarks()
        
        # For Thumbs Down:
        # 1. Fold other fingers
        # 2. Tip lm[4].y > lm[2].y (tip is lower/larger y than MCP)
        # 3. Extended thumb
        lm[4] = MockLandmark(0.2, 0.7) # Tip far down
        lm[2] = MockLandmark(0.3, 0.5) # Base MCP
        
        fingers = [True, False, False, False, False]
        now = time.time()
        
        # Test detection directly
        res = self.controller._check_high_level_events(lm, fingers, now)
        
        self.assertTrue(res)
        self.callback.assert_called_once_with("GESTURE_CANCEL")

    def test_wave_detection(self):
        # We need all fingers open
        fingers = [True, True, True, True, True]
        
        # Simulate consecutive frames representing a side-to-side wave
        # Middle MCP (landmark 9) x coordinate will oscillate back and forth:
        # 0.5 -> 0.6 -> 0.7 -> 0.6 -> 0.5 -> 0.4 -> 0.3 -> 0.4 -> 0.5 -> 0.6 -> 0.7
        x_sequence = [
            0.5, 0.55, 0.6, 0.65, 0.7,   # Moving Right
            0.65, 0.6, 0.55, 0.5, 0.45,  # Moving Left (Sign change 1)
            0.4, 0.35, 0.3,              # Continuing Left
            0.35, 0.4, 0.45, 0.5, 0.55,  # Moving Right (Sign change 2)
            0.6, 0.65, 0.7,              # Continuing Right
            0.65, 0.6, 0.55, 0.5         # Moving Left (Sign change 3)
        ]
        
        # Feed the sequence of coordinates
        now = time.time()
        triggered = False
        for idx, x in enumerate(x_sequence):
            lm = self._create_base_landmarks()
            lm[9].x = x # Middle MCP
            
            # Extend index, middle, ring, pinky in coordinate space to avoid fingers_folded being True
            lm[8] = MockLandmark(x, 0.2)   # Index tip
            lm[12] = MockLandmark(x, 0.1)  # Middle tip
            lm[16] = MockLandmark(x, 0.2)  # Ring tip
            lm[20] = MockLandmark(x, 0.3)  # Pinky tip
            
            # Run detection check
            res = self.controller._check_high_level_events(lm, fingers, now)
            if res:
                triggered = True
                
        self.assertTrue(triggered)
        self.callback.assert_called_once_with("GESTURE_WAKE")

if __name__ == "__main__":
    unittest.main()
