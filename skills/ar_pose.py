"""
ar_pose.py — ARIA Advanced AR Suite
Mode: Pose Detection
Voice triggers: "AR pose mode", "AR body mode"

Features:
- Full body skeleton overlay (33 landmarks)
- Both arms raised = particle burst
- T-pose = saves screenshot
- Right arm point = moves mouse cursor
- Jump = plays sound effect
- Live joint angle display (elbows, knees)
"""

import cv2
import numpy as np
import math
import random
import time
import os

import mediapipe as mp
import pyautogui

from ar_drawing import _draw_corner_brackets, _draw_bottom_bar

# ── MediaPipe Pose ────────────────────────────────────────────────────────────
_mp_pose = mp.solutions.pose
_pose = _mp_pose.Pose(
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
    model_complexity=0
)

# Skeleton connections (pairs of landmark indices)
_SKELETON = [
    # Torso
    (11, 12), (11, 23), (12, 24), (23, 24),
    # Left arm
    (11, 13), (13, 15), (15, 17), (15, 19), (15, 21),
    # Right arm
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22),
    # Left leg
    (23, 25), (25, 27), (27, 29), (27, 31),
    # Right leg
    (24, 26), (26, 28), (28, 30), (28, 32),
    # Face connections
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8),
    (9, 10), (11, 12),
]

# Joint angle triples (vertex in middle)
_ANGLE_JOINTS = [
    (11, 13, 15, "L-ELBOW"),
    (12, 14, 16, "R-ELBOW"),
    (23, 25, 27, "L-KNEE"),
    (24, 26, 28, "R-KNEE"),
]


def _lm_px(landmark, w, h):
    return int(landmark.x * w), int(landmark.y * h)


def _angle_3pts(a, b, c):
    """Angle at b formed by a-b-c."""
    ba = (a[0] - b[0], a[1] - b[1])
    bc = (c[0] - b[0], c[1] - b[1])
    dot = ba[0]*bc[0] + ba[1]*bc[1]
    mag = math.hypot(*ba) * math.hypot(*bc)
    if mag == 0:
        return 0
    return math.degrees(math.acos(max(-1, min(1, dot / mag))))


