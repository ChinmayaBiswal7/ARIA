import unittest

from skills.voice_filter import is_valid_speech_text


class TestVoiceFilter(unittest.TestCase):
    def test_active_conversation_allows_short_replies(self):
        self.assertTrue(is_valid_speech_text("Okay.", active_conversation=True)[0])
        self.assertTrue(is_valid_speech_text("हेलो", active_conversation=True)[0])
        self.assertTrue(is_valid_speech_text("Amazon.", active_conversation=True)[0])
        self.assertTrue(is_valid_speech_text("Absolutely.", active_conversation=True)[0])
        self.assertTrue(is_valid_speech_text("That's it.", active_conversation=True)[0])

    def test_idle_context_still_filters_common_hallucinations(self):
        self.assertFalse(is_valid_speech_text("Okay.", active_conversation=False)[0])
        self.assertFalse(is_valid_speech_text("you", active_conversation=True)[0])


if __name__ == "__main__":
    unittest.main()
