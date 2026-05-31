import sys
import os

project_root = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, project_root)

try:
    from skills.gesture_control import GestureController, start_gesture_control, MEDIAPIPE_AVAILABLE
    print("MEDIAPIPE_AVAILABLE:", MEDIAPIPE_AVAILABLE)
    print("Successfully imported GestureController and start_gesture_control!")
except Exception as e:
    print("Failed to import or run gesture control:", e)
    import traceback
    traceback.print_exc()
