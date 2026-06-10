"""
skills/desktop_control_skill.py — ARIA Desktop Control Layer (Sprint P25.2)
============================================================================

Provides ARIA with safe, audited desktop interaction through 5 narrow APIs:
  - focus_window()        : Bring a window into the foreground
  - type_text()           : Type text with app + content safety checks
  - send_hotkey()         : Execute keyboard shortcuts with confirmation gating
  - click_control()       : Click a named UI element in the active window
  - read_selected_text()  : Capture highlighted text via clipboard

Safety Architecture:
  - App Risk Groups: SAFE_TEXT_APPS / CONFIRM_APPS / BLOCKED_APPS
  - Confirmation Levels: SAFE / CONFIRM / BLOCKED applied per-hotkey
  - Content Safety: Destructive command pattern blocklist applied on typed text
  - Unknown apps default to CONFIRM (not SAFE, not BLOCKED)

Every action is written to the `desktop_action_ledger` SQLite table.
"""

import os
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

import psutil
import pyautogui
import pyperclip
import win32gui
import win32process


# ── Module-level constants ────────────────────────────────────────────────────

# Actions that were never executed by the OS but were evaluated
_UNEXECUTED_RESULTS = frozenset({"BLOCKED", "CONFIRM_REQUIRED"})


# ─── Safety Classification Tables ─────────────────────────────────────────────

# Applications in which typing and hotkeys are immediately safe.
SAFE_TEXT_APPS: frozenset = frozenset({
    # Code editors
    "CODE.EXE",         # VS Code
    "CURSOR.EXE",       # Cursor IDE
    "IDEA64.EXE",       # IntelliJ IDEA
    "PYCHARM64.EXE",    # PyCharm
    "SUBLIME_TEXT.EXE", # Sublime Text
    "NOTEPAD.EXE",      # Notepad
    "NOTEPAD++.EXE",    # Notepad++
    "WORDPAD.EXE",      # WordPad
    "WINWORD.EXE",      # Microsoft Word
    "EXCEL.EXE",        # Microsoft Excel
    "POWERPNT.EXE",     # PowerPoint
    # Browsers
    "CHROME.EXE",
    "MSEDGE.EXE",
    "FIREFOX.EXE",
    "OPERA.EXE",
    "BRAVE.EXE",
    # Communication / messaging
    "DISCORD.EXE",
    "SLACK.EXE",
    "TELEGRAM.EXE",
    "TEAMS.EXE",
    "ZOOM.EXE",
    "SKYPE.EXE",
    "WHATSAPP.EXE",
    # Notes / PKM
    "OBSIDIAN.EXE",
    "NOTION.EXE",
    "ONENOTE.EXE",
})

# Applications that require user confirmation before any typing or restricted hotkey.
CONFIRM_APPS: frozenset = frozenset({
    "CMD.EXE",
    "POWERSHELL.EXE",
    "PWSH.EXE",              # PowerShell Core
    "WT.EXE",                # Windows Terminal
    "WINDOWSTERMINAL.EXE",
    "REGEDIT.EXE",
    "MSHTA.EXE",             # HTML Application Host
    "WSCRIPT.EXE",           # Windows Script Host
    "CSCRIPT.EXE",
    "MSIEXEC.EXE",
    "RUNAS.EXE",
    "BASH.EXE",              # WSL bash
    "WSL.EXE",
    "UBUNTU.EXE",
})

# Applications where typing is always blocked — no confirmation possible.
BLOCKED_APPS: frozenset = frozenset({
    "DISKPART.EXE",
    "DISKMGMT.EXE",
    "FORMAT.COM",
    "FDISK.EXE",
    "SETUP.EXE",
    "INSTALL.EXE",
    "BCDEDIT.EXE",           # Boot Config Editor
    "BOOTREC.EXE",
    "REAGENTC.EXE",          # Windows Recovery
    "RECOVERYIMAGE.EXE",
})


# ─── Content-Level Safety Blocklist ───────────────────────────────────────────

