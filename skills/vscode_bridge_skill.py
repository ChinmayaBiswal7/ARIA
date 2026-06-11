"""
skills/vscode_bridge_skill.py — ARIA VS Code Intelligence Bridge (Sprint P25.4)
================================================================================

Architecture:
  VS Code Extension (TypeScript)
        │  POST JSON to http://localhost:9821/vscode/state
        ▼
  AriaVsCodeBridgeServer  ← Flask HTTP server, runs in daemon thread
        │  persists to SQLite
        ▼
  AriaVsCodeBridgeSkill   ← 5 query APIs for command router

Payload received from extension:
  {
    "active_file":   "/absolute/path/to/file.py",
    "language_id":   "python",
    "cursor_line":   42,
    "selection":     "selected code snippet or empty string",
    "diagnostics":   [{"severity": "ERROR", "message": "...", "line": 10}, ...],
    "git_branch":    "main",
    "open_files":    ["file1.py", "file2.py"],
    "terminal_cwd":  "/workspace/folder"
  }

Design rules:
  - HTTP server binds to 127.0.0.1 only (local-only, not exposed to network).
  - No code execution — only metadata is stored (paths, counts, branch names).
  - Port 9821 is the canonical ARIA VS Code bridge port.
  - Server starts lazily on first query / explicit start command.
  - Thread-safe SQLite writes via connection-per-write pattern.
"""

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

# ── Port constant ─────────────────────────────────────────────────────────────
VSCODE_BRIDGE_PORT = 9821
VSCODE_BRIDGE_HOST = "127.0.0.1"

# ── Schema ────────────────────────────────────────────────────────────────────

