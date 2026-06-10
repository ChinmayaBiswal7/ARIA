import os
import sqlite3
import json
import time
import random
import math
from typing import Dict, Any, List, Tuple
from contextlib import closing

class AriaSimulationEngine:
    def __init__(self, db_path: str = "aria_orchestrator.db"):
        self.db_path = db_path
        self._init_simulation_ledger()

    def _init_simulation_ledger(self):
        """Initializes tables for simulation scenarios and simulation accuracy tracking."""
        if not self.db_path:
            return
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS simulation_scenarios (
                        scenario_id TEXT PRIMARY KEY,
                        campaign_id TEXT,
                        description TEXT,
                        path_type TEXT,
                        completion_probability REAL,
                        burnout_risk REAL,
                        expected_delay INTEGER,
                        resource_cost INTEGER,
                        executive_score REAL,
                        timestamp INTEGER
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS simulation_accuracy (
                        simulation_id TEXT PRIMARY KEY,
                        campaign_id TEXT,
                        predicted_completion_probability REAL,
                        actual_completion_probability REAL,
                        prediction_error REAL,
                        timestamp INTEGER
                    )
                """)
                conn.commit()
        except Exception as e:
            print(f"[SimulationEngine] Database initialization failed: {e}")

    def run_future_projections(self, campaign_id: str, base_goal: str, proposed_tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Component P18.1 & P18.2: Forks candidate paths and estimates their outcomes via Monte Carlo."""
        now = int(time.time())
        
        # 1. Fetch capacity constraints and energy levels from Resource Manager (P17)
        baseline_capacity = 240
        energy_score = 70
        life_state = "NORMAL"
        try:
            from skills.resource_manager import AriaResourceManager
            res_mgr = AriaResourceManager(self.db_path)
            baseline_capacity = res_mgr._get_historical_baseline_capacity()
            _, energy_factor = res_mgr.get_daily_capacity()
            energy_score = int(energy_factor * 100)
            
            # P22: Fetch LifeState dynamically
            from skills.personal_os_reasoning import PersonalOSReasoningEngine
            os_engine = PersonalOSReasoningEngine(db_path=self.db_path)
            life_state = os_engine.compute_systemic_pressures().get("life_state", "NORMAL")
        except Exception as e:
            print(f"[SimulationEngine] Resource Manager or LifeState query failed, using defaults: {e}")

        # 2. Extract Strategic Memory details (P16)
        weak_areas = []
        domain_success_rates = {}
        avg_intervention_success = 0.75
        try:
            from skills.strategic_memory_engine import AriaStrategicMemoryEngine
            mem_engine = AriaStrategicMemoryEngine(self.db_path)
            matrix = mem_engine.compile_experience_matrix(base_goal)
            
            # Extract weak area nodes
            for prereq in matrix.get("known_prerequisites", []):
                if "WEAK_AREA" in prereq or "BLOCKED_BY" in prereq:
                    # Parse node name
                    parts = prereq.split(" -[")
                    if parts:
                        weak_areas.append(parts[0].strip())

            # Extract domain success rates from historical tasks
            for task in matrix.get("task_success_and_failures", []):
                pattern = task["task_pattern"].lower()
                rate_str = task["success_rate"].rstrip('%')
                try:
                    rate = float(rate_str) / 100.0
                    domain_success_rates[pattern] = rate
                except ValueError:
                    pass

            # Extract average intervention success rate
            interventions = matrix.get("proven_behavioral_interventions", [])
            if interventions:
                rates = []
                for inter in interventions:
                    try:
                        rates.append(float(inter["success_rate"].rstrip('%')) / 100.0)
                    except (ValueError, KeyError):
                        pass
                if rates:
                    avg_intervention_success = sum(rates) / len(rates)
        except Exception as e:
            print(f"[SimulationEngine] Strategic Memory Engine query failed, using defaults: {e}")

        # 3. Generate Candidate Plan Scenarios (Scenario Generator P18.1)
        scenarios = self._generate_candidate_scenarios(campaign_id, proposed_tasks)

        evaluated_scenarios = []
        best_scenario = None
        highest_exec_score = -1.0

        for sc in scenarios:
            path_type = sc["path_type"]
            tasks = sc["tasks"]
            
            prob, burnout, delay, cost = self._run_monte_carlo_simulation(
                path_type=path_type,
                tasks=tasks,
                baseline_capacity=baseline_capacity,
                energy_score=energy_score,
                weak_areas=weak_areas,
                avg_intervention_success=avg_intervention_success,
                domain_success_rates=domain_success_rates,
                life_state=life_state
            )

            # P18.3: Apply Executive Comparison Formula
            # executive_score = success * 0.5 + resource_efficiency * 0.2 + (1 - risk) * 0.3
            resource_efficiency = 240.0 / (240.0 + cost)
            schedule_risk = min(1.0, delay / 5.0)
            overall_risk = (burnout + schedule_risk) / 2.0
            
            exec_score = (prob * 0.5) + (resource_efficiency * 0.2) + ((1.0 - overall_risk) * 0.3)

            # Fetch BURNOUT_THRESHOLD policy warning limit
            warning_limit = 0.70
            try:
                from skills.learning_engine import AriaLongTermLearningEngine
                engine = AriaLongTermLearningEngine(self.db_path)
                val, pol_status = engine.fetch_calibrated_value("POL_BURNOUT_LIMIT", 0.70)
                if pol_status != "DEFAULT":
                    warning_limit = val
            except Exception as e:
                print(f"[SimulationEngine] Error fetching BURNOUT_THRESHOLD policy: {e}")

            severe_limit = warning_limit + 0.10
            reject_limit = warning_limit + 0.20

            # Apply Tiered Burnout Penalty Scale
            penalty_applied = "NONE"
            if burnout > reject_limit:
                exec_score = 0.0
                penalty_applied = "REJECT_BURNOUT_LIMIT"
            elif burnout > severe_limit:
                exec_score *= 0.60
                penalty_applied = "SEVERE_PENALTY_0.60"
            elif burnout > warning_limit:
                exec_score *= 0.85
                penalty_applied = "WARNING_PENALTY_0.85"

            exec_score = round(exec_score, 3)

            evaluated_data = {
                "scenario_id": sc["id"],
                "path_type": path_type,
                "description": sc["description"],
                "completion_probability": round(prob, 2),
                "burnout_risk": round(burnout, 2),
                "expected_delay": int(math.ceil(delay)),
                "resource_cost": int(cost),
                "executive_score": exec_score,
                "penalty_applied": penalty_applied,
                "tasks": tasks
            }

            self._archive_scenario_record(campaign_id, evaluated_data, now)
            evaluated_scenarios.append(evaluated_data)

            # Select best scenario based on executive score
            if penalty_applied != "REJECT_BURNOUT_LIMIT" and exec_score > highest_exec_score:
                highest_exec_score = exec_score
                best_scenario = evaluated_data

        return {
            "status": "SIMULATION_COMPLETE",
            "campaign_id": campaign_id,
            "target_goal": base_goal,
            "best_path_selected": best_scenario,
            "all_simulated_branches": evaluated_scenarios
        }

    def _generate_candidate_scenarios(self, campaign_id: str, proposed_tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Scenario Generator: Forks the base plan into Balanced, Aggressive, and Conservative paths."""
        scenarios = []

        # 1. Balanced Path: Original tasks list
        scenarios.append({
            "id": f"SIM_BAL_{campaign_id[:6].upper()}_{int(time.time()) % 1000}",
            "path_type": "BALANCED",
            "description": "Balanced: Execute standard task plan roadmap.",
            "tasks": [dict(t) for t in proposed_tasks]
        })

        # 2. Aggressive Path: High-impact validation tasks appended, scopes scaled up (1.2x base duration check)
        aggressive_tasks = [dict(t) for t in proposed_tasks]
        # Append simulated extra deployment and integration validation task
        aggressive_tasks.append({
            "id": f"TSK_AGR_EXTRA_{campaign_id[:4].upper()}",
            "description": "Deploy infrastructure and run end-to-end automated validation suite.",
            "priority": "HIGH",
            "agent_target": "CodingAgent",
            "depends_on": [t["id"] for t in proposed_tasks]
        })
        scenarios.append({
            "id": f"SIM_AGR_{campaign_id[:6].upper()}_{int(time.time()) % 1000}",
            "path_type": "AGGRESSIVE",
            "description": "Aggressive: High-impact features, deeper validation, and auto-deploy checks.",
            "tasks": aggressive_tasks
        })

        # 3. Conservative Path: Filters only HIGH and MEDIUM priority tasks, prunes non-essential details
        conservative_tasks = [dict(t) for t in proposed_tasks if t.get("priority", "MEDIUM") in ("HIGH", "MEDIUM")]
        if not conservative_tasks and proposed_tasks:
            # Fallback if no tasks match priority
            conservative_tasks = [dict(proposed_tasks[0])]
        scenarios.append({
            "id": f"SIM_CON_{campaign_id[:6].upper()}_{int(time.time()) % 1000}",
            "path_type": "CONSERVATIVE",
            "description": "Conservative: Safe core roadmap focusing on high-priority items.",
            "tasks": conservative_tasks
        })

        return scenarios

    def _run_monte_carlo_simulation(
        self,
        path_type: str,
        tasks: List[Dict[str, Any]],
        baseline_capacity: int,
        energy_score: int,
        weak_areas: List[str],
        avg_intervention_success: float,
        domain_success_rates: Dict[str, float],
        life_state: str = "NORMAL"
    ) -> Tuple[float, float, float, float]:
        """Runs 100-iteration Monte Carlo simulation to estimate outcome vectors."""
        random.seed(42)  # Set seed for deterministic test outputs
        
        num_iterations = 100
        total_prob = 0.0
        total_burnout = 0.0
        total_delay = 0.0
        total_cost = 0.0

        # Calculate a base success multiplier from domain rates
        # If any domain success rates exist, we take the average as our historical outcome grounding
        if domain_success_rates:
            historical_success_base = sum(domain_success_rates.values()) / len(domain_success_rates)
        else:
            # Sane fallbacks matching domains
            historical_success_base = 0.75

        # Base burnout rates by path type
        base_burnout_map = {"CONSERVATIVE": 0.05, "BALANCED": 0.20, "AGGRESSIVE": 0.45}
        base_burnout = base_burnout_map.get(path_type, 0.20)

        # P22: Calibrate base burnout and success rates based on life state
        duration_multiplier = 1.0
        success_multiplier = 1.0
        
        if life_state in ("BURNOUT_RISK_MODE", "RECOVERY_MODE"):
            base_burnout = min(0.95, base_burnout + 0.30)
            duration_multiplier = 1.3  # sluggish performance
        elif life_state == "HIGH_PERFORMANCE_MODE":
            base_burnout = max(0.01, base_burnout * 0.5)
            success_multiplier = 1.15  # performance boost

        for _ in range(num_iterations):
            iter_delay_days = 0.0
            iter_burnout_days = 0
            iter_total_duration = 0.0
            iter_failed_interventions = 0
            
            # Randomize baseline daily focus budget (uniform noise 80% to 120%)
            daily_budget = max(60, int(baseline_capacity * random.uniform(0.8, 1.2)))
            current_day_capacity = daily_budget
            days_simulated = 1

            for task in tasks:
                desc = task.get("description", "")
                target = task.get("agent_target", "ResearchAgent")
                priority = task.get("priority", "MEDIUM")

                # 1. Estimate base duration
                try:
                    from skills.resource_manager import AriaResourceManager
                    base_dur = AriaResourceManager(self.db_path).estimate_task_duration(desc, target)
                except Exception:
                    base_dur = 45

                # Adjust duration by path scaling factor
                if path_type == "AGGRESSIVE":
                    base_dur = int(base_dur * 1.2)
                elif path_type == "CONSERVATIVE":
                    base_dur = int(base_dur * 0.7)

                # Randomize duration (uniform noise 80% to 130%)
                randomized_duration = base_dur * random.uniform(0.8, 1.3) * duration_multiplier

                # Randomize daily energy (fluctuations of +/-15)
                sim_energy = max(20, min(100, energy_score + random.randint(-15, 15)))
                sim_energy_factor = sim_energy / 100.0

                # Scale duration by simulated energy factor (1.5 - energy_factor)
                scaled_dur = int(randomized_duration * (1.5 - sim_energy_factor))
                iter_total_duration += scaled_dur

                # 2. Check KG blocker/weak areas (P14/P16 blocker grounding)
                is_blocked = any(wa in desc.lower() for wa in weak_areas)
                if is_blocked:
                    # Simulate automated intervention success
                    if random.random() > avg_intervention_success:
                        # Intervention failed, add delay and risk penalties
                        iter_failed_interventions += 1
                        iter_delay_days += random.uniform(1.0, 2.0)

                # 3. Schedule day-by-day (Resource P17 schedule tracking)
                if scaled_dur <= current_day_capacity:
                    current_day_capacity -= scaled_dur
                else:
                    # Wrap task to tomorrow
                    iter_delay_days += 1.0
                    days_simulated += 1
                    
                    # Check for burnout due to daily workload exceeding capacity limit
                    if scaled_dur > daily_budget:
                        iter_burnout_days += 1
                        # Degrade simulated capacity due to fatigue for subsequent days
                        daily_budget = int(daily_budget * 0.8)

                    current_day_capacity = max(30, daily_budget)

            # Compute iteration results
            iter_success_rate = historical_success_base * success_multiplier
            if path_type == "AGGRESSIVE":
                # High-impact adds base success but carries penalty risks
                iter_success_rate += 0.10
            elif path_type == "CONSERVATIVE":
                # Pruning non-essential nodes caps success ceiling
                iter_success_rate -= 0.15

            # P22: EXAM_MODE penalty for non-academic tasks in simulated success
            if life_state == "EXAM_MODE":
                non_academic_count = 0
                for task in tasks:
                    desc_l = task.get("description", "").lower()
                    target_l = task.get("agent_target", "ResearchAgent").lower()
                    is_academic = any(k in desc_l for k in ["study", "exam", "dsa", "leetcode", "dbms", "notes", "academics"]) or target_l == "careeragent"
                    if not is_academic:
                        non_academic_count += 1
                if non_academic_count > 0:
                    iter_success_rate -= (non_academic_count * 0.15)

            # Deduct success for failed interventions or excessive delay
            iter_success_rate -= (iter_failed_interventions * 0.12)
            iter_success_rate -= (iter_delay_days * 0.04)

            # Cap outcomes to standard bounds
            iter_success = max(0.10, min(0.95, iter_success_rate))
            iter_burnout_val = base_burnout + (iter_burnout_days / max(1, days_simulated))
            
            # Spikes burnout if daily capacity was consistently degraded
            if daily_budget < (baseline_capacity * 0.6):
                iter_burnout_val += 0.25

            iter_burnout_val = max(0.0, min(0.99, iter_burnout_val))

            total_prob += iter_success
            total_burnout += iter_burnout_val
            total_delay += iter_delay_days
            total_cost += iter_total_duration

        # Fetch SIMULATION_BIAS policy value to correct optimistic predictions
        bias = 0.0
        try:
            from skills.learning_engine import AriaLongTermLearningEngine
            engine = AriaLongTermLearningEngine(self.db_path)
            val, pol_status = engine.fetch_calibrated_value("POL_SIM_BIAS", 0.0)
            if pol_status != "DEFAULT":
                bias = val
        except Exception as e:
            print(f"[SimulationEngine] Error fetching SIMULATION_BIAS policy: {e}")

        avg_prob = total_prob / num_iterations
        corrected_prob = avg_prob - bias
        corrected_prob = max(0.05, min(0.95, corrected_prob))

        return (
            corrected_prob,
            total_burnout / num_iterations,
            total_delay / num_iterations,
            total_cost / num_iterations
        )

    def _archive_scenario_record(self, campaign_id: str, data: dict, timestamp: int):
        if not self.db_path:
            return
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO simulation_scenarios 
                    (scenario_id, campaign_id, description, path_type, completion_probability, burnout_risk, expected_delay, resource_cost, executive_score, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    data["scenario_id"],
                    campaign_id,
                    data["description"],
                    data["path_type"],
                    data["completion_probability"],
                    data["burnout_risk"],
                    data["expected_delay"],
                    data["resource_cost"],
                    data["executive_score"],
                    timestamp
                ))
                conn.commit()
        except Exception as e:
            print(f"[SimulationEngine] Failed to log scenario: {e}")

    def log_simulation_accuracy(self, simulation_id: str, campaign_id: str, predicted_prob: float, actual_prob: float):
        """Allows campaigns completion to record accuracy stats, letting ARIA learn from error gaps."""
        if not self.db_path:
            return
        error = abs(predicted_prob - actual_prob)
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO simulation_accuracy (simulation_id, campaign_id, predicted_completion_probability, actual_completion_probability, prediction_error, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (simulation_id, campaign_id, predicted_prob, actual_prob, error, int(time.time())))
                conn.commit()
            print(f"[SimulationEngine] Accuracy logged: Pred={predicted_prob}, Act={actual_prob}, Error={error}")
        except Exception as e:
            print(f"[SimulationEngine] Failed to log accuracy: {e}")

    def run_what_if_analysis(self, user_query: str, proposed_tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Component P18.4: Intercepts natural language parameters, runs forecast, and outputs strategic advice."""
        clean_query = user_query.lower().strip()

        # Parse defaults
        sim_capacity_override = 240
        exclude_domains = []
        guidance = "Standard baseline scenario configured."

        # Parse basic parameters from natural language queries
        if "3 hours" in clean_query or "180 minutes" in clean_query:
            sim_capacity_override = 180
            guidance = "Spiking daily focus budgets to 180 minutes increases completion probability but increases burnout risks."
        elif "2 hours" in clean_query or "120 minutes" in clean_query:
            sim_capacity_override = 120
            guidance = "Reducing daily focus budgets to 120 minutes lowers workload pressure but adds delay to campaign completion."
        elif "4 hours" in clean_query or "240 minutes" in clean_query:
            sim_capacity_override = 240
            guidance = "Generous focus budget of 240 minutes provides high runway for comprehensive task structures."

        if "skip dbms" in clean_query:
            exclude_domains.append("dbms")
            guidance = "Skipping DBMS revision reduces immediate study time but introduces a 15% success penalty due to missing career prerequisites."
        elif "skip dsa" in clean_query:
            exclude_domains.append("dsa")
            guidance = "Skipping DSA practice minimizes daily study workload but causes a severe failure penalty due to high interviewer evaluation dependency."
        elif "focus only on java" in clean_query:
            exclude_domains.append("spring")
            exclude_domains.append("docker")
            guidance = "Focusing exclusively on Java syntax accelerates early progress but leaves you weak in frameworks like Spring Boot."

        # Filter tasks based on query exclusions
        filtered_tasks = []
        for task in proposed_tasks:
            desc = task.get("description", "").lower()
            if any(dom in desc for dom in exclude_domains):
                continue
            filtered_tasks.append(task)

        # Get active LifeState
        life_state = "NORMAL"
        try:
            from skills.personal_os_reasoning import PersonalOSReasoningEngine
            os_engine = PersonalOSReasoningEngine(db_path=self.db_path)
            life_state = os_engine.compute_systemic_pressures().get("life_state", "NORMAL")
        except Exception:
            pass

        # Run Monte Carlo forecast with overridden parameters
        prob, burnout, delay, cost = self._run_monte_carlo_simulation(
            path_type="BALANCED",
            tasks=filtered_tasks,
            baseline_capacity=sim_capacity_override,
            energy_score=70,
            weak_areas=[],
            avg_intervention_success=0.75,
            domain_success_rates={},
            life_state=life_state
        )

        # Apply specific overrides to success rates based on exclusions
        if "skip dsa" in clean_query:
            prob = max(0.10, prob - 0.25)
        if "skip dbms" in clean_query:
            prob = max(0.10, prob - 0.15)

        resource_efficiency = 240.0 / (240.0 + cost)
        schedule_risk = min(1.0, delay / 5.0)
        overall_risk = (burnout + schedule_risk) / 2.0
        exec_score = round((prob * 0.5) + (resource_efficiency * 0.2) + ((1.0 - overall_risk) * 0.3), 3)

        return {
            "query": user_query,
            "completion_probability": round(prob, 2),
            "burnout_risk": round(burnout, 2),
            "expected_delay_days": int(math.ceil(delay)),
            "resource_cost_minutes": int(cost),
            "executive_score": exec_score,
            "strategic_guidance": guidance
        }
