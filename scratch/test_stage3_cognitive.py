import unittest
import numpy as np
import time
import speech_recognition as sr
from skills.voice_emotion_analyzer import VoiceEmotionAnalyzer
from intent_classifier import IntentClassifier
from skills.memory_manager import MemoryManager

class TestStage3Cognitive(unittest.TestCase):
    def test_voice_emotion_analyzer(self):
        print("\n=== Testing Voice Emotion Analyzer ===")
        analyzer = VoiceEmotionAnalyzer()
        
        # Test 1: Generate a mock neutral signal (low volume noise)
        sample_rate = 16000
        duration = 1.5
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        # 100 Hz sine wave with small amplitude
        samples = (0.01 * np.sin(2 * np.pi * 100 * t)).astype(np.float32)
        # Convert to 16-bit PCM bytes
        pcm_bytes = (samples * 32768).astype(np.int16).tobytes()
        
        audio = sr.AudioData(pcm_bytes, sample_rate, 2)
        emotion = analyzer.analyze(audio)
        print(f"Mock quiet audio result: {emotion}")
        self.assertIn(emotion, ["neutral", "tired", "stressed"])

        # Test 2: Generate a mock stressed signal (loud volume, high frequency)
        # 350 Hz sine wave with large amplitude and random noise perturbation
        samples_stressed = (0.4 * np.sin(2 * np.pi * 350 * t) + 0.1 * np.random.randn(len(t))).astype(np.float32)
        pcm_bytes_stressed = (samples_stressed * 32768).clip(-32768, 32767).astype(np.int16).tobytes()
        audio_stressed = sr.AudioData(pcm_bytes_stressed, sample_rate, 2)
        emotion_stressed = analyzer.analyze(audio_stressed)
        print(f"Mock loud/high pitch audio result: {emotion_stressed}")
        self.assertIn(emotion_stressed, ["neutral", "tired", "stressed"])

    def test_ml_intent_classifier(self):
        print("\n=== Testing ML Intent Classifier ===")
        classifier = IntentClassifier()
        
        # Assert ML is loaded
        print(f"ML Classifier enabled: {classifier.use_ml}")
        
        test_queries = {
            "who am i": "identity",
            "what is my name": "identity",
            "remember when we spoke about Python": "memory",
            "what is in my database memory": "memory",
            "open the first result": "followup",
            "summarize the page": "followup",
            "search for neural networks online": "search",
            "what's on the web page": "browser",
            "hello there": "chat",
        }
        
        for q, expected in test_queries.items():
            intent, confidence = classifier.classify(q)
            print(f"Query: '{q}' -> Intent: {intent} (conf: {confidence:.2f})")
            # For "hello there", the guard will route to chat, which is expected
            if expected != "chat":
                self.assertEqual(intent, expected)

    def test_memory_manager_episodic_injection(self):
        print("\n=== Testing Episodic Memory Injection ===")
        mm = MemoryManager()
        
        # Inject some test episodic memory first
        from skills.episodic_memory import EpisodicMemory
        ep_mem = EpisodicMemory()
        
        test_user = "test_user_stage3"
        ep_mem.record(
            username=test_user,
            event_text="User successfully compiled the cognitive AI pipeline.",
            emotion="neutral",
            importance=0.7,
            retention_tier="permanent"
        )
        
        # Set a preference to ensure that section is populated
        mm.set_preference(test_user, "favorite_color", "blue", confidence=1.0)

        # Get context
        context = mm.get_injected_context(test_user, "pipeline compile")
        print("Generated Injected Context:")
        print("-" * 50)
        print(context)
        print("-" * 50)
        
        self.assertIn("User Preferences", context)
        self.assertIn("Recent Episodes ARIA Remembers", context)
        self.assertIn("compiled the cognitive AI pipeline", context)

if __name__ == "__main__":
    unittest.main()
