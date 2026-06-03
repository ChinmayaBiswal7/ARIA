import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Ensure project path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from skills.runtime_capabilities import CAPABILITIES

if not (CAPABILITIES.has_cv2 and CAPABILITIES.has_numpy):
    raise unittest.SkipTest("cv2/numpy unavailable; skipping optional vision stability tests")

import numpy as np
from main import ARIA

class TestFaceRecognitionStability(unittest.TestCase):
    
    def setUp(self):
        # Instantiate ARIA without calling initialize() to avoid spawning threads/hardware connections
        self.aria = ARIA()
        
        # Set up mocks for camera and memory dependencies
        self.aria.camera = MagicMock()
        self.aria.camera.available = True
        
        self.aria.memory = MagicMock()
        self.mock_mm = MagicMock()
        self.aria.memory.memory_manager = self.mock_mm
        
        # Mock context_skill and sandbox_safety (needed by _detect_user privacy zone check)
        self.aria.context_skill = MagicMock()
        self.aria.context_skill.get_active_window.return_value = "Test Window"
        self.aria.sandbox_safety = MagicMock()
        self.aria.sandbox_safety.is_perception_allowed.return_value = True
        
        # Clear/initialize match history
        self.aria.face_match_history = []
        
    def test_detect_user_no_camera(self):
        self.aria.camera.available = False
        res = self.aria._detect_user()
        self.assertIsNone(res)
        
    def test_detect_user_no_embeddings(self):
        self.aria.camera.available = True
        self.aria.camera.capture_image.return_value = "dummy_frame"
        self.mock_mm.embedder.get_embedding.return_value = None
        
        res = self.aria._detect_user()
        self.assertIsNone(res)
        
    def test_detect_user_averaging_and_l2_normalization(self):
        self.aria.camera.available = True
        self.aria.camera.capture_image.return_value = "dummy_frame"
        
        # Create mock 4096-dimensional face embedding vectors
        v1 = [0.1] * 4096
        v2 = [0.2] * 4096
        v3 = [0.15] * 4096
        
        embeddings_sequence = [v1, v2, v3, v1, v2]
        self.mock_mm.embedder.get_embedding.side_effect = embeddings_sequence
        
        # Mock memory_manager.identify_user
        self.mock_mm.identify_user.return_value = ("Unknown", 0.0)
        
        res = self.aria._detect_user()
        
        # Verify averaging calculation
        avg_v = np.mean(embeddings_sequence, axis=0)
        norm = np.linalg.norm(avg_v)
        expected_normalized_avg = (avg_v / norm).tolist()
        
        self.mock_mm.identify_user.assert_called_once()
        called_args, called_kwargs = self.mock_mm.identify_user.call_args
        actual_embedding = called_kwargs.get('embedding')
        
        np.testing.assert_allclose(actual_embedding, expected_normalized_avg, rtol=1e-5)
        self.assertIsNone(res)

    def test_detect_user_temporal_smoothing_boost(self):
        self.aria.camera.available = True
        self.aria.camera.capture_image.return_value = "dummy_frame"
        
        # Mock embedding return
        mock_emb = [0.1] * 4096
        self.mock_mm.embedder.get_embedding.return_value = mock_emb
        
        # Setup history with 2 "chinmay" detections
        self.aria.face_match_history = [
            ("chinmay", 0.76),
            ("chinmay", 0.77),
        ]
        
        # Now detect user again; identify_user returns "chinmay" with similarity 0.78
        self.mock_mm.identify_user.return_value = ("chinmay", 0.78)
        
        name = self.aria._detect_user()
        
        self.assertEqual(name, "chinmay")
        # Match history has 2 pre-existing + 1 new = 3 "chinmay" matches.
        # This is >= 3 out of 5 frames, so similarity boosts by +0.05
        # Expected similarity: 0.78 + 0.05 = 0.83
        self.assertAlmostEqual(self.aria.known_user_similarity, 0.83)
        self.assertEqual(self.aria.known_user_confidence, "medium")  # 0.83 in [0.75, 0.85)

    def test_detect_user_temporal_smoothing_high_confidence(self):
        self.aria.camera.available = True
        self.aria.camera.capture_image.return_value = "dummy_frame"
        
        mock_emb = [0.1] * 4096
        self.mock_mm.embedder.get_embedding.return_value = mock_emb
        
        # Setup history with 3 "chinmay" detections
        self.aria.face_match_history = [
            ("chinmay", 0.82),
            ("chinmay", 0.81),
            ("chinmay", 0.83),
        ]
        
        # identify_user returns "chinmay" with similarity 0.81
        self.mock_mm.identify_user.return_value = ("chinmay", 0.81)
        
        name = self.aria._detect_user()
        
        self.assertEqual(name, "chinmay")
        # similarity boosted: 0.81 + 0.05 = 0.86
        self.assertAlmostEqual(self.aria.known_user_similarity, 0.86)
        self.assertEqual(self.aria.known_user_confidence, "high")  # 0.86 >= 0.85

    def test_detect_user_persistence_lock_success(self):
        import time
        self.aria.camera.available = True
        self.aria.camera.capture_image.return_value = "dummy_frame"
        
        # Mock embedding return for 1 frame
        mock_emb = [0.1] * 4096
        self.mock_mm.embedder.get_embedding.return_value = mock_emb
        
        # Setup active locked identity
        self.aria.known_user = "chinmay"
        self.aria.known_user_confidence = "high"
        self.aria.last_identity_match_time = time.time() - 40.0
        self.aria.known_user_similarity = 0.88
        
        # identify_user returns the locked name
        self.mock_mm.identify_user.return_value = ("chinmay", 0.89)
        
        # Run detection: it should hit the fast persistence lock path (only 1 get_embedding call)
        name = self.aria._detect_user()
        
        self.assertEqual(name, "chinmay")
        self.mock_mm.embedder.get_embedding.assert_called_once()
        self.assertEqual(self.aria.known_user_similarity, 0.89)
        self.assertEqual(self.aria.known_user_confidence, "high")

    def test_detect_user_persistence_lock_different_user(self):
        import time
        self.aria.camera.available = True
        self.aria.camera.capture_image.return_value = "dummy_frame"
        
        # Mock embedding sequences:
        # First call (lock path): mock_emb (different user)
        # Next 5 calls (fallback path): 5 * mock_emb
        mock_emb = [0.1] * 4096
        self.mock_mm.embedder.get_embedding.return_value = mock_emb
        
        # Setup active locked identity
        self.aria.known_user = "chinmay"
        self.aria.known_user_confidence = "high"
        self.aria.last_identity_match_time = time.time() - 40.0
        self.aria.known_user_similarity = 0.88
        
        # First query returns different user "rahul", triggering lock break
        # Subsequent query (full averaging) returns "rahul"
        self.mock_mm.identify_user.side_effect = [
            ("rahul", 0.78),  # Break lock check
            ("rahul", 0.78),  # Full check
        ]
        
        name = self.aria._detect_user()
        
        self.assertEqual(name, "rahul")
        self.assertEqual(self.aria.known_user, "rahul")
        self.assertEqual(self.aria.known_user_confidence, "medium")  # similarity 0.78 is medium

    def test_detect_user_face_disappeared_clears_identity(self):
        self.aria.camera.available = True
        self.aria.camera.capture_image.return_value = "dummy_frame"
        
        # Camera captures but embedder returns None (no face detected)
        self.mock_mm.embedder.get_embedding.return_value = None
        
        # Set active user
        self.aria.known_user = "chinmay"
        self.aria.known_user_confidence = "high"
        self.aria.known_user_similarity = 0.90
        self.aria.face_match_history = [("chinmay", 0.90)]
        
        name = self.aria._detect_user()
        
        self.assertIsNone(name)
        # Since face disappeared, state should be reset/cleared
        self.assertIsNone(self.aria.known_user)
        self.assertEqual(self.aria.known_user_confidence, "none")
        self.assertEqual(self.aria.known_user_similarity, 0.0)
        self.assertEqual(self.aria.face_match_history, [])

if __name__ == "__main__":
    unittest.main()
