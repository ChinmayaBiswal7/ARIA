import sys
import os
import unittest
import time
from unittest.mock import MagicMock, patch

# Ensure project path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from skills.runtime_capabilities import CAPABILITIES

if not CAPABILITIES.has_playwright:
    raise unittest.SkipTest("playwright unavailable; skipping optional DOM/browser memory tests")

from skills.browser_skill import BrowserSkill

class TestDOMAwarenessMemory(unittest.TestCase):
    
    def setUp(self):
        # Reset the thread local instance to ensure a clean instance for every test
        if hasattr(BrowserSkill._thread_local, "instance"):
            delattr(BrowserSkill._thread_local, "instance")
        self.bs = BrowserSkill()
        print("self.bs instance id:", id(self.bs))
        self.bs.browser = MagicMock()
        self.bs.context = MagicMock()
        self.bs.page = MagicMock()
        self.bs.page.is_closed = MagicMock(return_value=False)
        
        # Clear fields
        self.bs.page_state = {}
        self.bs.action_history = []

    def test_update_page_state_mock(self):
        # Mock evaluate return value representing browser extraction
        mock_raw_state = {
            "url": "https://www.example.com",
            "title": "Example Domain",
            "scroll_y": 100,
            "viewport_height": 800,
            "document_height": 1600,
            "inputs": [
                {
                    "aria_id": "input_0",
                    "role": "text",
                    "text": "",
                    "placeholder": "search text",
                    "bbox": {"x": 10, "y": 20, "width": 100, "height": 30},
                    "is_visible_in_viewport": True
                }
            ],
            "buttons": [
                {
                    "aria_id": "button_0",
                    "role": "button",
                    "text": "Submit",
                    "bbox": {"x": 120, "y": 20, "width": 50, "height": 30},
                    "is_visible_in_viewport": True
                }
            ],
            "links": [
                {
                    "aria_id": "link_0",
                    "role": "link",
                    "text": "More info",
                    "href": "/more-info",
                    "bbox": {"x": 10, "y": 60, "width": 80, "height": 20},
                    "is_visible_in_viewport": True
                },
                {
                    "aria_id": "link_1",
                    "role": "link",
                    "text": "Contact Us",
                    "href": "/contact",
                    "bbox": {"x": 10, "y": 90, "width": 80, "height": 20},
                    "is_visible_in_viewport": False
                }
            ],
            "cards": []
        }
        
        self.bs.page.evaluate = MagicMock(return_value=mock_raw_state)
        self.bs.is_browser_active = MagicMock(return_value=True)
        
        print("is_browser_active returns:", self.bs.is_browser_active())
        self.bs._update_page_state()
        print("page_state after update:", self.bs.page_state)
        
        # Verify page state was parsed and set correctly
        self.assertEqual(self.bs.page_state.get("url"), "https://www.example.com")
        self.assertEqual(len(self.bs.page_state["inputs"]), 1)
        self.assertEqual(len(self.bs.page_state["links"]), 2)
        self.assertEqual(self.bs.page_state["scroll_y"], 100)

    def test_compute_page_fingerprint(self):
        # Empty state should be None
        self.bs.page_state = {}
        self.assertIsNone(self.bs._compute_page_fingerprint())
        
        # Setup initial state
        self.bs.page_state = {
            "url": "https://www.example.com",
            "inputs": [{"aria_id": "input_0", "role": "text", "text": "value"}],
            "buttons": [], "links": [], "cards": []
        }
        fp1 = self.bs._compute_page_fingerprint()
        self.assertIsNotNone(fp1)
        
        # Same state should yield identical hash
        fp2 = self.bs._compute_page_fingerprint()
        self.assertEqual(fp1, fp2)
        
        # Modified state (e.g. text changed) should yield a different hash
        self.bs.page_state["inputs"][0]["text"] = "different value"
        fp3 = self.bs._compute_page_fingerprint()
        self.assertNotEqual(fp1, fp3)

    def test_resolve_semantic_target(self):
        self.bs.page_state = {
            "url": "https://www.example.com",
            "inputs": [
                {"aria_id": "input_0", "role": "text", "text": "", "placeholder": "Search site", "is_visible_in_viewport": True}
            ],
            "buttons": [
                {"aria_id": "button_0", "role": "button", "text": "Add to Cart", "is_visible_in_viewport": True}
            ],
            "links": [
                {"aria_id": "link_0", "role": "link", "text": "Contact", "href": "/contact", "is_visible_in_viewport": True},
                {"aria_id": "link_1", "role": "link", "text": "Terms", "href": "/terms", "is_visible_in_viewport": True}
            ],
            "cards": []
        }
        # Mock _update_page_state to not reset the manually built state
        self.bs._update_page_state = MagicMock()
        
        # 1. Test query mapping on placeholders
        res = self.bs.resolve_semantic_target("Search site")
        self.assertEqual(res, "input_0")
        
        # 2. Test substring query matching
        res = self.bs.resolve_semantic_target("Cart")
        self.assertEqual(res, "button_0")
        
        # 3. Test relative positioning matching (visible in viewport filter)
        res = self.bs.resolve_semantic_target("second link")
        self.assertEqual(res, "link_1")

    def test_record_action_and_no_op_detection(self):
        # Mock DOM state evaluations
        state_1 = {
            "url": "https://www.example.com",
            "inputs": [], "buttons": [{"aria_id": "button_0", "role": "button", "text": "Click me"}], "links": [], "cards": []
        }
        # For the no-op check, state doesn't change
        self.bs.page_state = state_1
        self.bs._update_page_state = MagicMock()
        
        # Mock _compute_page_fingerprint to return same hash
        self.bs._compute_page_fingerprint = MagicMock(return_value="samehash")
        
        print("Fingerprint returns:", self.bs._compute_page_fingerprint())
        is_no_op = self.bs.record_action("click", "button_0")
        print("is_no_op returned:", is_no_op)
        
        # Verified as no-op because fingerprints before and after were identical
        self.assertTrue(is_no_op)
        self.assertEqual(len(self.bs.action_history), 1)
        self.assertTrue(self.bs.action_history[0]["is_no_op"])

    def test_click_aria_id(self):
        self.bs.page_state = {
            "url": "https://www.example.com",
            "buttons": [
                {
                    "aria_id": "button_0",
                    "role": "button",
                    "text": "Submit",
                    "bbox": {"x": 100, "y": 200, "width": 50, "height": 30},
                    "is_visible_in_viewport": True
                }
            ]
        }
        
        # Mock recording action
        self.bs.record_action = MagicMock(return_value=False)
        self.bs._ensure_browser = MagicMock()
        
        # Trigger coordinate click via aria_id
        res = self.bs.click_aria_id("button_0")
        
        # Mouse should click the center of the bounding box:
        # center x = 100 + 50//2 = 125
        # center y = 200 + 30//2 = 215
        self.bs.page.mouse.click.assert_called_once_with(125, 215)
        self.assertEqual(res, "Clicked element button_0.")

if __name__ == "__main__":
    unittest.main()
