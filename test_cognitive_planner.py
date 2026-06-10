import unittest
from unittest.mock import MagicMock, patch
import json
from skills.cognitive_planner import AriaCognitivePlanner

class TestAriaCognitivePlanner(unittest.TestCase):
    def setUp(self):
        self.planner = AriaCognitivePlanner()

    def test_orchestrate_goal_success(self):
        mock_aria = MagicMock()
        
        mock_json_plan = {
            "goal": "Prepare DBMS quiz",
            "priority": "high",
            "steps": [
                {"subtask_name": "Find DBMS notes", "type": "notes", "target": "DBMS index", "scheduled_delay_seconds": None},
                {"subtask_name": "Search quiz topics", "type": "search", "target": "DBMS quiz questions", "scheduled_delay_seconds": None}
            ]
        }
        mock_aria.brain.think.return_value = json.dumps(mock_json_plan)
        mock_aria.search_and_read.return_value = "Mock search results"
        
        with patch.object(self.planner, 'fetch_notes', return_value="Mock notes content"):
            res = self.planner.orchestrate_goal(mock_aria, "Prepare DBMS quiz")
            self.assertEqual(res, "Orchestration complete.")
            
            self.assertTrue(mock_aria.search_and_read.called)
            self.assertTrue(mock_aria.brain.think.called)

if __name__ == "__main__":
    unittest.main()
