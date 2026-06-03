import unittest
from unittest.mock import MagicMock
from skills.security_guard import SecurityGuard

class TestSecurityRoles(unittest.TestCase):
    def setUp(self):
        self.mock_mm = MagicMock()
        self.mock_mm.db_path = "aria_memory.db"
        self.security = SecurityGuard(memory_manager=self.mock_mm)

    def test_get_user_access_level_owner(self):
        self.assertEqual(self.security.get_user_access_level("chinmay"), SecurityGuard.LEVEL_OWNER)
        self.assertEqual(self.security.get_user_access_level("chinmay."), SecurityGuard.LEVEL_OWNER)
        self.assertEqual(self.security.get_user_access_level("chinmaya"), SecurityGuard.LEVEL_OWNER)

    def test_get_user_access_level_guest(self):
        self.assertEqual(self.security.get_user_access_level(None), SecurityGuard.LEVEL_GUEST)
        self.assertEqual(self.security.get_user_access_level("unknown"), SecurityGuard.LEVEL_GUEST)
        self.assertEqual(self.security.get_user_access_level("guest"), SecurityGuard.LEVEL_GUEST)

    def test_verify_agent_action_tag_guest(self):
        # In Guest mode (LEVEL_GUEST), no actions are safe
        safe, msg = self.security.verify_agent_action_tag("[OPEN: Chrome]", user_name="guest")
        self.assertFalse(safe)
        self.assertIn("requires Trusted User", msg)

    def test_verify_agent_action_tag_trusted(self):
        # A trusted user (LEVEL_TRUSTED) can open apps but not run shell/shutdown
        safe, msg = self.security.verify_agent_action_tag("[OPEN: Chrome]", user_name="random_user")
        self.assertTrue(safe)
        
        safe, msg = self.security.verify_agent_action_tag("[SHUTDOWN]", user_name="random_user")
        self.assertFalse(safe)
        self.assertIn("requires Owner", msg)

if __name__ == "__main__":
    unittest.main()
