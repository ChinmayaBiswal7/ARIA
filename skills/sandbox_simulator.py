import os
import threading
from skills.predictive_modeler import PredictiveModeler

class SandboxSimulator:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SandboxSimulator, cls).__new__(cls)
                cls._instance.modeler = PredictiveModeler()
            return cls._instance

    def simulate_and_compare(self, task_goal):
        """
        Simulates different strategy paths mentally for a given goal:
        - Evaluates path utility score: (SuccessRate * 0.70) + (1.0 - Latency Penalty * 0.30)
        - Selects the path with the highest utility.
        """
        task_lower = task_goal.strip().lower()
        
        # 1. Define candidate execution strategies based on keywords
        candidates = []
        if "chrome" in task_lower or "search" in task_lower or "news" in task_lower or "browser" in task_lower:
            candidates = [
                {"name": "Browser Automation (chrome)", "verb": "search"},
                {"name": "OS Direct Access (cmd)", "verb": "open"}
            ]
        elif "type" in task_lower or "write" in task_lower or "message" in task_lower:
            candidates = [
                {"name": "UI Window Control (unigram/notepad)", "verb": "type"},
                {"name": "Vision Coordinate Coordinates Click", "verb": "click"}
            ]
        else:
            candidates = [
                {"name": "OS Command Line Executive", "verb": "open"},
                {"name": "Direct GUI Click Automation", "verb": "click"}
            ]
            
        # 2. Evaluate simulated rewards for each candidate
        evaluation_results = []
        best_path = None
        best_score = -1.0
        
        for cand in candidates:
            est = self.modeler.estimate_outcome(cand["verb"])
            
            # Latency penalty mapping
            lat_penalty = min(est["expected_latency"] / 10.0, 1.0)
            
            # Calculate composite utility score (0.0 to 1.0)
            utility_score = (est["success_prob"] * 0.70) + ((1.0 - lat_penalty) * 0.30)
            
            cand_result = {
                "path_name": cand["name"],
                "strategy_verb": cand["verb"],
                "success_prob": est["success_prob"],
                "expected_latency": est["expected_latency"],
                "fail_risk": est["fail_risk"],
                "recovery_cost": est["recovery_cost"],
                "utility_score": round(utility_score, 2)
            }
            evaluation_results.append(cand_result)
            
            if utility_score > best_score:
                best_score = utility_score
                best_path = cand_result

        return {
            "goal": task_goal,
            "best_path": best_path,
            "candidates": evaluation_results
        }

    def run_counterfactual_reflection(self, failed_strategy, candidates_list):
        """
        Compares the failed strategy path against alternative candidates:
        - Selects the alternative path that would have had the highest expected success rate.
        - Returns a counterfactual learning summary.
        """
        failed_key = failed_strategy.strip().lower()
        best_alt = None
        best_alt_score = -1.0
        
        for cand in candidates_list:
            cand_verb = cand.get("strategy_verb", "")
            if cand_verb != failed_key:
                score = cand.get("utility_score", 0.0)
                if score > best_alt_score:
                    best_alt_score = score
                    best_alt = cand

        if best_alt:
            summary = (
                f"Counterfactual Reflection: Strategy '{failed_key}' failed. "
                f"Alternative strategy '{best_alt['strategy_verb']}' ('{best_alt['path_name']}') would "
                f"have succeeded with a predicted {best_alt['success_prob']*100:.0f}% success rate."
            )
            return {
                "recommendation": best_alt["strategy_verb"],
                "recommendation_path": best_alt["path_name"],
                "summary": summary
            }
        
        # Fallback if no alternative candidates existed
        fallback_map = {
            "click": "type",
            "type": "click",
            "search": "open",
            "open": "search"
        }
        rec = fallback_map.get(failed_key, "open")
        return {
            "recommendation": rec,
            "recommendation_path": f"Alternative OS executive path ({rec})",
            "summary": f"Counterfactual Reflection: Strategy '{failed_key}' failed. Recommending backup strategy '{rec}'."
        }
