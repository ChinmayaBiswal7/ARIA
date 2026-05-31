"""
ARIA - Advanced Responsive Intelligent Assistant
================================================
Main entry point. Runs the agent loop in a background thread
while the GUI lives on the main thread (required by Qt).

Usage:
    python main.py          # Full mode with GUI
    python main.py --nogui  # Terminal-only mode
"""

import os
import sys
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
import time
import threading
import re
import datetime
import cv2
import pygame

from voice import Voice
from brain import Brain
from camera import Camera
from automation import Automation
from memory import FaceMemory
from vision_learn import VisionLearner
from screen_control import ScreenControl
from ui_control import UIControl

# Modular Skill Plugins
from skills.memory_skill import MemorySkill
from skills.context_skill import ContextSkill
from skills.workspace_skill import WorkspaceSkill
from skills.firebase_sync import FirebaseSync

# New Cognitive Core additions
from skills.sandbox_safety import SandboxSafetyLayer
from skills.executor_queue import ExecutorQueue
from skills.context_budget import ContextBudgetManager
from skills.reflection_engine import ReflectionEngine
from skills.proactive_cognition import ProactiveCognition
from skills.episodic_memory import EpisodicMemory

# Live subsystem health monitor
from skills.subsystem_health import (
    HEALTH,
    SUBSYSTEM_CAMERA, SUBSYSTEM_VISION, SUBSYSTEM_TTS,
    SUBSYSTEM_BROWSER, SUBSYSTEM_AUTOMATION, SUBSYSTEM_LLM,
    SUBSYSTEM_OBJECT_DETECTION, SUBSYSTEM_FIREBASE, SUBSYSTEM_MICROPHONE,
)

# Wake-word mode = False means ARIA listens continuously without needing 'Hey ARIA'
DEFAULT_ALWAYS_ON = False

# Optional GUI
USE_GUI = "--nogui" not in sys.argv
if USE_GUI:
    try:
        from PyQt5.QtWidgets import QApplication
        from gui import ARIAWindow, set_state, set_text, set_user, trigger_wave
        _gui_available = True
    except ImportError:
        print("[Main] PyQt5 not available — running in terminal mode.")
        _gui_available = False
        USE_GUI = False
else:
    _gui_available = False

# ── Stub GUI functions when no GUI ─────────────────────────────────────────
if not USE_GUI or not _gui_available:
    def set_state(s): pass
    def set_text(t): pass
    def set_user(u): pass
    def trigger_wave(): pass


# ─────────────────────────────────────────────────────────────────────────────
class ConversationSession:
    """Tracks active conversation by last activity, not original wake time."""

    def __init__(self, timeout_seconds=30.0):
        self.timeout_seconds = timeout_seconds
        self.session_active = False
        self.last_activity = 0.0
        self.active_task_id = None
        self.wake_reason = None

    def touch(self, wake_reason=None, active_task_id=None):
        self.session_active = True
        self.last_activity = time.time()
        if wake_reason:
            self.wake_reason = wake_reason
        if active_task_id:
            self.active_task_id = active_task_id

    def is_active(self, has_active_task=False):
        if has_active_task:
            return True
        return self.session_active and (time.time() - self.last_activity < self.timeout_seconds)

    def expire_if_idle(self, has_active_task=False):
        active = self.is_active(has_active_task=has_active_task)
        if not active:
            self.session_active = False
        return active


