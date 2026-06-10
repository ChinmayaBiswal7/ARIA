import os
import sqlite3
import json
import time
from typing import Dict, Any, List

class AriaStrategicMemoryEngine:
    # Class-level cache to persist across multiple instantiations of the engine
    _cache: Dict[str, Dict[str, Any]] = {}
    CACHE_TTL = 3600  # 1 hour in seconds

    def __init__(self, db_path: str = "aria_orchestrator.db"):
        self.db_path = db_path

    def compile_experience_matrix(self, goal_text: str) -> Dict[str, Any]:
        """Component P16: Extracts domain keywords, queries or pulls from cache, and merges strategic metrics."""
        # 1. Multi-Domain Extraction
        domains = self._extract_domains(goal_text)
        print(f"[StrategicMemory] Extracted domains for goal: {domains}")

        merged_tasks = []
        merged_teams = []
        merged_reflections = []
        merged_prerequisites = []
        merged_interventions = []

        now = time.time()

        for domain in domains:
            # 2. Cache Layer
            if domain in self._cache and (now - self._cache[domain]["timestamp"]) < self.CACHE_TTL:
                print(f"[StrategicMemory] Cache HIT for domain: '{domain}'")
                matrix = self._cache[domain]["matrix"]
            else:
                print(f"[StrategicMemory] Cache MISS for domain: '{domain}'. Building matrix from DB.")
                matrix = self._build_matrix_for_domain(domain)
                self._cache[domain] = {
                    "timestamp": now,
                    "matrix": matrix
                }

            # 3. Merge components
            merged_tasks.extend(matrix.get("task_success_and_failures", []))
            merged_teams.extend(matrix.get("high_performing_teams", []))
            merged_reflections.extend(matrix.get("reflection_directives", []))
            merged_prerequisites.extend(matrix.get("prerequisites", []))
            merged_interventions.extend(matrix.get("intervention_metrics", []))

        # Deduplicate and sort task success/failure patterns
        deduped_tasks = self._deduplicate_tasks(merged_tasks)
        # Deduplicate and sort teams by average review score
        deduped_teams = self._deduplicate_teams(merged_teams)
        # Deduplicate and limit reflections, prerequisites, and interventions
        deduped_reflections = list(set(merged_reflections))[:5]
        deduped_prerequisites = list(set(merged_prerequisites))[:8]
        deduped_interventions = self._deduplicate_interventions(merged_interventions)

        return {
            "domains": domains,
            "task_success_and_failures": deduped_tasks,
            "high_performing_teams": deduped_teams,
            "reflection_directives": deduped_reflections,
            "proven_behavioral_interventions": deduped_interventions,
            "known_prerequisites": deduped_prerequisites
        }

    def _extract_domains(self, goal_text: str) -> List[str]:
        """Extracts domain keywords matching standard ARIA capabilities from goal text."""
        goal_lower = goal_text.lower()
        supported_domains = ["java", "spring", "dbms", "dsa", "docker", "aws", "security", "career", "resume", "interview"]
        domains = [d for d in supported_domains if d in goal_lower]
        if not domains:
            domains = ["general"]
        return domains

    def _build_matrix_for_domain(self, domain: str) -> Dict[str, Any]:
        """Builds experience metrics for a single domain from production databases."""
        return {
            "task_success_and_failures": self._calculate_task_success_rates(domain),
            "high_performing_teams": self._aggregate_workforce_scores(domain),
            "reflection_directives": self._pull_latest_reflection_directives(domain),
            "prerequisites": self._fetch_knowledge_graph_prerequisites(domain),
            "intervention_metrics": self._aggregate_intervention_success_rates()
        }

    def _calculate_task_success_rates(self, domain: str) -> List[Dict[str, Any]]:
        """Queries agent_tasks table to score and sort relevant historical task patterns."""
        metrics = []
        if not os.path.exists(self.db_path):
            return metrics

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # 1. Pull runs grouped by task description
            query = """
                SELECT 
                    task_description,
                    COUNT(*) as total_runs,
                    SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as successes,
                    SUM(CASE WHEN status = 'FAILED' OR status = 'CANCELLED' THEN 1 ELSE 0 END) as failures
                FROM agent_tasks
                WHERE task_description LIKE ?
                GROUP BY task_description
            """
            cursor = conn.execute(query, (f"%{domain}%",))
            
            for row in cursor.fetchall():
                total = row["total_runs"]
                successes = row["successes"]
                failures = row["failures"]
                
                # Relevance Scoring: Frequency * (1.0 if net success else 0.5)
                net_success = successes > failures
                relevance_score = float(total) * (1.0 if net_success else 0.5)
                success_rate = (successes / total) if total > 0 else 0.0

                metrics.append({
                    "task_pattern": row["task_description"],
                    "success_rate": f"{round(success_rate * 100, 1)}%",
                    "failure_rate": f"{round((1.0 - success_rate) * 100, 1)}%",
                    "relevance_score": relevance_score,
                    "runs": total
                })
        
        # Sort by relevance_score descending and return top 5
        metrics.sort(key=lambda x: x["relevance_score"], reverse=True)
        return metrics[:5]

    def _aggregate_workforce_scores(self, domain: str) -> List[Dict[str, Any]]:
        """Queries workforce_sessions and workforce_artifacts to evaluate successful teams."""
        teams = []
        if not os.path.exists(self.db_path):
            return teams

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                # Group by participating_agents combination, joining campaigns to match goal text
                query = """
                    SELECT 
                        w.participating_agents,
                        AVG(w.review_score) as avg_score,
                        COUNT(*) as runs
                    FROM workforce_sessions w
                    LEFT JOIN campaigns c ON w.campaign_id = c.id
                    WHERE w.participating_agents LIKE ?
                       OR w.campaign_id LIKE ?
                       OR (c.goal_text IS NOT NULL AND c.goal_text LIKE ?)
                    GROUP BY w.participating_agents
                    ORDER BY avg_score DESC
                    LIMIT 3
                """
                cursor = conn.execute(query, (f"%{domain}%", f"%{domain}%", f"%{domain}%"))
                for row in cursor.fetchall():
                    teams.append({
                        "agent_team": row["participating_agents"],
                        "average_review_score": round(row["avg_score"], 2),
                        "total_collaborations": row["runs"]
                    })
            except sqlite3.OperationalError:
                pass
        return teams

    def _pull_latest_reflection_directives(self, domain: str) -> List[str]:
        """Queries system_reflections table to fetch relevant strategic guidelines."""
        directives = []
        if not os.path.exists(self.db_path):
            return directives

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute("""
                    SELECT insights FROM system_reflections
                    WHERE (insights LIKE ? OR insights LIKE '%strategic%')
                    AND horizon = 'WEEKLY'
                    ORDER BY timestamp DESC
                    LIMIT 2
                """, (f"%{domain}%",))
                directives = [row["insights"] for row in cursor.fetchall()]
            except sqlite3.OperationalError:
                pass
        return directives

    def _fetch_knowledge_graph_prerequisites(self, domain: str) -> List[str]:
        """Queries knowledge_graph_edges for dependencies or weak blockers relating to domain."""
        edges = []
        if not os.path.exists(self.db_path):
            return edges

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute("""
                    SELECT source_node, relationship, target_node, confidence_weight
                    FROM knowledge_graph_edges
                    WHERE (source_node LIKE ? OR target_node LIKE ?)
                    AND relationship IN ('BLOCKED_BY', 'REQUIRES', 'WEAK_AREA')
                    ORDER BY confidence_weight DESC
                    LIMIT 5
                """, (f"%{domain}%", f"%{domain}%"))
                for row in cursor.fetchall():
                    edges.append(f"{row['source_node']} -[{row['relationship']}]-> {row['target_node']} (Conf: {row['confidence_weight']})")
            except sqlite3.OperationalError:
                pass
        return edges

    def _aggregate_intervention_success_rates(self) -> List[Dict[str, Any]]:
        """Queries intervention_ledger to identify historical success rates of intervention categories."""
        interventions = []
        if not os.path.exists(self.db_path):
            return interventions

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute("""
                    SELECT 
                        action,
                        COUNT(*) as total,
                        AVG(success_score) as avg_score
                    FROM intervention_ledger
                    WHERE success_score IS NOT NULL
                    GROUP BY action
                    ORDER BY avg_score DESC
                """)
                for row in cursor.fetchall():
                    interventions.append({
                        "action": row["action"],
                        "success_rate": f"{round(row['avg_score'] * 100, 1)}%",
                        "total_interventions": row["total"]
                    })
            except sqlite3.OperationalError:
                pass
        return interventions

    # Deduplication and merging helpers
    def _deduplicate_tasks(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = {}
        for t in tasks:
            pattern = t["task_pattern"]
            if pattern not in seen or t["relevance_score"] > seen[pattern]["relevance_score"]:
                seen[pattern] = t
        merged = list(seen.values())
        merged.sort(key=lambda x: x["relevance_score"], reverse=True)
        return [{
            "task_pattern": t["task_pattern"],
            "success_rate": t["success_rate"],
            "failure_rate": t["failure_rate"],
            "runs": t["runs"]
        } for t in merged[:5]]

    def _deduplicate_teams(self, teams: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = {}
        for t in teams:
            team = t["agent_team"]
            if team not in seen or t["average_review_score"] > seen[team]["average_review_score"]:
                seen[team] = t
        merged = list(seen.values())
        merged.sort(key=lambda x: x["average_review_score"], reverse=True)
        return merged[:3]

    def _deduplicate_interventions(self, interventions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = {}
        for i in interventions:
            action = i["action"]
            if action not in seen or float(i["success_rate"].rstrip('%')) > float(seen[action]["success_rate"].rstrip('%')):
                seen[action] = i
        merged = list(seen.values())
        merged.sort(key=lambda x: float(x["success_rate"].rstrip('%')), reverse=True)
        return merged[:4]
