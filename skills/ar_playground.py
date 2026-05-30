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

_SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SKILL_DIR)
_MODEL_PATH = os.path.join(_PROJECT_DIR, "models", "hand_landmarker.task")

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

# ─── Main Subsystem ───────────────────────────────────────────────────────────
class ARPlayground:
    WINDOW = "ARIA AR Playground"
    MAX_PARTICLES = 300
    MAX_FLOWERS = 20

    def __init__(self, frame_provider):
        self._frame_provider = frame_provider
        self._running = False
        self._thread = None
        self._mode = "wand"  # "wand", "flowers", "piano", "pet"

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
        if mode in ["wand", "magic", "trail"]:
            self._mode = "wand"
        elif mode in ["flowers", "garden", "flower"]:
            self._mode = "flowers"
        elif mode in ["piano", "synth", "music"]:
            self._mode = "piano"
        elif mode in ["pet", "cat"]:
            self._mode = "pet"
        print(f"[ARPlayground] Switched mode to: {self._mode.upper()}")
        self.clear_canvas()

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
        print("[ARPlayground] Subsystem started.")
        return True

    def stop(self):
        self._running = False
        print("[ARPlayground] Subsystem stopped.")

    def _on_result(self, result, _output_image, _timestamp_ms):
        lm = result.hand_landmarks[0] if result.hand_landmarks else None
        with self._lm_lock:
            self._latest_lm = lm

    def _loop(self):
        base_opts = _mp_python.BaseOptions(model_asset_path=_MODEL_PATH)
        options = _mp_vision.HandLandmarkerOptions(
            base_options=base_opts,
            running_mode=_mp_vision.RunningMode.LIVE_STREAM,
            num_hands=1,
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
                frame = self._frame_provider()

                if frame is None:
                    time.sleep(0.03)
                    continue

                h, w = frame.shape[:2]
                # Mirror frame for intuitive AR interaction
                flipped = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(flipped, cv2.COLOR_BGR2RGB)
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                
                ts += 1
                landmarker.detect_async(mp_img, ts)

                with self._lm_lock:
                    lm = self._latest_lm

                # ── Hand Detection Timeout ──
                if lm is None:
                    hand_lost_frames += 1
                else:
                    hand_lost_frames = 0

                # Render & update effects
                display = flipped.copy()
                self._update_and_draw(display, lm, w, h, hand_lost_frames > 15)

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
    def _update_and_draw(self, display, lm, w, h, hand_lost):
        # 1. Corner brackets instead of full border
        bracket_len = 20
        # top-left
        cv2.line(display, (0, 0), (bracket_len, 0), WHITE, 1)
        cv2.line(display, (0, 0), (0, bracket_len), WHITE, 1)
        # top-right
        cv2.line(display, (w - 1, 0), (w - 1 - bracket_len, 0), WHITE, 1)
        cv2.line(display, (w - 1, 0), (w - 1, bracket_len), WHITE, 1)
        # bottom-left
        cv2.line(display, (0, h - 1), (bracket_len, h - 1), WHITE, 1)
        cv2.line(display, (0, h - 1), (0, h - 1 - bracket_len), WHITE, 1)
        # bottom-right
        cv2.line(display, (w - 1, h - 1), (w - 1 - bracket_len, h - 1), WHITE, 1)
        cv2.line(display, (w - 1, h - 1), (w - 1, h - 1 - bracket_len), WHITE, 1)

        # 2. Gather Hand Landmarks in screen coordinates
        landmarks = {}
        n_fingers_up = 0
        is_fist = False

        if hand_lost:
            self.clear_canvas()
            # Reset piano key state when hand is lost
            self.piano_key_pressed = [False] * 5
        else:
            if lm is not None:
                # Map landmarks to pixel space
                for idx in [4, 8, 12, 16, 20, 3, 6, 10, 14, 18]:
                    landmarks[idx] = (int(lm[idx].x * w), int(lm[idx].y * h))

                # Detect raised fingers
                thumb_up = lm[4].y < lm[3].y
                index_up = lm[8].y < lm[6].y
                middle_up = lm[12].y < lm[10].y
                ring_up = lm[16].y < lm[14].y
                pinky_up = lm[20].y < lm[18].y
                
                n_fingers_up = sum([thumb_up, index_up, middle_up, ring_up, pinky_up])
                # Fist detection
                is_fist = not (index_up or middle_up or ring_up or pinky_up)

            # 3. Closed Fist Erase Feature
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

            # 4. Mode Processing
            if 8 in landmarks and not is_fist:
                index_pt = landmarks[8]

                if self._mode == "wand":
                    for _ in range(2):
                        self.particles.append({
                            "pos": [index_pt[0], index_pt[1]],
                            "vel": [random.uniform(-2, 2), random.uniform(-3, 1)],
                            "color": (random.randint(0, 50), random.randint(200, 255), random.randint(220, 255)), # cyan glow
                            "size": random.randint(4, 8),
                            "age": 0,
                            "max_age": 20
                        })

                elif self._mode == "flowers":
                    if random.random() < 0.12 and len(self.flowers) < self.MAX_FLOWERS:
                        col = random.choice([
                            (203, 105, 255),  # magenta
                            (255, 120, 180),  # soft pink
                            (0, 230, 255),    # neon yellow
                            (100, 255, 150)   # mint green
                        ])
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

            # 5. Render Flowers (only when not hand_lost)
            for f in self.flowers:
                if f["size"] < f["target_size"]:
                    f["size"] += (f["target_size"] - f["size"]) * f["bloom_speed"]
                f["rot"] += f["rot_speed"]
                self._draw_procedural_flower(display, f)

            # 6. Draw Piano keyboard keys (only when not hand_lost)
            if self._mode == "piano" and self.piano_keys:
                key_colors = [
                    (50, 50, 255),   # C4 Red BGR
                    (50, 150, 255),  # D4 Orange
                    (50, 255, 255),  # E4 Yellow
                    (50, 255, 50),   # F4 Green
                    (255, 100, 50)   # G4 Blue
                ]
                key_names = ["C4", "D4", "E4", "F4", "G4"]
                for i, rect in enumerate(self.piano_keys):
                    is_active = self.piano_key_pressed[i]
                    col = key_colors[i]
                    if is_active:
                        cv2.rectangle(display, (rect[0], rect[1]), (rect[2], rect[3]), col, -1)
                        cv2.rectangle(display, (rect[0], rect[1]), (rect[2], rect[3]), (255, 255, 255), 2)
                    else:
                        overlay = display.copy()
                        cv2.rectangle(overlay, (rect[0], rect[1]), (rect[2], rect[3]), col, -1)
                        cv2.addWeighted(overlay, 0.25, display, 0.75, 0, display)
                        cv2.rectangle(display, (rect[0], rect[1]), (rect[2], rect[3]), col, 1)
                    
                    cv2.putText(display, key_names[i], (rect[0] + 12, rect[1] + 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            # 7. Draw Virtual Pet Cat (only when not hand_lost)
            if self._mode == "pet":
                self._draw_hologram_cat(display)

            # 8. Update and Draw Particles (only when not hand_lost)
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
                    cv2.circle(display, (pt[0]-2, pt[1]-2), sz//2, col, -1)
                    cv2.circle(display, (pt[0]+2, pt[1]-2), sz//2, col, -1)
                    pts = np.array([[pt[0]-sz, pt[1]], [pt[0]+sz, pt[1]], [pt[0], pt[1]+sz]], np.int32)
                    cv2.fillPoly(display, [pts], col)
                elif p.get("type") == "music":
                    cv2.circle(display, pt, sz, col, -1)
                    cv2.line(display, (pt[0]+sz//2, pt[1]), (pt[0]+sz//2, pt[1]-sz*2), col, 1)
                    cv2.line(display, (pt[0]+sz//2, pt[1]-sz*2), (pt[0]+sz//2+sz, pt[1]-sz*2+sz//2), col, 1)
                else:
                    cv2.circle(display, pt, sz, col, -1)

            for p in dead_particles:
                if p in self.particles:
                    self.particles.remove(p)

            if len(self.particles) > self.MAX_PARTICLES:
                self.particles = self.particles[-self.MAX_PARTICLES:]

        # 9. HUD / Text Panel
        self._draw_hud(display, n_fingers_up, is_fist)

    # ── Custom Vector Graphics Renderers ──────────────────────────────────────
    def _draw_procedural_flower(self, display, flower):
        """Draw a beautiful vector flower with rotating petals."""
        cx, cy = int(flower["pos"][0]), int(flower["pos"][1])
        r = int(flower["size"])
        if r <= 0:
            return
        col = flower["color"]
        num_petals = 6

        # Draw Petals
        for i in range(num_petals):
            angle = flower["rot"] + i * (2 * math.pi / num_petals)
            # Offset center of petal
            petal_cx = int(cx + math.cos(angle) * r * 0.65)
            petal_cy = int(cy + math.sin(angle) * r * 0.65)
            
            # Petal shapes (rotated ellipses)
            cv2.ellipse(
                display,
                (petal_cx, petal_cy),
                (r, r // 2),
                int(angle * 180 / math.pi),
                0, 360, col, -1
            )
            # Inner white/light glow lines on petals
            cv2.ellipse(
                display,
                (petal_cx, petal_cy),
                (r - 3 if r > 3 else 1, (r // 2) - 1 if r // 2 > 1 else 1),
                int(angle * 180 / math.pi),
                0, 360, (255, 255, 255), 1
            )

        # Draw Center Core
        cv2.circle(display, (cx, cy), int(r * 0.45), (255, 255, 255), -1)
        cv2.circle(display, (cx, cy), int(r * 0.45), col, 2)

    def _draw_hologram_cat(self, display):
        """Draw a retro-futuristic hologram cat face in pixel space."""
        cx, cy = int(self.pet_pos[0]), int(self.pet_pos[1])
        color = (150, 255, 100)  # neon green cat hologram
        if self.pet_state == "petting":
            color = (180, 150, 255)  # pastel pink/purple when happy

        # 1. Ears (Triangles)
        left_ear = np.array([[cx - 24, cy - 8], [cx - 24, cy - 32], [cx - 6, cy - 14]], np.int32)
        right_ear = np.array([[cx + 24, cy - 8], [cx + 24, cy - 32], [cx + 6, cy - 14]], np.int32)
        cv2.fillPoly(display, [left_ear, right_ear], color)
        
        # 2. Main Face Circle
        cv2.circle(display, (cx, cy), 22, color, -1)
        cv2.circle(display, (cx, cy), 22, (255, 255, 255), 1)

        # 3. Eyes
        eye_color = (25, 25, 25)
        # Happy eyes when petting
        if self.pet_state == "petting":
            # Drawing curve arcs for happy squinting eyes
            cv2.ellipse(display, (cx - 8, cy - 2), (5, 3), 0, 180, 360, (255, 255, 255), 2)
            cv2.ellipse(display, (cx + 8, cy - 2), (5, 3), 0, 180, 360, (255, 255, 255), 2)
        else:
            cv2.circle(display, (cx - 7, cy - 3), 3, eye_color, -1)
            cv2.circle(display, (cx + 7, cy - 3), 3, eye_color, -1)
            cv2.circle(display, (cx - 6, cy - 4), 1, (255, 255, 255), -1)  # eye glint
            cv2.circle(display, (cx + 8, cy - 4), 1, (255, 255, 255), -1)

        # 4. Nose & Mouth
        cv2.circle(display, (cx, cy + 3), 2, (50, 50, 50), -1)  # tiny nose
        cv2.line(display, (cx, cy + 3), (cx, cy + 6), (50, 50, 50), 1)
        cv2.ellipse(display, (cx - 3, cy + 7), (3, 2), 0, 0, 180, (50, 50, 50), 1)
        cv2.ellipse(display, (cx + 3, cy + 7), (3, 2), 0, 0, 180, (50, 50, 50), 1)

        # 5. Whiskers
        cv2.line(display, (cx - 15, cy + 3), (cx - 30, cy + 1), (255, 255, 255), 1)
        cv2.line(display, (cx - 15, cy + 6), (cx - 28, cy + 7), (255, 255, 255), 1)
        cv2.line(display, (cx + 15, cy + 3), (cx + 30, cy + 1), (255, 255, 255), 1)
        cv2.line(display, (cx + 15, cy + 6), (cx + 28, cy + 7), (255, 255, 255), 1)

    def _draw_hud(self, display, n_fingers, is_fist):
        """Draw minimal overlay dashboards and text indicators."""
        h, w = display.shape[:2]

        # Top HUD bar - thin 1px line separator instead of filled rectangle
        cv2.line(display, (0, 50), (w, 50), GRAY_MID, 1)

        # Mode text - clean, no background box
        cv2.putText(display, f"MODE: {self._mode.upper()}", (12, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 1, cv2.LINE_AA)

        # Bottom command bar — semi-transparent dark strip
        overlay = display.copy()
        cv2.rectangle(overlay, (0, h - 30), (w, h), GRAY_DARK, -1)
        cv2.addWeighted(overlay, 0.5, display, 0.5, 0, display)

        hint = "Commands: 'AR wand mode' | 'AR flower mode' | 'AR piano mode' | 'AR pet mode'"
        if is_fist:
            hint = "Closed Fist: Erasing drawn particles/flowers!"
        elif n_fingers > 0:
            hint = f"Hand Active ({n_fingers} finger(s) raised) | Fist to Clear"

        cv2.putText(display, hint, (12, h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, ACCENT, 1, cv2.LINE_AA)
