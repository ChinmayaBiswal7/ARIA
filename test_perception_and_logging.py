import sys
import os
import unittest
import time
from unittest.mock import MagicMock, patch
from PIL import Image

# Ensure project path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import ARIA

class TestPerceptionAndLogging(unittest.TestCase):
    def setUp(self):
        self.aria = ARIA()
        
        # Mock the camera
        self.aria.camera = MagicMock()
        self.aria.camera.available = True
        
        # Mock episodic memory
        self.aria.episodic_memory = MagicMock()
        
        # Mock face cascade
        self.aria.memory = MagicMock()
        self.aria.memory.face_cascade = MagicMock()
        
        # Mock memory manager
        self.mock_mm = MagicMock()
        self.aria.memory.memory_manager = self.mock_mm
        
        # Mock context_skill and sandbox_safety
        self.aria.context_skill = MagicMock()
        self.aria.context_skill.get_active_window.return_value = "Normal Desktop"
        self.aria.sandbox_safety = MagicMock()
        self.aria.sandbox_safety.is_perception_allowed.return_value = True
        
        # Mock brain
        self.aria.brain = MagicMock()
        self.aria.brain.vision_ready = True
        
        # Reset state variables
        self.aria.known_user = "chinmaya"
        self.aria.presence_state = "USER_LEFT"
        self.aria.current_user_emotion = "neutral"
        self.aria.current_user_emotion_confidence = 1.0
        self.aria.last_interaction_time = time.time()

    def test_background_perception_no_face(self):
        # Setup: camera returns dummy frame, face cascade detects 0 faces
        dummy_img = Image.new('RGB', (100, 100))
        self.aria.camera.capture_image.return_value = dummy_img
        self.aria.memory.face_cascade.detectMultiScale.return_value = []
        
        self.aria._run_background_perception()
        
        # Verify: presence state is USER_LEFT, emotion reset to neutral
        self.assertEqual(self.aria.presence_state, "USER_LEFT")
        self.assertEqual(self.aria.current_user_emotion, "neutral")

    def test_background_perception_emotional_user(self):
        # Setup: camera returns dummy frame, face cascade detects 1 face
        dummy_img = Image.new('RGB', (100, 100))
        self.aria.camera.capture_image.return_value = dummy_img
        self.aria.memory.face_cascade.detectMultiScale.return_value = [(10, 20, 100, 100)]
        self.mock_mm.embedder.get_embedding.return_value = [0.1] * 4096
        self.mock_mm.identify_user.return_value = ("chinmaya", 0.90)
        
        # Vision model returns "sad"
        self.aria.brain._ask_vision.return_value = "sad"
        
        # Trigger background perception
        self.aria._run_background_perception()
        
        # Verify: emotion updated to sad, episodic memory recorded, presence_state USER_EMOTIONAL
        self.assertEqual(self.aria.current_user_emotion, "sad")
        self.assertEqual(self.aria.presence_state, "USER_EMOTIONAL")
        self.aria.episodic_memory.record.assert_called_once()
        
        # Check call arguments
        args, kwargs = self.aria.episodic_memory.record.call_args
        self.assertEqual(kwargs.get("username"), "chinmaya")
        self.assertEqual(kwargs.get("emotion"), "sad")
        self.assertEqual(kwargs.get("source"), "observed")

    def test_background_perception_engaged_user(self):
        # Setup: face cascade detects 1 face, emotion is neutral
        dummy_img = Image.new('RGB', (100, 100))
        self.aria.camera.capture_image.return_value = dummy_img
        self.aria.memory.face_cascade.detectMultiScale.return_value = [(10, 20, 100, 100)]
        self.mock_mm.embedder.get_embedding.return_value = [0.1] * 4096
        self.mock_mm.identify_user.return_value = ("chinmaya", 0.90)
        
        # Vision returns "neutral"
        self.aria.brain._ask_vision.return_value = "neutral"
        
        # Update last interaction to 5 seconds ago
        self.aria.last_interaction_time = time.time() - 5.0
        
        self.aria._run_background_perception()
        
        # Verify: presence state is USER_ENGAGED
        self.assertEqual(self.aria.presence_state, "USER_ENGAGED")
        self.assertEqual(self.aria.current_user_emotion, "neutral")

    def test_background_perception_present_user(self):
        # Setup: face cascade detects 1 face, emotion is neutral
        dummy_img = Image.new('RGB', (100, 100))
        self.aria.camera.capture_image.return_value = dummy_img
        self.aria.memory.face_cascade.detectMultiScale.return_value = [(10, 20, 100, 100)]
        self.mock_mm.embedder.get_embedding.return_value = [0.1] * 4096
        self.mock_mm.identify_user.return_value = ("chinmaya", 0.90)
        self.aria.brain._ask_vision.return_value = "neutral"
        
        # Update last interaction to 60 seconds ago
        self.aria.last_interaction_time = time.time() - 60.0
        
        self.aria._run_background_perception()
        
        # Verify: presence state is USER_PRESENT
        self.assertEqual(self.aria.presence_state, "USER_PRESENT")

    def test_background_perception_idle_user(self):
        # Setup: face cascade detects 1 face, emotion is neutral
        dummy_img = Image.new('RGB', (100, 100))
        self.aria.camera.capture_image.return_value = dummy_img
        self.aria.memory.face_cascade.detectMultiScale.return_value = [(10, 20, 100, 100)]
        self.mock_mm.embedder.get_embedding.return_value = [0.1] * 4096
        self.mock_mm.identify_user.return_value = ("chinmaya", 0.90)
        self.aria.brain._ask_vision.return_value = "neutral"
        
        # Update last interaction to 150 seconds ago
        self.aria.last_interaction_time = time.time() - 150.0
        
        self.aria._run_background_perception()
        
        # Verify: presence state is USER_IDLE
        self.assertEqual(self.aria.presence_state, "USER_IDLE")

    def test_conversational_turn_logging_in_wrapper(self):
        # Mock _handle_input_impl to speak something and then return early (which was bypassing logging before)
        def mock_impl(user_input, image=None):
            self.aria._speak("Hello there, chinmaya!")
            return True
            
        self.aria._handle_input_impl = mock_impl
        self.aria.speech_queue = MagicMock()
        
        # Call the wrapped _handle_input
        self.aria._handle_input("hi")
        
        # Verify: episodic memory recorded the conversational turn despite the early return in mock_impl
        self.aria.episodic_memory.record.assert_called_once()
        args, kwargs = self.aria.episodic_memory.record.call_args
        self.assertEqual(kwargs.get("username"), "chinmaya")
        self.assertIn("User: 'hi'", kwargs.get("event_text"))
        self.assertIn("ARIA: 'Hello there, chinmaya!'", kwargs.get("event_text"))
        self.assertEqual(kwargs.get("source"), "user_explicit")

if __name__ == "__main__":
    unittest.main()
