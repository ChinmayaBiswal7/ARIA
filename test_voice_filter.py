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
        self.assertFalse(is_valid_speech_text("thank you", active_conversation=False)[0])

    def test_conversation_control_words_are_always_allowed(self):
        control_words = ["bye", "goodbye", "good bye", "exit", "pause", "resume", "stop"]
        for word in control_words:
            self.assertTrue(is_valid_speech_text(word, active_conversation=False)[0], f"Failed on: {word}")
            self.assertTrue(is_valid_speech_text(word, active_conversation=True)[0], f"Failed on: {word}")


if __name__ == "__main__":
    unittest.main()
