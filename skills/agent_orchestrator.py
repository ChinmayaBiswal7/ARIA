import sqlite3
import time
import os
import threading
from typing import List, Dict, Any, Optional
from skills.agent_status import get_db_connection
from skills.task_scheduler import AriaTaskScheduler, update_campaign_progress

class AriaMultiAgentOrchestrator:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AriaMultiAgentOrchestrator, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, aria_instance=None):
        if self._initialized:
            if aria_instance:
                self.aria = aria_instance
            return
        self.aria = aria_instance
        self.active_workers = []
        self._init_schemas()
        self._seed_agent_resources()
        self.scheduler = AriaTaskScheduler(self.active_workers)
        self.scheduler.start()

        # P9.4 & P9.5: Subscribe to coordinate adjustments and blackboard changes
        from skills.event_bus import EventBus
        self.bus = EventBus()
        self.bus.subscribe("COACH_ADJUSTMENT", self.handle_coach_adjustment)
        self.bus.subscribe("BLACKBOARD_PUBLISHED", self._on_blackboard_change)

        self._initialized = True
        print("[Orchestrator] Multi-agent parallel task matrix operational.")

    def _init_schemas(self):
        with get_db_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS campaigns (
                    id TEXT PRIMARY KEY,
                    goal_text TEXT NOT NULL,
                    status TEXT DEFAULT 'PENDING',
                    progress REAL DEFAULT 0.0,
                    created_at INTEGER NOT NULL,
                    completed_at INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    task_description TEXT NOT NULL,
                    target TEXT,
                    priority INTEGER DEFAULT 5,
                    status TEXT DEFAULT 'PENDING',
                    timeout_seconds INTEGER DEFAULT 120,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 2,
                    started_at INTEGER,
                    created_at INTEGER NOT NULL,
                    completed_at INTEGER,
                    milestone_id TEXT,
                    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
                )
            """)
            
            # Run automated schema migrations for campaigns
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(campaigns)")
            campaigns_cols = [col[1] for col in cursor.fetchall()]
            if campaigns_cols:
                if "progress" not in campaigns_cols:
                    conn.execute("ALTER TABLE campaigns ADD COLUMN progress REAL DEFAULT 0.0")
                if "created_at" not in campaigns_cols:
                    conn.execute("ALTER TABLE campaigns ADD COLUMN created_at INTEGER")
                if "completed_at" not in campaigns_cols:
                    conn.execute("ALTER TABLE campaigns ADD COLUMN completed_at INTEGER")

            # Run automated schema migrations for agent_tasks
            cursor.execute("PRAGMA table_info(agent_tasks)")
            tasks_cols = [col[1] for col in cursor.fetchall()]
            if tasks_cols:
                if "target" not in tasks_cols:
                    conn.execute("ALTER TABLE agent_tasks ADD COLUMN target TEXT")
                if "priority" not in tasks_cols:
                    conn.execute("ALTER TABLE agent_tasks ADD COLUMN priority INTEGER DEFAULT 5")
                if "timeout_seconds" not in tasks_cols:
                    conn.execute("ALTER TABLE agent_tasks ADD COLUMN timeout_seconds INTEGER DEFAULT 120")
                if "retry_count" not in tasks_cols:
                    conn.execute("ALTER TABLE agent_tasks ADD COLUMN retry_count INTEGER DEFAULT 0")
                if "max_retries" not in tasks_cols:
                    conn.execute("ALTER TABLE agent_tasks ADD COLUMN max_retries INTEGER DEFAULT 2")
                if "started_at" not in tasks_cols:
                    conn.execute("ALTER TABLE agent_tasks ADD COLUMN started_at INTEGER")
                if "created_at" not in tasks_cols:
                    conn.execute("ALTER TABLE agent_tasks ADD COLUMN created_at INTEGER")
                if "completed_at" not in tasks_cols:
                    conn.execute("ALTER TABLE agent_tasks ADD COLUMN completed_at INTEGER")
                if "milestone_id" not in tasks_cols:
                    conn.execute("ALTER TABLE agent_tasks ADD COLUMN milestone_id TEXT")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_dependencies (
                    task_id TEXT NOT NULL,
                    depends_on_task_id TEXT NOT NULL,
                    PRIMARY KEY (task_id, depends_on_task_id),
                    FOREIGN KEY(task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_resources (
                    agent_name TEXT NOT NULL,
                    resource_name TEXT NOT NULL,
                    PRIMARY KEY (agent_name, resource_name)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    result_payload TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    FOREIGN KEY(task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_status (
                    agent_name TEXT PRIMARY KEY,
                    state TEXT DEFAULT 'IDLE',
                    current_task TEXT,
                    started_at INTEGER,
                    heartbeat INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS campaign_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS blackboard_store (
                    topic TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    expires_at INTEGER,
                    PRIMARY KEY (topic, key)
                )
            """)
            conn.commit()

    def _seed_agent_resources(self):
        with get_db_connection() as conn:
            # Seed resource locks
            conn.execute("INSERT OR IGNORE INTO agent_resources (agent_name, resource_name) VALUES ('browseragent', 'browser')")
            conn.execute("INSERT OR IGNORE INTO agent_resources (agent_name, resource_name) VALUES ('newsagent', 'browser')")
            conn.execute("INSERT OR IGNORE INTO agent_resources (agent_name, resource_name) VALUES ('researchagent', 'browser')")
            conn.commit()

            # P9.2: Create milestones table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS campaign_milestones (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT DEFAULT 'PENDING',
                    created_at INTEGER NOT NULL,
                    completed_at INTEGER,
                    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
                )
            """)

            # P9.2: Add milestone_id column to agent_tasks table
            try:
                conn.execute("ALTER TABLE agent_tasks ADD COLUMN milestone_id TEXT")
            except sqlite3.OperationalError:
                pass

            # Stage 2 Self-Improvement schemas init
            try:
                from skills.self_improvement_core import init_self_improvement_schema
                from skills.agent_status import DB_PATH
                init_self_improvement_schema(DB_PATH)
            except Exception as e:
                print(f"[Orchestrator] Failed to initialize self-improvement schemas: {e}")

            conn.commit()

    def submit_campaign(self, goal_text: str, tasks_data: List[Dict[str, Any]], milestones_data: List[Dict[str, Any]] = None) -> str:
        """
        Submits a campaign, its constituent tasks, milestones, and dependencies.
        """
        now = int(time.time())
        campaign_id = f"CMP_{int(time.time())}"
        
        # Translate local IDs to unique global task IDs to avoid campaign name collisions
        id_map = {}
        for t in tasks_data:
            local_id = t["id"]
            global_id = f"TSK_{campaign_id}_{local_id.upper()}"
            id_map[local_id] = global_id
            
        # Translate local milestone IDs to global milestone IDs
        milestone_map = {}
        if milestones_data:
            for m in milestones_data:
                local_m_id = m["id"]
                global_m_id = f"MS_{campaign_id}_{local_m_id.upper()}"
                milestone_map[local_m_id] = global_m_id
                
        with get_db_connection() as conn:
            # Insert Campaign
            conn.execute(
                "INSERT INTO campaigns (id, goal_text, status, created_at) VALUES (?, ?, 'PENDING', ?)",
                (campaign_id, goal_text, now)
            )
            
            # Insert Milestones
            if milestones_data:
                for m in milestones_data:
                    g_m_id = milestone_map[m["id"]]
                    conn.execute("""
                        INSERT INTO campaign_milestones (id, campaign_id, title, description, status, created_at)
                        VALUES (?, ?, ?, ?, 'PENDING', ?)
                    """, (g_m_id, campaign_id, m["title"], m.get("description", ""), now))
            
            # Insert Tasks
            for t in tasks_data:
                g_id = id_map[t["id"]]
                priority = t.get("priority", 5)
                if isinstance(priority, str):
                    p_map = {"HIGH": 8, "MEDIUM": 5, "LOW": 2}
                    priority = p_map.get(priority.upper(), 5)
                timeout = t.get("timeout_seconds", 120)
                max_retries = t.get("max_retries", 2)
                agent = t["agent_name"].lower() if "agent_name" in t else t.get("agent_target", "browseragent").lower()
                
                local_m_id = t.get("milestone_id")
                g_m_id = milestone_map.get(local_m_id) if local_m_id else None
                
                conn.execute("""
                    INSERT INTO agent_tasks 
                    (id, campaign_id, agent_name, task_description, target, priority, status, timeout_seconds, max_retries, created_at, milestone_id)
                    VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)
                """, (g_id, campaign_id, agent, t.get("task_description") or t.get("description", "Run task"), t.get("target", ""), priority, timeout, max_retries, now, g_m_id))
                
            # Insert Dependencies
            for t in tasks_data:
                g_id = id_map[t["id"]]
                for dep in t.get("depends_on", []):
                    if dep in id_map:
                        conn.execute(
                            "INSERT INTO task_dependencies (task_id, depends_on_task_id) VALUES (?, ?)",
                            (g_id, id_map[dep])
                        )
            conn.commit()
            
        update_campaign_progress(campaign_id)
        print(f"[Orchestrator] Submitted campaign {campaign_id} with {len(tasks_data)} tasks.")
        return campaign_id

    def add_campaign_artifact(self, campaign_id: str, artifact_type: str, content: str):
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO campaign_artifacts (campaign_id, artifact_type, content) VALUES (?, ?, ?)",
                (campaign_id, artifact_type, content)
            )
            conn.commit()
        print(f"[Orchestrator] Recorded artifact for campaign {campaign_id}: {artifact_type}")

    def get_campaign_status(self, campaign_id: str) -> Dict[str, Any]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, progress FROM campaigns WHERE id = ?", (campaign_id,))
            row = cursor.fetchone()
            if row:
                return {"status": row[0], "progress": row[1]}
        return {"status": "UNKNOWN", "progress": 0.0}

    # ── P9.1: Campaign Lifecycle Management APIs ────────────────────────────
    def pause_campaign(self, campaign_id: str) -> bool:
        """Suspends active task scheduling and sets running tasks to INTERRUPTED."""
        print(f"[Orchestrator] Pausing campaign: {campaign_id}")
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM campaigns WHERE id = ?", (campaign_id,))
            if not cursor.fetchone():
                return False
            conn.execute("UPDATE campaigns SET status = 'PAUSED' WHERE id = ?", (campaign_id,))
            conn.execute("UPDATE agent_tasks SET status = 'INTERRUPTED' WHERE campaign_id = ? AND status = 'RUNNING'", (campaign_id,))
            conn.commit()
        return True

    def resume_campaign(self, campaign_id: str) -> bool:
        """Resumes paused campaign and restarts task scheduler loop if stopped."""
        print(f"[Orchestrator] Resuming campaign: {campaign_id}")
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM campaigns WHERE id = ?", (campaign_id,))
            if not cursor.fetchone():
                return False
            conn.execute("UPDATE campaigns SET status = 'RUNNING' WHERE id = ?", (campaign_id,))
            conn.execute("UPDATE agent_tasks SET status = 'PENDING' WHERE campaign_id = ? AND status = 'INTERRUPTED'", (campaign_id,))
            conn.commit()

        # Restart scheduler thread if stopped
        if self.scheduler is None or not self.scheduler.is_alive():
            print("[Orchestrator] Task scheduler was stopped. Spawning a new thread.")
            self.scheduler = AriaTaskScheduler(self.active_workers)
            self.scheduler.start()

        return True

    def cancel_campaign(self, campaign_id: str) -> bool:
        """Cancels campaign and sets all uncompleted tasks to CANCELLED."""
        print(f"[Orchestrator] Cancelling campaign: {campaign_id}")
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM campaigns WHERE id = ?", (campaign_id,))
            if not cursor.fetchone():
                return False
            conn.execute("UPDATE campaigns SET status = 'CANCELLED' WHERE id = ?", (campaign_id,))
            conn.execute("UPDATE agent_tasks SET status = 'CANCELLED' WHERE campaign_id = ? AND status IN ('PENDING', 'RUNNING')", (campaign_id,))
            conn.commit()
        return True

    # ── P9.2: Milestone Progress Calculation ────────────────────────────────
    def get_milestone_progress(self, milestone_id: str) -> float:
        """Calculates milestone completion percentage based on child tasks."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*), SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END)
                FROM agent_tasks WHERE milestone_id = ?
            """, (milestone_id,))
            total, completed = cursor.fetchone()
        if not total:
            return 0.0
        return round((completed / total) * 100.0, 1)

    # ── P9.3: Dependency-Aware Dynamic Task Injection ────────────────────────
    def inject_task(self, campaign_id: str, task_data: Dict[str, Any], dependency_ids: List[str] = None) -> str:
        """Injects a new task into a campaign, validating that dependency IDs exist."""
        now = int(time.time())
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # 1. Verify campaign exists and is active
            cursor.execute("SELECT status FROM campaigns WHERE id = ?", (campaign_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Campaign {campaign_id} does not exist.")
            campaign_status = row[0]
            if campaign_status in ("PAUSED", "CANCELLED", "FAILED", "COMPLETED"):
                print(f"[Orchestrator] Rejected task injection: Campaign is {campaign_status}")
                return f"REJECTED_CAMPAIGN_{campaign_status}"

            # 2. Validate every dependency ID exists in agent_tasks
            if dependency_ids:
                for dep in dependency_ids:
                    # Translate local dep to global task id if it isn't already
                    g_dep_id = dep
                    if not dep.startswith("TSK_"):
                        g_dep_id = f"TSK_{campaign_id}_{dep.upper()}"
                    
                    cursor.execute("SELECT id FROM agent_tasks WHERE id = ?", (g_dep_id,))
                    if not cursor.fetchone():
                        raise ValueError(f"Dependency task {g_dep_id} does not exist.")

            # 3. Formulate global task ID
            local_id = task_data.get("id") or f"inject_{int(time.time() * 1000) % 100000}"
            g_id = f"TSK_{campaign_id}_{local_id.upper()}"
            
            priority = task_data.get("priority", 5)
            if isinstance(priority, str):
                p_map = {"HIGH": 8, "MEDIUM": 5, "LOW": 2}
                priority = p_map.get(priority.upper(), 5)
                
            timeout = task_data.get("timeout_seconds", 120)
            max_retries = task_data.get("max_retries", 2)
            agent = (task_data.get("agent_name") or task_data.get("agent_target") or "browseragent").lower()
            desc = task_data.get("task_description") or task_data.get("description", "Injected task")
            target = task_data.get("target", "")
            m_id = task_data.get("milestone_id")

            # 4. Insert task
            conn.execute("""
                INSERT INTO agent_tasks 
                (id, campaign_id, agent_name, task_description, target, priority, status, timeout_seconds, max_retries, created_at, milestone_id)
                VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)
            """, (g_id, campaign_id, agent, desc, target, priority, timeout, max_retries, now, m_id))

            # 5. Insert dependencies
            if dependency_ids:
                for dep in dependency_ids:
                    g_dep_id = dep
                    if not dep.startswith("TSK_"):
                        g_dep_id = f"TSK_{campaign_id}_{dep.upper()}"
                    conn.execute(
                        "INSERT INTO task_dependencies (task_id, depends_on_task_id) VALUES (?, ?)",
                        (g_id, g_dep_id)
                    )
            conn.commit()

        # Update progress tracking
        update_campaign_progress(campaign_id)
        print(f"[Orchestrator] Dynamic task {g_id} injected into campaign {campaign_id}.")
        return g_id

    # ── P9.4: Decoupled Feedback Loop (Priority Adjustment) ─────────────────
    def handle_coach_adjustment(self, envelope: Dict[str, Any]):
        data = envelope.get("data", {})
        campaign_id = data.get("campaign_id")
        action = data.get("action")
        if campaign_id and action == "increase_priority":
            self.boost_campaign_priority(campaign_id)

    def boost_campaign_priority(self, campaign_id: str):
        """Increments priority for all pending tasks in the campaign by 2."""
        print(f"[Orchestrator] Boosting pending tasks priority for campaign {campaign_id}")
        with get_db_connection() as conn:
            conn.execute("""
                UPDATE agent_tasks 
                SET priority = CAST(priority AS INTEGER) + 2 
                WHERE campaign_id = ? AND status = 'PENDING'
            """, (campaign_id,))
            conn.commit()

    # ── P9.5: Blackboard Event Bridge Coordinator ───────────────────────────
    def _on_blackboard_change(self, envelope: Dict[str, Any]):
        data = envelope.get("data", {})
        topic = data.get("topic")
        key = data.get("key")
        value = data.get("value")

        if topic == "coach" and key == "campaign_adjustment":
            if isinstance(value, dict):
                campaign_id = value.get("campaign_id")
                action = value.get("action")
                if campaign_id and action == "increase_priority":
                    self.boost_campaign_priority(campaign_id)
        elif topic == "research" and key == "task_injection":
            if isinstance(value, dict):
                campaign_id = value.get("campaign_id")
                milestone_id = value.get("milestone_id")
                task_data = value.get("task_data")
                deps = value.get("dependencies", [])
                if campaign_id and task_data:
                    if milestone_id and "milestone_id" not in task_data:
                        task_data["milestone_id"] = milestone_id
                    try:
                        self.inject_task(campaign_id, task_data, dependency_ids=deps)
                    except Exception as e:
                        print(f"[Orchestrator] Decoupled blackboard injection failed: {e}")
