"""
web_text_extractor.py — Chrome DOM Text Extraction
====================================================
Reads actual webpage text from Chrome using accessibility/clipboard,
instead of relying on pixel-level vision.
"""

import subprocess
import time

class WebTextExtractor:
    """Extracts text content from Chrome browser using keyboard shortcuts."""

    def extract_chrome_text(self, max_chars=3000):
        """
        Extracts visible text from Chrome by:
        1. Selecting all text (Ctrl+A)
        2. Copying to clipboard (Ctrl+C)
        3. Reading clipboard content
        Returns extracted text or empty string.
        """
        try:
            import pyperclip
            import pyautogui

            # Save current clipboard
            old_clipboard = ""
            try:
                old_clipboard = pyperclip.paste()
            except Exception:
                pass

            # Select all and copy
            pyautogui.hotkey('ctrl', 'a', interval=0.05)
            time.sleep(0.3)
            pyautogui.hotkey('ctrl', 'c', interval=0.05)
            time.sleep(0.3)

            # Click somewhere to deselect
            pyautogui.press('escape')

            # Read clipboard
            page_text = pyperclip.paste()

            # Restore old clipboard
            try:
                if old_clipboard:
                    pyperclip.copy(old_clipboard)
            except Exception:
                pass

            if page_text and len(page_text) > 50:
                # Trim to max_chars
                if len(page_text) > max_chars:
                    page_text = page_text[:max_chars] + "\n...(truncated)"
                print(f"[WebText] Extracted {len(page_text)} chars from Chrome page.")
                return page_text
            else:
                return ""

        except ImportError:
            print("[WebText] pyperclip or pyautogui not installed.")
            return ""
        except Exception as e:
            print(f"[WebText] Chrome text extraction error: {e}")
            return ""

    def is_browser_active(self):
        """Check if Chrome or a browser is the active foreground window."""
        try:
            import pygetwindow as gw
            active = gw.getActiveWindow()
            if active:
                title = active.title.lower()
                return any(b in title for b in ["chrome", "firefox", "edge", "brave", "opera", "safari"])
        except Exception:
            pass
        return False
