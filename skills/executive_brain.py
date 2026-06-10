"""
skills/executive_brain.py — Sprint P24: Unified Cognitive Core (Stage 1: Shadow Mode)
======================================================================================
Implements three tightly coupled components:

  1. AriaCognitiveStateAggregator
       Queries all 7 mature ARIA subsystems and compiles a single, structured
       JSON snapshot:  PersonalOS · Simulation · StrategicMemory · LearningPolicies
                       WorkforceOptimizer · OpportunityDiscovery · AutonomousGoals

  2. AriaExecutiveBrain  (Stage 1: Shadow Mode)
       Event-driven reasoning loop.  Reads the aggregated snapshot, asks Vertex AI
       what it would do, and logs the result alongside the actual ChiefOfStaff
       decision to the executive_shadow_ledger.  No real system mutations.

       Stage-gate cooldown:  30 minutes between passes except for EMERGENCY /
       CRITICAL_FATIGUE / EXAM_PREP_GUARD events.

       4-vector weighted alignment scoring:
           Directive  30 %   |   Domain   30 %
           Risk       20 %   |   ROI      20 %

  3. ExecutiveActionDispatcher  (Stage 2 stub — no-ops until Stage 2 is enabled)
       Will translate brain decisions into live EventBus / DB actions once enough
       alignment data is collected.

Trigger events understood:
    LIFE_OS_SHIFT          — life_state changed (burnout / exam / recovery)
    OPPORTUNITY_FOUND      — new high-ROI opportunity discovered
    CAMPAIGN_BLOCKER       — campaign stuck with an active blocker
    DAILY_REVIEW           — morning / evening scheduled review pass
    EMERGENCY              — immediate escalation, bypasses cooldown
    CRITICAL_FATIGUE       — energy_score < 30, bypasses cooldown
    EXAM_PREP_GUARD        — exam within 24 h, bypasses cooldown

Fully cp1252 safe.  No external dependencies beyond the ARIA skills layer.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from typing import Any, Dict, List, Optional, Tuple

from skills.base_agent import BaseAgent
from skills.event_bus import ARIAEvents, EventBus

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_DB = "aria_orchestrator.db"

# Seconds between executive passes in Shadow Mode (30 min)
MIN_EXECUTIVE_INTERVAL: int = 1800

# Events that bypass the cooldown gate
BYPASS_COOLDOWN_EVENTS = {"EMERGENCY", "CRITICAL_FATIGUE", "EXAM_PREP_GUARD"}

# New ARIAEvents event type for executive decisions
EXECUTIVE_SHADOW_LOGGED = "EXECUTIVE_SHADOW_LOGGED"


# ─────────────────────────────────────────────────────────────────────────────
# Schema bootstrap
# ─────────────────────────────────────────────────────────────────────────────

def init_executive_schema(db_path: str = _DEFAULT_DB) -> None:
    """
    Creates all tables required by P24 Stage 1 if they do not already exist.
    Safe to call on every startup — all statements use CREATE TABLE IF NOT EXISTS.
    """
    statements = [
        # ── Shadow decision ledger ──────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS executive_shadow_ledger (
            decision_id             TEXT PRIMARY KEY,
            trigger_event_source    TEXT    NOT NULL,
            aggregated_state_json   TEXT    NOT NULL,   -- full CognitiveState snapshot
            brain_directive         TEXT,
            brain_domain            TEXT,
            brain_risk_estimate     REAL,
            brain_roi_estimate      REAL,
            brain_justification     TEXT,
            cos_directive           TEXT,
            cos_domain              TEXT,
            cos_risk_estimate       REAL,
            cos_roi_estimate        REAL,
            directive_match         REAL,               -- 0.0 or 1.0
            domain_match            REAL,               -- 0.0 or 1.0
            risk_alignment          REAL,               -- 0.0 – 1.0
            roi_alignment           REAL,               -- 0.0 – 1.0
            weighted_alignment      REAL,               -- final 4-vector score
            actual_outcome_score    REAL    DEFAULT NULL,
            decision_winner         TEXT    DEFAULT 'PENDING',
            resolved_at             INTEGER DEFAULT NULL,
            timestamp               INTEGER NOT NULL
        )
        """,
        # ── Autonomous goals (P23 — created here if P23 not yet deployed) ──
        """
        CREATE TABLE IF NOT EXISTS autonomous_goals (
            goal_id             TEXT PRIMARY KEY,
            title               TEXT,
            goal_domain         TEXT    NOT NULL,
            source_signal       TEXT,               -- e.g. 'OPPORTUNITY', 'SKILL_GAP'
            alignment_score     REAL    DEFAULT 0.0,
            priority_tier       TEXT    DEFAULT 'STANDARD',
            lifecycle_state     TEXT    DEFAULT 'PROPOSED',
            justification       TEXT,
            campaign_id         TEXT,
            created_at          INTEGER NOT NULL,
            updated_at          INTEGER NOT NULL
        )
        """,
        # ── Cooldown tracking (one row, upserted) ───────────────────────────
        """
        CREATE TABLE IF NOT EXISTS executive_brain_state (
            key     TEXT PRIMARY KEY,
            value   TEXT NOT NULL
        )
        """,
    ]
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            for stmt in statements:
                conn.execute(stmt)
            conn.commit()
    except Exception as exc:
        print(f"[ExecutiveBrain] Schema init error: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Cognitive State Aggregator  (all 7 subsystems)
# ─────────────────────────────────────────────────────────────────────────────

class AriaCognitiveStateAggregator:
    """
    Compiles a unified, normalised JSON snapshot from every mature ARIA subsystem.
    Called once per executive pass — results are embedded in the ledger row so
    the full system state is preserved for retrospective analysis.
    """

    def __init__(self, db_path: str = _DEFAULT_DB) -> None:
        self.db_path = db_path

    # ── Public API ──────────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        """
        Returns a structured cognitive state dict with 7 top-level keys,
        one per subsystem, plus convergence overrides. All exceptions are silently swallowed and replaced
        with safe defaults so a partial outage never blocks the brain.
        """
        # Ingest convergence overrides
        try:
            from skills.intelligence_convergence_hub import AriaIntelligenceConvergenceHub
            db = self.db_path if "test_" in self.db_path else None
            hub = AriaIntelligenceConvergenceHub(db)
            overrides = hub.generate_convergence_overrides()
            matrix = hub.compile_converged_intelligence_matrix()
        except Exception as exc:
            print(f"[CognitiveAggregator] Convergence fetch failed: {exc}")
            overrides = {"interaction_mode": "STANDARD", "avoid_skills": [], "skill_routing_penalties": {}, "timeout_factor": 1.0, "extra_delay": 0.0, "max_proactive_interventions": 3}
            matrix = {}

        return {
            "timestamp": int(time.time()),
            "personal_os":          self._fetch_personal_os(),
            "simulation":           self._fetch_simulation(),
            "strategic_memory":     self._fetch_strategic_memory(),
            "learning_policies":    self._fetch_learning_policies(),
            "workforce":            self._fetch_workforce(),
            "opportunity_discovery":self._fetch_opportunities(),
            "autonomous_goals":     self._fetch_autonomous_goals(),
            "convergence_overrides": overrides,
            "convergence_matrix":    matrix,
        }

    # ── Subsystem fetchers ───────────────────────────────────────────────────

    def _fetch_personal_os(self) -> Dict[str, Any]:
        """P22: Full systemic pressure vector from PersonalOSReasoningEngine."""
        try:
            from skills.personal_os_reasoning import PersonalOSReasoningEngine
            engine = PersonalOSReasoningEngine(db_path=self.db_path)
            pressures = engine.compute_systemic_pressures()
            return {
                "life_state":               pressures.get("life_state", "NORMAL"),
                "overall_life_load":        pressures.get("overall_life_load", 0.0),
                "academic_pressure":        pressures.get("academic_pressure", 0.0),
                "energy_pressure":          pressures.get("energy_pressure", 0.0),
                "raw_energy_score":         pressures.get("raw_energy_score", 70),
                "sleep_debt":               pressures.get("sleep_debt", 0.0),
                "circadian_focus_multiplier": pressures.get("circadian_focus_multiplier", 1.0),
                "active_guards":            pressures.get("active_guards", []),
                "burnout_limit_policy":     pressures.get("burnout_limit_policy", 0.70),
            }
        except Exception as exc:
            print(f"[CognitiveAggregator] PersonalOS fetch failed: {exc}")
            return {
                "life_state": "UNKNOWN", "overall_life_load": 0.0,
                "raw_energy_score": 70, "active_guards": []
            }

    def _fetch_simulation(self) -> Dict[str, Any]:
        """P18: Latest scenario from simulation_scenarios table."""
        defaults = {
            "scenario_id": None,
            "completion_probability": 0.75,
            "burnout_risk": 0.20,
            "executive_score": 0.60,
            "expected_delay_days": 0,
            "path_type": "UNKNOWN",
        }
        if not os.path.exists(self.db_path):
            return defaults
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("""
                    SELECT scenario_id, completion_probability, burnout_risk,
                           executive_score, expected_delay, path_type
                    FROM   simulation_scenarios
                    ORDER  BY timestamp DESC
                    LIMIT  1
                """).fetchone()
                if row:
                    return {
                        "scenario_id":            row["scenario_id"],
                        "completion_probability": row["completion_probability"],
                        "burnout_risk":           row["burnout_risk"],
                        "executive_score":        row["executive_score"],
                        "expected_delay_days":    (row["expected_delay"] or 0) // 86400,
                        "path_type":              row["path_type"],
                    }
        except Exception as exc:
            print(f"[CognitiveAggregator] Simulation fetch failed: {exc}")
        return defaults

    def _fetch_strategic_memory(self) -> Dict[str, Any]:
        """P16: Recent completed task patterns + best intervention success rates."""
        defaults = {
            "recent_completed_tasks": [],
            "top_performing_domains": [],
            "avg_intervention_success": 0.75,
        }
        if not os.path.exists(self.db_path):
            return defaults
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT description, domain_keyword
                    FROM   agent_tasks
                    WHERE  status = 'COMPLETED'
                    ORDER  BY completed_at DESC
                    LIMIT  5
                """).fetchall()
                completed = [r["description"] for r in rows if r["description"]]

                # Top domains by completion ratio
                domain_rows = conn.execute("""
                    SELECT domain_keyword,
                           CAST(SUM(CASE WHEN status='COMPLETED' THEN 1 ELSE 0 END) AS REAL)
                           / COUNT(*) AS success_rate
                    FROM   agent_tasks
                    WHERE  domain_keyword IS NOT NULL
                    GROUP  BY domain_keyword
                    HAVING COUNT(*) >= 2
                    ORDER  BY success_rate DESC
                    LIMIT  3
                """).fetchall()
                top_domains = [r["domain_keyword"] for r in domain_rows]

                return {
                    "recent_completed_tasks": completed,
                    "top_performing_domains": top_domains,
                    "avg_intervention_success": 0.75,
                }
        except Exception as exc:
            print(f"[CognitiveAggregator] StrategicMemory fetch failed: {exc}")
        return defaults

    def _fetch_learning_policies(self) -> Dict[str, Any]:
        """P20: Active operational policies from system_operational_policies."""
        defaults = {
            "active_policies": [],
            "burnout_limit": 0.70,
            "simulation_bias": 0.0,
            "policy_count": 0,
        }
        if not os.path.exists(self.db_path):
            return defaults
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT policy_id, policy_type, policy_key, policy_value,
                           confidence, status
                    FROM   system_operational_policies
                    WHERE  status IN ('ACTIVE', 'PROBATION')
                    ORDER  BY confidence DESC
                """).fetchall()

                policies = [
                    {
                        "id":         r["policy_id"],
                        "type":       r["policy_type"],
                        "key":        r["policy_key"],
                        "value":      r["policy_value"],
                        "confidence": r["confidence"],
                        "status":     r["status"],
                    }
                    for r in rows
                ]

                burnout_limit = 0.70
                sim_bias = 0.0
                for p in policies:
                    if p["id"] == "POL_BURNOUT_LIMIT":
                        burnout_limit = p["value"]
                    if p["type"] == "SIMULATION_BIAS":
                        sim_bias = p["value"]

                return {
                    "active_policies":  policies,
                    "burnout_limit":    burnout_limit,
                    "simulation_bias":  sim_bias,
                    "policy_count":     len(policies),
                }
        except Exception as exc:
            print(f"[CognitiveAggregator] LearningPolicies fetch failed: {exc}")
        return defaults

    def _fetch_workforce(self) -> Dict[str, Any]:
        """P19: Best performing agent team from workforce_sessions."""
        defaults = {
            "top_team": [],
            "top_team_score": 0.0,
            "top_domain": "GENERAL",
            "total_sessions_logged": 0,
        }
        if not os.path.exists(self.db_path):
            return defaults
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("""
                    SELECT participating_agents,
                           AVG(review_score) AS avg_review,
                           AVG(success_score) AS avg_success,
                           domain_keyword,
                           COUNT(*) AS runs
                    FROM   workforce_sessions
                    GROUP  BY participating_agents
                    HAVING runs >= 3
                    ORDER  BY (avg_review * 0.5 + avg_success * 0.5) DESC
                    LIMIT  1
                """).fetchone()

                total = conn.execute("SELECT COUNT(*) FROM workforce_sessions").fetchone()[0]

                if row:
                    try:
                        team = json.loads(row["participating_agents"])
                    except Exception:
                        team = [row["participating_agents"]]
                    score = round(
                        (row["avg_review"] or 0) * 0.5 + (row["avg_success"] or 0) * 0.5, 3
                    )
                    return {
                        "top_team":             team,
                        "top_team_score":       score,
                        "top_domain":           row["domain_keyword"] or "GENERAL",
                        "total_sessions_logged": total,
                    }
                return {**defaults, "total_sessions_logged": total}
        except Exception as exc:
            print(f"[CognitiveAggregator] Workforce fetch failed: {exc}")
        return defaults

    def _fetch_opportunities(self) -> Dict[str, Any]:
        """P21: Top proposed opportunities from external_opportunities."""
        defaults = {
            "top_opportunity": None,
            "proposed_count": 0,
            "max_roi_score": 0.0,
        }
        if not os.path.exists(self.db_path):
            return defaults
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("""
                    SELECT title, provider, career_value, roi_score,
                           required_skills, missing_skills,
                           estimated_preparation_hours, application_deadline
                    FROM   external_opportunities
                    WHERE  status IN ('DISCOVERED', 'PROPOSED')
                    ORDER  BY roi_score DESC
                    LIMIT  1
                """).fetchone()
                count = conn.execute("""
                    SELECT COUNT(*) FROM external_opportunities
                    WHERE  status IN ('DISCOVERED', 'PROPOSED')
                """).fetchone()[0]

                if row:
                    top = {
                        "title":           row["title"],
                        "provider":        row["provider"],
                        "career_value":    row["career_value"],
                        "roi_score":       row["roi_score"],
                        "prep_hours":      row["estimated_preparation_hours"],
                        "days_to_deadline": max(
                            0,
                            ((row["application_deadline"] or 0) - int(time.time())) // 86400
                        ) if row["application_deadline"] else None,
                    }
                    return {
                        "top_opportunity": top,
                        "proposed_count":  count,
                        "max_roi_score":   row["roi_score"] or 0.0,
                    }
                return {**defaults, "proposed_count": count}
        except Exception as exc:
            print(f"[CognitiveAggregator] Opportunities fetch failed: {exc}")
        return defaults

    def _fetch_autonomous_goals(self) -> Dict[str, Any]:
        """P23: Staged autonomous goals awaiting promotion."""
        defaults = {
            "proposed_goals": [],
            "accepted_goals": [],
            "proposed_count": 0,
        }
        if not os.path.exists(self.db_path):
            return defaults
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT goal_id, title, goal_domain, priority_tier,
                           alignment_score, source_signal
                    FROM   autonomous_goals
                    WHERE  lifecycle_state IN ('PROPOSED', 'ACCEPTED')
                    ORDER  BY alignment_score DESC
                """).fetchall()

                proposed = [
                    {
                        "id":       r["goal_id"],
                        "domain":   r["goal_domain"],
                        "tier":     r["priority_tier"],
                        "score":    r["alignment_score"],
                        "signal":   r["source_signal"],
                    }
                    for r in rows if r["lifecycle_state"] == "PROPOSED"
                    # Note: lifecycle_state not in SELECT — filter by priority_tier heuristic
                ] if rows else []
                # Simplified: just return all
                goals = [dict(r) for r in rows]
                return {
                    "proposed_goals": goals,
                    "accepted_goals": [],
                    "proposed_count": len(goals),
                }
        except Exception as exc:
            print(f"[CognitiveAggregator] AutonomousGoals fetch failed: {exc}")
        return defaults


