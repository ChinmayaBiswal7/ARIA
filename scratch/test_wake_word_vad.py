# -*- coding: utf-8 -*-
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice import Voice

class TestWakeWordVAD(unittest.TestCase):
    @patch("speech_recognition.Microphone")
    @patch("speech_recognition.Recognizer")
    @patch("pygame.mixer.init")
    def test_default_vad_thresholds(self, mock_pygame, mock_rec, mock_mic):
        v = Voice()
        
        # We mock VAD module so it doesn't try to load webrtcvad
        with patch("webrtcvad.Vad") as mock_vad_cls:
            mock_vad = MagicMock()
            mock_vad_cls.return_value = mock_vad
            
            # Setup mock audio
            mock_audio = MagicMock()
            mock_audio.sample_rate = 16000
            mock_audio.sample_width = 2
            mock_audio.get_raw_data.return_value = b"\x00\x00" * 960 # 30ms frame
            
            # Mock webrtcvad.Vad.is_speech to return True for all frames
            mock_vad.is_speech.return_value = True
            
            # Call is_human_speech with active_conversation=True
            with patch("builtins.print") as mock_print:
                res_conv = v.is_human_speech(mock_audio, active_conversation=True)
                # Should use CONVERSATION_VAD_THRESHOLD = 0.15
                args, kwargs = mock_print.call_args_list[-1]
                log_msg = args[0]
                self.assertIn("Threshold: 15.0%", log_msg)
                
            # Call is_human_speech with active_conversation=False
            with patch("builtins.print") as mock_print:
                res_idle = v.is_human_speech(mock_audio, active_conversation=False)
                # Should use WAKE_VAD_THRESHOLD = 0.18
                args, kwargs = mock_print.call_args_list[-1]
                log_msg = args[0]
                self.assertIn("Threshold: 18.0%", log_msg)

    @patch("speech_recognition.Microphone")
    @patch("speech_recognition.Recognizer")
    @patch("pygame.mixer.init")
    @patch("voice.Voice.denoise_audio")
    @patch("voice.Voice.is_loud_enough")
    @patch("voice.Voice.is_human_speech")
    def test_listen_for_wake_word_vad_call(self, mock_human_speech, mock_loud, mock_denoise, mock_pygame, mock_rec, mock_mic):
        v = Voice()
        mock_loud.return_value = True
        mock_human_speech.return_value = False # fail VAD check to exit early
        
        # Setup mock microphone listen
        mock_audio = MagicMock()
        v._record_audio_chunked = MagicMock(return_value=mock_audio)
        mock_denoise.return_value = mock_audio
        
        # Trigger wake-word listening
        v.listen_for_wake_word(timeout=3)
        
        # Verify is_human_speech was called with min_ratio=0.18
        mock_human_speech.assert_called_once()
        kwargs = mock_human_speech.call_args[1]
        self.assertEqual(kwargs.get("min_ratio"), 0.18)
        self.assertEqual(kwargs.get("active_conversation"), False)

if __name__ == "__main__":
    unittest.main()
