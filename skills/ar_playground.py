"""
skills/ar_playground.py

Interactive AR Playground for ARIA
===================================
A high-performance webcam overlay system using MediaPipe HandLandmarker + OpenCV.
Features:
  1. Magic Wand: Neon particle trails following index finger.
  2. Flower Garden: Procedural vector blooming flowers.
  3. Air Piano: Procedural sound synth + color-coded bottom virtual keys.
  4. Virtual Pet: Holographic cat that follows finger and reacts to petting.
  5. Fist (0 fingers) gesture clears/erases particles.
"""

import os
import threading
import time
import math
import random
import cv2
import numpy as np
import pygame

# ─── MediaPipe import ─────────────────────────────────────────────────────────
try:
    import mediapipe as mp
    from mediapipe.tasks import python as _mp_python
    from mediapipe.tasks.python import vision as _mp_vision
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False

import sys
_SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'models', 'hand_landmarker.task')
_MODEL_PATH = os.path.normpath(os.path.abspath(_MODEL_PATH))

if _SKILL_DIR not in sys.path:
    sys.path.insert(0, _SKILL_DIR)

from ar_drawing import ARDrawing
from ar_physics import ARPhysics
from ar_face import ARFace
from ar_pose import ARPose
from ar_whiteboard import ARWhiteboard
from ar_object_interact import ARObjectInteract
from ar_3d_mode import AR3DMode, match_model
from ar_model_generator import ModelGenerator

# Minimal HUD Redesign Color Palette
WHITE     = (255, 255, 255)
GRAY_DARK = (40, 40, 40)
GRAY_MID  = (120, 120, 120)
ACCENT    = (200, 200, 200)

# ─── Audio Synthesis Helper ───────────────────────────────────────────────────
def generate_tone(frequency, duration=0.3, sample_rate=44100, volume=12000, type="sine"):
    """Generate a NumPy-synthesized pygame Sound with decay envelope."""
    try:
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        if type == "sine":
            wave = np.sin(2 * np.pi * frequency * t)
        elif type == "chirp":
            # Pitch sweep for pet cat mew sound
            f_t = np.linspace(frequency, frequency * 1.5, len(t))
            wave = np.sin(2 * np.pi * f_t * t)
        else:
            wave = np.sin(2 * np.pi * frequency * t)

        envelope = np.exp(-5.0 * t / duration)  # clean decay envelope
        wave = wave * envelope * volume
        wave = wave.astype(np.int16)
        stereo_wave = np.column_stack((wave, wave))
        return pygame.sndarray.make_sound(stereo_wave)
    except Exception as e:
        print(f"[ARPlayground] Sound synthesis error: {e}")
        return None

# ─── Helpers ──────────────────────────────────────────────────────────────────
def _dist(p1, p2):
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

class DummyHandLandmarks:
    def __init__(self, landmark_list):
        self.landmark = landmark_list

    def __getitem__(self, idx):
        return self.landmark[idx]

    def __len__(self):
        return len(self.landmark)

    def __iter__(self):
        return iter(self.landmark)

