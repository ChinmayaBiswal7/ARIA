import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import speech_recognition as sr
import asyncio

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from voice import Voice
from brain import Brain

class TestMultilingualRouting(unittest.TestCase):
    def setUp(self):
        # Start all patchers so they remain active for the duration of each test run
        self.patchers = [
            patch('voice.Voice._load_available_voices'),
            patch('voice.Voice._init_mic'),
            patch('voice.Voice.calibrate_noise_profile'),
            patch('pygame.mixer.music'),
            patch('pygame.mixer.init'),
        ]
        
        self.mocks = [p.start() for p in self.patchers]
        
        for p in self.patchers:
            self.addCleanup(p.stop)
            
        mock_mixer_music = self.mocks[3]
        mock_mixer_music.get_busy.return_value = False
        mock_mixer_music.get_volume.return_value = 0.5
        
        self.voice = Voice()
        self.voice.available_voices = [
            "en-US-AriaNeural",
            "hi-IN-MadhuramNeural",
            "hi-IN-SwaraNeural"
        ]
        self.voice._load_groq_key = MagicMock(return_value="mock_groq_key")
        self.voice._load_elevenlabs_key = MagicMock(return_value=None)

    def test_language_normalization_and_regex_fallback(self):
        with patch('requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "text": "नमस्ते आप कैसे हैं",
                "language": "hindi",
                "segments": [{"avg_logprob": -0.1, "no_speech_prob": 0.01}]
            }
            
            # Setup real AudioData to satisfy speech_recognition library checks
            audio_data = sr.AudioData(b'\x00' * 32000, 16000, 2)
            
            # Transcribe
            res = self.voice.whisper_transcribe(audio_data)
            self.assertEqual(res, "नमस्ते आप कैसे हैं")
            self.assertEqual(self.voice.current_language, "hi")
            self.assertEqual(self.voice.english_turns_count, 0)
    def test_consecutive_english_turns_reset(self):
        # Start in Hindi mode
        self.voice.current_language = "hi"
        self.voice.english_turns_count = 0

        with patch('requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "text": "Yes, sure.",
                "language": "english",
                "segments": []
            }
            
            audio_data = sr.AudioData(b'\x00' * 32000, 16000, 2)

            self.voice.whisper_transcribe(audio_data)
            # Should still be sticky to Hindi
            self.assertEqual(self.voice.current_language, "hi")
            self.assertEqual(self.voice.english_turns_count, 1)

            # Simulate 2nd English turn
            self.voice.whisper_transcribe(audio_data)
            # Should reset to English
            self.assertEqual(self.voice.current_language, "en")
            self.assertEqual(self.voice.english_turns_count, 2)

    def test_regex_force_language_fallback(self):
        # Even if Whisper API returns english, if script is Odia, force Odia
        with patch('requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "text": "ନମସ୍କାର ତୁମେ କେମିତି ଅଛ",
                "language": "english",
                "segments": []
            }
            
            audio_data = sr.AudioData(b'\x00' * 32000, 16000, 2)

            self.voice.whisper_transcribe(audio_data)
            self.assertEqual(self.voice.current_language, "or")

    def test_edge_tts_voice_selection_and_fallback(self):
        async def mock_save(*args, **kwargs):
            return None

        # 1. Hindi voice present
        self.voice.current_language = "hi"
        with patch('edge_tts.Communicate') as mock_comm:
            mock_comm.return_value.save = mock_save
            self.voice.speak("नमस्ते")
            mock_comm.assert_called_once()
            called_args = mock_comm.call_args[0]
            self.assertEqual(called_args[1], "hi-IN-MadhuramNeural")

        # 2. Odia voice missing, should fallback to hi-IN-MadhuramNeural
        self.voice.current_language = "or"
        with patch('edge_tts.Communicate') as mock_comm2:
            mock_comm2.return_value.save = mock_save
            self.voice.speak("ନମସ୍କାର")
            called_args = mock_comm2.call_args[0]
            self.assertEqual(called_args[1], "hi-IN-MadhuramNeural")

        # 3. Odia voice present, should use or-IN-OdiaNeural
        self.voice.available_voices.append("or-IN-OdiaNeural")
        with patch('edge_tts.Communicate') as mock_comm3:
            mock_comm3.return_value.save = mock_save
            self.voice.speak("ନମସ୍କାର")
            called_args = mock_comm3.call_args[0]
            self.assertEqual(called_args[1], "or-IN-OdiaNeural")

    def test_brain_system_prompt_language_directives(self):
        brain = Brain.__new__(Brain)
        
        # Test Hindi prompt
        brain.current_language = "hi"
        prompt_hi = brain._build_system_prompt()
        self.assertIn("You must respond only in Hindi", prompt_hi)
        self.assertIn("Use natural conversational Hindi", prompt_hi)

        # Test Odia prompt
        brain.current_language = "or"
        prompt_or = brain._build_system_prompt()
        self.assertIn("You must respond only in Odia", prompt_or)
        self.assertIn("Use natural conversational Odia", prompt_or)

if __name__ == "__main__":
    unittest.main()
