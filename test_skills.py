import sys
import os

# Ensure skills folder is importable
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from skills.memory_skill import MemorySkill
from skills.context_skill import ContextSkill

def test_memory():
    print("--- Testing Memory Skill ---")
    mem = MemorySkill()
    
    # Test reminders
    print(mem.add_reminder("Revise DBMS", "tomorrow"))
    print(mem.get_pending_reminders())
    print(mem.clear_reminders())
    print(mem.get_pending_reminders())
    
    # Test project paths
    print(mem.save_folder("ml project", r"C:\D FOLDER\Projects\AI"))
    print("Retrieved ML path:", mem.get_folder_path("ml project"))

def test_context():
    print("\n--- Testing PC Context Skill ---")
    ctx = ContextSkill()
    
    print("Battery percent:", ctx.get_battery_percent())
    print("Is charging:", ctx.get_charging_status())
    print("Active window title:", ctx.get_active_window())
    print("Wifi connectivity:", ctx.get_wifi_status())
    print("\nPC Context Summary:\n", ctx.get_context_summary())

if __name__ == "__main__":
    test_memory()
    test_context()
    print("\nAll modular skill tests completed successfully!")
