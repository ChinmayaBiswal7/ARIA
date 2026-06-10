import unittest
from unittest.mock import MagicMock, patch
import time
import os
import json
import datetime
import numpy as np
from skills.security_monitor import SecurityMonitor

class TestSecurityMonitor(unittest.TestCase):
    def setUp(self):
        self.mock_aria = MagicMock()
        # Mock active window and sandbox safety
        self.mock_aria.context_skill.get_active_window.return_value = "VS Code"
        self.mock_aria.sandbox_safety.is_perception_allowed.return_value = True
        self.mock_aria.known_user_similarity = 0.9
        
        self.monitor = SecurityMonitor(aria=self.mock_aria)
        # Mock lazy-loaded db and storage clients
        self.mock_db = MagicMock()
        self.mock_bucket = MagicMock()
        self.monitor._get_db = MagicMock(return_value=self.mock_db)
        self.monitor._get_storage_bucket = MagicMock(return_value=self.mock_bucket)
        
        # Proper NumPy array representing a dummy frame
        self.dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)

    def test_initial_state_safe(self):
        self.assertEqual(self.monitor.state, SecurityMonitor.STATE_SAFE)

    def test_safe_to_observing_on_unknown(self):
        # Frame with unknown face, mouse hasn't moved
        self.monitor.last_mouse_pos = (100, 100)
        with patch('pyautogui.position', return_value=(100, 100)):
            self.monitor.process_frame(frame=self.dummy_frame, identified_user=None, similarity=0.0, owner_present=True)
            
        self.assertEqual(self.monitor.state, SecurityMonitor.STATE_OBSERVING)
        self.assertIsNotNone(self.monitor.unknown_start_time)

    def test_observing_to_safe_on_owner_return(self):
        # First transition to OBSERVING
        self.monitor.last_mouse_pos = (100, 100)
        with patch('pyautogui.position', return_value=(100, 100)):
            self.monitor.process_frame(frame=self.dummy_frame, identified_user=None, similarity=0.0, owner_present=True)
            self.assertEqual(self.monitor.state, SecurityMonitor.STATE_OBSERVING)
            
            # Owner returns
            self.monitor.process_frame(frame=self.dummy_frame, identified_user="chinmay", similarity=0.9, owner_present=True)
            self.assertEqual(self.monitor.state, SecurityMonitor.STATE_SAFE)
            self.assertIsNone(self.monitor.unknown_start_time)

    @patch('firebase_admin.messaging.send')
    def test_observing_to_intrusion_on_timeout(self, mock_fcm_send):
        self.monitor.last_mouse_pos = (100, 100)
        with patch('pyautogui.position', return_value=(100, 100)):
            # Set to observing
            self.monitor.process_frame(frame=self.dummy_frame, identified_user=None, similarity=0.0, owner_present=True)
            self.assertEqual(self.monitor.state, SecurityMonitor.STATE_OBSERVING)
            
            # Artificially age the unknown start time
            self.monitor.unknown_start_time = time.time() - 11.0
            
            # Mock bucket blob
            mock_blob = MagicMock()
            mock_blob.public_url = "http://test.url/face.jpg"
            self.mock_bucket.blob.return_value = mock_blob
            
            # Trigger check
            self.monitor.process_frame(frame=self.dummy_frame, identified_user=None, similarity=0.0, owner_present=True)
            
            # Should transition to ALERTED via INTRUSION
            self.assertEqual(self.monitor.state, SecurityMonitor.STATE_ALERTED)
            self.assertTrue(mock_fcm_send.called)
            self.assertTrue(self.mock_db.collection.called)

    @patch('firebase_admin.messaging.send')
    @patch('pyautogui.screenshot')
    def test_immediate_intrusion_on_mouse_movement(self, mock_screenshot, mock_fcm_send):
        self.monitor.last_mouse_pos = (100, 100)
        
        # Mock screenshot
        mock_image = MagicMock()
        mock_screenshot.return_value = mock_image
        
        # Mouse moved while owner is absent and unknown face is seen
        with patch('pyautogui.position', return_value=(200, 200)):
            self.monitor.process_frame(frame=self.dummy_frame, identified_user=None, similarity=0.0, owner_present=False)
            
        # Should transition straight to ALERTED bypassing OBSERVING
        self.assertEqual(self.monitor.state, SecurityMonitor.STATE_ALERTED)
        self.assertTrue(mock_fcm_send.called)

    def test_privacy_zone_silences_intrusion(self):
        # Set window to a blocked one or mock sandbox safety to return False
        self.mock_aria.sandbox_safety.is_perception_allowed.return_value = False
        
        # Unknown face + mouse activity
        self.monitor.last_mouse_pos = (100, 100)
        with patch('pyautogui.position', return_value=(200, 200)):
            self.monitor.process_frame(frame=self.dummy_frame, identified_user=None, similarity=0.0, owner_present=False)
            
        # Should remain in SAFE state because perception is not allowed
        self.assertEqual(self.monitor.state, SecurityMonitor.STATE_SAFE)

    @patch('firebase_admin.messaging.send')
    @patch('pyautogui.screenshot')
    def test_remote_live_check_in(self, mock_screenshot, mock_fcm_send):
        # Mock screenshot
        mock_image = MagicMock()
        mock_screenshot.return_value = mock_image
        
        # Mock camera frame capture
        mock_camera = MagicMock()
        mock_camera.available = True
        mock_camera.capture_frame_raw.return_value = self.dummy_frame
        self.mock_aria.camera = mock_camera
        
        # Call remote check-in
        self.monitor.handle_remote_check_in()
        
        # Check Storage and DB calls
        self.assertTrue(self.mock_bucket.blob.called)
        self.assertTrue(self.mock_db.collection.called)
        self.assertTrue(mock_fcm_send.called)

if __name__ == '__main__':
    unittest.main()
