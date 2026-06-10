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
import json
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
from skills.image_gen import ImageGenerator

# New Cognitive Core additions
from skills.sandbox_safety import SandboxSafetyLayer
from skills.executor_queue import ExecutorQueue
from skills.context_budget import ContextBudgetManager
from skills.reflection_engine import ReflectionEngine
from skills.proactive_cognition import ProactiveCognition
from skills.episodic_memory import EpisodicMemory
from skills.knowledge_graph import KnowledgeGraph
from skills.life_learner import LifeLearner
from skills.agent_orchestrator import AriaMultiAgentOrchestrator
from skills.blackboard import AriaBlackboard

# New modular commands
import skills.voice_session_commands
import skills.proactive_scheduler_commands

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


_original_set_state = set_state
_original_set_text = set_text
_current_gui_state = "IDLE"

def set_state(s):
    global _current_gui_state
    _current_gui_state = s
    _original_set_state(s)
    try:
        import sys
        aria_inst = getattr(sys.modules.get('__main__'), 'instance', None)
        if aria_inst and hasattr(aria_inst, 'firebase_sync') and aria_inst.firebase_sync:
            aria_inst.firebase_sync.update_status("", status_str=s.lower())
    except Exception as e:
        print(f"[Main] Failed to update firebase sync status: {e}")

