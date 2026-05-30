import os
import time
import subprocess
import webbrowser
import urllib.parse
import pyautogui
import ctypes

try:
    from AppOpener import open as app_open, close as app_close
    APPOPENER_AVAILABLE = True
except ImportError:
    APPOPENER_AVAILABLE = False
    print("[Automation] AppOpener not available. Using subprocess fallback.")

class Automation:
    """Handles all system automation tasks."""

    # Map of common app aliases to actual executable names
    APP_ALIASES = {
        "chrome": "chrome",
        "google chrome": "chrome",
        "firefox": "firefox",
        "edge": "msedge",
        "microsoft edge": "msedge",
        "notepad": "notepad",
        "calculator": "calc",
        "calc": "calc",
        "file explorer": "explorer",
        "explorer": "explorer",
        "task manager": "taskmgr",
        "paint": "mspaint",
        "command prompt": "cmd",
        "cmd": "cmd",
        "powershell": "powershell",
        "word": "winword",
        "excel": "excel",
        "powerpoint": "powerpnt",
        "vlc": "vlc",
        "discord": "discord",
        "spotify": "spotify",
        "vscode": "code",
        "vs code": "code",
        "visual studio code": "code",
        "whatsapp": "whatsapp",
        "telegram": "telegram",
        "zoom": "zoom",
        "teams": "teams",
        "obs": "obs64",
        "unigram": "unigram",
        "unigrm": "unigram",
    }

    def __init__(self):
        pyautogui.FAILSAFE = False  # Disable fail-safe corner
        pyautogui.PAUSE = 0.05
        print("[Automation] Initialized.")

    def open_app(self, app_name):
        """Opens an application by name."""
        app_lower = app_name.lower().strip()
        print(f"[Automation] Opening: {app_name}")

        # Special cases — websites & Windows URIs
        if "copilot" in app_lower or "microsoft copilot" in app_lower:
            return self.open_url("https://copilot.microsoft.com")
        if "chatgpt" in app_lower:
            return self.open_url("https://chat.openai.com")
        if "gemini" in app_lower:
            return self.open_url("https://gemini.google.com")
        if "settings" in app_lower:
            subprocess.Popen("ms-settings:", shell=True)
            return "Opening Settings."
        if "store" in app_lower or "microsoft store" in app_lower:
            subprocess.Popen("ms-windows-store:", shell=True)
            return "Opening Microsoft Store."
        if "youtube" in app_lower:
            return self.open_url("https://www.youtube.com")
        if "gmail" in app_lower or "email" in app_lower:
            return self.open_url("https://mail.google.com")
        if "maps" in app_lower or "google maps" in app_lower:
            return self.open_url("https://maps.google.com")
        if "google" in app_lower and "chrome" not in app_lower:
            return self.open_url("https://www.google.com")
        if "instagram" in app_lower:
            return self.open_url("https://www.instagram.com")
        if "twitter" in app_lower or "x.com" in app_lower:
            return self.open_url("https://www.x.com")
        if "whatsapp web" in app_lower:
            return self.open_url("https://web.whatsapp.com")
        if "netflix" in app_lower:
            return self.open_url("https://www.netflix.com")

        # Chrome — bypass profile chooser by specifying Default profile
        if "chrome" in app_lower:
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
            ]
            for path in chrome_paths:
                if os.path.exists(path):
                    subprocess.Popen([path, "--profile-directory=Default"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(1.5)  # Give Chrome time to open
                    return "Opening Chrome."
            # fallback
            subprocess.Popen("chrome", shell=True)
            return "Opening Chrome."

        # Try AppOpener first
        if APPOPENER_AVAILABLE:
            try:
                app_open(app_name, match_closest=True, output=False)
                return f"Opening {app_name}."
            except Exception as e:
                print(f"[Automation] AppOpener failed: {e}, trying subprocess...")

        # Fallback: resolve alias and use subprocess
        exe = self.APP_ALIASES.get(app_lower, app_lower)
        try:
            subprocess.Popen(exe, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Opening {app_name}."
        except Exception as e:
            return f"Sorry, I couldn't open {app_name}. Error: {e}"

    def close_app(self, app_name):
        """Closes an application by name using taskkill."""
        app_lower = app_name.lower().strip()
        print(f"[Automation] Closing: {app_name}")

        # Try AppOpener first
        if APPOPENER_AVAILABLE:
            try:
                app_close(app_name, match_closest=True, output=False)
                return f"Closing {app_name}."
            except Exception as e:
                print(f"[Automation] AppOpener close failed: {e}, trying taskkill...")

        # Fallback: taskkill
        exe = self.APP_ALIASES.get(app_lower, app_lower)
        if not exe.endswith(".exe"):
            exe += ".exe"
        try:
            subprocess.run(["taskkill", "/f", "/im", exe], capture_output=True)
            return f"Closing {app_name}."
        except Exception as e:
            return f"Sorry, I couldn't close {app_name}. Error: {e}"

    def type_text(self, text):
        """Types text into the currently focused window."""
        print(f"[Automation] Typing: {text}")
        try:
            time.sleep(0.5)
            pyautogui.write(text, interval=0.04)
            return "Done typing."
        except Exception as e:
            # Fallback: use clipboard
            try:
                import pyperclip
                pyperclip.copy(text)
                pyautogui.hotkey('ctrl', 'v')
                return "Done typing (via clipboard)."
            except:
                return f"Failed to type: {e}"

    def search_web(self, query):
        """Opens the right URL for a query — website name or web search using BrowserSkill."""
        print(f"[Automation] Search/Open using BrowserSkill: {query}")
        q = query.lower().strip()

        from skills.browser_skill import BrowserSkill
        browser = BrowserSkill()

        # Site-scoped product searches must stay inside the requested site.
        if "amazon" in q and any(term in q for term in ["search", "keyboard", "keyboards", "buy", "shop", "for", "on amazon"]):
            import re
            clean_q = query
            for term in [
                "search amazon for", "search for", "search", "in amazon",
                "on amazon", "from amazon", "amazon", "buy", "shop for",
            ]:
                clean_q = re.sub(r'(?i)\b' + re.escape(term) + r'\b', '', clean_q)
            clean_q = clean_q.strip(" .?!") or query
            if clean_q.lower() not in {"it", "that", "this", "something"}:
                return browser.search_amazon(clean_q)

        # Specific search inside YouTube detection
        has_search_terms = len(q.replace("youtube", "").replace("yt", "").strip()) > 0
        if ("youtube" in q or "yt" in q) and has_search_terms:
            import re
            clean_q = query
            for term in ["in youtube", "on youtube", "inside youtube", "in yt", "on yt", "inside yt", "youtube", "yt"]:
                clean_q = re.sub(r'(?i)\b' + re.escape(term) + r'\b', '', clean_q)
            clean_q = clean_q.strip()
            if clean_q:
                encoded = urllib.parse.quote(clean_q)
                url = f"https://www.youtube.com/results?search_query={encoded}"
                browser.navigate(url)
                return f"Searching YouTube for: {clean_q}"

        # Smart website detection — open directly instead of searching Google
        SITE_MAP = {
            "youtube": "https://www.youtube.com",
            "ytb": "https://www.youtube.com",
            "yt": "https://www.youtube.com",
            "gmail": "https://mail.google.com",
            "google": "https://www.google.com",
            "instagram": "https://www.instagram.com",
            "twitter": "https://www.twitter.com",
            "x.com": "https://www.x.com",
            "facebook": "https://www.facebook.com",
            "netflix": "https://www.netflix.com",
            "github": "https://www.github.com",
            "reddit": "https://www.reddit.com",
            "amazon": "https://www.amazon.in",
            "flipkart": "https://www.flipkart.com",
            "spotify": "https://open.spotify.com",
            "whatsapp": "https://web.whatsapp.com",
            "linkedin": "https://www.linkedin.com",
            "maps": "https://maps.google.com",
            "chatgpt": "https://chat.openai.com",
        }
        for keyword, url in SITE_MAP.items():
            if keyword in q:
                browser.navigate(url)
                return f"Opening {keyword}."

        # Regular Google search
        encoded = urllib.parse.quote(query)
        url = f"https://www.google.com/search?q={encoded}"
        browser.navigate(url)
        return f"Searching for: {query}"

    def open_url(self, url):
        """Opens a URL using BrowserSkill."""
        print(f"[Automation] Opening URL using BrowserSkill: {url}")
        from skills.browser_skill import BrowserSkill
        BrowserSkill().navigate(url)
        return f"Opened {url}."

    def volume_up(self):
        """Increases system volume."""
        try:
            for _ in range(5):
                pyautogui.press('volumeup')
            return "Volume increased."
        except Exception as e:
            return f"Volume control failed: {e}"

    def volume_down(self):
        """Decreases system volume."""
        try:
            for _ in range(5):
                pyautogui.press('volumedown')
            return "Volume decreased."
        except Exception as e:
            return f"Volume control failed: {e}"

    def volume_mute(self):
        """Toggles mute."""
        try:
            pyautogui.press('volumemute')
            return "Volume toggled."
        except Exception as e:
            return f"Mute failed: {e}"

    def take_screenshot(self, filename=None):
        """Takes a screenshot and saves it."""
        try:
            if not filename:
                import datetime
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{ts}.png"
            screenshot = pyautogui.screenshot()
            screenshot.save(filename)
            print(f"[Automation] Screenshot saved to {filename}")
            return filename
        except Exception as e:
            print(f"[Automation] Screenshot error: {e}")
            return None

    def lock_screen(self):
        """Locks the Windows screen."""
        try:
            ctypes.windll.user32.LockWorkStation()
            return "Screen locked."
        except Exception as e:
            return f"Lock failed: {e}"

    def shutdown(self):
        """Shuts down the computer."""
        try:
            os.system("shutdown /s /t 5")
            return "Shutting down in 5 seconds."
        except Exception as e:
            return f"Shutdown failed: {e}"

    def restart(self):
        """Restarts the computer."""
        try:
            os.system("shutdown /r /t 5")
            return "Restarting in 5 seconds."
        except Exception as e:
            return f"Restart failed: {e}"

    def press_key(self, key):
        """Presses a keyboard key/shortcut."""
        try:
            pyautogui.hotkey(*key.split('+'))
            return f"Pressed {key}."
        except Exception as e:
            return f"Key press failed: {e}"
