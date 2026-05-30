import time
import sys
import os

# Ensure project root is in path
sys.path.append(os.getcwd())

from camera import Camera
from vision_learn import VisionLearner

def test_shared_camera():
    print("Initializing Camera (simulating ARIA startup)...")
    cam = Camera()
    
    if not cam.available:
        print("Camera not available on this machine. Skipping physical shared test, validating import/interface compatibility...")
        vl = VisionLearner()
        assert hasattr(vl, 'start_camera')
        print("Interface check passed.")
        return
        
    print("Camera is available. Capturing frame from background stream...")
    frame1 = cam.capture_frame_raw()
    assert frame1 is not None, "Failed to capture raw frame from background camera"
    print(f"Captured background frame: {frame1.shape}")
    
    print("\nInitializing VisionLearner...")
    vl = VisionLearner()
    
    print("\nStarting VisionLearner camera loop with the shared frame provider...")
    # Pass the shared frame provider callback
    success = vl.start_camera(frame_provider=cam.capture_frame_raw)
    assert success, "Failed to start VisionLearner with shared frame provider"
    
    print("Waiting 2 seconds for VisionLearner loop to process shared frames...")
    time.sleep(2.0)
    
    # Verify that background camera is still open and we can read from it at the same time!
    print("Reading from background camera stream while VisionLearner is active...")
    frame2 = cam.capture_frame_raw()
    assert frame2 is not None, "Background camera stream got locked or closed!"
    print(f"Captured background frame while VisionLearner is running: {frame2.shape}")
    
    # Verify VisionLearner has been receiving frames
    with vl._lock:
        latest = vl.current_frame
    assert latest is not None, "VisionLearner did not receive any frames from the provider"
    print(f"VisionLearner latest processed frame: {latest.shape}")
    
    print("\nStopping VisionLearner camera loop...")
    vl.stop_camera()
    time.sleep(1.0)
    
    # Verify background camera is still available and open
    print("Verifying background camera is still active after closing VisionLearner...")
    frame3 = cam.capture_frame_raw()
    assert frame3 is not None, "Background camera got closed during VisionLearner cleanup!"
    print(f"Captured background frame after VisionLearner stopped: {frame3.shape}")
    assert cam.available, "Camera should still be marked as available"
    
    print("\nReleasing Camera...")
    cam.release()
    print("\nAll shared camera tests passed successfully!")

if __name__ == '__main__':
    test_shared_camera()
