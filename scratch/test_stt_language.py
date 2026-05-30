# -*- coding: utf-8 -*-
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice import Voice

class TestSTTLanguage(unittest.TestCase):
    @patch("speech_recognition.Microphone")
    @patch("speech_recognition.Recognizer")
    @patch("pygame.mixer.init")
    @patch("voice.Voice._load_groq_key")
    @patch("requests.post")
    def test_whisper_transcribe_language_en(self, mock_post, mock_key, mock_pygame, mock_rec, mock_mic):
        mock_key.return_value = "fake_key"
        
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "hello"}
        mock_post.return_value = mock_response

        # Mock audio data
        mock_audio = MagicMock()
        mock_audio.get_wav_data.return_value = b"wav_data"

        # Initialize voice
        v = Voice()
        v.stt_language = "en"
        
        # Transcribe
        res = v.whisper_transcribe(mock_audio)
        self.assertEqual(res, "hello")
        
        # Verify language parameter in files payload
        mock_post.assert_called_once()
        kwargs = mock_post.call_args[1]
        files = kwargs["files"]
        self.assertIn("language", files)
        self.assertEqual(files["language"], (None, "en"))

    @patch("speech_recognition.Microphone")
    @patch("speech_recognition.Recognizer")
    @patch("pygame.mixer.init")
    @patch("voice.Voice._load_groq_key")
    @patch("requests.post")
    def test_whisper_transcribe_language_none(self, mock_post, mock_key, mock_pygame, mock_rec, mock_mic):
        mock_key.return_value = "fake_key"
        
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "hello"}
        mock_post.return_value = mock_response

        # Mock audio data
        mock_audio = MagicMock()
        mock_audio.get_wav_data.return_value = b"wav_data"

        # Initialize voice
        v = Voice()
        v.stt_language = None
        
        # Transcribe
        res = v.whisper_transcribe(mock_audio)
        self.assertEqual(res, "hello")
        
        # Verify language parameter NOT in files payload
        mock_post.assert_called_once()
        kwargs = mock_post.call_args[1]
        files = kwargs["files"]
        self.assertNotIn("language", files)

if __name__ == "__main__":
    unittest.main()
