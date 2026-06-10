"""
scratch/test_desktop_control.py — Sprint P25.2 Verification Suite
=================================================================

Validates the complete safety pipeline of AriaDesktopControlSkill:

  1. App Risk Classification  — SAFE / CONFIRM / BLOCKED app groups
  2. Hotkey Safety Levels     — SAFE executes, CONFIRM intercepts, BLOCKED rejects
  3. Content Safety Layer     — Destructive text patterns blocked regardless of app
  4. Combined App+Content     — Both filters must pass (SAFE app + SAFE content)
  5. Action Ledger Schema     — Schema creation & row persistence
  6. Confirmation Columns     — requires_confirmation / confirmed_by_user fields
  7. read_selected_text mock  — Clipboard backup/restore path
  8. Ledger query helpers     — get_recent_actions / get_safety_summary
"""

import os
import sqlite3
import time
import unittest
from unittest.mock import MagicMock, patch

from skills.desktop_control_skill import (
    AriaDesktopControlSkill,
    init_desktop_control_schema,
    SAFETY_SAFE,
    SAFETY_CONFIRM,
    SAFETY_BLOCKED,
    SAFE_TEXT_APPS,
    CONFIRM_APPS,
    BLOCKED_APPS,
    HOTKEY_SAFETY_LEVELS,
)

TEST_DB = "test_desktop_control_sandbox.db"


def _make_skill() -> AriaDesktopControlSkill:
    """Return a fresh skill instance connected to the isolated test DB."""
    mock_aria = MagicMock()
    skill = AriaDesktopControlSkill(aria_instance=mock_aria, db_path=TEST_DB)
    return skill


class TestDesktopControlSchema(unittest.TestCase):
    """Verify schema creation and ledger columns."""

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        init_desktop_control_schema(TEST_DB)

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_schema_creates_all_columns(self):
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.execute("PRAGMA table_info(desktop_action_ledger)")
        cols = {row[1] for row in cursor.fetchall()}
        conn.close()
        expected = {
            "action_id", "timestamp", "action_type",
            "target_window_title", "target_process_name",
            "safety_level", "execution_result",
            "requires_confirmation", "confirmed_by_user",
        }
        self.assertTrue(expected.issubset(cols), f"Missing columns: {expected - cols}")

    def test_schema_is_idempotent(self):
        """Calling init twice must not raise or duplicate anything."""
        init_desktop_control_schema(TEST_DB)
        init_desktop_control_schema(TEST_DB)
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.execute("SELECT COUNT(*) FROM desktop_action_ledger")
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)


class TestAppRiskClassification(unittest.TestCase):
    """_classify_app returns the correct tier for each group."""

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        self.skill = _make_skill()

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_safe_apps_return_safe(self):
        for app in ["CODE.EXE", "CHROME.EXE", "NOTEPAD.EXE", "DISCORD.EXE", "OBSIDIAN.EXE"]:
            self.assertEqual(self.skill._classify_app(app), SAFETY_SAFE, app)

    def test_confirm_apps_return_confirm(self):
        for app in ["CMD.EXE", "POWERSHELL.EXE", "WT.EXE", "REGEDIT.EXE", "BASH.EXE"]:
            self.assertEqual(self.skill._classify_app(app), SAFETY_CONFIRM, app)

    def test_blocked_apps_return_blocked(self):
        for app in ["DISKPART.EXE", "FORMAT.COM", "BCDEDIT.EXE", "INSTALL.EXE"]:
            self.assertEqual(self.skill._classify_app(app), SAFETY_BLOCKED, app)

    def test_unknown_app_defaults_to_confirm(self):
        self.assertEqual(self.skill._classify_app("SOMERANDOMEAPP.EXE"), SAFETY_CONFIRM)


