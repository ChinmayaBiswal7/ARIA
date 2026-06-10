import unittest
from unittest.mock import MagicMock, patch
import sqlite3
import time

from main import ARIA
from skills.memory_commands import handle_personal_notes_pc_status
from skills.command_router import handle_memory
from brain import Brain

class TestSessionCarryOver(unittest.TestCase):
    def setUp(self):
        self.username = "test_user_session"
        # Clean up database records
        self.db_path = "aria_memory.db"
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS session_summaries")
        conn.commit()
        conn.close()

    def tearDown(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS session_summaries")
        conn.commit()
        conn.close()

    @patch('brain.Brain._think_impl')
    def test_persist_session_summary(self, mock_think):
        mock_think.return_value = "- User improved gesture confirm accuracy\n- Tested system stats command successfully"
        
        # Instantiate minimal ARIA mock/instance
        aria = MagicMock()
        aria.known_user = self.username
        aria.brain = MagicMock()
        aria.brain.chat_history = [
            {"role": "user", "content": "Let's fix gesture controls"},
            {"role": "assistant", "content": "Sure, I have updated the gesture recognizer."}
        ]
        
        # We want _persist_session_summary to use self.brain._think_impl
        aria.brain._think_impl = mock_think
        
        # Call the actual method from ARIA class on our mock/instance
        ARIA._persist_session_summary(aria)
        
        # Verify saved summary in SQLite
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM session_summaries WHERE username = ?", (self.username.lower(),))
        row = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(row)
        self.assertEqual(row["summary"], "- User improved gesture confirm accuracy\n- Tested system stats command successfully")
        self.assertTrue(time.time() - row["updated_at"] < 5.0)

    def test_get_sqlite_context_injection(self):
        # Insert a mock summary into SQLite
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_summaries (
                username TEXT PRIMARY KEY,
                summary TEXT,
                updated_at REAL
            )
        """)
        cursor.execute(
            "INSERT INTO session_summaries (username, summary, updated_at) VALUES (?, ?, ?)",
            (self.username.lower(), "Mocked previous session summary text.", time.time())
        )
        conn.commit()
        conn.close()
        
        # Instantiate Brain and run _get_sqlite_context
        brain = Brain.__new__(Brain)
        context = brain._get_sqlite_context(user_name=self.username)
        
        # Verify context contains the summary block
        self.assertIn("== LAST SESSION SUMMARY ==", context)
        self.assertIn("Mocked previous session summary text.", context)

    def test_last_session_query_routing(self):
        aria = MagicMock()
        aria.known_user = self.username
        aria.normalizer_val = "what did we do last session"
        
        # Insert a mock summary into SQLite
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_summaries (
                username TEXT PRIMARY KEY,
                summary TEXT,
                updated_at REAL
            )
        """)
        cursor.execute(
            "INSERT INTO session_summaries (username, summary, updated_at) VALUES (?, ?, ?)",
            (self.username.lower(), "Built a dragon model.", time.time())
        )
        conn.commit()
        conn.close()
        
        # Test routing through handle_personal_notes_pc_status
        res = handle_personal_notes_pc_status(aria, "what did we do last session", "what did we do last session")
        self.assertEqual(res, "read_last_session_summary")
        aria._speak.assert_called_once_with("Here is a summary of our last session: Built a dragon model.")

        # Test command router integration
        aria._speak.reset_mock()
        res_router = handle_memory(aria, "what did we do last session", "what did we do last session")
        self.assertTrue(res_router["handled"])
        self.assertEqual(res_router["action"], "memory")
        self.assertEqual(res_router["response"], "read_last_session_summary")

if __name__ == "__main__":
    unittest.main()