# ─── Main Subsystem ───────────────────────────────────────────────────────────
class ARPlayground:
    WINDOW = "ARIA AR Playground"
    MAX_PARTICLES = 300
    MAX_FLOWERS = 20

    def __init__(self, frame_provider, yolo_model=None, aria_brain=None, aria_speak=None, aria_instance=None):
        self._frame_provider = frame_provider
        self._yolo_model = yolo_model
        self._aria_brain = aria_brain
        self._aria_speak = aria_speak
        self._aria_instance = aria_instance
        self._running = False
        self._thread = None
        self._mode = "wand"  # "wand", "flowers", "piano", "pet"
        self.w = 1280
        self.h = 720

        # Lazy loaded mode objects
        self._drawing_obj = None
        self._physics_obj = None
        self._face_obj = None
        self._pose_obj = None
        self._whiteboard_obj = None
        self._object_obj = None
        self._3d_mode = None
        self._model_gen = None

        # MediaPipe Landmarks (updated in async callback)
        self._latest_lm = None
        self._lm_lock = threading.Lock()

        # Subsystem State Managers
        self.particles = []
        self.flowers = []
        self.pet_pos = [320, 240]
        self.pet_vel = [0, 0]
        self.pet_state = "idle"
        self.pet_last_mew = 0.0

        # Synth Sounds
        self.sounds = {}
        self._init_sounds()

        # Keyboard press tracker for piano
        self.piano_key_pressed = [False] * 5
        self.piano_keys = []

    @property
    def mode_drawing(self):
        if self._drawing_obj is None:
            self._drawing_obj = ARDrawing(self.w, self.h)
        return self._drawing_obj

    @property
    def mode_physics(self):
        if self._physics_obj is None:
            self._physics_obj = ARPhysics(self.w, self.h)
        return self._physics_obj

    @property
    def mode_face(self):
        if self._face_obj is None:
            self._face_obj = ARFace(self.w, self.h)
        return self._face_obj

    @property
    def mode_pose(self):
        if self._pose_obj is None:
            self._pose_obj = ARPose(self.w, self.h)
        return self._pose_obj

    @property
    def mode_whiteboard(self):
        if self._whiteboard_obj is None:
            self._whiteboard_obj = ARWhiteboard(self.w, self.h)
        return self._whiteboard_obj

    @property
    def mode_object(self):
        if self._object_obj is None:
            self._object_obj = ARObjectInteract(self.w, self.h, yolo_model=self._yolo_model, aria_brain=self._aria_brain)
        return self._object_obj

    @property
    def mode_ar3d(self):
        if self._3d_mode is None:
            self._3d_mode = AR3DMode(aria_brain=self._aria_brain)
            self._model_gen = ModelGenerator()
            self._3d_mode._model_gen = self._model_gen
        return self._3d_mode

    @property
    def thread(self):
        return self._thread


    def _init_sounds(self):
        """Pre-synthesize piano notes and cat sounds."""
        # Initialize mixer if not already done
        if not pygame.mixer.get_init():
            try:
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            except Exception as e:
                print(f"[ARPlayground] Pygame mixer init failed: {e}")
        
        # Synth Notes (C4, D4, E4, F4, G4 major scale)
        frequencies = [261.63, 293.66, 329.63, 349.23, 392.00]
        for idx, freq in enumerate(frequencies):
            self.sounds[f"note_{idx}"] = generate_tone(freq, duration=0.4, volume=12000)

        # Pet Mew sound
        self.sounds["mew"] = generate_tone(450.00, duration=0.18, volume=8000, type="chirp")
        # Purr sound
        self.sounds["purr"] = generate_tone(85.00, duration=0.25, volume=6000, type="sine")

    def set_mode(self, mode):
        """Set the current AR mode cleanly."""
        mode = mode.lower().strip()

        # Stop 3D mode if we are switching away from it
        if self._mode == "ar3d" and mode not in ["ar3d", "3d", "hologram"]:
            if self._3d_mode:
                self._3d_mode.stop()

        if mode in ["wand", "magic", "trail"]:
            self._mode = "wand"
        elif mode in ["flowers", "garden", "flower"]:
            self._mode = "flowers"
        elif mode in ["piano", "synth", "music"]:
            self._mode = "piano"
        elif mode in ["pet", "cat"]:
            self._mode = "pet"
        elif mode in ["drawing", "canvas"]:
            self._mode = "drawing"
        elif mode in ["physics", "balls"]:
            self._mode = "physics"
        elif mode in ["face", "mask", "face_ar"]:
            self._mode = "face"
        elif mode in ["pose", "body"]:
            self._mode = "pose"
        elif mode in ["whiteboard", "write"]:
            self._mode = "whiteboard"
        elif mode in ["object", "interact"]:
            self._mode = "object"
        elif mode in ["ar3d", "3d", "hologram"]:
            self._mode = "ar3d"
        print(f"[ARPlayground] Switched mode to: {self._mode.upper()}")
        self.clear_canvas()

        if self._mode == "ar3d":
            import time
            t0 = time.time()
            try:
                cv2.destroyWindow(self.WINDOW)
            except Exception:
                pass
            print(f"[ARPlayground Profiler] Destroyed OpenCV window in {time.time() - t0:.3f}s")
            
            t_start = time.time()
            self.mode_ar3d.start()
            print(f"[ARPlayground Profiler] mode_ar3d.start() returned in {time.time() - t_start:.3f}s")
            
            t_load = time.time()
            self.mode_ar3d.load_model("crystal")
            print(f"[ARPlayground Profiler] mode_ar3d.load_model('crystal') queued in {time.time() - t_load:.3f}s")
            
            if not getattr(self, "_announcer_started", False):
                self._announcer_started = True
                threading.Thread(target=self._progress_announcer, daemon=True).start()

    def _on_model_ready(self, prompt, path, is_completed_late=False):
        print(f"[AR3D] Model ready: {prompt} (late={is_completed_late})")
        if is_completed_late and self._aria_instance:
            self._aria_instance.pending_intent_action = {
                "type": "replace_high_quality_model",
                "model_key": prompt,
                "model_path": path,
                "expires_at": time.time() + 60.0
            }
            if self._aria_speak:
                self._aria_speak(f"Your enhanced {prompt} model is now ready. Would you like to replace the current one?")
        else:
            if self._3d_mode:
                self._3d_mode.load_model(prompt)
            if self._aria_speak:
                self._aria_speak(f"Your {prompt} model is ready. Loading now.")

    def _progress_announcer(self):
        """Speaks progress at key milestones."""
        announced = set()
        while self._running:
            try:
                if self._model_gen and self._model_gen._generating:
                    p = self._model_gen.progress
                    if p >= 25 and 25 not in announced:
                        announced.add(25)
                        if self._aria_speak:
                            self._aria_speak("25 percent done.")
                    elif p >= 50 and 50 not in announced:
                        announced.add(50)
                        if self._aria_speak:
                            self._aria_speak("Halfway there.")
                    elif p >= 75 and 75 not in announced:
                        announced.add(75)
                        if self._aria_speak:
                            self._aria_speak("Almost ready.")
                    elif p >= 100 and 100 not in announced:
                        announced.add(100)
                        announced.clear()
                else:
                    announced.clear()
            except Exception as announcer_err:
                print(f"[ARPlayground] Progress announcer error: {announcer_err}")
            time.sleep(2)

    def handle_subcommand(self, cmd_name):
        cmd_name = cmd_name.lower().strip()
        if self._mode == "ar3d" and self._3d_mode:
            # Check for transform actions first to prevent trigger collisions with loading
            is_transform = any(x in cmd_name for x in ["move", "rotate", "bigger", "smaller", "larger", "zoom", "reset", "center", "wireframe", "explode", "color", "show controls", "controls"])
            if is_transform:
                return self._3d_mode.voice_command(cmd_name)

            key = match_model(cmd_name)
            if key:
                if self._3d_mode._current_model_key == key:
                    self._3d_mode.voice_command("reset")
                    return f"The {key} model is already loaded. Focusing camera on the model."

                dest_path = os.path.join(_SKILL_DIR, "assets", "3d", f"{key}.obj")
                if not os.path.exists(dest_path) or os.path.getsize(dest_path) <= 1000:
                    print(f"[ARPlayground] Generating 3D model for '{key}' in background...")
                    def on_ready(path, is_completed_late=False):
                        self._on_model_ready(key, path, is_completed_late)
                    self._model_gen.generate(key, callback=on_ready)
                    return f"Generating 3D model for {key} in background. Please wait."
                else:
                    self._3d_mode.load_model(key)
                    return f"Loading {key} model."
            else:
                return self._3d_mode.voice_command(cmd_name)

        if cmd_name == "clear_board":
            if self._whiteboard_obj:
                self._whiteboard_obj.clear_board()
            if self._drawing_obj:
                self._drawing_obj.clear()
        elif cmd_name == "undo":
            if self._whiteboard_obj:
                self._whiteboard_obj.undo()
            if self._drawing_obj:
                self._drawing_obj.undo()
        elif cmd_name == "next_mask":
            if self._face_obj:
                self._face_obj.next_mask()
        elif cmd_name == "prev_mask":
            if self._face_obj:
                self._face_obj.prev_mask()
        elif cmd_name == "remember_current":
            if self._object_obj:
                self._object_obj.remember_current()

    def clear_canvas(self):
        """Clear all active drawn shapes and particles."""
        self.particles.clear()
        self.flowers.clear()

    def start(self):
        if self._running:
            return True
        if not MEDIAPIPE_AVAILABLE:
            print("[ARPlayground] MediaPipe unavailable. Cannot start AR mode.")
            return False
        if not os.path.exists(_MODEL_PATH):
            print(f"[ARPlayground] Model not found at {_MODEL_PATH}. Cannot start.")
            return False

        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ARPlayground")
        self._thread.start()
        
        # Start progress announcer on start if not already active
        if not getattr(self, "_announcer_started", False):
            self._announcer_started = True
            threading.Thread(target=self._progress_announcer, daemon=True).start()

        print("[ARPlayground] Subsystem started.")
        return True

    def stop(self):
        self._running = False
        self._announcer_started = False
        if self._3d_mode:
            self._3d_mode.stop()
            self._3d_mode = None
        print("[ARPlayground] Subsystem stopped.")

    def _on_result(self, result, _output_image, _timestamp_ms):
        lm = result.hand_landmarks[0] if result.hand_landmarks else None
        lm_list = result.hand_landmarks if result.hand_landmarks else []
        with self._lm_lock:
            self._latest_lm = lm
            self._latest_lm_list = lm_list

    def _loop(self):
        with open(_MODEL_PATH, "rb") as f:
            model_data = f.read()
        base_opts = _mp_python.BaseOptions(model_asset_buffer=model_data)
        options = _mp_vision.HandLandmarkerOptions(
            base_options=base_opts,
            running_mode=_mp_vision.RunningMode.LIVE_STREAM,
            num_hands=2,
            min_hand_detection_confidence=0.65,
            min_hand_presence_confidence=0.55,
            min_tracking_confidence=0.55,
            result_callback=self._on_result,
        )

        with _mp_vision.HandLandmarker.create_from_options(options) as landmarker:
            ts = 0
            hand_lost_frames = 0

            # Create named window with normal/resizable property and set default size
            cv2.namedWindow(self.WINDOW, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.WINDOW, 1280, 720)

            while self._running:
                t0 = time.time()
                
                # Check for camera sharing with VisionLearner to avoid lock contention/starvation
                frame = None
                if (self._aria_instance and hasattr(self._aria_instance, "vision_learner") 
                        and self._aria_instance.vision_learner and self._aria_instance.vision_learner.running):
                    try:
                        with self._aria_instance.vision_learner._lock:
                            if self._aria_instance.vision_learner.current_frame is not None:
                                frame = self._aria_instance.vision_learner.current_frame.copy()
                    except Exception as frame_err:
                        print(f"[ARPlayground] Error sharing frame with VisionLearner: {frame_err}")
                            
                if frame is None:
                    frame = self._frame_provider()

                if frame is None:
                    time.sleep(0.03)
                    continue


                # ── Aspect Ratio Corrective Cropping & Resizing ──
                h_orig, w_orig = frame.shape[:2]
                target_aspect = 16.0 / 9.0
                current_aspect = w_orig / h_orig
                
                if current_aspect > target_aspect:
                    target_w = int(h_orig * target_aspect)
                    crop_x1 = (w_orig - target_w) // 2
                    cropped = frame[:, crop_x1:crop_x1 + target_w]
                elif current_aspect < target_aspect:
                    target_h = int(w_orig / target_aspect)
                    crop_y1 = (h_orig - target_h) // 2
                    cropped = frame[crop_y1:crop_y1 + target_h, :]
                else:
                    cropped = frame
                
                frame_16_9 = cv2.resize(cropped, (1280, 720), interpolation=cv2.INTER_LINEAR)
                h, w = 720, 1280

                # Mirror frame for intuitive AR interaction
                flipped = cv2.flip(frame_16_9, 1)
                rgb = cv2.cvtColor(flipped, cv2.COLOR_BGR2RGB)
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                
                ts += 1
                landmarker.detect_async(mp_img, ts)

                with self._lm_lock:
                    lm = self._latest_lm
                    lm_list = getattr(self, '_latest_lm_list', [])

                # ── Hand Detection Timeout ──
                if lm is None:
                    hand_lost_frames += 1
                else:
                    hand_lost_frames = 0

                # Wrap raw lists for compatibility with modular solution-based components
                wrapped_lm = DummyHandLandmarks(lm) if lm is not None else None
                wrapped_lm_list = [DummyHandLandmarks(hand) for hand in lm_list] if lm_list else []

                # Render & update effects
                display = flipped.copy()
                self._update_and_draw(display, wrapped_lm, w, h, hand_lost_frames > 15, wrapped_lm_list)

                if self._mode == "ar3d":
                    cv2.waitKey(1)
                    # Actively destroy the window every frame to keep it hidden
                    try:
                        cv2.destroyWindow(self.WINDOW)
                    except:
                        pass
                else:
                    cv2.imshow(self.WINDOW, display)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q') or key == 27:
                        break

                elapsed = time.time() - t0
                sleep = (1.0 / 30) - elapsed
                if sleep > 0:
                    time.sleep(sleep)

        self._running = False
        try:
            for _ in range(5):
                cv2.waitKey(1)
            cv2.destroyWindow(self.WINDOW)
            for _ in range(5):
                cv2.waitKey(1)
        except Exception:
            pass

    # ── Update & Draw Main Routine ────────────────────────────────────────────
    def _update_and_draw(self, display, lm, w, h, hand_lost, lm_list=None):
        if lm_list is None:
            lm_list = []

        if self._mode in ["drawing", "physics", "face", "pose", "whiteboard", "object", "ar3d"]:
            if self._mode == "drawing":
                annotated = self.mode_drawing.process(display, lm)
            elif self._mode == "physics":
                annotated = self.mode_physics.process(display, lm, lm_list)
            elif self._mode == "face":
                annotated = self.mode_face.process(display)
            elif self._mode == "pose":
                annotated = self.mode_pose.process(display)
            elif self._mode == "whiteboard":
                annotated = self.mode_whiteboard.process(display, lm)
            elif self._mode == "object":
                annotated = self.mode_object.process(display, lm)
            elif self._mode == "ar3d":
                if self._3d_mode:
                    hand_obj = lm[0] if isinstance(lm, list) else lm
                    self._3d_mode.update_hand(hand_obj, w, h)
                annotated = display
            display[:] = annotated
            return

        # 1. Corner brackets (using LINE_AA for anti-aliasing)
        bracket_len = 20
        cv2.line(display, (0, 0), (bracket_len, 0), WHITE, 1, cv2.LINE_AA)
        cv2.line(display, (0, 0), (0, bracket_len), WHITE, 1, cv2.LINE_AA)
        cv2.line(display, (w - 1, 0), (w - 1 - bracket_len, 0), WHITE, 1, cv2.LINE_AA)
        cv2.line(display, (w - 1, 0), (w - 1, bracket_len), WHITE, 1, cv2.LINE_AA)
        cv2.line(display, (0, h - 1), (bracket_len, h - 1), WHITE, 1, cv2.LINE_AA)
        cv2.line(display, (0, h - 1), (0, h - 1 - bracket_len), WHITE, 1, cv2.LINE_AA)
        cv2.line(display, (w - 1, h - 1), (w - 1 - bracket_len, h - 1), WHITE, 1, cv2.LINE_AA)
        cv2.line(display, (w - 1, h - 1), (w - 1, h - 1 - bracket_len), WHITE, 1, cv2.LINE_AA)

        # 2. Gather Hand Landmarks in screen coordinates
        landmarks = {}
        n_fingers_up = 0
        is_fist = False

        if hand_lost:
            self.clear_canvas()
            self.piano_key_pressed = [False] * 5
        else:
            if lm is not None:
                for idx in [4, 8, 12, 16, 20, 3, 6, 10, 14, 18]:
                    landmarks[idx] = (int(lm[idx].x * w), int(lm[idx].y * h))
                thumb_up = lm[4].y < lm[3].y
                index_up = lm[8].y < lm[6].y
                middle_up = lm[12].y < lm[10].y
                ring_up = lm[16].y < lm[14].y
                pinky_up = lm[20].y < lm[18].y
                n_fingers_up = sum([thumb_up, index_up, middle_up, ring_up, pinky_up])
                is_fist = not (index_up or middle_up or ring_up or pinky_up)

            if is_fist and 8 in landmarks:
                fist_pt = landmarks[8]
                for _ in range(3):
                    self.particles.append({
                        "pos": [fist_pt[0] + random.randint(-15, 15), fist_pt[1] + random.randint(-15, 15)],
                        "vel": [random.uniform(-1, 1), random.uniform(-1, 1)],
                        "color": (25, 25, 40),
                        "size": random.randint(8, 15),
                        "age": 0,
                        "max_age": 12
                    })
                self.flowers = [f for f in self.flowers if _dist(f["pos"], fist_pt) > 80]
                self.particles = [p for p in self.particles if _dist(p["pos"], fist_pt) > 80 or p["color"] == (25, 25, 40)]

            if 8 in landmarks and not is_fist:
                index_pt = landmarks[8]
                if self._mode == "wand":
                    for _ in range(2):
                        self.particles.append({
                            "pos": [index_pt[0], index_pt[1]],
                            "vel": [random.uniform(-2, 2), random.uniform(-3, 1)],
                            "color": (random.randint(0, 50), random.randint(200, 255), random.randint(220, 255)),
                            "size": random.randint(4, 8),
                            "age": 0,
                            "max_age": 20
                        })
                elif self._mode == "flowers":
                    if random.random() < 0.12 and len(self.flowers) < self.MAX_FLOWERS:
                        col = random.choice([(203, 105, 255), (255, 120, 180), (0, 230, 255), (100, 255, 150)])
                        self.flowers.append({
                            "pos": [index_pt[0], index_pt[1]],
                            "size": 0.0,
                            "target_size": random.randint(22, 38),
                            "rot": random.uniform(0, 2 * math.pi),
                            "rot_speed": random.uniform(-0.05, 0.05),
                            "color": col,
                            "bloom_speed": random.uniform(0.04, 0.08)
                        })
                elif self._mode == "piano":
                    key_w = w // 5
                    key_h = 75
                    self.piano_keys = []
                    for i in range(5):
                        self.piano_keys.append((i * key_w, h - key_h, (i + 1) * key_w, h))
                    fingertips = [8, 12, 16, 20]
                    active_keys = [False] * 5
                    for f_idx in fingertips:
                        if f_idx in landmarks:
                            pt = landmarks[f_idx]
                            for k_idx, rect in enumerate(self.piano_keys):
                                if rect[0] <= pt[0] <= rect[2] and rect[1] <= pt[1] <= rect[3]:
                                    active_keys[k_idx] = True
                    for k_idx, active in enumerate(active_keys):
                        if active and not self.piano_key_pressed[k_idx]:
                            if f"note_{k_idx}" in self.sounds and self.sounds[f"note_{k_idx}"]:
                                self.sounds[f"note_{k_idx}"].play()
                            self.piano_key_pressed[k_idx] = True
                            rect = self.piano_keys[k_idx]
                            key_center = (rect[0] + rect[2]) // 2
                            for _ in range(5):
                                self.particles.append({
                                    "pos": [key_center + random.randint(-15, 15), rect[1]],
                                    "vel": [random.uniform(-1, 1), random.uniform(-3, -1)],
                                    "color": (random.randint(180, 255), random.randint(100, 255), 80),
                                    "size": random.randint(3, 6),
                                    "age": 0,
                                    "max_age": 25,
                                    "type": "music"
                                })
                        elif not active:
                            self.piano_key_pressed[k_idx] = False
                elif self._mode == "pet":
                    self.pet_pos[0] += (index_pt[0] - self.pet_pos[0]) * 0.08
                    self.pet_pos[1] += (index_pt[1] - self.pet_pos[1]) * 0.08
                    dist_to_finger = _dist(self.pet_pos, index_pt)
                    now = time.time()
                    if dist_to_finger < 45:
                        self.pet_state = "petting"
                        if now - self.pet_last_mew > 0.35:
                            if "purr" in self.sounds and self.sounds["purr"]:
                                self.sounds["purr"].play()
                            self.pet_last_mew = now
                        if random.random() < 0.15:
                            self.particles.append({
                                "pos": [int(self.pet_pos[0]) + random.randint(-15, 15), int(self.pet_pos[1]) - 10],
                                "vel": [random.uniform(-1, 1), random.uniform(-2, -0.8)],
                                "color": (80, 80, 255),
                                "size": random.randint(4, 7),
                                "age": 0,
                                "max_age": 22,
                                "type": "heart"
                            })
                    else:
                        self.pet_state = "walking"
                        if now - self.pet_last_mew > 4.5 and random.random() < 0.02:
                            if "mew" in self.sounds and self.sounds["mew"]:
                                self.sounds["mew"].play()
                            self.pet_last_mew = now

            for f in self.flowers:
                if f["size"] < f["target_size"]:
                    f["size"] += (f["target_size"] - f["size"]) * f["bloom_speed"]
                f["rot"] += f["rot_speed"]
                self._draw_procedural_flower(display, f)

            if self._mode == "piano" and self.piano_keys:
                key_colors = [(50, 50, 255), (50, 150, 255), (50, 255, 255), (50, 255, 50), (255, 100, 50)]
                key_names = ["C4", "D4", "E4", "F4", "G4"]
                for i, rect in enumerate(self.piano_keys):
                    is_active = self.piano_key_pressed[i]
                    col = key_colors[i]
                    if is_active:
                        cv2.rectangle(display, (rect[0], rect[1]), (rect[2], rect[3]), col, -1, cv2.LINE_AA)
                        cv2.rectangle(display, (rect[0], rect[1]), (rect[2], rect[3]), (255, 255, 255), 2, cv2.LINE_AA)
                    else:
                        overlay = display.copy()
                        cv2.rectangle(overlay, (rect[0], rect[1]), (rect[2], rect[3]), col, -1, cv2.LINE_AA)
                        cv2.addWeighted(overlay, 0.25, display, 0.75, 0, display)
                        cv2.rectangle(display, (rect[0], rect[1]), (rect[2], rect[3]), col, 1, cv2.LINE_AA)
                    cv2.putText(display, key_names[i], (rect[0] + 12, rect[1] + 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

            if self._mode == "pet":
                self._draw_hologram_cat(display)

            dead_particles = []
            for p in self.particles:
                p["pos"][0] += p["vel"][0]
                p["pos"][1] += p["vel"][1]
                p["age"] += 1
                if p["age"] >= p["max_age"]:
                    dead_particles.append(p)
                    continue
                alpha = (p["max_age"] - p["age"]) / p["max_age"]
                sz = max(1, int(p["size"] * alpha))
                col = p["color"]
                pt = (int(p["pos"][0]), int(p["pos"][1]))
                if p.get("type") == "heart":
                    cv2.circle(display, (pt[0]-2, pt[1]-2), sz//2, col, -1, cv2.LINE_AA)
                    cv2.circle(display, (pt[0]+2, pt[1]-2), sz//2, col, -1, cv2.LINE_AA)
                    pts = np.array([[pt[0]-sz, pt[1]], [pt[0]+sz, pt[1]], [pt[0], pt[1]+sz]], np.int32)
                    cv2.fillPoly(display, [pts], col, cv2.LINE_AA)
                elif p.get("type") == "music":
                    cv2.circle(display, pt, sz, col, -1, cv2.LINE_AA)
                    cv2.line(display, (pt[0]+sz//2, pt[1]), (pt[0]+sz//2, pt[1]-sz*2), col, 1, cv2.LINE_AA)
                    cv2.line(display, (pt[0]+sz//2, pt[1]-sz*2), (pt[0]+sz//2+sz, pt[1]-sz*2+sz//2), col, 1, cv2.LINE_AA)
                else:
                    cv2.circle(display, pt, sz, col, -1, cv2.LINE_AA)
            for p in dead_particles:
                if p in self.particles:
                    self.particles.remove(p)
            if len(self.particles) > self.MAX_PARTICLES:
                self.particles = self.particles[-self.MAX_PARTICLES:]

        self._draw_hud(display, n_fingers_up, is_fist)

    def _draw_procedural_flower(self, display, flower):
        cx, cy = int(flower["pos"][0]), int(flower["pos"][1])
        r = int(flower["size"])
        if r <= 0: return
        col = flower["color"]
        num_petals = 6
        for i in range(num_petals):
            angle = flower["rot"] + i * (2 * math.pi / num_petals)
            petal_cx = int(cx + math.cos(angle) * r * 0.65)
            petal_cy = int(cy + math.sin(angle) * r * 0.65)
            cv2.ellipse(display, (petal_cx, petal_cy), (r, r // 2), int(angle * 180 / math.pi), 0, 360, col, -1, cv2.LINE_AA)
            cv2.ellipse(display, (petal_cx, petal_cy), (r - 3 if r > 3 else 1, (r // 2) - 1 if r // 2 > 1 else 1), int(angle * 180 / math.pi), 0, 360, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.circle(display, (cx, cy), int(r * 0.45), (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(display, (cx, cy), int(r * 0.45), col, 2, cv2.LINE_AA)

    def _draw_hologram_cat(self, display):
        cx, cy = int(self.pet_pos[0]), int(self.pet_pos[1])
        color = (150, 255, 100)
        if self.pet_state == "petting": color = (180, 150, 255)
        left_ear = np.array([[cx - 24, cy - 8], [cx - 24, cy - 32], [cx - 6, cy - 14]], np.int32)
        right_ear = np.array([[cx + 24, cy - 8], [cx + 24, cy - 32], [cx + 6, cy - 14]], np.int32)
        cv2.fillPoly(display, [left_ear, right_ear], color, cv2.LINE_AA)
        cv2.circle(display, (cx, cy), 22, color, -1, cv2.LINE_AA)
        cv2.circle(display, (cx, cy), 22, (255, 255, 255), 1, cv2.LINE_AA)
        eye_color = (25, 25, 25)
        if self.pet_state == "petting":
            cv2.ellipse(display, (cx - 8, cy - 2), (5, 3), 0, 180, 360, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.ellipse(display, (cx + 8, cy - 2), (5, 3), 0, 180, 360, (255, 255, 255), 2, cv2.LINE_AA)
        else:
            cv2.circle(display, (cx - 7, cy - 3), 3, eye_color, -1, cv2.LINE_AA)
            cv2.circle(display, (cx + 7, cy - 3), 3, eye_color, -1, cv2.LINE_AA)
            cv2.circle(display, (cx - 6, cy - 4), 1, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(display, (cx + 8, cy - 4), 1, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(display, (cx, cy + 3), 2, (50, 50, 50), -1, cv2.LINE_AA)
        cv2.line(display, (cx, cy + 3), (cx, cy + 6), (50, 50, 50), 1, cv2.LINE_AA)
        cv2.ellipse(display, (cx - 3, cy + 7), (3, 2), 0, 0, 180, (50, 50, 50), 1, cv2.LINE_AA)
        cv2.ellipse(display, (cx + 3, cy + 7), (3, 2), 0, 0, 180, (50, 50, 50), 1, cv2.LINE_AA)
        cv2.line(display, (cx - 15, cy + 3), (cx - 30, cy + 1), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(display, (cx - 15, cy + 6), (cx - 28, cy + 7), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(display, (cx + 15, cy + 3), (cx + 30, cy + 1), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(display, (cx + 15, cy + 6), (cx + 28, cy + 7), (255, 255, 255), 1, cv2.LINE_AA)

    def _draw_hud(self, display, n_fingers, is_fist):
        h, w = display.shape[:2]
        cv2.line(display, (0, 50), (w, 50), GRAY_MID, 1, cv2.LINE_AA)
        cv2.putText(display, f"MODE: {self._mode.upper()}", (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 1, cv2.LINE_AA)
        overlay = display.copy()
        cv2.rectangle(overlay, (0, h - 30), (w, h), GRAY_DARK, -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.5, display, 0.5, 0, display)
        hint = "Commands: 'AR wand mode' | 'AR flower mode' | 'AR piano mode' | 'AR pet mode'"
        if is_fist:
            hint = "Closed Fist: Erasing drawn particles/flowers!"
        elif n_fingers > 0:
            hint = f"Hand Active ({n_fingers} finger(s) raised) | Fist to Clear"

        cv2.putText(display, hint, (12, h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, ACCENT, 1, cv2.LINE_AA)

def _draw_3d_hud_overlay(frame, lm, w, h):
    """Draw minimal hand tracking overlay when AR 3D mode is active."""
    from ar_drawing import _draw_corner_brackets, _draw_bottom_bar
    import cv2

    # Draw hand skeleton lightly
    connections = [
        (0,1),(1,2),(2,3),(3,4),
        (0,5),(5,6),(6,7),(7,8),
        (0,9),(9,10),(10,11),(11,12),
        (0,13),(13,14),(14,15),(15,16),
        (0,17),(17,18),(18,19),(19,20),
        (5,9),(9,13),(13,17),
    ]
    pts = [(int(lm.landmark[i].x * w), int(lm.landmark[i].y * h))
           for i in range(21)]
    for a, b in connections:
        cv2.line(frame, pts[a], pts[b], (100, 180, 255), 1, cv2.LINE_AA)
    for pt in pts:
        cv2.circle(frame, pt, 3, (200, 220, 255), -1, cv2.LINE_AA)

    # Top HUD
    cv2.line(frame, (0, 48), (w, 48), (180, 180, 180), 1)
    cv2.putText(frame, "MODE: AR 3D HOLOGRAM", (12, 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    _draw_corner_brackets(frame)
    _draw_bottom_bar(frame,
        "Pinch=Rotate | Two-finger=Zoom | Fist=Explode | OpenPalm=Reset")
