import unittest
import os
import sqlite3
import json
import time
from unittest.mock import MagicMock, patch
from skills.context_skill import AriaDesktopPerceptionService, WindowEvent
from ui_control import capture_desktop_perception_snapshot

class TestAriaDesktopPerceptionService(unittest.TestCase):
    def setUp(self):
        self.db_path = "test_desktop_service.db"
        self.mock_aria = MagicMock()
        self.mock_aria.broker = MagicMock()
        
        self.service = AriaDesktopPerceptionService(self.mock_aria, self.db_path)
        self.service.accessibility_cache.clear()
        self.service.last_pid = -1
        self.service.last_app = "IDLE"
        self.service.last_title = ""
        self.service.last_shift_timestamp = time.time()

        # Build local timeline tables natively
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS vision_event_timeline (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER, event_description TEXT, sequence_duration_seconds INTEGER)")
            conn.commit()

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_debouncing_and_lru_cache_bounds_enforce_performance_limits(self):
        # ── TEST STEP 1: VERIFY WINDOW DEBOUNCING ───────────────────────────
        event_init = WindowEvent(pid=101, app_name="code.exe", window_title="VS Code - loading...")
        self.assertTrue(self.service.process_window_focus_event(event_init))

        # Simulate a rapid title change 0.5 seconds later within the same PID
        event_rapid = WindowEvent(pid=101, app_name="code.exe", window_title="Visual Studio Code - main.py")
        # The service must debounce and reject this rapid noise update to optimize processing loops
        self.assertFalse(self.service.process_window_focus_event(event_rapid))

        # ── TEST STEP 2: VERIFY DUAL WHITELIST CLASSIFICATION ──────────────
        # Spotify should match the focus tracker but skip heavy tree extractions
        event_spotify = capture_desktop_perception_snapshot(pid=202, app_exe_name="spotify.exe", window_title="Spotify")
        self.assertEqual(len(event_spotify.accessibility_tree.get("buttons", [])), 0)

        # VS Code should trigger a full structural tree crawl
        with patch('ui_control._crawl_window_tree', return_value={"buttons": ["Run Task", "Debug Program"], "active_tabs": ["main.py"], "input_fields": []}):
            event_vscode = capture_desktop_perception_snapshot(pid=101, app_exe_name="code.exe", window_title="VS Code - main.py")
            self.assertGreater(len(event_vscode.accessibility_tree.get("buttons", [])), 0)

        # ── TEST STEP 3: VERIFY MINIMAL LRU CACHE EVICTION SIZE LIMITS ──────
        self.service.MAX_CACHE_ENTRIES = 2
        self.service.process_window_focus_event(event_vscode) # Inserts cache 1
        
        event_chrome = WindowEvent(pid=303, app_name="chrome.exe", window_title="Chrome", accessibility_tree={"buttons": ["New Tab"]})
        self.service.process_window_focus_event(event_chrome) # Inserts cache 2
        
        event_edge = WindowEvent(pid=404, app_name="msedge.exe", window_title="Edge", accessibility_tree={"buttons": ["Home"]})
        self.service.process_window_focus_event(event_edge) # Inserts cache 3 (Triggers eviction of oldest item)

        # Verify that the oldest cached item (VS Code) was evicted cleanly to respect memory limits
        self.assertEqual(len(self.service.get_cached_accessibility_tree(101, "code.exe")), 0)
        # Ensure newer entries remain active in the service memory store
        self.assertGreater(len(self.service.get_cached_accessibility_tree(404, "msedge.exe")), 0)

if __name__ == "__main__":
    unittest.main()
