import time
import sys
import os

# Ensure project root is in path
sys.path.append(os.getcwd())

from camera import Camera
from skills.gesture_control import start_gesture_control, stop_gesture_control, is_active

def test_custom_gesture():
    print("Initializing Camera (simulating ARIA startup)...")
    cam = Camera()
    
    if not cam.available:
        print("Camera not available on this machine. Skipping physical custom gesture test, validating import/interface compatibility...")
        assert start_gesture_control is not None
        assert stop_gesture_control is not None
        assert not is_active()
        print("Interface check passed.")
        return
        
    print("Camera is active. Starting custom gesture control via shared frame callback...")
    assert not is_active(), "Gesture control should be inactive initially"
    
    msg = start_gesture_control(frame_provider=cam.capture_frame_raw)
    print(f"Start message: {msg}")
    
    time.sleep(1.0)
    print(f"Is gesture active: {is_active()}")
    assert is_active(), "Gesture control failed to start!"
    
    print("Letting it run for 3 seconds...")
    time.sleep(3.0)
    
    print("Stopping gesture control...")
    msg2 = stop_gesture_control()
    print(f"Stop message: {msg2}")
    
    time.sleep(1.0)
    print(f"Is gesture active: {is_active()}")
    assert not is_active(), "Gesture control failed to stop!"
    
    print("Releasing camera...")
    cam.release()
    print("\nAll custom gesture control tests passed successfully under the shared camera stream!")

if __name__ == '__main__':
    test_custom_gesture()
