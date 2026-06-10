"""
scratch/test_browser_attachment.py — Sprint P25.3 Verification Suite
===================================================================

Validates the complete Chrome CDP Browser Attachment features of AriaBrowserAttachmentSkill:
  1. Schema Validation - all tables & columns created and idempotent.
  2. Stable Tab ID Generation - url+title yields same ID, domains extracted properly.
  3. Tab Syncing Pipeline - 5 mock tabs mapped, banking auto-DENIED, others ASK.
  4. Sync Logging - entries recorded in browser_sync_log with correct stats.
  5. Read Metadata Access Gates - BLOCKED on ASK/DENIED, returns details on ALLOWED.
  6. Permission Modification - transition ASK -> ALLOWED/DENIED, block manual ALLOWED on protected.
  7. Permission Preservation - sync does not override manually-set ALLOWED or DENIED.
  8. Ledger queries - get_tab_list returns correct order and columns.
  9. Chrome Debuggable probe - responds correctly under port availability.
"""

import os
import sqlite3
import time
import unittest
from unittest.mock import MagicMock, patch

from skills.browser_attachment_skill import (
    AriaBrowserAttachmentSkill,
    init_chrome_cdp_schema,
    _stable_tab_id,
    _extract_domain,
    _is_protected,
    PERM_ALLOWED,
    PERM_ASK,
    PERM_DENIED,
)

TEST_DB = "test_browser_attachment_sandbox.db"


def _make_skill() -> AriaBrowserAttachmentSkill:
    """Return a fresh skill instance connected to the isolated test DB using mock adapter."""
    mock_aria = MagicMock()
    skill = AriaBrowserAttachmentSkill(
        aria_instance=mock_aria,
        db_path=TEST_DB,
        use_mock=True,
    )
    return skill


class TestBrowserAttachmentSchema(unittest.TestCase):
    """Verify database schema creation and columns."""

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        init_chrome_cdp_schema(TEST_DB)

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_schema_creates_active_browser_tabs_columns(self):
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.execute("PRAGMA table_info(active_browser_tabs)")
        cols = {row[1] for row in cursor.fetchall()}
        conn.close()
        expected = {
            "tab_id", "tab_title", "tab_url", "domain_segment",
            "permission_tier", "last_seen_timestamp", "last_read_timestamp",
        }
        self.assertTrue(expected.issubset(cols), f"Missing columns in active_browser_tabs: {expected - cols}")

    def test_schema_creates_browser_sync_log_columns(self):
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.execute("PRAGMA table_info(browser_sync_log)")
        cols = {row[1] for row in cursor.fetchall()}
        conn.close()
        expected = {
            "sync_id", "timestamp", "mode", "tabs_found",
            "tabs_denied", "tabs_ask", "tabs_allowed", "error_message",
        }
        self.assertTrue(expected.issubset(cols), f"Missing columns in browser_sync_log: {expected - cols}")

    def test_schema_is_idempotent(self):
        init_chrome_cdp_schema(TEST_DB)
        init_chrome_cdp_schema(TEST_DB)
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.execute("SELECT COUNT(*) FROM active_browser_tabs")
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)


class TestTabIDAndHelpers(unittest.TestCase):
    """Verify domain parsing, protected domain matching, and stable ID generation."""

    def test_stable_tab_id_consistency(self):
        url = "https://github.com/ChinmayaBiswal7/ARIA"
        title = "ARIA - GitHub"
        id1 = _stable_tab_id(url, title)
        id2 = _stable_tab_id(url, title)
        self.assertEqual(id1, id2)
        self.assertEqual(len(id1), 16)

        # Different url/title must produce different IDs
        id3 = _stable_tab_id(url, "Different Title")
        self.assertNotEqual(id1, id3)

    def test_extract_domain(self):
        self.assertEqual(_extract_domain("https://portal.kiit.ac.in/opportunities"), "portal.kiit.ac.in")
        self.assertEqual(_extract_domain("http://localhost:9222/json"), "localhost:9222")

    def test_is_protected(self):
        # Protected patterns
        self.assertTrue(_is_protected("https://netbanking.sbi.co.in/banking/home"))
        self.assertTrue(_is_protected("https://accounts.google.com/signin"))
        self.assertTrue(_is_protected("https://github.com/login"))
        self.assertTrue(_is_protected("https://1password.com/vault"))

        # Regular patterns
        self.assertFalse(_is_protected("https://github.com/ChinmayaBiswal7/ARIA"))
        self.assertFalse(_is_protected("https://spring.io/guides"))


class TestTabSyncingPipeline(unittest.TestCase):
    """Verify sync_live_tabs reads the mock data, auto-denies protected domains, and sets others to ASK."""

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        self.skill = _make_skill()

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_sync_live_tabs_success(self):
        stats = self.skill.sync_live_tabs()
        self.assertEqual(stats["status"], "SUCCESS")
        self.assertEqual(stats["mode"], "MOCK")
        self.assertEqual(stats["tabs_found"], 5)
        self.assertEqual(stats["tabs_denied"], 1) # sbi netbanking
        self.assertEqual(stats["tabs_ask"], 4)
        self.assertEqual(stats["tabs_allowed"], 0)

        # Check ledger entries directly
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.execute("SELECT tab_url, permission_tier FROM active_browser_tabs")
        rows = cursor.fetchall()
        conn.close()

        self.assertEqual(len(rows), 5)
        for url, perm in rows:
            if "netbanking.sbi" in url:
                self.assertEqual(perm, PERM_DENIED)
            else:
                self.assertEqual(perm, PERM_ASK)

    def test_sync_log_recorded(self):
        self.skill.sync_live_tabs()
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.execute("SELECT mode, tabs_found, tabs_denied, tabs_ask FROM browser_sync_log")
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "MOCK")
        self.assertEqual(row[1], 5)
        self.assertEqual(row[2], 1)
        self.assertEqual(row[3], 4)