def set_text(t):
    _original_set_text(t)
    try:
        import sys
        aria_inst = getattr(sys.modules.get('__main__'), 'instance', None)
        if aria_inst and hasattr(aria_inst, 'firebase_sync') and aria_inst.firebase_sync:
            aria_inst.firebase_sync.update_status(t, status_str=_current_gui_state.lower())
    except Exception as e:
        print(f"[Main] Failed to update firebase sync text: {e}")


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
        self._cleanup_done = False
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
        self.last_welcome_time = 0.0         # Timestamp of last spoken welcome back greeting
        self.presence_state = "USER_LEFT"
        self.last_background_perception_time = 0.0
        self.owner_last_seen_time = 0.0
        self.last_presence_state_logged = None
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
        self.image_gen_mode = False
        self.wake_sentinel = None
        self.wake_sentinel_thread = None
        self.db_path = "aria_memory.db"
        from skills.security_monitor import SecurityMonitor
        self.security_monitor = SecurityMonitor(aria=self, db_path=self.db_path)
        self.knowledge_graph = KnowledgeGraph()
        self.life_learner = LifeLearner(knowledge_graph=self.knowledge_graph, aria=self)

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
        threading.Thread(target=skills.voice_session_commands.speech_worker, args=(self,), daemon=True).start()

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
        self.image_gen = ImageGenerator(aria=self)

        # New Cognitive Core Plugins Instantiation
        self.sandbox_safety = SandboxSafetyLayer()
        self.executor_queue = ExecutorQueue()
        self.context_budget = ContextBudgetManager()
        self.reflection_engine = ReflectionEngine()
        self.proactive_cognition = ProactiveCognition()
        self.episodic_memory = EpisodicMemory()
        self.orchestrator = AriaMultiAgentOrchestrator(self)
        self.blackboard = AriaBlackboard()

        # Start Background Task Executor Queue Worker
        threading.Thread(target=skills.proactive_scheduler_commands.executor_queue_worker, args=(self,), daemon=True).start()

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
            scheduler_thread = threading.Thread(target=skills.proactive_scheduler_commands.run_background_scheduler, args=(self,), daemon=True)
            scheduler_thread.start()
            print("[ARIA Scheduler] Proactive Background Cognition Loop active.")
        except Exception as se:
            print(f"[ARIA Scheduler] Could not start proactive scheduler: {se}")

        # Start Face-Wake Background Loop
        try:
            face_wake_thread = threading.Thread(target=self._run_face_wake_loop, name="ARIA-FaceWake", daemon=True)
            face_wake_thread.start()
            print("[ARIA] Face-Wake background loop successfully running.")
        except Exception as fwe:
            print(f"[ARIA] Could not start face wake loop: {fwe}")

        # Start Window Monitor Background Loop
        try:
            window_monitor_thread = threading.Thread(target=self._run_window_monitor_loop, name="ARIA-WindowMonitor", daemon=True)
            window_monitor_thread.start()
            print("[ARIA] Window-Monitor background loop successfully running.")
        except Exception as wme:
            print(f"[ARIA] Could not start window monitor loop: {wme}")

        # Start Autonomous Background Learner Thread
        try:
            self.life_learner.start()
        except Exception as lle:
            print(f"[ARIA] Could not start autonomous life learner: {lle}")
        
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

        # Check for pending unsent drafts in SQLite queue and notify the user
        try:
            from skills.email_skill import AriaEmailSkill
            email_skill = AriaEmailSkill()
            pending_drafts = email_skill.get_all_pending_drafts()
            if pending_drafts:
                count = len(pending_drafts)
                if count == 1:
                    self._speak("Welcome back! You have 1 pending email draft waiting for approval.")
                else:
                    self._speak(f"Welcome back! You have {count} pending email drafts waiting for approval.")
        except Exception as e:
            print(f"[ARIA Email Startup] Failed to check pending drafts: {e}")

        # Trigger delayed memory maintenance pass
        try:
            def run_startup_maintenance():
                time.sleep(60)
                print("[MemoryMaintenance] Running startup memory maintenance...")
                try:
                    username = self.known_user or "chinmaya"
                    self.episodic_memory.decay_pass(username)
                    print("[MemoryMaintenance] Decay pass complete.")
                    self.episodic_memory.compress_old_episodes(username)
                    print("[MemoryMaintenance] Startup maintenance complete.")
                except Exception as e:
                    print(f"[MemoryMaintenance] Startup error: {repr(e)}")

            maintenance_thread = threading.Thread(target=run_startup_maintenance, name="ARIA-StartupMemoryMaintenance", daemon=True)
            maintenance_thread.start()
        except Exception as me:
            print(f"[MemoryMaintenance] Could not start startup memory maintenance: {me}")

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

    @property
    def _is_user_speaking(self):
        return self.is_user_speaking()

    def is_user_speaking(self):
        now = time.time()
        recording = self.voice and getattr(self.voice, 'recording_active', False)
        user_speaking = self.voice and getattr(self.voice, 'vad_detecting_speech', False)
        recent_speech = (now - getattr(self, "last_user_speech_time", 0.0)) < 3.0
        return bool(recording or user_speaking or recent_speech)

    def safe_speak(self, text):
        time_since_last_user_speech = time.time() - getattr(self, "last_user_speech_time", 0.0)
        # Queue proactive speech if user is speaking, conversation task is active, or user spoke within last 5s
        if self.is_user_speaking() or self._has_active_conversation_task() or time_since_last_user_speech < 5.0:
            print(f"[ARIA] User is busy/speaking. Queuing proactive speech: '{text}'")
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
            
        # Drop soft proactive suggestions completely if user is speaking, conversation is active, or user spoke within 5s
        if self.is_user_speaking():
            print(f"[Proactive] Dropping suggestion because user is speaking: {msg}")
            return
        if self._has_active_conversation_task():
            print(f"[Proactive] Dropping suggestion because conversation is active: {msg}")
            return
        time_since_last_user_speech = time.time() - getattr(self, "last_user_speech_time", 0.0)
        if time_since_last_user_speech < 5.0:
            print(f"[Proactive] Dropping suggestion because user spoke recently ({time_since_last_user_speech:.1f}s ago): {msg}")
            return
        time_since_interaction = time.time() - getattr(self, "last_interaction_time", 0.0)
        if time_since_interaction < 180.0:
            print(f"[Proactive] Dropping suggestion because conversation is active (last interaction {time_since_interaction:.1f}s ago): {msg}")
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
        return skills.voice_session_commands.mark_conversation_activity(self, wake_reason, active_task_id)

    def _is_aria_busy(self):
        """Returns True if any background subsystem is actively running."""
        return skills.voice_session_commands.is_aria_busy(self)

    def _has_active_conversation_task(self):
        """True when an active task should keep ARIA in light conversational idle."""
        return skills.voice_session_commands.has_active_conversation_task(self)

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
    def _speak(self, text, source=None, allow_barge_in=True):
        if source is None:
            source = getattr(self._reply_context, "input_source", None)
        return skills.voice_session_commands.speak(self, text, source=source, allow_barge_in=allow_barge_in)

    def _sanitize_spoken_text(self, text):
        return skills.voice_session_commands.sanitize_spoken_text(self, text)

    def _wait_for_speech(self):
        """Block until the speech queue is processed and the voice has stopped playing audio."""
        return skills.voice_session_commands.wait_for_speech(self)

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
        
        # 0. Cache identity check: If owner was detected recently (last 30s) and confidence is high/medium, reuse it to save CPU
        if self.known_user and self.known_user != "Unknown" and self.known_user_confidence in ["high", "medium"] and (now - self.last_identity_match_time < 30.0):
            self.owner_last_seen_time = now
            return self.known_user
            
        # 1. Identity persistence lock check (3 minutes)
        # If we have a verified user within the last 180s, do a fast check using 1 frame
        if self.known_user and self.known_user != "Unknown" and self.known_user_confidence in ["high", "medium"] and (now - self.last_identity_match_time < 180.0):
            arr = self.camera.capture_frame_raw()  # BGR numpy — correct for FaceEmbedder
            if arr is not None:
                try:
                    emb = self.memory.memory_manager.embedder.get_embedding(arr)
                    if emb:
                        name, similarity = self.memory.memory_manager.identify_user(
                            threshold=0.65, 
                            return_confidence=True, 
                            embedding=emb
                        )
                        if name == self.known_user:
                            # Keep identity locked and refresh timestamp
                            self.last_identity_match_time = now
                            self.known_user_similarity = similarity
                            
                            # Continuous face learning update (Delegated to MemoryManager)
                            if name in ["chinmay", "chinmaya"]:
                                self.memory.memory_manager.add_face_embedding_to_cluster(name, emb, similarity)

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
        
        # 2. Capture 5 frames at 30ms intervals (BGR via capture_frame_raw — correct for FaceEmbedder)
        for i in range(5):
            arr = self.camera.capture_frame_raw()
            if arr is not None:
                try:
                    emb = self.memory.memory_manager.embedder.get_embedding(arr)
                    if emb:
                        embeddings.append(emb)
                except Exception:
                    pass
            time.sleep(0.03)
            
        if not embeddings:
            # Face disappeared / no face seen — use grace period before clearing identity
            # so brief look-aways or lighting glitches don't reset user context
            FACE_LOSS_GRACE_SECONDS = 180.0
            now_t = time.time()
            last_seen = getattr(self, "_face_last_seen_time", 0.0)
            if self.known_user and self.known_user != "Unknown":
                import random
                # Do not clear user if there is an active conversation session/task or recent interaction
                time_since_interaction = now_t - getattr(self, "last_interaction_time", 0.0)
                if self._has_active_conversation_task() or time_since_interaction < 180.0:
                    self._face_last_seen_time = now_t
                    # Don't spam log every loop iteration, print occasionally
                    if random.random() < 0.02:
                        print(f"[Main] Active conversation ongoing (last interaction {time_since_interaction:.1f}s ago). Holding context for '{self.known_user}'.")
                elif (now_t - last_seen) > FACE_LOSS_GRACE_SECONDS:
                    print(f"[Main] No face detected for {FACE_LOSS_GRACE_SECONDS:.0f}s. Clearing active user '{self.known_user}'.")
                    self.known_user = None
                    self.known_user_confidence = "none"
                    self.known_user_similarity = 0.0
                    self.face_match_history = []
                else:
                    remaining = FACE_LOSS_GRACE_SECONDS - (now_t - last_seen)
                    import random
                    if random.random() < 0.02:
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
                threshold=0.65, 
                return_confidence=True, 
                embedding=avg_emb.tolist()
            )
            
            if name != "Unknown":
                # Continuous face learning update (Delegated to MemoryManager)
                if name in ["chinmay", "chinmaya"]:
                    self.memory.memory_manager.add_face_embedding_to_cluster(name, avg_emb.tolist(), similarity)

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
                if name in ["chinmay", "chinmaya"]:
                    self.owner_last_seen_time = time.time()
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
        1. Prioritizes recent voice emotion (from voice analyzer) if captured within the last 30s.
        2. Otherwise, returns the latest background-detected user emotion (never blocks the main thread).
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

        # 2. Return the latest background-detected user emotion
        return getattr(self, "current_user_emotion", "neutral")

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

    def update_presence_state(self):
        """Update wake_mode and access permissions based on owner presence timer."""
        now = time.time()
        time_since_owner = now - getattr(self, "owner_last_seen_time", 0.0)
        
        # Determine presence state
        if time_since_owner < 300.0:  # 0-5 mins
            state = "OWNER_ACTIVE"
            self.wake_mode = True  # Wake-word-free mode enabled
        elif time_since_owner < 900.0:  # 5-15 mins
            state = "OWNER_IDLE"
            self.wake_mode = False  # Require wake-word again
        else:  # 15+ mins
            state = "GUEST_MODE"
            self.wake_mode = False
            # Clear known user if they were owner to drop to guest permissions
            if self.known_user in ["chinmay", "chinmaya"]:
                self.known_user = "Unknown"
                self.known_user_confidence = "none"
                self.known_user_similarity = 0.0

        if getattr(self, "last_presence_state_logged", None) != state:
            print(f"[PresenceEngine] State Transition: {getattr(self, 'last_presence_state_logged', 'None')} -> {state} (Time since owner: {time_since_owner:.1f}s)")
            self.last_presence_state_logged = state
            
        return state

    def _run_face_wake_loop(self):
        """Runs a dedicated background loop to detect the owner's face and wake up the system if detected."""
        print("[PresenceEngine] Dedicated Face-Wake Loop started.")
        import time
        while self.running:
            try:
                # Yield CPU priorities: If voice session is active, slow down checking frequency
                if self.voice and (self.voice.is_speaking or getattr(self.voice, "vad_detecting_speech", False)):
                    time.sleep(3.0)
                    continue

                # Check if camera is available and we are NOT in active conversation
                if self.camera and self.camera.available and not self.conversation_session.is_active():
                    now_t = time.time()
                    is_owner_active = (self.known_user in ["chinmay", "chinmaya"] and (now_t - getattr(self, "last_identity_match_time", 0.0) < 180.0))
                    if is_owner_active:
                        if now_t - getattr(self, "last_face_wake_check_time", 0.0) < 10.0:
                            time.sleep(1.0)
                            continue
                        self.last_face_wake_check_time = now_t
                    
                    # Capture raw BGR frame
                    arr = self.camera.capture_frame_raw()
                    if arr is not None:
                        import cv2
                        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
                        faces = self.memory.face_cascade.detectMultiScale(gray, 1.1, 4)
                        detected = None
                        if len(faces) > 0:
                            # Try to identify the user
                            detected = self.identify_user()
                            if detected in ["chinmay", "chinmaya"]:
                                self.owner_last_seen_time = time.time()
                                self.known_user = detected
                                self.known_user_confidence = "high"
                                
                                now_t = time.time()
                                if now_t - getattr(self, "last_face_wake_trigger_time", 0.0) > 30.0:
                                    self.last_face_wake_trigger_time = now_t
                                    self.last_identity_match_time = now_t
                                    
                                    # Greet with cooldown of 30 minutes (1800s)
                                    if now_t - getattr(self, "last_welcome_time", 0.0) > 1800.0:
                                        print(f"[PresenceEngine] Owner '{detected}' detected by camera. Greeting owner and auto-waking conversation!")
                                        self.last_welcome_time = now_t
                                        self._mark_conversation_activity(wake_reason="face_detection")
                                        self._speak("Welcome back, Chinmaya.", allow_barge_in=False)
                                    else:
                                        print(f"[PresenceEngine] Owner '{detected}' detected by camera. Silent wake-up / match refreshed.")
                        
                        # Invoke security monitor frame processing
                        if hasattr(self, "security_monitor") and self.security_monitor is not None:
                            try:
                                owner_present = (self.known_user in ["chinmay", "chinmaya"] and (time.time() - self.owner_last_seen_time < 180.0))
                                identified_user_passed = detected if detected in ["chinmay", "chinmaya"] else None
                                self.security_monitor.process_frame(
                                    frame=arr if len(faces) > 0 else None,
                                    identified_user=identified_user_passed,
                                    similarity=self.known_user_similarity,
                                    owner_present=owner_present
                                )
                            except Exception as sec_err:
                                print(f"[PresenceEngine] SecurityMonitor process_frame error: {sec_err}")
            except Exception as e:
                print(f"[PresenceEngine] Error in face wake loop: {e}")
            time.sleep(2.0)

    def _run_background_perception(self):
        """Runs periodic background webcam scans to detect presence and emotions."""
        # Yield CPU priorities: If voice session is active, delay check and return immediately
        if self.voice and (self.voice.is_speaking or getattr(self.voice, "vad_detecting_speech", False)):
            self.last_background_perception_time = time.time() - 50.0  # check again in 10s (slow poll) instead of 60s
            return

        self.last_background_perception_time = time.time()

        # Privacy Zone check
        active_window = self.context_skill.get_active_window()
        if not self.sandbox_safety.is_perception_allowed(active_window):
            print(f"[BackgroundPerception] Webcam perception blocked: Privacy Zone active (Window: '{active_window}').")
            self.presence_state = "USER_LEFT"
            return

        if not self.camera.available:
            return

        # Use BGR frame directly — FaceEmbedder expects BGR (cv2.COLOR_BGR2GRAY)
        arr = self.camera.capture_frame_raw()
        if arr is None:
            self.presence_state = "USER_LEFT"
            return

        import numpy as np
        import cv2
        import io
        import base64
        from PIL import Image

        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        
        faces = []
        try:
            faces = self.memory.face_cascade.detectMultiScale(gray, 1.1, 4)
        except Exception as e:
            print(f"[BackgroundPerception] Face detection error: {e}")

        if len(faces) == 0:
            self.presence_state = "USER_LEFT"
            self.current_user_emotion = "neutral"
            self.current_user_emotion_confidence = 1.0
            return

        user = self.known_user or "chinmaya"
        # Skip face recognition embedding if we matched recently (within 30s)
        if self.known_user and self.known_user != "Unknown" and self.known_user_confidence in ["high", "medium"] and (time.time() - self.last_identity_match_time < 30.0):
            user = self.known_user
            print(f"[BackgroundPerception] Using cached user identity '{user}' (detected {time.time() - self.last_identity_match_time:.1f}s ago). Skipping FaceEmbedder.")
        else:
            try:
                emb = self.memory.memory_manager.embedder.get_embedding(arr)
                if emb:
                    name, similarity = self.memory.memory_manager.identify_user(
                        threshold=0.65, 
                        return_confidence=True, 
                        embedding=emb
                    )
                    if name != "Unknown":
                        user = name
                        self.known_user = name
                        self.known_user_similarity = similarity
                        
                        # Continuous face learning update (Delegated to MemoryManager)
                        if name in ["chinmay", "chinmaya"]:
                            self.memory.memory_manager.add_face_embedding_to_cluster(name, emb, similarity)

                        if similarity >= 0.85:
                            self.known_user_confidence = "high"
                            self.last_identity_match_time = time.time()
                        elif similarity >= 0.75:
                            self.known_user_confidence = "medium"
                        else:
                            self.known_user_confidence = "low"
                        if name in ["chinmay", "chinmaya"]:
                            self.owner_last_seen_time = time.time()
            except Exception as id_err:
                print(f"[BackgroundPerception] Identity match error: {id_err}")

        matched_emotion = "neutral"
        try:
            x, y, w, h = faces[0]
            face_crop_bgr = arr[y:y+h, x:x+w]
            # Convert BGR crop to RGB PIL for vision model encoding
            face_crop_rgb = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2RGB)
            face_img = Image.fromarray(face_crop_rgb)

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


    def _run_window_monitor_loop(self):
        """Monitors the active window and triggers proactive reminders for projects after dwell time."""
        print("[WindowMonitor] Continuous awareness loop started.")
        from skills.proactive_governor import AriaProactiveGovernor
        governor = AriaProactiveGovernor(self.db_path)
        cooldowns = {}  # project_name -> timestamp of last voice alert
        focus_start_times = {}  # project_name -> timestamp when window focus started
        alerted_this_focus = {}  # project_name -> bool

        from skills.context_skill import AriaDesktopPerceptionService, WindowEvent
        from skills.event_bus import EventBus, ARIAEvents
        from skills.active_context import ActiveContext
        from ui_control import capture_desktop_perception_snapshot
        
        perception_service = AriaDesktopPerceptionService(self, self.db_path)

        while self.running:
            try:
                time.sleep(3.0)
                
                # Check active projects JSON
                projects_file = "aria_projects.json"
                if not os.path.exists(projects_file):
                    continue
                    
                with open(projects_file, "r") as f:
                    projects_data = json.load(f)
                
                active_projects = projects_data.get("active_projects", {})
                if not active_projects:
                    continue

                # Get the detailed info of the active window on screen
                pid, process_name, current_window = self.context_skill.get_active_window_info()
                if not current_window:
                    focus_start_times.clear()
                    alerted_this_focus.clear()
                    continue

                # Get the WindowEvent with UIA tree snapshot if whitelisted
                event = capture_desktop_perception_snapshot(pid, process_name, current_window)

                # Feed event to perception service (which debounces, tracks focus duration, and caches)
                is_processed = perception_service.process_window_focus_event(event)

                if is_processed:
                    # Publish event to EventBus
                    payload = ARIAEvents.build_payload(
                        extra={
                            "window_title": current_window,
                            "process_name": process_name,
                            "pid": pid,
                            "timestamp": time.time(),
                            "source": "DesktopPerceptionService"
                        }
                    )
                    EventBus().publish(ARIAEvents.WINDOW_CHANGED, payload)
                    
                    # Update ActiveContext state
                    ActiveContext().active_window = current_window
                    ActiveContext().active_file = None

                # Execute governor context evaluation check
                try:
                    governor.evaluate_context(self, current_window)
                except Exception as gov_err:
                    print(f"[WindowMonitor] Governor check error: {gov_err}")
                
                matched_proj_name = None
                matched_tool = None
                matched_focus = None
                matched_last_session = None
                matched_next_action = None
                
                for proj_name, details in active_projects.items():
                    for tool in details.get("associated_tools", []):
                        if tool.lower() in current_window.lower():
                            matched_proj_name = proj_name
                            matched_tool = tool
                            matched_focus = details.get("current_focus", "unknown focus")
                            matched_last_session = details.get("last_session_summary", "")
                            matched_next_action = details.get("next_action", "")
                            break
                    if matched_proj_name:
                        break
                
                if matched_proj_name:
                    now = time.time()
                    
                    # Clean up other projects' timers
                    for p in list(focus_start_times.keys()):
                        if p != matched_proj_name:
                            focus_start_times.pop(p, None)
                            alerted_this_focus.pop(p, None)
                            
                    if matched_proj_name not in focus_start_times:
                        focus_start_times[matched_proj_name] = now
                        alerted_this_focus[matched_proj_name] = False
                        print(f"[WindowMonitor] Detected focus on tool '{matched_tool}' for project '{matched_proj_name}'. Dwell timer started.")
                    else:
                        duration = now - focus_start_times[matched_proj_name]
                        if duration >= 20.0 and not alerted_this_focus.get(matched_proj_name, False):
                            last_alert = cooldowns.get(matched_proj_name, 0.0)
                            # 30 minutes cooldown (1800 seconds)
                            if now - last_alert > 1800.0:
                                # Ensure user is idle relative to ARIA conversation
                                time_since_last_interaction = now - self.last_interaction_time
                                _speaking = self.voice is not None and getattr(self.voice, 'is_speaking', False)
                                
                                if time_since_last_interaction >= 20.0 and not _speaking and self.speech_queue.empty():
                                    prompt_parts = []
                                    prompt_parts.append(f"I noticed you've been working in {matched_tool} for a bit.")
                                    if matched_last_session:
                                        prompt_parts.append(f"Last session, you {matched_last_session}.")
                                    if matched_next_action:
                                        prompt_parts.append(f"The next recommended action is {matched_next_action}.")
                                    prompt_parts.append("Would you like to continue from there?")
                                    
                                    prompt = " ".join(prompt_parts)
                                    print(f"\n[WindowMonitor Alert] Proactive speech: {prompt}")
                                    
                                    cooldowns[matched_proj_name] = now
                                    alerted_this_focus[matched_proj_name] = True
                                    self._speak(prompt, allow_barge_in=True)
                else:
                    focus_start_times.clear()
                    alerted_this_focus.clear()
                    
            except Exception as e:
                print(f"[WindowMonitor] Error: {e}")


    # ── Action Execution (delegated to skills/autonomous_agent_commands.py) ──
    def _is_action_tag_authorized(self, category, source_user_input):
        from skills.autonomous_agent_commands import is_action_tag_authorized
        return is_action_tag_authorized(self, category, source_user_input)

    def _execute_actions(self, response, source_user_input=""):
        from skills.autonomous_agent_commands import execute_actions
        return execute_actions(self, response, source_user_input)

    def _verify_action(self, action_tag, sw, sh):
        from skills.autonomous_agent_commands import verify_action
        return verify_action(self, action_tag, sw, sh)

    def run_autonomous_agent(self, task, max_steps=8, task_item=None):
        from skills.autonomous_agent_commands import run_autonomous_agent
        return run_autonomous_agent(self, task, max_steps, task_item)

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
        self.assistant_replied = True
        # Security authorization check for local inputs (microphone speech / console typing)
        if not remote:
            now = time.time()
            is_owner = (self.known_user in ["chinmay", "chinmaya"] and (now - getattr(self, "last_identity_match_time", 0.0) < 180.0))
            
            # If identity match expired, perform active camera verification
            if not is_owner:
                print("[SecurityGuard] Local input received. Actively verifying speaker identity via camera...")
                detected = self.identify_user()
                if detected in ["chinmay", "chinmaya"]:
                    print(f"[SecurityGuard] Identity verified as '{detected}'. Access granted.")
                    self.known_user = detected
                    self.known_user_confidence = "high"
                    self.last_identity_match_time = now
                    self.owner_last_seen_time = now
                else:
                    print(f"[SecurityGuard] Access Denied. Speaker identified as '{detected}', not recognized as owner.")
                    self._speak("Unauthorized person.")
                    return

        if self.known_user in ["chinmay", "chinmaya"]:
            self.owner_last_seen_time = time.time()
            
        previous_phone_only = getattr(self._reply_context, "phone_only", False)
        self._reply_context.phone_only = remote
        
        # Track input source in threading.local for thread-safe access
        source = "phone" if remote else "laptop"
        previous_source = getattr(self._reply_context, "input_source", None)
        self._reply_context.input_source = source
        
        self._spoken_during_turn = []
        try:
            return self._handle_input_impl(user_input, image=image, source=source)
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
                self._reply_context.input_source = previous_source

    def _translate_hindi_to_english(self, text):
        try:
            system_instruction = (
                "You are a translation assistant for ARIA AI. "
                "Translate the given Hindi/Devanagari text to direct English commands. "
                "Return ONLY the English translation, with absolutely no other text, explanation, intro, or formatting. "
                "For example, if the input is 'एनेबल द एर 3D मोड', you must return 'enable ar 3d mode'."
            )
            prompt = f"Input Hindi text to translate: '{text}'"
            
            if hasattr(self, 'brain') and self.brain:
                # Use think_raw with system_instruction to bypass SemanticRouter entirely
                if hasattr(self.brain, 'think_raw'):
                    res = self.brain.think_raw(prompt, system_instruction=system_instruction)
                else:
                    res = self.brain._think_impl(f"{system_instruction}\nInput: {text}", user_name="Translator_System")
                
                if res:
                    cleaned = res.strip().replace('"', '').replace("'", "")
                    for prefix in ["translation:", "english:", "output:", "here is the translation:", "the english translation is:"]:
                        if cleaned.lower().startswith(prefix):
                            cleaned = cleaned[len(prefix):].strip()
                    
                    # Discard translation if the LLM repeated instructions/prompt instead of translating
                    if any(x in cleaned.lower() for x in ["translation assistant", "translate this", "for example"]):
                        print("[Main/LanguageGuard] Translation returned instruction text, discarding.")
                        return None
                        
                    return cleaned
        except Exception as e:
            print(f"[Main/LanguageGuard] Translation error: {e}")
        return None

    def _check_and_release_camera(self):
        """Releases the camera if no camera-dependent modes are active."""
        ar_active = getattr(self, "ar_mode", False) or getattr(self, "ar_playground", None) is not None
        gesture_active = getattr(self, "gesture_mode", False)
        vision_active = getattr(self, "vision_learner", None) and self.vision_learner.running
        
        if not ar_active and not gesture_active and not vision_active:
            if self.camera:
                print("[Camera] No active camera consumer. Releasing camera to turn it off.")
                self.camera.release()

    def _handle_input_impl(self, user_input, image=None, source=None):
        """Process one utterance from the user."""
        self._mark_conversation_activity(wake_reason="user_input")

        # Devanagari detection and translation to English
        import re
        if re.search(r"[\u0900-\u097F]", user_input):
            print(f"[Main/LanguageGuard] Devanagari script detected in input: '{user_input}'")
            translated = self._translate_hindi_to_english(user_input)
            if translated:
                print(f"[Main/LanguageGuard] Translated Devanagari to English: '{translated}'")
                user_input = translated
        
        # Get normalized query for trigger checking and command processing
        inp = user_input.strip().lower()
        if hasattr(self, 'brain') and self.brain and getattr(self.brain, 'semantic_router', None) and self.brain.semantic_router.normalizer:
            try:
                result = self.brain.semantic_router.normalizer.normalize(user_input)
                # Safely unpack — only if result is a proper 2-tuple of strings
                if isinstance(result, (list, tuple)) and len(result) == 2 and isinstance(result[0], str):
                    normalized_val = result[0]
                    inp = normalized_val.strip().lower().rstrip('.!?')
            except Exception as norm_err:
                pass  # Normalization is a best-effort enhancement; fall back to raw inp

        # Extract facts from voice declarations dynamically
        if hasattr(self, 'life_learner') and self.life_learner:
            try:
                self.life_learner.learn_from_voice(user_input)
            except Exception as ll_err:
                print(f"[ARIA] Error extracting facts from voice: {ll_err}")

        # Personal profile queries routing
        if any(trigger in inp for trigger in ["what do you know about me", "tell me about myself", "summarize my profile", "show my profile summary"]):
            summary = self.knowledge_graph.query_profile_summary()
            reply = f"Here is what I know about you:\n{summary}"
            self._speak(reply)
            self.chat_history.append({"role": "user", "content": user_input})
            self.chat_history.append({"role": "assistant", "content": reply})
            return

        if inp in ["my skills", "show my skills", "what are my skills"]:
            skills = self.knowledge_graph.get_nodes_by_type("skill")
            if skills:
                names = [f"{s['name']} ({s['status']})" for s in skills[:10]]
                reply = f"Your top skills include: {', '.join(names)}."
            else:
                reply = "I don't have any skills recorded for you yet."
            self._speak(reply)
            self.chat_history.append({"role": "user", "content": user_input})
            self.chat_history.append({"role": "assistant", "content": reply})
            return

        if inp in ["my goals", "what are my goals", "show my goals"]:
            goals = self.knowledge_graph.get_nodes_by_type("goal")
            if goals:
                names = [g['name'] for g in goals]
                reply = f"Your recorded goals are: {', '.join(names)}."
            else:
                reply = "I don't have any goals recorded for you yet."
            self._speak(reply)
            self.chat_history.append({"role": "user", "content": user_input})
            self.chat_history.append({"role": "assistant", "content": reply})
            return

        # Project recommendation queries routing
        rec_match = re.search(r"(?:best project for|recommend a project for|suggest a project for|project recommendation for)\s+([a-z0-9\+\#\s]+)", inp)
        if rec_match:
            topic = rec_match.group(1).strip()
            scored = self.knowledge_graph.find_relevant_projects(topic)
            if scored:
                top = scored[0]
                reasons_str = " ".join(top["reasons"])
                reply = f"I recommend working on '{top['name']}'. Score: {top['score']:.1f}. Reason: {reasons_str}."
            else:
                reply = f"I couldn't find any projects matching '{topic}' in your knowledge graph."
            self._speak(reply)
            self.chat_history.append({"role": "user", "content": user_input})
            self.chat_history.append({"role": "assistant", "content": reply})
            return

        # Security check-in command routing
        if any(trigger in inp for trigger in ["who is at my computer", "who is at my pc", "live check-in", "check-in"]):
            if hasattr(self, "security_monitor") and self.security_monitor is not None:
                threading.Thread(target=self.security_monitor.handle_remote_check_in, daemon=True).start()
                if hasattr(self, "firebase_sync") and self.firebase_sync is not None:
                    self.firebase_sync.update_status("Triggering remote live check-in...", status_str="thinking")
                return "Security check-in triggered."

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

        if time.time() - getattr(self, "_last_proactive_warning_time", 0.0) < 30.0:
            try:
                from skills.proactive_governor import AriaProactiveGovernor
                AriaProactiveGovernor(self.db_path).log_feedback(user_input)
            except Exception as e:
                print(f"[Main] Governor feedback routing error: {e}")
            self._last_proactive_warning_time = 0.0

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

        # ── Image Generation Mode ──────────────────────────
        if re.search(
            r"(enable|start|open|activate)\s+image\s*gen",
            user_input.lower()
        ):
            self.image_gen_mode = True
            self._speak(
                "Image generation mode active. "
                "Tell me what to generate."
            )
            return

        if re.search(
            r"(disable|stop|close|deactivate)\s+image\s*gen",
            user_input.lower()
        ):
            self.image_gen_mode = False
            self._speak("Image generation mode disabled.")
            return

        if self.image_gen_mode:
            prompt = user_input.strip()
            print(f"[ImageGen] Mode active. Generating: '{prompt}'")
            threading.Thread(
                target=self.image_gen.generate_or_load,
                args=(prompt,),
                daemon=True
            ).start()
            return
        # ───────────────────────────────────────────────────

        # Route through modular dispatcher
        from skills.command_router import (
            handle_system, handle_ar, handle_browser, handle_identity, 
            handle_memory, handle_chief_of_staff, handle_email,
            handle_screen_triage_wrapper, handle_cognitive_planning,
            handle_career, handle_orchestration, handle_missions,
            handle_vision, handle_rag_search, handle_code_search,
            handle_architecture_query, handle_research_query, handle_task_planning,
            handle_gesture_monitoring, handle_personal_coach, handle_self_improvement,
            handle_desktop_control, handle_chrome_cdp
        )

        image_param = image
        
        # Intercept RAG search queries
        res = handle_rag_search(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return

        # Intercept codebase searches (Code RAG)
        res = handle_code_search(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return

        # Intercept system architecture queries (dependency graph RAG)
        res = handle_architecture_query(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return

        # Intercept deep research queries
        res = handle_research_query(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return

        # Intercept task planning queries
        res = handle_task_planning(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return

        # Intercept gesture monitoring queries
        res = handle_gesture_monitoring(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return



        # Intercept screen triage confirmations and triggers
        res = handle_screen_triage_wrapper(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return
            
        res = handle_cognitive_planning(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return

        res = handle_vision(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return

        res = handle_orchestration(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return

        res = handle_missions(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return

        res = handle_system(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return
        res = handle_ar(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return
        res = handle_browser(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return
        res = handle_identity(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return
        res = handle_memory(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return
        res = handle_email(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return
        res = handle_career(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return
        res = handle_personal_coach(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return
        res = handle_self_improvement(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return
        res = handle_desktop_control(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return
        res = handle_chrome_cdp(self, inp, user_input, image=image_param)
        if res.get("handled"):
            return
        res = handle_chief_of_staff(self, inp, user_input, image=image_param)
        if res.get("handled"):
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

        # ─ Detect current user from camera (skip if owner recently verified) ─
        is_owner_currently_active = (self.known_user in ["chinmay", "chinmaya"] and (time.time() - getattr(self, "last_identity_match_time", 0.0) < 180.0))
        if not is_owner_currently_active:
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
        else:
            print(f"[Main] Owner '{self.known_user}' is active (timer: {time.time() - self.last_identity_match_time:.1f}s). Skipping active face re-detection.")

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
                self._speak(clean, source=source)

        self.brain._stream_callback = _on_streamed_sentence
        if hasattr(self, 'brain') and self.brain and hasattr(self, 'voice') and self.voice:
            self.brain.current_language = getattr(self.voice, "current_language", "en")

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
        response = self._execute_actions(response, source_user_input=user_input)

        # ─ Speak clean response — skip if streaming already spoke it or if identity was spoken directly ─
        if not spoken_via_stream and not getattr(self, "_identity_already_spoken", False):
            spoken = re.sub(r'\[[A-Z]+:[^\]]*\]', '', response or "")  # remove [TAG: value] tokens
            spoken = re.sub(r'\[[A-Z]+\]', '', spoken)                  # remove bare [TAG] tokens
            spoken = spoken.strip()
            if spoken:
                print(f"[TTS] About to speak: {spoken[:100]}")
                self._speak(spoken, source=source)
        
        # Clear the identity spoken flag
        if hasattr(self, "_identity_already_spoken"):
            delattr(self, "_identity_already_spoken")

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
        return skills.proactive_scheduler_commands.run_proactive_checks(self)

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
                # Check for a pending email draft waiting for approval
                from skills.email_skill import AriaEmailSkill
                email_skill = AriaEmailSkill()
                draft = email_skill.get_latest_pending_draft()
                if draft:
                    self._speak(f"Sending email to {draft['to_email']} now...")
                    res = email_skill.execute_send(draft["id"], approved_by="gesture")
                    if res == "SUCCESS":
                        self._speak("Email sent successfully!")
                        if hasattr(self, "_pending_email_draft_id"):
                            self._pending_email_draft_id = None
                    else:
                        self._speak(f"Failed to send email. {res}")
                else:
                    self._speak("Confirmed.")
            elif event == "GESTURE_CANCEL":
                self.automation_mode = False
                # Check for a pending email draft waiting for approval
                from skills.email_skill import AriaEmailSkill
                email_skill = AriaEmailSkill()
                draft = email_skill.get_latest_pending_draft()
                if draft:
                    email_skill.cancel_draft(draft["id"])
                    self._speak("Email draft cancelled and cleared.")
                    if hasattr(self, "_pending_email_draft_id"):
                        self._pending_email_draft_id = None
                else:
                    self._speak("Cancelled.")
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
        if getattr(self, "_cleanup_done", False):
            return
        self._cleanup_done = True
        print("[ARIA] Releasing resources...")
        
        # Stop autonomous background learner
        if hasattr(self, 'life_learner') and self.life_learner:
            try:
                self.life_learner.stop()
            except Exception:
                pass
        
        # Persist session summary for context carry-over
        try:
            self._persist_session_summary()
        except Exception as e:
            print(f"[ARIA/Cleanup] Failed to persist session summary: {e}")

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
        if hasattr(self, 'wake_sentinel') and self.wake_sentinel:
            try:
                self.wake_sentinel.stop()
            except Exception:
                pass
        if hasattr(self, 'voice') and self.voice:
            try:
                self.voice.cleanup()
            except Exception:
                pass
        print("[ARIA] Shutdown complete.")

    def _persist_session_summary(self):
        import sqlite3
        import time
        username = (self.known_user or "chinmaya").lower().strip()
        
        # Check if we have anything to summarize
        if not self.brain or not hasattr(self.brain, "chat_history") or not self.brain.chat_history:
            print("[ARIA/SessionSummary] No chat history to summarize.")
            return

        db_path = "aria_memory.db"
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS session_summaries (
                    username TEXT PRIMARY KEY,
                    summary TEXT,
                    updated_at REAL
                )
            """)
            conn.commit()

            # Retrieve last 10 episodic memories to augment context
            cursor.execute(
                "SELECT event_text FROM episodic_events WHERE username = ? ORDER BY timestamp DESC LIMIT 10",
                (username,)
            )
            episodes = [row["event_text"] for row in cursor.fetchall()]
            conn.close()
        except Exception as e:
            print(f"[ARIA/SessionSummary] Database setup/query error: {e}")
            return

        chat_lines = []
        for msg in self.brain.chat_history[-20:]:
            chat_lines.append(f"{msg['role'].capitalize()}: {msg['content']}")
        chat_context = "\n".join(chat_lines)
        episodes_context = "\n".join([f"- {ep}" for ep in episodes])

        prompt = f"""Summarize the key topics discussed, goals established, or actions taken in this session into a concise list of 3 to 5 key facts.
Focus strictly on what was actually done, requested, or achieved during this session.
Format the output as a few short, clear bullet points.

CONVERSATION HISTORY:
{chat_context}

RECENT EVENTS:
{episodes_context}

Provide only the bullet points in the summary, with no other text, introduction, or markdown header.
"""

        print("[ARIA/SessionSummary] Generating session summary via LLM...")
        backup_history = list(self.brain.chat_history)
        self.brain.chat_history = []
        backup_lang = getattr(self.brain, "current_language", "en")
        self.brain.current_language = "en"
        try:
            summary_response = self.brain._think_impl(prompt)
        except Exception as e:
            print(f"[ARIA/SessionSummary] LLM summary generation failed: {e}")
            return
        finally:
            self.brain.chat_history = backup_history
            self.brain.current_language = backup_lang

        if summary_response:
            clean_summary = summary_response.strip()
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO session_summaries (username, summary, updated_at) VALUES (?, ?, ?)",
                    (username, clean_summary, time.time())
                )
                conn.commit()
                conn.close()
                print(f"[ARIA/SessionSummary] Saved summary for user '{username}':\n{clean_summary}")
            except Exception as e:
                print(f"[ARIA/SessionSummary] Database save error: {e}")

    def _start_wake_sentinel(self):
        try:
            from skills.wake_word_sentinel import AriaWakeSentinel
            
            # State coordination provider: return True if system is busy
            def is_system_busy():
                return (
                    getattr(self, 'state', None) in ("LISTENING", "THINKING", "TRANSCRIBING")
                    or (self.voice is not None and getattr(self.voice, 'is_speaking', False))
                )
            
            # Wake Callback
            def on_wake_triggered():
                print("\n[WakeSentinel] Wake word detected locally! Transitioning to LISTENING.")
                self.state = "LISTENING"
                set_state("LISTENING")
                
                # Play chime if voice is initialized
                if self.voice:
                    try:
                        self.voice.play_audio_file("assets/wake_chime.wav")
                    except Exception as play_err:
                        print(f"[WakeSentinel] Chime playback failed: {play_err}")
                
                # Mark interaction time to initialize/open active window
                self._mark_conversation_activity(wake_reason="wake_word")
                self._was_in_conversation = True
                
                # Start a non-blocking dialog turn thread
                def run_dialog_turn():
                    set_text("Go ahead, I am listening...")
                    self.assistant_replied = False
                    user_input = self.voice.listen(timeout=8, phrase_time_limit=15, active_conversation=True)
                    if user_input and self.running:
                        if self.voice.is_valid_speech(user_input, active_conversation=True):
                            self._handle_input(user_input)
                        else:
                            if not getattr(self, "assistant_replied", False):
                                self._speak("I am listening, go ahead.")
                    else:
                        if not getattr(self, "assistant_replied", False):
                            self._speak("I am listening, go ahead.")
                
                threading.Thread(target=run_dialog_turn, daemon=True).start()

            self.wake_sentinel = AriaWakeSentinel(system_state_provider=is_system_busy)
            if self.wake_sentinel.model is not None:
                self.wake_sentinel_thread = threading.Thread(
                    target=self.wake_sentinel.start_background_listening,
                    args=(on_wake_triggered,),
                    name="ARIA-WakeSentinel",
                    daemon=True
                )
                self.wake_sentinel_thread.start()
                print("[ARIA] Background local openWakeWord sentinel thread started.")
            else:
                print("[ARIA] WakeWord sentinel not started because custom model weights (aria.onnx) are missing.")
        except Exception as e:
            print(f"[ARIA] Could not initialize local WakeWord sentinel: {e}")

    # ── Main Loop ─────────────────────────────────────────────────────────────
    def run(self):
        try:
            self.initialize()
            if not self.wake_mode:
                self._start_wake_sentinel()
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

        # Cooldown check to prevent race-condition duplicate greetings with Face-Wake loop
        if time.time() - getattr(self, "last_welcome_time", 0.0) > 1800.0:
            self.last_welcome_time = time.time()
            self._speak(greeting, allow_barge_in=False)
        else:
            print("[ARIA] Skipping duplicate startup greeting. Already greeted owner recently.")
        self.startup_greeting_done = True

        print("\n[ARIA] Entering main loop.")
        if self.wake_mode:
            print("[ARIA] Always-On mode: just speak and I will respond!")
        else:
            print("[ARIA] Wake-word mode: say 'Hey ARIA' to activate.")
        print()

        while self.running:
            try:
                self.update_presence_state()
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

                # Deliver any pending proactive speech if user is not speaking and no active conversation/recent speech
                time_since_last_user_speech = time.time() - getattr(self, "last_user_speech_time", 0.0)
                if (hasattr(self, "pending_speech") and self.pending_speech 
                        and not self.is_user_speaking() 
                        and not self._has_active_conversation_task()
                        and time_since_last_user_speech >= 5.0):
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

                    is_owner_active = (self.known_user in ["chinmay", "chinmaya"] and (time.time() - getattr(self, "last_identity_match_time", 0.0) < 180.0))

                    if self.wake_mode:
                        # ── Always-On Mode ──────────────────────────────────
                        set_state("LISTENING")
                        set_text("Listening... speak anytime.")
                        user_input = self.voice.listen(timeout=5, phrase_time_limit=20, active_conversation=in_conversation)
                        if user_input and self.running:
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
                            # Continue conversation
                            set_state("LISTENING")
                            set_text("Listening (active conversation)...")
                            user_input = self.voice.listen(timeout=6, phrase_time_limit=15, active_conversation=True)
                            if user_input and self.running:
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
                            if self.wake_sentinel and self.wake_sentinel_thread and self.wake_sentinel_thread.is_alive():
                                time.sleep(0.2)
                                continue
                            detected = self.voice.listen_for_wake_word(self.WAKE_WORDS, timeout=3)
                            if detected and self.running:
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
                                self.assistant_replied = False

                                if remaining_input and self.running:
                                    print(f"[ARIA] Processing immediate query: '{remaining_input}'")
                                    if self.voice.is_valid_speech(remaining_input, active_conversation=True):
                                        self._handle_input(remaining_input)
                                else:
                                    set_text("Go ahead, I am listening...")
                                    user_input = self.voice.listen(timeout=8, phrase_time_limit=15, active_conversation=True)
                                    if user_input and self.running:
                                        if self.voice.is_valid_speech(user_input, active_conversation=True):
                                            self._handle_input(user_input)
                                        else:
                                            if not getattr(self, "assistant_replied", False):
                                                self._speak("I am listening, go ahead.")
                                    else:
                                        if not getattr(self, "assistant_replied", False):
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

    def _stop_cancel_command_helper(self):
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

    def _security_admin_helper(self, inp):
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

    def _weather_github_helper(self, inp, user_input):
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

    def _system_command_dispatcher_helper(self, inp, user_input):
        from skills.command_patterns import (
            WORKSPACE_PREPARE_WORDS, WORKSPACE_STUDY_WORDS, WORKSPACE_CLOSE_WORDS,
            AUTONOMOUS_TASK_RUN_WORDS, AUTONOMOUS_TASK_CANCEL_WORDS,
            OLLAMA_LAUNCH_WORDS, EXIT_APP_WORDS, GOODBYE_WORDS, RESET_MEMORY_WORDS,
            WINDOWS_OPEN_WORDS, TEACH_COMMAND_WORDS,
            LANGUAGE_HINDI_WORDS, LANGUAGE_TELUGU_WORDS, LANGUAGE_ENGLISH_WORDS, LANGUAGE_AUTO_WORDS,
            GESTURE_DISABLE_WORDS, GESTURE_ENABLE_WORDS
        )
        
        if any(x in inp for x in WORKSPACE_PREPARE_WORDS):
            self._speak("Setting up your Machine Learning workspace...")
            resp = self.workspace_skill.prepare_ml_workspace()
            self._speak("Workspace is configured.")
            return

        if any(x in inp for x in WORKSPACE_STUDY_WORDS):
            self._speak("Activating study focus mode...")
            resp = self.workspace_skill.study_mode()
            self._speak("Study mode is active. Distractions minimized.")
            return

        if any(x in inp for x in WORKSPACE_CLOSE_WORDS):
            self._speak("Cleaning up active workspace.")
            self.workspace_skill.close_workspace()
            return

        if inp.startswith("run task ") or inp.startswith("automate ") or inp.startswith("aria run "):
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

        if any(x in inp for x in AUTONOMOUS_TASK_CANCEL_WORDS):
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

        if "ollama launch" in inp or any(inp.startswith(prefix) for prefix in OLLAMA_LAUNCH_WORDS):
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

        if any(x in inp for x in EXIT_APP_WORDS):
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

        if any(x in inp for x in GOODBYE_WORDS):
            self._speak("Goodbye! Have a great day. I'll be here in sleep mode whenever you need me.")
            if hasattr(self, "conversation_session") and self.conversation_session:
                self.conversation_session.session_active = False
            return

        if any(x in inp for x in RESET_MEMORY_WORDS):
            self.brain.reset_conversation()
            self._speak("Conversation memory cleared. Fresh start!")
            return

        if any(x in inp for x in WINDOWS_OPEN_WORDS):
            windows = self.screen.list_open_windows()
            filtered = [w for w in windows if w.strip() and len(w) > 2][:8]
            if filtered:
                self._speak(f"I can see {len(filtered)} open windows: {', '.join(filtered[:5])}.")
            else:
                self._speak("I couldn't detect any open windows right now.")
            return

        if inp.startswith("press ") and any(x in inp for x in ["ctrl", "alt", "enter", "escape", "tab", "delete", "win"]):
            combo = inp.replace("press ", "").strip()
            keys = [k.strip() for k in combo.replace(" and ", "+").split("+")]
            self.screen.press(*keys)
            self._speak(f"Pressed {combo}.")
            return

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

        if any(x in inp for x in TEACH_COMMAND_WORDS):
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

        if self.voice:
            if any(x in inp for x in LANGUAGE_HINDI_WORDS):
                self.voice.stt_language = 'hi'
                self.voice.voice_model = 'hi-IN-SwaraNeural'
                self._speak("Speech recognition language switched to Hindi.")
                return
            if any(x in inp for x in LANGUAGE_TELUGU_WORDS):
                self.voice.stt_language = 'te'
                self.voice.voice_model = 'te-IN-ShrutiNeural'
                self._speak("Speech recognition language switched to Telugu.")
                return
            if any(x in inp for x in LANGUAGE_ENGLISH_WORDS):
                self.voice.stt_language = 'en'
                self.voice.voice_model = 'en-US-AriaNeural'
                self._speak("Speech recognition language switched to English.")
                return
            if any(x in inp for x in LANGUAGE_AUTO_WORDS):
                self.voice.stt_language = None
                self.voice.voice_model = 'en-US-AriaNeural'
                self._speak("Language lock disabled. Automatic language detection mode is active.")
                return

        if any(x in inp for x in GESTURE_DISABLE_WORDS):
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

        if any(x in inp for x in GESTURE_ENABLE_WORDS):
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
                msg = start_gesture_control(frame_provider=self.camera.capture_frame_raw, callback=self._gesture_event_callback)
                self.gesture_mode = True
                self._speak(msg)
            except Exception as e:
                print(f"[GestureControl] Failed to start: {e}")
                self._speak("Sorry, I could not start gesture control.")
            return

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
                os._exit(result.returncode)
            except KeyboardInterrupt:
                # Ctrl+C in venv child — exit cleanly without traceback
                os._exit(0)

    aria_instance = None
    qt_app = None
    qt_window = None
    is_shutting_down = False

    def shutdown_gracefully(sig=None, frame=None):
        nonlocal is_shutting_down
        if is_shutting_down:
            return
        is_shutting_down = True
        
        # Start a fallback watchdog thread to force exit if cleanup hangs
        def force_exit_watchdog():
            time.sleep(5.0)
            print("[ShutdownCoordinator] Force exit watchdog triggered after 5s cleanup timeout.")
            import os
            os._exit(0)
        
        threading.Thread(target=force_exit_watchdog, daemon=True).start()
        
        print("\n[ShutdownCoordinator] SIGINT (Ctrl+C) or exit request received. Initiating graceful shutdown...")
        
        # 1. Stop background run loops
        if aria_instance:
            print("[ShutdownCoordinator] Stopping agent loop...")
            aria_instance.running = False
            
            # Upload pending generated images to Firebase Storage on shutdown
            if hasattr(aria_instance, 'image_gen') and hasattr(aria_instance, 'firebase_sync') and aria_instance.firebase_sync:
                try:
                    aria_instance.firebase_sync.upload_pending_images(aria_instance.image_gen)
                except Exception as ex:
                    print(f"[ShutdownCoordinator] Failed uploading pending images: {ex}")
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
            if getattr(ModelCloudManager, "_instance", None) is not None:
                ModelCloudManager._instance.free_all_temps()
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
