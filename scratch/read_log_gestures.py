import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

log_path = r"C:\Users\KIIT\.gemini\antigravity\brain\0650d426-80f2-40eb-a1e0-5b9edd420919\.system_generated\logs\transcript.jsonl"
if os.path.exists(log_path):
    print("Searching for specific gesture implementations...")
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                data = json.loads(line)
                content = data.get("content", "")
                if "def _check_" in content or "gesture_control.py" in content or "class GestureController" in content:
                    for keyword in ["volume", "right_click", "drag", "double_click"]:
                        if keyword in content:
                            print(f"\n--- Found {keyword} in step {data.get('step_index')} ---")
                            # print the paragraph or line containing keyword
                            lines = content.split("\n")
                            for i, l in enumerate(lines):
                                if keyword in l:
                                    start = max(0, i-5)
                                    end = min(len(lines), i+15)
                                    print(f"Context (lines {start}-{end}):")
                                    print("\n".join(lines[start:end]))
                                    print("-" * 40)
                                    break
            except Exception as e:
                pass
else:
    print("Log file not found.")
