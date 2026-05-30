# -*- coding: utf-8 -*-
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from skills.gesture_control import (
    GestureController, ACTIVE_X_MIN, ACTIVE_X_MAX,
    MIN_ALPHA, MAX_ALPHA, PINCH_THRESH, PINCH_RELEASE_THRESH
)

class MockLandmark:
    def __init__(self, x, y, z=0.0):
        self.x = x
        self.y = y
        self.z = z

class TestGestureControlUpgrades(unittest.TestCase):
    @patch("pyautogui.size")
    @patch("pyautogui.position")
    @patch("pyautogui.moveTo")
    @patch("pyautogui.click")
    def test_active_zone_remapping(self, mock_click, mock_moveTo, mock_position, mock_size):
        mock_size.return_value = (1920, 1080)
        mock_position.return_value = (100, 100)
        
        # We need a dummy frame_provider
        gc = GestureController(frame_provider=lambda: None)
        
        # Test 1: Hand in center
        lm_center = [None]*21
        lm_center[8] = MockLandmark(x=0.5, y=0.5)
        gc._move_cursor(lm_center)
        
        # With active zone 0.5 is exactly in the middle of X [0.35, 0.65] and Y [0.40, 0.60] (norm = 0.5)
        # 0.5 * 1920 = 960, 0.5 * 1080 = 540
        self.assertAlmostEqual(gc._sx, 960.0)
        self.assertAlmostEqual(gc._sy, 540.0)
        
        # Test 2: Hand at left active zone boundary (0.35)
        gc._sx = gc._sy = None
        lm_left = [None]*21
        lm_left[8] = MockLandmark(x=0.35, y=0.5)
        gc._move_cursor(lm_left)
        self.assertAlmostEqual(gc._sx, 0.0)
        
        # Test 3: Hand at right active zone boundary (0.65)
        gc._sx = gc._sy = None
        lm_right = [None]*21
        lm_right[8] = MockLandmark(x=0.65, y=0.5)
        gc._move_cursor(lm_right)
        self.assertAlmostEqual(gc._sx, 1920.0)
        
        # Test 4: Hand clamped outside active zone (e.g. 0.20 -> clamps to 0.35 -> 0.0)
        gc._sx = gc._sy = None
        lm_outside = [None]*21
        lm_outside[8] = MockLandmark(x=0.20, y=0.5)
        gc._move_cursor(lm_outside)
        self.assertAlmostEqual(gc._sx, 0.0)

    @patch("pyautogui.size")
    @patch("pyautogui.position")
    @patch("pyautogui.moveTo")
    def test_dynamic_smoothing(self, mock_moveTo, mock_position, mock_size):
        mock_size.return_value = (1920, 1080)
        mock_position.return_value = (100, 100)
        
        gc = GestureController(frame_provider=lambda: None)
        
        # Initialize position
        lm_start = [None]*21
        lm_start[8] = MockLandmark(x=0.5, y=0.5)
        gc._move_cursor(lm_start)
        self.assertAlmostEqual(gc._sx, 960.0)
        
        # Move slightly (very slow move)
        # 0.5025 relative coordinate in active zone (0.30 span) is (0.5025-0.35)/0.30 = 0.508333
        # 0.508333 * 1920 = 976.0 (diff of 16px)
        lm_slow = [None]*21
        lm_slow[8] = MockLandmark(x=0.5025, y=0.5)
        
        # Let's intercept requests inside the dynamic calculation
        # We patch math.sqrt inside self._move_cursor to see the alpha applied
        with patch("skills.gesture_control.MIN_ALPHA", 0.15) as mock_min, \
             patch("skills.gesture_control.MAX_ALPHA", 0.80) as mock_max:
            
            # Reset and do a fresh move:
            gc._sx = 960.0
            gc._sy = 540.0            
            # Since distance is 16px:
            # alpha = 0.15 + (0.80 - 0.15) * ((16.0 - 10.0) / 140.0) = 0.15 + 0.65 * (6.0/140.0) = 0.1778
            gc._move_cursor(lm_slow)
            self.assertTrue(0.15 < (gc._sx - 960.0)/16.0 < 0.20)

    @patch("pyautogui.click")
    def test_click_debouncing_state_machine(self, mock_click):
        gc = GestureController(frame_provider=lambda: None)
        self.assertFalse(gc._is_pinched)
        
        # Create pinched landmarks (thumb and index close)
        lm = [None]*21
        lm[4] = MockLandmark(0.5, 0.5)
        lm[8] = MockLandmark(0.5, 0.5 + (PINCH_THRESH - 0.01)) # Pinched!
        
        fingers = [True, True, False, False, False]
        now = 100.0
        
        # 1st call: should click
        gc._check_click(lm, fingers, now)
        mock_click.assert_called_once()
        self.assertTrue(gc._is_pinched)
        
        mock_click.reset_mock()
        
        # 2nd call: still pinched, should NOT click again
        gc._check_click(lm, fingers, now + 0.1)
        mock_click.assert_not_called()
        self.assertTrue(gc._is_pinched)
        
        # 3rd call: finger separation increases, but not past release threshold
        lm[8] = MockLandmark(0.5, 0.5 + (PINCH_THRESH + 0.01)) # slightly apart
        gc._check_click(lm, fingers, now + 0.2)
        mock_click.assert_not_called()
        self.assertTrue(gc._is_pinched) # still locked due to hysteresis
        
        # 4th call: fingers fully separate past release threshold
        lm[8] = MockLandmark(0.5, 0.5 + (PINCH_RELEASE_THRESH + 0.01))
        gc._check_click(lm, fingers, now + 0.3)
        mock_click.assert_not_called()
        self.assertFalse(gc._is_pinched) # released!
        
        # 5th call: pinch again, should click again (after 0.45s cooldown)
        lm[8] = MockLandmark(0.5, 0.5 + (PINCH_THRESH - 0.01))
        gc._check_click(lm, fingers, now + 0.50)
        mock_click.assert_called_once()
        self.assertTrue(gc._is_pinched)

    @patch("pyautogui.rightClick")
    def test_right_click(self, mock_right_click):
        gc = GestureController(frame_provider=lambda: None)
        lm = [None]*21
        lm[4] = MockLandmark(0.5, 0.5)
        lm[12] = MockLandmark(0.5, 0.5 + (PINCH_THRESH - 0.01))
        fingers = [True, True, True, False, False]
        gc._check_right_click(lm, fingers, 100.0)
        mock_right_click.assert_called_once()
        self.assertTrue(gc._is_right_pinched)

    @patch("pyautogui.doubleClick")
    def test_double_click(self, mock_double_click):
        gc = GestureController(frame_provider=lambda: None)
        lm = [None]*21
        lm[4] = MockLandmark(0.5, 0.5)
        lm[20] = MockLandmark(0.5, 0.5 + (PINCH_THRESH - 0.01))
        fingers = [True, True, False, False, True]
        gc._check_double_click(lm, fingers, 100.0)
        mock_double_click.assert_called_once()
        self.assertTrue(gc._is_double_pinched)

    @patch("pyautogui.mouseDown")
    @patch("pyautogui.mouseUp")
    def test_drag_and_drop(self, mock_mouseup, mock_mousedown):
        gc = GestureController(frame_provider=lambda: None)
        lm = [None]*21
        lm[4] = MockLandmark(0.5, 0.5)
        lm[16] = MockLandmark(0.5, 0.5 + (PINCH_THRESH - 0.01))
        fingers = [True, True, False, True, False]
        
        # Pinch to drag
        gc._check_drag_and_drop(lm, fingers, 100.0)
        mock_mousedown.assert_called_once()
        self.assertTrue(gc._is_dragging)
        
        # Release pinch
        lm[16] = MockLandmark(0.5, 0.5 + (PINCH_RELEASE_THRESH + 0.01))
        gc._check_drag_and_drop(lm, fingers, 100.5) # beyond cooldown/interval
        mock_mouseup.assert_called_once()
        self.assertFalse(gc._is_dragging)

    @patch("pyautogui.press")
    def test_volume_control(self, mock_press):
        gc = GestureController(frame_provider=lambda: None)
        lm = [None]*21
        lm[12] = MockLandmark(0.5, 0.5)
        fingers = [False, True, True, True, False]
        
        # Init vol y
        gc._check_volume(lm, fingers, 100.0)
        self.assertEqual(gc._prev_vol_y, 0.5)
        
        # Move up (delta > 0)
        lm[12] = MockLandmark(0.5, 0.4)
        gc._check_volume(lm, fingers, 100.2)
        mock_press.assert_called_once_with('volumeup', _pause=False)

if __name__ == "__main__":
    unittest.main()