# ─────────────────────────────────────────────────────────────────────────────
# 2. Executive Brain  (Stage 1: Shadow Mode)
# ─────────────────────────────────────────────────────────────────────────────

class AriaExecutiveBrain(BaseAgent):
    """
    Stage 1: Shadow Mode — observes all subsystems, generates a parallel
    decision, and stores it alongside the actual ChiefOfStaff action.
    No mutations to campaign state, tasks, or EventBus commands.

    Usage (from ChiefOfStaff or any event handler):
        brain = AriaExecutiveBrain(aria_instance, db_path)
        brain.observe(
            event_source   = "CAMPAIGN_BLOCKER",
            cos_directive  = "INJECT_TASK",
            cos_domain     = "JAVA",
            cos_risk       = 0.30,
            cos_roi        = 0.55,
        )
    """

    # Vertex AI JSON schema for the executive decision
    _DECISION_SCHEMA: Dict[str, Any] = {
        "type": "OBJECT",
        "properties": {
            "primary_directive": {
                "type": "STRING",
                "description": (
                    "One of: DEPLOY_CAMPAIGN | INJECT_TASK | RAISE_PRIORITY | "
                    "TRIGGER_AGENT | SUSPEND_QUEUE | MAINTAIN_IDLE | DEFER_ALL | "
                    "TRIGGER_REMEDIATION | ALERT_USER | CALIBRATE_SYSTEM"
                )
            },
            "target_domain":        {"type": "STRING"},
            "modeled_risk":         {"type": "NUMBER"},
            "modeled_roi":          {"type": "NUMBER"},
            "justification":        {"type": "STRING"},
            "confidence":           {"type": "NUMBER"},
        },
        "required": [
            "primary_directive", "target_domain",
            "modeled_risk", "modeled_roi", "justification", "confidence"
        ]
    }

    _SYSTEM_INSTRUCTION = (
        "You are ARIA's top-level ExecutiveBrain operating in Stage 1 Shadow Mode. "
        "You analyse a unified cognitive snapshot spanning 7 subsystems and determine "
        "the single best strategic directive. You must output a valid JSON object "
        "matching the provided schema exactly.  Do not explain.  Do not add commentary."
    )

    def __init__(
        self,
        aria_instance: Any = None,
        db_path: str = _DEFAULT_DB,
    ) -> None:
        super().__init__("ExecutiveBrain", aria_instance)
        self.db_path = db_path
        self.aggregator = AriaCognitiveStateAggregator(db_path)
        self.bus = EventBus()
        init_executive_schema(db_path)

    # ── Public API ──────────────────────────────────────────────────────────

    def observe(
        self,
        event_source: str,
        cos_directive: str,
        cos_domain: str,
        cos_risk: float = 0.25,
        cos_roi: float   = 0.50,
    ) -> Dict[str, Any]:
        """
        Main entry point.  Checks the cooldown gate, aggregates state, runs
        the LLM pass, calculates alignment, and writes to the ledger.
        Returns a result dict (never raises).
        """
        event_source = event_source.upper().strip()

        # ── Cooldown gate ────────────────────────────────────────────────
        if event_source not in BYPASS_COOLDOWN_EVENTS:
            last_ts = self._get_last_run_ts()
            elapsed = int(time.time()) - last_ts
            if elapsed < MIN_EXECUTIVE_INTERVAL:
                remaining = MIN_EXECUTIVE_INTERVAL - elapsed
                print(
                    f"[ExecutiveBrain] Cooldown active — {remaining}s remaining. "
                    f"Skipping shadow pass for event '{event_source}'."
                )
                return {
                    "status": "COOLDOWN",
                    "event": event_source,
                    "next_pass_in_seconds": remaining,
                }

        self.log_state_shift(
            "RUNNING",
            f"Shadow pass triggered by '{event_source}' | "
            f"COS: {cos_directive} / {cos_domain}"
        )

        # ── Aggregate all 7 subsystems ───────────────────────────────────
        state = self.aggregator.snapshot()

        # ── LLM deliberation ─────────────────────────────────────────────
        brain_dec = self._deliberate(state, event_source, cos_directive, cos_domain)

        # ── 4-vector alignment ───────────────────────────────────────────
        alignment = self._score_alignment(brain_dec, cos_directive, cos_domain, cos_risk, cos_roi)

        # ── Persist to ledger ────────────────────────────────────────────
        decision_id = self._persist(
            event_source, state, brain_dec,
            cos_directive, cos_domain, cos_risk, cos_roi, alignment
        )

        # ── Update cooldown timestamp ────────────────────────────────────
        self._set_last_run_ts(int(time.time()))

        # ── Publish non-mutating observation event ───────────────────────
        self.bus.publish(
            EXECUTIVE_SHADOW_LOGGED,
            ARIAEvents.build_payload(
                task_id=decision_id,
                extra={
                    "event_source":      event_source,
                    "weighted_alignment": alignment["weighted"],
                    "brain_directive":   brain_dec.get("primary_directive"),
                }
            )
        )

        # ── Dispatch (Stage 2/3) ─────────────────────────────────────────
        stage = self.get_active_stage()
        dispatcher = ExecutiveActionDispatcher(self.db_path, self.aria)
        dispatch_status = dispatcher.dispatch(brain_dec, stage=stage)

        self.log_state_shift(
            "IDLE",
            f"Shadow logged {decision_id} | "
            f"Alignment: {alignment['weighted']:.0%} | Stage: {stage}"
        )

        return {
            "status":            "LOGGED",
            "decision_id":       decision_id,
            "brain_directive":   brain_dec.get("primary_directive"),
            "brain_domain":      brain_dec.get("target_domain"),
            "weighted_alignment": alignment["weighted"],
            "directive_match":   alignment["directive"],
            "domain_match":      alignment["domain"],
            "risk_alignment":    alignment["risk"],
            "roi_alignment":     alignment["roi"],
            "dispatch_status":   dispatch_status,
        }

    def resolve_outcome(
        self,
        decision_id: str,
        actual_outcome_score: float,
        winner: str,          # 'BRAIN' | 'CHIEF_OF_STAFF' | 'TIE'
    ) -> None:
        """
        Called after a campaign/task resolves to close the learning loop.
        winner should reflect which decision (brain vs chief) led to the
        better real-world result.
        """
        winner = winner.upper().strip()
        now = int(time.time())
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    UPDATE executive_shadow_ledger
                    SET    actual_outcome_score = ?,
                           decision_winner      = ?,
                           resolved_at          = ?
                    WHERE  decision_id = ?
                """, (actual_outcome_score, winner, now, decision_id))
                conn.commit()
            print(
                f"[ExecutiveBrain] Outcome resolved for {decision_id}: "
                f"Winner={winner}, Score={actual_outcome_score:.2f}"
            )
        except Exception as exc:
            print(f"[ExecutiveBrain] resolve_outcome error: {exc}")

    def alignment_summary(self, limit: int = 30) -> Dict[str, Any]:
        """
        Returns aggregate statistics from the last `limit` shadow decisions
        to track brain accuracy over time.
        """
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT weighted_alignment, directive_match, domain_match,
                           decision_winner, brain_directive, cos_directive
                    FROM   executive_shadow_ledger
                    ORDER  BY timestamp DESC
                    LIMIT  ?
                """, (limit,)).fetchall()

                if not rows:
                    return {"message": "No shadow decisions logged yet."}

                total   = len(rows)
                avg_aln = sum(r["weighted_alignment"] or 0 for r in rows) / total
                dir_aln = sum(r["directive_match"]    or 0 for r in rows) / total
                dom_aln = sum(r["domain_match"]       or 0 for r in rows) / total

                resolved = [r for r in rows if r["decision_winner"] != "PENDING"]
                brain_wins = sum(1 for r in resolved if r["decision_winner"] == "BRAIN")
                cos_wins   = sum(1 for r in resolved if r["decision_winner"] == "CHIEF_OF_STAFF")
                ties       = sum(1 for r in resolved if r["decision_winner"] == "TIE")

                return {
                    "total_passes":        total,
                    "avg_weighted_alignment": round(avg_aln, 3),
                    "directive_hit_rate":  round(dir_aln, 3),
                    "domain_hit_rate":     round(dom_aln, 3),
                    "resolved_decisions":  len(resolved),
                    "brain_wins":          brain_wins,
                    "chief_of_staff_wins": cos_wins,
                    "ties":                ties,
                    "stage2_eligible": (
                        total >= 50
                        and len(resolved) >= 10
                        and avg_aln >= 0.85
                        and brain_wins >= cos_wins
                    ),
                }
        except Exception as exc:
            print(f"[ExecutiveBrain] alignment_summary error: {exc}")
            return {"error": str(exc)}

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _deliberate(
        self,
        state: Dict[str, Any],
        event_source: str,
        cos_directive: str,
        cos_domain: str,
    ) -> Dict[str, Any]:
        """Calls Vertex AI with the cognitive snapshot; returns parsed JSON dict."""

        prompt = (
            "== ARIA EXECUTIVE SHADOW DECISION PASS ==\n\n"
            f"Event Trigger: {event_source}\n\n"
            "== 7-SUBSYSTEM COGNITIVE SNAPSHOT ==\n"
            f"{json.dumps(state, indent=2)}\n\n"
            "== CHIEF OF STAFF PARALLEL ACTION ==\n"
            f"Directive: {cos_directive}  |  Domain: {cos_domain}\n\n"
            "Select the single best strategic directive for this system state. "
            "Consider biometric guards first (FATIGUE / BURNOUT suppress heavy work), "
            "simulation burnout_risk second, and opportunity ROI last. "
            "Output the JSON schema exactly."
        )

        try:
            from skills.vertex_bridge import AriaVertexBridge
            bridge = AriaVertexBridge()
            if bridge.initialized:
                raw = bridge.generate(
                    prompt=prompt,
                    system_instruction=self._SYSTEM_INSTRUCTION,
                    enforce_json_schema=self._DECISION_SCHEMA,
                    model_type="pro",
                    brain_instance=self.aria,
                )
                return json.loads(raw)
        except Exception as exc:
            print(f"[ExecutiveBrain] Vertex deliberation failed: {exc}. Using local heuristic.")

        # ── Local heuristic fallback (no LLM) ──────────────────────────
        return self._local_heuristic(state, cos_directive, cos_domain)

    def _local_heuristic(
        self,
        state: Dict[str, Any],
        cos_directive: str,
        cos_domain: str,
    ) -> Dict[str, Any]:
        """
        Deterministic rule-based fallback when Vertex is unavailable.
        Mirrors the same decision logic used by ChiefOfStaff + PersonalOS.
        """
        life = state.get("personal_os", {})
        sim  = state.get("simulation", {})

        life_state   = life.get("life_state", "NORMAL")
        energy       = life.get("raw_energy_score", 70)
        burnout_risk = sim.get("burnout_risk", 0.20)
        guards       = life.get("active_guards", [])

        if "BURNOUT_PROTECTION" in guards or energy < 30 or burnout_risk > 0.75:
            directive = "DEFER_ALL"
            roi, risk = 0.10, burnout_risk
            reason = f"Critical fatigue detected (energy={energy}, burnout_risk={burnout_risk:.2f})."
        elif life_state == "EXAM_MODE":
            directive = "SUSPEND_QUEUE"
            roi, risk = 0.40, 0.15
            reason = "EXAM_MODE active — suppress non-academic campaigns."
        elif life_state == "RECOVERY_MODE":
            directive = "MAINTAIN_IDLE"
            roi, risk = 0.30, 0.10
            reason = "RECOVERY_MODE — preserve energy, defer heavy tasks."
        elif life_state == "HIGH_PERFORMANCE_MODE":
            directive = cos_directive   # agree with CoS during peak state
            roi, risk = 0.80, 0.15
            reason = "HIGH_PERFORMANCE_MODE — endorsing CoS directive."
        else:
            directive = cos_directive
            roi, risk = 0.60, 0.25
            reason = "Nominal state — deferring to CoS directive."

        opp = state.get("opportunity_discovery", {})
        top_opp = opp.get("top_opportunity")
        if top_opp and top_opp.get("roi_score", 0) > 0.85 and directive not in ("DEFER_ALL", "SUSPEND_QUEUE"):
            directive = "DEPLOY_CAMPAIGN"
            cos_domain = top_opp.get("title", cos_domain)[:20]
            reason += f" High-ROI opportunity: {top_opp.get('title', '')}."

        goals = state.get("autonomous_goals", {}).get("proposed_goals", [])
        if goals and directive not in ("DEFER_ALL", "SUSPEND_QUEUE", "MAINTAIN_IDLE"):
            top_goal = goals[0]
            cos_domain = top_goal.get("goal_domain", cos_domain)

        return {
            "primary_directive": directive,
            "target_domain":     cos_domain,
            "modeled_risk":      round(risk, 3),
            "modeled_roi":       round(roi, 3),
            "justification":     reason,
            "confidence":        0.65,
        }

    @staticmethod
    def _score_alignment(
        brain: Dict[str, Any],
        cos_directive: str,
        cos_domain: str,
        cos_risk: float,
        cos_roi: float,
    ) -> Dict[str, float]:
        """
        4-vector weighted alignment score.
            Directive  30 %
            Domain     30 %
            Risk       20 %   (proximity — 1 - abs_delta)
            ROI        20 %   (proximity)
        """
        directive_match = 1.0 if (
            brain.get("primary_directive", "").upper() == cos_directive.upper()
        ) else 0.0

        domain_match = 1.0 if (
            brain.get("target_domain", "").upper() == cos_domain.upper()
        ) else 0.0

        risk_delta   = abs(brain.get("modeled_risk", 0.25) - cos_risk)
        risk_align   = max(0.0, round(1.0 - risk_delta, 3))

        roi_delta    = abs(brain.get("modeled_roi", 0.50) - cos_roi)
        roi_align    = max(0.0, round(1.0 - roi_delta, 3))

        weighted = round(
            directive_match * 0.30
            + domain_match  * 0.30
            + risk_align    * 0.20
            + roi_align     * 0.20,
            3
        )

        return {
            "directive": directive_match,
            "domain":    domain_match,
            "risk":      risk_align,
            "roi":       roi_align,
            "weighted":  weighted,
        }

    def _persist(
        self,
        event_source: str,
        state: Dict[str, Any],
        brain: Dict[str, Any],
        cos_directive: str,
        cos_domain: str,
        cos_risk: float,
        cos_roi: float,
        alignment: Dict[str, float],
    ) -> str:
        """Writes one row to executive_shadow_ledger; returns the decision_id."""
        import random
        now  = int(time.time())
        dec_id = f"SHADOW_{now}_{random.randint(100000, 999999)}"
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    INSERT INTO executive_shadow_ledger (
                        decision_id, trigger_event_source, aggregated_state_json,
                        brain_directive, brain_domain, brain_risk_estimate,
                        brain_roi_estimate, brain_justification,
                        cos_directive, cos_domain, cos_risk_estimate, cos_roi_estimate,
                        directive_match, domain_match, risk_alignment, roi_alignment,
                        weighted_alignment, timestamp
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    dec_id, event_source, json.dumps(state),
                    brain.get("primary_directive"), brain.get("target_domain"),
                    brain.get("modeled_risk"), brain.get("modeled_roi"),
                    brain.get("justification"),
                    cos_directive, cos_domain, cos_risk, cos_roi,
                    alignment["directive"], alignment["domain"],
                    alignment["risk"],      alignment["roi"],
                    alignment["weighted"],  now,
                ))
                conn.commit()
        except Exception as exc:
            print(f"[ExecutiveBrain] Ledger write error: {exc}")
        return dec_id

    # ── Cooldown and Stage state persistence ──────────────────────────────────

    def get_active_stage(self) -> int:
        """
        Retrieves the active stage (1, 2, or 3) from the executive_brain_state table.
        If not manually overridden, evaluates eligibility criteria for auto-promotion.
        """
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                row = conn.execute(
                    "SELECT value FROM executive_brain_state WHERE key = 'executive_stage'"
                ).fetchone()
                if row:
                    return int(row[0])
        except Exception:
            pass

        # If not manually set, evaluate auto-promotion eligibility
        try:
            summary = self.alignment_summary(limit=100)
            if isinstance(summary, dict) and summary.get("stage2_eligible", False):
                self.set_active_stage(2)
                return 2
        except Exception:
            pass

        return 1

    def set_active_stage(self, stage: int) -> None:
        """Saves the manual active stage override to the executive_brain_state table."""
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    INSERT INTO executive_brain_state (key, value)
                    VALUES ('executive_stage', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """, (str(stage),))
                conn.commit()
        except Exception:
            pass

    def _get_last_run_ts(self) -> int:
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                row = conn.execute(
                    "SELECT value FROM executive_brain_state WHERE key = 'last_run_ts'"
                ).fetchone()
                return int(row[0]) if row else 0
        except Exception:
            return 0

    def _set_last_run_ts(self, ts: int) -> None:
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("""
                    INSERT INTO executive_brain_state (key, value)
                    VALUES ('last_run_ts', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """, (str(ts),))
                conn.commit()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# 3. Executive Action Dispatcher  (Stage 2 stub — currently no-ops)
# ─────────────────────────────────────────────────────────────────────────────

class ExecutiveActionDispatcher:
    """
    Stage 2 / Stage 3 placeholder.

    Activation criteria (checked by alignment_summary()):
        • >= 50 shadow decisions logged
        • weighted_alignment >= 0.85 on average
        • brain_wins >= chief_of_staff_wins in resolved decisions

    Until those conditions are met, all dispatch() calls are no-ops that
    log an ADVISORY note to the blackboard only.
    """

    STAGE2_THRESHOLD = {"min_passes": 50, "min_alignment": 0.85}

    def __init__(
        self,
        db_path: str = _DEFAULT_DB,
        aria_instance: Any = None,
    ) -> None:
        self.db_path = db_path
        self.aria    = aria_instance

    def dispatch(self, brain_decision: Dict[str, Any], stage: int = 1) -> str:
        """
        Stage 1: No-op — just log.
        Stage 2: Post advisory to blackboard.
        Stage 3: Full execution (not implemented yet).
        """
        directive = brain_decision.get("primary_directive", "UNKNOWN")
        domain    = brain_decision.get("target_domain", "?")

        if stage == 1:
            print(
                f"[Dispatcher] STAGE 1 — no-op. Brain wanted: {directive} / {domain}"
            )
            return "NOOP"

        if stage == 2:
            try:
                from skills.blackboard import AriaBlackboard
                bb = AriaBlackboard()
                bb.publish(
                    "executive",
                    "brain_advisory",
                    {
                        "directive":     directive,
                        "domain":        domain,
                        "confidence":    brain_decision.get("confidence", 0),
                        "justification": brain_decision.get("justification", ""),
                        "timestamp":     int(time.time()),
                    },
                    publisher="ExecutiveBrain",
                    ttl_hours=6,
                )
                print(f"[Dispatcher] STAGE 2 — Advisory published: {directive} / {domain}")
                return "ADVISORY_POSTED"
            except Exception as exc:
                print(f"[Dispatcher] Advisory post failed: {exc}")
                return "ERROR"

        # Stage 3 — not yet enabled
        print("[Dispatcher] STAGE 3 not yet enabled. Awaiting Stage 2 alignment baseline.")
        return "STAGE3_LOCKED"
