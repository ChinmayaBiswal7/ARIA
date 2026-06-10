import os
import sqlite3
import json
import time
from typing import Dict, Any, List, Tuple
from contextlib import closing

class AriaOpportunityDiscoveryEngine:
    def __init__(self, db_path: str = "aria_orchestrator.db"):
        self.db_path = db_path
        self._init_opportunity_schema()

    def _init_opportunity_schema(self):
        """Creates tables for tracking external opportunities and historical recommendation metrics."""
        if not self.db_path:
            return
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS external_opportunities (
                        opportunity_id TEXT PRIMARY KEY,
                        title TEXT,
                        provider TEXT,
                        source TEXT,
                        required_skills TEXT, -- JSON array of strings
                        missing_skills TEXT,  -- JSON array of strings
                        estimated_preparation_hours INTEGER,
                        career_value TEXT,    -- 'LOW', 'MEDIUM', 'HIGH', 'VERY_HIGH'
                        application_deadline INTEGER,
                        match_score REAL,
                        roi_score REAL,
                        status TEXT DEFAULT 'DISCOVERED', -- 'DISCOVERED', 'PROPOSED', 'ACCEPTED', 'IGNORED', 'EXPIRED'
                        last_seen INTEGER
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS opportunity_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        opportunity_id TEXT,
                        action_taken TEXT,    -- 'PROPOSED', 'ACCEPTED', 'IGNORED', 'EXPIRED'
                        accepted INTEGER,     -- 1 or 0
                        outcome_score REAL,
                        timestamp INTEGER
                    )
                """)
                conn.commit()
        except Exception as e:
            print(f"[OpportunityDiscovery] Schema initialization failed: {e}")

    def seed_market_listings(self):
        """Seeds mock data representing external opportunity listings from 10 target platforms."""
        if not os.path.exists(self.db_path):
            return
        
        now = int(time.time())
        listings = [
            {
                "id": "OPP_GG_SWE_2027",
                "title": "Software Engineering Intern (Summer 2027)",
                "provider": "Google",
                "source": "Google Careers",
                "required_skills": json.dumps(["Java", "DSA", "C++"]),
                "hours": 45,
                "value": "VERY_HIGH",
                "deadline": now + 15 * 86400 # 15 days from now
            },
            {
                "id": "OPP_AWS_VOUCH_2026",
                "title": "AWS Cloud Practitioner Certification Voucher",
                "provider": "AWS Academy",
                "source": "AWS Academy",
                "required_skills": json.dumps(["Cloud Architecture", "Python"]),
                "hours": 18,
                "value": "MEDIUM",
                "deadline": now + 60 * 86400 # 60 days
            },
            {
                "id": "OPP_UNSTOP_HACK_2026",
                "title": "National Coding Hackathon 2026",
                "provider": "Unstop",
                "source": "Unstop",
                "required_skills": json.dumps(["Java", "Spring", "DBMS"]),
                "hours": 24,
                "value": "HIGH",
                "deadline": now + 30 * 86400 # 30 days
            },
            {
                "id": "OPP_DEVFOLIO_WEB3",
                "title": "Web3 Solidity Hackathon",
                "provider": "Devfolio",
                "source": "Devfolio",
                "required_skills": json.dumps(["Solidity", "Cryptography", "JavaScript"]),
                "hours": 50,
                "value": "MEDIUM",
                "deadline": now + 45 * 86400
            },
            {
                "id": "OPP_HE_DSA_CHALLENGE",
                "title": "Monthly Algorithms Challenge",
                "provider": "HackerEarth",
                "source": "HackerEarth",
                "required_skills": json.dumps(["DSA", "C++"]),
                "hours": 10,
                "value": "MEDIUM",
                "deadline": now + 10 * 86400
            },
            {
                "id": "OPP_KAGGLER_DATA",
                "title": "Predictive Regression Competition",
                "provider": "Kaggle",
                "source": "Kaggle",
                "required_skills": json.dumps(["Python", "Pandas", "Scikit-Learn"]),
                "hours": 60,
                "value": "HIGH",
                "deadline": now + 25 * 86400
            },
            {
                "id": "OPP_GSOC_2027",
                "title": "Google Summer of Code Open Source Contributor",
                "provider": "GSoC",
                "source": "GSoC",
                "required_skills": json.dumps(["Git", "Python", "Docker"]),
                "hours": 80,
                "value": "VERY_HIGH",
                "deadline": now + 90 * 86400
            },
            {
                "id": "OPP_GH_STUDENT",
                "title": "GitHub Student Developer Pack Perks",
                "provider": "GitHub",
                "source": "GitHub Student Pack",
                "required_skills": json.dumps(["Git", "GitHub"]),
                "hours": 5,
                "value": "MEDIUM",
                "deadline": now + 120 * 86400
            },
            {
                "id": "OPP_LINKEDIN_JAVA",
                "title": "Junior Backend Java Developer",
                "provider": "Local Startup",
                "source": "LinkedIn Jobs",
                "required_skills": json.dumps(["Java", "Spring", "Docker", "SQL"]),
                "hours": 35,
                "value": "VERY_HIGH",
                "deadline": now + 5 * 86400
            },
            {
                "id": "OPP_COURSERA_SPRING",
                "title": "Spring Boot Microservices Course Voucher",
                "provider": "Coursera",
                "source": "Coursera / Google Certs",
                "required_skills": json.dumps(["Spring", "Java"]),
                "hours": 15,
                "value": "MEDIUM",
                "deadline": now + 40 * 86400
            }
        ]

        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                for lst in listings:
                    conn.execute("""
                        INSERT OR REPLACE INTO external_opportunities 
                        (opportunity_id, title, provider, source, required_skills, estimated_preparation_hours, career_value, application_deadline, last_seen)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (lst["id"], lst["title"], lst["provider"], lst["source"], lst["required_skills"], lst["hours"], lst["value"], lst["deadline"], now))
                conn.commit()
        except Exception as e:
            print(f"[OpportunityDiscovery] Error seeding listings: {e}")

    def nightly_opportunity_cleanup(self) -> int:
        """Deactivates expired listings by transitioning status to 'EXPIRED' and logging to history."""
        now = int(time.time())
        expired_count = 0
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                # Select all DISCOVERED or PROPOSED opportunities where deadline has passed
                cursor = conn.execute("""
                    SELECT opportunity_id FROM external_opportunities 
                    WHERE status IN ('DISCOVERED', 'PROPOSED') AND application_deadline < ?
                """, (now,))
                rows = cursor.fetchall()
                for row in rows:
                    opp_id = row["opportunity_id"]
                    conn.execute("UPDATE external_opportunities SET status = 'EXPIRED' WHERE opportunity_id = ?", (opp_id,))
                    conn.execute("""
                        INSERT INTO opportunity_history (opportunity_id, action_taken, accepted, outcome_score, timestamp)
                        VALUES (?, 'EXPIRED', 0, 0.0, ?)
                    """, (opp_id, now))
                    expired_count += 1
                conn.commit()
        except Exception as e:
            print(f"[OpportunityDiscovery] Error in nightly cleanup: {e}")
        return expired_count

    def log_opportunity_action(self, opportunity_id: str, action_taken: str, accepted: int, outcome_score: float = 0.0):
        """Logs an action taken on a specific opportunity to record historical effectiveness."""
        now = int(time.time())
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    INSERT INTO opportunity_history (opportunity_id, action_taken, accepted, outcome_score, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (opportunity_id, action_taken, accepted, outcome_score, now))
                conn.execute("""
                    UPDATE external_opportunities 
                    SET status = ? 
                    WHERE opportunity_id = ?
                """, (action_taken, opportunity_id))
                conn.commit()
        except Exception as e:
            print(f"[OpportunityDiscovery] Error logging action to history: {e}")

    def evaluate_and_score_opportunities(self, aria_instance) -> List[Dict[str, Any]]:
        """Scans external listings, calculates match ratio/skill gaps, runs P18 simulations, and computes priority score."""
        proposals = []
        if not os.path.exists(self.db_path):
            return proposals

        # P22: Suppress opportunity scans if overall life load is critical (> 0.85)
        try:
            from skills.personal_os_reasoning import PersonalOSReasoningEngine
            os_engine = PersonalOSReasoningEngine(db_path=self.db_path)
            pressures = os_engine.compute_systemic_pressures()
            if pressures.get("overall_life_load", 0.0) > 0.85:
                print("[OpportunityDiscovery] Life Load > 0.85. Suppressing opportunity evaluation sweeps.")
                return proposals
        except Exception:
            pass

        now = int(time.time())
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                verified_skills = self._fetch_verified_skills(conn)
                
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM external_opportunities WHERE status = 'DISCOVERED'")
                raw_opps = cursor.fetchall()

            for opp in raw_opps:
                opp_id = opp["opportunity_id"]
                req_skills = json.loads(opp["required_skills"])
                prep_hours = opp["estimated_preparation_hours"]

                # 1. Match Scoring & Skill Gaps
                matched = [s for s in req_skills if s.lower().strip() in verified_skills]
                missing = [s for s in req_skills if s.lower().strip() not in verified_skills]
                match_score = len(matched) / len(req_skills) if req_skills else 1.0

                # 2. ROI Normalization (Career Value points / prep hours)
                val_points = {"LOW": 1.0, "MEDIUM": 2.0, "HIGH": 3.0, "VERY_HIGH": 4.0}.get(opp["career_value"], 2.0)
                roi_score = val_points / max(1, prep_hours)
                # Normalize ROI: let's map value=4.0/hours=10.0 (0.40 score) to 1.0 ceiling
                roi_normalized = min(1.0, roi_score / 0.40)

                # 3. Deadline Pressure Factor (Clamped: closer deadline has higher score)
                days_left = (opp["application_deadline"] - now) / 86400.0
                if days_left <= 0:
                    continue  # Expired
                deadline_factor = max(0.0, min(1.0, 1.0 - (days_left / 90.0)))

                # 4. Integrate Simulation Engine (Monte Carlo completion projections)
                prob, burnout = self._run_simulation_forecast(opp_id, opp["title"], req_skills, missing, prep_hours)

                # 5. Compute Executive Priority Score
                exec_score = (match_score * 0.25) + (prob * 0.30) + ((1.0 - burnout) * 0.20) + (roi_normalized * 0.15) + (deadline_factor * 0.10)
                exec_score = round(exec_score, 3)

                recommended = "YES" if (exec_score >= 0.70 and burnout < 0.70) else "NO"

                proposal_card = {
                    "opportunity_id": opp_id,
                    "title": opp["title"],
                    "provider": opp["provider"],
                    "source": opp["source"],
                    "match_score": match_score,
                    "roi_score": roi_normalized,
                    "missing_skills": missing,
                    "estimated_preparation_hours": prep_hours,
                    "completion_probability": prob,
                    "burnout_risk": burnout,
                    "deadline_days": int(days_left),
                    "executive_score": exec_score,
                    "recommended": recommended
                }

                # Update database record
                with closing(sqlite3.connect(self.db_path)) as conn:
                    conn.execute("""
                        UPDATE external_opportunities 
                        SET match_score = ?, roi_score = ?, missing_skills = ?, status = 'PROPOSED' 
                        WHERE opportunity_id = ?
                    """, (match_score, roi_normalized, json.dumps(missing), opp_id))
                    conn.commit()

                # Dispatch Alert if recommended and alert router exists
                if recommended == "YES" and hasattr(aria_instance, "alert_router") and aria_instance.alert_router:
                    aria_instance.alert_router.dispatch_alert(
                        title="🎯 STRATEGIC OPPORTUNITY PROPOSED",
                        body=f"{opp['title']} by {opp['provider']} is recommended (Executive Score: {exec_score:.2f}).",
                        priority="HIGH",
                        category="OPPORTUNITY"
                    )

                proposals.append(proposal_card)
        except Exception as e:
            print(f"[OpportunityDiscovery] Error evaluating opportunities: {e}")

        return proposals

    def _fetch_verified_skills(self, conn) -> List[str]:
        try:
            cursor = conn.execute("SELECT DISTINCT target_node FROM knowledge_graph_edges")
            return [row[0].lower().strip() for row in cursor.fetchall() if row[0]]
        except Exception:
            return ["java", "dsa", "c++", "python", "spring", "docker"]

    def _run_simulation_forecast(self, opp_id: str, title: str, req_skills: List[str], missing_skills: List[str], prep_hours: int) -> Tuple[float, float]:
        """Component P18 Integration: Runs a Monte Carlo simulation pass for the preparation workload."""
        dummy_tasks = [
            {
                "id": f"TSK_PREP_{opp_id}",
                "description": f"Prepare for {title} (Required: {', '.join(req_skills)})",
                "priority": "HIGH",
                "agent_target": "LearningAgent"
            }
        ]
        try:
            from skills.simulation_engine import AriaSimulationEngine
            sim_engine = AriaSimulationEngine(self.db_path)
            prob, burnout, delay, cost = sim_engine._run_monte_carlo_simulation(
                path_type="BALANCED",
                tasks=dummy_tasks,
                baseline_capacity=240,
                energy_score=70,
                weak_areas=missing_skills,
                avg_intervention_success=0.75,
                domain_success_rates={}
            )
            return round(prob, 2), round(burnout, 2)
        except Exception as e:
            # Fallback based on matches
            match_ratio = 1.0 - (len(missing_skills) / max(1, len(req_skills)))
            prob = max(0.10, min(0.95, match_ratio))
            burnout = 0.25 if prep_hours < 40 else 0.65
            return prob, burnout
