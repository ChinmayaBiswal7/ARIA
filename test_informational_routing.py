
import unittest
import sys
import os
from unittest.mock import MagicMock, patch

# Ensure project path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from semantic_router import SemanticRouter
from skills.routing_policy import evaluate_tool_arming, looks_like_information_question


class TestInformationalRouting(unittest.TestCase):
    def setUp(self):
        self.router = SemanticRouter()

    def test_looks_like_information_question(self):
        # 1. Informational queries should return True
        self.assertTrue(looks_like_information_question("Do you know about ITL cricket match? Is it going to happen today or which day?"))
        self.assertTrue(looks_like_information_question("I want you to give me information about IPL cricket match."))
        self.assertTrue(looks_like_information_question("Tell me about IPL"))
        self.assertTrue(looks_like_information_question("Who is Virat Kohli"))
        self.assertTrue(looks_like_information_question("What is Java"))
        self.assertTrue(looks_like_information_question("Explain recursion"))
        self.assertTrue(looks_like_information_question("Is it going to rain today?"))

        # 2. Browser control/action queries should return False
        self.assertFalse(looks_like_information_question("Search google for Virat Kohli"))
        self.assertFalse(looks_like_information_question("search for python tutorials"))
        self.assertFalse(looks_like_information_question("look up stock price of Google"))
        self.assertFalse(looks_like_information_question("Open Cricbuzz"))
        self.assertFalse(looks_like_information_question("Click search box"))
        self.assertFalse(looks_like_information_question("Search Amazon"))

    def test_evaluate_tool_arming_informational(self):
        # High confidence but informational query
        decision = evaluate_tool_arming(
            intent="search",
            confidence=0.90,
            user_input="Do you know about ITL cricket match? Is it going to happen today or which day?"
        )
        # Should not be armed, and reason should be informational_query
        self.assertFalse(decision.armed)
        self.assertEqual(decision.reason, "informational_query")

        # Low confidence informational query should also bypass and be classified as informational_query
        decision2 = evaluate_tool_arming(
            intent="search",
            confidence=0.75,
            user_input="Do you know about ITL cricket match? Is it going to happen today or which day?"
        )
        self.assertFalse(decision2.armed)
        self.assertEqual(decision2.reason, "informational_query")

    @patch('intent_classifier.IntentClassifier.classify')
    def test_requires_clarification_informational(self, mock_classify):
        # Informational queries should not trigger clarification prompts, even at low confidence
        mock_classify.return_value = ("search", 0.75)
        
        routing = self.router.route("Do you know about ITL cricket match? Is it going to happen today or which day?")
        self.assertFalse(routing["tool_armed"])
        self.assertFalse(routing["requires_clarification"])
        self.assertEqual(routing["tool_arm_reason"], "informational_query")

        routing2 = self.router.route("I want you to give me information about IPL cricket match.")
        self.assertFalse(routing2["tool_armed"])
        self.assertFalse(routing2["requires_clarification"])
        self.assertEqual(routing2["tool_arm_reason"], "informational_query")

    @patch('intent_classifier.IntentClassifier.classify')
    def test_task_creation_gating(self, mock_classify):
        # 1. Informational questions should not create tasks
        mock_classify.return_value = ("search", 0.75)
        self.router.reset_context()
        routing = self.router.route("I want you to give me information about IPL cricket match.")
        self.assertIsNone(self.router.task_manager.get_active_task())

        routing2 = self.router.route("Do you know about ITL cricket match? Is it going to happen today or which day?")
        self.assertIsNone(self.router.task_manager.get_active_task())

        # 2. Explicit task verbs should create tasks
        mock_classify.return_value = ("search", 0.90)
        self.router.reset_context()
        routing3 = self.router.route("Track IPL scores.")
        self.assertIsNotNone(self.router.task_manager.get_active_task())
        self.assertEqual(self.router.task_manager.get_active_task().goal.lower(), "track ipl scores.")

        mock_classify.return_value = ("search", 0.90)
        self.router.reset_context()
        routing4 = self.router.route("Search today's IPL match schedule.")
        self.assertIsNotNone(self.router.task_manager.get_active_task())
        self.assertEqual(self.router.task_manager.get_active_task().goal.lower(), "search today's ipl match schedule.")

        # 3. Browser control commands should create tasks
        mock_classify.return_value = ("browser", 0.95)
        self.router.reset_context()
        routing5 = self.router.route("Open Chrome.")
        self.assertIsNotNone(self.router.task_manager.get_active_task())
        self.assertEqual(self.router.task_manager.get_active_task().goal.lower(), "open chrome.")


if __name__ == "__main__":
    unittest.main()
