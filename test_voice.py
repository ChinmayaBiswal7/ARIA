import unittest

from skills.runtime_capabilities import CAPABILITIES

if not CAPABILITIES.has_voice_synthesis:
    raise unittest.SkipTest("pyttsx3 unavailable; skipping optional voice synthesis test")

import pyttsx3
try:
    engine = pyttsx3.init()
    print("Testing voice...")
    engine.say("Hello, I am verifying my voice modules.")
    engine.runAndWait()
    print("Voice test complete.")
except Exception as e:
    print(f"Voice Error: {e}")
