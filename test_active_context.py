import unittest
from skills.active_context import ActiveContext

class TestActiveContext(unittest.TestCase):
    def test_singleton_behavior(self):
        ctx1 = ActiveContext()
        ctx2 = ActiveContext()
        self.assertIs(ctx1, ctx2)

    def test_state_persistence(self):
        ctx = ActiveContext()
        ctx.current_goal = "Test Goal"
        ctx.active_file = "test.py"
        
        ctx_new = ActiveContext()
        self.assertEqual(ctx_new.current_goal, "Test Goal")
        self.assertEqual(ctx_new.active_file, "test.py")

    def test_reset(self):
        ctx = ActiveContext()
        ctx.current_goal = "Some Goal"
        ctx.reset()
        self.assertIsNone(ctx.current_goal)
        self.assertIsNone(ctx.active_file)

if __name__ == "__main__":
    unittest.main()
