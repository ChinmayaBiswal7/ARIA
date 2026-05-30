"""
screen_control.py — ARIA's Screen Control & Computer Use Module
================================================================
Gives ARIA the ability to:
  - See the screen (screenshots)
  - Click, type, drag using screen coordinates
  - Find and focus application windows
  - Navigate File Explorer to open/select files
  - Send files via WhatsApp Web
  - Execute multi-step automated workflows
"""

import os
import time
import subprocess
import webbrowser
import pyautogui
import pyperclip
import urllib.parse
from pathlib import Path

try:
    import pygetwindow as gw
    PYGETWINDOW = True
except ImportError:
    PYGETWINDOW = False

# Safety settings
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.1


class ScreenControl:
    """ARIA's computer use / screen control engine."""

    def __init__(self):
        self.screen_w, self.screen_h = pyautogui.size()
        print(f"[ScreenControl] Screen: {self.screen_w}x{self.screen_h}. Ready.")

    # ── Screenshots ────────────────────────────────────────────────────────────
    def take_screenshot(self, save_path="last_screenshot.png"):
        """Captures the full screen and saves it."""
        img = pyautogui.screenshot()
        img.save(save_path)
        return save_path

    def get_screen_image(self):
        """Returns a PIL Image of the current screen for AI analysis."""
        return pyautogui.screenshot()

    # ── Window Management ──────────────────────────────────────────────────────
    def find_window(self, title_keyword):
        """Find a window by partial title and return it."""
        if not PYGETWINDOW:
            return None
        keyword = title_keyword.lower()
        for w in gw.getAllWindows():
            if keyword in w.title.lower():
                return w
        return None

    def focus_window(self, title_keyword):
        """Bring a window to the foreground by partial title."""
        win = self.find_window(title_keyword)
        if win:
            try:
                win.activate()
                time.sleep(0.5)
                return True
            except Exception as e:
                print(f"[ScreenControl] Focus error: {e}")
        return False

    def list_open_windows(self):
        """Returns names of all currently open windows."""
        if not PYGETWINDOW:
            return []
        return [w.title for w in gw.getAllWindows() if w.title.strip()]

    # ── Mouse & Keyboard ───────────────────────────────────────────────────────
    def click(self, x, y, button="left", clicks=1):
        """Click at screen coordinates."""
        pyautogui.click(x, y, button=button, clicks=clicks)

    def double_click(self, x, y):
        pyautogui.doubleClick(x, y)

    def right_click(self, x, y):
        pyautogui.click(x, y, button="right")

    def move_to(self, x, y):
        pyautogui.moveTo(x, y, duration=0.3)

    def drag_to(self, x1, y1, x2, y2):
        pyautogui.drag(x2 - x1, y2 - y1, duration=0.5)

    def type_text(self, text, interval=0.04):
        """Types text at the current cursor position."""
        # Use clipboard for faster, unicode-safe typing
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")

    def press(self, *keys):
        """Press a key or combination. E.g. press('ctrl','c')"""
        pyautogui.hotkey(*keys)

    def scroll(self, clicks=3, direction="down"):
        amount = -clicks if direction == "down" else clicks
        pyautogui.scroll(amount)

    # ── File Explorer Operations ───────────────────────────────────────────────
    def open_folder(self, folder_path):
        """Opens a folder in File Explorer."""
        folder_path = os.path.expanduser(folder_path)
        if os.path.exists(folder_path):
            subprocess.Popen(f'explorer "{folder_path}"')
            time.sleep(1.5)
            return True
        return False

    def open_file(self, file_path):
        """Opens a file with its default application."""
        file_path = os.path.expanduser(file_path)
        if os.path.exists(file_path):
            os.startfile(file_path)
            time.sleep(1)
            return True
        return False

    def navigate_to_path(self, path):
        """
        Opens File Explorer at a given path using Ctrl+L (address bar shortcut).
        """
        # Open File Explorer
        subprocess.Popen("explorer")
        time.sleep(1.5)
        # Focus the address bar
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.3)
        pyperclip.copy(path)
        pyautogui.hotkey("ctrl", "v")
        pyautogui.press("enter")
        time.sleep(1)
        return True

    def find_file(self, folder, filename_keyword):
        """Search for a file in a folder matching a keyword."""
        folder = os.path.expanduser(folder)
        matches = []
        if os.path.exists(folder):
            for f in os.listdir(folder):
                if filename_keyword.lower() in f.lower():
                    matches.append(os.path.join(folder, f))
        return matches

    # ── WhatsApp Web Operations ────────────────────────────────────────────────
    def send_whatsapp_message(self, contact_name, message):
        """
        Opens WhatsApp Web and sends a message to a contact.
        Opens the direct WhatsApp Web chat link.
        """
        # Try wa.me link (works for saved contacts via phone number)
        # For contact by name, open WhatsApp Web and guide user
        encoded_msg = urllib.parse.quote(message)
        url = f"https://web.whatsapp.com/"
        webbrowser.open(url)
        time.sleep(4)  # Wait for WhatsApp Web to load

        # Search for the contact
        # Press Ctrl+F or click search bar
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.5)
        self.type_text(contact_name)
        time.sleep(1.5)
        pyautogui.press("enter")
        time.sleep(1)

        # Type the message
        self.type_text(message)
        time.sleep(0.3)
        pyautogui.press("enter")
        return f"Message sent to {contact_name} on WhatsApp Web."

    def send_whatsapp_file(self, contact_name, file_path):
        """
        Opens WhatsApp Web, finds the contact, and sends a file.
        """
        file_path = os.path.abspath(file_path)
        if not os.path.exists(file_path):
            return f"File not found: {file_path}"

        # Copy file path to clipboard
        pyperclip.copy(file_path)

        url = "https://web.whatsapp.com/"
        webbrowser.open(url)
        time.sleep(4)

        # Search for contact
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.5)
        self.type_text(contact_name)
        time.sleep(1.5)
        pyautogui.press("enter")
        time.sleep(1.5)

        # Click attachment button (paperclip icon — approximate location in WhatsApp Web)
        # This is a heuristic; may need adjustment per screen resolution
        # We'll use keyboard shortcut instead
        return f"Opened WhatsApp Web for {contact_name}. Please click the attachment icon and select the file: {file_path}"

    # ── Multi-Step Workflows ───────────────────────────────────────────────────
    def run_workflow(self, steps):
        """
        Executes a list of step dictionaries. Each step is:
        {"action": "click|type|press|wait|open_folder|open_file|focus", ...params}
        """
        results = []
        for step in steps:
            action = step.get("action", "")
            try:
                if action == "click":
                    self.click(step["x"], step["y"])
                elif action == "double_click":
                    self.double_click(step["x"], step["y"])
                elif action == "right_click":
                    self.right_click(step["x"], step["y"])
                elif action == "type":
                    self.type_text(step["text"])
                elif action == "press":
                    self.press(*step["keys"].split("+"))
                elif action == "wait":
                    time.sleep(step.get("seconds", 1))
                elif action == "open_folder":
                    self.open_folder(step["path"])
                elif action == "open_file":
                    self.open_file(step["path"])
                elif action == "focus":
                    self.focus_window(step["window"])
                elif action == "scroll":
                    self.scroll(step.get("clicks", 3), step.get("direction", "down"))
                results.append(f"✓ {action}")
            except Exception as e:
                results.append(f"✗ {action}: {e}")
        return results
