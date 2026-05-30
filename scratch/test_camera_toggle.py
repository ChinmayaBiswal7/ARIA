import time
from camera import Camera

def test_camera_toggle():
    print("Initializing camera...")
    cam = Camera()
    
    print(f"Camera available initially: {cam.available}")
    if not cam.available:
        print("Camera not available on this machine, skipping physical tests but validating method presence...")
        assert hasattr(cam, 'release')
        assert hasattr(cam, 'reacquire')
        print("Methods are present.")
        return
        
    print("Capturing initial frame...")
    img = cam.capture_image()
    print(f"Captured image: {img}")
    assert img is not None, "Failed to capture initial image"
    
    print("Releasing camera for AirTouch...")
    cam.release()
    print(f"Camera available after release: {cam.available}")
    assert not cam.available, "Camera should not be available after release"
    
    print("Capturing frame while released (should be None)...")
    img2 = cam.capture_image()
    print(f"Captured image: {img2}")
    assert img2 is None, "Should not be able to capture image when released"
    
    print("Re-acquiring camera...")
    acquired = cam.reacquire()
    print(f"Re-acquire result: {acquired}, cam.available: {cam.available}")
    assert acquired, "Failed to re-acquire camera"
    assert cam.available, "Camera should be available after re-acquiring"
    
    print("Capturing frame after re-acquisition...")
    img3 = cam.capture_image()
    print(f"Captured image: {img3}")
    assert img3 is not None, "Failed to capture image after re-acquisition"
    
    print("Releasing final camera...")
    cam.release()
    print("All tests passed successfully!")

if __name__ == '__main__':
    test_camera_toggle()
