"""
Verification for ARIA runtime capability health and graceful degradation.
"""

import os
import sys
import unittest
from unittest.mock import PropertyMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from skills.runtime_capabilities import (
    AVAILABLE,
    DEGRADED,
    HEADLESS_COGNITION,
    RuntimeCapabilities,
    UNAVAILABLE,
)


class TestRuntimeCapabilities(unittest.TestCase):
    def test_capability_checks_are_cached(self):
        caps = RuntimeCapabilities()
        with patch("importlib.util.find_spec", return_value=None) as find_spec:
            self.assertFalse(caps.has_playwright)
            self.assertFalse(caps.has_playwright)

        find_spec.assert_called_once()

    def test_health_snapshot_contains_confidence_and_recovery_policy(self):
        caps = RuntimeCapabilities()
        health = caps.health_snapshot()

        self.assertIn("browser_runtime", health)
        browser = health["browser_runtime"]
        self.assertIn(browser["status"], {AVAILABLE, DEGRADED, UNAVAILABLE})
        self.assertGreaterEqual(browser["confidence"], 0.0)
        self.assertLessEqual(browser["confidence"], 1.0)
        self.assertIn("recovery_policy", browser)
        self.assertIn("action", browser["recovery_policy"])

    def test_degraded_vision_when_numpy_available_but_cv2_missing(self):
        caps = RuntimeCapabilities()
        with patch.object(RuntimeCapabilities, "has_cv2", new_callable=PropertyMock, return_value=False), \
             patch.object(RuntimeCapabilities, "has_numpy", new_callable=PropertyMock, return_value=True):
            health = caps.health("vision_runtime")

        self.assertEqual(health.status, DEGRADED)
        self.assertEqual(health.confidence, 0.41)
        self.assertEqual(health.missing_dependencies, ["cv2"])

    def test_cognition_context_includes_health_confidence(self):
        caps = RuntimeCapabilities()
        with patch.object(RuntimeCapabilities, "has_playwright", new_callable=PropertyMock, return_value=False), \
             patch.object(RuntimeCapabilities, "has_desktop_control", new_callable=PropertyMock, return_value=False), \
             patch.object(RuntimeCapabilities, "has_audio", new_callable=PropertyMock, return_value=False), \
             patch.object(RuntimeCapabilities, "has_numpy", new_callable=PropertyMock, return_value=True):
            context = caps.cognition_context()

        self.assertIn(HEADLESS_COGNITION, context)
        self.assertIn("browser_runtime", context)
        self.assertIn("0.05", context)

    def test_recovery_policy_contract(self):
        caps = RuntimeCapabilities()
        policies = caps.recovery_policies()

        self.assertEqual(policies["browser_runtime"]["action"], "retry_browser_init")
        self.assertEqual(policies["browser_runtime"]["retry_after_seconds"], 30)
        self.assertEqual(policies["browser_runtime"]["fallback_mode"], HEADLESS_COGNITION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
