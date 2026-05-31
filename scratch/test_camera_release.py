# -*- coding: utf-8 -*-
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Create a mock health monitor and main loop dependencies before importing main
sys.modules['voice'] = MagicMock()
sys.modules['brain'] = MagicMock()
sys.modules['camera'] = MagicMock()
sys.modules['automation'] = MagicMock()
sys.modules['memory'] = MagicMock()
sys.modules['vision_learn'] = MagicMock()
sys.modules['screen_control'] = MagicMock()
sys.modules['ui_control'] = MagicMock()

# Mock other external dependencies that get imported
sys.modules['PyQt5'] = MagicMock()
sys.modules['PyQt5.QtWidgets'] = MagicMock()
sys.modules['PyQt5.QtCore'] = MagicMock()
sys.modules['PyQt5.QtGui'] = MagicMock()

# Avoid running pygame init during import
import pygame
pygame.init = MagicMock()
pygame.mixer = MagicMock()

# Now import ARIA from main
with patch('pygame.mixer.init'):
    from main import ARIA

class TestCameraRelease(unittest.TestCase):
    def test_camera_not_released_when_ar_active(self):
        # Instantiate a mock-initialized ARIA
        with patch.object(ARIA, '__init__', lambda self: None):
            aria = ARIA()
            aria.camera = MagicMock()
            aria.ar_mode = True
            aria.ar_playground = MagicMock()
            aria.gesture_mode = False
            aria.vision_learner = MagicMock()
            aria.vision_learner.running = False
            
            aria._check_and_release_camera()
            aria.camera.release.assert_not_called()

    def test_camera_not_released_when_gesture_active(self):
        with patch.object(ARIA, '__init__', lambda self: None):
            aria = ARIA()
            aria.camera = MagicMock()
            aria.ar_mode = False
            aria.ar_playground = None
            aria.gesture_mode = True
            aria.vision_learner = MagicMock()
            aria.vision_learner.running = False
            
            aria._check_and_release_camera()
            aria.camera.release.assert_not_called()

    def test_camera_released_when_all_inactive(self):
        with patch.object(ARIA, '__init__', lambda self: None):
            aria = ARIA()
            aria.camera = MagicMock()
            aria.ar_mode = False
            aria.ar_playground = None
            aria.gesture_mode = False
            aria.vision_learner = MagicMock()
            aria.vision_learner.running = False
            
            aria._check_and_release_camera()
            aria.camera.release.assert_called_once()

if __name__ == "__main__":
    unittest.main()
