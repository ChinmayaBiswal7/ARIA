import unittest
import os
import json
from skills.knowledge_graph import KnowledgeGraph

class TestKnowledgeGraph(unittest.TestCase):

    def setUp(self):
        # Reset the singleton to ensure isolation
        KnowledgeGraph._instance = None
        self.db_path = "test_aria_knowledge.db"
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass
        self.kg = KnowledgeGraph(db_path=self.db_path)

    def tearDown(self):
        # Reset singleton and remove the database file
        KnowledgeGraph._instance = None
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_priority_resolution_node(self):
        # 1. Insert a node from a lower-priority source (conversation: 50)
        self.kg.add_node(
            name="Python",
            node_type="skill",
            properties={"level": "beginner"},
            confidence=0.5,
            source="conversation",
            status="unconfirmed"
        )
        
        node = self.kg.get_node("Python", "skill")
        self.assertEqual(node["source"], "conversation")
        self.assertEqual(node["confidence"], 0.5)
        self.assertEqual(json.loads(node["properties"])["level"], "beginner")

        # 2. Try to update from even lower priority source (window_monitor: 30)
        self.kg.add_node(
            name="Python",
            node_type="skill",
            properties={"level": "novice"},
            confidence=0.4,
            source="window_monitor",
            status="unconfirmed"
        )
        # Should not update properties, but may adjust confidence (max)
        node = self.kg.get_node("Python", "skill")
        self.assertEqual(node["source"], "conversation")
        self.assertEqual(json.loads(node["properties"])["level"], "beginner")

        # 3. Update from higher priority source (voice: 100)
        self.kg.add_node(
            name="Python",
            node_type="skill",
            properties={"level": "expert"},
            confidence=1.0,
            source="voice",
            status="confirmed"
        )
        node = self.kg.get_node("Python", "skill")
        self.assertEqual(node["source"], "voice")
        self.assertEqual(node["status"], "confirmed")
        self.assertEqual(node["confidence"], 1.0)
        self.assertEqual(json.loads(node["properties"])["level"], "expert")

    def test_priority_resolution_fact(self):
        # 1. Insert a fact with conversation (50)
        self.kg.add_fact(
            subject="chinmaya",
            predicate="likes",
            obj="Java",
            confidence=0.6,
            source="conversation",
            status="unconfirmed"
        )
        
        facts = self.kg.get_facts(subject="chinmaya", predicate="likes")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["source"], "conversation")
        self.assertEqual(facts[0]["status"], "unconfirmed")

        # 2. Try to update with window_monitor (30)
        self.kg.add_fact(
            subject="chinmaya",
            predicate="likes",
            obj="Java",
            confidence=0.4,
            source="window_monitor",
            status="unconfirmed"
        )
        facts = self.kg.get_facts(subject="chinmaya", predicate="likes")
        self.assertEqual(facts[0]["source"], "conversation")

        # 3. Update with voice (100)
        self.kg.add_fact(
            subject="chinmaya",
            predicate="likes",
            obj="Java",
            confidence=1.0,
            source="voice",
            status="confirmed"
        )
        facts = self.kg.get_facts(subject="chinmaya", predicate="likes")
        self.assertEqual(facts[0]["source"], "voice")
        self.assertEqual(facts[0]["status"], "confirmed")
        self.assertEqual(facts[0]["confidence"], 1.0)

    def test_status_flags_merging(self):
        # Start unconfirmed
        self.kg.add_node("React", "skill", source="git_scan", status="unconfirmed")
        node = self.kg.get_node("React", "skill")
        self.assertEqual(node["status"], "unconfirmed")

        # Update via voice (confirmed)
        self.kg.add_node("React", "skill", source="voice", status="confirmed")
        node = self.kg.get_node("React", "skill")
        self.assertEqual(node["status"], "confirmed")

        # Update via git_scan again (should keep confirmed status)
        self.kg.add_node("React", "skill", source="git_scan", status="unconfirmed")
        node = self.kg.get_node("React", "skill")
        self.assertEqual(node["status"], "confirmed")

    def test_lexical_context_injection(self):
        # Insert relevant nodes
        self.kg.add_node("Django", "skill", properties={"description": "Web framework"}, source="voice", status="confirmed")
        self.kg.add_fact("chinmaya", "expert_in", "Django", source="voice", status="confirmed")
        self.kg.add_fact("chinmaya", "studying", "DBMS", source="voice", status="confirmed")

        # Lexical retrieval
        context = self.kg.retrieve_relevant_profile("I need help with my Django web app")
        self.assertIn("Django", context)
        self.assertIn("expert_in", context)
        
        # General briefing fallback when no direct query keywords match
        fallback_context = self.kg.retrieve_relevant_profile("How is the weather today?")
        self.assertIn("DBMS", fallback_context)
        self.assertIn("Django", fallback_context)

    def test_explainable_project_recommendation(self):
        # Insert project nodes
        self.kg.add_node(
            name="ARIA-System",
            node_type="project",
            properties={
                "description": "An intelligent AI assistant using ML models",
                "tags": ["python", "machine_learning", "embeddings"]
            },
            source="git_scan",
            status="unconfirmed"
        )
        self.kg.add_node(
            name="Calculator",
            node_type="project",
            properties={
                "description": "Simple arithmetic calculator",
                "tags": ["java"]
            },
            source="git_scan",
            status="unconfirmed"
        )
        self.kg.add_edge(
            from_name="ARIA-System",
            from_type="project",
            to_name="python",
            to_type="skill",
            relation="uses",
            source="git_scan",
            status="unconfirmed"
        )

        # Query projects matching 'python'
        projects = self.kg.find_relevant_projects("python")
        self.assertTrue(len(projects) > 0)
        self.assertEqual(projects[0]["name"], "ARIA-System")
        self.assertTrue(any("uses" in r or "skill" in r or "tags" in r for r in projects[0]["reasons"]))

        # Query projects matching 'ML'
        projects_ml = self.kg.find_relevant_projects("ML")
        self.assertTrue(len(projects_ml) > 0)
        self.assertEqual(projects_ml[0]["name"], "ARIA-System")
        self.assertTrue(any("description" in r or "ML" in r for r in projects_ml[0]["reasons"]))

if __name__ == "__main__":
    unittest.main()
