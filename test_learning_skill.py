import unittest
from unittest.mock import MagicMock, patch
import json
import sqlite3
import os
from skills.learning_skill import AriaLearningSkill

class TestAriaLearningSkill(unittest.TestCase):
    def setUp(self):
        self.db_path = "test_learning_skill_memory.db"
        self.skill = AriaLearningSkill(db_path=self.db_path)
        self._init_db()

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS personal_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                content TEXT,
                status TEXT
            )
        """)
        cursor.execute(
            "INSERT INTO personal_notes (category, content, status) VALUES ('DBMS', 'My detailed DBMS notes.', 'active')"
        )
        conn.commit()
        conn.close()

    def test_fetch_notes(self):
        notes = self.skill.fetch_notes("DBMS")
        self.assertEqual(notes, "My detailed DBMS notes.")

    def test_compile_study_sheet(self):
        mock_aria = MagicMock()
        mock_aria.brain.think.return_value = "Compiled high-yield bullet points."
        
        file_name = self.skill.compile_study_sheet(mock_aria, "DBMS", "My notes.", "Search results.")
        self.assertEqual(file_name, "dbms_study_guide.md")
        
        file_path = os.path.join("scratch", file_name)
        self.assertTrue(os.path.exists(file_path))
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, "Compiled high-yield bullet points.")
        
        # Cleanup
        try:
            os.remove(file_path)
        except Exception:
            pass

    def test_orchestrate_study_goal_success(self):
        mock_aria = MagicMock()
        
        mock_json_plan = {
            "goal": "Prepare DBMS quiz",
            "priority": "high",
            "steps": [
                {"subtask_name": "Find DBMS notes", "type": "notes", "target": "DBMS", "scheduled_delay_seconds": None},
                {"subtask_name": "Search quiz topics", "type": "search", "target": "DBMS quiz questions", "scheduled_delay_seconds": None},
                {"subtask_name": "Compile study guide", "type": "summarize", "target": "DBMS", "scheduled_delay_seconds": None},
                {"subtask_name": "Schedule review", "type": "reminder", "target": "Review DBMS", "scheduled_delay_seconds": 3600}
            ]
        }
        mock_aria.brain.think.return_value = json.dumps(mock_json_plan)
        mock_aria.search_and_read.return_value = "Mock search results"
        
        res = self.skill.orchestrate_study_goal(mock_aria, "Prepare DBMS quiz")
        self.assertEqual(res, "Orchestration complete.")
        
        self.assertTrue(mock_aria.search_and_read.called)
        self.assertTrue(mock_aria.brain.think.called)
        self.assertTrue(mock_aria.memory_skill.add_reminder.called)

if __name__ == "__main__":
    unittest.main()
