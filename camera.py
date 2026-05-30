import cv2
import threading
from PIL import Image

class Camera:
    def __init__(self):
        self.cap = None
        self.available = False
        self._lock = threading.Lock()
        self._try_open()

    def _try_open(self, index=0):
        """Try to open webcam at given index."""
        with self._lock:
            try:
                cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)  # CAP_DSHOW faster on Windows
                if cap.isOpened():
                    # Verify we can actually read a frame
                    ret, _ = cap.read()
                    if ret:
                        self.cap = cap
                        self.available = True
                        # Set resolution for speed
                        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                        print(f"[Camera] Webcam opened at index {index}.")
                        return
                    else:
                        cap.release()
                # Try index 1 as fallback
                if index == 0:
                    # Release lock temporarily before recursive call
                    pass
            except Exception as e:
                print(f"[Camera] Could not open webcam: {e}")
                self.available = False
        
        # Recursive call outside the lock to avoid deadlock
        if index == 0:
            self._try_open(index=1)

    def capture_image(self):
        """Captures a single frame from the webcam and returns a PIL Image."""
        if not self.available or not self.cap:
            return None

        with self._lock:
            try:
                ret, frame = self.cap.read()
                if not ret:
                    print("[Camera] Failed to read frame.")
                    return None

                # Convert BGR to RGB and return as PIL Image
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                return Image.fromarray(rgb)
            except Exception as e:
                print(f"[Camera] Capture error: {e}")
                return None

    def capture_frame_raw(self):
        """
        Captures a single frame and returns a raw BGR numpy array.
        Used by gesture_control and other cv2-based consumers so they can
        share this camera without opening a second VideoCapture.
        Returns None if the camera is unavailable.
        """
        if not self.available or not self.cap:
            return None
        with self._lock:
            try:
                ret, frame = self.cap.read()
                if not ret:
                    return None
                return frame          # BGR ndarray — caller converts as needed
            except Exception as e:
                print(f"[Camera] Raw capture error: {e}")
                return None

    def release(self):
        """Releases the webcam resource."""
        with self._lock:
            if self.cap and self.available:
                try:
                    self.cap.release()
                    self.available = False
                    print("[Camera] Webcam released.")
                except Exception as e:
                    print(f"[Camera] Error releasing: {e}")

    def reacquire(self):
        """Re-acquires the webcam if it was released."""
        with self._lock:
            if self.available and self.cap:
                return True
        print("[Camera] Re-acquiring webcam...")
        self._try_open()
        return self.available
