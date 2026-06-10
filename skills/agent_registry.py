class AriaAgentRegistry:
    """Registry to keep track of specialized agents."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AriaAgentRegistry, cls).__new__(cls)
            cls._instance.agents = {}
        return cls._instance

    def register(self, agent_name: str, agent_instance):
        self.agents[agent_name.lower()] = agent_instance
        print(f"[AgentRegistry] Registered agent: '{agent_name}'")

    def get(self, agent_name: str):
        return self.agents.get(agent_name.lower())

    def get_capable_agents(self, goal: str) -> list:
        """Component P15: Registry discovery to select agents capable of assisting with the goal."""
        goal_lower = goal.lower()
        capable = []
        # Mapping keyword selectors to registered agent names
        mapping = {
            "careeragent": ["career", "job", "internship", "resume", "placement", "interview"],
            "researchagent": ["research", "market", "trend", "metrics", "find", "java", "dsa", "security", "spring"],
            "habitintelligenceagent": ["habit", "time", "schedule", "routine", "productivity", "focus"],
            "codesearchagent": ["code", "develop", "build", "program", "architecture", "module"],
            "learningagent": ["study", "learn", "course", "exam", "documentation"]
        }
        for agent_name, keywords in mapping.items():
            if any(kw in goal_lower for kw in keywords):
                if agent_name.lower() in self.agents:
                    capable.append(agent_name)
        # Fallback to defaults if no matches found
        if not capable:
            capable = ["researchagent", "habitintelligenceagent"]
        return capable

# Global registry instance
registry = AriaAgentRegistry()

# Standard wrappers for registered agents
class GitHubAgent:
    def __init__(self):
        from skills.career_agent import CareerAgent
        self.career_agent = CareerAgent()

    def run(self, target: str, task_description: str = "") -> str:
        return self.career_agent.get_github_stats(target)

class NewsAgent:
    def run(self, target: str, task_description: str = "") -> str:
        import urllib.request
        import json
        import urllib.parse
        news_snippets = []
        try:
            q_enc = urllib.parse.quote(target)
            hn_url = f"https://hn.algolia.com/api/v1/search?query={q_enc}&tags=story&hitsPerPage=5"
            req = urllib.request.Request(hn_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                hn_data = json.loads(resp.read().decode("utf-8"))
                for hit in hn_data.get("hits", []):
                    title = hit.get("title", "")
                    url_val = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
                    points = hit.get("points", 0)
                    news_snippets.append(f"• {title} ({points} pts) – {url_val}")
        except Exception as hn_err:
            return f"Failed to fetch news: {hn_err}"
        return "\n".join(news_snippets) if news_snippets else "No news found."

class BrowserAgent:
    def run(self, target: str, task_description: str = "") -> str:
        return NewsAgent().run(target, task_description)

class CareerAgentWrapper:
    def __init__(self):
        self._career_agent = None

    @property
    def career_agent(self):
        if self._career_agent is None:
            from skills.career_agent import CareerAgent
            self._career_agent = CareerAgent()
        return self._career_agent

    def run(self, target: str, task_description: str = "") -> str:
        desc = (task_description or "").lower()
        targ = (target or "").lower()
        if "search" in desc or "find" in desc or "search" in targ or "find" in targ:
            jobs = self.career_agent.search_job_opportunities(target)
            summary_list = []
            for j in jobs[:3]:
                tags_str = ", ".join(j.get("tags", [])) if j.get("tags") else ""
                job_desc = (
                    f"Role: {j['role']}\n"
                    f"Company: {j['company']}\n"
                    f"Location: {j.get('location', 'Remote')}\n"
                    f"Skills / Tags: {tags_str or 'software engineering'}\n"
                    f"Category: tech/software development"
                )
                match_res = self.career_agent.match_resume_to_job(job_desc)
                score = match_res.get("match_score", 50)
                
                self.career_agent.add_opportunity(
                    company=j["company"],
                    role=j["role"],
                    location=j.get("location"),
                    apply_link=j.get("apply_link"),
                    match_score=float(score),
                    status="bookmarked",
                    source_type="IMPORT"
                )
                summary_list.append(f"- {j['role']} at {j['company']} (Match Score: {score}%) -> Link: {j.get('apply_link')}")
            return f"Career Search for '{target}':\n" + "\n".join(summary_list) if summary_list else f"No job opportunities found for '{target}'."
        else:
            opps = self.career_agent.get_opportunities()
            return f"Career opportunities list has {len(opps)} tracked items."

# Register default agents
from skills.base_agent import BaseAgent

class CareerIntelligenceWrapper(BaseAgent):
    def __init__(self):
        super().__init__("CareerAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.career_intelligence import AriaCareerIntelligence
            self._agent = AriaCareerIntelligence()
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        return self.agent.run(task_id, task_description, payload, campaign_id)

class LearningAgentWrapper(BaseAgent):
    def __init__(self):
        super().__init__("LearningAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.learning_agent import AriaLearningAgent
            self._agent = AriaLearningAgent()
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        return self.agent.run(task_id, task_description, payload, campaign_id)

class ErrorAnalyzerWrapper(BaseAgent):
    def __init__(self):
        super().__init__("ErrorAnalyzerAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.error_analyzer import AriaErrorAnalyzer
            self._agent = AriaErrorAnalyzer()
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        return self.agent.run(task_id, task_description, payload, campaign_id)

class TestRunnerWrapper(BaseAgent):
    def __init__(self):
        super().__init__("TestRunnerAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.test_runner import AriaTestRunner
            self._agent = AriaTestRunner()
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        return self.agent.run(task_id, task_description, payload, campaign_id)

class RootCauseAnalyzerWrapper(BaseAgent):
    def __init__(self):
        super().__init__("RootCauseAnalyzerAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.root_cause_analyzer import AriaRootCauseAnalyzer
            self._agent = AriaRootCauseAnalyzer()
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        return self.agent.run(task_id, task_description, payload, campaign_id)

class PatchPlannerWrapper(BaseAgent):
    def __init__(self):
        super().__init__("PatchPlannerAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.patch_planner import AriaPatchPlanner
            self._agent = AriaPatchPlanner()
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        return self.agent.run(task_id, task_description, payload, campaign_id)

class PatchGeneratorWrapper(BaseAgent):
    def __init__(self):
        super().__init__("PatchGeneratorAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.patch_generator import AriaPatchGenerator
            self._agent = AriaPatchGenerator()
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        return self.agent.run(task_id, task_description, payload, campaign_id)

class SandboxValidatorWrapper(BaseAgent):
    def __init__(self):
        super().__init__("SandboxValidatorAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.sandbox_validator import AriaSandboxValidator
            self._agent = AriaSandboxValidator()
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        return self.agent.run(task_id, task_description, payload, campaign_id)

class ApprovalWorkflowWrapper(BaseAgent):
    def __init__(self):
        super().__init__("ApprovalWorkflowAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.approval_workflow import AriaApprovalWorkflow
            self._agent = AriaApprovalWorkflow()
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        return self.agent.run(task_id, task_description, payload, campaign_id)

class PatchApplicationWrapper(BaseAgent):
    def __init__(self):
        super().__init__("PatchApplicationAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.patch_application import AriaPatchApplication
            self._agent = AriaPatchApplication()
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        return self.agent.run(task_id, task_description, payload, campaign_id)

class VisionAgentWrapper(BaseAgent):
    def __init__(self):
        super().__init__("VisionAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.vision_agent import AriaVisionAgent
            self._agent = AriaVisionAgent()
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        return self.agent.run(task_id, task_description, payload, campaign_id)

class KnowledgeSearchAgentWrapper(BaseAgent):
    def __init__(self):
        super().__init__("KnowledgeSearchAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.knowledge_search_agent import AriaKnowledgeSearchAgent
            self._agent = AriaKnowledgeSearchAgent(self.aria)
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        if self._agent is not None:
            self._agent.aria = self.aria
        return self.agent.run(task_id, task_description, payload, campaign_id)

class CodeSearchAgentWrapper(BaseAgent):
    def __init__(self):
        super().__init__("CodeSearchAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.code_search_agent import AriaCodeSearchAgent
            self._agent = AriaCodeSearchAgent(self.aria)
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        if self._agent is not None:
            self._agent.aria = self.aria
        return self.agent.run(task_id, task_description, payload, campaign_id)

class ArchitectureAgentWrapper(BaseAgent):
    def __init__(self):
        super().__init__("ArchitectureAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.architecture_agent import AriaArchitectureAgent
            self._agent = AriaArchitectureAgent(self.aria)
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        if self._agent is not None:
            self._agent.aria = self.aria
        return self.agent.run(task_id, task_description, payload, campaign_id)

class ResearchAgentWrapper(BaseAgent):
    def __init__(self):
        super().__init__("ResearchAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.research_agent import AriaResearchAgent
            self._agent = AriaResearchAgent(self.aria)
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        if self._agent is not None:
            self._agent.aria = self.aria
        return self.agent.run(task_id, task_description, payload, campaign_id)

class PlanningAgentWrapper(BaseAgent):
    def __init__(self):
        super().__init__("PlanningAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.task_graph_planner import AriaTaskGraphPlanner
            self._agent = AriaTaskGraphPlanner(self.aria)
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        if self._agent is not None:
            self._agent.aria = self.aria
        return self.agent.run(task_id, task_description, payload, campaign_id)

class GestureAgentWrapper(BaseAgent):
    def __init__(self):
        super().__init__("GestureAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.gesture_agent import AriaGestureAgent
            self._agent = AriaGestureAgent(self.aria)
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        if self._agent is not None:
            self._agent.aria = self.aria
        return self.agent.run(task_id, task_description, payload, campaign_id)

class VisionMemoryAgentWrapper(BaseAgent):
    def __init__(self):
        super().__init__("VisionMemoryAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.vision_memory_agent import AriaVisionMemoryAgent
            self._agent = AriaVisionMemoryAgent(self.aria)
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        if self._agent is not None:
            self._agent.aria = self.aria
        return self.agent.run(task_id, task_description, payload, campaign_id)

class HabitIntelligenceAgentWrapper(BaseAgent):
    def __init__(self):
        super().__init__("HabitIntelligenceAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.habit_intelligence import AriaHabitIntelligence
            self._agent = AriaHabitIntelligence(self.aria)
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        if self._agent is not None:
            self._agent.aria = self.aria
        return self.agent.run(task_id, task_description, payload, campaign_id)

class HabitDatasetMonitorAgentWrapper(BaseAgent):
    def __init__(self):
        super().__init__("HabitDatasetMonitorAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.habit_dataset_monitor import AriaHabitDatasetMonitor
            self._agent = AriaHabitDatasetMonitor(self.aria)
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        if self._agent is not None:
            self._agent.aria = self.aria
        return self.agent.run(task_id, task_description, payload, campaign_id)

class NeuralHabitEngineAgentWrapper(BaseAgent):
    def __init__(self):
        super().__init__("NeuralHabitEngineAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.neural_habit_engine import AriaNeuralHabitEngine
            self._agent = AriaNeuralHabitEngine(self.aria)
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        if self._agent is not None:
            self._agent.aria = self.aria
        return self.agent.run(task_id, task_description, payload, campaign_id)

class PersonalCoachAgentWrapper(BaseAgent):
    def __init__(self):
        super().__init__("PersonalCoachAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.personal_coach import AriaPersonalCoach
            self._agent = AriaPersonalCoach(self.aria)
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        if self._agent is not None:
            self._agent.aria = self.aria
        return self.agent.run(task_id, task_description, payload, campaign_id)

registry.register("careeragent", CareerAgentWrapper())
registry.register("careerintelligence", CareerIntelligenceWrapper())
registry.register("learningagent", LearningAgentWrapper())
registry.register("erroranalyzer", ErrorAnalyzerWrapper())
registry.register("testrunner", TestRunnerWrapper())
registry.register("rootcauseanalyzer", RootCauseAnalyzerWrapper())
registry.register("patchplanner", PatchPlannerWrapper())
registry.register("patchgenerator", PatchGeneratorWrapper())
registry.register("sandboxvalidator", SandboxValidatorWrapper())
registry.register("approvalworkflow", ApprovalWorkflowWrapper())
registry.register("patchapplication", PatchApplicationWrapper())
registry.register("visionagent", VisionAgentWrapper())
registry.register("knowledgesearchagent", KnowledgeSearchAgentWrapper())
registry.register("codesearchagent", CodeSearchAgentWrapper())
registry.register("architectureagent", ArchitectureAgentWrapper())
registry.register("researchagent", ResearchAgentWrapper())
registry.register("planningagent", PlanningAgentWrapper())
registry.register("gestureagent", GestureAgentWrapper())
registry.register("visionmemoryagent", VisionMemoryAgentWrapper())
registry.register("habitdatasetmonitoragent", HabitDatasetMonitorAgentWrapper())
registry.register("neuralhabitengineagent", NeuralHabitEngineAgentWrapper())
registry.register("personalcoachagent", PersonalCoachAgentWrapper())

class ChiefOfStaffAgentWrapper(BaseAgent):
    def __init__(self):
        super().__init__("ChiefOfStaffAgent", None)
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from skills.chief_of_staff_agent import AriaChiefOfStaffAgent
            self._agent = AriaChiefOfStaffAgent(self.aria)
        return self._agent

    def run(self, task_id: str, task_description: str, payload: dict, campaign_id: str = None) -> str:
        if self._agent is not None:
            self._agent.aria = self.aria
        return self.agent.run(task_id, task_description, payload, campaign_id)

registry.register("chiefofstaffagent", ChiefOfStaffAgentWrapper())

habit_wrapper = HabitIntelligenceAgentWrapper()
registry.register("habitintelligenceagent", habit_wrapper)
try:
    _ = habit_wrapper.agent
except Exception as e:
    print(f"[AgentRegistry] Failed to eagerly start HabitIntelligenceAgent: {e}")

coach_wrapper = PersonalCoachAgentWrapper()
registry.register("personalcoachagent", coach_wrapper)
try:
    _ = coach_wrapper.agent
except Exception as e:
    print(f"[AgentRegistry] Failed to eagerly start PersonalCoachAgent: {e}")

cos_wrapper = ChiefOfStaffAgentWrapper()
registry.register("chiefofstaffagent", cos_wrapper)
try:
    _ = cos_wrapper.agent
except Exception as e:
    print(f"[AgentRegistry] Failed to eagerly start ChiefOfStaffAgent: {e}")

registry.register("githubagent", GitHubAgent())
registry.register("newsagent", NewsAgent())
registry.register("browseragent", BrowserAgent())


