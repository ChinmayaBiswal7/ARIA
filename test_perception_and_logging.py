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
        import numpy as np
        self.aria.camera = MagicMock()
        self.aria.camera.available = True
        self.aria.camera.capture_frame_raw.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
        
        # Mock episodic memory
        self.aria.episodic_memory = MagicMock()
        
        # Mock face cascade
        self.aria.memory = MagicMock()
        self.aria.memory.face_cascade = MagicMock()
        
        # Mock memory manager
        self.mock_mm = MagicMock()
        self.mock_mm.identify_user.return_value = ("chinmaya", 0.90)
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
        self.aria.known_user_confidence = "high"
        self.aria.known_user_similarity = 0.90
        self.aria.last_identity_match_time = time.time()
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
        def mock_impl(user_input, image=None, source=None):
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

    def test_presence_engine_no_abort_loop(self):
        from voice import Voice
        with patch.object(Voice, '_init_mic'), \
             patch.object(Voice, 'calibrate_noise_profile'):
            self.aria.voice = Voice()

        import sys
        main_mod = sys.modules['__main__']
        orig_aria_instance = getattr(main_mod, 'aria_instance', None)
        main_mod.aria_instance = self.aria
        
        try:
            self.aria.known_user = "chinmay"
            self.aria.last_identity_match_time = time.time()
            
            mock_source = MagicMock()
            mock_source.SAMPLE_RATE = 16000
            mock_source.SAMPLE_WIDTH = 2
            mock_source.stream.read.return_value = b'\xff\x7f' * 1600
            
            # active_conversation=True should NOT abort
            audio = self.aria.voice._record_audio_chunked(
                mock_source,
                timeout=1,
                phrase_time_limit=1,
                active_conversation=True
            )
            self.assertIsNotNone(audio)
            
            # active_conversation=False SHOULD abort because owner is active
            audio_aborted = self.aria.voice._record_audio_chunked(
                mock_source,
                timeout=1,
                phrase_time_limit=1,
                active_conversation=False
            )
            self.assertIsNone(audio_aborted)
        finally:
            if orig_aria_instance is not None:
                main_mod.aria_instance = orig_aria_instance
            elif hasattr(main_mod, 'aria_instance'):
                del main_mod.aria_instance

    @patch('skills.voice_session_commands.HEALTH.is_available', return_value=True)
    def test_source_routing_isolation(self, mock_is_available):
        # Mock speech_queue and voice
        self.aria.speech_queue = MagicMock()
        self.aria.voice = MagicMock()
        self.aria.voice.is_speaking = False
        
        # Mock firebase_sync
        self.aria.firebase_sync = MagicMock()
        self.aria.firebase_sync.firestore_client = MagicMock()
        mock_doc = MagicMock()
        self.aria.firebase_sync.firestore_client.collection.return_value.document.return_value = mock_doc
        
        # Setup _reply_context
        self.aria._reply_context = MagicMock()
        self.aria._reply_context.phone_only = False
        self.aria._reply_context.input_source = "laptop"
        
        # 1. Test source="phone"
        self.aria._speak("hello to phone", source="phone")
        # Verify speech_queue was NOT touched
        self.aria.speech_queue.put.assert_not_called()
        self.aria.voice.speak.assert_not_called()
        # Verify firestore_client was written to
        self.aria.firebase_sync.firestore_client.collection.assert_called_with("phone_reply")
        self.aria.firebase_sync.firestore_client.collection().document.assert_called_with("latest")
        mock_doc.set.assert_called_once()
        args, kwargs = mock_doc.set.call_args
        self.assertEqual(args[0]["response"], "hello to phone")
        
        # Reset mocks
        self.aria.speech_queue.reset_mock()
        self.aria.voice.speak.reset_mock()
        self.aria.firebase_sync.firestore_client.collection.reset_mock()
        mock_doc.set.reset_mock()
        
        # 2. Test source="laptop"
        self.aria._speak("hello to laptop", source="laptop")
        # Verify speech_queue WAS touched
        self.aria.speech_queue.put.assert_called_once()
        # Verify firestore_client was NOT written to
        self.aria.firebase_sync.firestore_client.collection.assert_not_called()
        mock_doc.set.assert_not_called()

if __name__ == "__main__":
    unittest.main()
