import sys
import os
import unittest
import time
from unittest.mock import MagicMock

# Ensure project path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from skills.model_runtime_registry import ModelRuntimeRegistry, ModelHealth

class TestModelRuntimeRegistry(unittest.TestCase):
    
    def setUp(self):
        self.registry = ModelRuntimeRegistry()

    def test_default_models_registered(self):
        self.assertIsNotNone(self.registry.get_model("gemini-2.5-flash"))
        self.assertIsNotNone(self.registry.get_model("llama-3.1-8b-instant"))
        self.assertIsNotNone(self.registry.get_model("ollama_local"))

    def test_record_success_updates_model(self):
        m = self.registry.get_model("llama-3.1-8b-instant")
        self.assertEqual(m.status, "HEALTHY")
        
        self.registry.record_success("llama-3.1-8b-instant", 0.5)
        self.assertEqual(m.status, "HEALTHY")
        self.assertEqual(m.failure_count, 0)
        self.assertEqual(m.avg_latency, 0.5)

    def test_record_failure_triggers_cooldown(self):
        m = self.registry.get_model("llama-3.1-8b-instant")
        self.assertEqual(m.status, "HEALTHY")
        
        self.registry.record_failure("llama-3.1-8b-instant", is_quota_error=False)
        self.assertEqual(m.status, "COOLDOWN")
        self.assertEqual(m.failure_count, 1)
        self.assertTrue(m.cooldown_until > time.time())

    def test_shared_gemini_cooldown_on_quota_error(self):
        gemini_flash = self.registry.get_model("gemini-2.5-flash")
        gemini_2_0 = self.registry.get_model("gemini-2.0-flash")
        
        self.assertEqual(gemini_flash.status, "HEALTHY")
        self.assertEqual(gemini_2_0.status, "HEALTHY")
        
        # Trigger 429 quota error on gemini-2.5-flash
        self.registry.record_failure("gemini-2.5-flash", is_quota_error=True)
        
        # Both models should be cooldowned
        self.assertEqual(gemini_flash.status, "COOLDOWN")
        self.assertEqual(gemini_2_0.status, "COOLDOWN")

    def test_shared_groq_cooldown_on_quota_error(self):
        llama_instant = self.registry.get_model("llama-3.1-8b-instant")
        llama_versatile = self.registry.get_model("llama-3.3-70b-versatile")
        gemma = self.registry.get_model("gemma2-9b-it")
        
        self.assertEqual(llama_instant.status, "HEALTHY")
        self.assertEqual(llama_versatile.status, "HEALTHY")
        self.assertEqual(gemma.status, "HEALTHY")
        
        # Trigger 429 quota error on llama-3.1-8b-instant
        self.registry.record_failure("llama-3.1-8b-instant", is_quota_error=True)
        
        # All Groq models should be cooldowned together
        self.assertEqual(llama_instant.status, "COOLDOWN")
        self.assertEqual(llama_versatile.status, "COOLDOWN")
        self.assertEqual(gemma.status, "COOLDOWN")

    def test_non_quota_failure_does_not_cooldown_others(self):
        llama_instant = self.registry.get_model("llama-3.1-8b-instant")
        llama_versatile = self.registry.get_model("llama-3.3-70b-versatile")
        
        self.assertEqual(llama_instant.status, "HEALTHY")
        self.assertEqual(llama_versatile.status, "HEALTHY")
        
        # Trigger non-quota failure
        self.registry.record_failure("llama-3.1-8b-instant", is_quota_error=False)
        
        # Only failed model is cooldowned
        self.assertEqual(llama_instant.status, "COOLDOWN")
        self.assertEqual(llama_versatile.status, "HEALTHY")

if __name__ == "__main__":
    unittest.main()
