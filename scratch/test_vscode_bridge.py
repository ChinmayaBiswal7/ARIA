"""
scratch/test_vscode_bridge.py — Sprint P25.4 Verification Suite
===============================================================

Validates the complete VS Code Intelligence Bridge features of AriaVsCodeBridgeSkill
and AriaVsCodeBridgeServer:
  1. Schema Validation - tables created and idempotent.
  2. Data Persistence - _persist correctly calculates error/warning counts and saves to SQLite.
  3. Query APIs - get_workspace_snapshot, get_active_file, get_diagnostics, get_selection.
  4. Snapshot Pruning - only keeps last 200 rows in SQLite.
  5. Summary Formatting - output correct info when empty vs when populated.
  6. Server Ping and State - verify HTTP server endpoints via local requests (or mocked).
"""

import os
import sqlite3
import time
import unittest
from unittest.mock import MagicMock, patch
import urllib.request
import json

from skills.vscode_bridge_skill import (
    AriaVsCodeBridgeServer,
    AriaVsCodeBridgeSkill,
    init_vscode_bridge_schema,
    VSCODE_BRIDGE_HOST,
    VSCODE_BRIDGE_PORT,
)

TEST_DB = "test_vscode_bridge.db"


class TestVsCodeBridgeSchema(unittest.TestCase):
    """Verify database schema creation, columns, and idempotency."""

    def setUp(self):
        if os.path.exists(TEST_DB):
            try:
                os.remove(TEST_DB)
            except OSError:
                pass
        init_vscode_bridge_schema(TEST_DB)

    def tearDown(self):
        if os.path.exists(TEST_DB):
            try:
                os.remove(TEST_DB)
            except OSError:
                pass

    def test_schema_creates_vscode_workspace_state_columns(self):
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.execute("PRAGMA table_info(vscode_workspace_state)")
        cols = {row[1] for row in cursor.fetchall()}
        conn.close()
        expected = {
            "id", "timestamp", "active_file", "file_name", "language_id",
            "cursor_line", "selection", "error_count", "warning_count",
            "info_count", "git_branch", "open_files_json", "terminal_cwd",
            "diagnostics_json"
        }
        self.assertTrue(expected.issubset(cols), f"Missing columns in vscode_workspace_state: {expected - cols}")

    def test_schema_creates_vscode_diagnostic_log_columns(self):
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.execute("PRAGMA table_info(vscode_diagnostic_log)")
        cols = {row[1] for row in cursor.fetchall()}
        conn.close()
        expected = {
            "log_id", "timestamp", "file_name", "severity", "message", "line_number"
        }
        self.assertTrue(expected.issubset(cols), f"Missing columns in vscode_diagnostic_log: {expected - cols}")

    def test_schema_is_idempotent(self):
        init_vscode_bridge_schema(TEST_DB)
        init_vscode_bridge_schema(TEST_DB)
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.execute("SELECT COUNT(*) FROM vscode_workspace_state")
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)


