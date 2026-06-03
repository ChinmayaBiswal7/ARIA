"""
skills/opportunity_detector.py -- Phase 6B: Strategic Opportunity Detector
========================================================================
Traverses the SQLite advanced knowledge graph to discover strategic showcase,
synergy, goal learning, and workflow automation opportunities.
Implements acceptance feedback loops, adaptive counters, average confidence,
and 30-day presentation cooldowns.
Fully cp1252 safe.
"""

import os
import json
import sqlite3
import time


class AriaOpportunityDetector:
    def __init__(self, db_path=None):
        repo_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = db_path or os.path.join(repo_path, "aria_memory.db")
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 1. Create opportunity history tracking table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS project_opportunity_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    last_presented_timestamp INTEGER NOT NULL,
                    opportunity_type TEXT NOT NULL,
                    title TEXT NOT NULL UNIQUE,
                    source_nodes TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    impact REAL NOT NULL,
                    status TEXT DEFAULT 'pending'
                )
            """)
            
            # 2. Create opportunity weights learning table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS opportunity_weights (
                    opportunity_type TEXT PRIMARY KEY,
                    weight_modifier REAL DEFAULT 1.0,
                    times_accepted INTEGER DEFAULT 0,
                    times_dismissed INTEGER DEFAULT 0
                )
            """)
            
            # Seed default weights
            for optype in ["TECHNICAL_SHOWCASE", "ARCHITECTURE_SYNERGY", "GOAL_ALIGNMENT", "AUTOMATION"]:
                cursor.execute("""
                    INSERT OR IGNORE INTO opportunity_weights 
                    (opportunity_type, weight_modifier, times_accepted, times_dismissed)
                    VALUES (?, 1.0, 0, 0)
                """, (optype,))
                
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[OpportunityDetector] Database initialization failed: {e}")

    def _get_weight_info(self, optype: str) -> tuple:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT weight_modifier, times_accepted, times_dismissed 
                FROM opportunity_weights WHERE opportunity_type = ?
            """, (optype,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return row[0], row[1], row[2]
        except Exception:
            pass
        return 1.0, 0, 0

    def _is_suppressed(self, title: str) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            thirty_days_ago = int(time.time()) - 2592000
            cursor.execute("""
                SELECT 1 FROM project_opportunity_history 
                WHERE title = ? AND last_presented_timestamp > ?
            """, (title, thirty_days_ago))
            suppressed = cursor.fetchone() is not None
            conn.close()
            return suppressed
        except Exception:
            return False

    def detect_showcase_opportunities(self) -> list:
        """
        Pattern: [Project] -> uses/depends_on -> [Technology] AND [Chinmay] -> member_of -> [Organization]
        """
        opportunities = []
        optype = "TECHNICAL_SHOWCASE"
        weight_mod, _, _ = self._get_weight_info(optype)

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Traverses Project -> Tech AND User -> Org
            query = """
                SELECT DISTINCT 
                       n_proj.name, n_proj.confidence,
                       n_tech.name, n_tech.confidence,
                       n_org.name, n_org.confidence,
                       e_uses.confidence, e_user.confidence,
                       n_user.confidence
                FROM knowledge_graph_edges e_uses
                JOIN knowledge_graph_nodes n_proj ON e_uses.source_id = n_proj.id AND n_proj.type = 'Project'
                JOIN knowledge_graph_nodes n_tech ON e_uses.target_id = n_tech.id AND n_tech.type = 'Technology'
                
                JOIN knowledge_graph_edges e_user ON e_user.relation IN ('member_of', 'associated_with', 'belongs_to', 'works_at')
                JOIN knowledge_graph_nodes n_user ON e_user.source_id = n_user.id AND n_user.name LIKE 'chinmay%'
                JOIN knowledge_graph_nodes n_org ON e_user.target_id = n_org.id AND n_org.type = 'Organization'
                
                WHERE e_uses.relation IN ('uses', 'depends_on')
            """
            cursor.execute(query)
            matches = cursor.fetchall()
            conn.close()
        except Exception as e:
            print(f"[OpportunityDetector] Showcase query failed: {e}")
            matches = []

        for p_name, p_conf, t_name, t_conf, o_name, o_conf, e_uses_conf, e_user_conf, u_conf in matches:
            title = f"Technical Showcase: Present {p_name} at {o_name}"
            if self._is_suppressed(title):
                continue

            # Average-based confidence logic
            node_avg = (p_conf + t_conf + o_conf + u_conf) / 4.0
            edge_avg = (e_uses_conf + e_user_conf) / 2.0
            joint_conf = node_avg * edge_avg
            
            base_impact = 8.0
            final_score = round(base_impact * joint_conf * weight_mod, 2)

            opportunities.append({
                "type": optype,
                "title": title,
                "description": f"Since you are actively building '{p_name}' using '{t_name}', this would make a high-impact demo or workshop topic for your community at {o_name}.",
                "source_nodes": json.dumps([p_name, t_name, o_name]),
                "confidence": round(joint_conf, 2),
                "impact": base_impact,
                "final_score": final_score
            })
            
        return opportunities

    def detect_synergy_bridges(self) -> list:
        """
        Pattern: [Project A] -> uses -> [Tech] AND [Project B] -> uses -> [Tech]
        """
        opportunities = []
        optype = "ARCHITECTURE_SYNERGY"
        weight_mod, _, _ = self._get_weight_info(optype)

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            query = """
                SELECT DISTINCT 
                       n1.name, n1.confidence,
                       n2.name, n2.confidence,
                       n3.name, n3.confidence,
                       e1.confidence, e2.confidence
                FROM knowledge_graph_edges e1
                JOIN knowledge_graph_nodes n1 ON e1.source_id = n1.id AND n1.type = 'Project'
                JOIN knowledge_graph_nodes n3 ON e1.target_id = n3.id AND n3.type = 'Technology'
                
                JOIN knowledge_graph_edges e2 ON e2.target_id = e1.target_id AND e2.relation IN ('uses', 'depends_on')
                JOIN knowledge_graph_nodes n2 ON e2.source_id = n2.id AND n2.type = 'Project'
                WHERE e1.relation IN ('uses', 'depends_on') AND n1.id < n2.id
            """
            cursor.execute(query)
            matches = cursor.fetchall()
            conn.close()
        except Exception as e:
            print(f"[OpportunityDetector] Synergy query failed: {e}")
            matches = []

        for p1_name, p1_conf, p2_name, p2_conf, t_name, t_conf, e1_conf, e2_conf in matches:
            title = f"Code Reuse Synergy: Share {t_name} logic"
            if self._is_suppressed(title):
                continue

            node_avg = (p1_conf + p2_conf + t_conf) / 3.0
            edge_avg = (e1_conf + e2_conf) / 2.0
            joint_conf = node_avg * edge_avg

            base_impact = 7.0
            final_score = round(base_impact * joint_conf * weight_mod, 2)

            opportunities.append({
                "type": optype,
                "title": title,
                "description": f"Both '{p1_name}' and '{p2_name}' utilize '{t_name}'. You can modularize your backend logic to accelerate development across both domains.",
                "source_nodes": json.dumps([p1_name, p2_name, t_name]),
                "confidence": round(joint_conf, 2),
                "impact": base_impact,
                "final_score": final_score
            })
            
        return opportunities

    def detect_goal_alignment(self) -> list:
        """
        Pattern: [Goal] -> requires/supports -> [Technology] (with no project currently using it)
        """
        opportunities = []
        optype = "GOAL_ALIGNMENT"
        weight_mod, _, _ = self._get_weight_info(optype)

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            query = """
                SELECT DISTINCT 
                       n1.name, n1.confidence,
                       n2.name, n2.confidence,
                       e1.confidence
                FROM knowledge_graph_edges e1
                JOIN knowledge_graph_nodes n1 ON e1.source_id = n1.id AND n1.type = 'Goal'
                JOIN knowledge_graph_nodes n2 ON e1.target_id = n2.id AND n2.type = 'Technology'
                WHERE e1.relation IN ('requires', 'teaches', 'linked_to', 'supports', 'uses')
            """
            cursor.execute(query)
            matches = cursor.fetchall()
            
            aligned_opportunities = []
            for g_name, g_conf, t_name, t_conf, e_conf in matches:
                # Check if any active project uses this technology
                cursor.execute("""
                    SELECT 1 FROM knowledge_graph_edges e
                    JOIN knowledge_graph_nodes n_src ON e.source_id = n_src.id AND n_src.type = 'Project'
                    JOIN knowledge_graph_nodes n_tgt ON e.target_id = n_tgt.id AND n_tgt.type = 'Technology'
                    WHERE n_tgt.name = ? AND e.relation IN ('uses', 'depends_on')
                """, (t_name,))
                project_exists = cursor.fetchone() is not None
                
                if not project_exists:
                    aligned_opportunities.append((g_name, g_conf, t_name, t_conf, e_conf))
            conn.close()
        except Exception as e:
            print(f"[OpportunityDetector] Goal alignment query failed: {e}")
            aligned_opportunities = []

        for g_name, g_conf, t_name, t_conf, e_conf in aligned_opportunities:
            title = f"Goal Learning Project: Build {t_name} Showcase"
            if self._is_suppressed(title):
                continue

            node_avg = (g_conf + t_conf) / 2.0
            edge_avg = e_conf
            joint_conf = node_avg * edge_avg

            base_impact = 7.5
            final_score = round(base_impact * joint_conf * weight_mod, 2)

            opportunities.append({
                "type": optype,
                "title": title,
                "description": f"To support your goal '{g_name}', consider starting a lightweight showcase or study project centered around '{t_name}' as no active projects implement it.",
                "source_nodes": json.dumps([g_name, t_name]),
                "confidence": round(joint_conf, 2),
                "impact": base_impact,
                "final_score": final_score
            })
            
        return opportunities

    def detect_automation_opportunities(self) -> list:
        """
        Pattern: Normalizes timeline description logs and groups by count in past 14 days.
        Triggered if same description repeated >= 3 times.
        """
        opportunities = []
        optype = "AUTOMATION"
        weight_mod, _, _ = self._get_weight_info(optype)
        cutoff = int(time.time()) - (14 * 86400)

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT description, COUNT(*) 
                FROM project_timeline 
                WHERE timestamp >= ? 
                GROUP BY description 
                HAVING COUNT(*) >= 3
            """, (cutoff,))
            repeated_events = cursor.fetchall()
            conn.close()
        except Exception as e:
            print(f"[OpportunityDetector] Automation query failed: {e}")
            repeated_events = []

        for desc, count in repeated_events:
            # Strip trailing task symbols or ids if any
            clean_desc = desc.replace("[OK]", "").replace("[BLOCKER]", "").strip()
            title = f"Automate repeated workflow: {clean_desc}"
            if self._is_suppressed(title):
                continue

            # Highly confident as it is backed by actual logs
            joint_conf = 0.95
            base_impact = 6.5
            final_score = round(base_impact * joint_conf * weight_mod, 2)

            opportunities.append({
                "type": optype,
                "title": title,
                "description": f"You have executed the workflow '{clean_desc}' {count} times in the last 14 days. Writing a script to automate this would save you effort.",
                "source_nodes": json.dumps([clean_desc]),
                "confidence": joint_conf,
                "impact": base_impact,
                "final_score": final_score
            })
            
        return opportunities

    def log_and_rank_all(self) -> list:
        all_ideas = (
            self.detect_showcase_opportunities() +
            self.detect_synergy_bridges() +
            self.detect_goal_alignment() +
            self.detect_automation_opportunities()
        )
        
        # Sort by final score descending
        all_ideas.sort(key=lambda x: x["final_score"], reverse=True)
        return all_ideas

    def record_presentation(self, title: str, optype: str, source_nodes: str, confidence: float, impact: float):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            current_time = int(time.time())
            
            cursor.execute("""
                INSERT INTO project_opportunity_history 
                (timestamp, last_presented_timestamp, opportunity_type, title, source_nodes, confidence, impact)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(title) DO UPDATE SET last_presented_timestamp = excluded.last_presented_timestamp
            """, (current_time, current_time, optype, title, source_nodes, confidence, impact))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[OpportunityDetector] Failed to log presentation: {e}")

    def process_opportunity_feedback(self, title: str, user_action: str):
        """
        Updates feedback stats and learns category preference weights.
        user_action: 'accepted' or 'dismissed'
        """
        user_action = user_action.strip().lower()
        if user_action not in ["accepted", "dismissed"]:
            return

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 1. Update status
            cursor.execute("""
                UPDATE project_opportunity_history 
                SET status = ? 
                WHERE title = ?
            """, (user_action, title))
            
            # 2. Retrieve type
            cursor.execute("SELECT opportunity_type FROM project_opportunity_history WHERE title = ?", (title,))
            row = cursor.fetchone()
            
            if row:
                optype = row[0]
                cursor.execute("""
                    SELECT weight_modifier, times_accepted, times_dismissed 
                    FROM opportunity_weights WHERE opportunity_type = ?
                """, (optype,))
                w_row = cursor.fetchone()
                
                if w_row:
                    curr_weight, acc_count, dis_count = w_row
                    
                    if user_action == "accepted":
                        new_weight = min(2.0, curr_weight + 0.15)
                        acc_count += 1
                    else:
                        new_weight = max(0.2, curr_weight - 0.15)
                        dis_count += 1
                        
                    cursor.execute("""
                        UPDATE opportunity_weights 
                        SET weight_modifier = ?, times_accepted = ?, times_dismissed = ?
                        WHERE opportunity_type = ?
                    """, (new_weight, acc_count, dis_count, optype))
                    print(f"[AriaOpportunityDetector] Modifying weight: {optype} -> {new_weight:.2f} (Accepts: {acc_count}, Dismisses: {dis_count})")
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[OpportunityDetector] Feedback processing failed: {e}")