class ARPose:

    def __init__(self, frame_w, frame_h):
        self.w = frame_w
        self.h = frame_h
        self.label = "POSE"

        # Gesture state
        self._arms_raised_time = 0
        self._last_burst_time  = 0
        self._last_tpose_time  = 0
        self._last_jump_time   = 0

        # Jump detection
        self._prev_hip_y = None
        self._jump_peak  = False

        # Particles
        self._particles = []

        # Screenshot save folder
        self._save_dir = os.path.join(os.path.expanduser("~"), "ARIA_Poses")
        os.makedirs(self._save_dir, exist_ok=True)

        # Mouse control state
        self._mouse_active = False
        self._screen_w, self._screen_h = pyautogui.size()

        # Sound (pygame must be init'd by ar_playground.py)
        self._sound_ready = False
        try:
            import pygame
            if pygame.mixer.get_init():
                self._pygame = pygame
                self._sound_ready = True
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, frame):
        out = frame.copy()
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = _pose.process(rgb)

        if results.pose_landmarks:
            lms = results.pose_landmarks.landmark
            self._draw_skeleton(out, lms)
            self._draw_joint_angles(out, lms)
            self._detect_gestures(out, lms)
        else:
            cv2.putText(out, "BODY NOT DETECTED", (20, out.shape[0] // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1, cv2.LINE_AA)

        self._update_particles(out)
        self._draw_hud(out)
        return out

    # ── Skeleton Drawing ──────────────────────────────────────────────────

    def _draw_skeleton(self, frame, lms):
        w, h = self.w, self.h

        # Color segments by body part
        segment_colors = {
            'torso': (200, 200, 200),
            'arm':   (0, 210, 255),
            'leg':   (100, 255, 100),
            'face':  (180, 180, 180),
        }

        def seg_color(a, b):
            if a in (11,12,23,24) and b in (11,12,23,24):
                return segment_colors['torso']
            if a <= 10 or b <= 10:
                return segment_colors['face']
            if a in range(11,23) or b in range(11,23):
                return segment_colors['arm']
            return segment_colors['leg']

        for a_idx, b_idx in _SKELETON:
            la = lms[a_idx]
            lb = lms[b_idx]
            if la.visibility < 0.5 or lb.visibility < 0.5:
                continue
            pa = _lm_px(la, w, h)
            pb = _lm_px(lb, w, h)
            col = seg_color(a_idx, b_idx)
            cv2.line(frame, pa, pb, col, 2, cv2.LINE_AA)

        # Draw landmark dots
        for i, lm in enumerate(lms):
            if lm.visibility < 0.5:
                continue
            px = _lm_px(lm, w, h)
            cv2.circle(frame, px, 4, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(frame, px, 4, (100, 100, 100), 1,  cv2.LINE_AA)

    # ── Joint Angles ──────────────────────────────────────────────────────

    def _draw_joint_angles(self, frame, lms):
        w, h = self.w, self.h
        for a_idx, b_idx, c_idx, label in _ANGLE_JOINTS:
            la, lb, lc = lms[a_idx], lms[b_idx], lms[c_idx]
            if min(la.visibility, lb.visibility, lc.visibility) < 0.5:
                continue
            pa = _lm_px(la, w, h)
            pb = _lm_px(lb, w, h)
            pc = _lm_px(lc, w, h)
            angle = _angle_3pts(pa, pb, pc)

            # Arc visualization
            cv2.ellipse(frame, pb, (20, 20), 0, 0, int(angle), (255, 200, 0), 1)

            # Text label
            tx = pb[0] + 10
            ty = pb[1] - 5
            cv2.putText(frame, f"{int(angle)}", (tx, ty),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 200, 0), 1, cv2.LINE_AA)

    # ── Gesture Detection ─────────────────────────────────────────────────

    def _detect_gestures(self, out, lms):
        now = time.time()
        w, h = self.w, self.h

        l_wrist = lms[15]
        r_wrist = lms[16]
        l_shoulder = lms[11]
        r_shoulder = lms[12]
        l_hip = lms[23]
        r_hip = lms[24]

        # ── Both arms raised ──────────────────────────────────────────────
        if (l_wrist.visibility > 0.5 and r_wrist.visibility > 0.5 and
                l_wrist.y < l_shoulder.y and r_wrist.y < r_shoulder.y):
            if now - self._last_burst_time > 2.0:
                self._spawn_burst(out)
                self._last_burst_time = now
        
        # ── T-pose detection ──────────────────────────────────────────────
        if (l_wrist.visibility > 0.5 and r_wrist.visibility > 0.5):
            l_arm_horiz = abs(l_wrist.y - l_shoulder.y) < 0.08
            r_arm_horiz = abs(r_wrist.y - r_shoulder.y) < 0.08
            arms_wide = abs(l_wrist.x - r_wrist.x) > 0.5
            if l_arm_horiz and r_arm_horiz and arms_wide:
                if now - self._last_tpose_time > 3.0:
                    self._save_screenshot(out)
                    self._last_tpose_time = now
                    cv2.putText(out, "SCREENSHOT SAVED!", (w//2 - 90, h//2),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

        # ── Right arm point → mouse control ──────────────────────────────
        if r_wrist.visibility > 0.6:
            r_elbow = lms[14]
            # Pointing = wrist extended beyond elbow on same line
            wrist_px  = _lm_px(r_wrist, w, h)
            elbow_px  = _lm_px(r_elbow, w, h)
            shoulder_px = _lm_px(r_shoulder, w, h)
            
            # Check if arm is somewhat straight and pointing (not bent)
            angle = _angle_3pts(shoulder_px, elbow_px, wrist_px)
            if angle > 155:  # arm nearly straight
                # Map wrist position to screen
                mx = int(r_wrist.x * self._screen_w)
                my = int(r_wrist.y * self._screen_h)
                mx = max(0, min(self._screen_w - 1, mx))
                my = max(0, min(self._screen_h - 1, my))
                try:
                    pyautogui.moveTo(mx, my, duration=0.05)
                except Exception:
                    pass
                # Visual indicator
                cv2.circle(out, wrist_px, 12, (0, 255, 200), 2)
                cv2.putText(out, "MOUSE", (wrist_px[0]+14, wrist_px[1]),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 200), 1, cv2.LINE_AA)

        # ── Jump detection ────────────────────────────────────────────────
        if l_hip.visibility > 0.5 and r_hip.visibility > 0.5:
            hip_y = (l_hip.y + r_hip.y) / 2
            if self._prev_hip_y is not None:
                delta = hip_y - self._prev_hip_y
                # Hips moved up fast = jump
                if delta < -0.04 and not self._jump_peak:
                    self._jump_peak = True
                elif delta > 0.02 and self._jump_peak:
                    self._jump_peak = False
                    if now - self._last_jump_time > 1.0:
                        self._play_jump_sound()
                        self._last_jump_time = now
                        cv2.putText(out, "JUMP!", (w//2 - 30, 80),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 100), 2, cv2.LINE_AA)
            self._prev_hip_y = hip_y

    # ── Particle Burst ────────────────────────────────────────────────────

    def _spawn_burst(self, frame):
        w, h = self.w, self.h
        for _ in range(60):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(5, 15)
            self._particles.append({
                'x': float(w // 2),
                'y': float(h // 3),
                'vx': math.cos(angle) * speed,
                'vy': math.sin(angle) * speed - 5,
                'life': 1.0,
                'color': (random.randint(150, 255),
                          random.randint(150, 255),
                          random.randint(150, 255)),
                'size': random.randint(3, 7)
            })

    def _update_particles(self, frame):
        alive = []
        for p in self._particles:
            p['x'] += p['vx']
            p['y'] += p['vy']
            p['vy'] += 0.4
            p['life'] -= 0.025
            if p['life'] > 0:
                col = tuple(int(c * p['life']) for c in p['color'])
                cv2.circle(frame, (int(p['x']), int(p['y'])), p['size'], col, -1)
                alive.append(p)
        self._particles = alive

    # ── Screenshot ────────────────────────────────────────────────────────

    def _save_screenshot(self, frame):
        fname = os.path.join(self._save_dir,
                             f"pose_{int(time.time())}.png")
        cv2.imwrite(fname, frame)

    # ── Sound ─────────────────────────────────────────────────────────────

    def _play_jump_sound(self):
        if not self._sound_ready:
            return
        try:
            sr = 44100
            t = np.linspace(0, 0.18, int(sr * 0.18), False)
            freq = np.linspace(300, 600, len(t))
            wave = (np.sin(2 * np.pi * freq * t) * 22000).astype(np.int16)
            stereo = np.column_stack([wave, wave])
            sound = self._pygame.sndarray.make_sound(stereo)
            sound.play()
        except Exception:
            pass

    # ── HUD ───────────────────────────────────────────────────────────────

    def _draw_hud(self, frame):
        h, w = frame.shape[:2]
        cv2.line(frame, (0, 48), (w, 48), (180, 180, 180), 1)
        cv2.putText(frame, "MODE: POSE", (12, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        _draw_corner_brackets(frame)
        _draw_bottom_bar(frame,
            "Arms Up=Burst | T-Pose=Screenshot | R-Point=Mouse | Jump=SFX")
