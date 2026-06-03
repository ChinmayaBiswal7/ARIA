"""
skills/git_monitor.py — Phase 4B: Automatic Git Commit Timeline Logger
=======================================================================
Watches the ARIA repository for new git commits and automatically logs
each commit as a timeline event in the project_timeline table.

Usage:
    # Run once (usually called from brain startup or a scheduled thread)
    from skills.git_monitor import GitMonitor
    GitMonitor().sync_commits_to_timeline()

    # Or run as a background watcher
    GitMonitor().start_background_watcher(interval_seconds=120)
"""

import os
import subprocess
import json
import time
import threading
import sqlite3

REPO_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAST_COMMIT_FILE = os.path.join(REPO_PATH, "scratch", "last_synced_commit.txt")
DB_PATH = os.path.join(REPO_PATH, "aria_memory.db")

# Maps git commit message keywords → project names in aria_projects.json
COMMIT_PROJECT_MAP = {
    "android": "ARIA_Android_App",
    "kotlin": "ARIA_Android_App",
    "health bridge": "ARIA_Android_App",
    "face": "ARIA_Android_App",
    "stt": "ARIA_Android_App",
    "speech recognizer": "ARIA_Android_App",
    "brain": "ARIA_Core",
    "voice": "ARIA_Core",
    "memory": "ARIA_Core",
    "graph": "ARIA_Core",
    "knowledge": "ARIA_Core",
    "dashboard": "ARIA_Dashboard",
    "firebase": "ARIA_Dashboard",
    "timeline": "ARIA_Core",
    "priority": "ARIA_Core",
    "briefing": "ARIA_Core",
}

# Default project to assign commits that don't match any keyword
DEFAULT_PROJECT = "ARIA_Core"


def _infer_project_from_message(message: str) -> str:
    msg_lower = message.lower()
    for keyword, project in COMMIT_PROJECT_MAP.items():
        if keyword in msg_lower:
            return project
    return DEFAULT_PROJECT


def _infer_importance_from_message(message: str) -> int:
    """Returns 1-10 importance score based on commit message keywords."""
    msg_lower = message.lower()
    if any(kw in msg_lower for kw in ["fix", "bug", "crash", "error", "broken"]):
        return 7
    if any(kw in msg_lower for kw in ["feat", "add", "implement", "new", "build", "create"]):
        return 8
    if any(kw in msg_lower for kw in ["refactor", "cleanup", "improve", "optimize"]):
        return 6
    if any(kw in msg_lower for kw in ["test", "verify", "check"]):
        return 5
    if any(kw in msg_lower for kw in ["wip", "draft", "temp"]):
        return 3
    return 5


def _get_commits_since(since_hash: str = None, max_commits: int = 20) -> list:
    """Returns list of (hash, timestamp_unix, author, message) tuples for recent commits."""
    try:
        if since_hash:
            git_cmd = ["git", "log", f"{since_hash}..HEAD", "--format=%H|%at|%an|%s", f"--max-count={max_commits}"]
        else:
            git_cmd = ["git", "log", "--format=%H|%at|%an|%s", f"--max-count={max_commits}"]
        
        result = subprocess.run(
            git_cmd,
            cwd=REPO_PATH,
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode != 0:
            print(f"[GitMonitor] git log failed: {result.stderr.strip()}")
            return []
        
        commits = []
        for line in result.stdout.strip().split("\n"):
            if "|" not in line:
                continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                commit_hash, ts_str, author, message = parts
                try:
                    commits.append((commit_hash.strip(), int(ts_str.strip()), author.strip(), message.strip()))
                except ValueError:
                    continue
        return commits
    except subprocess.TimeoutExpired:
        print("[GitMonitor] git log timed out.")
        return []
    except FileNotFoundError:
        print("[GitMonitor] git not found in PATH. Skipping commit sync.")
        return []
    except Exception as e:
        print(f"[GitMonitor] Unexpected error getting commits: {e}")
        return []


def _load_last_synced_hash() -> str:
    """Reads the last processed commit hash from disk."""
    if os.path.exists(LAST_COMMIT_FILE):
        with open(LAST_COMMIT_FILE, "r") as f:
            return f.read().strip()
    return None


def _save_last_synced_hash(commit_hash: str):
    """Persists the last processed commit hash to disk."""
    os.makedirs(os.path.dirname(LAST_COMMIT_FILE), exist_ok=True)
    with open(LAST_COMMIT_FILE, "w") as f:
        f.write(commit_hash)


def _log_commit_to_timeline(commit_hash, timestamp_unix, author, message):
    """Directly inserts a commit event into the project_timeline table."""
    project = _infer_project_from_message(message)
    importance = _infer_importance_from_message(message)
    metadata = json.dumps({"commit_hash": commit_hash[:8], "author": author})
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # Check for duplicate (same commit hash already logged)
        cursor.execute(
            "SELECT id FROM project_timeline WHERE metadata LIKE ?",
            (f'%{commit_hash[:8]}%',)
        )
        if cursor.fetchone():
            conn.close()
            return False  # Already logged
        
        cursor.execute("""
            INSERT INTO project_timeline (project_name, timestamp, event_type, description, source, importance, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (project, timestamp_unix, "git_commit", message, f"Git/{author}", importance, metadata))
        conn.commit()
        conn.close()
        print(f"[GitMonitor] Logged commit [{commit_hash[:8]}] to {project}: '{message[:60]}'")
        return True
    except Exception as e:
        print(f"[GitMonitor] DB error logging commit: {e}")
        return False


class GitMonitor:
    """Syncs git commits to the ARIA project timeline database."""

    def sync_commits_to_timeline(self) -> int:
        """
        Fetches all new commits since the last sync and logs them.
        Returns the number of new commits logged.
        """
        last_hash = _load_last_synced_hash()
        commits = _get_commits_since(since_hash=last_hash, max_commits=50)
        
        if not commits:
            print("[GitMonitor] No new commits to sync.")
            return 0
        
        logged = 0
        for commit_hash, ts, author, message in commits:
            if _log_commit_to_timeline(commit_hash, ts, author, message):
                logged += 1
        
        # Save the most recent commit hash (commits are returned newest-first)
        if commits:
            _save_last_synced_hash(commits[0][0])
        
        print(f"[GitMonitor] Sync complete. {logged} new commit(s) logged.")
        return logged

    def get_recent_commits_summary(self, n: int = 5) -> str:
        """Returns a human-readable string of the n most recent commits."""
        commits = _get_commits_since(max_commits=n)
        if not commits:
            return "No recent commits found."
        
        lines = [f"Last {len(commits)} git commits:"]
        for commit_hash, ts, author, message in commits:
            dt = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
            lines.append(f"  [{commit_hash[:7]}] {dt} by {author}: {message}")
        return "\n".join(lines)

    def start_background_watcher(self, interval_seconds: int = 300):
        """Starts a daemon thread that polls for new commits every interval_seconds."""
        def _watch():
            print(f"[GitMonitor] Background watcher started (interval: {interval_seconds}s)")
            while True:
                try:
                    self.sync_commits_to_timeline()
                except Exception as e:
                    print(f"[GitMonitor] Watcher error: {e}")
                time.sleep(interval_seconds)
        
        thread = threading.Thread(target=_watch, daemon=True, name="GitMonitorWatcher")
        thread.start()
        return thread
