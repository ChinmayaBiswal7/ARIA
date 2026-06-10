import unittest
from unittest.mock import MagicMock, patch
import sqlite3
import time
import os
from skills.proactive_governor import AriaProactiveGovernor

class TestAriaProactiveGovernor(unittest.TestCase):
    def setUp(self):
        self.db_path = "test_governor_memory.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
            
        self.governor = AriaProactiveGovernor(db_path=self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_receptiveness_persistence(self):
        self.assertEqual(self.governor.get_receptiveness_score(), 5.0)
        
        self.governor.set_receptiveness_score(7.5)
        self.assertEqual(self.governor.get_receptiveness_score(), 7.5)

    def test_feedback_adjustments(self):
        self.governor.set_receptiveness_score(5.0)
        
        self.governor.log_feedback("shut up and be quiet")
        self.assertEqual(self.governor.get_receptiveness_score(), 4.0)
        
        self.governor.log_feedback("thanks that was helpful")
        self.assertEqual(self.governor.get_receptiveness_score(), 5.0)

    def test_alert_suppression_under_threshold(self):
        self.governor.set_receptiveness_score(2.5)
        mock_aria = MagicMock()
        
        res = self.governor.evaluate_context(mock_aria, "Valorant")
        self.assertIsNone(res)

    def test_gaming_alert_trigger(self):
        self.governor.set_receptiveness_score(6.0)
        mock_aria = MagicMock()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS life_calendar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                day_of_week TEXT,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL,
                associated_goal TEXT,
                criticality INTEGER DEFAULT 5
            )
        """)
        current_time = int(time.time())
        exam_time = current_time + 172800
        cursor.execute(
            "INSERT INTO life_calendar (timestamp, event_type, title) VALUES (?, 'academic_exam', 'DBMS Midterm')",
            (exam_time,)
        )
        conn.commit()
        conn.close()
        
        res = self.governor.evaluate_context(mock_aria, "Valorant")
        self.assertIsNotNone(res)
        self.assertIn("DBMS Midterm", res)
        self.assertTrue(mock_aria.safe_speak.called)

if __name__ == "__main__":
    unittest.main()
