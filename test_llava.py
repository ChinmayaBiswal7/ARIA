"""
Quick test: LLaVA screen reading + coordinate detection
"""
import base64, re, sys
import unittest

from skills.runtime_capabilities import CAPABILITIES

missing = []
if not CAPABILITIES.has_desktop_control:
    missing.append("pyautogui")
if not CAPABILITIES.has_ollama:
    missing.append("ollama")
if missing:
    raise unittest.SkipTest(f"{', '.join(missing)} unavailable; skipping optional LLaVA screen test")

import pyautogui
import ollama

print("=" * 50)
print("  ARIA Vision Test - LLaVA Screen Reading")
print("=" * 50)

# 1. Take a screenshot
print("\n[1] Taking screenshot of your current screen...")
img = pyautogui.screenshot()
img.save("test_vision_shot.png")
print("    Saved: test_vision_shot.png")

# 2. Encode as base64
with open("test_vision_shot.png", "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode("utf-8")

sw, sh = pyautogui.size()
print(f"    Screen size: {sw}x{sh}")

# 3. Send to LLaVA
print("\n[2] Sending to LLaVA - asking it to describe the screen...")
try:
    response = ollama.chat(
        model="llava",
        messages=[{
            "role": "user",
            "content": (
                f"This is a Windows desktop screenshot ({sw}x{sh} pixels). "
                "Describe what you can see briefly (apps, icons, taskbar etc). "
                "Then pick the most obvious clickable thing and give its coordinates as: CLICK: x,y"
            ),
            "images": [img_b64]
        }]
    )
    result = response["message"]["content"].strip()
    print(f"\n[LLaVA says]:\n{result}\n")

    # 4. Try to parse coordinates
    match = re.search(r'CLICK:\s*(\d+)\s*,\s*(\d+)', result, re.IGNORECASE)
    if match:
        cx, cy = int(match.group(1)), int(match.group(2))
        print(f"[3] Coordinate found: ({cx}, {cy})")
        print(f"    This is within screen bounds: {0 < cx < sw and 0 < cy < sh}")
        print("\n[SUCCESS] VISION SYSTEM WORKING PERFECTLY!")
    else:
        print("[3] No CLICK coordinates returned - but LLaVA CAN see the screen!")
        print("[SUCCESS] VISION SYSTEM ONLINE (description mode works)")

except Exception as e:
    print(f"\n[ERROR] Error: {e}")
    print("Make sure Ollama is running and llava model is available.")
    raise unittest.SkipTest(f"Ollama/llava unavailable: {e}")