# These substring patterns are blocked in typed content regardless of the active app.
# Pattern is matched on the lowercased, stripped version of the text.
DESTRUCTIVE_CONTENT_PATTERNS: List[str] = [
    r"format\s+[a-z]:",         # format c:
    r"del\s+/[fs]",             # del /f, del /s
    r"rmdir\s+/s",              # rmdir /s
    r"rd\s+/s",                 # rd /s
    r"shutdown\s*/[srh]",       # shutdown /s /r /h
    r"shutdown\s+/[srh]",
    r"taskkill\s+/f",           # taskkill /f
    r"reg\s+delete",            # reg delete
    r"reg\s+add",               # reg add
    r"attrib\s+[+-][rsh]",      # attrib -r, attrib +h
    r"cipher\s+/w",             # cipher /w (wipe free space)
    r"sfc\s+/scannow",          # sfc (allowed via voice but block raw typing)
    r"bcdedit\s+/",             # Boot config edits
    r"net\s+user\s+\w+\s+/delete",  # User deletion
    r"mklink\s+/[djh]",         # Symbolic links
]

_COMPILED_DESTRUCTIVE: List[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in DESTRUCTIVE_CONTENT_PATTERNS
]


# ─── Hotkey Confirmation Levels ────────────────────────────────────────────────

#: The three confirmation tiers an action can occupy.
SAFETY_SAFE    = "SAFE"
SAFETY_CONFIRM = "CONFIRM"
SAFETY_BLOCKED = "BLOCKED"

# Per-hotkey safety level.  Keys are *lowercase* normalised (e.g. "ctrl+c").
HOTKEY_SAFETY_LEVELS: Dict[str, str] = {
    # ── SAFE shortcuts ──────────────────────────────────────────────────────
    "ctrl+c":           SAFETY_SAFE,
    "ctrl+v":           SAFETY_SAFE,
    "ctrl+x":           SAFETY_SAFE,
    "ctrl+z":           SAFETY_SAFE,
    "ctrl+y":           SAFETY_SAFE,
    "ctrl+s":           SAFETY_SAFE,
    "ctrl+a":           SAFETY_SAFE,
    "ctrl+f":           SAFETY_SAFE,
    "ctrl+h":           SAFETY_SAFE,
    "ctrl+p":           SAFETY_SAFE,
    "ctrl+n":           SAFETY_SAFE,
    "ctrl+t":           SAFETY_SAFE,    # new tab
    "ctrl+w":           SAFETY_SAFE,    # close tab
    "ctrl+shift+t":     SAFETY_SAFE,    # reopen tab
    "ctrl+tab":         SAFETY_SAFE,
    "ctrl+shift+tab":   SAFETY_SAFE,
    "alt+tab":          SAFETY_SAFE,
    "f5":               SAFETY_SAFE,
    "escape":           SAFETY_SAFE,
    "enter":            SAFETY_SAFE,
    "tab":              SAFETY_SAFE,
    "ctrl+enter":       SAFETY_SAFE,
    "ctrl+shift+p":     SAFETY_SAFE,    # VS Code command palette
    "ctrl+`":           SAFETY_SAFE,    # VS Code terminal toggle
    "ctrl+b":           SAFETY_SAFE,    # sidebar toggle / bold
    "ctrl+shift+e":     SAFETY_SAFE,    # VS Code explorer
    # ── CONFIRM shortcuts ───────────────────────────────────────────────────
    "alt+f4":           SAFETY_CONFIRM,
    "win+r":            SAFETY_CONFIRM,
    "win+x":            SAFETY_CONFIRM,
    "win+e":            SAFETY_CONFIRM,
    "ctrl+alt+t":       SAFETY_CONFIRM,  # may open terminal
    "ctrl+shift+esc":   SAFETY_CONFIRM,  # Task Manager
    "ctrl+alt+delete":  SAFETY_CONFIRM,
    "ctrl+alt+del":     SAFETY_CONFIRM,
    "shift+delete":     SAFETY_CONFIRM,  # Permanent delete
    "f2":               SAFETY_CONFIRM,  # Rename
    "ctrl+d":           SAFETY_CONFIRM,  # Delete / bookmark
    # ── BLOCKED shortcuts ───────────────────────────────────────────────────
    "win+l":            SAFETY_BLOCKED,  # Lock screen (breaks session)
    "win+d":            SAFETY_BLOCKED,  # Show desktop abruptly
}


# ─── Schema Initialisation ─────────────────────────────────────────────────────

