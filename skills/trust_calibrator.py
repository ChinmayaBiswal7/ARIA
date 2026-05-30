import sqlite3
import threading

class SkillTrustCalibrator:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SkillTrustCalibrator, cls).__new__(cls)
                cls._instance.db_path = "aria_memory.db"
                cls._instance._init_db()
            return cls._instance

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS skill_trust (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_name TEXT UNIQUE NOT NULL,
                    success_runs INTEGER DEFAULT 0,
                    failed_runs INTEGER DEFAULT 0,
                    trust_score REAL DEFAULT 1.0
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contextual_skill_trust (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_name TEXT NOT NULL,
                    context_app TEXT NOT NULL,
                    success_runs INTEGER DEFAULT 0,
                    failed_runs INTEGER DEFAULT 0,
                    trust_score REAL DEFAULT 1.0,
                    UNIQUE(skill_name, context_app)
                )
            """)
            conn.commit()

    def record_skill_run(self, skill_name, success=True, context_app="unknown"):
        skill_name = skill_name.strip().lower()
        context_app = context_app.strip().lower()
        if not skill_name:
            return
            
        with self._lock:
            # 1. Update Global Skill Trust
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT success_runs, failed_runs, trust_score FROM skill_trust WHERE skill_name = ?", (skill_name,))
                    row = cursor.fetchone()
                    if row:
                        success_runs, failed_runs, trust_score = row
                        if success:
                            success_runs += 1
                            trust_score = min(trust_score + 0.08, 2.0)
                        else:
                            failed_runs += 1
                            trust_score = max(trust_score - 0.20, 0.1)
                        cursor.execute(
                            "UPDATE skill_trust SET success_runs = ?, failed_runs = ?, trust_score = ? WHERE skill_name = ?",
                            (success_runs, failed_runs, trust_score, skill_name)
                        )
                    else:
                        success_runs = 1 if success else 0
                        failed_runs = 0 if success else 1
                        trust_score = 1.08 if success else 0.80
                        cursor.execute(
                            "INSERT INTO skill_trust (skill_name, success_runs, failed_runs, trust_score) VALUES (?, ?, ?, ?)",
                            (skill_name, success_runs, failed_runs, trust_score)
                        )
                    
                    # 2. Update Contextual/App-Specific Skill Trust
                    cursor.execute(
                        "SELECT success_runs, failed_runs, trust_score FROM contextual_skill_trust WHERE skill_name = ? AND context_app = ?",
                        (skill_name, context_app)
                    )
                    row_ctx = cursor.fetchone()
                    if row_ctx:
                        s_runs, f_runs, t_score = row_ctx
                        if success:
                            s_runs += 1
                            t_score = min(t_score + 0.12, 2.0) # Condition-specific boosts faster
                        else:
                            f_runs += 1
                            t_score = max(t_score - 0.25, 0.1)
                        cursor.execute(
                            "UPDATE contextual_skill_trust SET success_runs = ?, failed_runs = ?, trust_score = ? WHERE skill_name = ? AND context_app = ?",
                            (s_runs, f_runs, t_score, skill_name, context_app)
                        )
                    else:
                        s_runs = 1 if success else 0
                        f_runs = 0 if success else 1
                        t_score = 1.12 if success else 0.75
                        cursor.execute(
                            "INSERT INTO contextual_skill_trust (skill_name, context_app, success_runs, failed_runs, trust_score) VALUES (?, ?, ?, ?, ?)",
                            (skill_name, context_app, s_runs, f_runs, t_score)
                        )
                    conn.commit()
            except Exception as e:
                print(f"[SkillTrust] Error recording skill run: {e}")

    def get_skill_trust_context(self, context_app='unknown'):
        try:
            context_app = context_app.strip().lower()
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Fetch app-specific contextual trust ratings
                cursor.execute(
                    "SELECT skill_name, trust_score FROM contextual_skill_trust WHERE context_app = ? ORDER BY trust_score DESC",
                    (context_app,)
                )
                ctx_rows = cursor.fetchall()
                
                # Fetch global ratings
                cursor.execute("SELECT skill_name, success_runs, failed_runs, trust_score FROM skill_trust ORDER BY trust_score DESC")
                rows = cursor.fetchall()
                
            if not rows:
                return ""
                
            parts = []
            if ctx_rows:
                parts.append("== APP-SPECIFIC CONTEXT TRUST ==")
                for name, score in ctx_rows:
                    rel = "RELIABLE" if score >= 0.90 else ("MEDIOCRE" if score >= 0.60 else "UNSTABLE")
                    parts.append(f"- Skill '{name}' in app '{context_app}': Trust {score:.2f} [{rel}]")
                parts.append("")
                
            parts.append("== GLOBAL SKILL TRUST ==")
            for name, succ, fail, score in rows:
                reliability = "RELIABLE"
                if score < 0.60:
                    reliability = "UNSTABLE"
                elif score < 0.90:
                    reliability = "MEDIOCRE"
                parts.append(f"- Skill '{name}': Trust Rating {score:.2f} [{reliability}] (runs: {succ + fail})")
                
            return "\n".join(parts)
        except Exception as e:
            print(f"[SkillTrust] Context load error: {e}")
            return ""
