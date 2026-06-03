"""
skills/voice_session_commands.py — Extracted Speech and Session logic for ARIA
==============================================================================
Encapsulates Edge-TTS sequential playback workers and conversation session states.
Does not import main.py directly.
"""
import re
import time
import threading
from skills.subsystem_health import HEALTH, SUBSYSTEM_TTS

try:
    from gui import set_state, set_text, trigger_wave
except ImportError:
    def set_state(s): pass
    def set_text(t): pass
    def trigger_wave(): pass


def sanitize_spoken_text(aria, text):
    if not text:
        return text
    cleaned = str(text).strip()
    if not aria.startup_greeting_done:
        return cleaned

    names = ["chinmay", "chinmaya"]
    if aria.known_user:
        names.append(str(aria.known_user).strip().lower().rstrip("."))
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


def speak(aria, text, source=None, allow_barge_in=True):
    print(f"[VoiceSessionCommands/speak] Entry text: {text[:100]}")
    if hasattr(aria, "conversation_session") and aria.conversation_session.session_active:
        aria._mark_conversation_activity(wake_reason="assistant_reply")
    text = sanitize_spoken_text(aria, text)
    if hasattr(aria, "_spoken_during_turn") and aria._spoken_during_turn is not None:
        aria._spoken_during_turn.append(text)
        
    # Resolve source:
    if source is None:
        is_remote = False
        if hasattr(aria, 'firebase_sync') and aria.firebase_sync:
            if getattr(aria.firebase_sync, "current_command_id", None) is not None:
                is_remote = True
        if is_remote or getattr(aria._reply_context, "phone_only", False):
            source = "phone"
        else:
            source = "laptop"

    print(f"[Input Source] {source}")
    
    if source == "phone":
        print(f"[Output Route] phone_tts")
        print(f"[ARIA/Phone Reply] {text}")
        if hasattr(aria, 'firebase_sync') and aria.firebase_sync:
            aria.firebase_sync.update_status(text, status_str="idle")
            if aria.firebase_sync.firestore_client:
                try:
                    aria.firebase_sync.firestore_client.collection("phone_reply").document("latest").set({
                        "response": text,
                        "timestamp": time.time()
                    })
                except Exception as db_err:
                    print(f"[VoiceSessionCommands] Could not write to phone_reply/latest: {db_err}")
        return

    # Output route is laptop
    print(f"[Output Route] laptop_tts")

    # Graceful TTS degradation — if TTS subsystem is FAILED, fall back to console
    if not HEALTH.is_available(SUBSYSTEM_TTS):
        print(f"[ARIA/TTS-OFFLINE] {text}")
        try:
            set_text(text[:120] + "..." if len(text) > 120 else text)
        except Exception:
            pass
        return

    # Push to the thread-safe queue for sequential processing
    if aria.speech_queue:
        aria.speech_queue.put((text, allow_barge_in))
    else:
        if aria.voice:
            aria.voice.speak(text, allow_barge_in=allow_barge_in)


def wait_for_speech(aria):
    if aria.speech_queue:
        aria.speech_queue.join()
    while aria.voice and aria.voice.is_speaking:
        time.sleep(0.05)


def speech_worker(aria):
    while True:
        try:
            # Blocks until an item is available
            item = aria.speech_queue.get()
            if item is None:
                break
            if isinstance(item, tuple):
                text, allow_barge_in = item
            else:
                text = item
                allow_barge_in = True
            print(f"[SpeechWorker] Got text from queue: {text[:100]} (allow_barge_in={allow_barge_in})")

            if aria.voice and aria.voice.is_user_actively_speaking:
                print("[SpeechWorker] User is actively speaking. Discarding response and clearing queues.")
                while not aria.speech_queue.empty():
                    try:
                        aria.speech_queue.get_nowait()
                        aria.speech_queue.task_done()
                    except Exception:
                        break
                if hasattr(aria, "pending_speech"):
                    aria.pending_speech.clear()
                aria.speech_queue.task_done()
                continue

            set_state("SPEAKING")
            set_text(text[:100] + "..." if len(text) > 100 else text)
            if hasattr(aria, 'firebase_sync') and aria.firebase_sync:
                aria.firebase_sync.update_status(text, status_str="speaking")

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
                interrupted = aria.voice.speak(text, allow_barge_in=allow_barge_in)
                # Mark TTS healthy on successful speak
                if HEALTH.get_status(SUBSYSTEM_TTS) != "HEALTHY":
                    HEALTH.mark_healthy(SUBSYSTEM_TTS, "TTS recovered — speak succeeded")
            except Exception as _tts_err:
                print(f"[SpeechWorker] TTS exception: {_tts_err}")
                HEALTH.mark_degraded(SUBSYSTEM_TTS, f"TTS speak error: {_tts_err}")
                interrupted = False

            _stop_wave.set()
            aria.speech_queue.task_done()

            if interrupted:
                print("[SpeechWorker] Speech was interrupted! Clearing the speech queue.")
                try:
                    aria.cognitive_load_manager.log_interruption()
                except Exception:
                    pass
                
                while not aria.speech_queue.empty():
                    try:
                        aria.speech_queue.get_nowait()
                        aria.speech_queue.task_done()
                    except Exception:
                        break
                
                if hasattr(aria, "pending_speech"):
                    aria.pending_speech.clear()
                        
                set_state("IDLE")
                if hasattr(aria, 'firebase_sync') and aria.firebase_sync:
                    aria.firebase_sync.update_status("", status_str="idle")
                aria.last_interaction_time = time.time()
                continue

            # Transition back to IDLE only if queue is empty
            if aria.speech_queue.empty():
                set_state("IDLE")
                if hasattr(aria, 'firebase_sync') and aria.firebase_sync:
                    aria.firebase_sync.update_status(text, status_str="idle")
        except Exception as e:
            print(f"[SpeechWorker] Error: {e}")
            time.sleep(0.1)


def mark_conversation_activity(aria, wake_reason="interaction", active_task_id=None):
    aria.last_interaction_time = time.time()
    if hasattr(aria, "conversation_session"):
        aria.conversation_session.touch(wake_reason=wake_reason, active_task_id=active_task_id)


def is_aria_busy(aria):
    # Check AR playground is running
    if getattr(aria, 'ar_playground', None) is not None and aria.ar_playground._running:
        return True
    # Check 3D model is currently generating
    if getattr(aria, 'ar_playground', None) is not None:
        ar = aria.ar_playground
        if getattr(ar, '_model_gen', None) is not None:
            if getattr(ar._model_gen, '_generating', False):
                return True
    # Check vision learner running
    if getattr(aria, 'vision_learner', None) is not None and getattr(aria.vision_learner, 'running', False):
        return True
    # Check gesture control running
    if getattr(aria, 'gesture_mode', False):
        return True
    return False


def has_active_conversation_task(aria):
    if is_aria_busy(aria):
        aria.conversation_session.touch(wake_reason="background_subsystem")
        return True
    try:
        if aria.brain and aria.brain.semantic_router:
            active = aria.brain.semantic_router.task_manager.get_active_task()
            if active and getattr(active, "status", "") in {"RUNNING", "WAITING", "INTERRUPTED"}:
                return True
    except Exception:
        pass
    try:
        active = aria.executor_queue.get_active_task() if hasattr(aria, "executor_queue") else None
        if active:
            return True
    except Exception:
        pass
    return bool(getattr(aria, "automation_mode", False))
