import subprocess
import time
import os
import sqlite3
from skills.desktop_control_skill import AriaDesktopControlSkill

db_path = "aria_orchestrator.db"

print("[Control] Launching Notepad...")
notepad_proc = subprocess.Popen(["notepad.exe"])

time.sleep(2.5)  # Wait for Notepad to load and focus

try:
    skill = AriaDesktopControlSkill(db_path=db_path)
    
    print("[Control] Focusing Notepad window...")
    success, msg = skill.focus_window("Notepad")
    print(f"  - Focus Window Result: Success={success} | Message={msg}")
    
    # Give the system a brief moment to stabilize focus
    time.sleep(1.0)
    
    print("[Control] Typing text into Notepad...")
    # notepad.exe is in SAFE_TEXT_APPS by default, so it executes immediately
    level, type_success, type_msg = skill.type_text("Hello from ARIA real-world verification!")
    print(f"  - Type Text Result: Level={level} | Success={type_success} | Message={type_msg}")
    
    time.sleep(1.5)
    
    print("[Control] Selecting all text in Notepad...")
    hotkey_level, hotkey_success, hotkey_msg = skill.send_hotkey("ctrl+a")
    print(f"  - Send Hotkey Result: Level={hotkey_level} | Success={hotkey_success} | Message={hotkey_msg}")
    
    time.sleep(1.0)
    
    print("[Control] Reading selected text from Notepad...")
    read_success, selected_text = skill.read_selected_text()
    print(f"  - Read Selection Result: Success={read_success} | Selected Text={repr(selected_text)}")
    
finally:
    print("[Control] Terminating Notepad process...")
    notepad_proc.terminate()
    notepad_proc.wait()
    print("[Control] Done.")
