import os
import threading
import requests
import cv2
import numpy as np
from PIL import Image
from io import BytesIO

IMAGES_DIR = os.path.join("skills", "assets", "images")
os.makedirs(IMAGES_DIR, exist_ok=True)

class ImageGenerator:
    def __init__(self, aria=None):
        self.aria = aria
        self.pending_uploads = []

    def _sanitize(self, prompt):
        return "".join(
            c if c.isalnum() or c == " " else ""
            for c in prompt
        ).strip().replace(" ", "_").lower()[:50]

    def _local_path(self, prompt):
        return os.path.join(IMAGES_DIR, f"{self._sanitize(prompt)}.png")

    def _generate_from_api(self, prompt):
        print(f"[ImageGen] Calling Pollinations API for: '{prompt}'")
        url = (
            f"https://image.pollinations.ai/prompt/"
            f"{requests.utils.quote(prompt)}"
            f"?width=512&height=512&nologo=true&model=flux"
        )
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                img = Image.open(BytesIO(response.content)).convert("RGB")
                return img
            else:
                print(f"[ImageGen] API error: {response.status_code}")
                return None
        except Exception as e:
            print(f"[ImageGen] API call failed: {repr(e)}")
            return None

    def _show_image_window(self, img_pil, title, on_close=None):
        try:
            img_cv = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
            img_cv = cv2.resize(img_cv, (512, 512))
            window_name = f"ARIA — {title[:40]}"
            cv2.imshow(window_name, img_cv)
            cv2.setWindowProperty(
                window_name,
                cv2.WND_PROP_TOPMOST,
                1
            )
            print(f"[ImageGen] Showing window. Press any key to close.")
            cv2.waitKey(0)
            cv2.destroyWindow(window_name)
        except Exception as e:
            print(f"[ImageGen] Error displaying window: {e}")
        if on_close:
            on_close()

    def generate_or_load(self, prompt):
        local_path = self._local_path(prompt)

        # Load from cache if exists
        if os.path.exists(local_path):
            print(f"[ImageGen] Loading from cache: {local_path}")
            img = Image.open(local_path).convert("RGB")
            threading.Thread(
                target=self._show_image_window,
                args=(img, prompt),
                daemon=True
            ).start()
            return True

        # Generate from API
        if self.aria:
            self.aria._speak(f"Generating image of {prompt}, please wait.")

        img = self._generate_from_api(prompt)
        if img is None:
            if self.aria:
                self.aria._speak("Sorry, image generation failed.")
            return False

        # Save to disk
        try:
            img.save(local_path)
            print(f"[ImageGen] Saved: {local_path}")
            self.pending_uploads.append(local_path)
        except Exception as e:
            print(f"[ImageGen] Failed to save image locally: {e}")

        # Show window
        threading.Thread(
            target=self._show_image_window,
            args=(img, prompt),
            daemon=True
        ).start()

        if self.aria:
            self.aria._speak("Image ready.")
        return True

    def get_pending_uploads(self):
        return self.pending_uploads.copy()

    def mark_uploaded(self, path):
        if path in self.pending_uploads:
            self.pending_uploads.remove(path)