class TestVsCodeBridgeSkillAndServer(unittest.TestCase):
    """Verify data persistence, snapshot queries, and formatting APIs."""

    def setUp(self):
        if os.path.exists(TEST_DB):
            try:
                os.remove(TEST_DB)
            except OSError:
                pass
        self.server = AriaVsCodeBridgeServer(db_path=TEST_DB)
        self.skill = AriaVsCodeBridgeSkill(db_path=TEST_DB, server=self.server)

    def tearDown(self):
        if os.path.exists(TEST_DB):
            try:
                os.remove(TEST_DB)
            except OSError:
                pass

    def test_persist_writes_correctly_and_computes_stats(self):
        payload = {
            "active_file": "c:/D FOLDER/Projects/AI/skills/vscode_bridge_skill.py",
            "language_id": "python",
            "cursor_line": 105,
            "selection": "test code selection here",
            "diagnostics": [
                {"severity": "ERROR", "message": "SyntaxError", "line": 42},
                {"severity": "WARNING", "message": "Unused import", "line": 10},
                {"severity": "INFO", "message": "Typo in comment", "line": 15},
                {"severity": "HINT", "message": "Simplify code", "line": 20},
            ],
            "git_branch": "feature/sprint-p25-desktop",
            "open_files": [
                "c:/D FOLDER/Projects/AI/skills/vscode_bridge_skill.py",
                "c:/D FOLDER/Projects/AI/main.py"
            ],
            "terminal_cwd": "c:/D FOLDER/Projects/AI"
        }
        self.server._persist(payload)

        # Retrieve snapshot via skill
        snap = self.skill.get_workspace_snapshot()
        self.assertIsNotNone(snap)
        self.assertEqual(snap["active_file"], "c:/D FOLDER/Projects/AI/skills/vscode_bridge_skill.py")
        self.assertEqual(snap["file_name"], "vscode_bridge_skill.py")
        self.assertEqual(snap["language_id"], "python")
        self.assertEqual(snap["cursor_line"], 105)
        self.assertEqual(snap["selection"], "test code selection here")
        self.assertEqual(snap["git_branch"], "feature/sprint-p25-desktop")
        self.assertEqual(snap["terminal_cwd"], "c:/D FOLDER/Projects/AI")
        self.assertEqual(snap["error_count"], 1)
        self.assertEqual(snap["warning_count"], 1)
        self.assertEqual(snap["info_count"], 2) # INFO + HINT

        # Check deserialized lists
        self.assertEqual(len(snap["open_files"]), 2)
        self.assertEqual(snap["open_files"][1], "c:/D FOLDER/Projects/AI/main.py")
        self.assertEqual(len(snap["diagnostics"]), 4)

        # Check active file and selection APIs
        self.assertEqual(self.skill.get_active_file(), "c:/D FOLDER/Projects/AI/skills/vscode_bridge_skill.py")
        self.assertEqual(self.skill.get_selection(), "test code selection here")

        # Check diagnostics log table
        diags = self.skill.get_diagnostics()
        self.assertEqual(len(diags), 4)
        
        # Check filtered diagnostics (ERROR only)
        err_diags = self.skill.get_diagnostics(severity="ERROR")
        self.assertEqual(len(err_diags), 1)
        self.assertEqual(err_diags[0]["message"], "SyntaxError")

    def test_pruning_limits_to_200_rows(self):
        payload = {
            "active_file": "file.py",
            "language_id": "python",
            "cursor_line": 1,
            "selection": "",
            "diagnostics": [],
            "git_branch": "main",
            "open_files": [],
            "terminal_cwd": ""
        }
        # Write 220 entries
        for i in range(220):
            payload["cursor_line"] = i
            self.server._persist(payload)

        # Check total rows
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.execute("SELECT COUNT(*) FROM vscode_workspace_state")
        count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count, 200)

        # Check that the last one has cursor_line = 219 (descending order by id)
        snap = self.skill.get_workspace_snapshot()
        self.assertEqual(snap["cursor_line"], 219)

    def test_format_workspace_summary_empty(self):
        summary = self.skill.format_workspace_summary()
        self.assertIn("VS Code bridge has no data yet", summary)

    def test_format_workspace_summary_with_data(self):
        payload = {
            "active_file": "c:/D FOLDER/Projects/AI/main.py",
            "language_id": "python",
            "cursor_line": 50,
            "selection": "def hello():",
            "diagnostics": [{"severity": "ERROR", "message": "Fatal error", "line": 5}],
            "git_branch": "main",
            "open_files": ["file1.py", "file2.py", "file3.py", "file4.py", "file5.py", "file6.py"],
            "terminal_cwd": "c:/D FOLDER/Projects/AI"
        }
        self.server._persist(payload)
        summary = self.skill.format_workspace_summary()
        self.assertIn("main.py", summary)
        self.assertIn("PYTHON", summary)
        self.assertIn("def hello():", summary)
        self.assertIn("🔴 1 error(s)", summary)
        self.assertIn("Git Branch:** `main`", summary)
        self.assertIn("(+1 more)", summary) # file1-5 + 1 more


class TestBridgeServerLifeAndHttp(unittest.TestCase):
    """Verify HTTP server startup, ping routing, state POSTing, and liveness probe."""

    def setUp(self):
        if os.path.exists(TEST_DB):
            try:
                os.remove(TEST_DB)
            except OSError:
                pass

    def tearDown(self):
        if os.path.exists(TEST_DB):
            try:
                os.remove(TEST_DB)
            except OSError:
                pass

    @patch("urllib.request.urlopen")
    def test_is_bridge_server_alive_mocked_true(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        skill = AriaVsCodeBridgeSkill(db_path=TEST_DB)
        self.assertTrue(skill.is_bridge_server_alive())

    @patch("urllib.request.urlopen")
    def test_is_bridge_server_alive_mocked_false(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")

        skill = AriaVsCodeBridgeSkill(db_path=TEST_DB)
        self.assertFalse(skill.is_bridge_server_alive())

    def test_live_server_endpoints(self):
        """Start a real server thread locally and test HTTP requests to it."""
        server = AriaVsCodeBridgeServer(db_path=TEST_DB)
        skill = AriaVsCodeBridgeSkill(db_path=TEST_DB, server=server)

        # Initially offline
        self.assertFalse(skill.is_bridge_server_alive())

        # Start server
        started = server.start()
        if not started:
            self.skipTest("Flask server failed to start or bind port (possibly port 9821 in use).")

        try:
            # Check liveness
            self.assertTrue(skill.is_bridge_server_alive())

            # Test POST /vscode/state
            payload = {
                "active_file": "c:/D FOLDER/Projects/AI/test_live_vscode.py",
                "language_id": "python",
                "cursor_line": 99,
                "selection": "live selection",
                "diagnostics": [],
                "git_branch": "live-testing",
                "open_files": [],
                "terminal_cwd": "c:/D FOLDER/Projects/AI"
            }
            
            url = f"http://{VSCODE_BRIDGE_HOST}:{VSCODE_BRIDGE_PORT}/vscode/state"
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                self.assertEqual(resp.status, 200)
                resp_data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(resp_data["status"], "ok")

            # Check that data got persisted via POST
            snap = skill.get_workspace_snapshot()
            self.assertIsNotNone(snap)
            self.assertEqual(snap["active_file"], "c:/D FOLDER/Projects/AI/test_live_vscode.py")
            self.assertEqual(snap["git_branch"], "live-testing")

        finally:
            # Server runs as daemon thread, will terminate when unittest runner exits.
            pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
