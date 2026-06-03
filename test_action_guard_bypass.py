import unittest
import sys
import os
from unittest.mock import MagicMock, patch

# Ensure project path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import ARIA

class TestActionGuardBypass(unittest.TestCase):
    def setUp(self):
        # Create an instance of ARIA with mocked subsystems to avoid startup overhead
        self.agent = ARIA()
        self.agent.brain = MagicMock()
        self.agent.brain.last_routing_decision = None
        
        # Patch is_browser_active to return False by default for these tests to prevent test pollution
        patcher = patch('skills.browser_skill.BrowserSkill.is_browser_active', return_value=False)
        self.mock_is_active = patcher.start()
        self.addCleanup(patcher.stop)

    def test_unauthorized_when_no_routing_decision_and_no_keyword(self):
        # Case 1: Query is "Amazon", category is "OPEN", no routing decision
        # "Amazon" does not contain open/launch/start, so it should be unauthorized.
        self.agent.brain.last_routing_decision = None
        self.assertFalse(self.agent._is_action_tag_authorized("OPEN", "Amazon"))

    def test_authorized_by_keyword_even_without_routing_decision(self):
        # Case 2: Query is "Open Amazon", category is "OPEN", no routing decision
        # "open" is in the input, so it should be authorized by keyword check.
        self.agent.brain.last_routing_decision = None
        self.assertTrue(self.agent._is_action_tag_authorized("OPEN", "Open Amazon"))

    def test_authorized_by_high_confidence_intent(self):
        # Case 3: Query is "Show me cricket scores", category is "SEARCH", routing decision is search (0.90)
        # "Show me cricket scores" doesn't have keyword 'search' or 'find', but intent is search with >= 0.8 confidence.
        self.agent.brain.last_routing_decision = {
            "intent": "search",
            "intent_confidence": 0.90
        }
        self.assertTrue(self.agent._is_action_tag_authorized("SEARCH", "Show me cricket scores"))

        # Category OPEN should also be authorized
        self.assertTrue(self.agent._is_action_tag_authorized("OPEN", "Show me cricket scores"))

    def test_blocked_by_low_confidence_intent(self):
        # Case 4: Intent is search but confidence is 0.70 (< 0.8) and query doesn't match keyword
        self.agent.brain.last_routing_decision = {
            "intent": "search",
            "intent_confidence": 0.70
        }
        self.assertFalse(self.agent._is_action_tag_authorized("SEARCH", "Show me cricket scores"))

    def test_blocked_for_critical_actions_even_with_high_confidence_intent(self):
        # Case 5: Critical actions like SHUTDOWN or RESTART must NOT bypass using the intent logic
        self.agent.brain.last_routing_decision = {
            "intent": "search",
            "intent_confidence": 0.95
        }
        # Shutdown is not in "Show me cricket scores", so it should be blocked
        self.assertFalse(self.agent._is_action_tag_authorized("SHUTDOWN", "Show me cricket scores"))
        # Shutdown with "shutdown" in input should be allowed by keyword
        self.assertTrue(self.agent._is_action_tag_authorized("SHUTDOWN", "Please shutdown"))

    @patch('skills.browser_skill.BrowserSkill.is_browser_active', return_value=True)
    def test_authorized_when_browser_active_regardless_of_intent(self, mock_active):
        # Even with low confidence intent, browser actions should be authorized if browser is active
        self.agent.brain.last_routing_decision = {
            "intent": "chat",
            "intent_confidence": 0.20
        }
        self.assertTrue(self.agent._is_action_tag_authorized("CLICK", "some random query"))
        self.assertTrue(self.agent._is_action_tag_authorized("SEARCH", "some query"))

    def test_click_keyword_expansion(self):
        # Click action should be authorized if query contains keywords like "product", "item", "first", etc.
        self.agent.brain.last_routing_decision = None
        self.assertTrue(self.agent._is_action_tag_authorized("CLICK", "Open the product"))
        self.assertTrue(self.agent._is_action_tag_authorized("CLICK", "choose the first result"))
        self.assertTrue(self.agent._is_action_tag_authorized("CLICK", "go to the item"))

if __name__ == "__main__":
    unittest.main()
