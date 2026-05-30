import mss
import mss.tools
from PIL import Image

class Vision:
    def __init__(self):
        self.sct = mss.mss()

    def capture_screen(self, monitor_index=1):
        """
        Captures the primary monitor and returns a PIL Image.
        monitor_index=0 is all monitors combined, 1 is primary.
        """
        try:
            monitor = self.sct.monitors[monitor_index]
            sct_img = self.sct.grab(monitor)
            # Convert BGRA → RGB correctly using PIL
            img = Image.frombytes("RGBA", sct_img.size, sct_img.bgra, "raw", "BGRA")
            img = img.convert("RGB")
            return img
        except Exception as e:
            print(f"[Vision] Screen capture error: {e}")
            return None

    def save_screenshot(self, filename=None):
        """Captures and saves a screenshot. Returns filename."""
        import datetime
        if not filename:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{ts}.png"
        try:
            monitor = self.sct.monitors[1]
            sct_img = self.sct.grab(monitor)
            mss.tools.to_png(sct_img.rgb, sct_img.size, output=filename)
            print(f"[Vision] Screenshot saved: {filename}")
            return filename
        except Exception as e:
            print(f"[Vision] Save error: {e}")
            return None
