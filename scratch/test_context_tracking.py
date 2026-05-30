import sys
import os
import time

# Ensure project path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills.browser_skill import BrowserSkill
from brain import Brain

def test_context_tracking():
    print("=== TEST 1: Generic Search In-Page ===")
    bs = BrowserSkill()
    
    # Launch browser
    success, msg = bs.start_browser()
    print(f"Browser launch: {success} ({msg})")
    assert success
    
    # Get absolute path to mock html file
    curr_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mock_url = "file:///" + os.path.join(curr_dir, "mock_wikipedia.html").replace("\\", "/")
    
    # Navigate
    print(f"Navigating to mock URL: {mock_url}")
    nav_res = bs.navigate(mock_url)
    print(f"Navigation result: {nav_res}")
    
    # Verify inputs are found
    assert len(bs.page_state.get("inputs", [])) > 0
    
    # Perform generic search in-page
    print("Searching in-page for 'Machine Learning'...")
    search_res = bs.search_in_page("Machine Learning")
    print(f"Search in-page result: {search_res}")
    
    # Check that search navigated the page correctly
    time.sleep(1.0)
    current_url = bs.page.url
    print(f"Current URL after search: {current_url}")
    assert "page=machine_learning" in current_url, "Generic search should submit input and navigate page"
    
    print("\n=== TEST 2: Active Browser Context Injection ===")
    brain = Brain()
    # Mock routing decision inside brain
    brain.last_routing_decision = {
        "intent": "followup",
        "intent_confidence": 0.95
    }
    
    prompt = brain._build_system_prompt(user_name="chinmay", user_similarity=0.98, user_confidence="high")
    print("System Prompt snippet including ACTIVE BROWSER CONTEXT:")
    print("-------------------------------------------------------------")
    context_lines = [line for line in prompt.split("\n") if "ACTIVE BROWSER" in line or "Current URL:" in line or "Page Title:" in line or "search_in_page" in line]
    print("\n".join(context_lines))
    print("-------------------------------------------------------------")
    
    assert any("ACTIVE BROWSER CONTEXT" in line for line in prompt.split("\n")), "ACTIVE BROWSER CONTEXT section must be present in prompt"
    assert any("mock_wikipedia.html" in line for line in prompt.split("\n")), "Mock URL must be in prompt"
    assert any("search_in_page" in line for line in prompt.split("\n")), "action history should be visible in prompt"

    print("\n=== TEST 3: Action Authorization Guard ===")
    from main import ARIA
    # Mock main app
    class MockApp(ARIA):
        def __init__(self):
            # Bypass full init to avoid launching camera/audio threads
            self.brain = brain
            
    app = MockApp.__new__(MockApp)
    app.brain = brain
    
    # Test authorization logic when browser active and intent is followup
    auth_search = app._is_action_tag_authorized("SEARCH", "search keyboard in it")
    auth_click = app._is_action_tag_authorized("CLICK", "click it")
    auth_shutdown = app._is_action_tag_authorized("SHUTDOWN", "click it")
    
    print(f"Authorized SEARCH: {auth_search}")
    print(f"Authorized CLICK: {auth_click}")
    print(f"Authorized SHUTDOWN (should be false/blocked): {auth_shutdown}")
    
    assert auth_search == True, "SEARCH should be authorized when browser is active"
    assert auth_click == True, "CLICK should be authorized when browser is active"
    assert auth_shutdown == False, "SHUTDOWN should not be automatically authorized"
    
    # Close browser
    bs.close_browser()
    print("\nAll Site-Aware context tracking tests passed successfully!")

if __name__ == "__main__":
    test_context_tracking()
