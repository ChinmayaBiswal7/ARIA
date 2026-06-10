import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import time
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from skills.wake_word_sentinel import AriaWakeSentinel

class TestWakeWordSentinel(unittest.TestCase):
    @patch('os.path.exists')
    @patch('openwakeword.model.Model')
    @patch('pyaudio.PyAudio')
    def setUp(self, mock_pyaudio, mock_model_class, mock_exists):
        mock_exists.return_value = True
        self.mock_model = MagicMock()
        mock_model_class.return_value = self.mock_model
        
        self.mock_audio = MagicMock()
        mock_pyaudio.return_value = self.mock_audio
        self.mock_stream = MagicMock()
        self.mock_audio.open.return_value = self.mock_stream
        # Return dummy 80ms mono PCM bytes matching CHUNK_SIZE * 2
        self.mock_stream.read.return_value = b'\x00' * 2560
        
        self.callback_fired = False
        self.callback_count = 0
        
        def mock_callback():
            self.callback_fired = True
            self.callback_count += 1
            
        self.wake_callback = mock_callback
        
    @patch('os.path.exists')
    @patch('openwakeword.model.Model')
    def test_missing_model_handling(self, mock_model_class, mock_exists):
        mock_exists.return_value = False
        
        # Capture warnings
        with patch('logging.Logger.warning') as mock_warn:
            sentinel = AriaWakeSentinel(model_path="nonexistent_aria.onnx")
            self.assertIsNone(sentinel.model)
            mock_warn.assert_called_once()
            
            # Verify starting background listening returns immediately
            sentinel.start_background_listening(self.wake_callback)
            self.assertEqual(self.callback_count, 0)

    @patch('os.path.exists')
    @patch('openwakeword.model.Model')
    def test_wake_trigger(self, mock_model_class, mock_exists):
        mock_exists.return_value = True
        mock_model_class.return_value = self.mock_model
        
        # Mock predict to return trigger score
        self.mock_model.predict.return_value = {"aria": 0.85}
        
        sentinel = AriaWakeSentinel()
        sentinel.model = self.mock_model
        
        # Stop loop after one execution to avoid infinite loops
        def stop_after_one(*args, **kwargs):
            sentinel.stop()
            return {"aria": 0.85}
        self.mock_model.predict.side_effect = stop_after_one
        
        sentinel.start_background_listening(self.wake_callback)
        
        self.assertTrue(self.callback_fired)
        self.assertEqual(self.callback_count, 1)
        self.mock_model.reset.assert_called_once()

    @patch('os.path.exists')
    @patch('openwakeword.model.Model')
    def test_no_trigger_below_threshold(self, mock_model_class, mock_exists):
        mock_exists.return_value = True
        mock_model_class.return_value = self.mock_model
        
        self.mock_model.predict.return_value = {"aria": 0.20}
        
        sentinel = AriaWakeSentinel()
        sentinel.model = self.mock_model
        
        def stop_after_one(*args, **kwargs):
            sentinel.stop()
            return {"aria": 0.20}
        self.mock_model.predict.side_effect = stop_after_one
        
        sentinel.start_background_listening(self.wake_callback)
        
        self.assertFalse(self.callback_fired)
        self.assertEqual(self.callback_count, 0)
        self.mock_model.reset.assert_not_called()

    @patch('os.path.exists')
    @patch('openwakeword.model.Model')
    def test_cooldown_prevention(self, mock_model_class, mock_exists):
        mock_exists.return_value = True
        mock_model_class.return_value = self.mock_model
        
        sentinel = AriaWakeSentinel()
        sentinel.model = self.mock_model
        
        # Run predict twice. First time triggers callback, second time should be within 3s cooldown and ignore it.
        call_idx = 0
        def predict_seq(*args, **kwargs):
            nonlocal call_idx
            call_idx += 1
            if call_idx >= 2:
                sentinel.stop()
            return {"aria": 0.85}
            
        self.mock_model.predict.side_effect = predict_seq
        
        sentinel.start_background_listening(self.wake_callback)
        
        self.assertTrue(self.callback_fired)
        self.assertEqual(self.callback_count, 1) # Only once due to cooldown

    @patch('os.path.exists')
    @patch('openwakeword.model.Model')
    def test_state_coordination_provider_busy(self, mock_model_class, mock_exists):
        mock_exists.return_value = True
        mock_model_class.return_value = self.mock_model
        
        # System returns True (busy)
        system_busy = MagicMock(return_value=True)
        
        sentinel = AriaWakeSentinel(system_state_provider=system_busy)
        sentinel.model = self.mock_model
        
        # Setup stop to occur quickly
        def stop_after_sleep():
            time.sleep(0.05)
            sentinel.stop()
            
        threading.Thread(target=stop_after_sleep, daemon=True).start()
        
        sentinel.start_background_listening(self.wake_callback)
        
        # Verify predict was never called because system was busy
        self.mock_model.predict.assert_not_called()
        self.assertFalse(self.callback_fired)

if __name__ == "__main__":
    unittest.main()