class TestPermissionAndReadGates(unittest.TestCase):
    """Verify reading and modifying tab permissions."""

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        self.skill = _make_skill()
        self.skill.sync_live_tabs()

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_read_tab_metadata_blocks_ask(self):
        # find a regular tab (e.g. portal.kiit.ac.in)
        tabs = self.skill.get_tab_list()
        ask_tab = [t for t in tabs if "kiit" in t["tab_url"]][0]
        tab_id = ask_tab["tab_id"]

        status, text = self.skill.read_tab_metadata(tab_id)
        self.assertEqual(status, PERM_ASK)
        self.assertIn("AWAITING APPROVAL", text)

    def test_read_tab_metadata_blocks_denied(self):
        tabs = self.skill.get_tab_list()
        denied_tab = [t for t in tabs if "netbanking" in t["tab_url"]][0]
        tab_id = denied_tab["tab_id"]

        status, text = self.skill.read_tab_metadata(tab_id)
        self.assertEqual(status, PERM_DENIED)
        self.assertIn("ACCESS DENIED", text)

    def test_set_tab_permission_allowed_succeeds_on_regular_tab(self):
        tabs = self.skill.get_tab_list()
        ask_tab = [t for t in tabs if "kiit" in t["tab_url"]][0]
        tab_id = ask_tab["tab_id"]

        success, msg = self.skill.set_tab_permission(tab_id, PERM_ALLOWED)
        self.assertTrue(success)
        self.assertIn("ALLOWED", msg)

        # Now reading it should return ALLOWED + structural metadata
        status, text = self.skill.read_tab_metadata(tab_id)
        self.assertEqual(status, PERM_ALLOWED)
        self.assertIn("Tab: KIIT Placement Portal", text)
        self.assertIn("URL: https://portal.kiit.ac.in/opportunities", text)
        self.assertNotIn("<html>", text)  # structural metadata only, no raw HTML

    def test_set_tab_permission_allowed_fails_on_protected_tab(self):
        tabs = self.skill.get_tab_list()
        denied_tab = [t for t in tabs if "netbanking" in t["tab_url"]][0]
        tab_id = denied_tab["tab_id"]

        # Try to upgrade SBI NetBanking to ALLOWED
        success, msg = self.skill.set_tab_permission(tab_id, PERM_ALLOWED)
        self.assertFalse(success)
        self.assertIn("Cannot grant ALLOWED to a protected domain", msg)

    def test_set_tab_permission_invalid_rejected(self):
        tabs = self.skill.get_tab_list()
        tab_id = tabs[0]["tab_id"]
        success, msg = self.skill.set_tab_permission(tab_id, "SUPER_ALLOW")
        self.assertFalse(success)
        self.assertIn("Invalid permission", msg)


class TestPermissionPreservation(unittest.TestCase):
    """Verify that sync_live_tabs preserves user-defined permissions (doesn't downgrade to ASK)."""

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        self.skill = _make_skill()
        self.skill.sync_live_tabs()

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_permission_preservation_on_subsequent_syncs(self):
        tabs = self.skill.get_tab_list()
        kiit_tab = [t for t in tabs if "kiit" in t["tab_url"]][0]
        tab_id = kiit_tab["tab_id"]

        # 1. Manually set KIIT tab to ALLOWED
        self.skill.set_tab_permission(tab_id, PERM_ALLOWED)

        # 2. Re-sync live tabs
        self.skill.sync_live_tabs()

        # 3. Read it again; it must remain ALLOWED (not downgraded to ASK)
        status, text = self.skill.read_tab_metadata(tab_id)
        self.assertEqual(status, PERM_ALLOWED)

        # 4. Manually set spring.io to DENIED
        spring_tab = [t for t in tabs if "spring.io" in t["tab_url"]][0]
        spring_id = spring_tab["tab_id"]
        self.skill.set_tab_permission(spring_id, PERM_DENIED)

        # 5. Re-sync live tabs
        self.skill.sync_live_tabs()

        # 6. Reading spring.io should still be DENIED (not downgraded/changed)
        status, text = self.skill.read_tab_metadata(spring_id)
        self.assertEqual(status, PERM_DENIED)


class TestChromeDebuggable(unittest.TestCase):
    """Verify the localhost:9222/json/version probe."""

    @patch("urllib.request.urlopen")
    def test_is_chrome_debuggable_true(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        skill = _make_skill()
        self.assertTrue(skill.is_chrome_debuggable())

    @patch("urllib.request.urlopen")
    def test_is_chrome_debuggable_false(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")

        skill = _make_skill()
        self.assertFalse(skill.is_chrome_debuggable())


if __name__ == "__main__":
    unittest.main(verbosity=2)
