"""
ui_control.py — ARIA's Direct Screen Control (No Vision Needed)
===============================================================
Uses Windows UI Automation to directly access and control:
  - Any open window by title
  - Buttons, text boxes, menus, links by name
  - Address bars, search boxes, tabs
  - File dialogs, menus, dropdowns
All without taking any screenshot or using any AI vision model.
"""

import time
import subprocess
import pyautogui

try:
    from pywinauto import Application, Desktop
    from pywinauto.findwindows import find_windows
    import pywinauto.keyboard as kb
    PYWINAUTO = True
    print("[UIControl] pywinauto ready — direct screen control enabled.")
except ImportError:
    PYWINAUTO = False
    print("[UIControl] pywinauto not installed. Run: pip install pywinauto")

try:
    import win32gui, win32con, win32api
    WIN32 = True
except ImportError:
    WIN32 = False


class UIControl:
    """
    Direct Windows UI control — no screenshots, no AI.
    Finds real UI elements and controls them instantly.
    """

    def __init__(self):
        self.desktop = Desktop(backend="uia") if PYWINAUTO else None
        print("[UIControl] Initialized.")

    # ── Window Finding ────────────────────────────────────────────────────────

    def find_window(self, title_keyword):
        """Find an open window by partial title."""
        if not PYWINAUTO:
            return None
        try:
            wins = self.desktop.windows()
            kw = title_keyword.lower()
            for w in wins:
                try:
                    if kw in w.window_text().lower():
                        return w
                except Exception:
                    continue
        except Exception as e:
            print(f"[UIControl] find_window error: {e}")
        return None

    def list_windows(self):
        """List all open window titles."""
        if not PYWINAUTO:
            return []
        try:
            return [w.window_text() for w in self.desktop.windows()
                    if w.window_text().strip()]
        except Exception:
            return []

    def focus_window(self, title_keyword):
        """Bring a window to front by partial title."""
        win = self.find_window(title_keyword)
        if win:
            try:
                win.set_focus()
                time.sleep(0.3)
                return True, f"Focused {win.window_text()}"
            except Exception as e:
                return False, str(e)
        return False, f"Window '{title_keyword}' not found"

    # ── Element Interaction ───────────────────────────────────────────────────

    def click_element(self, window_title, element_name):
        """
        Click a named UI element inside a window.
        e.g. click_element("Chrome", "Address and search bar")
        """
        if not PYWINAUTO:
            return False, "pywinauto not available"
        try:
            win = self.find_window(window_title)
            if not win:
                return False, f"Window '{window_title}' not found"
            # Try to find by name, automation_id, or control_type
            for ctrl in win.descendants():
                try:
                    cname = ctrl.window_text().lower()
                    if element_name.lower() in cname:
                        ctrl.click_input()
                        return True, f"Clicked '{ctrl.window_text()}'"
                except Exception:
                    continue
            return False, f"Element '{element_name}' not found in {window_title}"
        except Exception as e:
            return False, str(e)

    def type_in_element(self, window_title, element_name, text):
        """Find a text field in a window and type into it."""
        if not PYWINAUTO:
            return False, "pywinauto not available"
        try:
            win = self.find_window(window_title)
            if not win:
                return False, f"Window '{window_title}' not found"
            for ctrl in win.descendants():
                try:
                    cname = ctrl.window_text().lower()
                    ctype = ctrl.element_info.control_type
                    if element_name.lower() in cname or ctype in ["Edit", "Document"]:
                        ctrl.click_input()
                        time.sleep(0.2)
                        ctrl.type_keys(text, with_spaces=True)
                        return True, f"Typed into '{ctrl.window_text()}'"
                except Exception:
                    continue
            return False, f"Text field '{element_name}' not found"
        except Exception as e:
            return False, str(e)

    def click_button(self, window_title, button_name):
        """Click a named button in a window."""
        if not PYWINAUTO:
            return False, "pywinauto not available"
        try:
            win = self.find_window(window_title)
            if not win:
                return False, f"Window '{window_title}' not found"
            # Try direct child search
            try:
                btn = win.child_window(title=button_name, control_type="Button")
                btn.click_input()
                return True, f"Clicked button '{button_name}'"
            except Exception:
                pass
            # Fuzzy search
            for ctrl in win.descendants():
                try:
                    if (button_name.lower() in ctrl.window_text().lower()
                            and ctrl.element_info.control_type == "Button"):
                        ctrl.click_input()
                        return True, f"Clicked '{ctrl.window_text()}'"
                except Exception:
                    continue
            return False, f"Button '{button_name}' not found"
        except Exception as e:
            return False, str(e)

    # ── Browser Control ───────────────────────────────────────────────────────

    def browser_go_to(self, url, browser="chrome"):
        """Navigate the browser to a URL directly via address bar."""
        # Use keyboard shortcut — works on any browser
        import pyperclip
        pyautogui.hotkey("ctrl", "l")     # focus address bar
        time.sleep(0.3)
        pyperclip.copy(url)
        pyautogui.hotkey("ctrl", "v")
        pyautogui.press("enter")
        return True, f"Navigating to {url}"

    def browser_new_tab(self):
        pyautogui.hotkey("ctrl", "t")
        time.sleep(0.3)
        return True, "Opened new tab"

    def browser_close_tab(self):
        pyautogui.hotkey("ctrl", "w")
        return True, "Closed tab"

    def browser_back(self):
        pyautogui.hotkey("alt", "Left")
        return True, "Went back"

    def browser_forward(self):
        pyautogui.hotkey("alt", "Right")
        return True, "Went forward"

    def browser_refresh(self):
        pyautogui.hotkey("ctrl", "r")
        return True, "Refreshed page"

    # ── App-level actions ─────────────────────────────────────────────────────

    def close_window(self, title_keyword=None):
        """Close a window by title or the currently focused window."""
        if title_keyword:
            ok, msg = self.focus_window(title_keyword)
            if not ok:
                return False, msg
            time.sleep(0.2)
        pyautogui.hotkey("alt", "F4")
        return True, "Window closed"

    def maximize_window(self, title_keyword=None):
        if title_keyword:
            self.focus_window(title_keyword)
            time.sleep(0.2)
        pyautogui.hotkey("win", "up")
        return True, "Window maximized"

    def minimize_window(self, title_keyword=None):
        if title_keyword:
            self.focus_window(title_keyword)
            time.sleep(0.2)
        pyautogui.hotkey("win", "down")
        return True, "Window minimized"

    def get_open_apps(self):
        """Return list of all open app window titles (filtered)."""
        wins = self.list_windows()
        filtered = [w for w in wins if len(w.strip()) > 2]
        return filtered

    # ── Smart command parser ──────────────────────────────────────────────────

    def execute_voice_command(self, command):
        """
        Parse and execute a natural voice command like:
          'click the close button in Chrome'
          'type hello in notepad'
          'focus notepad'
          'close chrome'
          'go to youtube in chrome'
        Returns (success, message)
        """
        cmd = command.lower().strip()

        # Focus / switch to window
        if "focus" in cmd or "switch to" in cmd or "go to app" in cmd:
            app = cmd.replace("focus", "").replace("switch to", "").replace("go to app", "").strip()
            return self.focus_window(app)

        # Close specific app
        if cmd.startswith("close ") and "tab" not in cmd:
            app = cmd[6:].strip()
            return self.close_window(app)

        # Browser navigation
        if "go to " in cmd and any(b in cmd for b in ["chrome", "edge", "firefox", "browser"]):
            words = cmd.split("go to ")
            url = words[-1].strip()
            if not url.startswith("http"):
                url = "https://" + url
            return self.browser_go_to(url)

        # New tab
        if "new tab" in cmd:
            return self.browser_new_tab()

        # Refresh
        if "refresh" in cmd or "reload" in cmd:
            return self.browser_refresh()

        # Go back
        if "go back" in cmd:
            return self.browser_back()

        return False, "Command not recognized by UIControl"

    def get_accessibility_tree(self):
        """Parse the active foreground window descendants and return an accessibility tree description list."""
        if not PYWINAUTO:
            return "pywinauto not available"
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return "No foreground window active"
            
            # Find matching window in desktop descendants
            app_win = None
            for w in self.desktop.windows():
                if w.handle == hwnd:
                    app_win = w
                    break
                    
            if not app_win:
                return "Could not match foreground window"
                
            # Parse descendants to get control tree metadata
            tree_nodes = []
            title = app_win.window_text() or "Untitled Window"
            tree_nodes.append(f"Window: '{title}'")
            
            count = 0
            for ctrl in app_win.descendants():
                try:
                    c_text = ctrl.window_text().strip()
                    c_type = ctrl.element_info.control_type
                    c_rect = ctrl.rectangle()
                    # Only include visible/interactable elements with names or standard controls
                    if c_text or c_type in ["Button", "Edit", "MenuItem", "CheckBox", "TabItem"]:
                        cx = (c_rect.left + c_rect.right) // 2
                        cy = (c_rect.top + c_rect.bottom) // 2
                        tree_nodes.append(f"  ├── {c_type}: '{c_text}' (center: {cx},{cy})")
                        count += 1
                        if count > 40:  # limit tree depth to prevent context overload
                            break
                except Exception:
                    continue
            return "\n".join(tree_nodes)
        except Exception as e:
            return f"Error retrieving accessibility tree: {e}"

    def open_browser(self, url=None):
        target_url = url.strip() if url else "https://www.google.com"
        if not target_url.startswith("http"):
            target_url = "https://" + target_url
        from skills.browser_skill import BrowserSkill
        BrowserSkill().navigate(target_url)
        return True, f"Opened browser pointing to: {target_url}"

    def search_google(self, query):
        from skills.browser_skill import BrowserSkill
        success, msg = BrowserSkill().search_google(query)
        return success, msg

    def open_vscode_project(self, path):
        import subprocess
        target_path = path.strip().strip("'\"")
        subprocess.Popen(f'code "{target_path}"', shell=True)
        return True, f"VS Code opened at path: {target_path}"


