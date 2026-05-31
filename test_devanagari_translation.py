import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import ARIA

class TestDevanagariTranslation(unittest.TestCase):
    @patch('main.ARIA._translate_hindi_to_english')
    @patch('skills.command_router.handle_ar')
    @patch('main.ARIA._mark_conversation_activity')
    def test_devanagari_input_translation_and_routing(self, mock_mark_activity, mock_handle_ar, mock_translate):
        # Create ARIA mock instance dependencies
        aria = ARIA.__new__(ARIA)
        aria.brain = MagicMock()
        aria.brain.semantic_router = MagicMock()
        aria.brain.semantic_router.normalizer = MagicMock()
        
        # Mock normalization to return the normalized value
        aria.brain.semantic_router.normalizer.normalize.side_effect = lambda x: (x, "no change")
        
        # Mock translation to return "enable ar 3d mode" when Devanagari is input
        mock_translate.return_value = "enable ar 3d mode"
        
        # Mock AR handle to return handled=True
        mock_handle_ar.return_value = {"handled": True, "action": "ar", "response": "ar_playground_enabled"}
        
        # Mock other dependencies called during _handle_input_impl
        aria.known_user = "chinmay"
        aria.voice = MagicMock()
        aria.reflection_engine = MagicMock()
        aria.reflection_engine.get_relationship_vector.return_value = {"trust": 10.0}
        aria.automation_mode = False
        
        # Mock emotional detection
        aria._get_current_emotion = MagicMock(return_value="neutral")
        
        # Perform handle input
        devanagari_input = "या अलोके, एनेबल द एर 3D मोड।"
        aria._handle_input_impl(devanagari_input)
        
        # Verify translation was called with Devanagari input
        mock_translate.assert_called_once_with(devanagari_input)
        
        # Verify that handle_ar was called with "enable ar 3d mode" instead of the original Devanagari input
        mock_handle_ar.assert_called_once()
        called_args = mock_handle_ar.call_args[0]
        # called_args[0] is aria instance
        # called_args[1] is normalized inp
        # called_args[2] is user_input
        self.assertEqual(called_args[1], "enable ar 3d mode")
        self.assertEqual(called_args[2], "enable ar 3d mode")

if __name__ == "__main__":
    unittest.main()
