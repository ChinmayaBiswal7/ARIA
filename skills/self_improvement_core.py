"""
skills/self_improvement_core.py -- Sprints P11, P11.5, P12, P13
===============================================================
Core self-evaluation ledger and graph reasoning dependencies engine for ARIA.
Provides mechanisms to log predictions, trace interventions, track bottlenecks, and reflect.
"""

import sqlite3
import json
import time
from typing import Dict, Any, List

def init_self_improvement_schema(db_path: str):
    """Establishes the relational architecture for evaluation logs and knowledge graph links."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        # 1. Component P11: Transactional Prediction Registry
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prediction_ledger (
                prediction_id TEXT PRIMARY KEY,
                prediction_text TEXT,
                actual_outcome TEXT,
                accuracy_score REAL, -- 1.0 for True, 0.0 for False
                timestamp INTEGER
            )
        """)
        
        # 2. Component P11.5: Intervention Ledger
        conn.execute("""
            CREATE TABLE IF NOT EXISTS intervention_ledger (
                intervention_id TEXT PRIMARY KEY,
                campaign_id TEXT,
                agent TEXT,
                action TEXT,
                reason TEXT,
                timestamp INTEGER,
                result TEXT,
                success_score REAL -- 1.0 for Success, 0.0 for Failure
            )
        """)
        # Ensure migration: check table columns and alter if campaign_id is missing
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(intervention_ledger)")
        cols = [col[1] for col in cursor.fetchall()]
        if cols and "campaign_id" not in cols:
            conn.execute("ALTER TABLE intervention_ledger ADD COLUMN campaign_id TEXT")
        
        # 3. Component P12: Semantic Knowledge Graph Store
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_graph_edges (
                source_node TEXT,
                relationship TEXT, -- 'REQUIRES', 'BLOCKED_BY', 'BUILT_WITH', 'PARENT_OF'
                target_node TEXT,
                confidence_weight REAL DEFAULT 1.0,
                PRIMARY KEY (source_node, relationship, target_node)
            )
        """)
        
        # 4. Component P13: Weekly Reflection Archives
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_reflections (
                reflection_id TEXT PRIMARY KEY,
                horizon TEXT, -- 'WEEKLY', 'MONTHLY'
                insights TEXT,
                adapted_directives TEXT,
                timestamp INTEGER
            )
        """)
        conn.commit()