class TestHotkeySafetyLevels(unittest.TestCase):
    """send_hotkey routes SAFE / CONFIRM / BLOCKED correctly."""

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        self.skill = _make_skill()

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    @patch("pyautogui.hotkey")
    def test_safe_hotkey_executes(self, mock_hotkey, mock_fg):
        mock_fg.return_value = ("CODE.EXE", "Visual Studio Code")
        level, success, msg = self.skill.send_hotkey("ctrl+s")
        self.assertEqual(level, SAFETY_SAFE)
        self.assertTrue(success)
        mock_hotkey.assert_called_once_with("ctrl", "s")

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    def test_confirm_hotkey_intercepted_without_user_approval(self, mock_fg):
        mock_fg.return_value = ("CODE.EXE", "Visual Studio Code")
        level, success, msg = self.skill.send_hotkey("alt+f4")
        self.assertEqual(level, SAFETY_CONFIRM)
        self.assertFalse(success)
        self.assertIn("requires CONFIRMATION", msg)

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    @patch("pyautogui.hotkey")
    def test_confirm_hotkey_executes_with_user_approval(self, mock_hotkey, mock_fg):
        mock_fg.return_value = ("CODE.EXE", "Visual Studio Code")
        level, success, msg = self.skill.send_hotkey("alt+f4", user_confirmed=True)
        self.assertEqual(level, SAFETY_SAFE)
        self.assertTrue(success)

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    def test_blocked_hotkey_rejected(self, mock_fg):
        mock_fg.return_value = ("CODE.EXE", "Visual Studio Code")
        level, success, msg = self.skill.send_hotkey("win+l")
        self.assertEqual(level, SAFETY_BLOCKED)
        self.assertFalse(success)
        self.assertIn("permanent blocklist", msg)

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    def test_unknown_hotkey_defaults_to_confirm(self, mock_fg):
        mock_fg.return_value = ("CODE.EXE", "Visual Studio Code")
        level, success, msg = self.skill.send_hotkey("ctrl+shift+q")  # not in table
        self.assertEqual(level, SAFETY_CONFIRM)
        self.assertFalse(success)


class TestContentSafetyLayer(unittest.TestCase):
    """_destructive_content_check blocks harmful patterns in typed text."""

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        self.skill = _make_skill()

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def _blocked(self, text: str) -> bool:
        return self.skill._destructive_content_check(text) is not None

    def test_format_command_blocked(self):
        self.assertTrue(self._blocked("format c:"))

    def test_del_flag_blocked(self):
        self.assertTrue(self._blocked("del /f /s /q C:\\temp"))

    def test_rmdir_blocked(self):
        self.assertTrue(self._blocked("rmdir /s /q dist"))

    def test_shutdown_blocked(self):
        self.assertTrue(self._blocked("shutdown /s /t 0"))

    def test_taskkill_force_blocked(self):
        self.assertTrue(self._blocked("taskkill /f /im explorer.exe"))

    def test_reg_delete_blocked(self):
        self.assertTrue(self._blocked("reg delete HKLM\\Software\\test"))

    def test_normal_code_allowed(self):
        self.assertFalse(self._blocked("print('Hello, ARIA!')"))
        self.assertFalse(self._blocked("def main(): return 42"))
        self.assertFalse(self._blocked("git commit -m 'wip'"))

    def test_partial_word_not_blocked(self):
        # "formatted" does not start with "format <driveletter>:"
        self.assertFalse(self._blocked("formatted output as JSON"))


class TestTypingGates(unittest.TestCase):
    """type_text applies both app-level and content-level gates."""

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        self.skill = _make_skill()

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    @patch("pyperclip.copy")
    @patch("pyautogui.hotkey")
    def test_safe_app_safe_content_executes(self, mock_hotkey, mock_copy, mock_fg):
        mock_fg.return_value = ("CODE.EXE", "VS Code")
        level, success, msg = self.skill.type_text("print('hello')")
        self.assertEqual(level, SAFETY_SAFE)
        self.assertTrue(success)

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    def test_safe_app_destructive_content_blocked(self, mock_fg):
        # Even in VS Code, destructive commands must be blocked
        mock_fg.return_value = ("CODE.EXE", "VS Code")
        level, success, msg = self.skill.type_text("rmdir /s /q .")
        self.assertEqual(level, SAFETY_BLOCKED)
        self.assertFalse(success)
        self.assertIn("destructive pattern", msg)

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    def test_confirm_app_without_approval_intercepted(self, mock_fg):
        mock_fg.return_value = ("POWERSHELL.EXE", "Windows PowerShell")
        level, success, msg = self.skill.type_text("Get-Process")
        self.assertEqual(level, SAFETY_CONFIRM)
        self.assertFalse(success)
        self.assertIn("requires CONFIRMATION", msg)

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    @patch("pyperclip.copy")
    @patch("pyautogui.hotkey")
    def test_confirm_app_with_approval_and_safe_content_executes(self, mock_hotkey, mock_copy, mock_fg):
        mock_fg.return_value = ("POWERSHELL.EXE", "Windows PowerShell")
        level, success, msg = self.skill.type_text("Get-Process", user_confirmed=True)
        self.assertEqual(level, SAFETY_SAFE)
        self.assertTrue(success)

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    def test_blocked_app_always_blocked(self, mock_fg):
        mock_fg.return_value = ("DISKPART.EXE", "DiskPart")
        level, success, msg = self.skill.type_text("list disk")
        self.assertEqual(level, SAFETY_BLOCKED)
        self.assertFalse(success)
        self.assertIn("BLOCKED_APPS", msg)


