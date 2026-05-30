import sys
import os
import time
import unittest

# Ensure project path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from skills.runtime_capabilities import CAPABILITIES

if not CAPABILITIES.has_playwright:
    raise unittest.SkipTest("playwright unavailable; skipping optional browser runtime test")

from skills.browser_skill import BrowserSkill

def test_browser_skill():
    print("--- Testing BrowserSkill System ---")
    bs = BrowserSkill()

    # 1. Start browser
    print("Launching browser...")
    success, msg = bs.start_browser()
    print(f"Browser launch result: success={success}, msg='{msg}'")
    assert success, "Browser should start successfully"
    assert bs.page is not None, "Page reference should be set"

    # 2. Navigate to a fast loading page (e.g. Wikipedia main page)
    print("Navigating to Wikipedia...")
    nav_msg = bs.navigate("https://en.wikipedia.org/wiki/Main_Page")
    print(f"Navigation result: '{nav_msg}'")
    assert "Navigated" in nav_msg or "successful" in nav_msg.lower(), "Should report successful navigation"

    # 3. Test scrolling
    print("Scrolling page down...")
    scroll_down_msg = bs.scroll("down")
    print(f"Scroll down result: '{scroll_down_msg}'")
    assert "Scrolled down" in scroll_down_msg

    print("Scrolling page up...")
    scroll_up_msg = bs.scroll("up")
    print(f"Scroll up result: '{scroll_up_msg}'")
    assert "Scrolled up" in scroll_up_msg

    # 4. Test general form filling (Wikipedia Search input)
    print("Testing general form input filling...")
    fill_msg = bs.fill_element("Search Wikipedia", "Artificial Intelligence")
    print(f"Fill element result: '{fill_msg}'")
    assert "Filled" in fill_msg or "Typed" in fill_msg, "Should report successful filling or typing"
    
    # Submit search
    bs.page.keyboard.press("Enter")
    time.sleep(2.0) # wait for page to render

    # 5. Test page summarization
    print("Testing webpage content extraction and summarization...")
    summary_msg = bs.summarize_page(brain=None)
    print(f"Summarize page result (raw snippet): '{summary_msg}'")
    assert "preview" in summary_msg or "text" in summary_msg

    # 6. Test security interception
    print("Testing safety block on 'delete account' click...")
    block_msg = bs.click_element("Delete Account")
    print(f"Safety block result: '{block_msg}'")
    assert "blocked" in block_msg.lower(), "Should block dangerous operations"

    print("Testing safety block on 'place order' click...")
    block_msg2 = bs.click_element("Place Order")
    print(f"Safety block result 2: '{block_msg2}'")
    assert "blocked" in block_msg2.lower(), "Should block checkout/buy operations"

    # 5. Close browser
    print("Closing browser...")
    close_msg = bs.close_browser()
    print(f"Close browser result: '{close_msg}'")
    assert bs.page is None, "Page should be cleared"
    assert bs.browser is None, "Browser should be cleared"

    print("\nAll BrowserSkill tests passed successfully!")

if __name__ == "__main__":
    try:
        test_browser_skill()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nBrowserSkill integration test failed: {e}")
