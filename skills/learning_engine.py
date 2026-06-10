import os
import sqlite3
import json
import time
import math
from typing import List, Dict, Any, Tuple
from contextlib import closing

class AriaLongTermLearningEngine:
    def __init__(self, db_path: str = "aria_orchestrator.db"):
        self.db_path = db_path
        self._init_learning_tables()

    def _init_learning_tables(self):
        """Initializes tables for system operational policies and policy effectiveness tracking."""
        if not self.db_path:
            return
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS system_operational_policies (
                        policy_id TEXT PRIMARY KEY,
                        policy_type TEXT,            -- 'DURATION_CALIBRATION', 'BURNOUT_THRESHOLD', 'SIMULATION_BIAS'
                        policy_key TEXT,             -- e.g., 'spring', 'docker', 'java'
                        policy_value REAL,           -- e.g., 1.4, 0.75, 0.08
                        confidence REAL,
                        sample_size INTEGER,
                        status TEXT,                 -- 'EXPERIMENTAL', 'PROBATION', 'ACTIVE', 'RETIRED'
                        policy_version INTEGER DEFAULT 1,
                        created_at INTEGER,
                        last_applied INTEGER
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS policy_effectiveness_ledger (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        policy_id TEXT,
                        applied_at INTEGER,
                        campaign_id TEXT,
                        task_id TEXT,
                        outcome_success INTEGER,     -- 1 for Success, 0 for Failure/Delay
                        notes TEXT
                    )
                """)
                conn.commit()
        except Exception as e:
            print(f"[LearningEngine] Database initialization failed: {e}")

    def run_nightly_policy_calibration(self) -> Dict[str, Any]:
        """Component P20: Runs analytical sweeps across database logs to refine decision policies."""
        now = int(time.time())
        calibrations = {
            "duration_policies_updated": 0,
            "simulation_bias_updated": False,
            "burnout_threshold_updated": False,
            "policies_retired": 0
        }

        if not os.path.exists(self.db_path):
            return calibrations

        # 1. Calibrate Task Durations
        durations = self._calibrate_task_durations(now)
        calibrations["duration_policies_updated"] = durations

        # 2. Calibrate Simulation Bias
        bias = self._calibrate_simulation_bias(now)
        calibrations["simulation_bias_updated"] = bias

        # 3. Calibrate Burnout Thresholds
        burnout = self._calibrate_burnout_thresholds(now)
        calibrations["burnout_threshold_updated"] = burnout

        # 4. Meta-Learning: Evaluate Policy Effectiveness & Retire Failing Policies (P20.5)
        retired = self._evaluate_policy_effectiveness(now)
        calibrations["policies_retired"] = retired

        return calibrations

    def _calibrate_task_durations(self, now: int) -> int:
        """Analyzes completed tasks in agent_tasks to calibrate multipliers for key domains."""
        updated_count = 0
        keywords = ["spring", "docker", "java", "dsa", "dbms"]
        
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                for kw in keywords:
                    # Query all completed tasks containing keyword in description
                    cursor = conn.execute("""
                        SELECT started_at, completed_at, task_description, agent_name
                        FROM agent_tasks
                        WHERE (task_description LIKE ? OR agent_name = ?)
                          AND status = 'COMPLETED'
                          AND started_at IS NOT NULL
                          AND completed_at IS NOT NULL
                    """, (f"%{kw}%", kw.lower()))
                    
                    rows = cursor.fetchall()
                    sample_size = len(rows)
                    if sample_size < 1:
                        continue

                    # Calculate average actual duration in minutes
                    total_actual = 0.0
                    for row in rows:
                        actual_mins = (row["completed_at"] - row["started_at"]) / 60.0
                        total_actual += actual_mins
                    avg_actual = total_actual / sample_size

                    # Baseline estimate (fallbacks from resource manager)
                    default_baseline = 45
                    if kw in ("docker", "aws", "deploy"):
                        default_baseline = 60
                    elif kw in ("security", "spring", "auth"):
                        default_baseline = 90

                    deviation_ratio = avg_actual / default_baseline
                    deviation_ratio = round(max(0.5, min(2.5, deviation_ratio)), 2)

                    # Only create policy if the deviation is significant (>15% difference)
                    if abs(deviation_ratio - 1.0) < 0.15:
                        continue

                    policy_id = f"POL_DUR_{kw.upper()}"
                    
                    # Versioning and status check
                    cursor_exist = conn.execute("SELECT policy_value, policy_version, status FROM system_operational_policies WHERE policy_id = ?", (policy_id,))
                    row_exist = cursor_exist.fetchone()
                    
                    version = 1
                    status = "EXPERIMENTAL"
                    
                    if row_exist:
                        old_val = row_exist["policy_value"]
                        version = row_exist["policy_version"]
                        # Increment version only if values differ significantly
                        if abs(old_val - deviation_ratio) > 0.05:
                            version += 1
                        
                        # Retain retired status if already retired
                        if row_exist["status"] == "RETIRED":
                            status = "RETIRED"
                        
                    # Enforce maturity gates
                    if status != "RETIRED":
                        if sample_size >= 15:
                            status = "ACTIVE"
                        elif sample_size >= 5:
                            status = "PROBATION"
                        else:
                            status = "EXPERIMENTAL"

                    # Calculate confidence metric: higher sample sizes give higher confidence
                    confidence = round(1.0 - (1.0 / (sample_size + 1.0)), 2)

                    conn.execute("""
                        INSERT OR REPLACE INTO system_operational_policies 
                        (policy_id, policy_type, policy_key, policy_value, confidence, sample_size, status, policy_version, created_at)
                        VALUES (?, 'DURATION_CALIBRATION', ?, ?, ?, ?, ?, ?, ?)
                    """, (policy_id, kw, deviation_ratio, confidence, sample_size, status, version, now))
                    updated_count += 1
                conn.commit()
        except Exception as e:
            print(f"[LearningEngine] Error calibrating durations: {e}")
            
        return updated_count

    def _calibrate_simulation_bias(self, now: int) -> bool:
        """Analyzes simulation accuracy records to compute and correct forecasting optimistic bias."""
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT predicted_completion_probability, actual_completion_probability
                    FROM simulation_accuracy
                """)
                rows = cursor.fetchall()
                sample_size = len(rows)
                if sample_size < 5:
                    return False  # Not enough data points to compute bias

                total_error = 0.0
                for row in rows:
                    # Positive error means predictions are too optimistic
                    total_error += (row["predicted_completion_probability"] - row["actual_completion_probability"])
                mean_bias = round(total_error / sample_size, 3)

                policy_id = "POL_SIM_BIAS"
                
                # Check version
                cursor_exist = conn.execute("SELECT policy_value, policy_version, status FROM system_operational_policies WHERE policy_id = ?", (policy_id,))
                row_exist = cursor_exist.fetchone()
                
                version = 1
                status = "EXPERIMENTAL"
                if row_exist:
                    old_val = row_exist["policy_value"]
                    version = row_exist["policy_version"]
                    if abs(old_val - mean_bias) > 0.02:
                        version += 1
                    if row_exist["status"] == "RETIRED":
                        status = "RETIRED"

                if status != "RETIRED":
                    if sample_size >= 15:
                        status = "ACTIVE"
                    elif sample_size >= 5:
                        status = "PROBATION"
                    else:
                        status = "EXPERIMENTAL"

                confidence = round(1.0 - (1.0 / (sample_size + 1.0)), 2)

                conn.execute("""
                    INSERT OR REPLACE INTO system_operational_policies 
                    (policy_id, policy_type, policy_key, policy_value, confidence, sample_size, status, policy_version, created_at)
                    VALUES (?, 'SIMULATION_BIAS', 'default', ?, ?, ?, ?, ?, ?)
                """, (policy_id, mean_bias, confidence, sample_size, status, version, now))
                conn.commit()
                return True
        except Exception as e:
            print(f"[LearningEngine] Error calibrating simulation bias: {e}")
        return False

    def _calibrate_burnout_thresholds(self, now: int) -> bool:
        """Correlates simulated burnout risk against campaign outcomes to optimize safety parameters."""
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                # Query completed/failed campaigns and join simulation scenarios
                cursor = conn.execute("""
                    SELECT c.status as camp_status, s.burnout_risk
                    FROM campaigns c
                    LEFT JOIN simulation_scenarios s ON c.id = s.campaign_id
                    WHERE c.status IN ('COMPLETED', 'FAILED')
                      AND s.burnout_risk IS NOT NULL
                """)
                rows = cursor.fetchall()
                sample_size = len(rows)
                if sample_size < 5:
                    return False

                # Count failures for high simulated burnout risk
                high_burnout_runs = 0
                high_burnout_failures = 0
                for row in rows:
                    if row["burnout_risk"] >= 0.70:
                        high_burnout_runs += 1
                        if row["camp_status"] == "FAILED":
                            high_burnout_failures += 1

                # If high burnout risk consistently leads to failure (>60% of times), reduce active warning limit
                calibrated_limit = 0.70
                if high_burnout_runs >= 3:
                    failure_rate = high_burnout_failures / high_burnout_runs
                    if failure_rate > 0.60:
                        calibrated_limit = 0.60  # Tighten safety guard
                    elif failure_rate < 0.20:
                        calibrated_limit = 0.80  # Loosen safety guard

                policy_id = "POL_BURNOUT_LIMIT"
                
                # Check version
                cursor_exist = conn.execute("SELECT policy_value, policy_version, status FROM system_operational_policies WHERE policy_id = ?", (policy_id,))
                row_exist = cursor_exist.fetchone()
                
                version = 1
                status = "EXPERIMENTAL"
                if row_exist:
                    old_val = row_exist["policy_value"]
                    version = row_exist["policy_version"]
                    if abs(old_val - calibrated_limit) > 0.05:
                        version += 1
                    if row_exist["status"] == "RETIRED":
                        status = "RETIRED"

                if status != "RETIRED":
                    if sample_size >= 15:
                        status = "ACTIVE"
                    elif sample_size >= 5:
                        status = "PROBATION"
                    else:
                        status = "EXPERIMENTAL"

                confidence = round(1.0 - (1.0 / (sample_size + 1.0)), 2)

                conn.execute("""
                    INSERT OR REPLACE INTO system_operational_policies 
                    (policy_id, policy_type, policy_key, policy_value, confidence, sample_size, status, policy_version, created_at)
                    VALUES (?, 'BURNOUT_THRESHOLD', 'warning_limit', ?, ?, ?, ?, ?, ?)
                """, (policy_id, calibrated_limit, confidence, sample_size, status, version, now))
                conn.commit()
                return True
        except Exception as e:
            print(f"[LearningEngine] Error calibrating burnout threshold: {e}")
        return False

    def _evaluate_policy_effectiveness(self, now: int) -> int:
        """Meta-Learning (P20.5): Audits applied policies and retires those that fail to improve outcomes."""
        retired_count = 0
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT policy_id, 
                           SUM(outcome_success) as successes,
                           COUNT(*) as total_applied
                    FROM policy_effectiveness_ledger
                    GROUP BY policy_id
                """)
                
                rows = cursor.fetchall()
                for row in rows:
                    policy_id = row["policy_id"]
                    total = row["total_applied"]
                    successes = row["successes"]
                    
                    # Retire policy only if applied at least 10 times and success rate is < 50%
                    if total >= 10:
                        success_rate = successes / total
                        if success_rate < 0.50:
                            conn.execute("""
                                UPDATE system_operational_policies
                                SET status = 'RETIRED', last_applied = ?
                                WHERE policy_id = ?
                            """, (now, policy_id))
                            retired_count += 1
                            print(f"[LearningEngine] RETIRED ineffective policy: {policy_id} (Success rate: {success_rate:.2f} over {total} runs)")
                conn.commit()
        except Exception as e:
            print(f"[LearningEngine] Error evaluating policy effectiveness: {e}")
            
        return retired_count

    def apply_policy_log(self, policy_id: str, campaign_id: str, task_id: str, outcome_success: int, notes: str = ""):
        """Records an application of a policy to trace its effectiveness over time."""
        now = int(time.time())
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    INSERT INTO policy_effectiveness_ledger (policy_id, applied_at, campaign_id, task_id, outcome_success, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (policy_id, now, campaign_id, task_id, outcome_success, notes))
                
                # Update last_applied in policy record
                conn.execute("""
                    UPDATE system_operational_policies
                    SET last_applied = ?
                    WHERE policy_id = ?
                """, (now, policy_id))
                conn.commit()
        except Exception as e:
            print(f"[LearningEngine] Failed to log policy effectiveness: {e}")

    def fetch_calibrated_value(self, policy_id: str, default_value: float) -> Tuple[float, str]:
        """Reads operational policy value dynamically, scaling down values if on PROBATION."""
        if not os.path.exists(self.db_path):
            return default_value, "DEFAULT"
            
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT policy_value, status 
                    FROM system_operational_policies
                    WHERE policy_id = ? AND status IN ('ACTIVE', 'PROBATION')
                """, (policy_id,))
                row = cursor.fetchone()
                if row:
                    val = row["policy_value"]
                    status = row["status"]
                    if status == "ACTIVE":
                        return val, "ACTIVE"
                    elif status == "PROBATION":
                        # Apply probationary policy at 50% impact weight
                        weighted_val = default_value + (val - default_value) * 0.5
                        return round(weighted_val, 2), "PROBATION"
        except Exception:
            pass
            
        return default_value, "DEFAULT"
