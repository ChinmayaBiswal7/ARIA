import unittest
from unittest.mock import MagicMock, patch
import json
import os
from skills.screen_triage import AriaScreenTriage

class TestAriaScreenTriage(unittest.TestCase):
    def setUp(self):
        self.triage = AriaScreenTriage()
        self.triage.pending_fix = None

    @patch('skills.active_context.ActiveContext')
    def test_file_resolution_from_active_context(self, mock_ctx_class):
        mock_ctx = mock_ctx_class.return_value
        mock_ctx.active_file = r"C:\D FOLDER\Projects\AI\main.py"
        
        resolved = self.triage.resolve_file_path("main.py")
        self.assertEqual(resolved, r"C:\D FOLDER\Projects\AI\main.py")

    def test_triage_low_confidence(self):
        mock_aria = MagicMock()
        mock_aria.context_skill.get_active_window.return_value = "VS Code"
        mock_aria.sandbox_safety.is_perception_allowed.return_value = True
        
        low_conf_json = {
            "error_found": True,
            "error_type": "SyntaxError",
            "confidence": 0.5,
            "file_name": "main.py",
            "line_number": 10,
            "explanation": "Low confidence issue",
            "original_code": "print(",
            "corrected_code": "print()"
        }
        mock_aria.brain.think.return_value = json.dumps(low_conf_json)
        
        with patch.object(self.triage, 'resolve_file_path', return_value=r"C:\D FOLDER\Projects\AI\main.py"):
            res = self.triage.triage_active_screen(mock_aria)
            self.assertEqual(res, "Triage complete.")
            self.assertIsNone(self.triage.pending_fix)

    def test_patch_rollback_on_failed_compile(self):
        mock_aria = MagicMock()
        test_file = "test_sandbox_file.py"
        
        if os.path.exists(test_file):
            os.remove(test_file)
            
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("def func():\n    print('Hello')\n")
            
        self.triage.pending_fix = {
            "file_path": test_file,
            "line_number": 2,
            "original_code": "    print('Hello')",
            "corrected_code": "    print('Hello' # syntax error",
            "explanation": "Broken print",
            "confidence": 0.9,
            "error_type": "SyntaxError"
        }
        
        res = self.triage.apply_fix(mock_aria)
        self.assertEqual(res, "Validation failed, rolled back.")
        
        with open(test_file, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("print('Hello')", content)
        self.assertNotIn("# syntax error", content)
        
        if os.path.exists(test_file):
            os.remove(test_file)

if __name__ == "__main__":
    unittest.main()
