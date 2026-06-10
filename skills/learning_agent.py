from typing import Dict, Any
from skills.base_agent import BaseAgent
from skills.blackboard import AriaBlackboard
import json
import re

class AriaLearningAgent(BaseAgent):
    def __init__(self, aria_instance=None):
        super().__init__("LearningAgent", aria_instance)

    @property
    def aria_inst(self):
        if self.aria is None:
            try:
                from skills.agent_orchestrator import AriaMultiAgentOrchestrator
                self.aria = AriaMultiAgentOrchestrator().aria
            except Exception:
                pass
        return self.aria

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        self.log_state_shift("RUNNING", "Reading career gaps from blackboard...")
        
        # Instantiate blackboard
        bb = getattr(self.aria_inst, "blackboard", None)
        if bb is None or type(bb).__name__ in ('MagicMock', 'Mock'):
            bb = AriaBlackboard()
            
        # 1. Read the career entry from blackboard based on company_name
        company_name = payload.get("company_name", "").lower().strip()
        if company_name:
            key = f"{company_name.replace(' ', '_')}_gap_analysis"
            gap_data = bb.read(topic="career", key=key)
        else:
            # Fallback to scan all keys under career
            all_career = bb.get_all(topic="career")
            gap_data = None
            if "career" in all_career:
                keys = list(all_career["career"].keys())
                if keys:
                    gap_data = all_career["career"][keys[0]]["value"]
                    company_name = gap_data.get("company", "Target Company")
                    
        if not gap_data:
            self.log_state_shift("IDLE", "No gap analysis found on blackboard.")
            return json.dumps({"error": "No career gap analysis data found on blackboard."})
            
        missing_skills = gap_data.get("missing_skills") or gap_data.get("missingskills") or []
        company = gap_data.get("company", "Target Company")
        role = gap_data.get("role", "Software Engineering Intern")
        
        if not missing_skills:
            self.log_state_shift("IDLE", "No skill gaps to address.")
            return json.dumps({
                "message": f"No missing skills found for {role} at {company}."
            })
            
        self.log_state_shift("RUNNING", f"Generating learning roadmap for gaps: {missing_skills}")
        
        # 2. Use LLM to create study roadmap and project suggestion
        prompt = f"""
        You are the Learning Agent for ARIA.
        The user has career gaps for the position of {role} at {company}.
        Missing Skills / Gaps: {missing_skills}
        
        Create a detailed study roadmap and a concrete portfolio project suggestion to bridge these gaps.
        
        CRITICAL: Do NOT use raw double quotes inside JSON string values. Use single quotes instead if you need to quote terms (e.g. write 'hooks' instead of \"hooks\").
        
        Provide the response as exactly a raw JSON object (no markdown formatting blocks like ```json).
        The JSON object schema:
        {{
            "company": "{company}",
            "role": "{role}",
            "missing_skills": {json.dumps(missing_skills)},
            "study_roadmap": [
                {{
                    "skill": "skill name",
                    "week_1": "Description of what to study",
                    "week_2": "Hands-on implementation task"
                }}
            ],
            "project_suggestion": {{
                "title": "Concrete project title matching gaps",
                "description": "Project description",
                "tech_stack": ["React", "FastAPI"],
                "deliverables": [
                    "Deliverable 1",
                    "Deliverable 2"
                ]
            }}
        }}
        """
        clean = ""
        raw_res = ""
        try:
            raw_res = self.aria_inst.brain.think(prompt).strip()
            # Clean formatting
            match = re.search(r"(\{.*\})", raw_res, re.DOTALL)
            if match:
                clean = match.group(1).strip()
            else:
                for marker in ("```json", "```"):
                    if raw_res.startswith(marker):
                        raw_res = raw_res[len(marker):]
                    if raw_res.endswith("```"):
                        raw_res = raw_res[:-3]
                clean = raw_res.strip()
                
            roadmap_data = json.loads(clean)
            
            # Normalize and reconstruct keys to restore underscores stripped by brain._clean()
            normalized_roadmap = []
            raw_roadmap = roadmap_data.get("study_roadmap") or roadmap_data.get("studyroadmap") or []
            for item in raw_roadmap:
                normalized_roadmap.append({
                    "skill": item.get("skill", ""),
                    "week_1": item.get("week_1") or item.get("week1", ""),
                    "week_2": item.get("week_2") or item.get("week2", "")
                })
                
            raw_proj = roadmap_data.get("project_suggestion") or roadmap_data.get("projectsuggestion") or {}
            normalized_proj = {
                "title": raw_proj.get("title", "Portfolio Project"),
                "description": raw_proj.get("description", ""),
                "tech_stack": raw_proj.get("tech_stack") or raw_proj.get("techstack") or [],
                "deliverables": raw_proj.get("deliverables") or []
            }
            
            clean_roadmap = {
                "company": roadmap_data.get("company", company),
                "role": roadmap_data.get("role", role),
                "missing_skills": roadmap_data.get("missing_skills") or roadmap_data.get("missingskills") or missing_skills,
                "study_roadmap": normalized_roadmap,
                "project_suggestion": normalized_proj
            }
            
            # 3. Publish learning roadmap back to blackboard
            dest_key = f"{company.lower().replace(' ', '_')}_learning_roadmap"
            bb.publish(
                topic="learning",
                key=dest_key,
                value=clean_roadmap,
                source=self.agent_name,
                ttl_hours=24
            )
            self.log_state_shift("IDLE", f"Learning roadmap successfully published for {company}.")
            return json.dumps(clean_roadmap)
        except Exception as e:
            print(f"[LearningAgent Debug] Raw response from brain: {raw_res}")
            print(f"[LearningAgent Debug] Cleaned string: {clean}")
            self.log_state_shift("IDLE", f"Failed to generate study roadmap: {e}")
            return json.dumps({"error": str(e)})