class AriaSelfImprovementCore:
    def __init__(self, db_path: str = None):
        if db_path:
            self.db_path = db_path
        else:
            try:
                from skills.agent_status import DB_PATH
                self.db_path = DB_PATH
            except ImportError:
                self.db_path = "aria_orchestrator.db"
        self._init_db()

    def _init_db(self):
        init_self_improvement_schema(self.db_path)

    # ── SPRINT P11: SELF-EVALUATION LOGGING ─────────────────────────────────
    def register_system_prediction(self, pred_id: str, prediction: str):
        """Logs a baseline prediction milestone to be audited later against reality."""
        now = int(time.time())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO prediction_ledger (prediction_id, prediction_text, actual_outcome, accuracy_score, timestamp)
                VALUES (?, ?, 'PENDING', NULL, ?)
            """, (pred_id, prediction, now))
            conn.commit()

    def resolve_prediction_outcome(self, pred_id: str, reality: str):
        """Audits a pending prediction against reality and saves the accuracy score."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT prediction_text FROM prediction_ledger WHERE prediction_id = ?", (pred_id,))
            row = cursor.fetchone()
            if not row:
                return

            predicted = row[0].strip().upper()
            actual = reality.strip().upper()
            score = 1.0 if predicted == actual else 0.0

            conn.execute("""
                UPDATE prediction_ledger 
                SET actual_outcome = ?, accuracy_score = ? 
                WHERE prediction_id = ?
            """, (actual, score, pred_id))
            conn.commit()

    # ── SPRINT P11.5: INTERVENTION LOGGING ──────────────────────────────────
    def register_intervention(self, intervention_id: str, agent: str, action: str, reason: str, result: str = "PENDING", success_score: float = None, campaign_id: str = None):
        """Logs an intervention deployment to the ledger."""
        now = int(time.time())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO intervention_ledger (intervention_id, campaign_id, agent, action, reason, timestamp, result, success_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (intervention_id, campaign_id, agent, action, reason, now, result, success_score))
            conn.commit()

    def resolve_intervention(self, intervention_id: str, result: str, success_score: float):
        """Resolves the outcome and success score of a logged intervention."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE intervention_ledger
                SET result = ?, success_score = ?
                WHERE intervention_id = ?
            """, (result, success_score, intervention_id))
            conn.commit()

    # ── SPRINT P12: KNOWLEDGE GRAPH REASONING ───────────────────────────────
    def inject_graph_dependency(self, source: str, relationship: str, target: str, weight: float = 1.0):
        """Injects a contextual directional link to expand ARIA's graph reasoning."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO knowledge_graph_edges (source_node, relationship, target_node, confidence_weight)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_node, relationship, target_node) DO UPDATE SET
                    confidence_weight = (confidence_weight + ?) / 2.0
            """, (source.strip(), relationship.upper().strip(), target.strip(), weight, weight))
            conn.commit()

    def identify_campaign_bottlenecks(self, target_goal: str) -> List[str]:
        """Traces dependency lines recursively across fields to locate blocked components."""
        bottlenecks = []
        visited = set()

        def trace(node):
            if node in visited:
                return
            visited.add(node)
            
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                # Find direct requirements or dependencies of the current node
                cursor = conn.execute("""
                    SELECT target_node, relationship FROM knowledge_graph_edges 
                    WHERE source_node = ?
                """, (node,))
                edges = cursor.fetchall()
                
                for edge in edges:
                    t_node = edge["target_node"]
                    rel = edge["relationship"]
                    
                    if rel == "BLOCKED_BY":
                        bottlenecks.append(f"Goal component '{node}' is halted because '{t_node}' is incomplete.")
                    
                    # Recurse down the dependency tree
                    trace(t_node)

        trace(target_goal)
        return bottlenecks

    # ── SPRINT P13: THE REFLECTION CORE ─────────────────────────────────────
    def execute_sunday_reflection_pass(self, vertex_bridge_instance) -> str:
        """Aggregates metrics and runs a deep strategy update via the Vertex AI bridge."""
        now = int(time.time())

        # Pull prediction stats to analyze accuracy trends
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT COUNT(*), AVG(accuracy_score) FROM prediction_ledger WHERE accuracy_score IS NOT NULL
            """)
            total_preds, avg_pred_acc = cursor.fetchone()
            pred_rate = avg_pred_acc if total_preds and avg_pred_acc is not None else 0.85

            cursor = conn.execute("""
                SELECT COUNT(*), AVG(success_score) FROM intervention_ledger WHERE success_score IS NOT NULL
            """)
            total_interventions, avg_inter_acc = cursor.fetchone()
            inter_rate = avg_inter_acc if total_interventions and avg_inter_acc is not None else 0.80

        prompt = f"""
        You are ARIA's core Strategic Reflection Engine powered by Vertex AI.
        It is Sunday afternoon. Conduct an objective self-audit of your execution, predictions, and interventions.
        
        == TRACKED PERFORMANCE METRICS ==
        Current Prediction Accuracy: {round(pred_rate * 100, 1)}% across {total_preds or 0} evaluations.
        Current Intervention Success Rate: {round(inter_rate * 100, 1)}% across {total_interventions or 0} interventions.
        
        Analyze what worked and what failed in your recommendations. Focus on optimizing Chinmaya's study habits and placement preparation.
        Output your analysis in this exact layout design format:
        
        ### 📊 Weekly Strategic Reflection
        
        **Self-Evaluation Accuracy Score:** {round(pred_rate * 100, 1)}%  
        **Intervention Success Score:** {round(inter_rate * 100, 1)}%  
        **Core Strategic Adjustments:** [Define exactly what long-term campaign plans need adjustment]
        
        - **What Succeeded:** [Identify hit milestones or accurate predictions]
        - **What Failed/Delayed:** [Identify missed targets, broken habits, or faulty assumptions]
        - **Next Week's Corrective Directives:** [List precise executive orders for the Chief of Staff loop]
        """
        
        # Use Vertex AI bridge's standard generate method (replaces cognitive_reasoning_pass)
        reflection_brief = vertex_bridge_instance.generate(prompt=prompt, model_type="pro")

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO system_reflections (reflection_id, horizon, insights, adapted_directives, timestamp)
                VALUES (?, 'WEEKLY', ?, '', ?)
            """, (f"REF_WEEK_{now}", reflection_brief, now))
            conn.commit()

        return reflection_brief

    def resolve_all_pending_predictions(self):
        """Audits all pending predictions in prediction_ledger against the habit dataset and completed tasks."""
        import os
        import glob
        import json
        
        now = int(time.time())
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT prediction_id, prediction_text, timestamp FROM prediction_ledger WHERE actual_outcome = 'PENDING'")
            pending = cursor.fetchall()
            
            if not pending:
                return

            for row in pending:
                pred_id = row["prediction_id"]
                predicted_topic = row["prediction_text"].strip().upper()
                pred_ts = row["timestamp"]
                
                # Check 1: Scan data/habit_dataset/*.json for a session within 3 hours
                dataset_dir = "data/habit_dataset"
                session_found = False
                actual_topic = None
                
                if os.path.exists(dataset_dir):
                    files = glob.glob(os.path.join(dataset_dir, "session_*.json"))
                    for f in files:
                        try:
                            # filename format: session_timestamp.json
                            basename = os.path.basename(f)
                            ts_str = basename.replace("session_", "").replace(".json", "")
                            file_ts = int(ts_str)
                            if abs(file_ts - pred_ts) <= 10800: # 3 hours
                                with open(f, "r", encoding="utf-8") as file:
                                    data = json.load(file)
                                actual_topic = data.get("topic", "DBMS").strip().upper()
                                session_found = True
                                break
                        except Exception:
                            continue
                            
                # Check 2: Scan SQLite agent_tasks for a completed task with same topic matching within 3 hours
                if not session_found:
                    task_cursor = conn.execute("""
                        SELECT task_description, completed_at FROM agent_tasks 
                        WHERE status = 'COMPLETED' AND completed_at IS NOT NULL 
                          AND abs(completed_at - ?) <= 10800
                    """, (pred_ts,))
                    tasks = task_cursor.fetchall()
                    for t in tasks:
                        desc = t["task_description"].upper()
                        # If the completed task description matches the predicted topic
                        if predicted_topic in desc:
                            actual_topic = predicted_topic
                            session_found = True
                            break
                        # Otherwise if it has any other known topic
                        for topic in ["DSA", "DBMS", "JAVA", "CN", "OS", "OOP", "INTERVIEW", "PROJECT"]:
                            if topic in desc:
                                actual_topic = topic
                                session_found = True
                                break
                        if session_found:
                            break
                            
                if session_found and actual_topic:
                    # Resolve with actual topic (score will be calculated inside resolve_prediction_outcome)
                    self.resolve_prediction_outcome(pred_id, actual_topic)
                    print(f"[SelfImprovement] Resolved prediction {pred_id} against actual session {actual_topic}.")
                elif now - pred_ts > 86400: # 24 hours
                    # No session was found and it's older than 24 hours -> MISSED
                    self.resolve_prediction_outcome(pred_id, "MISSED")
                    print(f"[SelfImprovement] Resolved prediction {pred_id} as MISSED (expired).")

    def resolve_all_pending_interventions(self):
        """Audits all pending interventions in intervention_ledger to compute success_score (impact score)."""
        now = int(time.time())
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT intervention_id, campaign_id, action, reason, timestamp FROM intervention_ledger WHERE result = 'PENDING'")
            pending = cursor.fetchall()
            
            for row in pending:
                i_id = row["intervention_id"]
                campaign_id = row["campaign_id"]
                action = row["action"].strip().upper()
                reason = row["reason"]
                ts = row["timestamp"]
                
                resolved = False
                success_score = 0.0
                result_status = "PENDING"
                
                if action == "INJECT_TASK":
                    # Extract injected task ID from reason (e.g. "Description | Injected Task ID: TSK_123")
                    task_id = None
                    if "Injected Task ID: " in reason:
                        task_id = reason.split("Injected Task ID: ")[-1].strip()
                        
                    if task_id:
                        task_cursor = conn.execute("SELECT status FROM agent_tasks WHERE id = ?", (task_id,))
                        t_row = task_cursor.fetchone()
                        if t_row:
                            status = t_row["status"].upper()
                            if status == "COMPLETED":
                                resolved = True
                                success_score = 1.0
                                result_status = "COMPLETED"
                            elif status == "FAILED":
                                resolved = True
                                success_score = 0.0
                                result_status = "FAILED"
                        else:
                            # Not found in tasks table - check if expired
                            if now - ts > 172800: # 48 hours
                                resolved = True
                                success_score = 0.0
                                result_status = "EXPIRED"
                    else:
                        resolved = True
                        success_score = 0.0
                        result_status = "INVALID_TASK_ID"
                        
                elif action == "RAISE_PRIORITY":
                    # Check if all tasks in the campaign that were pending at the time of priority boost are now completed
                    task_cursor = conn.execute("""
                        SELECT COUNT(*), SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) 
                        FROM agent_tasks 
                        WHERE campaign_id = ?
                    """, (campaign_id,))
                    res_row = task_cursor.fetchone()
                    t_count, t_completed = res_row[0], res_row[1]
                    
                    if t_count > 0:
                        if t_completed == t_count:
                            resolved = True
                            success_score = 1.0
                            result_status = "COMPLETED"
                        else:
                            # Check if failed or expired
                            task_failed_cursor = conn.execute("""
                                SELECT COUNT(*) FROM agent_tasks 
                                WHERE campaign_id = ? AND status = 'FAILED'
                            """, (campaign_id,))
                            failed_count = task_failed_cursor.fetchone()[0]
                            if failed_count > 0:
                                resolved = True
                                success_score = 0.0
                                result_status = "FAILED"
                            elif now - ts > 172800: # 48 hours
                                resolved = True
                                success_score = 0.0
                                result_status = "EXPIRED"
                    else:
                        # No tasks in campaign -> resolved as complete
                        resolved = True
                        success_score = 1.0
                        result_status = "NO_TASKS"
                        
                elif action == "TRIGGER_AGENT":
                    # Check if there is a completed task matching target campaign created/started after the intervention
                    task_cursor = conn.execute("""
                        SELECT status FROM agent_tasks 
                        WHERE campaign_id = ? AND created_at >= ?
                    """, (campaign_id, ts))
                    tasks = task_cursor.fetchall()
                    
                    if tasks:
                        # If any task succeeded
                        if any(t["status"] == "COMPLETED" for t in tasks):
                            resolved = True
                            success_score = 1.0
                            result_status = "COMPLETED"
                        elif all(t["status"] in ("FAILED", "CANCELLED") for t in tasks):
                            resolved = True
                            success_score = 0.0
                            result_status = "FAILED"
                    if not resolved and now - ts > 172800: # 48 hours
                        resolved = True
                        success_score = 0.0
                        result_status = "EXPIRED"
                        
                if resolved:
                    self.resolve_intervention(i_id, result_status, success_score)
                    print(f"[SelfImprovement] Resolved intervention {i_id} as {result_status} (score={success_score}).")