def init_vscode_bridge_schema(db_path: str = "aria_orchestrator.db") -> None:
    """
    Create VS Code workspace tracking tables.
    Safe to call multiple times — uses IF NOT EXISTS.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vscode_workspace_state (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp            INTEGER NOT NULL,
                active_file          TEXT,
                file_name            TEXT,
                language_id          TEXT,
                cursor_line          INTEGER DEFAULT 0,
                selection            TEXT,
                error_count          INTEGER DEFAULT 0,
                warning_count        INTEGER DEFAULT 0,
                info_count           INTEGER DEFAULT 0,
                git_branch           TEXT,
                open_files_json      TEXT,   -- JSON array of open file paths
                terminal_cwd         TEXT,
                diagnostics_json     TEXT    -- JSON array of diagnostic objects
            )
        """)
        # Keep only the last 200 snapshots (old rows auto-pruned on insert)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vscode_diagnostic_log (
                log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   INTEGER NOT NULL,
                file_name   TEXT,
                severity    TEXT,
                message     TEXT,
                line_number INTEGER
            )
        """)
        conn.commit()
    finally:
        conn.close()


# ── HTTP Server ───────────────────────────────────────────────────────────────

class AriaVsCodeBridgeServer:
    """
    Lightweight Flask HTTP server that receives state pushes from the VS Code extension.
    Runs as a background daemon thread — does NOT block ARIA's main loop.
    """

    def __init__(self, db_path: str = "aria_orchestrator.db") -> None:
        self.db_path    = db_path
        self._thread:   Optional[threading.Thread] = None
        self._running   = False
        self._last_state: Dict[str, Any] = {}
        init_vscode_bridge_schema(db_path)

    def start(self) -> bool:
        """Start the bridge HTTP server in a background thread. Returns True if started."""
        if self._running:
            return True
        try:
            from flask import Flask, request, jsonify
        except ImportError:
            print("[VsCodeBridge] Flask not installed. Run: pip install flask")
            return False

        app = Flask("aria_vscode_bridge")
        # Silence Flask logs
        import logging
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.ERROR)

        @app.route("/vscode/state", methods=["POST"])
        def receive_state():
            try:
                payload = request.get_json(force=True, silent=True) or {}
                self._last_state = payload
                self._persist(payload)
                return jsonify({"status": "ok"}), 200
            except Exception as exc:
                return jsonify({"status": "error", "detail": str(exc)}), 500

        @app.route("/vscode/ping", methods=["GET"])
        def ping():
            return jsonify({"status": "alive", "port": VSCODE_BRIDGE_PORT}), 200

        def _run():
            self._running = True
            app.run(host=VSCODE_BRIDGE_HOST, port=VSCODE_BRIDGE_PORT,
                    debug=False, use_reloader=False, threaded=True)

        self._thread = threading.Thread(target=_run, daemon=True, name="aria-vscode-bridge")
        self._thread.start()
        time.sleep(0.4)  # Give Flask a moment to bind the port
        print(f"[VsCodeBridge] HTTP server listening on {VSCODE_BRIDGE_HOST}:{VSCODE_BRIDGE_PORT}")
        return True

    def is_running(self) -> bool:
        return self._running and (self._thread is not None) and self._thread.is_alive()

    def get_last_state(self) -> Dict[str, Any]:
        return dict(self._last_state)

    def _persist(self, payload: Dict[str, Any]) -> None:
        """Write one snapshot row + individual diagnostic log rows to SQLite."""
        now = int(time.time())
        diagnostics: List[Dict] = payload.get("diagnostics", [])
        open_files:  List[str]  = payload.get("open_files", [])

        error_count   = sum(1 for d in diagnostics if d.get("severity", "").upper() == "ERROR")
        warning_count = sum(1 for d in diagnostics if d.get("severity", "").upper() == "WARNING")
        info_count    = sum(1 for d in diagnostics if d.get("severity", "").upper() in ("INFO", "HINT"))

        file_path = payload.get("active_file", "")
        file_name = os.path.basename(file_path) if file_path else ""

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT INTO vscode_workspace_state
                    (timestamp, active_file, file_name, language_id, cursor_line,
                     selection, error_count, warning_count, info_count,
                     git_branch, open_files_json, terminal_cwd, diagnostics_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                now,
                file_path,
                file_name,
                payload.get("language_id", ""),
                payload.get("cursor_line", 0),
                payload.get("selection", ""),
                error_count,
                warning_count,
                info_count,
                payload.get("git_branch", ""),
                json.dumps(open_files),
                payload.get("terminal_cwd", ""),
                json.dumps(diagnostics),
            ))

            # Prune snapshots older than the last 200 rows
            conn.execute("""
                DELETE FROM vscode_workspace_state
                WHERE id NOT IN (
                    SELECT id FROM vscode_workspace_state
                    ORDER BY id DESC LIMIT 200
                )
            """)

            # Write individual diagnostic rows
            for d in diagnostics:
                conn.execute("""
                    INSERT INTO vscode_diagnostic_log
                        (timestamp, file_name, severity, message, line_number)
                    VALUES (?,?,?,?,?)
                """, (
                    now,
                    file_name,
                    d.get("severity", "").upper(),
                    d.get("message", ""),
                    d.get("line", 0),
                ))

            conn.commit()
        finally:
            conn.close()


# ── Query Skill ───────────────────────────────────────────────────────────────

class AriaVsCodeBridgeSkill:
    """
    Read-only query API over the vscode_workspace_state and vscode_diagnostic_log tables.

    Five APIs:
      get_workspace_snapshot()     → latest state row as dict
      get_active_file()            → active_file path string
      get_diagnostics(limit)       → recent diagnostic log rows
      get_selection()              → current editor selection text
      is_bridge_server_alive()     → True if HTTP server is responding on port 9821
    """

    def __init__(
        self,
        db_path:        str = "aria_orchestrator.db",
        server:         Optional[AriaVsCodeBridgeServer] = None,
    ) -> None:
        self.db_path = db_path
        self.server  = server
        init_vscode_bridge_schema(db_path)

    # ── Public APIs ────────────────────────────────────────────────────────────

    def get_workspace_snapshot(self) -> Optional[Dict[str, Any]]:
        """Return the most recent VS Code workspace state snapshot."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("""
                SELECT * FROM vscode_workspace_state
                ORDER BY id DESC LIMIT 1
            """).fetchone()
            if row is None:
                return None
            result = dict(row)
            # Deserialize JSON fields
            result["open_files"]  = json.loads(result.get("open_files_json") or "[]")
            result["diagnostics"] = json.loads(result.get("diagnostics_json") or "[]")
            return result
        finally:
            conn.close()

    def get_active_file(self) -> Optional[str]:
        """Return just the active file path from the latest snapshot."""
        snap = self.get_workspace_snapshot()
        return snap["active_file"] if snap else None

    def get_diagnostics(self, limit: int = 20, severity: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Return recent diagnostic log rows, optionally filtered by severity
        (ERROR | WARNING | INFO | HINT).
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            if severity:
                rows = conn.execute("""
                    SELECT * FROM vscode_diagnostic_log
                    WHERE severity = ?
                    ORDER BY log_id DESC LIMIT ?
                """, (severity.upper(), limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM vscode_diagnostic_log
                    ORDER BY log_id DESC LIMIT ?
                """, (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_selection(self) -> str:
        """Return the current editor text selection (empty string if nothing selected)."""
        snap = self.get_workspace_snapshot()
        return snap["selection"] if snap else ""

    def is_bridge_server_alive(self) -> bool:
        """Check if the HTTP bridge server is responding on port 9821."""
        try:
            import urllib.request
            url = f"http://{VSCODE_BRIDGE_HOST}:{VSCODE_BRIDGE_PORT}/vscode/ping"
            with urllib.request.urlopen(url, timeout=1) as resp:
                return resp.status == 200
        except Exception:
            return False

    def format_workspace_summary(self) -> str:
        """Return a human-readable summary of the current workspace state."""
        snap = self.get_workspace_snapshot()
        if not snap:
            return (
                "VS Code bridge has no data yet.\n"
                "Make sure the ARIA VS Code extension is installed and VS Code is open."
            )
        import datetime
        ts = datetime.datetime.fromtimestamp(snap["timestamp"]).strftime("%H:%M:%S")
        errors   = snap.get("error_count", 0)
        warnings = snap.get("warning_count", 0)
        diag_str = f"🔴 {errors} error(s)" if errors else "✅ No errors"
        if warnings:
            diag_str += f", ⚠️ {warnings} warning(s)"

        open_files = snap.get("open_files", [])
        open_str = ", ".join(os.path.basename(f) for f in open_files[:5])
        if len(open_files) > 5:
            open_str += f" (+{len(open_files)-5} more)"

        selection = snap.get("selection", "")
        sel_str = repr(selection[:80]) if selection else "(nothing selected)"

        return (
            f"### ARIA VS Code Workspace Status (as of {ts})\n\n"
            f"- **Active File:** `{snap.get('active_file', 'unknown')}`\n"
            f"- **Language:** {snap.get('language_id', 'unknown').upper()}\n"
            f"- **Cursor Line:** {snap.get('cursor_line', 0)}\n"
            f"- **Selection:** {sel_str}\n"
            f"- **Diagnostics:** {diag_str}\n"
            f"- **Git Branch:** `{snap.get('git_branch', 'unknown')}`\n"
            f"- **Open Files:** {open_str or '(none)'}\n"
            f"- **Terminal CWD:** `{snap.get('terminal_cwd', 'unknown')}`"
        )
