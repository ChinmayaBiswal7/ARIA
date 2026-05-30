import sys
import os
import time

# Ensure project path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from skills.agent_planner import AgentPlanner
from brain import Brain

def test_agent_planner():
    print("--- Testing AgentPlanner (Autonomous Task Planner) ---")
    
    # Initialize the brain and planner
    brain = Brain()
    planner = AgentPlanner(brain)
    
    # Simple speak callback recorder
    spoken_messages = []
    def dummy_speak(msg):
        print(f"[Speech Callback Output] ARIA: {msg}")
        spoken_messages.append(msg)
    
    # Path inside scratch space (no spaces in path name)
    html_path = r"C:\Users\KIIT\.gemini\antigravity\scratch\mock_wikipedia.html"
    file_url = f"file:///{html_path.replace(os.sep, '/')}"
    
    goal = f"Go to local website {file_url}, search for 'machine learning', and summarize the result"
    print(f"Goal: '{goal}'")
    
    # Run the autonomous planner task
    print("\nStarting execution loop...")
    result = planner.run_task(goal, speak_callback=dummy_speak)
    print(f"\nExecution result: '{result}'")
    
    # Validations
    assert len(spoken_messages) > 0, "Agent should have spoken during execution"
    assert "completed" in result.lower() or "successful" in result.lower(), "Task should complete successfully"
    
    # Cleanup browser
    from skills.browser_skill import BrowserSkill
    BrowserSkill().close_browser()
    print("\nAgentPlanner test passed successfully!")

if __name__ == "__main__":
    try:
        test_agent_planner()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nAgentPlanner test failed: {e}")
        # Make sure to close browser on failure too
        try:
            from skills.browser_skill import BrowserSkill
            BrowserSkill().close_browser()
        except:
            pass
