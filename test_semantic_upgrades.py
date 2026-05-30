import unittest
import time
import os
import sys

# Ensure current directory is in path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from intent_classifier import IntentClassifier
from semantic_router import SemanticRouter
from active_task_manager import ActiveTask, TaskObject, ActiveTaskManager
from brain import Brain
from skills.routing_policy import evaluate_tool_arming, is_actionable_execution_request, is_site_action_request

class TestSemanticUpgrades(unittest.TestCase):

    def setUp(self):
        self.classifier = IntentClassifier()
        self.router = SemanticRouter()
        self.brain = Brain()

    def test_repair_intent_classification(self):
        """Verify conversational repair intent classification and dynamic confidence scoring."""
        repair_queries = [
            ("No wait", 0.98),
            ("stop stop", 0.98),
            ("actually i meant search for python", 0.98),
            ("wait", 0.85)
        ]
        for query, expected_min_conf in repair_queries:
            intent, confidence = self.classifier.classify(query)
            self.assertEqual(intent, "repair")
            self.assertTrue(confidence >= expected_min_conf, f"Failed confidence check for '{query}': {confidence} < {expected_min_conf}")

    def test_followup_ambiguity_classification(self):
        """Verify expanded followup patterns including positional and step references."""
        followup_queries = [
            "the second one",
            "open the first result",
            "go back to the previous step",
            "not this one",
            "go back"
        ]
        for query in followup_queries:
            intent, confidence = self.classifier.classify(query)
            self.assertEqual(intent, "followup", f"Query '{query}' was classified as {intent} instead of followup")

    def test_conversational_guard_blocks_search(self):
        """Smalltalk must stay conversational and never become browser/search routing."""
        smalltalk_queries = [
            "How are you?",
            "hello ARIA",
            "what's up",
            "thank you",
        ]
        for query in smalltalk_queries:
            intent, confidence = self.classifier.classify(query)
            self.assertEqual(intent, "chat", f"Query '{query}' should remain chat")
            self.assertGreaterEqual(confidence, 0.90)

            routing = self.router.route(query)
            self.assertEqual(routing["intent"], "chat")
            self.assertTrue(routing["skip_web_search"])
            self.assertFalse(routing["allow_web_search"])
            self.assertEqual(routing["action_type"], "general_chat")

    def test_tool_arming_policy_blocks_conversation(self):
        """Runtime policy, not the LLM, authorizes tool execution."""
        decision = evaluate_tool_arming("chat", 0.99, "How are you?", explicit_tool_signal=True)
        self.assertFalse(decision.armed)
        self.assertEqual(decision.reason, "conversation_guard")

    def test_tool_arming_policy_allows_explicit_search(self):
        """Explicit high-confidence searches can arm browser/search tools."""
        routing = self.router.route("search for python tutorials")
        self.assertEqual(routing["intent"], "search")
        self.assertTrue(routing["tool_armed"])
        self.assertEqual(routing["tool_arm_reason"], "explicit_high_confidence_tool_intent")

    def test_tool_arming_policy_clarifies_unarmed_tool_intent(self):
        """Tool-like intents without enough confidence/context should ask clarification."""
        decision = evaluate_tool_arming("search", 0.50, "news", explicit_tool_signal=False)
        self.assertFalse(decision.armed)
        self.assertEqual(decision.reason, "low_tool_confidence")

    def test_i_want_to_action_is_not_goal_storage(self):
        """Immediate action requests with 'I want to' must not be treated as stored goals."""
        self.assertTrue(is_actionable_execution_request(
            "I want to buy something from Amazon. I want to buy keyboards. Can you open it and search?"
        ))
        self.assertFalse(is_actionable_execution_request("I want to be more consistent with studying"))
        self.assertFalse(is_actionable_execution_request("I want to start exercising every morning"))
        self.assertFalse(is_actionable_execution_request("I want to please my parents"))

    def test_site_action_beats_followup_pronoun(self):
        """Site-scoped corrections should not resolve 'it' to random page objects."""
        self.assertTrue(is_site_action_request("Search it in Amazon, not normal search."))
        intent, confidence = self.classifier.classify("Search it in Amazon, not normal search.")
        self.assertEqual(intent, "search")
        self.assertGreaterEqual(confidence, 0.90)

    def test_active_task_priority_states(self):
        """Verify ActiveTask priority/state methods."""
        task = ActiveTask(goal="Test Task")
        self.assertEqual(task.status, "CREATED")
        
        task.start_running()
        self.assertEqual(task.status, "RUNNING")
        
        task.pause_task()
        self.assertEqual(task.status, "INTERRUPTED")
        
        task.resume_task()
        self.assertEqual(task.status, "RUNNING")
        
        task.wait_task()
        self.assertEqual(task.status, "WAITING")
        
        task.cancel_task()
        self.assertEqual(task.status, "CANCELLED")
        
        task.complete_task()
        self.assertEqual(task.status, "COMPLETED")
        
        task.fail_task(reason="Mock error", failure_type="FAILED_TIMEOUT")
        self.assertEqual(task.status, "FAILED")
        self.assertEqual(task.result, "[FAILED_TIMEOUT] Mock error")

    def test_active_task_tracing(self):
        """Verify ActiveTask UUID, parent-child links, timing, and trace graphs."""
        parent = ActiveTask(goal="Parent Task")
        child = ActiveTask(goal="Child Task", parent_id=parent.task_id)
        
        self.assertIsNotNone(parent.task_id)
        self.assertIsNotNone(child.task_id)
        self.assertEqual(child.parent_id, parent.task_id)
        
        step = child.add_step(action="navigate", target="google.com")
        self.assertEqual(step.status, "in_progress")
        self.assertIsNotNone(step.start_time)
        
        step.record_retry(reason="Timeout occurred")
        self.assertEqual(step.retry_count, 1)
        self.assertEqual(step.retry_reason, "Timeout occurred")
        
        child.complete_step(result="Loaded successfully")
        self.assertEqual(step.status, "completed")
        self.assertIsNotNone(step.duration)
        
        trace = child.get_trace_graph()
        self.assertIn("Child Task", trace)
        self.assertIn("Step 0: navigate google.com", trace)
        self.assertIn("completed", trace)
        self.assertIn("Retries: 1", trace)

    def test_reference_expiration(self):
        """Verify that objects older than the reference timeout expire."""
        manager = ActiveTaskManager()
        task = manager.start_task(goal="Find documentation")
        
        # Add valid object
        obj1 = TaskObject(id="link_1", type="link", name="Valid Link")
        task.add_object(obj1)
        
        # Add expired object (simulated via 150s old timestamp)
        obj2 = TaskObject(id="link_2", type="link", name="Expired Link")
        obj2.timestamp = time.time() - 150.0
        task.add_object(obj2)
        
        # Resolving direct reference should resolve to valid object
        resolved = manager.resolve_object_reference("that")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.id, "link_1")
        
        # Resolving expired object directly should return None
        resolved_expired = manager.resolve_object_reference("link_2")
        self.assertIsNone(resolved_expired, "Expired reference was incorrectly resolved")

    def test_conversational_repair_and_decomposition(self):
        """Verify that repair cancel tasks and multi-intent queries decompose recursively."""
        # 1. Start active task
        self.brain.semantic_router.task_manager.start_task(goal="Browse Amazon")
        active_task = self.brain.semantic_router.task_manager.get_active_task()
        self.assertIsNotNone(active_task)
        self.assertEqual(active_task.status, "RUNNING")

        # 2. Trigger repair command
        # Verify that it cancels task
        response = self.brain.think("No wait, stop stop")
        self.assertEqual(active_task.status, "CANCELLED")
        self.assertIn("stopped the active task", response.lower())

        # 3. Verify multi-intent repair decomposition
        # Mock active task and AgentPlanner state
        from skills.agent_planner import AgentPlanner
        planner = AgentPlanner(self.brain)
        planner.cancel_task = False
        
        new_task = self.brain.semantic_router.task_manager.start_task(goal="Browse Amazon")
        # Run multi-intent repair utterance
        response_decomp = self.brain.think("No wait, stop this and what is my name")
        # Verify active task got cancelled
        self.assertEqual(new_task.status, "CANCELLED")
        self.assertTrue(planner.cancel_task)
        
        # Verify remaining query ("what is my name") was routed and processed (should recognize or fallback)
        self.assertIsNotNone(response_decomp)

    def test_low_confidence_clarification(self):
        """Verify that routing decision with low confidence triggers clarification prompt."""
        # Query that is deliberately ambiguous but might trigger search/browser (e.g. just news)
        # We can mock route return or trigger low confidence by using a weak/unsupported intent keyword
        # Let's mock a query with a low confidence intent
        # Or construct a routing decision directly and test brain's routing logic
        routing_decision = {
            "intent": "search",
            "intent_confidence": 0.50, # below search threshold of 0.70
            "intent_metadata": self.classifier.get_intent_metadata("search"),
            "action_type": "web_search",
            "original_query": "news",
            "normalized_query": "News."
        }
        self.brain._current_routing_decision = routing_decision
        
        # Let's bypass routing classification by running brain's implementation directly
        # and checking if it intercepts low confidence
        res = self.brain._think_impl("news")
        self.assertIn("clarify what you'd like me to do", res)

if __name__ == "__main__":
    unittest.main()