class TestLedgerPersistence(unittest.TestCase):
    """Every action produces a correct ledger record."""

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        self.skill = _make_skill()

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    @patch("pyperclip.copy")
    @patch("pyautogui.hotkey")
    def test_ledger_row_created_on_safe_type(self, mock_hotkey, mock_copy, mock_fg):
        mock_fg.return_value = ("CODE.EXE", "VS Code")
        self.skill.type_text("x = 1")

        rows = self.skill.get_recent_actions(limit=5)
        self.assertTrue(len(rows) >= 1)
        row = rows[0]
        self.assertEqual(row["action_type"], "TYPE")
        self.assertEqual(row["safety_level"], SAFETY_SAFE)
        self.assertEqual(row["requires_confirmation"], 0)
        self.assertEqual(row["confirmed_by_user"], 0)

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    def test_ledger_confirm_columns_set_correctly_for_confirm_apps(self, mock_fg):
        # CONFIRM app without user approval → requires_confirmation=1, confirmed_by_user=0
        mock_fg.return_value = ("CMD.EXE", "Command Prompt")
        self.skill.type_text("dir")

        rows = self.skill.get_recent_actions(limit=5)
        self.assertTrue(any(r["requires_confirmation"] == 1 and r["confirmed_by_user"] == 0 for r in rows))

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    def test_ledger_blocked_hotkey_recorded(self, mock_fg):
        mock_fg.return_value = ("CODE.EXE", "VS Code")
        self.skill.send_hotkey("win+l")  # BLOCKED

        rows = self.skill.get_recent_actions(limit=5)
        self.assertTrue(any(r["safety_level"] == SAFETY_BLOCKED for r in rows))

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    @patch("pyperclip.copy")
    @patch("pyautogui.hotkey")
    def test_safety_summary_counts_match_reality(self, mock_hotkey, mock_copy, mock_fg):
        mock_fg.return_value = ("CODE.EXE", "VS Code")

        # 2 SAFE actions
        self.skill.type_text("hello = 1")
        self.skill.send_hotkey("ctrl+s")

        # 1 CONFIRM intercept
        self.skill.send_hotkey("alt+f4")  # CONFIRM, no approval

        # 1 BLOCKED action
        self.skill.send_hotkey("win+l")   # BLOCKED

        summary = self.skill.get_safety_summary()
        self.assertGreaterEqual(summary.get(SAFETY_SAFE, 0), 2)
        self.assertGreaterEqual(summary.get(SAFETY_CONFIRM, 0), 1)
        self.assertGreaterEqual(summary.get(SAFETY_BLOCKED, 0), 1)


class TestReadSelectedText(unittest.TestCase):
    """read_selected_text backs up and restores clipboard."""

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        self.skill = _make_skill()

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    @patch("pyautogui.hotkey")
    @patch("pyperclip.copy")
    @patch("pyperclip.paste")
    def test_selected_text_returned_and_clipboard_restored(
        self, mock_paste, mock_copy, mock_hotkey, mock_fg
    ):
        mock_fg.return_value = ("CODE.EXE", "VS Code")

        # First call = backup, second call = captured text after ctrl+c
        mock_paste.side_effect = ["original_clipboard_content", "selected code snippet"]

        success, text = self.skill.read_selected_text()

        self.assertTrue(success)
        self.assertEqual(text, "selected code snippet")

        # The clipboard must be restored to the backup content at the end
        restore_call = mock_copy.call_args_list[-1]
        self.assertEqual(restore_call[0][0], "original_clipboard_content")

    @patch("skills.desktop_control_skill.AriaDesktopControlSkill._active_foreground")
    @patch("pyautogui.hotkey")
    @patch("pyperclip.copy")
    @patch("pyperclip.paste")
    def test_empty_clipboard_returns_false(
        self, mock_paste, mock_copy, mock_hotkey, mock_fg
    ):
        mock_fg.return_value = ("CHROME.EXE", "Google Chrome")
        mock_paste.side_effect = ["backup", ""]  # nothing captured

        success, msg = self.skill.read_selected_text()
        self.assertFalse(success)
        self.assertIn("empty", msg.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