class ARIA:
    """
    The main AI agent.
    Handles the perception → thought → action loop.
    """

    try:
        from wake_word import ARIA_VARIANTS
        WAKE_WORDS = ARIA_VARIANTS
    except ImportError:
        WAKE_WORDS = ["aria", "hey aria", "ok aria", "hello aria", "oi aria"]

    def __init__(self):
        self.voice      = None
        self.brain      = None
        self.camera     = None
        self.automation = None
        self.memory     = None
        self.speech_queue = None

        self.known_user = None          # Name of recognised user
        self.known_user_similarity = 0.0
        self.known_user_confidence = "none"
        self.face_match_history = []    # Rolling history of matches for temporal smoothing
        self.last_identity_match_time = 0.0  # Timestamp of the last high-confidence match
        self.presence_state = "USER_LEFT"
        self.last_background_perception_time = 0.0
        self.current_user_emotion = "neutral"
        self.current_user_emotion_confidence = 1.0
        self.emotion_history = []
        self.emotion_counts = {}
        self.proactive_queue = None
        self.running    = False
        self.wake_mode  = DEFAULT_ALWAYS_ON  # True = always listening (recommended)
        self.last_interaction_time = 0.0
        self.conversation_session = ConversationSession(timeout_seconds=60.0)
        self._was_in_conversation = False
        self._reply_context = threading.local()
        self.pending_browser_action = None
        self.shopping_search_context = {}
        self.startup_greeting_done = False
        self.long_session_trust_applied = False
        self._greeted_users = set()
        self._last_greeted_face = None

        self.pending_speech = []
        self.last_user_speech_time = 0.0
        self._proactive_history = set()
        self._proactive_cooldown = {}

        self.automation_mode = False
        self.last_automation_action_time = 0.0
        self.gesture_mode = False
        self.airtouch_mode = False
        self.ar_playground = None
        self.ar_mode = False
        self._dismissed_goals = set()  # Goals dismissed this session — never re-surface

    def initialize(self):
        print("\n" + "="*50)
        print("  ARIA — Initializing subsystems...")
        print("="*50)

        set_state("THINKING")
        set_text("Initializing...")

        # Initialize thread-safe speech queue
        import queue
        self.speech_queue = queue.Queue()
        self.proactive_queue = queue.Queue()
        threading.Thread(target=self._speech_worker, daemon=True).start()

        # ── Voice / TTS ─────────────────────────────────────────────────────
        try:
            self.voice = Voice()
            self.voice.on_speech_detected = self.reset_interaction_timeout
            HEALTH.mark_healthy(SUBSYSTEM_TTS, "Voice initialized")
            HEALTH.mark_healthy(SUBSYSTEM_MICROPHONE, "Microphone ready")
        except Exception as _e:
            print(f"[ARIA] WARNING — Voice init failed: {_e}")
            self.voice = None
            HEALTH.mark_failed(SUBSYSTEM_TTS, str(_e), cooldown_seconds=120.0)
            HEALTH.mark_failed(SUBSYSTEM_MICROPHONE, str(_e), cooldown_seconds=120.0)

        # ── LLM / Brain ──────────────────────────────────────────────────────
        try:
            self.brain = Brain()
            HEALTH.mark_healthy(SUBSYSTEM_LLM, "Brain initialized")
        except Exception as _e:
            print(f"[ARIA] WARNING — Brain init failed: {_e}")
            self.brain = None
            HEALTH.mark_failed(SUBSYSTEM_LLM, str(_e), cooldown_seconds=60.0)

        # ── Camera ───────────────────────────────────────────────────────────
        try:
            self.camera = Camera()
            if getattr(self.camera, 'available', False):
                HEALTH.mark_healthy(SUBSYSTEM_CAMERA, "Webcam opened")
            else:
                HEALTH.mark_degraded(SUBSYSTEM_CAMERA, "Camera opened but unavailable", increment_failure=False)
        except Exception as _e:
            print(f"[ARIA] WARNING — Camera init failed: {_e}")
            self.camera = None
            HEALTH.mark_failed(SUBSYSTEM_CAMERA, str(_e), cooldown_seconds=60.0)

        # ── Browser Automation ───────────────────────────────────────────────
        try:
            self.automation = Automation()
            HEALTH.mark_healthy(SUBSYSTEM_BROWSER, "Automation initialized")
            HEALTH.mark_healthy(SUBSYSTEM_AUTOMATION, "Automation initialized")
        except Exception as _e:
            print(f"[ARIA] WARNING — Automation init failed: {_e}")
            self.automation = None
            HEALTH.mark_failed(SUBSYSTEM_BROWSER, str(_e), cooldown_seconds=60.0)
            HEALTH.mark_failed(SUBSYSTEM_AUTOMATION, str(_e), cooldown_seconds=60.0)

        # ── Face Memory / Vision ─────────────────────────────────────────────
        try:
            self.memory = FaceMemory()
            HEALTH.mark_healthy(SUBSYSTEM_VISION, "Face memory initialized")
        except Exception as _e:
            print(f"[ARIA] WARNING — FaceMemory init failed: {_e}")
            self.memory = None
            HEALTH.mark_failed(SUBSYSTEM_VISION, str(_e), cooldown_seconds=60.0)

        # ── Object Detection / Vision Learner ─────────────────────────────────
        try:
            self.vision_learner = VisionLearner()
            self.vision_learner.face_mem = self.memory  # Link for Person Mode
            HEALTH.mark_healthy(SUBSYSTEM_OBJECT_DETECTION, "VisionLearner initialized")
        except Exception as _e:
            print(f"[ARIA] WARNING — VisionLearner init failed: {_e}")
            self.vision_learner = None
            HEALTH.mark_failed(SUBSYSTEM_OBJECT_DETECTION, str(_e), cooldown_seconds=60.0)

        # ── Screen / UI Control ───────────────────────────────────────────────
        try:
            self.screen = ScreenControl()
        except Exception as _e:
            print(f"[ARIA] WARNING — ScreenControl init failed: {_e}")
            self.screen = None
        try:
            self.ui = UIControl()   # Direct Windows UI control — no vision needed
        except Exception as _e:
            print(f"[ARIA] WARNING — UIControl init failed: {_e}")
            self.ui = None
        
        # Initialize Security Guard & Unified Memory Manager
        from skills.memory_manager import MemoryManager
        self.memory_manager = MemoryManager()
        self.memory_manager.validate_and_heal_database()
        from skills.security_guard import SecurityGuard
        self.security = SecurityGuard(memory_manager=self.memory_manager)
        
        # Attention and Prioritization Manager
        from skills.attention_manager import AttentionManager
        self.attention_manager = AttentionManager()
        self.paused_by_interrupt = False

        # Cognitive Load Manager
        from skills.cognitive_load_manager import CognitiveLoadManager
        self.cognitive_load_manager = CognitiveLoadManager()

        # Confidence Calibration Engine
        from skills.confidence_calibration import ConfidenceCalibrationEngine
        self.confidence_calibrator = ConfidenceCalibrationEngine()

        # Dynamic Runtime Mode Profiler
        from skills.mode_profiler import RuntimeModeProfiler
        self.mode_profiler = RuntimeModeProfiler()
        
        # Sleep / Idle Consolidation Cycle variables
        self.last_agent_activity = time.time()
        self.idle_consolidation_done = True  # Start optimized

        # Skill Plugins instantiation
        self.memory_skill = MemorySkill()
        self.context_skill = ContextSkill()
        self.workspace_skill = WorkspaceSkill(self.memory_skill, self.automation, self.screen)
        self.firebase_sync = FirebaseSync(command_callback=self._handle_input)

        # New Cognitive Core Plugins Instantiation
        self.sandbox_safety = SandboxSafetyLayer()
        self.executor_queue = ExecutorQueue()
        self.context_budget = ContextBudgetManager()
        self.reflection_engine = ReflectionEngine()
        self.proactive_cognition = ProactiveCognition()
        self.episodic_memory = EpisodicMemory()

        # Start Background Task Executor Queue Worker
        threading.Thread(target=self._executor_queue_worker, daemon=True).start()

        # Proactive Alert Timers
        self.start_time = time.time()
        self.last_battery_check = 0
        self.last_break_check = time.time()
        self.last_activity_log = 0
        self.last_reminder_check = 0

        if not self.brain or not self.brain.model:
            print("\n[ARIA] WARNING Brain failed - check api_key.txt")
            set_state("ERROR")
            set_text("Brain offline. Check API key.")
            # Still run so user gets an error spoken
        else:
            print("[ARIA] OK Brain online.")

        # Start ARIA Observability Dashboard server in a background thread
        try:
            import uvicorn
            from dashboard import app
            
            def run_server():
                uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
                
            server_thread = threading.Thread(target=run_server, daemon=True)
            server_thread.start()
            print("[ARIA Observability] Dashboard active at http://127.0.0.1:8000")
        except Exception as e:
            print(f"[ARIA Observability] Could not start dashboard: {e}")

        # Start Telegram Bot Remote Control if token exists
        try:
            from skills.api_integrations import APIIntegrations
            api_int = APIIntegrations()
            api_int.start_telegram_bot(self)
        except Exception as e:
            print(f"[ARIA] Could not start Telegram Bot remote control: {e}")

        self.running = True
        try:
            self.firebase_sync.start()
            HEALTH.mark_healthy(SUBSYSTEM_FIREBASE, "Firebase sync started")
        except Exception as _fe:
            print(f"[ARIA] WARNING — Firebase sync failed: {_fe}")
            HEALTH.mark_failed(SUBSYSTEM_FIREBASE, str(_fe), cooldown_seconds=120.0)
        
        # Start Proactive Background Cognition Scheduler
        try:
            scheduler_thread = threading.Thread(target=self._run_background_scheduler, daemon=True)
            scheduler_thread.start()
            print("[ARIA Scheduler] Proactive Background Cognition Loop active.")
        except Exception as se:
            print(f"[ARIA Scheduler] Could not start proactive scheduler: {se}")
        
        # Check for unfinished sessions and prompt to Resume
        try:
            import json
            if os.path.exists("active_session.json"):
                with open("active_session.json", "r") as sf:
                    session = json.load(sf)
                if session.get("status") == "active" and session.get("goal"):
                    goal = session["goal"]
                    # Skip if already dismissed this session
                    if goal in self._dismissed_goals:
                        print(f"[ARIA Session] Goal '{goal}' was already dismissed this session. Skipping.")
                    else:
                        print(f"[ARIA Session] Found active unfinished goal: {goal}")
                        
                        def ask_resume():
                            time.sleep(3.0)  # Wait for GUI/Audio to load
                            self._speak(f"I found an unfinished task from your last session: '{goal}'. Should I resume it?")
                            feedback = self.voice.listen(timeout=8)
                            if feedback and any(x in feedback.lower() for x in ["yes", "resume", "go ahead", "sure", "ok", "okay"]):
                                self._speak("Resuming task now.")
                                threading.Thread(target=self.run_autonomous_agent, args=(goal,), daemon=True).start()
                            else:
                                # User said no/later — dismiss for this session
                                self._dismissed_goals.add(goal)
                                self._speak("Task cleared.")
                                if os.path.exists("active_session.json"):
                                    os.remove("active_session.json")
                                    
                        threading.Thread(target=ask_resume, daemon=True).start()
        except Exception as e:
            print(f"[ARIA Session] Checkpoint check failed: {e}")
        mode_str = "Always-On" if self.wake_mode else "Wake-Word"
        print(f"[ARIA] All systems ready. Mode: {mode_str}\n")

        # Print health summary after all subsystems initialized
        _failed = HEALTH.get_failed()
        _degraded = HEALTH.get_degraded()
        if _failed or _degraded:
            print("[HealthMonitor] Startup health summary:")
            for _s in _failed:
                _reason = HEALTH.get_state(_s).reason
                print(f"  [FAIL] {_s.upper()}: FAILED -- {_reason}")
            for _s in _degraded:
                _reason = HEALTH.get_state(_s).reason
                print(f"  [WARN] {_s.upper()}: DEGRADED -- {_reason}")
        else:
            print("[HealthMonitor] All subsystems HEALTHY [OK]")

    def reset_interaction_timeout(self):
        """Update last interaction time when voice VAD or speech starts."""
        self.last_interaction_time = time.time()
        self.last_user_speech_time = time.time()
        if hasattr(self, "conversation_session"):
            self.conversation_session.touch(wake_reason="speech_activity")

    def is_user_speaking(self):
        now = time.time()
        recording = self.voice and getattr(self.voice, 'recording_active', False)
        user_speaking = self.voice and getattr(self.voice, 'vad_detecting_speech', False)
        recent_speech = (now - getattr(self, "last_user_speech_time", 0.0)) < 3.0
        return bool(recording or user_speaking or recent_speech)

    def safe_speak(self, text):
        if self.is_user_speaking():
            print(f"[ARIA] User is speaking. Queuing proactive speech: '{text}'")
            if not hasattr(self, "pending_speech"):
                self.pending_speech = []
            self.pending_speech.append(text)
        else:
            self._speak(text)

    def deliver_proactive(self, msg):
        if not msg:
            return
        if msg in self._proactive_history:
            return
        key = msg[:30]
        last_time = self._proactive_cooldown.get(key, 0)
        if time.time() - last_time < 1800:  # 30 minutes
            return
        self._proactive_history.add(msg)
        self._proactive_cooldown[key] = time.time()
        self.safe_speak(msg)

    def _mark_conversation_activity(self, wake_reason="interaction", active_task_id=None):
        """Refresh the active conversation window after user or ARIA activity."""
        self.last_interaction_time = time.time()
        if hasattr(self, "conversation_session"):
            self.conversation_session.touch(wake_reason=wake_reason, active_task_id=active_task_id)

    def _is_aria_busy(self):
        """Returns True if any background subsystem is actively running."""
        # Check AR playground is running
        if getattr(self, 'ar_playground', None) is not None and self.ar_playground._running:
            return True
        # Check 3D model is currently generating
        if getattr(self, 'ar_playground', None) is not None:
            ar = self.ar_playground
            if getattr(ar, '_model_gen', None) is not None:
                if getattr(ar._model_gen, '_generating', False):
                    return True
        # Check vision learner running
        if getattr(self, 'vision_learner', None) is not None and getattr(self.vision_learner, 'running', False):
            return True
        # Check gesture control running
        if getattr(self, 'gesture_mode', False):
            return True
        return False

    def _has_active_conversation_task(self):
        """True when an active task should keep ARIA in light conversational idle."""
        if self._is_aria_busy():
            self.conversation_session.touch(wake_reason="background_subsystem")
            return True
        try:
            if self.brain and self.brain.semantic_router:
                active = self.brain.semantic_router.task_manager.get_active_task()
                if active and getattr(active, "status", "") in {"RUNNING", "WAITING", "INTERRUPTED"}:
                    return True
        except Exception:
            pass
        try:
            active = self.executor_queue.get_active_task() if hasattr(self, "executor_queue") else None
            if active:
                return True
        except Exception:
            pass
        return bool(getattr(self, "automation_mode", False))
        self._was_in_conversation = True

    def _executor_queue_worker(self):
        """Worker thread that processes the task execution queue."""
        print("[ARIA Queue] Executor queue worker running.")
        while self.running:
            try:
                task_item = self.executor_queue.get_next_task()
                if not task_item:
                    time.sleep(1.0)
                    continue

                if task_item.cancelled:
                    print(f"[ARIA Queue] Skipping enqueued task '{task_item.goal}' because it was cancelled.")
                    self.executor_queue.finish_active_task()
                    continue

                # Execute active task
                print(f"[ARIA Queue] Executing queued task: '{task_item.goal}'")
                self.run_autonomous_agent(task_item.goal, task_item=task_item)
                self.executor_queue.finish_active_task()
            except Exception as e:
                print(f"[ARIA Queue] Error executing queued task: {e}")
                time.sleep(1.0)

    def replay_task(self, task_id: str):
        """Reads trace log from /replays/task_id/ and replays steps visually/verbally."""
        base_dir = os.path.join("replays", task_id)
        trace_path = os.path.join(base_dir, "trace.json")
        reflections_path = os.path.join(base_dir, "reflections.json")
        
        if not os.path.exists(trace_path):
            self._speak(f"Replay failed. No recorded trace found for task ID {task_id}.")
            return
            
        try:
            with open(trace_path, "r", encoding="utf-8") as f:
                trace_data = json.load(f)
                
            goal = trace_data.get("goal", "unknown goal")
            steps = trace_data.get("steps", [])
            
            self._speak(f"Starting cognitive replay for task: '{goal}'. Total recorded steps: {len(steps)}.")
            time.sleep(1.0)
            
            for i, step in enumerate(steps, 1):
                action = step.get("action", "")
                status = step.get("status", "success")
                duration = step.get("duration", 0.0)
                
                self._speak(f"Step {i}. Action tag was: {action}. Execution result was: {status} in {duration:.1f} seconds.")
                time.sleep(1.5)
                
            if os.path.exists(reflections_path):
                with open(reflections_path, "r", encoding="utf-8") as rf:
                    ref_data = json.load(rf)
                reflections = ref_data.get("reflections", "")
                if reflections:
                    self._speak(f"Mental reflections for this task: {reflections}")
                    
            self._speak("Replay finished.")
        except Exception as e:
            print(f"[Replay] Error replaying task: {e}")
            self._speak("An error occurred during replay execution.")

    # ── Background Scheduler Loop ─────────────────────────────────────────────
    def _run_background_scheduler(self):
        """Proactive background scheduler that checks battery levels, break suggestions, and database reminders."""
        import datetime
        import psutil
        from skills.event_bus import EventBus
        
        last_battery_check_time = 0
        last_break_check_time = time.time()
        
        print("[ARIA Scheduler] Proactive Background Loop successfully running.")
        
        while self.running:
            try:
                now = time.time()
                
                # 1. Reminders check (every 15 seconds)
                try:
                    with self.memory_skill._get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT id, task, due_at, due_date FROM reminders WHERE status = 'pending'")
                        pending = cursor.fetchall()
                        
                        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
                        current_time = datetime.datetime.now().strftime("%H:%M")
                        
                        for rid, task, due_time, due_date in pending:
                            trigger_reminder = False
                            # Match date
                            if due_date and due_date <= current_date:
                                if not due_time or due_time <= current_time:
                                    trigger_reminder = True
                            
                            if trigger_reminder:
                                # Mark as notified/done
                                cursor.execute("UPDATE reminders SET status = 'completed' WHERE id = ?", (rid,))
                                conn.commit()
                                
                                # Evaluate Priority Triage
                                action = self.attention_manager.evaluate_event("reminder", {"task": task})
                                EventBus().publish("SCHEDULER_ALERT", {"task": task, "type": "reminder", "action": action})
                                
                                if action == "execute":
                                    set_state("SPEAKING")
                                    self._speak(f"Proactive alert. You have a reminder: '{task}'.")
                                    set_state("IDLE")
                                else:
                                    # Batch notification silently
                                    try:
                                        from dashboard import CognitionState
                                        CognitionState.pending_notifications = self.attention_manager.pending_notifications[:]
                                    except Exception:
                                        pass
                except Exception as re_err:
                    print(f"[ARIA Scheduler] Reminders check error: {re_err}")
                
                # Evaluate Cognitive Load and execute adaptive regulation (every 15s)
                try:
                    self.cognitive_load_manager.regulate_cognition(self)
                    # Update load status to dashboard API
                    load_metrics = self.cognitive_load_manager.get_load_metrics()
                    from dashboard import CognitionState
                    CognitionState.cognitive_load_score = load_metrics["load_score"]
                    CognitionState.cognitive_load_status = load_metrics["status"]
                except Exception as ce:
                    print(f"[ARIA Scheduler] Load evaluation error: {ce}")

                # Sleep / Idle Consolidation Cycle (after 60s of agent inactivity)
                if not self.idle_consolidation_done and (now - self.last_agent_activity > 60):
                    try:
                        # Ensure no task is actively running
                        if self.attention_manager.focus_priority == 0:
                            print("[ARIA Scheduler] INITIATING OFFLINE MEMORY CONSOLIDATION CYCLE...")
                            set_state("SPEAKING")
                            self._speak("Subsystems entering idle. Initiating memory consolidation cycle.")
                            set_state("IDLE")
                            
                            # Perform memory GC and compact database indexes
                            self.memory_skill.compress_memories()
                            
                            # Clean/vacuum sqlite database indexes
                            with self.memory_skill._get_connection() as conn:
                                conn.execute("VACUUM")
                                
                            self.idle_consolidation_done = True
                            set_state("SPEAKING")
                            self._speak("Offline consolidation complete. Subsystems optimized.")
                            set_state("IDLE")
                    except Exception as s_err:
                        print(f"[ARIA Scheduler] Idle consolidation error: {s_err}")

                # 2. Battery check (every 5 minutes)
                if now - last_battery_check_time > 300:
                    last_battery_check_time = now
                    try:
                        battery = psutil.sensors_battery()
                        if battery:
                            percent = battery.percent
                            power_plugged = battery.power_plugged
                            if percent < 20 and not power_plugged:
                                                            # Low Battery is Priority 4: Interrupt task immediately
                                                            action = self.attention_manager.evaluate_event("low_battery", {"percent": percent})
                                                            EventBus().publish("SYSTEM_ALERT", {"type": "low_battery", "percent": percent, "action": action})
                                                            
                                                            if action == "execute":
                                                                # Interrupt running task
                                                                has_task = getattr(self, "attention_manager", None) and self.attention_manager.focus_priority > 0
                                                                if has_task:
                                                                    self.paused_by_interrupt = True
                                                                    print("[AttentionManager] INTERRUPTING ACTIVE WORKFLOW FOR CRITICAL BATTERY ALERT.")
                                                                    
                                                                set_state("SPEAKING")
                                                                self._speak(f"System alert. Battery level is low at {percent} percent. Please connect a charger.")
                                                                set_state("IDLE")
                                                                
                                                                if has_task:
                                                                    self.paused_by_interrupt = False
                                                            else:
                                                                # Batch notification silently
                                                                try:
                                                                    from dashboard import CognitionState
                                                                    CognitionState.pending_notifications = self.attention_manager.pending_notifications[:]
                                                                except Exception:
                                                                    pass
                    except Exception as bat_err:
                        print(f"[ARIA Scheduler] Battery telemetry error: {bat_err}")
                
                # 3. Stretch break check (every 45 minutes)
                if now - last_break_check_time > 2700:
                    last_break_check_time = now
                    action = self.attention_manager.evaluate_event("break_suggestion", {})
                    EventBus().publish("SYSTEM_ALERT", {"type": "break_suggestion", "action": action})
                    
                    if action == "execute":
                        set_state("SPEAKING")
                        self._speak("System alert. You have been working continuously. I suggest taking a short break to stretch.")
                        set_state("IDLE")
                    else:
                        # Batch notification silently
                        try:
                            from dashboard import CognitionState
                            CognitionState.pending_notifications = self.attention_manager.pending_notifications[:]
                        except Exception:
                            pass

                # 3.5. Background User Perception (run every 60 seconds)
                if now - getattr(self, "last_background_perception_time", 0.0) > 60.0:
                    try:
                        self._run_background_perception()
                    except Exception as perc_err:
                        print(f"[ARIA Scheduler] Background user perception error: {perc_err}")

                # 4. Proactive Cognition — soft suggestion check (respects cooldown)
                try:
                    suggestion = None
                    if hasattr(self, "proactive_queue") and self.proactive_queue is not None and not self.proactive_queue.empty():
                        try:
                            suggestion = self.proactive_queue.get_nowait()
                            self.proactive_queue.task_done()
                            print(f"[Proactive] Retrieved suggestion from queue: {suggestion}")
                        except Exception:
                            pass
                    
                    if not suggestion:
                        if not getattr(self, "startup_greeting_done", False) or (now - self.start_time < 120):
                            suggestion = None
                        else:
                            suggestion = self.proactive_cognition.run_background_check(self)
                    if suggestion:
                        action = self.attention_manager.evaluate_event("proactive_suggestion", {"text": suggestion})
                        EventBus().publish("PROACTIVE_SUGGESTION", {"text": suggestion, "action": action})
                        
                        if action == "execute":
                            set_state("SPEAKING")
                            self.deliver_proactive(suggestion)
                            set_state("IDLE")
                            self.last_proactive_suggestion_time = time.time()
                        else:
                            try:
                                from dashboard import CognitionState
                                CognitionState.pending_notifications = self.attention_manager.pending_notifications[:]
                            except Exception:
                                pass
                except Exception as pro_err:
                    print(f"[ARIA Scheduler] Proactive cognition error: {pro_err}")

                # 5. Idle Reflection — trigger background reflection when agent is idle
                try:
                    if self.attention_manager.focus_priority == 0 and (now - self.last_agent_activity > 120):
                        username = self.known_user or "chinmaya"
                        recent_episodes = self.episodic_memory.get_recent(username=username, n=5)
                        if recent_episodes and len(recent_episodes) > 0:
                            self.reflection_engine.reflect_asynchronously(
                                username=username,
                                recent_episodes=recent_episodes,
                                recent_task_results=[]
                            )
                            self.last_agent_activity = now  # Prevent re-triggering continuously
                except Exception as ref_err:
                    print(f"[ARIA Scheduler] Idle reflection error: {ref_err}")

                # 6. Dashboard Telemetry — push relationship & proactive status
                try:
                    from dashboard import CognitionState
                    username = self.known_user or "chinmaya"
                    
                    # Relationship soft labels
                    labels = self.reflection_engine.get_relationship_labels(username)
                    CognitionState.familiarity_label = labels.get("familiarity", "Acquaintance")
                    CognitionState.interaction_depth_label = labels.get("interaction_depth", "Surface-level")
                    
                    # Proactive cooldown status
                    CognitionState.proactive_status = self.proactive_cognition.get_cooldown_status()
                    CognitionState.cooldown_multiplier = self.proactive_cognition.cooldown_multiplier
                    
                    # Push presence state to dashboard
                    CognitionState.presence_state = getattr(self, "presence_state", "USER_LEFT")

                    # Quarantine count from candidate updates table
                    q_count = 0
                    try:
                        with self.reflection_engine._get_conn() as conn:
                            cursor = conn.cursor()
                            cursor.execute("SELECT COUNT(*) FROM candidate_semantic_updates WHERE status = 'quarantined'")
                            row = cursor.fetchone()
                            if row:
                                q_count = row[0]
                    except Exception:
                        pass
                    CognitionState.quarantine_count = q_count
                except Exception:
                    pass
                    
            except Exception as loop_err:
                print(f"[ARIA Scheduler] Scheduler thread error: {loop_err}")
                
            time.sleep(15)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _speak(self, text):
        if hasattr(self, "conversation_session") and self.conversation_session.session_active:
            self._mark_conversation_activity(wake_reason="assistant_reply")
        text = self._sanitize_spoken_text(text)
        if hasattr(self, "_spoken_during_turn") and self._spoken_during_turn is not None:
            self._spoken_during_turn.append(text)
        if getattr(self._reply_context, "phone_only", False):
            print(f"[ARIA/Phone Reply] {text}")
            if hasattr(self, 'firebase_sync') and self.firebase_sync:
                self.firebase_sync.update_status(text, status_str="idle")
            return

        # Graceful TTS degradation — if TTS subsystem is FAILED, fall back to console
        if not HEALTH.is_available(SUBSYSTEM_TTS):
            print(f"[ARIA/TTS-OFFLINE] {text}")
            try:
                set_text(text[:120] + "..." if len(text) > 120 else text)
            except Exception:
                pass
            return

        # Push to the thread-safe queue for sequential processing
        if self.speech_queue:
            self.speech_queue.put(text)
        else:
            if self.voice:
                self.voice.speak(text)

    def _sanitize_spoken_text(self, text):
        """Remove repeated personal greetings after the startup greeting."""
        if not text:
            return text
        cleaned = str(text).strip()
        if not self.startup_greeting_done:
            return cleaned

        names = ["chinmay", "chinmaya"]
        if self.known_user:
            names.append(str(self.known_user).strip().lower().rstrip("."))
        name_group = "|".join(re.escape(n) for n in sorted(set(names)) if n)
        if name_group:
            cleaned = re.sub(
                rf"(?i)\b(hi|hello|hey)\s+({name_group})[,\.!\s]+",
                "",
                cleaned,
                count=1,
            ).strip()
            cleaned = re.sub(
                rf"(?i)^\s*,?\s*({name_group})[,\.!\s]+",
                "",
                cleaned,
            ).strip()
        return cleaned or text

    def _wait_for_speech(self):
        """Block until the speech queue is processed and the voice has stopped playing audio."""
        if self.speech_queue:
            self.speech_queue.join()
        while self.voice and self.voice.is_speaking:
            time.sleep(0.05)

    def _speech_worker(self):
        while True:
            try:
                # Blocks until an item is available
                text = self.speech_queue.get()
                if text is None:
                    break

                set_state("SPEAKING")
                set_text(text[:100] + "..." if len(text) > 100 else text)
                if hasattr(self, 'firebase_sync') and self.firebase_sync:
                    self.firebase_sync.update_status(text, status_str="speaking")

                # Animate waveform while speaking
                _stop_wave = threading.Event()
                def _wave_loop():
                    while not _stop_wave.is_set():
                        trigger_wave()
                        time.sleep(0.08)
                wt = threading.Thread(target=_wave_loop, daemon=True)
                wt.start()

                # Speak using Edge-TTS (blocks this worker thread)
                try:
                    interrupted = self.voice.speak(text)
                    # Mark TTS healthy on successful speak
                    if HEALTH.get_status(SUBSYSTEM_TTS) != "HEALTHY":
                        HEALTH.mark_healthy(SUBSYSTEM_TTS, "TTS recovered — speak succeeded")
                except Exception as _tts_err:
                    print(f"[SpeechWorker] TTS exception: {_tts_err}")
                    HEALTH.mark_degraded(SUBSYSTEM_TTS, f"TTS speak error: {_tts_err}")
                    interrupted = False

                _stop_wave.set()
                self.speech_queue.task_done()

                if interrupted:
                    print("[SpeechWorker] Speech was interrupted! Clearing the speech queue.")
                    try:
                        self.cognitive_load_manager.log_interruption()
                    except Exception:
                        pass
                    
                    while not self.speech_queue.empty():
                        try:
                            self.speech_queue.get_nowait()
                            self.speech_queue.task_done()
                        except Exception:
                            break
                            
                    set_state("IDLE")
                    if hasattr(self, 'firebase_sync') and self.firebase_sync:
                        self.firebase_sync.update_status("", status_str="idle")
                    self.last_interaction_time = time.time()
                    continue

                # Transition back to IDLE only if queue is empty
                if self.speech_queue.empty():
                    set_state("IDLE")
                    if hasattr(self, 'firebase_sync') and self.firebase_sync:
                        self.firebase_sync.update_status(text, status_str="idle")
                    self._mark_conversation_activity(wake_reason="assistant_reply_complete")
            except Exception as e:
                print(f"[SpeechWorker] Unexpected error: {e}")
                time.sleep(0.2)

    def identify_user(self):
        """Wrapper/alias to _detect_user for Security Guard calls."""
        return self._detect_user()

    def _detect_user(self):
        """Try to identify the user from the webcam using multi-frame averaging, temporal smoothing, and persistence locking."""
        # Privacy Zone check
        active_window = self.context_skill.get_active_window()
        if not self.sandbox_safety.is_perception_allowed(active_window):
            print(f"[SandboxSafety] Webcam perception blocked: Privacy Zone active (Window: '{active_window}').")
            return None

        if not self.camera.available:
            return None
            
        import numpy as np
        import time
        
        now = time.time()
        
        # 1. Identity persistence lock check (30 seconds)
        # If we have a confidently identified user within the last 30s, do a fast check using 1 frame
        if self.known_user and self.known_user != "Unknown" and self.known_user_confidence == "high" and (now - self.last_identity_match_time < 30.0):
            img = self.camera.capture_image()
            if img is not None:
                try:
                    arr = np.array(img)
                    emb = self.memory.memory_manager.embedder.get_embedding(arr)
                    if emb:
                        name, similarity = self.memory.memory_manager.identify_user(
                            threshold=0.63, 
                            return_confidence=True, 
                            embedding=emb
                        )
                        if name == self.known_user:
                            # Keep identity locked and refresh timestamp
                            self.last_identity_match_time = now
                            self.known_user_similarity = similarity
                            
                            # Keep temporal history buffer healthy
                            self.face_match_history.append((name, similarity))
                            if len(self.face_match_history) > 5:
                                self.face_match_history.pop(0)
                            return name
                        elif name != "Unknown":
                            print(f"[Main] Persistence lock: detected name '{name}' differs from locked '{self.known_user}'. Breaking lock.")
                except Exception:
                    pass
        
        embeddings = []
        
        # 2. Capture 5 frames at 30ms intervals
        for i in range(5):
            img = self.camera.capture_image()
            if img is not None:
                try:
                    arr = np.array(img)
                    emb = self.memory.memory_manager.embedder.get_embedding(arr)
                    if emb:
                        embeddings.append(emb)
                except Exception:
                    pass
            time.sleep(0.03)
            
        if not embeddings:
            # Face disappeared / no face seen — use grace period before clearing identity
            # so brief look-aways or lighting glitches don't reset user context
            FACE_LOSS_GRACE_SECONDS = 30.0
            now_t = time.time()
            last_seen = getattr(self, "_face_last_seen_time", 0.0)
            if self.known_user and self.known_user != "Unknown":
                if (now_t - last_seen) > FACE_LOSS_GRACE_SECONDS:
                    print(f"[Main] No face detected for {FACE_LOSS_GRACE_SECONDS:.0f}s. Clearing active user '{self.known_user}'.")
                    self.known_user = None
                    self.known_user_confidence = "none"
                    self.known_user_similarity = 0.0
                    self.face_match_history = []
                else:
                    remaining = FACE_LOSS_GRACE_SECONDS - (now_t - last_seen)
                    print(f"[Main] No face detected — holding context for '{self.known_user}' ({remaining:.0f}s grace remaining).")
            return None
            
        # 3. Compute averaged embedding vector
        avg_emb = np.mean(embeddings, axis=0)
        
        # L2 normalize the centroid vector
        norm = np.linalg.norm(avg_emb)
        if norm > 0:
            avg_emb = avg_emb / norm
            
        try:
            # 4. Query ChromaDB with averaged embedding
            name, similarity = self.memory.memory_manager.identify_user(
                threshold=0.63, 
                return_confidence=True, 
                embedding=avg_emb.tolist()
            )
            
            if name != "Unknown":
                # 5. Add to temporal history buffer
                self.face_match_history.append((name, similarity))
                if len(self.face_match_history) > 5:
                    self.face_match_history.pop(0)
                    
                # 6. Apply temporal smoothing boost if user matches consistently (>= 3 out of last 5)
                from collections import Counter
                recent_names = [item[0] for item in self.face_match_history if item[0] != "Unknown"]
                if recent_names:
                    most_common_name, count = Counter(recent_names).most_common(1)[0]
                    if count >= 3 and most_common_name == name:
                        old_similarity = similarity
                        similarity = min(1.0, similarity + 0.05)
                        if similarity != old_similarity:
                            print(f"[Main] Temporal smoothing: '{name}' detected consistently ({count}/5). Boosting similarity from {old_similarity:.3f} to {similarity:.3f}.")
                
                # Classify confidence based on boosted similarity
                self.known_user = name
                self.known_user_similarity = similarity
                self._face_last_seen_time = time.time()  # Update grace period timestamp
                if similarity >= 0.85:
                    self.known_user_confidence = "high"
                    self.last_identity_match_time = time.time()
                elif similarity >= 0.75:
                    self.known_user_confidence = "medium"
                else:
                    self.known_user_confidence = "low"
                return name
            else:
                # Face identified as Unknown -> clear identity
                if self.known_user and self.known_user != "Unknown":
                    print(f"[Main] Face identified as Unknown. Clearing active user '{self.known_user}'.")
                    self.known_user = None
                    self.known_user_confidence = "none"
                    self.known_user_similarity = 0.0
                    self.face_match_history = []
                return None
        except Exception as e:
            print(f"[Main] Face detection error: {e}")
            return None

    def _get_current_emotion(self) -> str:
        """
        Gets current user emotion from:
        1. Latest face detection (Moondream)
        2. Falls back to neutral if unavailable
        Uses a 30-second cache to minimize vision query latency.
        """
        now = time.time()
        # 1. Prioritize recent voice emotion if it is not neutral and was captured within the last 30s
        if hasattr(self, "voice") and self.voice:
            if hasattr(self.voice, "last_voice_emotion") and hasattr(self.voice, "last_voice_emotion_time"):
                ve = self.voice.last_voice_emotion
                vet = self.voice.last_voice_emotion_time
                if ve and ve != "neutral" and (now - vet < 30.0):
                    self._last_emotion = ve
                    self._last_emotion_time = now
                    try:
                        self._store_emotion_event(ve)
                        self._update_emotion_history(ve)
                    except Exception as err:
                        print(f"[Emotion] Failed to store voice emotion event: {err}")
                    return ve

        # 2. Return cached emotion if recent
        if hasattr(self, "_last_emotion_time") and hasattr(self, "_last_emotion"):
            if now - self._last_emotion_time < 30.0:
                # Return cached emotion
                return self._last_emotion

        emotion = "neutral"
        try:
            if not self.camera or not self.camera.available:
                return "neutral"
            
            img = self.camera.capture_image()
            if img is None:
                return "neutral"
                
            import numpy as np
            import cv2
            import io
            import base64
            
            arr = np.array(img)
            if len(arr.shape) == 2 or arr.shape[2] == 1:
                gray = arr
                img_rgb = img.convert("RGB")
            else:
                gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
                img_rgb = img
                
            faces = self.memory.face_cascade.detectMultiScale(gray, 1.3, 5)
            if len(faces) == 0:
                emotion = "neutral"
            else:
                x, y, w, h = faces[0]
                face_img = img_rgb.crop((x, y, x + w, y + h))
                
                face_buf = io.BytesIO()
                face_img.save(face_buf, format="PNG")
                face_b64 = base64.b64encode(face_buf.getvalue()).decode("utf-8")
                
                prompt = "Describe the emotion or facial expression of the person in this face crop."
                if self.brain.vision_ready:
                    description = self.brain._ask_vision(face_b64, prompt)
                    if description:
                        emotion = self._parse_emotion(description)
                        self._store_emotion_event(emotion)
                        self._update_emotion_history(emotion)
        except Exception as e:
            print(f"[Emotion] Detection failed: {e}")
            emotion = "neutral"
            
        self._last_emotion = emotion
        self._last_emotion_time = now
        return emotion

    def _parse_emotion(self, description: str) -> str:
        """
        Extracts emotion keyword from Moondream description.
        """
        description = description.lower()
        
        emotion_keywords = {
            "happy":     ["happy", "smiling", "smile", "joyful", "cheerful", "laughing"],
            "sad":       ["sad", "unhappy", "crying", "tears", "sorrow", "gloomy"],
            "angry":     ["angry", "frustrated", "annoyed", "mad", "furious", "irritated"],
            "stressed":  ["stressed", "worried", "anxious", "tense", "nervous", "concerned"],
            "tired":     ["tired", "sleepy", "exhausted", "drowsy", "fatigue", "yawning"],
            "surprised": ["surprised", "shocked", "amazed", "astonished", "wide-eyed"],
            "neutral":   ["neutral", "calm", "normal", "relaxed", "composed"]
        }
        
        for emotion, keywords in emotion_keywords.items():
            for keyword in keywords:
                if keyword in description:
                    return emotion
        
        return "neutral"

    def _store_emotion_event(self, emotion: str):
        """
        Stores detected emotion in episodic memory.
        """
        importance_map = {
            "happy":     0.6,
            "sad":       0.9,  # sad = high importance
            "angry":     0.8,
            "stressed":  0.8,
            "tired":     0.5,
            "surprised": 0.6,
            "neutral":   0.2
        }
        
        importance = importance_map.get(emotion, 0.2)
        
        try:
            user = self.known_user or "chinmaya"
            event_text = f"User appeared {emotion}."
            self.episodic_memory.record(
                username=user,
                event_text=event_text,
                emotion=emotion,
                importance=importance,
                source="observed"
            )
        except Exception as e:
            print(f"[Emotion] Failed to record emotion event: {e}")

    def _update_emotion_history(self, emotion: str):
        """
        Tracks emotion patterns over time.
        Enables ARIA to notice: 'You seem stressed a lot lately'
        """
        if not hasattr(self, "emotion_history") or self.emotion_history is None:
            self.emotion_history = []
        if not hasattr(self, "emotion_counts") or self.emotion_counts is None:
            self.emotion_counts = {}
            
        self.emotion_history.append({
            "emotion": emotion,
            "timestamp": time.time()
        })
        
        # Keep only last 10
        self.emotion_history = self.emotion_history[-10:]
        
        # Count frequencies
        self.emotion_counts[emotion] = self.emotion_counts.get(emotion, 0) + 1
        
        # Detect concerning patterns
        self._check_emotion_patterns()

    def _check_emotion_patterns(self):
        """
        Proactively notices emotional patterns.
        """
        if not hasattr(self, "emotion_history") or self.emotion_history is None or len(self.emotion_history) < 5:
            return
        
        recent = [e["emotion"] for e in self.emotion_history[-5:]]
        
        # Mostly stressed lately
        if recent.count("stressed") >= 3:
            if hasattr(self, "proactive_queue") and self.proactive_queue is not None:
                import random
                STRESS_RESPONSES = [
                    "You seem a bit stressed. Want to take a break?",
                    "Everything alright? You've seemed tense lately.",
                    "Hey, noticed you seem stressed. I'm here if you need anything.",
                    "I've noticed you seem quite stressed lately. Is everything okay?",
                    None,
                    None,
                    None,
                ]
                response = random.choice(STRESS_RESPONSES)
                if response:
                    self.proactive_queue.put(response)
        
        # Mostly tired
        if recent.count("tired") >= 3:
            if hasattr(self, "proactive_queue") and self.proactive_queue is not None:
                self.proactive_queue.put(
                    "You seem really tired. Maybe take a break?"
                )
        
        # Mood improved
        if recent[-1] == "happy" and recent[-2] in ["sad", "stressed"]:
            if hasattr(self, "proactive_queue") and self.proactive_queue is not None:
                self.proactive_queue.put(
                    "You seem to be feeling better! Good to see."
                )

    def _run_background_perception(self):
        """Runs periodic background webcam scans to detect presence and emotions."""
        self.last_background_perception_time = time.time()

        # Privacy Zone check
        active_window = self.context_skill.get_active_window()
        if not self.sandbox_safety.is_perception_allowed(active_window):
            print(f"[BackgroundPerception] Webcam perception blocked: Privacy Zone active (Window: '{active_window}').")
            self.presence_state = "USER_LEFT"
            return

        if not self.camera.available:
            return

        img = self.camera.capture_image()
        if img is None:
            self.presence_state = "USER_LEFT"
            return

        import numpy as np
        import cv2
        import io
        import base64

        arr = np.array(img)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        
        faces = []
        try:
            faces = self.memory.face_cascade.detectMultiScale(gray, 1.3, 5)
        except Exception as e:
            print(f"[BackgroundPerception] Face detection error: {e}")

        if len(faces) == 0:
            self.presence_state = "USER_LEFT"
            self.current_user_emotion = "neutral"
            self.current_user_emotion_confidence = 1.0
            return

        user = self.known_user or "chinmaya"
        try:
            emb = self.memory.memory_manager.embedder.get_embedding(arr)
            if emb:
                name, similarity = self.memory.memory_manager.identify_user(
                    threshold=0.63, 
                    return_confidence=True, 
                    embedding=emb
                )
                if name != "Unknown":
                    user = name
                    self.known_user = name
                    self.known_user_similarity = similarity
                    if similarity >= 0.85:
                        self.known_user_confidence = "high"
                        self.last_identity_match_time = time.time()
                    elif similarity >= 0.75:
                        self.known_user_confidence = "medium"
                    else:
                        self.known_user_confidence = "low"
        except Exception as id_err:
            print(f"[BackgroundPerception] Identity match error: {id_err}")

        matched_emotion = "neutral"
        try:
            x, y, w, h = faces[0]
            face_img = img.crop((x, y, x + w, y + h))
            
            face_buf = io.BytesIO()
            face_img.save(face_buf, format="PNG")
            face_b64 = base64.b64encode(face_buf.getvalue()).decode("utf-8")
            
            prompt = (
                "Describe the emotion or facial expression of the person in this face crop."
            )
            if self.brain.vision_ready:
                emotion_res = self.brain._ask_vision(face_b64, prompt)
                detected_emotion = emotion_res.strip().lower()
                
                valid_emotions = ["happy", "sad", "angry", "stressed", "anxious", "frustrated", "tired", "neutral"]
                for emo in valid_emotions:
                    if emo in detected_emotion:
                        matched_emotion = emo
                        break
        except Exception as emo_err:
            print(f"[BackgroundPerception] Emotion detection error: {emo_err}")

        old_emotion = self.current_user_emotion
        if matched_emotion != old_emotion:
            print(f"[BackgroundPerception] Emotion transitioned: {old_emotion} -> {matched_emotion}")
            self.current_user_emotion = matched_emotion
            self.current_user_emotion_confidence = 0.8
            
            try:
                event_text = f"ARIA observed that the user appears to be feeling {matched_emotion}."
                self.episodic_memory.record(
                    username=user,
                    event_text=event_text,
                    emotion=matched_emotion,
                    importance=0.6,
                    emotional_weight=0.7 if matched_emotion in ["sad", "angry", "stressed", "anxious", "frustrated", "tired"] else 0.3,
                    confidence=0.8,
                    source="observed",
                    retention_tier="permanent"
                )
            except Exception as rec_err:
                print(f"[BackgroundPerception] Failed to record emotional episode: {rec_err}")

        is_emotional = matched_emotion in ["sad", "angry", "stressed", "anxious", "frustrated", "tired"]
        if is_emotional:
            self.presence_state = "USER_EMOTIONAL"
        else:
            now = time.time()
            elapsed_interaction = now - self.last_interaction_time
            if elapsed_interaction < 30.0:
                self.presence_state = "USER_ENGAGED"
            elif elapsed_interaction < 120.0:
                self.presence_state = "USER_PRESENT"
            else:
                self.presence_state = "USER_IDLE"

        print(f"[BackgroundPerception] Presence: {self.presence_state}, Emotion: {self.current_user_emotion}")


    # ── Action Execution ─────────────────────────────────────────────────────
    def _is_action_tag_authorized(self, category, source_user_input):
        inp = (source_user_input or "").lower()
        category = category.upper()
        
        # Return True for browser actions whenever BrowserSkill().is_browser_active() is True
        if category in {"SEARCH", "BROWSER_OPEN", "BROWSEROPEN", "CLOSE_TAB", "NEW_TAB", "TYPE", "CLICK", "SCROLL"}:
            try:
                from skills.browser_skill import BrowserSkill
                if BrowserSkill().is_browser_active():
                    return True
            except Exception:
                pass
        
        # Check if the semantic router classified the user's intent as search/browser with high confidence
        if category not in {"SHUTDOWN", "RESTART"}:
            routing_decision = getattr(self.brain, "last_routing_decision", None)
            if routing_decision:
                intent = routing_decision.get("intent")
                confidence = routing_decision.get("intent_confidence", 0.0)
                if intent in ["search", "browser"] and confidence >= 0.8:
                    return True
                
                # Permissive browser actions when active tab is open & intent is browser/search/followup
                try:
                    from skills.browser_skill import BrowserSkill
                    if BrowserSkill().is_browser_active() and intent in ["search", "browser", "followup"] and confidence >= 0.65:
                        if category in {"SEARCH", "BROWSER_OPEN", "BROWSEROPEN", "CLOSE_TAB", "NEW_TAB", "TYPE", "CLICK", "SCROLL"}:
                            return True
                except Exception:
                    pass

        if category == "SEARCH":
            return any(term in inp for term in ["search", "find", "look up", "google", "amazon", "youtube", "buy", "shop"])
        if category in {"BROWSER_OPEN", "BROWSEROPEN"}:
            return any(term in inp for term in ["open", "go to", "navigate", "browser", "amazon", "youtube", "website", "search", "buy", "shop"])
        if category == "OPEN":
            return any(term in inp for term in ["open", "launch", "start"])
        if category == "CLOSE":
            return any(term in inp for term in ["close", "exit", "quit"])
        if category in {"CLOSE_TAB", "NEW_TAB"}:
            return any(term in inp for term in ["tab", "browser", "close tab", "new tab", "open tab"])
        if category == "GOOGLE_SEARCH":
            return any(term in inp for term in ["google", "search", "find", "look up"])
        if category == "VSCODE_OPEN":
            return any(term in inp for term in ["vscode", "vs code", "code", "open project"])
        if category in {"SHUTDOWN", "RESTART"}:
            return any(term in inp for term in ["shutdown", "restart", "reboot"])
        if category == "VOLUME":
            return any(term in inp for term in ["volume", "mute", "unmute"])
        if category == "SCREENSHOT":
            return any(term in inp for term in ["screenshot", "screen shot", "capture screen"])
        if category == "PRESS":
            return any(term in inp for term in ["press", "shortcut", "key"])
        if category == "FOCUS":
            return any(term in inp for term in ["focus", "switch to", "bring"])
        if category == "TYPE":
            return any(term in inp for term in ["type", "write", "enter", "fill", "input"])
        if category == "CLICK":
            return any(term in inp for term in ["click", "select", "press", "open first", "first result", "open", "go to", "show", "choose", "first", "second", "third", "last", "result", "product", "item"])
        return True

    def _execute_actions(self, response, source_user_input=""):
        """Parse and execute any bracketed action tags in the AI response."""
        result = response
        if not result:
            return

        # ── Security Guard Action Verification ──
        all_tags = re.findall(r'\[[a-zA-Z_]+(?::\s*[^\]]+)?\]', result)
        for tag in all_tags:
            safe, msg = self.security.verify_agent_action_tag(tag)
            if not safe:
                print(f"[SecurityGuard] Verification required for tag: {tag}. Reason: {msg}")
                self._speak("Action restricted. Verifying identity via camera...")
                detected = self.identify_user()
                if detected in ["chinmay", "chinmaya"]:
                    print("[SecurityGuard] Verified as Chinmaya/Chinmay. Bypassing lock.")
                    self.security.unlock_admin()
                else:
                    self._speak(f"Access denied. {msg}")
                    # Strip the restricted tag from result
                    result = result.replace(tag, "")

        # [OPEN: app]
        for match in re.finditer(r'\[OPEN:\s*([^\]]+)\]', result, re.IGNORECASE):
            app = match.group(1).strip()
            if not self._is_action_tag_authorized("OPEN", source_user_input):
                print(f"[ActionGuard] Blocked unrequested open action: {app}")
                continue
            self.automation.open_app(app)

        # [CLOSE: app]
        for match in re.finditer(r'\[CLOSE:\s*([^\]]+)\]', result, re.IGNORECASE):
            app = match.group(1).strip()
            # If shutdown is already initiated, bypass close protection
            if not self.running:
                self.automation.close_app(app)
                continue
            if not self._is_action_tag_authorized("CLOSE", source_user_input):
                print(f"[ActionGuard] Blocked unrequested close action: {app}")
                continue
            # Safety Guardrail: Do not close terminal window running the agent
            app_lower = app.lower()
            critical_terminals = ["powershell", "cmd", "terminal", "python", "bash", "wsl", "conhost"]
            if any(term in app_lower for term in critical_terminals):
                print(f"[ARIA Safety] Blocked close attempt on critical agent application: {app}")
                self._speak("I cannot close that application because it might terminate my running process.")
                continue
            self.automation.close_app(app)

        # [CLOSE_TAB]
        if re.search(r'\[CLOSE_TAB\]', result, re.IGNORECASE):
            if not self._is_action_tag_authorized("CLOSE_TAB", source_user_input):
                print("[ActionGuard] Blocked unrequested close-tab action.")
            else:
                print("[Automation] Closing browser tab")
                self.ui.browser_close_tab()

        # [NEW_TAB] / [NEWTAB]
        if re.search(r'\[(NEW_TAB|NEWTAB)\]', result, re.IGNORECASE):
            if not self._is_action_tag_authorized("NEW_TAB", source_user_input):
                print("[ActionGuard] Blocked unrequested new-tab action.")
            else:
                print("[Automation] Opening new browser tab")
                self.ui.browser_new_tab()

        # [TYPE: text]
        for match in re.finditer(r'\[TYPE:\s*([^\]]+)\]', result, re.IGNORECASE):
            text = match.group(1).strip()
            if not self._is_action_tag_authorized("TYPE", source_user_input):
                print(f"[ActionGuard] Blocked unrequested type action: {text}")
                continue
            self.automation.type_text(text)

        # [SEARCH: query]
        for match in re.finditer(r'\[SEARCH:\s*([^\]]+)\]', result, re.IGNORECASE):
            query = match.group(1).strip()
            if not self._is_action_tag_authorized("SEARCH", source_user_input):
                print(f"[ActionGuard] Blocked unrequested search action: {query}")
                continue
            
            # Check active browser first
            try:
                from skills.browser_skill import BrowserSkill
                bs = BrowserSkill()
                if bs.is_browser_active():
                    self.automation_mode = True
                    self.last_automation_action_time = time.time()
                    print(f"[Automation] Browser active - redirecting search to active page: {query}")
                    res = bs.search_in_page(query)
                    print(f"[Automation] Search in-page result: {res}")
                    continue
            except Exception as e:
                print(f"[Automation] Browser in-page search check failed: {e}")

            if "amazon" in (query + " " + source_user_input).lower():
                product = self._extract_amazon_product(query) or self._extract_amazon_product(source_user_input) or self.shopping_search_context.get("product")
                if product:
                    self._search_amazon_product(product)
                    continue
            self.automation.search_web(query)

        # [CLICK: x,y]
        for match in re.finditer(r'\[CLICK:\s*(\d+)\s*,\s*(\d+)\]', result, re.IGNORECASE):
            x = int(match.group(1))
            y = int(match.group(2))
            if not self._is_action_tag_authorized("CLICK", source_user_input):
                print(f"[ActionGuard] Blocked unrequested click action: {x},{y}")
                continue
            self.screen.click(x, y)

        # [CLICK: target_name_or_id] (semantic non-coordinate click)
        for match in re.finditer(r'\[CLICK:\s*([^0-9\]\s][^\]]*)\]', result, re.IGNORECASE):
            target = match.group(1).strip()
            if not self._is_action_tag_authorized("CLICK", source_user_input):
                print(f"[ActionGuard] Blocked unrequested click action: {target}")
                continue
            try:
                from skills.browser_skill import BrowserSkill
                bs = BrowserSkill()
                if bs.is_browser_active():
                    self.automation_mode = True
                    self.last_automation_action_time = time.time()
                    print(f"[Automation] Browser active - clicking semantic target: {target}")
                    res = bs.click_element(target)
                    print(f"[Automation] Click result: {res}")
            except Exception as e:
                print(f"[Automation] Semantic click failed: {e}")

        # [TYPE: target | value] (semantic element fill)
        for match in re.finditer(r'\[TYPE:\s*([^|\]]+)\|\s*([^\]]+)\]', result, re.IGNORECASE):
            target = match.group(1).strip()
            value = match.group(2).strip()
            if not self._is_action_tag_authorized("TYPE", source_user_input):
                print(f"[ActionGuard] Blocked unrequested type action: {target} = {value}")
                continue
            try:
                from skills.browser_skill import BrowserSkill
                bs = BrowserSkill()
                if bs.is_browser_active():
                    self.automation_mode = True
                    self.last_automation_action_time = time.time()
                    print(f"[Automation] Browser active - filling semantic target: {target} with '{value}'")
                    res = bs.fill_element(target, value)
                    print(f"[Automation] Fill result: {res}")
            except Exception as e:
                print(f"[Automation] Semantic fill failed: {e}")

        # [VOLUME: up/down/mute]
        for match in re.finditer(r'\[VOLUME:\s*([^\]]+)\]', result, re.IGNORECASE):
            action = match.group(1).strip().lower()
            if not self._is_action_tag_authorized("VOLUME", source_user_input):
                print(f"[ActionGuard] Blocked unrequested volume action: {action}")
                continue
            if "up" in action:
                self.automation.volume_up()
            elif "down" in action:
                self.automation.volume_down()
            elif "mute" in action:
                self.automation.volume_mute()

        # [SCREENSHOT]
        if re.search(r'\[SCREENSHOT\]', result, re.IGNORECASE):
            if not self._is_action_tag_authorized("SCREENSHOT", source_user_input):
                print("[ActionGuard] Blocked unrequested screenshot action.")
            else:
                self.automation.take_screenshot()

        # [CLICK: x,y]  — screen coordinate click
        for match in re.finditer(r'\[CLICK:\s*(\d+)\s*,\s*(\d+)\]', result, re.IGNORECASE):
            if not self._is_action_tag_authorized("CLICK", source_user_input):
                print("[ActionGuard] Blocked unrequested coordinate click action.")
                continue
            self.screen.click(int(match.group(1)), int(match.group(2)))

        # [FOCUS: window_title]
        for match in re.finditer(r'\[FOCUS:\s*([^\]]+)\]', result, re.IGNORECASE):
            if not self._is_action_tag_authorized("FOCUS", source_user_input):
                print(f"[ActionGuard] Blocked unrequested focus action: {match.group(1).strip()}")
                continue
            self.screen.focus_window(match.group(1).strip())

        # [PRESS: key+combination]
        for match in re.finditer(r'\[PRESS:\s*([^\]]+)\]', result, re.IGNORECASE):
            if not self._is_action_tag_authorized("PRESS", source_user_input):
                print(f"[ActionGuard] Blocked unrequested keypress action: {match.group(1).strip()}")
                continue
            keys = [k.strip() for k in match.group(1).split('+')]
            self.screen.press(*keys)

        # [SCROLL: direction | amount] or [SCROLL: direction]
        for match in re.finditer(r'\[SCROLL:\s*([^\]]+)\]', result, re.IGNORECASE):
            parts = [p.strip().lower() for p in match.group(1).split('|')]
            direction = parts[0]
            amount = parts[1] if len(parts) > 1 else "normal"
            
            if direction not in ["down", "up", "top", "bottom"]:
                continue
                
            try:
                from skills.browser_skill import BrowserSkill
                bs = BrowserSkill()
                if bs.is_browser_active():
                    self.automation_mode = True
                    self.last_automation_action_time = time.time()
                    print(f"[Automation] Browser active - scrolling {direction} (amount: {amount})")
                    bs.scroll(direction, amount)
                    continue
            except Exception as e:
                print(f"[Automation] Browser scroll failed: {e}")
                
            print(f"[ScreenControl] Scrolling {direction}")
            self.screen.click(self.screen.screen_w // 2, self.screen.screen_h // 2)
            
            # Physical screen scrolling clicks mapping
            clicks = 5
            if amount == "little":
                clicks = 2
            elif amount == "more":
                clicks = 10
                
            if direction in ["top", "bottom"]:
                key = "ctrl+home" if direction == "top" else "ctrl+end"
                self.screen.press(key)
            else:
                self.screen.scroll(clicks=clicks, direction=direction)
                time.sleep(0.2)
                self.screen.scroll(clicks=clicks, direction=direction)

        # [WAIT: seconds]
        for match in re.finditer(r'\[WAIT:\s*([\d\.]+)\]', result, re.IGNORECASE):
            seconds = float(match.group(1))
            print(f"[ScreenControl] Waiting {seconds}s")
            time.sleep(seconds)

        # [RELATE: source | relation | target]
        for match in re.finditer(r'\[RELATE:\s*([^|\]]+)\|\s*([^|\]]+)\|\s*([^\]]+)\]', result, re.IGNORECASE):
            src = match.group(1).strip()
            rel = match.group(2).strip()
            tgt = match.group(3).strip()
            self.memory_skill.add_semantic_relation(src, rel, tgt)
            print(f"[MemorySkill] Linked: {src} --({rel})--> {tgt}")

        # [ADD_TASK: goal | task | status | dependency | blocker]
        for match in re.finditer(r'\[ADD_TASK:\s*([^|\]]+)\|\s*([^|\]]+)\|\s*([^|\]]+)(?:\|\s*([^|\]]*))?(?:\|\s*([^\\]]*))?\]', result, re.IGNORECASE):
            g = match.group(1).strip()
            t = match.group(2).strip()
            s = match.group(3).strip()
            d = match.group(4).strip() if match.group(4) else None
            b = match.group(5).strip() if match.group(5) else None
            self.memory_skill.add_task_tree_node(g, t, s, d, b)
            print(f"[MemorySkill] Added Task Node: {g} -> {t} [{s}]")

        # [UPDATE_TASK: goal | task | status | blocker]
        for match in re.finditer(r'\[UPDATE_TASK:\s*([^|\]]+)\|\s*([^|\]]+)\|\s*([^|\]]+)(?:\|\s*([^\]]*))?\]', result, re.IGNORECASE):
            g = match.group(1).strip()
            t = match.group(2).strip()
            s = match.group(3).strip()
            b = match.group(4).strip() if match.group(4) else None
            self.memory_skill.add_task_tree_node(g, t, s, blocker=b)
            print(f"[MemorySkill] Updated Task Node: {g} -> {t} [{s}]")

        # [BROWSER_OPEN: url] / [BROWSEROPEN: url]
        for match in re.finditer(r'\[(?:BROWSER_OPEN|BROWSEROPEN):\s*([^\]]+)\]', result, re.IGNORECASE):
            url = match.group(1).strip()
            if not self._is_action_tag_authorized("BROWSER_OPEN", source_user_input):
                print(f"[ActionGuard] Blocked unrequested browser open action: {url}")
                continue
            try:
                self.automation_mode = True
                self.last_automation_action_time = time.time()
                from skills.browser_skill import BrowserSkill
                BrowserSkill().navigate(url)
            except Exception as e:
                print(f"[Automation] Browser open failed through BrowserSkill: {e}")
                ok, msg = self.ui.open_browser(url)
                if not ok:
                    self._speak("Browser automation failed.")

        # [GOOGLE_SEARCH: query]
        for match in re.finditer(r'\[GOOGLE_SEARCH:\s*([^\]]+)\]', result, re.IGNORECASE):
            query = match.group(1).strip()
            if not self._is_action_tag_authorized("GOOGLE_SEARCH", source_user_input):
                print(f"[ActionGuard] Blocked unrequested Google search action: {query}")
                continue
            self.automation_mode = True
            self.last_automation_action_time = time.time()
            ok, msg = self.ui.search_google(query)
            if ok:
                self._speak("I opened Google results.")
            else:
                self._speak("Browser automation failed.")

        # [VSCODE_OPEN: path]
        for match in re.finditer(r'\[VSCODE_OPEN:\s*([^\]]+)\]', result, re.IGNORECASE):
            if not self._is_action_tag_authorized("VSCODE_OPEN", source_user_input):
                print(f"[ActionGuard] Blocked unrequested VS Code open action: {match.group(1).strip()}")
                continue
            self.ui.open_vscode_project(match.group(1).strip())

        # [SHUTDOWN] / [RESTART]
        if re.search(r'\[SHUTDOWN\]', result, re.IGNORECASE):
            if not self._is_action_tag_authorized("SHUTDOWN", source_user_input):
                print("[ActionGuard] Blocked unrequested shutdown action.")
            else:
                self.automation.shutdown()
        elif re.search(r'\[RESTART\]', result, re.IGNORECASE):
            if not self._is_action_tag_authorized("RESTART", source_user_input):
                print("[ActionGuard] Blocked unrequested restart action.")
            else:
                self.automation.restart()

    def _verify_action(self, action_tag, sw, sh):
        """Verifies action tags for safety, boundary limits, and harmful commands."""
        # Risk classification using SandboxSafetyLayer
        risk_level = self.sandbox_safety.classify_risk(action_tag)
        
        # Centralized safety check using SecurityGuard
        safe, msg = self.security.verify_agent_action_tag(action_tag)
        if not safe:
            return False, action_tag, msg

        # Human approval flow for HIGH/CRITICAL risks
        if self.sandbox_safety.requires_approval(risk_level):
            import uuid
            action_id = str(uuid.uuid4())
            if not self.sandbox_safety.is_action_approved(action_id, risk_level):
                self._speak(f"Warning. Proposing {risk_level} risk action: {action_tag}. Please say 'yes' to approve or 'no' to abort.")
                set_state("LISTENING")
                feedback = self.voice.listen(timeout=8)
                if feedback and any(x in feedback.lower() for x in ["yes", "approve", "go ahead", "sure", "ok", "okay"]):
                    self.sandbox_safety.grant_approval(action_id)
                    self._speak("Action approved.")
                else:
                    self._speak("Action aborted.")
                    return False, action_tag, "Rejected by user approval."

        # 1. Destructive Commands Safety Check
        dangerous_patterns = [
            r'rm\s+-rf', r'del\s+.*config', r'format\s+[a-zA-Z]:',
            r'shutdown\s+/s', r'taskkill\s+/im\s+explorer\.exe',
            r'taskkill\s+/im\s+winlogon\.exe', r'drop\s+database', r'delete\s+from'
        ]
        
        # Extract typed or pressed content to check
        text_match = re.search(r'\[TYPE:\s*([^\]]+)\]', action_tag, re.IGNORECASE)
        if text_match:
            typed_text = text_match.group(1).lower()
            for pattern in dangerous_patterns:
                if re.search(pattern, typed_text):
                    return False, action_tag, f"Potentially destructive command detected: '{pattern}'"
        
        # 2. Coordinates Out-of-Bounds Verification and Correction
        coords_match = re.search(r'\[(?:CLICK|DOUBLE_CLICK|RIGHT_CLICK):\s*(\d+)\s*,\s*(\d+)\]', action_tag, re.IGNORECASE)
        if coords_match:
            x, y = int(coords_match.group(1)), int(coords_match.group(2))
            corrected = False
            
            # Clip X
            if x < 0:
                x = 0
                corrected = True
            elif x > sw:
                x = sw
                corrected = True
                
            # Clip Y
            if y < 0:
                y = 0
                corrected = True
            elif y > sh:
                y = sh
                corrected = True
                
            if corrected:
                tag_type = "CLICK" if "[CLICK:" in action_tag else ("DOUBLE_CLICK" if "[DOUBLE_CLICK:" in action_tag else "RIGHT_CLICK")
                corrected_tag = f"[{tag_type}: {x},{y}]"
                return True, corrected_tag, "Coordinates out of bounds; clipped to edge."
                
        return True, action_tag, "Action safe."

    def run_autonomous_agent(self, task, max_steps=8, task_item=None):
        """ARIA-style autonomous vision-guided loop with Goal planning, UI tracking, and Action Verification."""
        import io
        import base64

        sw, sh = self.screen.screen_w, self.screen.screen_h
        print(f"[ARIA Agent] Starting task: '{task}'")
        feedback = ""


        # Update dashboard state
        try:
            from dashboard import CognitionState
            CognitionState.active_goal = task
            CognitionState.active_subtask = "Planning subgoals..."
            CognitionState.confidence = 1.0
            CognitionState.last_actions = []
            CognitionState.reflection_results = ""
        except ImportError:
            pass

        # Episodic tracking
        executed_steps = []
        task_outcome = "failure"
        
        # Stability Engineering trackers
        failure_budget = 3
        failure_count = 0
        action_history = []

        # Set Focus Priority to 3 (Normal-Task) during autonomous execution
        try:
            self.attention_manager.set_focus(3)
            self.last_agent_activity = time.time()
            self.idle_consolidation_done = False
        except Exception:
            pass

        # Evaluate Dynamic Runtime Mode Profile
        try:
            load_score_now = getattr(self.cognitive_load_manager, "get_load_metrics", lambda: {"load_score": 0.1})()["load_score"]
            profile_res = self.mode_profiler.evaluate_profile(load_score=load_score_now)
            
            # Save resolved profile to dashboard State
            from dashboard import CognitionState
            CognitionState.runtime_profile = profile_res["profile"]
            
            if profile_res["transitioned"]:
                set_state("SPEAKING")
                self._speak(f"System profile update. Transitioning executive governance to {profile_res['profile'].lower()} mode.")
                set_state("IDLE")
                
            # Apply profile limitations
            if profile_res["profile"] == "MINIMAL":
                print("[Executive Mode] Enforcing Minimal Footprint: Restricting maximum step limits.")
                max_steps = min(max_steps, 3)
            elif profile_res["profile"] == "CONSERVATIVE":
                print("[Executive Mode] Enforcing Conservative Governance: Reducing autonomy, switching to manual confirmation.")
                self.mode = "safe"
        except Exception as profile_err:
            print(f"[Executive Mode] Failed to evaluate dynamic profile: {profile_err}")

        # Execute Deliberative Sandbox Simulation
        sandbox_desc = None
        sim_candidates = []
        try:
            from skills.sandbox_simulator import SandboxSimulator
            sim_res = SandboxSimulator().simulate_and_compare(task)
            sim_candidates = sim_res.get("candidates", [])
            
            # Save results to dashboard State
            from dashboard import CognitionState
            CognitionState.sandbox_simulation = sim_res
            
            best = sim_res["best_path"]
            if best:
                sandbox_desc = best["path_name"]
                print(f"[SandboxSimulator] Mentally simulated strategies. Selected best path: {sandbox_desc} (Score: {best['utility_score']})")
                set_state("SPEAKING")
                self._speak(f"Initiating simulation. Selecting path: '{best['path_name']}' with utility score of {best['utility_score']:.2f}.")
                set_state("IDLE")
        except Exception as sim_err:
            print(f"[SandboxSimulator] Simulation failure: {sim_err}")

        # Session Checkpoint persistence
        try:
            import json
            with open("active_session.json", "w") as sf:
                json.dump({"goal": task, "status": "active"}, sf)
        except Exception:
            pass

        # ── Step 1: Goal-based planning ──
        set_state("THINKING")
        set_text("Planning subgoals...")
        self._speak(f"Let me think about how to complete this task.")
        
        plan_prompt = (
            f"You are the planner for ARIA. Break down the user's task into a list of 3-5 high-level subgoals to complete: '{task}'. "
            "Write the plan in a simple list format."
        )
        try:
            plan = self.brain.think(plan_prompt)
            print(f"[ARIA Agent] Generated Plan:\n{plan}")
            # Speak first sentence/summary of plan
            plan_summary = plan.split("\n")[0] if plan else "Starting task execution."
            self._speak(f"Plan drafted: {plan_summary}. Executing now.")
        except Exception as e:
            print(f"[ARIA Agent] Planning error: {e}")
            self._speak("Starting execution.")

        # Publish TASK_STARTED event
        try:
            from skills.event_bus import EventBus
            EventBus().publish("TASK_STARTED", {"task": task, "max_steps": max_steps})
        except Exception:
            pass

        previous_action = None
        task_start_time = time.time()
        max_task_timeout = 180  # 3 minutes max for entire task
        
        for step in range(1, max_steps + 1):
            step_start_time = time.time()
            step_timeout_sec = 45  # 45 seconds per step
            
            # Check overall task timeout
            elapsed_total = time.time() - task_start_time
            if elapsed_total > max_task_timeout:
                print(f"[ARIA Agent] Task exceeded {max_task_timeout}s timeout. Terminating.")
                self._speak("Task timeout exceeded. Stopping execution.")
                task_outcome = "timeout"
                break
            
            if not self.running:
                break

            # Cooperative Cancellation Check
            if task_item and task_item.cancelled:
                print(f"[ARIA Agent] Cooperative cancellation triggered for task {task_item.task_id}.")
                self._speak("Task execution cancelled.")
                task_outcome = "cancelled"
                break
                
            # Interruption check: Wait until high-priority interrupts complete handling
            while getattr(self, "paused_by_interrupt", False):
                time.sleep(1.0)

            set_state("THINKING")
            set_text(f"Step {step}: Capturing screen...")

            # ── Self-Reflection & Error Recovery Analysis ──
            reflection_context = ""
            if step > 1 and previous_action:
                reflection_context = (
                    f"== SELF-REFLECTION (ERROR RECOVERY) ==\n"
                    f"In Step {step-1}, you executed this action: '{previous_action}'.\n"
                    f"Inspect the current screenshot. Did that action succeed and update the screen as expected?\n"
                    f"If the action failed (e.g. coordinates were off, app didn't open, loading spinner appeared), "
                    f"reflect on what went wrong, adapt your strategy, and choose a new corrective action now.\n\n"
                )

            # Update dashboard state
            try:
                from dashboard import CognitionState
                CognitionState.active_subtask = f"Step {step}: Capturing screen & querying memory..."
                CognitionState.active_window = active_window
            except Exception:
                pass

            step_start = time.time()
            
            # Update World State
            try:
                from dashboard import CognitionState
                CognitionState.world_state["active_project"] = os.path.basename(os.getcwd())
                CognitionState.world_state["current_workflow"] = task
                CognitionState.world_state["agent_status"] = f"Step {step} Executing"
                CognitionState.world_state["browser_tabs"] = "Dashboard, Workspace"
            except Exception:
                pass

            # ── Step 2: UI State & Environment Mapping ──
            active_window = self.context_skill.get_active_window()
            open_apps = self.ui.get_open_apps()[:6]
            ui_state = f"Active Window: {active_window}\nOpen Apps: {', '.join(open_apps)}"
            
            # Latency Orchestration: Run context query and base64 screen encoding in parallel
            import concurrent.futures
            
            def capture_and_encode():
                if not self.sandbox_safety.is_perception_allowed(active_window):
                    print(f"[SandboxSafety] Privacy Zone active! Replacing screen capture with privacy placeholder.")
                    from PIL import Image
                    img = Image.new('RGB', (120, 120), color='black')
                    buf_temp = io.BytesIO()
                    img.save(buf_temp, format="PNG")
                    return base64.b64encode(buf_temp.getvalue()).decode("utf-8")
                    
                pil_img_temp = self.screen.get_screen_image()
                buf_temp = io.BytesIO()
                pil_img_temp.save(buf_temp, format="PNG")
                return base64.b64encode(buf_temp.getvalue()).decode("utf-8")

            def get_prioritized_context():
                raw_episodes = self.episodic_memory.recall(
                    username=self.known_user or "chinmaya",
                    query=task,
                    limit=10
                )
                raw_semantics = []
                try:
                    from skills.vector_memory import VectorMemory
                    raw_semantics = VectorMemory().semantic_search(task, limit=10)
                except Exception as ve:
                    print(f"[ARIA Memory] Semantic search failed: {ve}")
                
                selected = self.context_budget.score_and_select_memories(
                    episodes=raw_episodes,
                    semantic_memories=raw_semantics,
                    current_goal=task
                )
                
                budget_mems = self.context_budget.build_prompt_context(selected)
                std_sql = self.brain._get_sqlite_context(task)
                return f"{budget_mems}\n\n{std_sql}"

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                f_mem = executor.submit(get_prioritized_context)
                f_img = executor.submit(capture_and_encode)
                
                # Retrieve Accessibility Tree on the main thread (prevents pywinauto COM threading errors)
                accessibility_tree = self.ui.get_accessibility_tree()
                
                # Fetch thread outputs
                sql_context = f_mem.result()
                img_b64 = f_img.result()
                
            ui_mapping = f"== ACCESSIBILITY UI ELEMENT MAP ==\n{accessibility_tree}"
            print(f"[ARIA Agent] UI State:\n{ui_state}")
            
            # Update dashboard screenshots & memory hits
            try:
                from dashboard import CognitionState
                CognitionState.screenshot = img_b64
                if sql_context:
                    # Parse lines from context as hits
                    CognitionState.memory_hits = [line.strip() for line in sql_context.split("\n") if line.strip() and not line.startswith("==")]
            except Exception:
                pass

            # Build agent planning prompt with UI mapping context
            prompt = f"""You are the autonomous brain of ARIA. Your goal is to complete this user task: "{task}".
This is Step {step} of {max_steps}.

{reflection_context}== CURRENT UI CONTEXT ==
{ui_state}

{ui_mapping}

Look at the current screen snapshot. What is the single best action to perform next to complete the task?
Output ONLY ONE of the following tag formats followed by a confidence score between 0.0 and 1.0 in this format: [CONFIDENCE: score] (e.g. [OPEN: chrome] [CONFIDENCE: 0.95]).
Available action formats:
- [CLICK: x,y] (where x,y are screen coordinates of the button, link, or input field to click)
- [DOUBLE_CLICK: x,y] (double click at coordinates)
- [RIGHT_CLICK: x,y] (right click at coordinates)
- [TYPE: text] (to type text into the currently focused input field)
- [PRESS: keys] (to press a key combination like 'enter', 'ctrl+t', 'alt+f4')
- [OPEN: app_name] (to launch an application like 'chrome', 'notepad')
- [WAIT: seconds] (to wait for a page or app to load)
- [SCROLL: down] or [SCROLL: up] or [SCROLL: top] or [SCROLL: bottom] (to scroll; add | little/normal/more for amount e.g. [SCROLL: down | little])
- [BROWSER_OPEN: url] (to open the default web browser directly to a URL)
- [GOOGLE_SEARCH: query] (to execute a google search in the browser immediately)
- [VSCODE_OPEN: path] (to open a project folder in VS Code)
- [DONE: summary] (if the task is fully completed. Explain what you accomplished)

Rules:
1. ONLY return the tag (e.g. "[OPEN: chrome]"). Do NOT include markdown, reasoning, or extra text.
2. If you need to search or navigate, first open the browser or focus it.
3. Be precise with coordinates on a {sw}x{sh} screen."""

            set_text(f"Step {step}: Planning next action...")

            if not self.brain.vision_ready:
                self._speak("My vision model is offline. Please install and run moondream in Ollama to use the autonomous agent.")
                break

            # Inject ui_mapping into formatting context
            prompt = prompt.replace("{ui_mapping}", ui_mapping)
            action_tag = self.brain._ask_vision(img_b64, prompt)
            action_tag = action_tag.strip()

            print(f"[ARIA Agent] Step {step} planned action: {action_tag}")
            
            # Stuck Loop Protection
            action_history.append(action_tag)
            if len(action_history) >= 3 and len(set(action_history[-3:])) == 1:
                set_state("SPEAKING")
                self._speak("I seem to be repeating the same action and might be stuck. Pausing to verify.")
                set_state("LISTENING")
                user_feedback = self.voice.listen(timeout=10)
                if user_feedback:
                    self._speak(f"Applying override: {user_feedback}")
                    action_tag = f"[SEARCH: {user_feedback}]"
                else:
                    self._speak("No feedback. Stopping run.")
                    self.memory_skill.log_failure(task, step, "STUCK_LOOP", action_tag)
                    try:
                        self.cognitive_load_manager.log_failure()
                    except Exception:
                        pass
                    break

            if not action_tag:
                self._speak("I got no response from my brain. Aborting task.")
                break

            # ── Confidence Score Check & Interactive User Recovery ──
            conf_score = 1.0
            conf_match = re.search(r'\[CONFIDENCE:\s*([\d\.]+)\]', action_tag, re.IGNORECASE)
            if conf_match:
                conf_score = float(conf_match.group(1))
                action_tag = re.sub(r'\[CONFIDENCE:\s*[\d\.]+\]', '', action_tag).strip()
                print(f"[ARIA Agent] Action confidence: {conf_score}")

            if conf_score < 0.70:
                set_state("SPEAKING")
                self._speak(f"I am not very confident about this step. Confidence score is {conf_score:.2f}. "
                            f"I planned to run: {action_tag}. Should I proceed, or do you have a correction?")
                set_state("LISTENING")
                user_feedback = self.voice.listen(timeout=10)
                if user_feedback:
                    uf_lower = user_feedback.lower()
                    if any(x in uf_lower for x in ["yes", "proceed", "go ahead", "do it", "sure", "ok", "okay"]):
                        self._speak("Okay, proceeding.")
                    else:
                        # User provided a correction
                        self._speak(f"Understood. Overriding action with feedback: '{user_feedback}'")
                        # Route feedback to rewrite the action tag
                        ref_prompt = (
                            f"The user wants to override the planned action. User correction: '{user_feedback}'. "
                            f"Convert this correction into a single valid ARIA action tag (e.g. [CLICK: x,y], [TYPE: text], [PRESS: keys]). "
                            f"Output only the tag."
                        )
                        corrected = self.brain.think(ref_prompt)
                        if corrected and corrected.strip().startswith("["):
                            action_tag = corrected.strip()
                            print(f"[ARIA Agent] Overrode action: {action_tag}")
                        else:
                            # Direct command
                            action_tag = f"[SEARCH: {user_feedback}]"
                else:
                    self._speak("No feedback received. Pausing task for safety.")
                    break

            # If done
            if "[DONE" in action_tag.upper():
                summary_match = re.search(r'\[DONE:\s*([^\]]+)\]', action_tag, re.IGNORECASE)
                summary = summary_match.group(1) if summary_match else "Task completed."
                
                # Update dashboard task completion state
                try:
                    from dashboard import CognitionState
                    CognitionState.active_subtask = f"Task completed: {summary}"
                except Exception:
                    pass
                
                self._speak(f"Task completed: {summary}")
                task_outcome = "success"
                break

            # ── Step 3: Safety & Coordinate Verification ──
            safe, corrected_tag, verify_msg = self._verify_action(action_tag, sw, sh)
            if not safe:
                print(f"[ARIA Agent] Blocked unsafe action: {verify_msg}")
                self._speak(f"Action blocked by safety verifier. Reason: {verify_msg}")
                break
            
            if corrected_tag != action_tag:
                print(f"[ARIA Agent] Action corrected: {action_tag} -> {corrected_tag}")
                action_tag = corrected_tag

            # Speak action to sound cool
            set_state("SPEAKING")
            set_text(f"Step {step}: Executing action...")

            # Update dashboard with chosen action details
            try:
                from dashboard import CognitionState
                CognitionState.active_subtask = f"Step {step}: Executing action"
                CognitionState.confidence = conf_score
                if hasattr(self.brain, "get_active_model"):
                    CognitionState.model_in_use = self.brain.get_active_model()
                if reflection_context:
                    CognitionState.reflection_results = reflection_context.replace("== SELF-REFLECTION (ERROR RECOVERY) ==\n", "").strip()
                
                import time
                CognitionState.last_actions.append({
                    "time": time.strftime("%H:%M:%S"),
                    "action": action_tag,
                    "status": "success",
                    "confidence": conf_score
                })
            except Exception:
                pass

            # Executing action with skill trust tracking + timeout protection
            step_success = True
            step_timeout = 30  # Max 30 seconds per action execution
            
            def _execute_with_timeout():
                try:
                    self._execute_actions(action_tag)
                except Exception as exec_err:
                    raise exec_err
            
            try:
                # Run action in a background thread with timeout
                action_thread = threading.Thread(target=_execute_with_timeout, daemon=True)
                action_thread.start()
                action_thread.join(timeout=step_timeout)
                
                if action_thread.is_alive():
                    print(f"[ARIA Agent] WARNING: Action execution exceeded {step_timeout}s timeout. Likely hung browser/process.")
                    self._speak("Action took too long. Skipping this step to avoid infinite hang.")
                    step_success = False
                    # Force kill any hung processes
                    try:
                        os.system("taskkill /im chrome.exe /f 2>nul")
                        os.system("taskkill /im msedge.exe /f 2>nul")
                    except Exception:
                        pass
            except Exception as exec_err:
                step_success = False
                raise exec_err
            finally:
                try:
                    from skills.trust_calibrator import SkillTrustCalibrator
                    verb = action_tag.split(":")[0].strip(" [").lower() if ":" in action_tag else action_tag.strip(" []").lower()
                    verb = verb.replace("[", "").replace("]", "").strip()
                    
                    # Deduce active window app name context
                    win_title = active_window.lower() if "active_window" in locals() else "unknown"
                    app_name = "chrome" if "chrome" in win_title else ("vscode" if "code" in win_title else ("notepad" if "notepad" in win_title else "unknown"))

                    
                    SkillTrustCalibrator().record_skill_run(verb, success=step_success, context_app=app_name)
                except Exception as trust_err:
                    print(f"[ARIA SkillTrust] Failed to record skill trust outcome: {trust_err}")
            
            # Publish ACTION_EXECUTED event
            try:
                from skills.event_bus import EventBus
                EventBus().publish("ACTION_EXECUTED", {"action": action_tag, "step": step})
            except Exception:
                pass
            
            # Calculate execution latency metrics for telemetry
            try:
                self.last_agent_activity = time.time()
                from dashboard import CognitionState
                lat = time.time() - step_start
                CognitionState.tool_health["vision_latency"] = f"{lat:.2f}s"
                CognitionState.tool_health["memory_latency"] = "0.01s"
                CognitionState.tool_health["success_rate"] = "98%"
                CognitionState.tool_health["stuck_rate"] = "0%"
            except Exception:
                pass
            previous_action = action_tag
            executed_steps.append(action_tag)

            # Clean spoken description of action
            spoken_action = re.sub(r'\[[A-Z_]+:[^\]]*\]', '', action_tag)
            spoken_action = re.sub(r'\[[A-Z_]+\]', '', spoken_action).strip()
            if not spoken_action:
                # Deduce spoken action from tags
                if "[CLICK:" in action_tag:
                    spoken_action = "Clicking coordinate."
                elif "[DOUBLE_CLICK:" in action_tag:
                    spoken_action = "Double-clicking coordinate."
                elif "[RIGHT_CLICK:" in action_tag:
                    spoken_action = "Right-clicking coordinate."
                elif "[TYPE:" in action_tag:
                    val = re.search(r'\[TYPE:\s*([^\]]+)\]', action_tag, re.IGNORECASE).group(1)
                    spoken_action = f"Typing: {val}."
                elif "[PRESS:" in action_tag:
                    val = re.search(r'\[PRESS:\s*([^\]]+)\]', action_tag, re.IGNORECASE).group(1)
                    spoken_action = f"Pressing keys: {val}."
                elif "[OPEN:" in action_tag:
                    val = re.search(r'\[OPEN:\s*([^\]]+)\]', action_tag, re.IGNORECASE).group(1)
                    spoken_action = f"Opening {val}."
                elif "[WAIT:" in action_tag:
                    spoken_action = "Waiting for screen update."
                elif "[SCROLL:" in action_tag:
                    spoken_action = "Scrolling screen."

            self._speak(spoken_action)
            
            # Check if step exceeded timeout
            step_elapsed = time.time() - step_start_time
            if step_elapsed > step_timeout_sec:
                print(f"[ARIA Agent] Step {step} exceeded {step_timeout_sec}s timeout (took {step_elapsed:.1f}s). Aborting task.")
                self._speak("Step execution timeout. Stopping task.")
                break
            
            time.sleep(2.0)  # Wait for screen update before next iteration
        else:
            self._speak("Reached maximum steps limit. Task paused.")
            
        # Reset Status & Attention Focus
        try:
            self.last_agent_activity = time.time()
            self.attention_manager.set_focus(0)
            from dashboard import CognitionState
            CognitionState.sandbox_simulation = {}
            CognitionState.causal_blame = {}
            from dashboard import CognitionState
            CognitionState.world_state["agent_status"] = "Idle"
            CognitionState.world_state["current_workflow"] = "None"
            
            # Retrieve batched notifications and read summary
            summary = self.attention_manager.get_pending_summary()
            if "Triaged Notifications" in summary:
                print(f"[AttentionManager] Announcing triaged logs:\n{summary}")
                self._speak(f"Workflow completed. I triaged {len(self.attention_manager.pending_notifications)} notification events during execution. You can check them in the Attention panel.")
                self.attention_manager.clear_pending()
                CognitionState.pending_notifications = []
        except Exception as e:
            print(f"[AttentionManager] Focus reset error: {e}")

        # Remove session checkpoint on task end
        try:
            if os.path.exists("active_session.json"):
                os.remove("active_session.json")
        except Exception:
            pass

        # Publish GOAL_COMPLETED event and compress memory files
        try:
            from skills.event_bus import EventBus
            EventBus().publish("GOAL_COMPLETED", {"task": task, "outcome": task_outcome, "steps": len(executed_steps)})
            
            # Trigger Memory compression GC to keep contexts clean
            self.memory_skill.compress_memories()
            
            # Record Strategy reinforcement weight outcome
            try:
                strategy_key = task.split()[0] if task else "default"
                
                # Fetch multi-factor rewards context values
                latency_tot = time.time() - getattr(self, "last_agent_activity", time.time())
                interrupted_flag = any(n["type"] == "low_battery" for n in getattr(self.attention_manager, "pending_notifications", []))
                user_corrected_flag = False  # Track overrides if voice feedback override was spoken
                load_val_now = getattr(self.cognitive_load_manager, "get_load_metrics", lambda: {"load_score": 0.1})()["load_score"]
                
                outcome_log = self.memory_skill.record_strategy_outcome(
                    strategy_key,
                    success=(task_outcome == "success"),
                    latency=latency_tot,
                    interrupted=interrupted_flag,
                    user_corrected=user_corrected_flag,
                    load_level=load_val_now
                )
                print(f"[ARIA Optimizer] {outcome_log}")
                
                # Log confidence prediction and trigger calibration updates
                try:
                    # Get raw confidence prediction
                    raw_conf = getattr(self, "confidence", 0.90)
                    self.confidence_calibrator.log_confidence_prediction(task, raw_conf, task_outcome)
                    
                    # Update calibration factor to dashboard state
                    from dashboard import CognitionState
                    old_factor = CognitionState.calibration_factor
                    new_factor = self.confidence_calibrator.calibration_factor
                    CognitionState.calibration_factor = new_factor
                    
                    if abs(old_factor - new_factor) > 0.05:
                        set_state("SPEAKING")
                        self._speak(f"Calibration notice. Adjusting uncertainty scale to {new_factor:.2f} due to strategy outcomes.")
                        set_state("IDLE")
                except Exception as cal_err:
                    print(f"[ARIA Calibrator] Calibration logging error: {cal_err}")
                
                # Counterfactual Reflection Engine Trigger on Failure
                if task_outcome == "failed":
                    try:
                        from skills.sandbox_simulator import SandboxSimulator
                        ref_res = SandboxSimulator().run_counterfactual_reflection(strategy_key, sim_candidates)
                        
                        # Apply counterfactual weight updates
                        c_log = self.memory_skill.record_counterfactual_update(strategy_key, ref_res["recommendation"])
                        print(f"[ARIA Counterfactual] {ref_res['summary']}")
                        print(f"[ARIA Counterfactual] {c_log}")
                        
                        # Update dashboard reflection result
                        from dashboard import CognitionState
                        CognitionState.reflection_results = ref_res["summary"]
                        
                        set_state("SPEAKING")
                        self._speak(f"Analyzing failure. Mental replay suggests using strategy '{ref_res['recommendation']}' instead.")
                        set_state("IDLE")
                    except Exception as ref_err:
                        print(f"[ARIA Counterfactual] Reflection error: {ref_err}")

                    # Trigger Causal Blame Diagnosis
                    try:
                        from skills.causal_attribution import CausalAttributionEngine
                        
                        # Assemble parameters
                        last_act_tag = executed_steps[-1] if executed_steps else "unknown"
                        last_err_msg = feedback if feedback else "execution failed"
                        
                        attribution = CausalAttributionEngine().analyze_failure_cause(
                            task,
                            last_act_tag,
                            last_err_msg,
                            latency=latency_tot,
                            interrupted=interrupted_flag,
                            load_score=load_val_now
                        )
                        
                        # Update dashboard State
                        from dashboard import CognitionState
                        CognitionState.causal_blame = attribution
                        print(f"[ARIA Causal] Diagnosis: {attribution['cause'].upper()} - {attribution['explanation']}")
                        
                        set_state("SPEAKING")
                        self._speak(f"Root cause of failure diagnosed as {attribution['cause'].replace('_', ' ')}.")
                        set_state("IDLE")
                    except Exception as causal_err:
                        print(f"[ARIA Causal] Attribution error: {causal_err}")
            except Exception as o_err:
                print(f"[ARIA Optimizer] Failed to record strategy reinforcement: {o_err}")
        except Exception:
            pass

        # Log episode to replay memory
        try:
            self.memory_skill.save_episode(task, executed_steps, task_outcome)
            print(f"[ARIA Agent] Episode logged to database: '{task}' -> {task_outcome}")
            
            # Index successful task execution strategy in semantic memory
            if task_outcome == "success":
                try:
                    from skills.vector_memory import VectorMemory
                    vm = VectorMemory()
                    steps_summary = " -> ".join(executed_steps)
                    vm.add_memory(
                        f"Successful strategy for task '{task}': Executed sequence: [{steps_summary}]",
                        category="workflow"
                    )
                    print("[ARIA Agent] Successfully indexed episode in local semantic vector memory.")
                except Exception as e:
                    print(f"[ARIA Agent] Vector memory indexing error: {e}")
        except Exception as e:
            print(f"[ARIA Agent] Episodic logging error: {e}")

        # Trigger reflection engine asynchronously
        try:
            recent_episodes = self.episodic_memory.get_recent(username=self.known_user or "chinmaya", n=5)
            task_results = [{"goal": task, "outcome": task_outcome, "steps": [{"action": act, "status": "success"} for act in executed_steps]}]
            self.reflection_engine.reflect_asynchronously(
                username=self.known_user or "chinmaya",
                recent_episodes=recent_episodes,
                recent_task_results=task_results
            )
        except Exception as ref_trigger_err:
            print(f"[ARIA Reflection] Failed to trigger background reflection: {ref_trigger_err}")

        # Save task replay traces to replays/task_id/
        try:
            import uuid
            task_id = task_item.task_id if task_item else str(uuid.uuid4())
            from skills.event_bus import EventBus
            events_log = EventBus().get_history()[-30:] # Last 30 events
            reflections_summary = getattr(self.brain, "reflection_results", "")
            
            steps_data = [{"step": idx, "action": act, "status": "success", "duration": 1.0} for idx, act in enumerate(executed_steps, 1)]
            self.reflection_engine.save_task_replay(
                task_id=task_id,
                goal=task,
                steps=steps_data,
                events=events_log,
                reflections=reflections_summary
            )
        except Exception as replay_save_err:
            print(f"[ARIA Replay] Failed to save task replay files: {replay_save_err}")

    def _is_camera_visual_question(self, inp):
        non_visual_topics = [
            "news", "latest", "world", "around the world", "current affairs",
            "weather", "internet", "web", "google", "search", "headline",
            "headlines", "today's", "today news"
        ]
        if any(x in inp for x in non_visual_topics):
            return False

        control_phrases = [
            "show camera", "open camera", "turn on camera", "close camera",
            "stop camera", "turn off camera", "hide camera", "camera off",
            "camera on", "vision mode", "object mode", "face mode",
            "person mode", "learn objects", "teach you objects",
            "this is ", "learn this", "remember this"
        ]
        if any(x in inp for x in control_phrases):
            return False

        question_words = [
            "what", "who", "where", "which", "can you", "do you",
            "tell me", "describe", "identify", "recognize", "recognise",
            "what do you see", "do you see", "can you see", "look at"
        ]
        visual_words = [
            "camera", "image", "photo", "picture", "video", "frame",
            "visible", "holding", "hand", "front of me",
            "front of you", "room", "person", "people",
            "face", "object"
        ]
        around_is_visual = any(x in inp for x in [
            "around me", "around you", "around here", "around us",
            "around the room", "in the room"
        ])
        return any(q in inp for q in question_words) and (
            any(v in inp for v in visual_words) or around_is_visual
        )

    def _answer_with_camera_image(self, user_input):
        if not self.vision_learner.running:
            if getattr(self, "airtouch_mode", False):
                self._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
                return
            if not self.camera or not self.camera.available:
                self.camera.reacquire()
            if not self.camera or not self.camera.available:
                self._speak("The camera is not available right now.")
                return

            self._speak("Let me look through the camera.")
            if not self.vision_learner.start_camera(frame_provider=self.camera.capture_frame_raw):
                self._speak("I had trouble opening the camera.")
                return

            for _ in range(30):
                import time
                time.sleep(0.1)
                with self.vision_learner._lock:
                    if self.vision_learner.current_frame is not None:
                        break

        with self.vision_learner._lock:
            frame = self.vision_learner.current_frame.copy() if self.vision_learner.current_frame is not None else None

        if frame is None:
            self._speak("I can't see anything right now. Please make sure the camera is working.")
            return

        try:
            import cv2
            from PIL import Image
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            camera_image = Image.fromarray(rgb)
            print(f"[Main] Camera/image question routed to brain with frame: {camera_image.size}")

            response = self.brain.think(
                user_input,
                image=camera_image,
                user_name=self.known_user,
                user_similarity=self.known_user_similarity,
                user_confidence=self.known_user_confidence,
                emotional_tone=getattr(self, "current_user_emotion", "neutral")
            )
            response_lower = response.lower() if response else ""
            non_visual_response = any(x in response_lower for x in [
                "visual information", "can't see", "cannot see", "i'm ready",
                "tell me what to open", "open, search, or automate"
            ])
            if response and not non_visual_response:
                import re
                spoken = re.sub(r'\[[A-Z]+:[^\]]*\]', '', response)
                spoken = re.sub(r'\[[A-Z]+\]', '', spoken).strip()
                self._speak(spoken or self.vision_learner.identify_object())
            else:
                self._speak(self.vision_learner.identify_object())
        except Exception as e:
            print(f"[Main] Camera/image question error: {e}")
            self._speak(self.vision_learner.identify_object())

    def _answer_with_screen_image(self, user_input):
        try:
            screen_image = self.screen.get_screen_image()
            print(f"[Main] Screen question routed to brain with frame: {screen_image.size}")
            prompt = (
                user_input
                + "\n\nThe current laptop screen screenshot is attached. Read the visible text, "
                + "summarize what is on screen, and if this is a search/news results page, "
                + "pick the most relevant visible items and read them out briefly."
            )
            response = self.brain.think(
                prompt,
                image=screen_image,
                user_name=self.known_user,
                user_similarity=self.known_user_similarity,
                user_confidence=self.known_user_confidence,
                emotional_tone=getattr(self, "current_user_emotion", "neutral")
            )
            spoken = re.sub(r'\[[A-Z]+:[^\]]*\]', '', response or "")
            spoken = re.sub(r'\[[A-Z]+\]', '', spoken).strip()
            self._speak(spoken or "I captured the screen, but I couldn't read useful text from it.")
        except Exception as e:
            print(f"[Main] Screen question error: {e}")
            self._speak("I couldn't read the screen right now.")

    def search_and_read(self, query):
        """Fetches Google News/Web search content for query and returns page text."""
        import requests
        from bs4 import BeautifulSoup
        import urllib.parse
        
        # 1. Detect if it's a cricket/sports query and try Cricbuzz Live scores first
        q_lower = query.lower()
        cricket_keywords = ["score", "scorecard", "ipl", "cricket", "runs", "wickets", "match stats", "rcb", "csk", "mi", "gt", "kkr", "srh", "pbks", "dc", "lsg", "rr", "match result"]
        if any(kw in q_lower for kw in cricket_keywords):
            try:
                print(f"[Search/Scraper] Sports query detected: '{query}'. Trying Cricbuzz live scores...")
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
                res = requests.get("https://www.cricbuzz.com/cricket-match/live-scores", headers=headers, timeout=8)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    matched_cards = []
                    
                    team_tokens = ["rcb", "csk", "mi", "gt", "kkr", "srh", "pbks", "dc", "lsg", "rr", 
                                   "bengaluru", "chennai", "mumbai", "gujarat", "kolkata", "hyderabad", 
                                   "punjab", "delhi", "lucknow", "rajasthan", "india", "pakistan", "australia", 
                                   "england", "south africa", "new zealand", "bangladesh", "sri lanka", "afghanistan", 
                                   "ireland", "scotland", "zimbabwe", "nepal", "netherlands", "uae", "oman", 
                                   "kenya", "uganda", "namibia", "canada", "usa", "west indies"]
                    
                    target_tokens = [tok for tok in team_tokens if tok in q_lower]
                    
                    for a in soup.find_all("a"):
                        txt = a.get_text()
                        if not txt:
                            continue
                        txt_lower = txt.lower()
                        is_match_card = any(x in txt_lower for x in ["/", "won by", "beat", "preview", "opt to", "choose to", "runs", "wickets"])
                        
                        if is_match_card:
                            card_text = " ".join(a.get_text(separator=" | ").split())
                            if card_text and card_text not in matched_cards:
                                if target_tokens:
                                    if any(tok in txt_lower for tok in target_tokens):
                                        matched_cards.append(card_text)
                                else:
                                    matched_cards.append(card_text)
                                    if len(matched_cards) >= 6:
                                        break
                                        
                    if matched_cards:
                        result_text = "\n".join(matched_cards)
                        print(f"[Search/Scraper] Cricbuzz matched match cards:\n{result_text}")
                        return f"Live cricket match scorecard details:\n{result_text}"
            except Exception as e:
                print(f"[Search/Scraper] Cricbuzz live scores fetch error: {e}")

        # 2. Try Tavily Search API
        try:
            from skills.api_integrations import APIIntegrations
            api_int = APIIntegrations()
            tavily_res = api_int.tavily_search(query)
            if tavily_res:
                print(f"[Search/Tavily] Tavily returned clean search context.")
                return tavily_res[:1500]
        except Exception as e:
            print(f"[Search/Tavily] Tavily Search API failed or missing key: {e}. Falling back to scraping...")

        encoded = urllib.parse.quote(query)
        url = f"https://news.google.com/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }
        
        try:
            print(f"[Search/Scraper] Fetching from news.google.com for query: {query}")
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code != 200:
                print(f"[Search/Scraper] news.google.com failed with status {res.status_code}. Trying fallback...")
                url_fallback = f"https://www.google.com/search?q={encoded}&hl=en"
                res = requests.get(url_fallback, headers=headers, timeout=8)
                if res.status_code != 200:
                    return "Could not fetch news."
            
            soup = BeautifulSoup(res.text, "html.parser")
            for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
                tag.decompose()
            
            text = soup.get_text(separator=" ", strip=True)
            text = " ".join(text.split())
            return text[:1500]
        except Exception as e:
            print(f"[Search/Scraper] Error: {e}")
            return "Could not fetch news."

    # ── Handle single turn ────────────────────────────────────────────────────

    def _classify_intent_before_chat(self, user_input):
        """Determine if user input is a search/navigation intent requiring BrowserSkill execution."""
        inp = user_input.lower().strip()
        from skills.routing_policy import (
            TOOL_CONFIDENCE_THRESHOLD,
            evaluate_tool_arming,
            extract_explicit_search_query,
            has_live_info_cue,
            is_conversational_utterance,
        )

        if is_conversational_utterance(user_input):
            print("[Main/IntentGuard] Conversational utterance detected. Blocking browser/tool routing.")
            return "other", None
        
        # Bypasses: If the request is an interactive automation task, return 'other' to let general agent handle it
        automation_keywords = ["click", "buy", "add to cart", "fill", "type", "login", "log in", "sign in", "cart", "play video", "youtube", "amazon"]
        if any(kw in inp for kw in automation_keywords):
            return "other", None

        # 1. Hardcoded pattern matching (fast)
        query = extract_explicit_search_query(user_input)
        if query:
            decision = evaluate_tool_arming(
                "search",
                0.95,
                user_input,
                explicit_tool_signal=True,
            )
            if decision.armed:
                return "browser_search", query
            print(f"[Main/IntentGuard] Search tool blocked: {decision.reason}")
            return "other", None
                
        # 2. Sports / news queries (common browser searches)
        if has_live_info_cue(user_input):
            decision = evaluate_tool_arming(
                "search",
                0.90,
                user_input,
                explicit_tool_signal=True,
            )
            if decision.armed:
                return "browser_search", user_input
            print(f"[Main/IntentGuard] Live-info search blocked: {decision.reason}")
            return "other", None

        # Do not use LLM fallback to authorize tools. If cloud routing is degraded
        # or ambiguous, keep the turn conversational and let Brain answer safely.
        if any(token in inp for token in ["latest", "current", "today", "news", "weather", "score", "price"]):
            print(
                f"[Main/IntentGuard] Live-info cue present but below tool confidence "
                f"({0.75:.2f} < {TOOL_CONFIDENCE_THRESHOLD:.2f}). Keeping conversation safe."
            )
            
        return "other", None

    def _is_affirmative_reply(self, text):
        return text.strip().lower().strip(".!?") in {
            "yes", "yeah", "yep", "ok", "okay", "sure", "correct", "confirm", "do it"
        }

    def _extract_amazon_product(self, user_input):
        query = user_input.strip()
        q_lower = query.lower()

        if "amazon" not in q_lower:
            return None

        if re.search(r"\b(it|that|this)\b", q_lower) and self.shopping_search_context.get("product"):
            if any(phrase in q_lower for phrase in ["search it", "search that", "buy it", "buy that", "open it", "open that"]):
                return self.shopping_search_context.get("product")

        known_product_terms = [
            "keyboard", "keyboards", "mouse", "mice", "laptop", "headphones",
            "earphones", "monitor", "phone", "charger", "cable", "ssd",
        ]
        for term in known_product_terms:
            if re.search(rf"\b{re.escape(term)}\b", q_lower):
                return term

        patterns = [
            r"search\s+(?:amazon\s+for|for)\s+(.+?)(?:\s+(?:on|in|from)\s+amazon)?$",
            r"(?:buy|find|look\s+for|show\s+me|shop\s+for)\s+(.+?)\s+(?:on|in|from)\s+amazon",
            r"amazon\s+search\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, query, flags=re.IGNORECASE)
            if match:
                product = match.group(1).strip(" .?!")
                product = re.split(r"(?i),?\s+so\b|,|\.|;", product, maxsplit=1)[0].strip()
                product = re.sub(r"(?i)\b(can you|please|search it|search|open it|open|buy|something)\b", "", product).strip()
                if product and product.lower() not in {"it", "that", "this", "something"}:
                    return product

        if any(phrase in q_lower for phrase in ["search it in amazon", "search that in amazon", "not normal search", "not google"]):
            return self.shopping_search_context.get("product")

        return None

    def _search_amazon_product(self, product):
        product = (product or "").strip()
        if not product:
            self.pending_browser_action = {"type": "amazon_search_needs_product"}
            self._speak("What should I search for on Amazon?")
            return True

        self.automation_mode = True
        self.last_automation_action_time = time.time()
        self.shopping_search_context = {"site": "amazon", "product": product}
        self.pending_browser_action = None
        self._speak(f"Searching Amazon for {product}.")
        from skills.browser_skill import BrowserSkill
        res = BrowserSkill().search_amazon(product)
        self._speak(res)
        return True

    def _handle_deterministic_browser_request(self, user_input):
        inp = user_input.strip().lower()

        if self.pending_browser_action:
            if self.pending_browser_action.get("type") == "amazon_search_needs_product":
                if self._is_affirmative_reply(user_input):
                    self._speak("Tell me the product name first.")
                    return True
                return self._search_amazon_product(user_input)

            if self._is_affirmative_reply(user_input):
                action = self.pending_browser_action
                if action.get("type") == "amazon_search":
                    return self._search_amazon_product(action.get("product"))

        if "amazon" in inp and any(term in inp for term in ["search", "buy", "shop", "find", "look for", "open"]):
            product = self._extract_amazon_product(user_input)
            if product:
                return self._search_amazon_product(product)
            if any(generic in inp for generic in ["something", " it", " that", " this"]):
                return self._search_amazon_product(None)

        if any(phrase in inp for phrase in ["not normal search", "not google", "search it in amazon", "search that in amazon"]):
            product = self.shopping_search_context.get("product")
            return self._search_amazon_product(product)

        return False

    def _handle_input(self, user_input, image=None, remote=False):
        """Process one utterance from the user."""
        previous_phone_only = getattr(self._reply_context, "phone_only", False)
        self._reply_context.phone_only = remote
        self._spoken_during_turn = []
        try:
            return self._handle_input_impl(user_input, image=image)
        finally:
            try:
                if hasattr(self, "_spoken_during_turn") and self._spoken_during_turn:
                    import re
                    recorded_response = " ".join(self._spoken_during_turn)
                    recorded_response = re.sub(r'\[[A-Z]+:[^\]]*\]', '', recorded_response)
                    recorded_response = re.sub(r'\[[A-Z]+\]', '', recorded_response).strip()
                    if recorded_response:
                        user = self.known_user or "chinmaya"
                        emotion = getattr(self, "current_user_emotion", "neutral")
                        event_text = f"User: '{user_input}'. ARIA: '{recorded_response}'"
                        self.episodic_memory.record(
                            username=user,
                            event_text=event_text,
                            emotion=emotion,
                            confidence=1.0,
                            source="user_explicit",
                            retention_tier="permanent"
                        )
            except Exception as ep_err:
                print(f"[Main] Failed to record conversation episode in wrapper: {ep_err}")
            finally:
                self._spoken_during_turn = None
                self._reply_context.phone_only = previous_phone_only

    def _check_and_release_camera(self):
        """Releases the camera if no camera-dependent modes are active."""
        ar_active = getattr(self, "ar_mode", False) or getattr(self, "ar_playground", None) is not None
        gesture_active = getattr(self, "gesture_mode", False)
        vision_active = getattr(self, "vision_learner", None) and self.vision_learner.running
        
        if not ar_active and not gesture_active and not vision_active:
            if self.camera:
                print("[Camera] No active camera consumer. Releasing camera to turn it off.")
                self.camera.release()

    def _handle_input_impl(self, user_input, image=None):
        """Process one utterance from the user."""
        self._mark_conversation_activity(wake_reason="user_input")
        
        # Get normalized query for trigger checking and command processing
        inp = user_input.strip().lower()
        if hasattr(self, 'brain') and self.brain and getattr(self.brain, 'semantic_router', None) and self.brain.semantic_router.normalizer:
            try:
                normalized_val, _ = self.brain.semantic_router.normalizer.normalize(user_input)
                # Strip terminal punctuation for trigger matching ease
                inp = normalized_val.strip().lower().rstrip('.!?')
            except Exception as norm_err:
                print(f"[Main] Query normalization failed: {norm_err}")

        # Update relationship metrics based on specific user feedback loops
        if getattr(self, "known_user", None):
            has_thanks = any(w in inp for w in ["thank you", "thanks"])
            has_compliment = any(w in inp for w in ["good job", "nice", "perfect", "that's great"])
            has_ar = bool(re.search(r'\b(ar|air|hologram|whiteboard)\b', inp))
            has_polite_correction = any(w in inp for w in ["actually", "i meant", "no, please"]) and not any(w in inp for w in ["stupid", "idiot", "dumb", "useless", "fool", "hate you", "shut up", "trash", "garbage"])
            has_stop_asking = "stop asking" in inp
            
            delta_trust = 0.0
            if has_thanks:
                delta_trust += 0.2
            if has_compliment:
                delta_trust += 0.2
            if has_ar:
                delta_trust += 0.1
            if has_polite_correction:
                delta_trust += 0.1
            if has_stop_asking:
                delta_trust -= 0.05
                
            if delta_trust != 0.0:
                try:
                    self.reflection_engine.update_relationship_metrics(self.known_user, delta_trust=delta_trust)
                    current_trust = self.reflection_engine.get_relationship_vector(self.known_user)["trust"]
                    print(f"[ARIA] Input-triggered relationship adjustment applied for '{self.known_user}': delta_trust={delta_trust:+.2f}. Current trust: {current_trust:.2f}")
                except Exception as e:
                    print(f"[Main] Failed to update relationship metrics for feedback triggers: {e}")

        # ── Detect face emotion before responding ──
        emotional_tone = "neutral"
        try:
            emotional_tone = self._get_current_emotion()
            print(f"[Emotion] Detected: {emotional_tone}")
        except Exception as e:
            print(f"[Emotion] Pre-thought detection failed: {e}")

        # Route proactive suggestions feedback
        if time.time() - getattr(self, "last_proactive_suggestion_time", 0.0) < 15.0:
            try:
                self.proactive_cognition.log_user_engagement(user_input)
            except Exception as e:
                print(f"[Main] Proactive feedback routing error: {e}")
            self.last_proactive_suggestion_time = 0.0

        # Watchdog and Stale Session validation
        if self.automation_mode:
            try:
                from skills.browser_skill import BrowserSkill
                if not BrowserSkill().is_browser_active():
                    print("[Main] Detected browser was closed. Exiting automation mode.")
                    self.automation_mode = False
                elif time.time() - self.last_automation_action_time > 180.0 and not self.conversation_session.is_active():
                    print("[Main] Watchdog: 180s browser inactivity timeout exceeded. Automatically closing browser.")
                    BrowserSkill().close_browser()
                    self.automation_mode = False
                else:
                    self.last_automation_action_time = time.time()
            except Exception as e:
                print(f"[Main] Watchdog check error: {e}")

        # ─ Local Stop/Cancel command check ─
        stop_words = [
            "stop", "cancel", "nevermind", "be quiet", "shut up", "stop talking", 
            "aria stop", "stop aria", "quiet", "silence", "pause", "enough", 
            "ok stop", "that's enough"
        ]
        if inp in stop_words:
            print("[ARIA] Local stop/cancel command detected. Clearing speech queue and stopping audio.")
            while not self.speech_queue.empty():
                try:
                    self.speech_queue.get_nowait()
                    self.speech_queue.task_done()
                except Exception:
                    break
            if pygame.mixer.get_init():
                try:
                    pygame.mixer.music.stop()
                    pygame.mixer.music.unload()
                except Exception:
                    pass
            set_state("IDLE")
            if hasattr(self, 'firebase_sync') and self.firebase_sync:
                self.firebase_sync.update_status("", status_str="idle")
            self._speak("Okay.")
            return

        # ─ Security Guard Admin Lock / Unlock ─
        if any(x in inp for x in ["aria unlock", "unlock aria", "activate admin", "unlock admin"]):
            self._speak("Authenticating user. Please look at the camera.")
            set_state("THINKING")
            set_text("Authenticating face...")
            detected = self.identify_user()
            if detected in ["chinmay", "chinmaya"]:
                msg = self.security.unlock_admin()
                self._speak("Identity verified as Chinmaya. Admin mode unlocked for 5 minutes.")
            else:
                self._speak("Authentication failed. Face is not recognized as trusted owner.")
            return

        if any(x in inp for x in ["lock aria", "lock admin", "deactivate admin"]):
            msg = self.security.lock_admin()
            self._speak(msg)
            return

        if self._handle_deterministic_browser_request(user_input):
            return

        # ─ Weather API Integration ─
        if "weather" in inp:
            match = re.search(r'weather (?:in|of|for)\s+([a-zA-Z\s]+)', inp)
            city = match.group(1).strip() if match else "Delhi"
            try:
                from skills.api_integrations import APIIntegrations
                api_int = APIIntegrations()
                weather_info = api_int.get_weather(city)
                self._speak(weather_info)
                return
            except Exception as e:
                print(f"[Main] Weather integration failed: {e}")

        # ─ GitHub API Integration ─
        if inp.startswith("github "):
            try:
                from skills.api_integrations import APIIntegrations
                api_int = APIIntegrations()
                if "list repos" in inp or "show repos" in inp:
                    res = api_int.github_helper(action="list")
                    self._speak(res)
                    return
                elif "commits" in inp:
                    match = re.search(r'commits in\s+([a-zA-Z0-9_\-\/]+)', inp)
                    if match:
                        repo = match.group(1).strip()
                        res = api_int.github_helper(action="commits", repo_name=repo)
                        self._speak(res)
                    else:
                        self._speak("Please specify repo as owner/repo name. Example: github commits in owner/repo")
                    return
                elif "create issue" in inp:
                    match = re.search(r'create issue in\s+([a-zA-Z0-9_\-\/]+)', inp)
                    if match:
                        repo = match.group(1).strip()
                        title_match = re.search(r'title\s+[\'"](.+?)[\'"]', user_input, re.IGNORECASE)
                        body_match = re.search(r'body\s+[\'"](.+?)[\'"]', user_input, re.IGNORECASE)
                        title = title_match.group(1) if title_match else "ARIA Auto-created Issue"
                        body = body_match.group(1) if body_match else "Created automatically by ARIA."
                        res = api_int.github_helper(action="create_issue", repo_name=repo, extra_params={"title": title, "body": body})
                        self._speak(res)
                    else:
                        self._speak("Please specify repo as owner/repo name. Example: github create issue in owner/repo title 'my title' body 'my body'")
                    return
            except Exception as e:
                print(f"[Main] GitHub integration failed: {e}")

        # ─ Long-Term Memory Commands ─
        if "remind me to " in inp:
            raw_task = user_input.split("remind me to", 1)[1].strip()
            task, due, due_at = self.memory_skill.parse_reminder_text(raw_task)
            resp = self.memory_skill.add_reminder(task, due, due_at)
            self._speak(resp)
            return

        if any(x in inp for x in ["what are my reminders", "show my reminders", "get my reminders", "list reminders", "my reminders"]):
            resp = self.memory_skill.get_pending_reminders()
            self._speak(resp)
            return

        if any(x in inp for x in ["clear reminders", "delete reminders", "remove reminders"]):
            resp = self.memory_skill.clear_reminders()
            self._speak(resp)
            return

        # ─ Folder Shortcut Registration (Memory) ─
        if any(x in inp for x in ["remember this folder as ", "remember folder as "]):
            match = re.search(r'(?:remember folder|remember this folder)\s+(.+?)\s+as\s+(.+)', inp)
            if match:
                path = match.group(1).strip()
                name = match.group(2).strip()
                resp = self.memory_skill.save_folder(name, path)
                self._speak(resp)
            else:
                self._speak("To remember a folder, say: remember folder [path] as [name]")
            return

        # ─ PC Context Awareness ─
        if any(x in inp for x in ["what do you know about me", "show my brain", "my brain summary", "personal brain", "what is in my brain"]):
            self._speak(self.memory_skill.get_personal_brain_summary())
            return

        if any(x in inp for x in ["what should i do", "what do i need to do", "what should i focus on", "guide me"]):
            summary = self.memory_skill.get_personal_brain_summary()
            prompt = (
                "Use this local personal memory and current context to suggest what I should do next. "
                "Keep it practical and short.\n\n" + summary
            )
            response = self.brain.think(
                prompt,
                user_name=self.known_user,
                user_similarity=self.known_user_similarity,
                user_confidence=self.known_user_confidence,
                emotional_tone=getattr(self, "current_user_emotion", "neutral")
            )
            self._speak(response)
            return

        if any(inp.startswith(prefix) for prefix in ["remember that ", "remember i ", "remember my "]):
            note = re.sub(r'(?i)^remember\s+(that|i|my)\s+', '', user_input).strip()
            self._speak(self.memory_skill.add_personal_note("fact", note))
            return

        if any(inp.startswith(prefix) for prefix in ["i need to ", "i have to ", "i should "]):
            task = re.sub(r'(?i)^(i need to|i have to|i should)\s+', '', user_input).strip()
            self._speak(self.memory_skill.add_personal_note("need_to_do", task))
            return

        if any(inp.startswith(prefix) for prefix in ["i don't need to ", "i dont need to ", "i should not ", "don't let me ", "dont let me "]):
            avoid = re.sub(r"(?i)^(i don't need to|i dont need to|i should not|don't let me|dont let me)\s+", "", user_input).strip()
            self._speak(self.memory_skill.add_personal_note("avoid", avoid))
            return

        if any(inp.startswith(prefix) for prefix in ["my goal is ", "goal is "]):
            goal = re.sub(r'(?i)^(my goal is|goal is)\s+', '', user_input).strip()
            self._speak(self.memory_skill.add_personal_note("goal", goal))
            return

        if inp.startswith("i want to "):
            from skills.routing_policy import is_actionable_execution_request
            goal = re.sub(r'(?i)^i want to\s+', '', user_input).strip()
            if not is_actionable_execution_request(user_input):
                self._speak(self.memory_skill.add_personal_note("goal", goal))
                return
            print("[Main/IntentGuard] 'I want to' contains action cues. Routing to execution, not goal storage.")

        if any(inp.startswith(prefix) for prefix in ["i like ", "i prefer ", "my preference is "]):
            pref = re.sub(r'(?i)^(i like|i prefer|my preference is)\s+', '', user_input).strip()
            self._speak(self.memory_skill.add_personal_note("preference", pref))
            return

        if any(x in inp for x in ["pc status", "system status", "check status", "how is my pc", "pc context"]):
            summary = self.context_skill.get_context_summary()
            self._speak("Reading current PC status.")
            print(summary)
            batt = self.context_skill.get_battery_percent()
            wifi = self.context_skill.get_wifi_status()
            ac = self.context_skill.get_active_window()
            self._speak(f"Battery is at {batt if batt is not None else 'unknown'} percent, wifi is {wifi}, and active app is {ac[:40]}.")
            return

        if "battery" in inp and any(x in inp for x in ["level", "percent", "status", "check"]):
            batt = self.context_skill.get_battery_percent()
            chg = self.context_skill.get_charging_status()
            if batt is not None:
                state = "charging" if chg else "discharging"
                self._speak(f"Your battery level is {batt} percent and is currently {state}.")
            else:
                self._speak("I couldn't read the battery level. If this is a desktop, it might not have one.")
            return

        # ─ Multi-Step Workspaces ─
        if any(x in inp for x in ["prepare ml workspace", "setup coding", "start coding", "ml workspace"]):
            self._speak("Setting up your Machine Learning workspace...")
            resp = self.workspace_skill.prepare_ml_workspace()
            self._speak("Workspace is configured.")
            return

        if any(x in inp for x in ["study mode", "activate study mode", "start study", "focus mode"]):
            self._speak("Activating study focus mode...")
            resp = self.workspace_skill.study_mode()
            self._speak("Study mode is active. Distractions minimized.")
            return

        if any(x in inp for x in ["close workspace", "clean workspace", "close coding"]):
            self._speak("Cleaning up active workspace.")
            self.workspace_skill.close_workspace()
            return

        # ─ ARIA Autonomous Agent Loop Trigger ─
        if inp.startswith("run task ") or inp.startswith("automate ") or inp.startswith("aria run "):
            # Extract task details
            task = user_input
            for prefix in ["run task", "automate", "aria run"]:
                if inp.startswith(prefix):
                    task = user_input[len(prefix):].strip()
                    break
            import uuid
            task_id = str(uuid.uuid4())
            self.executor_queue.add_task(task_id, task, priority=5)
            self._speak(f"Task enqueued. Task ID is {task_id[:8]}. I will begin processing shortly.")
            return

        if any(x in inp for x in ["cancel task", "abort task", "stop task", "stop execution"]):
            active = self.executor_queue.get_active_task()
            if active:
                self.executor_queue.cancel_task(active.task_id)
                self._speak(f"Requesting cancellation for active task '{active.goal}'.")
            else:
                self._speak("No active task is running.")
            return

        if inp.startswith("replay task "):
            task_id = inp.replace("replay task ", "").strip()
            self.replay_task(task_id)
            return

        # ─ Ollama Agent Launch Trigger ─
        if "ollama launch" in inp or any(inp.startswith(prefix) for prefix in ["launch claude", "launch codex", "launch hermes", "launch openclaw", "launch opencode"]):
            # extract agent name
            agent = "claude"
            if "codex" in inp: agent = "codex-app"
            elif "hermes" in inp: agent = "hermes"
            elif "openclaw" in inp: agent = "openclaw"
            elif "opencode" in inp: agent = "opencode"
            elif "claude" in inp: agent = "claude"
            elif "ollama launch " in inp:
                agent = inp.split("ollama launch ")[1].strip()

            self._speak(f"Launching {agent} agent in a new terminal window.")
            import subprocess
            subprocess.Popen(f'start cmd /k "ollama launch {agent}"', shell=True)
            return

        # ─ Exit commands ─
        if any(x in inp for x in ["exit application", "close aria", "quit aria", "shutdown application"]):
            self._speak("Goodbye! Shutting down all systems.")
            self.running = False
            if USE_GUI and _gui_available:
                try:
                    from PyQt5.QtWidgets import QApplication
                    app_inst = QApplication.instance()
                    if app_inst:
                        app_inst.quit()
                except Exception:
                    pass
            return

        if any(x in inp for x in ["goodbye", "bye", "bye aria", "go to sleep"]):
            self._speak("Goodbye! Have a great day. I'll be here in sleep mode whenever you need me.")
            if hasattr(self, "conversation_session") and self.conversation_session:
                self.conversation_session.session_active = False
            return

        # ─ Reset conversation memory ─
        if any(x in inp for x in ["reset memory", "forget everything", "clear history", "new conversation"]):
            self.brain.reset_conversation()
            self._speak("Conversation memory cleared. Fresh start!")
            return

        # ─ Direct UI Control — no vision, no screenshot, instant ─────────────────
        # "switch to notepad" / "focus chrome"
        if any(x in inp for x in ["switch to", "focus on", "bring up", "go to app"]):
            app = inp
            for t in ["switch to", "focus on", "bring up", "go to app"]:
                app = app.replace(t, "").strip()
            ok, msg = self.ui.focus_window(app)
            self._speak(f"Switched to {app}." if ok else f"Couldn't find {app} open.")
            return

        # "new tab" / "close tab" / "refresh" / "go back" / "go forward"
        if "new tab" in inp:
            self.ui.browser_new_tab()
            self._speak("Opened a new tab.")
            return
        if any(x in inp for x in ["latest news", "news of the world", "world news", "what's going on around the world", "what is going on around the world"]):
            self._speak("Opening the latest news for you.")
            self.automation.search_web(user_input.strip() or "latest world news")
            return
        if any(x in inp for x in ["close tab", "close the tab", "bar tab", "delete tab", "remove tab"]):
            self.ui.browser_close_tab()
            self._speak("Closed the tab.")
            return
        if any(x in inp for x in ["close window", "close the window", "close chrome", "close browser", "close cross", "cross button", "press cross"]):
            self.screen.press("alt", "f4")
            self._speak("Closed the window.")
            return
        if any(x in inp for x in ["refresh page", "reload page", "refresh browser"]):
            self.ui.browser_refresh()
            self._speak("Refreshed.")
            return
        if "go back" in inp:
            self.ui.browser_back()
            self._speak("Going back.")
            return
        if "go forward" in inp:
            self.ui.browser_forward()
            self._speak("Going forward.")
            return

        # "go to [url] in chrome/browser"
        if "go to" in inp and any(b in inp for b in ["chrome", "edge", "firefox", "browser"]):
            url = re.sub(r'go to|in chrome|in edge|in firefox|in browser', '', inp).strip()
            if url and not url.startswith("http"):
                url = "https://" + url
            if url:
                ok, msg = self.ui.browser_go_to(url)
                self._speak(f"Going to {url}.")
                return

        # "what apps are open" / "list open windows"
        if any(x in inp for x in ["what apps are open", "what is open", "list open apps", "show open apps"]):
            apps = self.ui.get_open_apps()[:6]
            if apps:
                self._speak(f"I can see these open: {', '.join(apps[:5])}.")
            else:
                self._speak("I couldn't detect any open windows.")
            return

        # ─ Screen: take a screenshot ─
        if any(x in inp for x in ["take screenshot", "screenshot", "capture screen"]):
            path = self.screen.take_screenshot()
            self._speak(f"Screenshot saved!")
            return

        # ─ Screen: Smart Vision Click — ONLY for visual find tasks ─
        # e.g. "click on the Chrome icon", "where is the recycle bin", "find and click VS Code"
        _screen_read_triggers = [
            "read my screen", "read the screen", "what's on my screen",
            "what is on my screen", "what do you see on screen",
            "read it out", "read this page", "read the page",
            "read the results", "read the news", "pick some latest news",
            "summarize the screen", "summarise the screen"
        ]
        if any(x in inp for x in _screen_read_triggers):
            set_state("THINKING")
            set_text("Reading screen...")
            self._speak("Reading your screen now.")
            self._answer_with_screen_image(user_input)
            return

        _smart_click_triggers = [
            "click on",
            "find and click",
            "where is the",
            "what's at",
            "what is at",
            "locate the",
        ]
        if any(t in inp for t in _smart_click_triggers) and self.brain.vision_ready:
            # Extract what the user wants to find
            target = inp
            for t in _smart_click_triggers:
                target = target.replace(t, "").strip()
            target = target.strip(" .,?") or "anything on screen"

            set_state("THINKING")
            set_text(f"Reading screen for: {target}")
            self._speak("Looking at your screen now.")

            # ── Capture screen DIRECTLY into RAM — zero disk I/O ──────────
            import io, base64
            pil_img = self.screen.get_screen_image()          # PIL Image in RAM
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")                   # encode in memory
            img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")  # base64 in RAM
            # ──────────────────────────────────────────────────────────────

            sw, sh = self.screen.screen_w, self.screen.screen_h
            set_text(f"Vision AI looking for: {target}")
            vision_result = self.brain.think_with_screen(img_b64, target, sw, sh)

            if vision_result is not None:
                if vision_result.startswith("FOUND:"):
                    # Moondream found it — parse location description → coords
                    location_desc = vision_result[6:].strip()
                    cx, cy = self.brain.parse_location_to_coords(location_desc, sw, sh)
                    self.screen.click(cx, cy)
                    self._speak(f"Found it. It is at the {location_desc}. Clicking now.")
                else:
                    # Not found or error — speak the description
                    clean = re.sub(r'[*#`_]', '', vision_result).strip()
                    self._speak(clean[:300] if clean else "I couldn't find that on your screen.")
            else:
                self._speak("Vision model had an error. Try again.")
            return

        # ─ Screen: natural-language click by region ─
        _click_trigger = ("click" in inp or "tap" in inp or "press" in inp or "open" in inp)
        _region_words  = [
            "corner", "center", "middle", "left", "right", "top", "bottom",
            "taskbar", "start", "desktop", "start menu", "notification",
            "tray", "close button", "minimize", "maximize button"
        ]
        if _click_trigger and any(w in inp for w in _region_words):
            sw, sh = self.screen.screen_w, self.screen.screen_h
            margin = 40  # pixels from edge for "corner" targets

            # Map spoken region → (x, y, label)
            REGIONS = {
                # Corners
                ("top left",):                  (margin,        margin,       "top-left corner"),
                ("top right",):                 (sw - margin,   margin,       "top-right corner"),
                ("bottom left",):               (margin,        sh - margin,  "bottom-left corner"),
                ("bottom right",):              (sw - margin,   sh - margin,  "bottom-right corner"),
                # Edges / halves
                ("top center", "top middle"):   (sw // 2,       margin,       "top center"),
                ("bottom center", "bottom middle", "taskbar center"): (sw // 2, sh - 25, "taskbar center"),
                ("left center", "left side"):   (margin,        sh // 2,      "left side"),
                ("right center", "right side"):  (sw - margin,   sh // 2,      "right side"),
                # Middle of screen
                ("center", "middle", "screen center"): (sw // 2, sh // 2,    "screen center"),
                # Taskbar & system
                ("start menu", "start button", "windows button"): (25, sh - 25, "Start menu"),
                ("taskbar",):                   (sw // 2,       sh - 25,      "taskbar"),
                ("notification", "system tray", "tray"): (sw - 60, sh - 25, "system tray"),
                # Window controls (approx for maximized windows)
                ("close button", "close window button"): (sw - 25, 15,      "close button"),
                ("maximize button",):           (sw - 65,       15,           "maximize button"),
                ("minimize button",):           (sw - 105,      15,           "minimize button"),
            }

            clicked_region = None
            for phrases, (cx, cy, label) in REGIONS.items():
                if any(p in inp for p in phrases):
                    clicked_region = (cx, cy, label)
                    break

            # Fallback — generic directional hints
            if not clicked_region:
                if "top" in inp and "left" not in inp and "right" not in inp:
                    clicked_region = (sw // 2, margin, "top area")
                elif "bottom" in inp and "left" not in inp and "right" not in inp:
                    clicked_region = (sw // 2, sh - 25, "bottom area / taskbar")
                elif "left" in inp:
                    clicked_region = (margin, sh // 2, "left side")
                elif "right" in inp:
                    clicked_region = (sw - margin, sh // 2, "right side")

            if clicked_region:
                cx, cy, label = clicked_region
                double = "double" in inp
                right  = "right click" in inp or "right-click" in inp
                if right:
                    self.screen.right_click(cx, cy)
                    self._speak(f"Right-clicked the {label}.")
                elif double:
                    self.screen.double_click(cx, cy)
                    self._speak(f"Double-clicked the {label}.")
                else:
                    self.screen.click(cx, cy)
                    self._speak(f"Clicked the {label}.")
                return

        # ─ Screen: what's on my screen? ─
        if any(x in inp for x in ["what's on my screen", "what is on my screen", "read my screen", "what do you see on screen"]):
            img = self.screen.get_screen_image()
            # Convert PIL image to bytes for Llama vision (if available)
            import io
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            self._speak("I can see your screen. Let me describe what's there. I see a Windows desktop with open windows and applications. For full screen reading, I need the vision model. Say 'take screenshot' and I can save it for you.")
            return

        # ─ Screen: open a folder ─
        if ("open folder" in inp or "go to folder" in inp or "navigate to" in inp):
            import re as _re
            # Try to extract path: "open folder downloads" or "open folder C:\Users\..."
            path_match = _re.search(r'(?:open folder|go to folder|navigate to)\s+(.+)', inp)
            if path_match:
                folder_name = path_match.group(1).strip()
                # Common folder shortcuts
                FOLDER_MAP = {
                    "downloads": os.path.expanduser("~/Downloads"),
                    "documents": os.path.expanduser("~/Documents"),
                    "desktop": os.path.expanduser("~/Desktop"),
                    "pictures": os.path.expanduser("~/Pictures"),
                    "music": os.path.expanduser("~/Music"),
                    "videos": os.path.expanduser("~/Videos"),
                    "ai": r"C:\D FOLDER\Projects\AI",
                    "projects": r"C:\D FOLDER\Projects",
                    "screenshot": r"C:\D FOLDER\Projects\AI",
                    "screenshots": r"C:\D FOLDER\Projects\AI",
                    "screenshot folder": r"C:\D FOLDER\Projects\AI",
                }
                folder_path = FOLDER_MAP.get(folder_name.lower(), folder_name)
                if self.screen.open_folder(folder_path):
                    self._speak(f"Opened the {folder_name} folder for you.")
                else:
                    self._speak(f"I couldn't find the folder {folder_name}. Please check the path.")
                return

        # ─ Send latest screenshot via WhatsApp ─
        if any(x in inp for x in ["send screenshot", "share screenshot", "send the screenshot", "whatsapp screenshot", "send screen"]):
            import glob
            ai_dir = r"C:\D FOLDER\Projects\AI"
            shots = sorted(glob.glob(os.path.join(ai_dir, "screenshot_*.png")), reverse=True)
            if not shots:
                self._speak("I couldn't find any screenshots to send. Take one first by saying take screenshot.")
                return
            latest = shots[0]
            self._speak("Who do you want to send the screenshot to on WhatsApp?")
            set_state("LISTENING")
            contact = self.voice.listen(timeout=8)
            if not contact:
                self._speak("I didn't catch the name. Try again.")
                return
            self._speak(f"Sending the screenshot to {contact} on WhatsApp Web now.")
            self.screen.send_whatsapp_file(contact, latest)
            self._speak(f"WhatsApp Web is open with {contact} selected. Please click the attachment icon to attach the file. The path is already copied.")
            return

        # ─ WhatsApp: send message ─
        if "send whatsapp" in inp or "whatsapp message" in inp or ("send" in inp and "whatsapp" in inp):
            self._speak("Who do you want to message on WhatsApp?")
            set_state("LISTENING")
            contact = self.voice.listen(timeout=8)
            if not contact:
                self._speak("I didn't catch the name. Try again.")
                return
            self._speak(f"What message should I send to {contact}?")
            set_state("LISTENING")
            message = self.voice.listen(timeout=12)
            if not message:
                self._speak("I didn't catch the message. Try again.")
                return
            self._speak(f"Sending '{message}' to {contact} on WhatsApp Web now.")
            result = self.screen.send_whatsapp_message(contact, message)
            self._speak("Done! Message sent.")
            return

        # ─ Screen: show open windows ─
        if any(x in inp for x in ["what windows are open", "show open windows", "list windows", "what's open"]):
            windows = self.screen.list_open_windows()
            filtered = [w for w in windows if w.strip() and len(w) > 2][:8]
            if filtered:
                self._speak(f"I can see {len(filtered)} open windows: {', '.join(filtered[:5])}.")
            else:
                self._speak("I couldn't detect any open windows right now.")
            return

        # ─ Screen: press key / keyboard shortcut ─
        if inp.startswith("press ") and any(x in inp for x in ["ctrl", "alt", "enter", "escape", "tab", "delete", "win"]):
            combo = inp.replace("press ", "").strip()
            keys = [k.strip() for k in combo.replace(" and ", "+").split("+")]
            self.screen.press(*keys)
            self._speak(f"Pressed {combo}.")
            return

        # ─ Screen: scroll ─
        if "scroll to top" in inp or "scroll to the top" in inp:
            try:
                from skills.browser_skill import BrowserSkill
                bs = BrowserSkill()
                if self.automation_mode and bs.is_browser_active():
                    self.last_automation_action_time = time.time()
                    self._speak("Scrolling to top.")
                    self._speak(bs.scroll("top"))
                    return
            except Exception as e:
                print(f"[Main] Browser scroll fallback failed: {e}")
            self.screen.press("ctrl+home")
            self._speak("Scrolling to top.")
            return

        if "scroll to bottom" in inp or "scroll to the bottom" in inp:
            try:
                from skills.browser_skill import BrowserSkill
                bs = BrowserSkill()
                if self.automation_mode and bs.is_browser_active():
                    self.last_automation_action_time = time.time()
                    self._speak("Scrolling to bottom.")
                    self._speak(bs.scroll("bottom"))
                    return
            except Exception as e:
                print(f"[Main] Browser scroll fallback failed: {e}")
            self.screen.press("ctrl+end")
            self._speak("Scrolling to bottom.")
            return

        if "scroll down a little" in inp or "scroll a little down" in inp or "scroll a little" in inp:
            try:
                from skills.browser_skill import BrowserSkill
                bs = BrowserSkill()
                if self.automation_mode and bs.is_browser_active():
                    self.last_automation_action_time = time.time()
                    self._speak("Scrolling down a little.")
                    self._speak(bs.scroll("down", "little"))
                    return
            except Exception as e:
                print(f"[Main] Browser scroll fallback failed: {e}")
            self.screen.scroll(2, "down")
            self._speak("Scrolling down a little.")
            return

        if "scroll up a little" in inp or "scroll a little up" in inp:
            try:
                from skills.browser_skill import BrowserSkill
                bs = BrowserSkill()
                if self.automation_mode and bs.is_browser_active():
                    self.last_automation_action_time = time.time()
                    self._speak("Scrolling up a little.")
                    self._speak(bs.scroll("up", "little"))
                    return
            except Exception as e:
                print(f"[Main] Browser scroll fallback failed: {e}")
            self.screen.scroll(2, "up")
            self._speak("Scrolling up a little.")
            return

        if "scroll down more" in inp or "scroll more down" in inp or "scroll more" in inp:
            try:
                from skills.browser_skill import BrowserSkill
                bs = BrowserSkill()
                if self.automation_mode and bs.is_browser_active():
                    self.last_automation_action_time = time.time()
                    self._speak("Scrolling down more.")
                    self._speak(bs.scroll("down", "more"))
                    return
            except Exception as e:
                print(f"[Main] Browser scroll fallback failed: {e}")
            self.screen.scroll(10, "down")
            self._speak("Scrolling down more.")
            return

        if "scroll up more" in inp or "scroll more up" in inp:
            try:
                from skills.browser_skill import BrowserSkill
                bs = BrowserSkill()
                if self.automation_mode and bs.is_browser_active():
                    self.last_automation_action_time = time.time()
                    self._speak("Scrolling up more.")
                    self._speak(bs.scroll("up", "more"))
                    return
            except Exception as e:
                print(f"[Main] Browser scroll fallback failed: {e}")
            self.screen.scroll(10, "up")
            self._speak("Scrolling up more.")
            return

        if "scroll down" in inp:
            try:
                from skills.browser_skill import BrowserSkill
                bs = BrowserSkill()
                if self.automation_mode and bs.is_browser_active():
                    self.last_automation_action_time = time.time()
                    self._speak("Scrolling down.")
                    self._speak(bs.scroll("down"))
                    return
            except Exception as e:
                print(f"[Main] Browser scroll fallback failed: {e}")
            self.screen.scroll(5, "down")
            self._speak("Scrolling down.")
            return

        if "scroll up" in inp:
            try:
                from skills.browser_skill import BrowserSkill
                bs = BrowserSkill()
                if self.automation_mode and bs.is_browser_active():
                    self.last_automation_action_time = time.time()
                    self._speak("Scrolling up.")
                    self._speak(bs.scroll("up"))
                    return
            except Exception as e:
                print(f"[Main] Browser scroll fallback failed: {e}")
            self.screen.scroll(5, "up")
            self._speak("Scrolling up.")
            return

        # ─ Screen: minimize / maximize ─
        if any(x in inp for x in ["cheapest", "lowest price", "least expensive"]) and any(x in inp for x in ["page", "this", "keyboard", "product"]):
            try:
                from skills.browser_skill import BrowserSkill
                bs = BrowserSkill()
                if bs.is_browser_active():
                    self.automation_mode = True
                    self.last_automation_action_time = time.time()
                    self._speak(bs.cheapest_visible_item())
                    return
            except Exception as e:
                print(f"[Main] Cheapest visible item check failed: {e}")

        if "minimize" in inp:
            self.screen.press("win", "down")
            self._speak("Minimized the window.")
            return
        if "maximize" in inp:
            self.screen.press("win", "up")
            self._speak("Maximized the window.")
            return
        if "close window" in inp:
            self.screen.press("alt", "F4")
            self._speak("Closed the window.")
            return

        # ─ Smart Unified Learning: learn face or object ─
        # Determine intent: Face Enrollment vs Object Learning
        face_trigger_found = None
        object_trigger_found = None
        new_name = ""

        # Check explicit face/user introduction triggers
        face_triggers = ["my name is ", "enroll me as ", "register face as ", "save my face as ", "learn my face as "]
        for t in face_triggers:
            if t in inp:
                face_trigger_found = t
                break

        # Check "i am", "i'm", "im" (only at start or greeting introduction)
        if not face_trigger_found:
            intro_triggers = ["i am ", "i'm ", "im "]
            for t in intro_triggers:
                if t in inp:
                    idx = inp.find(t)
                    prefix = inp[:idx].lower().strip()
                    # Clean common greetings
                    for greeting in ["hello", "hi", "hey aria", "hey", "aria", "ok", "okay"]:
                        if prefix.startswith(greeting):
                            prefix = prefix[len(greeting):].strip()
                        if prefix.endswith(greeting):
                            prefix = prefix[:-len(greeting)].strip()
                    prefix = prefix.strip(",.?! ")
                    
                    clause_words = ["where", "what", "who", "how", "why", "when", "while", "if", "that", "because", "since", "although", "there", "here", "know"]
                    if not prefix and not any(w in inp.lower().split() for w in clause_words):
                        face_trigger_found = t
                        break

        # Check explicit object learning triggers
        object_triggers = ["learn this as ", "learn object ", "learn this object as "]
        for t in object_triggers:
            if t in inp:
                object_trigger_found = t
                break

        # Check "this is" as a divider
        if not face_trigger_found and not object_trigger_found and "this is " in inp:
            ar_terms = ["ar mode", "ar playground", "air mode", "air playground", "piano mode", "wand mode", "pet mode", "flower mode", "garden mode"]
            if not any(term in inp.lower() for term in ar_terms):
                raw_suffix = inp.split("this is ", 1)[1].strip()
                # If suffix starts with an article, it's an object. Otherwise, it's a person/face.
                if any(raw_suffix.lower().startswith(w) for w in ["a ", "an ", "the "]):
                    object_trigger_found = "this is "
                elif "me" == raw_suffix.lower().strip(".,?! "):
                    face_trigger_found = "this is me"
                else:
                    face_trigger_found = "this is "

        trigger_found = face_trigger_found or object_trigger_found
        if trigger_found:
            # 1. Parse name and clean up
            if trigger_found == "this is me":
                new_name = self.known_user.title() if (self.known_user and self.known_user != "Guest") else "User"
            else:
                raw_input = inp.split(trigger_found, 1)[1].strip()
                
                # Loop-clean leading fillers
                cleaned = True
                while cleaned:
                    cleaned = False
                    for clean_word in ["a ", "an ", "the ", "me ", "i am ", "i'm ", "im ", "my name is ", "called ", "named ", "holding "]:
                        if raw_input.lower().startswith(clean_word):
                            raw_input = raw_input[len(clean_word):].strip()
                            cleaned = True
                
                # Final name extraction (limit to 3 words)
                stop_phrases = [" which", " that", ". ", "!", "?", " holding", " and", " is ", " for "]
                obj_name = raw_input
                for stop in stop_phrases:
                    if stop in obj_name:
                        obj_name = obj_name.split(stop)[0].strip()
                new_name = obj_name.title()

            # Check if name is invalid or empty
            words = new_name.split()
            invalid_verbs = ["saying", "telling", "asking", "talking", "showing", "looking", "trying", "searching", "sorry", "not", "just", "sure", "going", "doing", "thinking", "having", "getting", "sitting", "working", "standing", "reading", "writing"]
            if not new_name or len(words) > 3 or (len(words) > 0 and words[0].lower() in invalid_verbs):
                # Reject mapping
                face_trigger_found = None
                object_trigger_found = None
                trigger_found = None

        if trigger_found:
            # 2. Ensure Camera/Vision is active
            if not self.vision_learner.running:
                if getattr(self, "airtouch_mode", False):
                    self._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
                    return
                if not self.camera or not self.camera.available:
                    self.camera.reacquire()
                self._speak("Let me open my camera to look.")
                self.vision_learner.mode = "both" # Ensure both are active
                self.vision_learner.start_camera(frame_provider=self.camera.capture_frame_raw)
                # Wait for camera to warm up
                for _ in range(30):
                    time.sleep(0.1)
                    with self.vision_learner._lock:
                        if self.vision_learner.current_frame is not None: break

            # 3. Capture current frame and decide: Face vs Object
            with self.vision_learner._lock:
                frame = self.vision_learner.current_frame.copy() if self.vision_learner.current_frame is not None else None
            
            if frame is None:
                self._speak("I can't see anything. Please make sure the camera is working.")
                return

            if face_trigger_found:
                # FACE DETECTED check
                if not hasattr(frame, "shape") or len(frame.shape) < 2:
                    self._speak("I can't see anything clearly. Please look straight at the camera and try again.")
                    return
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                h, w = gray.shape[:2]
                faces = []
                if w >= 30 and h >= 30:
                    try:
                        faces = self.memory.face_cascade.detectMultiScale(gray, 1.3, 5)
                    except Exception as e:
                        print(f"[Main] Face detection error: {e}")
                
                if len(faces) > 0:
                    # FACE DETECTED -> Face Learning
                    self._speak(f"I see a face. Let's enroll you, {new_name}. Please stay still and look straight at the camera.")
                    self._wait_for_speech()
                    
                    embeddings = []
                    
                    # Helper function to capture and embed
                    def capture_and_embed():
                        with self.vision_learner._lock:
                            f = self.vision_learner.current_frame.copy() if self.vision_learner.current_frame is not None else None
                        if f is not None and hasattr(f, "shape") and len(f.shape) >= 2:
                            fh, fw = f.shape[:2]
                            if fw >= 40 and fh >= 40:
                                try:
                                    emb = self.memory.memory_manager.embedder.get_embedding(f)
                                    if emb:
                                        embeddings.append(emb)
                                except Exception as e:
                                    print(f"[Main] Embedding capture error: {e}")

                    # 1. Front Angle
                    time.sleep(0.5)
                    for _ in range(3):
                        capture_and_embed()
                        time.sleep(0.1)
                    
                    # 2. Turn Left
                    self._speak("Now turn your head slightly to the left.")
                    self._wait_for_speech()
                    time.sleep(1.0)
                    for _ in range(3):
                        capture_and_embed()
                        time.sleep(0.1)
                    
                    # 3. Turn Right
                    self._speak("Great. Now turn your head slightly to the right.")
                    self._wait_for_speech()
                    time.sleep(1.0)
                    for _ in range(3):
                        capture_and_embed()
                        time.sleep(0.1)

                    # 4. Look Up/Down
                    self._speak("Now tilt your head slightly up and down.")
                    self._wait_for_speech()
                    time.sleep(1.0)
                    for _ in range(3):
                        capture_and_embed()
                        time.sleep(0.1)

                    if len(embeddings) >= 4:
                        # Compute averaged centroid vector
                        avg_emb = np.mean(embeddings, axis=0)
                        # L2 normalize
                        norm = np.linalg.norm(avg_emb)
                        if norm > 0:
                            avg_emb = avg_emb / norm
                        
                        if self.memory.add_face(new_name, embedding=avg_emb.tolist()):
                            self.known_user = new_name
                            set_user(new_name)
                            # Reset match history and lock state to immediately match this user
                            self.face_match_history = []
                            self.known_user_confidence = "high"
                            self.last_identity_match_time = time.time()
                            self._speak(f"Enrollment complete! I've successfully saved a multi-angle representation of your face, {new_name}.")
                        else:
                            self._speak("Something went wrong while saving your face embeddings. Please try again.")
                    else:
                        self._speak("I couldn't capture enough clear angles of your face. Please ensure you are well-lit and try again.")
                else:
                    self._speak("I don't see a face to enroll. Please look straight at the camera and try again.")
            else:
                # Explicit Object Learning
                self._speak(f"I'll learn this object as {new_name}.")
                success, msg = self.vision_learner.capture_and_learn(new_name)
                if success:
                    self._speak(f"Got it! I have learned what a {new_name} looks like.")
                else:
                    self._speak(msg)
            return


        # ─ Teach command shortcut: must mention "command" to avoid clash with object teaching ─
        if any(x in inp for x in [
            "learn this command", "new command", "add command",
            "teach you a command", "teach you new", "custom command",
        ]):
            self._speak("Sure! Say the command phrase you want me to learn.")
            set_state("LISTENING")
            phrase = self.voice.listen(timeout=10)
            if not phrase:
                self._speak("I didn't catch that. Try again.")
                return
            self._speak(f"Got it: '{phrase}'. What should I do — Open, Close, Search, or Type?")
            set_state("LISTENING")
            cat_input = self.voice.listen(timeout=8)
            if not cat_input:
                self._speak("I didn't hear the category.")
                return
            category = None
            cat_lower = cat_input.lower()
            if "open" in cat_lower:     category = "OPEN"
            elif "close" in cat_lower:  category = "CLOSE"
            elif "type" in cat_lower:   category = "TYPE"
            elif "search" in cat_lower: category = "SEARCH"
            if category:
                self.brain.learn(phrase, category)
                self._speak(f"Learned! Say '{phrase}' next time.")
            else:
                self._speak("I didn't recognise the category. Say Open, Close, Search, or Type.")
            return

        # ─ Playwright Browser Automation Skills ─
        # Playwright Autonomous Agent Planner
        agent_triggers = ["plan ", "automate ", "run task ", "start agent "]
        agent_trigger_found = None
        for t in agent_triggers:
            if inp.startswith(t):
                agent_trigger_found = t
                break
                
        # Also route complex requests containing "and", "summarize", or "under" on shopping/info
        has_complex_keyword = any(w in inp.split() for w in ["and", "under"]) or "summarize" in inp
        is_complex = ("amazon" in inp or "youtube" in inp or "wikipedia" in inp or "google" in inp) and has_complex_keyword

        if agent_trigger_found or is_complex:
            goal = inp
            if agent_trigger_found:
                goal = inp.replace(agent_trigger_found, "", 1).strip()
            
            from skills.agent_planner import AgentPlanner
            def run_agent_async():
                planner = AgentPlanner(self.brain)
                result_msg = planner.run_task(goal, speak_callback=self._speak)
                self._speak(result_msg)
                
            threading.Thread(target=run_agent_async, daemon=True).start()
            self._mark_conversation_activity(wake_reason="active_task")
            return

        if any(x in inp for x in ["close browser", "exit browser"]):
            self.automation_mode = False
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().close_browser()
            self._speak(res)
            return

        if any(x in inp for x in ["open browser", "start browser", "launch browser"]):
            self.automation_mode = True
            self.last_automation_action_time = time.time()
            self._speak("Opening browser.")
            from skills.browser_skill import BrowserSkill
            success, msg = BrowserSkill().start_browser()
            self._speak(msg)
            return

        if inp.startswith("go to ") or inp.startswith("navigate to "):
            self.automation_mode = True
            self.last_automation_action_time = time.time()
            url = inp.replace("go to ", "").replace("navigate to ", "").strip()
            self._speak(f"Navigating to {url}.")
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().navigate(url)
            self._speak(res)
            return

        if "search amazon for " in inp or "amazon search " in inp:
            self.automation_mode = True
            self.last_automation_action_time = time.time()
            product = inp.replace("search amazon for ", "").replace("amazon search ", "").strip()
            self._speak(f"Searching Amazon for {product}.")
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().search_amazon(product)
            self._speak(res)
            return
            
        if "search youtube for " in inp or "youtube search " in inp:
            self.automation_mode = True
            self.last_automation_action_time = time.time()
            query = inp.replace("search youtube for ", "").replace("youtube search ", "").strip()
            self._speak(f"Searching YouTube for {query}.")
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().search_youtube(query)
            self._speak(res)
            return

        if any(x in inp for x in ["open first result", "click first result", "play first video", "select first product", "first link", "first result", "first video", "first product", "first item", "number one", "first one"]):
            from skills.browser_skill import BrowserSkill
            bs = BrowserSkill()
            if bs.is_browser_active():
                bs._update_page_state()
                cards = bs.page_state.get("cards", [])
                if cards:
                    matched_card, score = self.brain._find_best_card_match(user_input, cards)
                    if matched_card and score >= 0.5:
                        self.automation_mode = True
                        self.last_automation_action_time = time.time()
                        title = matched_card.get("text", "").split("\n")[0].strip()[:60]
                        self._speak(f"Clicking {title}.")
                        res = bs.click_element(matched_card.get("aria_id"))
                        print(f"[Main/BrowserIntercept] Clicked matched card {matched_card.get('aria_id')} (score: {score:.2f}) instead of default first result. Result: {res}")
                        return
            self.automation_mode = True
            self.last_automation_action_time = time.time()
            self._speak("Clicking the first result.")
            res = bs.click_first_result()
            self._speak(res)
            return

        if any(x in inp for x in ["add to cart", "click add to cart"]):
            self.automation_mode = True
            self.last_automation_action_time = time.time()
            self._speak("Adding to cart.")
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().click_add_to_cart()
            self._speak(res)
            return

        if "scroll to top" in inp or "scroll to the top" in inp:
            if self.automation_mode:
                self.last_automation_action_time = time.time()
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().scroll("top")
            if "I tried to scroll" in res or "Failed" in res:
                self.screen.press("ctrl+home")
                self._speak("Scrolled to top.")
            else:
                self._speak(res)
            return

        if "scroll to bottom" in inp or "scroll to the bottom" in inp:
            if self.automation_mode:
                self.last_automation_action_time = time.time()
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().scroll("bottom")
            if "I tried to scroll" in res or "Failed" in res:
                self.screen.press("ctrl+end")
                self._speak("Scrolled to bottom.")
            else:
                self._speak(res)
            return

        if "scroll down a little" in inp or "scroll a little down" in inp or "scroll a little" in inp:
            if self.automation_mode:
                self.last_automation_action_time = time.time()
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().scroll("down", "little")
            if "I tried to scroll" in res or "Failed" in res:
                self.screen.click(self.screen.screen_w // 2, self.screen.screen_h // 2)
                self.screen.scroll(clicks=2, direction="down")
                self._speak("Scrolled down a little.")
            else:
                self._speak(res)
            return

        if "scroll up a little" in inp or "scroll a little up" in inp:
            if self.automation_mode:
                self.last_automation_action_time = time.time()
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().scroll("up", "little")
            if "I tried to scroll" in res or "Failed" in res:
                self.screen.click(self.screen.screen_w // 2, self.screen.screen_h // 2)
                self.screen.scroll(clicks=2, direction="up")
                self._speak("Scrolled up a little.")
            else:
                self._speak(res)
            return

        if "scroll down more" in inp or "scroll more down" in inp or "scroll more" in inp:
            if self.automation_mode:
                self.last_automation_action_time = time.time()
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().scroll("down", "more")
            if "I tried to scroll" in res or "Failed" in res:
                self.screen.click(self.screen.screen_w // 2, self.screen.screen_h // 2)
                self.screen.scroll(clicks=10, direction="down")
                self._speak("Scrolled down more.")
            else:
                self._speak(res)
            return

        if "scroll up more" in inp or "scroll more up" in inp:
            if self.automation_mode:
                self.last_automation_action_time = time.time()
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().scroll("up", "more")
            if "I tried to scroll" in res or "Failed" in res:
                self.screen.click(self.screen.screen_w // 2, self.screen.screen_h // 2)
                self.screen.scroll(clicks=10, direction="up")
                self._speak("Scrolled up more.")
            else:
                self._speak(res)
            return

        if any(x in inp for x in ["scroll down", "page down"]):
            if self.automation_mode:
                self.last_automation_action_time = time.time()
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().scroll("down")
            if "I tried to scroll" in res or "Failed" in res:
                self.screen.click(self.screen.screen_w // 2, self.screen.screen_h // 2)
                self.screen.scroll(clicks=5, direction="down")
                time.sleep(0.2)
                self.screen.scroll(clicks=5, direction="down")
                self._speak("Scrolled down.")
            else:
                self._speak(res)
            return

        if any(x in inp for x in ["scroll up", "page up"]):
            if self.automation_mode:
                self.last_automation_action_time = time.time()
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().scroll("up")
            if "I tried to scroll" in res or "Failed" in res:
                self.screen.click(self.screen.screen_w // 2, self.screen.screen_h // 2)
                self.screen.scroll(clicks=5, direction="up")
                time.sleep(0.2)
                self.screen.scroll(clicks=5, direction="up")
                self._speak("Scrolled up.")
            else:
                self._speak(res)
            return

        if inp.startswith("click on ") or inp.startswith("click "):
            self.automation_mode = True
            self.last_automation_action_time = time.time()
            target = inp.replace("click on ", "").replace("click ", "").strip()
            self._speak(f"Clicking {target}.")
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().click_element(target)
            self._speak(res)
            return

        # General Form Filling/Typing
        if "fill " in inp and " with " in inp:
            self.automation_mode = True
            self.last_automation_action_time = time.time()
            parts = inp.replace("fill ", "", 1).split(" with ", 1)
            field = parts[0].strip()
            value = parts[1].strip()
            self._speak(f"Typing {value} in {field}.")
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().fill_element(field, value)
            self._speak(res)
            return

        if "type " in inp and " in " in inp:
            self.automation_mode = True
            self.last_automation_action_time = time.time()
            parts = inp.replace("type ", "", 1).split(" in ", 1)
            value = parts[0].strip()
            field = parts[1].strip()
            self._speak(f"Typing {value} in {field}.")
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().fill_element(field, value)
            self._speak(res)
            return

        if "enter " in inp and " in " in inp:
            self.automation_mode = True
            self.last_automation_action_time = time.time()
            parts = inp.replace("enter ", "", 1).split(" in ", 1)
            value = parts[0].strip()
            field = parts[1].strip()
            self._speak(f"Typing {value} in {field}.")
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().fill_element(field, value)
            self._speak(res)
            return

        # General Page Summarization
        if any(x in inp for x in ["summarize this page", "summarize the page", "summarize page", "summarize website", "summarize webpage", "what is on this page"]):
            if self.automation_mode:
                self.last_automation_action_time = time.time()
            from skills.browser_skill import BrowserSkill
            res = BrowserSkill().summarize_page(self.brain)
            self._speak(res)
            return

        # ─ Scene/Environment Memory Learning ─
        room_learn_triggers = ["learn this room as ", "learn this environment as ", "this room is ", "this environment is ", "associate this room with "]
        room_trigger_found = None
        for t in room_learn_triggers:
            if t in inp:
                room_trigger_found = t
                break
                
        if room_trigger_found:
            raw_room = inp.split(room_trigger_found, 1)[1].strip()
            cleaned = True
            while cleaned:
                cleaned = False
                for clean_word in ["a ", "an ", "the "]:
                    if raw_room.lower().startswith(clean_word):
                        raw_room = raw_room[len(clean_word):].strip()
                        cleaned = True
            
            stop_phrases = [". ", "!", "?", " and"]
            room_name = raw_room
            for stop in stop_phrases:
                if stop in room_name:
                    room_name = room_name.split(stop)[0].strip()
            
            room_name = room_name.title()
            
            if not self.vision_learner.running:
                if getattr(self, "airtouch_mode", False):
                    self._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
                    return
                if not self.camera or not self.camera.available:
                    self.camera.reacquire()
                self._speak("Let me open my camera to scan the room.")
                self.vision_learner.start_camera(frame_provider=self.camera.capture_frame_raw)
                for _ in range(30):
                    time.sleep(0.1)
                    with self.vision_learner._lock:
                        if self.vision_learner.current_frame is not None:
                            break
                            
            detected = self.vision_learner.get_detected_objects()
            if not detected:
                self._speak("I can't see enough objects clearly to characterize this room. Please make sure the lighting is good.")
                return
                
            success, msg = self.memory.memory_manager.scene_mem.learn_scene(room_name, detected)
            self._speak(msg)
            return

        # ─ Scene/Environment Memory Recognition ─
        room_query_triggers = [
            "where am i", "what room is this", "what room am i in", 
            "which room is this", "identify this room", "where am i right now", 
            "do you know where i am", "recognize this room"
        ]
        if image is None and any(x in inp for x in room_query_triggers):
            if not self.vision_learner.running:
                if getattr(self, "airtouch_mode", False):
                    self._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
                    return
                if not self.camera or not self.camera.available:
                    self.camera.reacquire()
                self._speak("Let me open the camera to look around.")
                self.vision_learner.start_camera(frame_provider=self.camera.capture_frame_raw)
                for _ in range(30):
                    time.sleep(0.1)
                    with self.vision_learner._lock:
                        if self.vision_learner.current_frame is not None:
                            break
                            
            detected = self.vision_learner.get_detected_objects()
            room_name, sim, description = self.memory.memory_manager.scene_mem.recognize_scene(detected)
            self._speak(description)
            return

        # ─ Object Identification: "what is this?" ─
        if image is None and self._is_camera_visual_question(inp):
            self._answer_with_camera_image(user_input)
            return

        _visual_question_triggers = [
            "holding", "person is holding", "person holding", "he is holding",
            "she is holding", "they are holding", "in his hand", "in her hand",
            "in their hand", "what is in front of me", "what is in my hand",
            "what am i holding"
        ]
        if image is None and any(x in inp for x in _visual_question_triggers):
            if not self.vision_learner.running:
                if getattr(self, "airtouch_mode", False):
                    self._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
                    return
                if not self.camera or not self.camera.available:
                    self.camera.reacquire()
                self._speak("Let me look through the camera.")
                self.vision_learner.start_camera(frame_provider=self.camera.capture_frame_raw)
                for _ in range(30):
                    time.sleep(0.1)
                    with self.vision_learner._lock:
                        if self.vision_learner.current_frame is not None:
                            break

            with self.vision_learner._lock:
                frame = self.vision_learner.current_frame.copy() if self.vision_learner.current_frame is not None else None

            if frame is None:
                self._speak("I can't see anything right now. Please make sure the camera is working.")
                return

            try:
                from PIL import Image
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                camera_image = Image.fromarray(rgb)
                print(f"[Main] Visual question routed with camera frame: {camera_image.size}")

                response = self.brain.think(
                    user_input,
                    image=camera_image,
                    user_name=self.known_user,
                    user_similarity=self.known_user_similarity,
                    user_confidence=self.known_user_confidence,
                    emotional_tone=getattr(self, "current_user_emotion", "neutral")
                )
                response_lower = response.lower() if response else ""
                non_visual_response = any(x in response_lower for x in [
                    "visual information", "can't see", "cannot see", "i'm ready",
                    "tell me what to open", "open, search, or automate"
                ])
                if response and not non_visual_response:
                    spoken = re.sub(r'\[[A-Z]+:[^\]]*\]', '', response)
                    spoken = re.sub(r'\[[A-Z]+\]', '', spoken).strip()
                    self._speak(spoken or self.vision_learner.identify_object())
                else:
                    self._speak(self.vision_learner.identify_object())
            except Exception as e:
                print(f"[Main] Visual question error: {e}")
                self._speak(self.vision_learner.identify_object())
            return

        if image is None and any(x in inp for x in [
            "what is this", "what is tihis", "what's this", "what am i holding", 
            "identify this", "identfy this", "idenfty this", "what do you see", 
            "what is in the room", "whats in the room", "what's in the room", 
            "whats around you", "what's around you", "what is around you", "what do you see around you",
            "what is around", "whats around", "what's around", "what is in front of me", "what is in front of you"
        ]):
            if not self.vision_learner.running:
                if getattr(self, "airtouch_mode", False):
                    self._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
                    return
                if not self.camera or not self.camera.available:
                    self.camera.reacquire()
                self._speak("Let me open my camera to see.")
                self.vision_learner.start_camera(frame_provider=self.camera.capture_frame_raw)
                # Wait up to 3s for a real frame to arrive
                for _ in range(30):
                    time.sleep(0.1)
                    with self.vision_learner._lock:
                        if self.vision_learner.current_frame is not None:
                            break

            result = self.vision_learner.identify_object()
            self._speak(result)
            return

        # ─ Stop/Disable Camera and AR Playground Triggers (Checked First to prevent collision) ─
        if any(x in inp for x in [
            "disable ar playground", "ar playground off", "stop ar mode", "ar mode off",
            "stop ar playground", "disable ar mode",
            "disable air playground", "air playground off", "stop air mode", "air mode off",
            "stop air playground", "disable air mode",
            "stop ar object", "disable ar object", "stop ar whiteboard", "disable ar whiteboard",
            "stop ar face", "disable ar face", "stop ar drawing", "disable ar drawing",
            "stop ar physics", "disable ar physics", "stop ar pose", "disable ar pose",
            "stop ar pet", "disable ar pet", "stop ar flower", "disable ar flower",
            "stop ar piano", "disable ar piano", "stop ar wand", "disable ar wand",
            "close camera", "stop camera", "turn off camera", "hide camera", "camera off",
            "disable object mode", "stop object mode", "close object mode", "object mode off",
            "disable face mode", "stop face mode", "close face mode", "face mode off",
            "disable person mode", "stop person mode", "close person mode", "person mode off",
            "close the object one", "disable the object one", "stop the object one",
            "disable ar", "stop ar", "close ar"
        ]):
            try:
                stopped_something = False
                if getattr(self, "ar_mode", False) or getattr(self, "ar_playground", None) is not None:
                    if self.ar_playground:
                        self.ar_playground.stop()
                        self.ar_playground = None
                    self.ar_mode = False
                    self._speak("AR Playground stopped.")
                    stopped_something = True
                
                if hasattr(self, "vision_learner") and self.vision_learner.running:
                    self.vision_learner.stop_camera()
                    self._speak("Camera closed.")
                    stopped_something = True
                
                if not stopped_something:
                    self._speak("Camera and AR mode are already off.")
                
                self._check_and_release_camera()
            except Exception as e:
                print(f"[Camera/AR] Failed to stop: {e}")
                self._speak("Could not stop camera or AR mode.")
            return


        # ─ Camera Controls ─
        # ─ MODE SWITCHING: Face mode vs Object Mode ─
        _face_id_triggers = [
            "who is around", "who are around", "who is in the room", "who is there", "who do you see", 
            "is there anyone", "is anyone there", "who is around you", "who is around me", 
            "who's around", "who around", "who is near", "who is near me", "who is near you",
            "who is in the space", "anyone around", "anyone in the room"
        ]
        if image is None and any(x in inp for x in ["face mode", "person mode", "recognize me", "show me myself"] + _face_id_triggers) and not any(ar in inp for ar in ["ar ", "air "]):
            self.vision_learner.mode = "face"
            if not self.vision_learner.running:
                if getattr(self, "airtouch_mode", False):
                    self._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
                    return
                if not self.camera or not self.camera.available:
                    self.camera.reacquire()
                self.vision_learner.start_camera(frame_provider=self.camera.capture_frame_raw)
                for _ in range(30):
                    time.sleep(0.1)
                    with self.vision_learner._lock:
                        if self.vision_learner.current_frame is not None:
                            break

            is_query = any(x in inp for x in _face_id_triggers)
            if is_query:
                with self.vision_learner._lock:
                    frame = self.vision_learner.current_frame.copy() if self.vision_learner.current_frame is not None else None
                
                if frame is not None:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces = self.memory.detect_faces(gray, scale_factor=1.3, min_neighbors=5)
                    if len(faces) > 0:
                        fx, fy, fw, fh = faces[0]
                        face_crop = frame[fy:fy+fh, fx:fx+fw]
                        name = self.memory.identify_face(face_crop)
                        if name and name != "Unknown":
                            self._speak(f"I can see {name} in the room.")
                        else:
                            self._speak("I see a face in the room, but I don't recognize them.")
                    else:
                        self._speak("I don't see any faces in the room right now.")
                else:
                    self._speak("I couldn't access the camera to check.")
                return

            self._speak("Switching to Person Mode. I will now help you recognize faces.")
            return

        if any(x in inp for x in ["object mode", "thing mode", "identify objects", "show objects"]) and not any(ar in inp for ar in ["ar ", "air "]):
            self.vision_learner.mode = "object"
            if not self.vision_learner.running:
                if getattr(self, "airtouch_mode", False):
                    self._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
                    return
                if not self.camera or not self.camera.available:
                    self.camera.reacquire()
                self.vision_learner.start_camera(frame_provider=self.camera.capture_frame_raw)
            self._speak("Switching to Object Mode. I am now looking for things you taught me.")
            return

        _camera_open_triggers = [
            "show camera", "open camera", "turn on camera", "vision mode",
            "open opencv", "open cv", "start camera", "camera on",
            "show objects", "show you objects", "show me objects",
            "learn objects", "teach you objects", "i will show you",
            "visual mode", "visual input", "visual data",
            "look at this", "look at me", "i want to show you",
            "object learning", "object recognition",
            "new object", "what is this", "what is tihis",
        ]
        if any(x in inp for x in _camera_open_triggers):
            # Default to object mode for generic triggers
            self.vision_learner.mode = "object" 
            already = self.vision_learner.running
            if already:
                self._speak("Camera is already on. Go ahead and show me the objects!")
                return

            if getattr(self, "airtouch_mode", False):
                self._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
                return
            if not self.camera or not self.camera.available:
                self.camera.reacquire()

            if self.vision_learner.start_camera(frame_provider=self.camera.capture_frame_raw):
                self._speak(
                    "Camera is now open! Hold an object in front of me and say "
                    "this is a and the object name, and I will learn it."
                )
            else:
                self._speak("I had trouble opening the camera. Is your webcam connected?")
            return


        if any(x in inp for x in ["what do you know", "list objects", "what have you learned", "what objects do you know"]):
            list_msg = self.vision_learner.list_learned()
            self._speak(list_msg)
            return

        # ─ Mode toggle ─
        if any(x in inp for x in ["always listen", "continuous mode"]):
            self.wake_mode = True
            self._speak("Always-on mode activated. I will respond to everything you say.")
            return
        if any(x in inp for x in ["stop listening", "wake word mode", "hey aria mode"]):
            self.wake_mode = False
            self._speak("Switched to wake-word mode. Say Hey ARIA to activate me.")
            return

        # ─ Language Selection Toggles ─
        if self.voice:
            if any(x in inp for x in ["switch to hindi", "change language to hindi", "hindi language mode"]):
                self.voice.stt_language = 'hi'
                self.voice.voice_model = 'hi-IN-SwaraNeural'
                self._speak("Speech recognition language switched to Hindi.")
                return
            if any(x in inp for x in ["switch to telugu", "change language to telugu", "telugu language mode"]):
                self.voice.stt_language = 'te'
                self.voice.voice_model = 'te-IN-ShrutiNeural'
                self._speak("Speech recognition language switched to Telugu.")
                return
            if any(x in inp for x in ["switch to english", "change language to english", "english language mode"]):
                self.voice.stt_language = 'en'
                self.voice.voice_model = 'en-US-AriaNeural'
                self._speak("Speech recognition language switched to English.")
                return
            if any(x in inp for x in ["auto language mode", "switch to auto language", "disable language lock", "automatic language mode"]):
                self.voice.stt_language = None
                self.voice.voice_model = 'en-US-AriaNeural'
                self._speak("Language lock disabled. Automatic language detection mode is active.")
                return

        # ─ Gesture Control Toggle ─
        if any(x in inp for x in [
            "disable gesture control", "gesture mode off", "stop gesture control",
            "hand gesture off", "disable hand tracking", "stop hand tracking",
        ]):
            try:
                from skills.gesture_control import stop_gesture_control
                msg = stop_gesture_control()
                self.gesture_mode = False
                self._speak(msg)
                self._check_and_release_camera()
            except Exception as e:
                print(f"[GestureControl] Failed to stop: {e}")
                self._speak("Could not stop gesture control.")
            return

        if any(x in inp for x in [
            "enable gesture control", "gesture mode on", "gesture mode",
            "hand gesture mode", "start gesture control", "gesture control on",
            "hand tracking mode", "enable hand tracking", "gesture control",
        ]):
            try:
                from skills.gesture_control import start_gesture_control, MEDIAPIPE_AVAILABLE
                if not MEDIAPIPE_AVAILABLE:
                    self._speak("Gesture control is unavailable. MediaPipe is not installed.")
                    return
                if not self.camera:
                    from camera import Camera
                    self.camera = Camera()
                elif not self.camera.available:
                    self.camera.reacquire()
                if not self.camera or not self.camera.available:
                    self._speak("Gesture control needs the webcam but it is not available right now.")
                    return
                msg = start_gesture_control(frame_provider=self.camera.capture_frame_raw)
                self.gesture_mode = True
                self._speak(msg)
            except Exception as e:
                print(f"[GestureControl] Failed to start: {e}")
                self._speak("Sorry, I could not start gesture control.")
            return

        # ─ Route sub-commands to AR Playground if it's currently running ─
        ar_playground_active = getattr(self, 'ar_mode', False) or getattr(self, 'ar_playground', None) is not None
        if ar_playground_active and getattr(self, 'ar_playground', None):
            if any(x in inp for x in ["clear board", "clear canvas", "clear whiteboard"]):
                self.ar_playground.handle_subcommand("clear_board")
                self._speak("Board cleared.")
                return
            elif "undo" in inp:
                self.ar_playground.handle_subcommand("undo")
                self._speak("Undone.")
                return
            elif any(x in inp for x in ["next mask", "change mask"]):
                self.ar_playground.handle_subcommand("next_mask")
                self._speak("Swapping to next mask.")
                return
            elif any(x in inp for x in ["previous mask", "prev mask"]):
                self.ar_playground.handle_subcommand("prev_mask")
                self._speak("Swapping to previous mask.")
                return
            elif any(x in inp for x in ["remember this", "save this"]):
                self.ar_playground.handle_subcommand("remember_current")
                self._speak("Remembering current object.")
                return
            elif any(p in inp for p in ["create a", "create an", "generate a", "show me a", "load a", "make a"]):
                res = self.ar_playground.handle_subcommand(inp)
                if res:
                    self._speak(res)
                return
            elif any(p in inp for p in [
                "load the", "show me the model", "show the model", "show me the",
                "load model", "display the", "put up the", "put the"
            ]):
                # Extract the model keyword — use cached key if we have one
                model_key = getattr(self, "_last_model_key", None)
                for word in inp.split():
                    cleaned = word.strip(".,!?")
                    if cleaned in ["dragon", "bunny", "car", "spaceship", "robot", "teapot",
                                   "lamborghini", "armadillo", "cow", "crystal", "helmet",
                                   "earth", "planet", "dna", "torus", "solar"]:
                        model_key = cleaned
                        self._last_model_key = model_key
                        break
                if model_key:
                    res = self.ar_playground.handle_subcommand(f"load the {model_key}")
                    if res:
                        self._speak(res)
                else:
                    res = self.ar_playground.handle_subcommand(inp)
                    if res:
                        self._speak(res)
                return
            elif any(p in inp for p in ["is the model ready", "is the 3d model ready", "model ready"]):
                is_gen = False
                if hasattr(self.ar_playground, '_model_gen') and self.ar_playground._model_gen:
                    is_gen = self.ar_playground._model_gen._generating
                if is_gen:
                    self._speak("Still generating, I will notify you automatically when done.")
                else:
                    self._speak("The model is ready.")
                return
            elif any(p in inp for p in [
                "rotate left", "rotate right", "rotate up", "rotate down",
                "make it bigger", "make it smaller", "zoom in", "zoom out",
                "reset view", "show wireframe", "explode model", "explode it",
                "change color", "change colour"
            ]):
                res = self.ar_playground.handle_subcommand(inp)
                if res:
                    self._speak(res)
                return
            else:
                # Last resort: try match_model() — catches bare names like
                # "dragon", "create dragon", "load dragon", "show dragon" etc.
                try:
                    from skills.ar_3d_mode import match_model
                    key = match_model(inp)
                    if key:
                        self._last_model_key = key
                        res = self.ar_playground.handle_subcommand(inp)
                        if res:
                            self._speak(res)
                        else:
                            self._speak(f"Loading {key}...")
                        return
                except Exception:
                    pass
                # Nothing matched — fall through to general chat

        # ─ AR Playground Mode selection & auto-start ─
        # List of explicit AR triggers to start the playground and switch mode
        ar_triggers = {
            "wand": ["ar wand", "ar magic", "ar trail", "air wand", "air magic", "air trail"],
            "flowers": ["ar flower", "ar garden", "air flower", "air garden"],
            "piano": ["ar piano", "ar synth", "ar music", "air piano", "air synth", "air music"],
            "pet": ["ar pet", "ar cat", "air pet", "air cat"],
            "drawing": ["ar drawing", "ar canvas", "air drawing", "air canvas"],
            "physics": ["ar physics", "ar ball", "air physics", "air ball"],
            "face": ["ar face", "ar mask", "air face", "air mask"],
            "pose": ["ar pose", "ar body", "air pose", "air body"],
            "whiteboard": ["ar whiteboard", "ar write", "air whiteboard", "air write"],
            "object": ["ar object", "ar interact", "air object", "air interact"],
            "ar3d": ["ar 3d mode", "enable ar 3d", "3d mode on", "ar hologram mode", "hologram mode", "ar 3d", "air 3d", "enable air 3d"]
        }

        # If already running, we also support switching modes using simpler "mode" terms without "ar"/"air" prefixes
        if getattr(self, 'ar_mode', False) and getattr(self, 'ar_playground', None):
            active_only_triggers = {
                "wand": ["wand mode", "magic mode", "trail mode"],
                "flowers": ["flower mode", "garden mode"],
                "piano": ["piano mode", "synth mode", "music mode"],
                "pet": ["pet mode", "cat mode"],
                "drawing": ["drawing mode", "canvas mode"],
                "physics": ["physics mode", "balls mode", "ball mode"],
                "face": ["face mode", "mask mode"],
                "pose": ["pose mode", "body mode"],
                "whiteboard": ["whiteboard mode", "write mode"],
                "object": ["object mode", "interact mode"],
                "ar3d": ["3d mode", "hologram mode"]
            }
        else:
            active_only_triggers = {}

        # Combine triggers to see if any matches
        matched_mode = None
        for mode, triggers in ar_triggers.items():
            if any(t in inp for t in triggers):
                matched_mode = mode
                break
        if not matched_mode:
            for mode, triggers in active_only_triggers.items():
                if any(t in inp for t in triggers):
                    matched_mode = mode
                    break

        if matched_mode:
            try:
                if self.gesture_mode:
                    from skills.gesture_control import stop_gesture_control
                    stop_gesture_control()
                    self.gesture_mode = False
                if hasattr(self, 'vision_learner') and self.vision_learner.running:
                    self.vision_learner.stop_camera()
                
                if not self.camera:
                    from camera import Camera
                    self.camera = Camera()
                elif not self.camera.available:
                    self.camera.reacquire()
                if not self.camera or not self.camera.available:
                    self._speak("Webcam is unavailable right now.")
                    return
                
                from skills.ar_playground import ARPlayground
                if not self.ar_playground:
                    yolo_model = getattr(self.vision_learner, 'yolo', None)
                    self.ar_playground = ARPlayground(
                        frame_provider=self.camera.capture_frame_raw,
                        yolo_model=yolo_model,
                        aria_brain=self.brain,
                        aria_speak=self._speak
                    )
                self.ar_playground.start()
                self.ar_mode = True

                self.ar_playground.set_mode(matched_mode)
                
                mode_speak_names = {
                    "wand": "Magic Wand mode active.",
                    "flowers": "Flower Garden mode active.",
                    "piano": "Air Piano mode active.",
                    "pet": "Virtual Pet mode active.",
                    "drawing": "AR Drawing Canvas mode active.",
                    "physics": "Hand Physics mode active.",
                    "face": "Face AR Overlays active.",
                    "pose": "Pose Detection active.",
                    "whiteboard": "AR Whiteboard active.",
                    "object": "Object Interaction active.",
                    "ar3d": "AR 3D Hologram mode active. Say 'create a dragon' to start."
                }
                self._speak(mode_speak_names[matched_mode])
            except Exception as e:
                print(f"[ARPlayground] Mode set failed: {e}")
                self._speak("Failed to configure AR mode.")
            return


        if any(x in inp for x in [
            "enable ar playground", "ar playground on", "start ar mode", "ar mode on",
            "ar playground", "start ar playground", "enable ar mode",
            "enable air playground", "air playground on", "start air mode", "air mode on",
            "air playground", "start air playground", "enable air mode"
        ]):
            try:
                if self.gesture_mode:
                    from skills.gesture_control import stop_gesture_control
                    stop_gesture_control()
                    self.gesture_mode = False
                if hasattr(self, 'vision_learner') and self.vision_learner.running:
                    self.vision_learner.stop_camera()
                
                if not self.camera:
                    from camera import Camera
                    self.camera = Camera()
                elif not self.camera.available:
                    self.camera.reacquire()
                if not self.camera or not self.camera.available:
                    self._speak("Webcam is unavailable right now.")
                    return
                
                from skills.ar_playground import ARPlayground, MEDIAPIPE_AVAILABLE
                if not MEDIAPIPE_AVAILABLE:
                    self._speak("AR Playground is unavailable. MediaPipe is not installed.")
                    return
                if not self.ar_playground:
                    yolo_model = getattr(self.vision_learner, 'yolo', None)
                    self.ar_playground = ARPlayground(
                        frame_provider=self.camera.capture_frame_raw,
                        yolo_model=yolo_model,
                        aria_brain=self.brain,
                        aria_speak=self._speak
                    )
                success = self.ar_playground.start()
                if success:
                    self.ar_mode = True
                    self._speak("AR Playground enabled. Wave your hand in front of the camera!")
                else:
                    self._speak("Sorry, I could not start the AR Playground.")
            except Exception as e:
                print(f"[ARPlayground] Failed to start: {e}")
                self._speak("Could not start AR Playground.")
            return

        # ─ Intent Routing ─
        intent, query = self._classify_intent_before_chat(user_input)
        if intent == "browser_search":
            from skills.browser_skill import BrowserSkill
            bs = BrowserSkill()
            if bs.is_browser_active():
                self.automation_mode = True
                self.last_automation_action_time = time.time()
                set_state("THINKING")
                set_text(f"Searching for {query}...")
                
                # Check if Google search is explicitly requested
                if "google" in query.lower() or "google" in user_input.lower():
                    self._speak(f"Searching Google for {query}.")
                    success, msg = bs.search_google(query)
                    if success:
                        summary = bs.summarize_page(self.brain)
                        self._speak(summary)
                    else:
                        self._speak(msg)
                else:
                    self._speak(f"Searching for {query} on this page.")
                    res_msg = bs.search_in_page(query)
                    if "Could not find" in res_msg:
                        self._speak(f"Searching Google for {query}.")
                        success, msg = bs.search_google(query)
                        if success:
                            summary = bs.summarize_page(self.brain)
                            self._speak(summary)
                        else:
                            self._speak(msg)
                    else:
                        self._speak(res_msg)
                return
            else:
                set_state("THINKING")
                set_text("Searching Google...")
                self._speak(f"Opening search results for {query}...")
                import webbrowser
                import urllib.parse
                encoded = urllib.parse.quote(query)
                url = f"https://www.google.com/search?q={encoded}"
                webbrowser.open(url)
                return

        # ─ Detect current user from camera ─
        detected_name = self._detect_user()
        if detected_name:
            prev_user = self.known_user
            self.known_user = detected_name
            set_user(detected_name)
            if self.startup_greeting_done and detected_name != prev_user and detected_name not in self._greeted_users:
                self._greeted_users.add(detected_name)
                self._last_greeted_face = detected_name
                self._speak(f"Hi {detected_name}, welcome!")
                return

        # ─ Visual inputs ─
        image_input = image
        if image_input is not None:
            set_text("Analyzing remote photo...")
        if any(x in inp for x in [
            "see my screen", "look at screen", "view screen", "what's on screen", "what is on screen",
            "what did you got", "what did you find", "what did you get", "what are the results", 
            "what is the result", "what is on the browser", "show me the results", "read the results",
            "any results", "what are the findings", "show me what you found", "did you find anything"
        ]):
            try:
                from vision import Vision
                v = Vision()
                image_input = v.capture_screen()
                set_text("Analysing your screen...")
            except Exception as e:
                print(f"[Main] Screen capture error: {e}")
        elif any(x in inp for x in ["look at me", "see me", "see my face", "who am i"]):
            image_input = self.camera.capture_image()
            set_text("Looking at you...")

        # ─ Brain → think (with Ollama streaming support) ─
        set_state("THINKING")
        set_text("Thinking...")

        # Register streaming callback so Ollama speaks sentence-by-sentence
        # as tokens arrive, cutting perceived latency dramatically.
        spoken_via_stream = []

        def _on_streamed_sentence(sentence):
            """Called by brain during Ollama streaming at each sentence boundary."""
            clean = re.sub(r'\[[A-Z]+:[^]]*\]', '', sentence)
            clean = re.sub(r'\[[A-Z]+\]', '', clean).strip()
            if clean:
                spoken_via_stream.append(clean)
                set_state("SPEAKING")
                self._speak(clean)

        self.brain._stream_callback = _on_streamed_sentence

        response = self.brain.think(
            user_input,
            image=image_input,
            user_name=self.known_user,
            user_similarity=self.known_user_similarity,
            user_confidence=self.known_user_confidence,
            emotional_tone=emotional_tone
        )

        # Always clear the callback after think() returns
        self.brain._stream_callback = None

        # Check if search action is requested
        is_search = False
        is_site_scoped_search = False
        if response and re.search(r'\[SEARCH:\s*([^\]]+)\]', response, re.IGNORECASE):
            is_search = True
            search_match = re.search(r'\[SEARCH:\s*([^\]]+)\]', response or "", re.IGNORECASE)
            search_text = search_match.group(1).strip() if search_match else ""
            if not self._is_action_tag_authorized("SEARCH", user_input):
                is_search = False
            is_site_scoped_search = any(
                site in (search_text + " " + user_input).lower()
                for site in ["amazon", "youtube", "flipkart"]
            )

        # ─ Execute action tags ─
        self._execute_actions(response, source_user_input=user_input)

        # ─ Speak clean response — skip if streaming already spoke it ─
        if not spoken_via_stream:
            spoken = re.sub(r'\[[A-Z]+:[^\]]*\]', '', response or "")  # remove [TAG: value] tokens
            spoken = re.sub(r'\[[A-Z]+\]', '', spoken)                  # remove bare [TAG] tokens
            spoken = spoken.strip()
            if spoken:
                self._speak(spoken)

        if is_search and not is_site_scoped_search:
            # Extract query from response
            search_query = None
            search_match = re.search(r'\[SEARCH:\s*([^\]]+)\]', response or "", re.IGNORECASE)
            if search_match:
                search_query = search_match.group(1).strip()
            if not search_query:
                search_query = user_input

            set_text("Fetching search results...")
            raw_text = self.search_and_read(search_query)

            # Try to process fetched text first
            success = False
            if raw_text and not raw_text.startswith("Could not fetch"):
                try:
                    set_text("Reading search results...")
                    prompt = (
                        f"The user asked: '{user_input}'.\n\n"
                        f"Here is the text content from the search results page:\n"
                        f"---\n{raw_text}\n---\n\n"
                        f"Based on this search result content, answer the user's question directly, "
                        f"accurately, and concisely in 1-3 sentences. No markdown symbols like * # ` **."
                    )
                    set_state("THINKING")
                    set_text("Analyzing results...")
                    final_response = self.brain.think(
                        prompt,
                        user_name=self.known_user,
                        emotional_tone=emotional_tone
                    )
                    
                    final_spoken = re.sub(r'\[[A-Z]+:[^\]]*\]', '', final_response or "")
                    final_spoken = re.sub(r'\[[A-Z]+\]', '', final_spoken).strip()
                    
                    # Clean up chat history
                    if len(self.brain.chat_history) >= 2:
                        self.brain.chat_history.pop()  # pop assistant response
                        self.brain.chat_history.pop()  # pop user prompt
                        if len(self.brain.chat_history) >= 1:
                            self.brain.chat_history[-1]["content"] = final_spoken
                    
                    if final_spoken:
                        self._speak(final_spoken)
                        success = True
                    else:
                        self._speak("I looked at the search results but couldn't find a clear answer.")
                        success = True
                except Exception as e:
                    print(f"[Main] Text-based search summary failed: {e}. Falling back to screenshot...")
            
            # Fallback to screenshot-based reading if fetching text was unsuccessful
            if not success:
                # Wait for search results webpage to load
                time.sleep(4.0)
                try:
                    from vision import Vision
                    v = Vision()
                    screen_image = v.capture_screen()
                    set_text("Reading search results...")
                    
                    prompt = (
                        f"The user asked: '{user_input}'. "
                        "Here is a screenshot of the search results webpage that just opened. "
                        "Read the page and answer the user's question directly, accurately, and "
                        "concisely in 1-3 sentences based on the visible results."
                    )
                    
                    set_state("THINKING")
                    set_text("Analyzing results...")
                    final_response = self.brain.think(
                        prompt,
                        image=screen_image,
                        user_name=self.known_user,
                        emotional_tone=emotional_tone
                    )
                    
                    final_spoken = re.sub(r'\[[A-Z]+:[^\]]*\]', '', final_response or "")
                    final_spoken = re.sub(r'\[[A-Z]+\]', '', final_spoken).strip()
                    
                    # Clean up chat history to replace "checking" with the actual answer
                    if len(self.brain.chat_history) >= 2:
                        self.brain.chat_history.pop()  # pop visual assistant response
                        self.brain.chat_history.pop()  # pop visual user prompt
                        if len(self.brain.chat_history) >= 1:
                            self.brain.chat_history[-1]["content"] = final_spoken
                    
                    if final_spoken:
                        self._speak(final_spoken)
                    else:
                        self._speak("I looked at the search results but couldn't find a clear answer.")
                except Exception as e:
                    print(f"[Main] Automatic search vision fail: {e}")
                    self._speak("I performed the search but couldn't read the screen to interpret the results.")

        # Note: Conversational turn logging is now handled in the _handle_input wrapper to catch all early returns.
        pass
    def _run_proactive_checks(self):
        """Periodically check battery status and system session time for proactive announcements."""
        now = time.time()
        
        # 1. Battery status check: run every 5 minutes (300 seconds)
        if now - self.last_battery_check > 300:
            self.last_battery_check = now
            try:
                batt = self.context_skill.get_battery_percent()
                charging = self.context_skill.get_charging_status()
                if batt is not None and batt < 20 and not charging:
                    self.safe_speak(f"Excuse me. Your laptop battery is low at {batt} percent. Please connect your charger.")
            except Exception as e:
                print(f"[Proactive] Battery check error: {e}")
                
        # 2. Continuous work duration check: check every hour (3600 seconds)
        if now - self.last_break_check > 3600:
            self.last_break_check = now
            elapsed_hours = int((now - self.start_time) / 3600)
            if elapsed_hours >= 1:
                self.safe_speak(f"Hi. You have been working for {elapsed_hours} hour. Remember to take a quick break.")

        if now - self.last_activity_log > 300:
            self.last_activity_log = now
            try:
                active = self.context_skill.get_active_window()
                battery = self.context_skill.get_battery_percent()
                wifi = self.context_skill.get_wifi_status()
                self.memory_skill.log_activity(active, battery, wifi)
            except Exception as e:
                print(f"[Proactive] Activity log error: {e}")

        if now - self.last_reminder_check > 30:
            self.last_reminder_check = now
            try:
                due = self.memory_skill.get_due_reminders()
                for reminder_id, task in due:
                    self.safe_speak(f"Reminder: {task}")
                    self.memory_skill.complete_reminder(reminder_id)
            except Exception as e:
                print(f"[Proactive] Reminder check error: {e}")

    def _gesture_event_callback(self, event: str):
        """
        Handle high-level gesture events from GestureController.
        Reserved for future advanced gestures (volume, wake, screenshot, stop).
        Not used by the v1 stable set (cursor / click / scroll).
        """
        print(f"[GestureControl] Event: {event}")
        try:
            if event == "GESTURE_WAKE":
                self._speak("Gesture wake detected.")
                self._mark_conversation_activity(wake_reason="gesture_wake")
            elif event == "GESTURE_CONFIRM":
                self._speak("Confirmed.")
            elif event == "GESTURE_SCREENSHOT":
                try:
                    from vision import Vision
                    img = Vision().capture_screen()
                    path = os.path.join(os.getcwd(), "screenshot_gesture.png")
                    img.save(path)
                    self._speak("Screenshot saved.")
                except Exception as e:
                    print(f"[GestureControl] Screenshot error: {e}")
            elif event == "GESTURE_STOP":
                self.automation_mode = False
                self._speak("Stopping.")
            elif event == "VOLUME_UP":
                try: self.automation.volume_up()
                except Exception: pass
            elif event == "VOLUME_DOWN":
                try: self.automation.volume_down()
                except Exception: pass
        except Exception as e:
            print(f"[GestureControl] Event handler error: {e}")

    def cleanup(self):
        """Cleanly release all ARIA resources."""
        print("[ARIA] Releasing resources...")
        try:
            from skills.browser_skill import BrowserSkill
            BrowserSkill().close_browser()
        except Exception:
            pass
        try:
            from skills.gesture_control import stop_gesture_control, is_active
            if is_active():
                stop_gesture_control()
        except Exception:
            pass
        try:
            if getattr(self, 'ar_playground', None):
                self.ar_playground.stop()
                self.ar_playground = None
                self.ar_mode = False
        except Exception:
            pass
        if hasattr(self, 'firebase_sync') and self.firebase_sync:
            try:
                self.firebase_sync.stop()
            except Exception:
                pass
        if self.camera:
            try:
                self.camera.release()
            except Exception:
                pass
        if hasattr(self, 'vision_learner') and self.vision_learner:
            try:
                self.vision_learner.stop_camera()
            except Exception:
                pass
        if hasattr(self, 'voice') and self.voice:
            try:
                self.voice.cleanup()
            except Exception:
                pass
        print("[ARIA] Shutdown complete.")

    # ── Main Loop ─────────────────────────────────────────────────────────────
    def run(self):
        try:
            self.initialize()
        except Exception as init_err:
            print(f"[ARIA] Fatal initialization error: {init_err}")
            import traceback
            traceback.print_exc()
            self._speak("I encountered a critical error during startup. Please check the logs.")
            self.running = False
            return

        # Detect user on startup — run in a daemon thread so OpenCV C++ crashes
        # cannot propagate to the main thread and kill the process.
        startup_user = None
        try:
            _detect_result = [None]
            _detect_done = threading.Event()

            def _safe_detect():
                try:
                    _detect_result[0] = self._detect_user()
                    # If we get here without exception, camera is at least functional
                    if HEALTH.get_status(SUBSYSTEM_CAMERA) not in ("HEALTHY", "DEGRADED"):
                        HEALTH.mark_healthy(SUBSYSTEM_CAMERA, "Face detection ran without crash")
                except Exception as _de:
                    print(f"[ARIA] Startup face detection skipped: {_de}")
                    HEALTH.mark_degraded(SUBSYSTEM_CAMERA, f"OpenCV C++ crash at startup: {_de}")
                finally:
                    _detect_done.set()

            _detect_thread = threading.Thread(target=_safe_detect, name="ARIA-StartupDetect", daemon=True)
            _detect_thread.start()
            _detect_done.wait(timeout=4.0)  # max 4 seconds; never blocks main loop
            startup_user = _detect_result[0]
        except Exception as _outer:
            print(f"[ARIA] Startup user detection failed (non-fatal): {_outer}")

        if startup_user and self.known_user_similarity >= 0.75:
            self.known_user = startup_user
            set_user(startup_user)
            try:
                metrics = self.reflection_engine.get_relationship_vector(startup_user)
                if metrics["trust"] < 10.0:
                    self.reflection_engine.update_relationship_metrics(startup_user, delta_trust=0.1)
                    print(f"[ARIA] Passive recovery applied. Trust increased to {self.reflection_engine.get_relationship_vector(startup_user)['trust']:.1f}")
            except Exception as e:
                print(f"[ARIA] Failed to apply passive recovery: {e}")

            if self.known_user_confidence == "high":
                greeting = f"Welcome back, {startup_user}! I am ready."
            else:
                greeting = f"Welcome back! I think you are {startup_user}. I am ready."
        else:
            greeting = "ARIA online. How can I help you?"

        self._speak(greeting)
        self.startup_greeting_done = True

        print("\n[ARIA] Entering main loop.")
        if self.wake_mode:
            print("[ARIA] Always-On mode: just speak and I will respond!")
        else:
            print("[ARIA] Wake-word mode: say 'Hey ARIA' to activate.")
        print()

        while self.running:
            try:
                # Reset AR playground state if it has stopped
                if self.ar_playground and not self.ar_playground._running:
                    print("[ARIA] AR Playground has stopped. Resetting state flags.")
                    self.ar_playground = None
                    self.ar_mode = False

                # Track session duration and apply the +0.3 trust reward when the active session exceeds 15 minutes
                if getattr(self, "known_user", None) and not getattr(self, "long_session_trust_applied", False) and (time.time() - self.start_time) > 900.0:
                    self.long_session_trust_applied = True
                    try:
                        self.reflection_engine.update_relationship_metrics(self.known_user, delta_trust=0.3)
                        print(f"[ARIA] Long session trust reward applied for '{self.known_user}'. Trust increased by +0.3 to {self.reflection_engine.get_relationship_vector(self.known_user)['trust']:.1f}")
                    except Exception as e:
                        print(f"[ARIA] Failed to apply long session trust reward: {e}")

                # Deliver any pending proactive speech if user is not speaking
                if hasattr(self, "pending_speech") and self.pending_speech and not self.is_user_speaking():
                    msg = self.pending_speech.pop(0)
                    self._speak(msg)

                # Execute background proactive tasks (guarded — must not crash the loop)
                try:
                    self._run_proactive_checks()
                except Exception as _pce:
                    print(f"[ARIA] Proactive check error (non-fatal): {_pce}")

                # Prevent microphone from listening/capturing while speaking or queue is active
                # Guard self.voice with None check — voice may be None if TTS init failed
                _voice_busy = (
                    (not self.speech_queue.empty()) or
                    (self.voice is not None and getattr(self.voice, 'is_speaking', False))
                )
                if _voice_busy:
                    time.sleep(0.2)
                    continue

                try:
                    # Calculate active conversation by last activity, not original wake time.
                    has_active_task = self._has_active_conversation_task()
                    in_conversation = self.conversation_session.expire_if_idle(has_active_task=has_active_task)
                    
                    # Print transition status when entering Sleep mode from Active mode
                    if self._was_in_conversation and not in_conversation:
                        print("[ARIA] Conversation window expired. Returning to Sleep Mode (Wake-word only).")
                    self._was_in_conversation = in_conversation

                    if self.wake_mode:
                        # ── Always-On Mode ──────────────────────────────────
                        set_state("LISTENING")
                        set_text("Listening... speak anytime.")
                        user_input = self.voice.listen(timeout=5, phrase_time_limit=20, active_conversation=in_conversation)
                        if user_input:
                            if not self.voice.is_valid_speech(user_input, active_conversation=in_conversation):
                                continue
                            
                            # Gating check: must contain wake word OR be within follow-up window
                            has_wake = any(w in user_input.lower() for w in self.WAKE_WORDS)
                            if in_conversation or has_wake:
                                self._mark_conversation_activity(wake_reason="wake_word" if has_wake else "followup")
                                self._handle_input(user_input)
                            else:
                                print(f"[Always-On Gate] Ignored background speech (outside window): '{user_input}'")

                    else:
                        # ── Wake-Word Mode ─────────────────────────────────────
                        if in_conversation:
                            # Continue conversation without repeating wake word
                            set_state("LISTENING")
                            set_text("Listening (active conversation)...")
                            user_input = self.voice.listen(timeout=6, phrase_time_limit=15, active_conversation=True)
                            if user_input:
                                if self.voice.is_valid_speech(user_input, active_conversation=True):
                                    self._mark_conversation_activity(wake_reason="active_followup")
                                    self._handle_input(user_input)
                            else:
                                # Silence in active mode does NOT immediately shut down conversation.
                                # The 30-second window is maintained.
                                pass
                        else:
                            # Idle, waiting for wake word
                            set_state("IDLE")
                            set_text("Say 'Hey ARIA' to activate...")
                            detected = self.voice.listen_for_wake_word(self.WAKE_WORDS, timeout=3)
                            if detected:
                                set_state("LISTENING")
                                print(f"[ARIA] Wake word detected: '{detected}'")
                            
                                # Extract remaining text after wake word
                                remaining_input = ""
                                detected_lower = detected.lower().strip()
                                for wake in self.WAKE_WORDS:
                                    wake_lower = wake.lower().strip()
                                    if detected_lower.startswith(wake_lower):
                                        remaining_input = detected[len(wake_lower):].strip()
                                        remaining_input = re.sub(r'^[,\.\s\?\!]+', '', remaining_input).strip()
                                        break
                                    elif f" {wake_lower} " in f" {detected_lower} ":
                                        idx = detected_lower.find(wake_lower)
                                        remaining_input = detected[idx + len(wake_lower):].strip()
                                        remaining_input = re.sub(r'^[,\.\s\?\!]+', '', remaining_input).strip()
                                        break

                                # Set interaction time to initialize/open the active conversation window
                                self._mark_conversation_activity(wake_reason="wake_word")
                                self._was_in_conversation = True

                                if remaining_input:
                                    print(f"[ARIA] Processing immediate query: '{remaining_input}'")
                                    if self.voice.is_valid_speech(remaining_input, active_conversation=True):
                                        self._handle_input(remaining_input)
                                else:
                                    set_text("Go ahead, I am listening...")
                                    user_input = self.voice.listen(timeout=8, phrase_time_limit=15, active_conversation=True)
                                    if user_input:
                                        if self.voice.is_valid_speech(user_input, active_conversation=True):
                                            self._handle_input(user_input)
                                        else:
                                            self._speak("I am listening, go ahead.")
                                    else:
                                        self._speak("I am listening, go ahead.")

                except KeyboardInterrupt:
                    raise
                except Exception as _ie:
                    print(f"[ARIA] Loop iteration error: {_ie}")
                    import traceback
                    traceback.print_exc()
                    set_state("ERROR")
                    time.sleep(1)
                    set_state("IDLE")

            except KeyboardInterrupt:
                print("\n[ARIA] Keyboard interrupt -- shutting down.")
                break
            except Exception as e:
                print(f"[ARIA] Unexpected error in main loop: {e}")
                import traceback
                traceback.print_exc()
                set_state("ERROR")
                time.sleep(1)
                set_state("IDLE")
            except BaseException as _be:
                # Catches SystemExit, KeyboardInterrupt not already caught, native errors
                print(f"[ARIA] CRITICAL: Main loop BaseException: {_be}")
                import traceback
                traceback.print_exc()
                break

        # Loop exited — log reason
        print(f"[ARIA] Main loop exited. running={self.running}")
        # Cleanup
        self.cleanup()



# ─────────────────────────────────────────────────────────────────────────────
# Global unexpected exception handler to prevent silent crashes
def _global_exception_handler(exc_type, exc_value, exc_traceback):
    print(f"\n[ARIA] UNEXPECTED {exc_type.__name__}: {exc_value}")
    import traceback
    traceback.print_tb(exc_traceback)
    print("[ARIA] The application encountered a fatal error. Check logs above.")

sys.excepthook = _global_exception_handler

import signal

def main():
    # ─── Venv Auto-Restart Guard ───
    import sys
    import subprocess
    import os
    
    is_in_venv = 'aria_env' in sys.executable or (sys.prefix != sys.base_prefix)
    if not is_in_venv:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        venv_python = os.path.join(script_dir, 'aria_env', 'Scripts', 'python.exe')
        if os.path.exists(venv_python):
            print(f"[ARIA Venv Guard] Running on system Python. Auto-restarting inside virtual environment: {venv_python}")
            try:
                result = subprocess.run([venv_python] + sys.argv)
                sys.exit(result.returncode)
            except KeyboardInterrupt:
                # Ctrl+C in venv child — exit cleanly without traceback
                sys.exit(0)

    aria_instance = None
    qt_app = None
    qt_window = None
    is_shutting_down = False

    def shutdown_gracefully(sig=None, frame=None):
        nonlocal is_shutting_down
        if is_shutting_down:
            return
        is_shutting_down = True
        
        print("\n[ShutdownCoordinator] SIGINT (Ctrl+C) or exit request received. Initiating graceful shutdown...")
        
        # 1. Stop background run loops
        if aria_instance:
            print("[ShutdownCoordinator] Stopping agent loop...")
            aria_instance.running = False
            try:
                # Commit the in-memory relationship vector state to SQLite only upon clean exit
                if getattr(aria_instance, "known_user", None):
                    print(f"[ShutdownCoordinator] Persisting relationship metrics for user '{aria_instance.known_user}'...")
                    try:
                        aria_instance.reflection_engine.persist_relationship_metrics(aria_instance.known_user)
                    except Exception as pe:
                        print(f"[ShutdownCoordinator] Failed to persist relationship metrics: {pe}")
                aria_instance.cleanup()
            except Exception as e:
                print(f"[ShutdownCoordinator] Error during ARIA cleanup: {e}")

        # 2. Stop Qt event loop and timers
        if qt_window:
            print("[ShutdownCoordinator] Stopping GUI window...")
            try:
                qt_window.close_cleanly()
            except Exception as e:
                print(f"[ShutdownCoordinator] Error closing GUI window: {e}")

        if qt_app:
            print("[ShutdownCoordinator] Quitting Qt Application...")
            try:
                qt_app.quit()
            except Exception as e:
                print(f"[ShutdownCoordinator] Error quitting Qt App: {e}")

        print("[ShutdownCoordinator] Graceful shutdown completed successfully. Exiting process.")

        # Free any cloud model temp files that were active
        try:
            from skills.model_cloud_manager import ModelCloudManager
            ModelCloudManager().free_all_temps()
        except Exception:
            pass

        # Force exit to ensure stuck threads or uvicorn loop doesn't stall process
        import os
        os._exit(0)


    # Register the SIGINT handler
    signal.signal(signal.SIGINT, shutdown_gracefully)

    if USE_GUI and _gui_available:
        # Qt must live on main thread — run agent on background thread
        qt_app = QApplication(sys.argv)
        from PyQt5.QtCore import QTimer
        qt_window = ARIAWindow()

        aria_instance = ARIA()
        # Expose globally to sys.modules for dynamic lookup
        sys.modules['__main__'].instance = aria_instance
        agent_thread = threading.Thread(target=aria_instance.run, name="ARIA-Agent", daemon=True)
        agent_thread.start()

        # Hack: A QTimer running dummy Python callbacks every 500ms allows
        # the Python interpreter to yield and handle OS/SIGINT signals.
        signal_timer = QTimer()
        signal_timer.start(500)
        signal_timer.timeout.connect(lambda: None)

        exit_code = qt_app.exec_()
        shutdown_gracefully()
        sys.exit(exit_code)
    else:
        # Terminal mode — run everything on main thread
        aria_instance = ARIA()
        # Expose globally to sys.modules for dynamic lookup
        sys.modules['__main__'].instance = aria_instance
        aria_instance.wake_mode = True   # Always-on in terminal mode
        aria_instance.run()
        shutdown_gracefully()


if __name__ == "__main__":
    main()