# Whitelist configurations for Sprint P25.1
OBSERVED_APPS = [
    "CODE.EXE", "CHROME.EXE", "FIREFOX.EXE", "MSEDGE.EXE",
    "TERMINAL.EXE", "POWERSHELL.EXE", "CMD.EXE",
    "DISCORD.EXE", "SPOTIFY.EXE", "NOTEPAD.EXE"
]

UI_TREE_APPS = [
    "CODE.EXE", "CHROME.EXE", "FIREFOX.EXE", "MSEDGE.EXE", "TERMINAL.EXE"
]

from skills.context_skill import WindowEvent

def _crawl_window_tree(window_title: str) -> dict:
    """Crawl UIA elements using pywinauto."""
    tree = {"buttons": [], "active_tabs": [], "input_fields": []}
    try:
        from pywinauto import Desktop
        desktop = Desktop(backend="uia")
        # Find open window matching title
        wins = desktop.windows()
        app_win = None
        kw = window_title.lower()
        for w in wins:
            try:
                if kw in w.window_text().lower():
                    app_win = w
                    break
            except Exception:
                continue
        
        if app_win:
            count = 0
            for ctrl in app_win.descendants():
                try:
                    c_text = ctrl.window_text().strip()
                    c_type = ctrl.element_info.control_type
                    
                    if c_type == "Button" and c_text:
                        tree["buttons"].append(c_text)
                    elif c_type == "TabItem" and c_text:
                        tree["active_tabs"].append(c_text)
                    elif c_type == "Edit" and c_text:
                        tree["input_fields"].append(c_text)
                        
                    count += 1
                    if count > 50:  # limit tree depth to prevent context/time overload
                        break
                except Exception:
                    continue
    except Exception as e:
        print(f"[ui_control] UIA crawl failed: {e}")
    return tree

def capture_desktop_perception_snapshot(pid: int, app_exe_name: str, window_title: str) -> WindowEvent:
    """Evaluates process whitelists to run high-value UI crawls only when needed."""
    app_tag = app_exe_name.upper().strip()
    
    # Check Track Tier A: Expensive accessibility crawls
    if app_tag in UI_TREE_APPS:
        print(f"[ui_control] UI Tree Whitelist hit ({app_tag}). Traversing structural nodes...")
        tree_data = _crawl_window_tree(window_title)
        return WindowEvent(pid, app_exe_name, window_title, accessibility_tree=tree_data)

    # Check Track Tier B: Simple focus time tracking
    if app_tag in OBSERVED_APPS:
        print(f"[ui_control] Focus Tracker Whitelist hit ({app_tag}). Logging title context only.")
        return WindowEvent(pid, app_exe_name, window_title)

    # Fallback default: Skip logging/crawling entirely for unmapped background applications
    return WindowEvent(pid, app_exe_name, window_title)


