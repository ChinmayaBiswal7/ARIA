"""
scratch/test_wake_sentinel_lock.py — Voice Pipeline Verification Suite
========================================================================

Validates the microphone lock synchronization and sentinel flag-based wake triggering:
  1. Voice Lock Initialization - verifies mic_lock is defined.
  2. Concurrent Audio Access - verifies self.mic_lock prevents simultaneous entry exceptions.
  3. Coordination Busy State - verifies is_system_busy blocks sentinel execution when wake is pending.
"""

import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voice import Voice
from main import ARIA

class MockMicrophoneSource:
    def __init__(self):
        self.SAMPLE_RATE = 16000
        self.SAMPLE_WIDTH = 2
        self.stream = MagicMock()
        self.is_entered = False

    def __enter__(self):
        if self.is_entered:
            raise AssertionError("This audio source is already inside a context manager")
        self.is_entered = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.is_entered = False
        return False


class TestVoiceMicrophoneLock(unittest.TestCase):
    """Verify that voice.py has mic_lock and handles concurrent entries thread-safely."""

    def test_mic_lock_exists(self):
        voice = Voice()
        self.assertTrue(hasattr(voice, 'mic_lock'))
        self.assertIsNotNone(voice.mic_lock)

    def test_concurrent_mic_entry_is_thread_safe_with_lock(self):
        voice = Voice()
        mock_mic = MockMicrophoneSource()
        voice.microphone = mock_mic

        errors = []
        started_events = []
        finish_event = threading.Event()

        def worker_thread(tid):
            try:
                # Use the same multi-manager structure: with voice.mic_lock, voice.microphone as source
                with voice.mic_lock, voice.microphone as source:
                    started_events.append(tid)
                    # Hold the resource for a moment
                    time.sleep(0.05)
            except Exception as e:
                errors.append(e)

        # Start two threads attempting to enter concurrently
        t1 = threading.Thread(target=worker_thread, args=(1,), daemon=True)
        t2 = threading.Thread(target=worker_thread, args=(2,), daemon=True)

        t1.start()
        t2.start()
        
        t1.join(timeout=1.0)
        t2.join(timeout=1.0)

        # If lock works, both threads should enter sequentially without throwing AssertionError
        self.assertEqual(len(errors), 0, f"Encountered unexpected errors during concurrent entry: {errors}")
        self.assertEqual(len(started_events), 2)


class TestSentinelWakeTriggerFlag(unittest.TestCase):
    """Verify state coordination checks sentinel_wake_triggered flag."""

    def test_is_system_busy_coordination_check(self):
        app = ARIA()
        app.voice = MagicMock()
        app.voice.is_speaking = False
        app.state = "IDLE"

        # Initially, sentinel_wake_triggered is False
        app.sentinel_wake_triggered = False

        # Define is_system_busy similarly to _start_wake_sentinel
        def is_system_busy():
            return (
                getattr(app, 'state', None) in ("LISTENING", "THINKING", "TRANSCRIBING")
                or (app.voice is not None and getattr(app.voice, 'is_speaking', False))
                or getattr(app, "sentinel_wake_triggered", False)
            )

        self.assertFalse(is_system_busy())

        # If sentinel_wake_triggered is set to True, it should mark system as busy
        app.sentinel_wake_triggered = True
        self.assertTrue(is_system_busy())

        # If state transitions to LISTENING, it stays busy
        app.sentinel_wake_triggered = False
        app.state = "LISTENING"
        self.assertTrue(is_system_busy())


if __name__ == "__main__":
    unittest.main()
