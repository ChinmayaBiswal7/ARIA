import sys
import os
import unittest
import time
from unittest.mock import MagicMock, patch

# Ensure project path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from skills.runtime_capabilities import CAPABILITIES

missing = []
if not (CAPABILITIES.has_cv2 and CAPABILITIES.has_numpy):
    missing.append("cv2/numpy")
if not CAPABILITIES.has_playwright:
    missing.append("playwright")
if missing:
    raise unittest.SkipTest(f"{', '.join(missing)} unavailable; skipping optional unified browser tests")

from main import ARIA
from skills.browser_skill import BrowserSkill

class TestUnifiedBrowserSession(unittest.TestCase):
    
    def setUp(self):
        # Create ARIA instance without calling initialize()
        self.aria = ARIA()
        self.aria.speech_queue = MagicMock()
        self.aria._speak = MagicMock()
        self.aria.brain = MagicMock()
        
        # Reset BrowserSkill singleton instance mock attributes
        self.bs = BrowserSkill()
        self.bs.browser = None
        self.bs.context = None
        self.bs.page = None
        self.bs.page_state = {}
        self.bs.action_history = []
        
        # Restore real methods that earlier test files may have monkey-patched on the singleton
        for attr in ('is_browser_active',):
            if attr in self.bs.__dict__:
                del self.bs.__dict__[attr]
        
        # Mock actual methods on BrowserSkill instance to prevent actual browser creation
        self.bs.start_browser = MagicMock(return_value=(True, "Opened browser."))
        self.bs.close_browser = MagicMock(return_value="Closed browser.")
        self.bs.navigate = MagicMock(return_value="Navigated.")
        self.bs.search_google = MagicMock(return_value=(True, "Searched Google."))
        self.bs.click_first_result = MagicMock(return_value="Clicked first result.")
        self.bs.click_element = MagicMock(return_value="Clicked element.")
        
    def test_browser_active_state_checking(self):
        # Setup mock active page/context/browser
        self.bs.browser = MagicMock()
        self.bs.context = MagicMock()
        self.bs.page = MagicMock()
        self.bs.page.is_closed = MagicMock(return_value=False)
        
        # Test when page is active and not closed (use the real class implementation)
        # Note: self.bs.is_browser_active is not mocked, so we test the actual logic
        self.assertTrue(self.bs.is_browser_active())
        
        # Test when page is closed
        self.bs.page.is_closed.return_value = True
        self.assertFalse(self.bs.is_browser_active())

        # Test when browser is None
        self.bs.browser = None
        self.assertFalse(self.bs.is_browser_active())

    def test_classify_intent_before_chat(self):
        # Mock think_raw to return browser_search for info query
        self.aria.brain.think_raw.return_value = "browser_search"
        
        # Simple informational searches should be classified as 'browser_search'
        intent, query = self.aria._classify_intent_before_chat("search Google for IPL score today")
        self.assertEqual(intent, "browser_search")
        self.assertEqual(query, "IPL score today")

        intent, query = self.aria._classify_intent_before_chat("IPL match stats")
        self.assertEqual(intent, "browser_search")

        # Interactive/automation tasks should bypass browser_search and return 'other' without querying LLM
        intent, query = self.aria._classify_intent_before_chat("buy headphones on Amazon")
        self.assertEqual(intent, "other")
        self.assertIsNone(query)

        intent, query = self.aria._classify_intent_before_chat("click on search box")
        self.assertEqual(intent, "other")

        intent, query = self.aria._classify_intent_before_chat("play video on YouTube")
        self.assertEqual(intent, "other")

    def test_watchdog_and_stale_session_handling(self):
        # Mock is_browser_active directly on the instance for this test
        self.bs.is_browser_active = MagicMock(return_value=True)
        
        # Enable automation mode
        self.aria.automation_mode = True
        self.aria.last_automation_action_time = time.time()
        
        # Case 1: Browser is active and time is within 60s -> should stay True
        self.aria._handle_input_impl("stop") # stop is a quick command that returns early but checks watchdog first
        self.assertTrue(self.aria.automation_mode)
        
        # Case 2: Browser is active but last action was > 180s ago -> watchdog should close browser and reset mode
        self.aria.conversation_session.is_active = MagicMock(return_value=False)
        self.aria.last_automation_action_time = time.time() - 185.0
        self.aria._handle_input_impl("stop")
        self.assertFalse(self.aria.automation_mode)
        self.bs.close_browser.assert_called_once()
        
        # Reset mocks
        self.bs.close_browser.reset_mock()
        self.aria.automation_mode = True
        self.aria.last_automation_action_time = time.time()
        
        # Case 3: Browser was closed manually (not active) -> should reset mode
        self.bs.is_browser_active.return_value = False
        self.aria._handle_input_impl("stop")
        self.assertFalse(self.aria.automation_mode)
        self.bs.close_browser.assert_not_called()

    @patch('webbrowser.open')
    def test_routing_rules_and_status_speech(self, mock_web_open):
        self.aria.brain.think_raw.return_value = "browser_search"
        self.aria.brain.think.return_value = "Page Summary"
        
        # Test Case 1: Simple search when automation mode is OFF -> webbrowser.open (non-automated)
        self.bs.is_browser_active = MagicMock(return_value=False)
        self.aria.automation_mode = False
        self.aria._handle_input("search Google for standard model")
        mock_web_open.assert_called_once()
        self.bs.search_google.assert_not_called()
        
        # Reset mocks
        mock_web_open.reset_mock()
        self.bs.search_google.reset_mock()
        
        # Test Case 2: Simple search when automation mode is ON -> Playwright search
        self.bs.is_browser_active = MagicMock(return_value=True)
        self.aria.automation_mode = True
        self.aria.last_automation_action_time = time.time()
        self.aria._handle_input("search Google for standard model")
        mock_web_open.assert_not_called()
        self.bs.search_google.assert_called_once_with("standard model")
        self.aria._speak.assert_any_call("Searching Google for standard model.")

    def test_click_first_result_phrases(self):
        phrases = [
            "click first result",
            "open first result",
            "select first product",
            "click the first link",
            "play first video",
            "click number one",
            "first item"
        ]

        for phrase in phrases:
            self.bs.click_first_result.reset_mock()
            self.aria.automation_mode = False
            self.aria.last_automation_action_time = 0.0
            
            self.aria._handle_input(phrase)
            
            # Should set automation mode, update time, and trigger click_first_result
            self.assertTrue(self.aria.automation_mode)
            self.assertGreater(self.aria.last_automation_action_time, 0.0)
            self.bs.click_first_result.assert_called_once()
            self.aria._speak.assert_any_call("Clicking the first result.")

if __name__ == "__main__":
    unittest.main()