def init_desktop_control_schema(db_path: str = "aria_orchestrator.db") -> None:
    """Create the `desktop_action_ledger` table if it does not yet exist."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS desktop_action_ledger (
                action_id             INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp             REAL    NOT NULL,
                action_type           TEXT    NOT NULL,  -- FOCUS | TYPE | HOTKEY | READ | CLICK
                target_window_title   TEXT,
                target_process_name   TEXT,
                safety_level          TEXT    NOT NULL,  -- SAFE | CONFIRM | BLOCKED
                execution_result      TEXT,
                requires_confirmation INTEGER DEFAULT 0, -- 1 when CONFIRM was required
                confirmed_by_user     INTEGER DEFAULT 0  -- 1 when user explicitly approved
            )
        """)
        conn.commit()
    finally:
        conn.close()


# ─── Main Skill Class ──────────────────────────────────────────────────────────

class AriaDesktopControlSkill:
    """
    Narrow, audited desktop control skill for ARIA.

    All public methods follow the same safety pipeline:
        1.  Determine active foreground app name.
        2.  Look up app risk group (SAFE / CONFIRM / BLOCKED / unknown→CONFIRM).
        3.  For BLOCKED apps, reject immediately.
        4.  For CONFIRM apps, return CONFIRM status — caller must solicit user.
        5.  Validate content against destructive pattern blocklist.
        6.  Execute the action.
        7.  Write a row to desktop_action_ledger.
    """

    def __init__(
        self,
        aria_instance: Any = None,
        db_path: str = "aria_orchestrator.db",
    ) -> None:
        self.aria    = aria_instance
        self.db_path = db_path
        init_desktop_control_schema(db_path)
        print("[DesktopControlSkill] Initialised. Action ledger ready.")

    # ── Public API ─────────────────────────────────────────────────────────

    def focus_window(self, title_keyword: str) -> Tuple[bool, str]:
        """
        Bring the first window whose title contains *title_keyword* to the front.
        Returns (success, message).
        """
        app_name, window_title = self._active_foreground()
        try:
            hwnd = self._find_hwnd_by_title(title_keyword)
            if hwnd is None:
                result = f"Window containing '{title_keyword}' not found."
                self._log("FOCUS", title_keyword, "UNKNOWN", SAFETY_SAFE, result)
                return False, result

            import ctypes
            ctypes.windll.user32.ShowWindow(hwnd, 5)   # SW_SHOWNOTINDEPENDENT
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(0.3)

            focused_title = win32gui.GetWindowText(hwnd)
            result = f"Focused: '{focused_title}'"
            self._log("FOCUS", focused_title, "SYSTEM", SAFETY_SAFE, result)
            return True, result

        except Exception as exc:
            result = f"Focus failed: {exc}"
            self._log("FOCUS", title_keyword, "SYSTEM", SAFETY_SAFE, result)
            return False, result

    def type_text(
        self,
        text: str,
        user_confirmed: bool = False,
    ) -> Tuple[str, bool, str]:
        """
        Type *text* into the currently active window.

        Returns (safety_level, success, message).
        safety_level will be one of SAFETY_SAFE / SAFETY_CONFIRM / SAFETY_BLOCKED.
        When safety_level == CONFIRM, set user_confirmed=True after asking the user.
        """
        app_name, window_title = self._active_foreground()
        app_risk = self._classify_app(app_name)

        # ── 1. App-level gate ──────────────────────────────────────────────
        if app_risk == SAFETY_BLOCKED:
            reason = (
                f"Typing BLOCKED: active app '{app_name}' is in the "
                f"BLOCKED_APPS group (disk/installer utilities)."
            )
            self._log("TYPE", window_title, app_name, SAFETY_BLOCKED, reason)
            return SAFETY_BLOCKED, False, reason

        if app_risk == SAFETY_CONFIRM and not user_confirmed:
            reason = (
                f"Typing requires CONFIRMATION: active app '{app_name}' is "
                f"a shell/registry editor.  Call again with user_confirmed=True."
            )
            self._log(
                "TYPE", window_title, app_name, SAFETY_CONFIRM, reason,
                requires_confirmation=1, confirmed_by_user=0,
            )
            return SAFETY_CONFIRM, False, reason

        # ── 2. Content-level gate ──────────────────────────────────────────
        blocked_pattern = self._destructive_content_check(text)
        if blocked_pattern:
            reason = (
                f"Typing BLOCKED: text contains destructive pattern "
                f"matching '{blocked_pattern}'."
            )
            self._log("TYPE", window_title, app_name, SAFETY_BLOCKED, reason)
            return SAFETY_BLOCKED, False, reason

        # ── 3. Execute ─────────────────────────────────────────────────────
        try:
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.05)
            result = f"Typed {len(text)} chars into '{window_title}'."
            cfm_val = 1 if app_risk == SAFETY_CONFIRM else 0
            self._log(
                "TYPE", window_title, app_name, SAFETY_SAFE, result,
                requires_confirmation=cfm_val, confirmed_by_user=cfm_val,
            )
            return SAFETY_SAFE, True, result
        except Exception as exc:
            result = f"Type execution failed: {exc}"
            self._log("TYPE", window_title, app_name, SAFETY_SAFE, result)
            return SAFETY_SAFE, False, result

    def send_hotkey(
        self,
        keys_string: str,
        user_confirmed: bool = False,
    ) -> Tuple[str, bool, str]:
        """
        Execute a keyboard shortcut such as 'ctrl+s' or 'alt+f4'.

        Returns (safety_level, success, message).
        For CONFIRM-level shortcuts, the caller must set user_confirmed=True.
        """
        app_name, window_title = self._active_foreground()
        clean_key = keys_string.lower().strip()
        safety    = HOTKEY_SAFETY_LEVELS.get(clean_key, SAFETY_CONFIRM)

        # ── BLOCKED ────────────────────────────────────────────────────────
        if safety == SAFETY_BLOCKED:
            reason = (
                f"Hotkey BLOCKED: '{clean_key}' is in the permanent blocklist."
            )
            self._log("HOTKEY", window_title, app_name, SAFETY_BLOCKED, reason)
            return SAFETY_BLOCKED, False, reason

        # ── CONFIRM ────────────────────────────────────────────────────────
        if safety == SAFETY_CONFIRM and not user_confirmed:
            reason = (
                f"Hotkey requires CONFIRMATION: '{clean_key}' needs explicit "
                f"user approval.  Call again with user_confirmed=True."
            )
            self._log(
                "HOTKEY", window_title, app_name, SAFETY_CONFIRM, reason,
                requires_confirmation=1, confirmed_by_user=0,
            )
            return SAFETY_CONFIRM, False, reason

        # ── Execute ────────────────────────────────────────────────────────
        try:
            parts = [k.strip() for k in clean_key.split("+") if k.strip()]
            pyautogui.hotkey(*parts)
            result = f"Executed hotkey: {clean_key}"
            cfm_val = 1 if (safety == SAFETY_CONFIRM and user_confirmed) else 0
            self._log(
                "HOTKEY", window_title, app_name, SAFETY_SAFE, result,
                requires_confirmation=cfm_val, confirmed_by_user=cfm_val,
            )
            return SAFETY_SAFE, True, result
        except Exception as exc:
            result = f"Hotkey execution failed: {exc}"
            self._log("HOTKEY", window_title, app_name, SAFETY_SAFE, result)
            return SAFETY_SAFE, False, result

    def click_control(self, control_name: str) -> Tuple[bool, str]:
        """
        Click a named UIA element in the foreground window using pywinauto
        (falls back gracefully if pywinauto is not installed).
        Returns (success, message).
        """
        app_name, window_title = self._active_foreground()
        try:
            from pywinauto import Desktop
            desktop = Desktop(backend="uia")
            hwnd = win32gui.GetForegroundWindow()
            app_win = None
            for w in desktop.windows():
                if w.handle == hwnd:
                    app_win = w
                    break

            if app_win is None:
                result = "Could not bind to foreground window via UIA."
                self._log("CLICK", window_title, app_name, SAFETY_SAFE, result)
                return False, result

            for ctrl in app_win.descendants():
                try:
                    if control_name.lower() in ctrl.window_text().lower():
                        ctrl.click_input()
                        result = f"Clicked UIA control: '{ctrl.window_text()}'"
                        self._log("CLICK", window_title, app_name, SAFETY_SAFE, result)
                        return True, result
                except Exception:
                    continue

            result = f"Control '{control_name}' not found in '{window_title}'."
            self._log("CLICK", window_title, app_name, SAFETY_SAFE, result)
            return False, result

        except ImportError:
            # pywinauto not installed — fall back to pyautogui pixel-based locate
            result = "pywinauto unavailable; UIA control click skipped."
            self._log("CLICK", window_title, app_name, SAFETY_SAFE, result)
            return False, result
        except Exception as exc:
            result = f"click_control failed: {exc}"
            self._log("CLICK", window_title, app_name, SAFETY_SAFE, result)
            return False, result

    def read_selected_text(self) -> Tuple[bool, str]:
        """
        Read currently highlighted/selected text by backing up the clipboard,
        sending Ctrl+C, reading the clipboard, then restoring the backup.
        Returns (success, captured_text_or_error).
        """
        app_name, window_title = self._active_foreground()
        backup = ""
        try:
            backup = pyperclip.paste()
        except Exception:
            pass

        try:
            pyperclip.copy("")
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.25)
            captured = pyperclip.paste()

            # Restore original clipboard
            try:
                pyperclip.copy(backup)
            except Exception:
                pass

            if captured:
                result = f"Captured {len(captured)} chars from '{window_title}'."
                self._log("READ", window_title, app_name, SAFETY_SAFE, result)
                return True, captured

            result = "No text was selected or clipboard was empty."
            self._log("READ", window_title, app_name, SAFETY_SAFE, result)
            return False, result

        except Exception as exc:
            try:
                pyperclip.copy(backup)
            except Exception:
                pass
            result = f"read_selected_text failed: {exc}"
            self._log("READ", window_title, app_name, SAFETY_SAFE, result)
            return False, result

    # ── Ledger Query Helpers ───────────────────────────────────────────────

    def get_recent_actions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return the *limit* most recent ledger rows as dicts."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                """
                SELECT action_type, target_window_title, target_process_name,
                       safety_level, execution_result,
                       requires_confirmation, confirmed_by_user, timestamp
                FROM   desktop_action_ledger
                ORDER  BY action_id DESC
                LIMIT  ?
                """,
                (limit,),
            )
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_safety_summary(self) -> Dict[str, int]:
        """Return a count of SAFE / CONFIRM / BLOCKED actions in the ledger."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT safety_level, COUNT(*) as cnt
                FROM   desktop_action_ledger
                GROUP  BY safety_level
                """
            )
            return {row[0]: row[1] for row in cursor.fetchall()}
        finally:
            conn.close()

    # ── Private Helpers ────────────────────────────────────────────────────

    def _active_foreground(self) -> Tuple[str, str]:
        """Return (process_name_upper, window_title) of the foreground window."""
        try:
            hwnd = win32gui.GetForegroundWindow()
            if hwnd == 0:
                return "IDLE", "Desktop"
            title = win32gui.GetWindowText(hwnd) or "Unknown"
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            return proc.name().upper().strip(), title
        except Exception:
            return "UNKNOWN", "Unknown"

    def _classify_app(self, app_name: str) -> str:
        """Classify an app_name into SAFE / CONFIRM / BLOCKED.  Unknown → CONFIRM."""
        if app_name in SAFE_TEXT_APPS:
            return SAFETY_SAFE
        if app_name in BLOCKED_APPS:
            return SAFETY_BLOCKED
        if app_name in CONFIRM_APPS:
            return SAFETY_CONFIRM
        # Unknown / unlisted apps are treated as CONFIRM by default.
        return SAFETY_CONFIRM

    def _destructive_content_check(self, text: str) -> Optional[str]:
        """
        Scan *text* against DESTRUCTIVE_CONTENT_PATTERNS.
        Returns the matched pattern string on a hit, or None if clean.
        """
        for pattern in _COMPILED_DESTRUCTIVE:
            if pattern.search(text):
                return pattern.pattern
        return None

    def _find_hwnd_by_title(self, title_keyword: str) -> Optional[int]:
        """Return the first HWND whose window text contains *title_keyword* (case-insensitive)."""
        results: List[int] = []
        kw = title_keyword.lower()

        def _enum_cb(hwnd: int, _: Any) -> bool:
            if win32gui.IsWindowVisible(hwnd):
                if kw in win32gui.GetWindowText(hwnd).lower():
                    results.append(hwnd)
            return True

        win32gui.EnumWindows(_enum_cb, None)
        return results[0] if results else None

    def _log(
        self,
        action_type:          str,
        window_title:         str,
        process_name:         str,
        safety_level:         str,
        execution_result:     str,
        requires_confirmation: int = 0,
        confirmed_by_user:    int = 0,
    ) -> None:
        """Write one row to desktop_action_ledger (silent on failure)."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO desktop_action_ledger
                        (timestamp, action_type, target_window_title,
                         target_process_name, safety_level, execution_result,
                         requires_confirmation, confirmed_by_user)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        time.time(), action_type, window_title,
                        process_name, safety_level, execution_result,
                        requires_confirmation, confirmed_by_user,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            print(f"[DesktopControlSkill] Ledger write failed: {exc}")
