import os
import sqlite3
import json
import time
import re
from typing import Dict, Any, List
from skills.base_agent import BaseAgent
from skills.blackboard import AriaBlackboard

CORE_KEYWORDS = [
    "react", "vue", "angular", "next.js", "typescript", "javascript", "html", "css",
    "python", "java", "spring boot", "fastapi", "django", "node.js", "express", "go", "c++", "rust",
    "sql", "dbms", "sqlite", "postgresql", "mongodb", "redis", "docker", "kubernetes", "distributed systems",
    "machine learning", "deep learning", "tensorflow", "pytorch", "nlp", "llm", "computer vision", "scikit-learn"
]

class AriaCareerIntelligence(BaseAgent):
    def __init__(self, aria_instance=None, memory_db_path: str = "aria_memory.db"):
        super().__init__("CareerAgent", aria_instance)
        self.memory_db_path = memory_db_path

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
        self.log_state_shift("RUNNING", f"Evaluating requirements for task: {task_description}")
        
        target = payload.get("target", "")
        job_description = payload.get("job_description") or target
        role_title = payload.get("role_title") or "Software Engineering Intern"
        company_name = payload.get("company_name") or "Target Company"
        
        # 1. Deterministic requirements parsing
        required_skills = self._parse_skills(job_description)
        
        # 2. Match evaluation against user profile weights
        profile_snapshot = self._get_profile_snapshot()
        evaluation = self._calculate_match_metrics(required_skills, profile_snapshot)
        
        # 3. LLM pass for qualitative gap analysis and recommendations
        analysis_report = self._analyze_gaps_via_llm(
            role_title=role_title,
            company_name=company_name,
            required_skills=required_skills,
            evaluation=evaluation,
            job_description=job_description
        )
        
        # 4. Blackboard Publication
        try:
            bb = getattr(self.aria_inst, "blackboard", None)
            if bb is None or type(bb).__name__ in ('MagicMock', 'Mock'):
                bb = AriaBlackboard()
            bb_key = f"{company_name.lower().replace(' ', '_')}_gap_analysis"
            bb.publish(
                topic="career",
                key=bb_key,
                value=analysis_report,
                source=self.agent_name,
                ttl_hours=24
            )
        except Exception as e:
            print(f"[CareerIntelligence] Error publishing to blackboard: {e}")
            
        self.log_state_shift("IDLE", "Analysis complete. Career gaps published to blackboard.")
        return json.dumps(analysis_report)

    def _parse_skills(self, text: str) -> List[str]:
        text_lower = text.lower()
        found = []
        for kw in CORE_KEYWORDS:
            if kw in ("next.js", "spring boot", "deep learning", "machine learning", "distributed systems", "computer vision", "scikit-learn"):
                if kw in text_lower:
                    found.append(kw)
            else:
                pattern = r'\b' + re.escape(kw) + r'\b'
                if re.search(pattern, text_lower):
                    found.append(kw)
        return found

    def _get_profile_snapshot(self) -> Dict[str, float]:
        snapshot = {}
        if not os.path.exists(self.memory_db_path):
            return snapshot
        try:
            conn = sqlite3.connect(self.memory_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT vector_key, vector_weight FROM user_profile_vectors")
            for row in cursor.fetchall():
                snapshot[row["vector_key"].lower().strip()] = row["vector_weight"]
            conn.close()
        except Exception as e:
            print(f"[CareerIntelligence] Error fetching user profile snapshot: {e}")
        return snapshot

    def _calculate_match_metrics(self, required_skills: List[str], profile: Dict[str, float]) -> Dict[str, Any]:
        matched = []
        strong = []
        medium = []
        gaps = []
        total_weight = 0.0
        
        alias_map = {
            "spring boot": ["spring", "springboot"],
            "machine learning": ["ml", "machinelearning"],
            "deep learning": ["dl", "deeplearning"],
            "distributed systems": ["distributed_systems", "distributedsystems"],
            "next.js": ["nextjs"],
            "dbms": ["sql", "database"],
            "dsa": ["dynamic_programming", "algorithms"]
        }
        
        for skill in required_skills:
            weight = profile.get(skill, 0.0)
            
            if weight == 0.0 and skill in alias_map:
                for alias in alias_map[skill]:
                    if alias in profile:
                        weight = max(weight, profile[alias])
                        
            total_weight += weight
            matched.append({"skill": skill, "weight": weight})
            
            if weight >= 0.75:
                strong.append(skill)
            elif weight >= 0.40:
                medium.append(skill)
            else:
                gaps.append(skill)
                
        count = len(required_skills)
        if count == 0:
            score = 100.0
        else:
            score = (total_weight / count) * 100.0
            
        return {
            "score": round(score, 1),
            "matched_details": matched,
            "strong": strong,
            "medium": medium,
            "gaps": gaps
        }

    def _analyze_gaps_via_llm(self, role_title: str, company_name: str, required_skills: List[str], evaluation: Dict[str, Any], job_description: str) -> Dict[str, Any]:
        prompt = f"""
        You are the Career Intelligence Engine for ARIA.
        Evaluate candidate compatibility for the position of {role_title} at {company_name}.
        
        == DETERMINISTIC ANALYSIS ==
        Match Score: {evaluation['score']}%
        Required Skills Found: {required_skills}
        Strong Matches: {evaluation['strong']}
        Medium Matches: {evaluation['medium']}
        Skills Gaps: {evaluation['gaps']}
        
        == FULL JOB DESCRIPTION ==
        {job_description[:2000]}
        
        Provide a structured assessment report. You MUST respond with exactly a valid raw JSON object (do not include markdown block formatting, e.g. ```json).
        The JSON object schema:
        {{
            "match_score": {evaluation['score']},
            "company": "{company_name}",
            "role": "{role_title}",
            "strengths": {json.dumps(evaluation['strong'])},
            "missing_skills": {json.dumps(evaluation['gaps'])},
            "recommended_project_actions": [
                "Specific portfolio projects, tasks or expansions the user should build to bridge the missing skill gaps"
            ],
            "resume_bullet_suggestions": [
                "Suggestions on how to improve the resume or current project bullets to highlight Java, CP, or other matched strengths"
            ]
        }}
        """
        try:
            raw_res = self.aria_inst.brain.think(prompt)
            clean = raw_res.strip()
            match = re.search(r"(\{.*\})", clean, re.DOTALL)
            if match:
                clean = match.group(1).strip()
            else:
                for marker in ("```json", "```"):
                    if clean.startswith(marker):
                        clean = clean[len(marker):]
                if clean.endswith("```"):
                    clean = clean[:-3]
                clean = clean.strip()
            data = json.loads(clean)
            
            # Normalize keys to be robust against LLM naming variations
            normalized = {}
            for k, v in data.items():
                normalized[k.lower().replace("_", "").replace("-", "")] = v
            
            res = {
                "match_score": normalized.get("matchscore", evaluation["score"]),
                "company": data.get("company") or normalized.get("company", company_name),
                "role": data.get("role") or normalized.get("role", role_title),
                "strengths": data.get("strengths") or normalized.get("strengths", evaluation["strong"]),
                "missing_skills": data.get("missing_skills") or normalized.get("missingskills") or normalized.get("gaps", evaluation["gaps"]),
                "recommended_project_actions": data.get("recommended_project_actions") or normalized.get("recommendedprojectactions") or [],
                "resume_bullet_suggestions": data.get("resume_bullet_suggestions") or normalized.get("resumebulletsuggestions") or []
            }
            
            try:
                res["match_score"] = float(res["match_score"])
            except Exception:
                res["match_score"] = evaluation["score"]
                
            return res
        except Exception as e:
            print(f"[CareerIntelligence] LLM assessment generation failed: {e}")
            return {
                "match_score": evaluation["score"],
                "company": company_name,
                "role": role_title,
                "strengths": evaluation["strong"],
                "missing_skills": evaluation["gaps"],
                "recommended_project_actions": [f"Error during LLM pass: {e}. Focus on learning: {', '.join(evaluation['gaps'])}"],
                "resume_bullet_suggestions": ["Ensure matched strengths are clearly listed on resume."]
            }
