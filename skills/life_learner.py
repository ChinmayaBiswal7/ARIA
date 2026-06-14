import os
import re
import time
import threading
import subprocess
from pathlib import Path
from datetime import datetime

class LifeLearner:
    """
    Autonomous background learner.
    Scans git repos, active window monitors, and conversation logs
    and populates the KnowledgeGraph automatically.
    """

    SCAN_INTERVAL = 3600  # rescan every hour

    # Language detection by extension
    LANG_MAP = {
        '.py': 'Python',
        '.kt': 'Kotlin',
        '.java': 'Java',
        '.js': 'JavaScript',
        '.ts': 'TypeScript',
        '.cpp': 'C++',
        '.c': 'C',
        '.html': 'HTML',
        '.css': 'CSS',
        '.dart': 'Dart',
        '.go': 'Go',
        '.rs': 'Rust',
        '.swift': 'Swift',
    }

    # ML/AI keywords for relevance scoring
    ML_KEYWORDS = [
        'neural', 'model', 'train', 'dataset',
        'tensorflow', 'pytorch', 'sklearn', 'nlp',
        'vision', 'embedding', 'inference', 'llm',
        'transformer', 'bert', 'gpt', 'yolo',
        'classification', 'regression', 'clustering'
    ]

    def __init__(self, knowledge_graph, aria=None, projects_dir=None):
        self.kg = knowledge_graph
        self.aria = aria
        self._stop = threading.Event()
        self._thread = None
        self.last_scan_time = 0

        # Dynamic project directory resolution
        if projects_dir:
            self.projects_dir = projects_dir
        elif aria and hasattr(aria, 'projects_dir') and aria.projects_dir:
            self.projects_dir = aria.projects_dir
        else:
            try:
                # Try to resolve relative to AI workspace root (parent of C:\D FOLDER\Projects\AI is C:\D FOLDER\Projects)
                self.projects_dir = str(Path(__file__).resolve().parent.parent.parent)
            except Exception:
                self.projects_dir = r"C:\D FOLDER\Projects"
        
        print(f"[LifeLearner] Initialized with projects directory: {self.projects_dir}")

    def start(self):
        self._thread = threading.Thread(
            target=self._learn_loop,
            name="ARIA-LifeLearner",
            daemon=True
        )
        self._thread.start()
        print("[LifeLearner] Background learning thread started.")

    def stop(self):
        self._stop.set()

    def _learn_loop(self):
        # Initial scan after 30s startup delay
        time.sleep(30)
        while not self._stop.is_set():
            try:
                self._scan_all()
                self.last_scan_time = time.time()
            except Exception as e:
                print(f"[LifeLearner] Scan cycle error: {repr(e)}")
            # Wait for next scan interval
            self._stop.wait(self.SCAN_INTERVAL)

    def _scan_all(self):
        if self.aria:
            is_voice_active = False
            if getattr(self.aria, 'voice', None):
                if self.aria.voice.is_speaking or getattr(self.aria.voice, "vad_detecting_speech", False) or getattr(self.aria.voice, "recording_active", False):
                    is_voice_active = True
            if hasattr(self.aria, 'conversation_session') and self.aria.conversation_session.is_active():
                is_voice_active = True
                
            if is_voice_active:
                print("[LifeLearner] Skipping scanning pass because voice/conversation session is active.")
                return

        print("[LifeLearner] Starting autonomous scanning pass...")
        self._scan_git_repos()
        self._scan_window_patterns()
        self._scan_conversation_patterns()
        print("[LifeLearner] Scanning pass finished.")


    # ── Git Repo Scanner ─────────────────────────────

    def _scan_git_repos(self):
        base = Path(self.projects_dir)
        if not base.exists() or not base.is_dir():
            print(f"[LifeLearner] Projects directory {self.projects_dir} does not exist or is not a folder.")
            return

        for project_dir in base.iterdir():
            if not project_dir.is_dir():
                continue
            git_dir = project_dir / ".git"
            if not git_dir.exists():
                continue

            try:
                self._process_repo(project_dir)
            except Exception as e:
                print(f"[LifeLearner] Failed to scan repo '{project_dir.name}': {repr(e)}")

    def _process_repo(self, repo_path):
        name = repo_path.name
        
        langs = set()
        file_count = 0
        ml_score = 0
        
        # Scan files for language matching and ML keyword checks
        for f in repo_path.rglob("*"):
            # Avoid traversing venv or output/build directories to conserve performance
            if any(x in f.parts for x in ["aria_env", ".git", "__pycache__", "build", "node_modules"]):
                continue
            if f.is_file() and f.suffix in self.LANG_MAP:
                langs.add(self.LANG_MAP[f.suffix])
                file_count += 1
                
                if any(kw in f.name.lower() for kw in self.ML_KEYWORDS):
                    ml_score += 1

        # Read README for description
        description = ""
        readme_files = ['README.md', 'readme.md', 'README.txt']
        for readme_name in readme_files:
            readme = repo_path / readme_name
            if readme.exists():
                try:
                    content = readme.read_text(encoding='utf-8', errors='ignore')
                    description = content[:500]
                    ml_score += sum(1 for kw in self.ML_KEYWORDS if kw in content.lower())
                    break
                except Exception:
                    pass

        # Get last commit relative time
        last_commit = self._get_last_commit(repo_path)

        tags = list(langs)
        if ml_score > 2:
            tags.append("machine_learning")

        # Save to Knowledge Graph (git scan has priority 70 -> status='unconfirmed')
        self.kg.add_node(
            name=name,
            node_type="project",
            properties={
                "description": description[:200].strip(),
                "languages": list(langs),
                "file_count": file_count,
                "ml_score": ml_score,
                "last_commit": last_commit,
                "tags": tags,
                "path": str(repo_path)
            },
            confidence=0.9,
            source="git_scan",
            status="unconfirmed"
        )

        # Link skills to projects
        for lang in langs:
            self.kg.add_node(
                name=lang,
                node_type="skill",
                properties={"type": "language"},
                confidence=0.85,
                source="git_scan",
                status="unconfirmed"
            )
            self.kg.add_edge(
                from_name=name,
                from_type="project",
                to_name=lang,
                to_type="skill",
                relation="uses",
                source="git_scan",
                status="unconfirmed"
            )

        print(f"[LifeLearner] Scanned project repo: '{name}' (Languages: {', '.join(langs)})")

    def _get_last_commit(self, repo_path):
        try:
            # Run simple git command to retrieve last commit date relatively
            result = subprocess.run(
                ['git', 'log', '-1', '--format=%cr', '--', '.'],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.stdout.strip()
        except Exception:
            return "unknown"

    # ── Window Activity Scanner ──────────────────────

    def _scan_window_patterns(self):
        """Learn tools and usage contexts from active desktop windows."""
        if not self.aria or not hasattr(self.aria, 'context_skill'):
            return
        
        try:
            title = self.aria.context_skill.get_active_window()
            if not title or title == "Desktop":
                return
            title_lower = title.lower()

            # Detect coding tools
            if any(w in title_lower for w in ['visual studio code', 'vs code', 'pycharm', 'eclipse', 'intellij']):
                self.kg.add_node(
                    name="VS Code",
                    node_type="tool",
                    confidence=0.8,
                    source="window_monitor",
                    status="unconfirmed"
                )
                self.kg.add_fact(
                    subject="chinmaya",
                    predicate="currently_using",
                    obj="VS Code",
                    confidence=0.7,
                    source="window_monitor",
                    status="unconfirmed"
                )

            # Detect browser research topics
            elif any(w in title_lower for w in ['chrome', 'firefox', 'edge', 'safari']):
                if ' - ' in title:
                    topic = title.split(' - ')[0][:50].strip()
                    # Skip generic tabs
                    if len(topic) > 3 and not any(w in topic.lower() for w in ['new tab', 'home', 'google search']):
                        self.kg.add_fact(
                            subject="chinmaya",
                            predicate="researching",
                            obj=topic,
                            confidence=0.5,
                            source="window_monitor",
                            status="unconfirmed"
                        )

            # Detect gaming patterns
            gaming_keywords = ['valorant', 'minecraft', 'steam', 'epic games', 'cyberpunk', 'gta']
            for game in gaming_keywords:
                if game in title_lower:
                    self.kg.add_fact(
                        subject="chinmaya",
                        predicate="plays",
                        obj=game.title(),
                        confidence=0.8,
                        source="window_monitor",
                        status="unconfirmed"
                    )

        except Exception as e:
            print(f"[LifeLearner] Window monitor learning error: {repr(e)}")

    # ── Conversation Pattern Scanner ─────────────────

    def _scan_conversation_patterns(self):
        """Parse episodic memory logs to extract facts asynchronously."""
        if not self.aria or not hasattr(self.aria, 'episodic_memory'):
            return

        try:
            em = self.aria.episodic_memory
            # Retrieve 50 recent episodes from memory DB
            recent = em.get_recent(username="chinmaya", n=50)
            
            for episode in recent:
                text = episode.get('event_text', '').lower()
                self._extract_facts_from_text(text)
        except Exception as e:
            print(f"[LifeLearner] Conversational logs scanning error: {repr(e)}")

    def _extract_facts_from_text(self, text):
        """Helper to matching pattern entities inside text."""
        # 1. Matches job/internship applications
        app_patterns = [
            r"applied (?:to|for) ([a-z\s]+)",
            r"interview (?:at|with) ([a-z\s]+)",
            r"got (?:call|response) from ([a-z\s]+)"
        ]
        for pattern in app_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                company = match.strip()[:50]
                if len(company) > 2:
                    self.kg.add_node(company.title(), "application", confidence=0.75, source="conversation", status="unconfirmed")
                    self.kg.add_fact("chinmaya", "applied_to", company.title(), confidence=0.75, source="conversation", status="unconfirmed")

        # 2. Matches skills mentioned
        skill_patterns = [
            r"learning ([a-z\+\#]+)",
            r"studying ([a-z\s]+)",
            r"working on ([a-z\s]+)",
            r"know ([a-z\+\#]+) well",
        ]
        for pattern in skill_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                skill = match.strip()[:30]
                if len(skill) > 2:
                    self.kg.add_node(skill.title(), "skill", confidence=0.6, source="conversation", status="unconfirmed")

        # 3. Matches subjects
        subject_patterns = [
            r"(?:dbms|database management)",
            r"(?:os|operating system)",
            r"(?:cn|computer network)",
            r"(?:algorithms|dsa|data structures)",
            r"(?:machine learning|ml)",
            r"(?:artificial intelligence|ai)",
            r"(?:compiler design)",
            r"(?:software engineering)"
        ]
        for pattern in subject_patterns:
            if re.search(pattern, text):
                subject = pattern.replace(r'(?:', '').replace(')', '')
                subject = subject.split('|')[0].strip()
                self.kg.add_node(subject.upper(), "subject", confidence=0.7, source="conversation", status="unconfirmed")

    # ── Manual Learning from Voice ───────────────────

    def learn_from_voice(self, text):
        """
        Parses explicit declarations from user speech.
        Triggers instantly and saves with status='confirmed' and high priority.
        """
        text_lower = text.lower()
        learned = []

        # 1. Application Check
        app_match = re.search(r"(?:applying|applied|interview) (?:to|at|with|for) ([a-z\s]+)", text_lower)
        if app_match:
            company = app_match.group(1).strip().title()
            self.kg.add_node(company, "application", confidence=1.0, source="voice", status="confirmed")
            self.kg.add_fact("chinmaya", "applied_to", company, confidence=1.0, source="voice", status="confirmed")
            learned.append(f"application at {company}")

        # 2. Skill Check
        skill_match = re.search(r"(?:i know|i use|i learn|i'm learning|working with) ([a-z\+\#\s]+)", text_lower)
        if skill_match:
            skill = skill_match.group(1).strip().title()
            # Exclude long descriptions or false positives
            if len(skill) <= 30:
                self.kg.add_node(skill, "skill", confidence=1.0, source="voice", status="confirmed")
                learned.append(f"skill: {skill}")

        # 3. Goal Check
        goal_match = re.search(r"(?:my goal|i want to|i'm trying to|i plan to) ([a-z\s]+)", text_lower)
        if goal_match:
            goal = goal_match.group(1).strip()[:60]
            self.kg.add_node(goal.title(), "goal", confidence=1.0, source="voice", status="confirmed")
            self.kg.add_fact("chinmaya", "goal_is", goal.title(), confidence=1.0, source="voice", status="confirmed")
            learned.append(f"goal: {goal}")

        # 4. Exam Check
        exam_match = re.search(r"([a-z\s]+) exam", text_lower)
        if exam_match:
            subject = exam_match.group(1).strip().upper()
            if len(subject) <= 25:
                self.kg.add_node(subject, "subject", confidence=1.0, source="voice", status="confirmed")
                learned.append(f"subject: {subject}")

        if learned:
            print(f"[LifeLearner] Explicitly learned from voice: {', '.join(learned)}")
        return learned
