"""
ar_drawing.py — ARIA Advanced AR Suite
Mode: AR Drawing Canvas
Voice triggers: "AR drawing mode", "AR canvas mode"

Features:
- Persistent drawing canvas blended over webcam feed
- Pinch (index+thumb) = pen down
- Fist = eraser
- Peace sign = color picker wheel
- 3 fingers = brush size slider
- Shake hand left-right = undo last stroke
"""

import cv2
import numpy as np
import math
import time


# ── Palette ───────────────────────────────────────────────────────────────────
COLORS = [
    (255, 255, 255),   # White
    (0, 200, 255),     # Cyan
    (0, 255, 120),     # Green
    (255, 80, 80),     # Red
    (255, 180, 0),     # Yellow
    (200, 80, 255),    # Purple
    (255, 140, 0),     # Orange
    (80, 80, 255),     # Blue
]
ERASER_COLOR = (0, 0, 0)


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _landmark_px(lm, w, h):
    return int(lm.x * w), int(lm.y * h)


class ARDrawing:
    """Persistent drawing canvas AR mode."""

    def __init__(self, frame_w, frame_h):
        self.w = frame_w
        self.h = frame_h

        # Persistent canvas (BGRA so we can blend with alpha)
        self.canvas = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)

        # Stroke history: list of canvas snapshots for undo
        self._history = []
        self._max_history = 20

        # Drawing state
        self.color = COLORS[0]          # current draw color
        self.brush_size = 4
        self.eraser_size = 30
        self._prev_point = None
        self._pen_down = False

        # Color picker state
        self._show_picker = False
        self._picker_center = (frame_w // 2, frame_h // 2)

        # Brush slider state
        self._show_brush_slider = False

        # Undo shake detection
        self._shake_positions = []
        self._last_undo_time = 0

        # Mode label
        self.label = "DRAWING"

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, frame, hand_landmarks):
        """
        Call every frame.
        hand_landmarks: mediapipe hand landmark object or None.
        Returns annotated frame.
        """
        out = frame.copy()

        if hand_landmarks:
            gesture = self._classify_gesture(hand_landmarks)
            self._handle_gesture(gesture, hand_landmarks, out)
            self._detect_shake(hand_landmarks)

        # Blend canvas onto frame
        mask = cv2.cvtColor(self.canvas, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(mask, 1, 255, cv2.THRESH_BINARY)
        canvas_region = cv2.bitwise_and(self.canvas, self.canvas, mask=mask)
        out = cv2.addWeighted(out, 1.0, canvas_region, 0.85, 0)

        # Draw HUD overlays
        self._draw_hud(out)
        if self._show_picker:
            self._draw_color_picker(out, hand_landmarks)
        if self._show_brush_slider:
            self._draw_brush_slider(out, hand_landmarks)

        return out

    def clear(self):
        self._push_history()
        self.canvas[:] = 0

    def undo(self):
        if self._history:
            self.canvas = self._history.pop()

    # ── Gesture Classification ─────────────────────────────────────────────

    def _classify_gesture(self, lms):
        """Returns: 'pinch', 'fist', 'peace', 'three', 'open', 'point'"""
        tips = [4, 8, 12, 16, 20]
        pips = [3, 6, 10, 14, 18]

        # Finger extended = tip above pip (in image coords, lower y = higher)
        extended = []
        for tip, pip in zip(tips[1:], pips[1:]):  # skip thumb
            t = lms.landmark[tip]
            p = lms.landmark[pip]
            extended.append(t.y < p.y)

        # Thumb extended (x-axis based)
        thumb_tip = lms.landmark[4]
        thumb_ip  = lms.landmark[3]
        thumb_ext = abs(thumb_tip.x - lms.landmark[0].x) > abs(thumb_ip.x - lms.landmark[0].x)

        n_ext = sum(extended)

        # Pinch = index up, thumb close to index tip
        idx_tip = lms.landmark[8]
        thb_tip = lms.landmark[4]
        pinch_dist = _dist(
            (idx_tip.x, idx_tip.y),
            (thb_tip.x, thb_tip.y)
        )
        if pinch_dist < 0.06:
            return 'pinch'

        if n_ext == 0:
            return 'fist'
        if n_ext == 1 and extended[0]:
            return 'point'
        if n_ext == 2 and extended[0] and extended[1]:
            return 'peace'
        if n_ext == 3:
            return 'three'
        if n_ext >= 4:
            return 'open'

        return 'other'

    # ── Gesture Handling ──────────────────────────────────────────────────

    def _handle_gesture(self, gesture, lms, frame):
        w, h = self.w, self.h
        idx_tip = _landmark_px(lms.landmark[8], w, h)

        if gesture == 'fist':
            # Eraser
            self._push_history()
            cv2.circle(self.canvas, idx_tip, self.eraser_size, (0, 0, 0), -1)
            cv2.circle(frame, idx_tip, self.eraser_size, (180, 180, 180), 2)
            self._pen_down = False
            self._prev_point = None
            self._show_picker = False
            self._show_brush_slider = False

        elif gesture == 'pinch':
            # Pen down — draw
            self._show_picker = False
            self._show_brush_slider = False
            tip = _landmark_px(lms.landmark[8], w, h)
            if not self._pen_down:
                self._push_history()
                self._pen_down = True
                self._prev_point = tip
            if self._prev_point:
                cv2.line(self.canvas, self._prev_point, tip,
                         self.color, self.brush_size, cv2.LINE_AA)
                # Glow effect
                cv2.line(self.canvas, self._prev_point, tip,
                         tuple(min(255, c + 80) for c in self.color),
                         max(1, self.brush_size - 2), cv2.LINE_AA)
            self._prev_point = tip

        elif gesture == 'peace':
            self._pen_down = False
            self._prev_point = None
            self._show_picker = True
            self._show_brush_slider = False
            # Handle color selection
            self._handle_color_pick(lms, frame)

        elif gesture == 'three':
            self._pen_down = False
            self._prev_point = None
            self._show_picker = False
            self._show_brush_slider = True
            self._handle_brush_size(lms, frame)

        else:
            self._pen_down = False
            self._prev_point = None

    def _handle_color_pick(self, lms, frame):
        w, h = self.w, self.h
        cx, cy = w // 2, h // 2
        tip = _landmark_px(lms.landmark[8], w, h)
        for i, col in enumerate(COLORS):
            angle = (2 * math.pi * i) / len(COLORS) - math.pi / 2
            r = 80
            px = int(cx + r * math.cos(angle))
            py = int(cy + r * math.sin(angle))
            if _dist(tip, (px, py)) < 28:
                self.color = col

    def _handle_brush_size(self, lms, frame):
        w, h = self.w, self.h
        tip = _landmark_px(lms.landmark[8], w, h)
        # Map y position to brush size 1..30
        rel_y = 1.0 - (tip[1] / h)
        self.brush_size = max(1, min(30, int(rel_y * 30)))

    # ── Shake / Undo ──────────────────────────────────────────────────────

    def _detect_shake(self, lms):
        w, h = self.w, self.h
        tip = _landmark_px(lms.landmark[8], w, h)
        now = time.time()
        self._shake_positions.append((tip[0], now))
        self._shake_positions = [p for p in self._shake_positions if now - p[1] < 0.5]

        if len(self._shake_positions) >= 6:
            xs = [p[0] for p in self._shake_positions]
            spread = max(xs) - min(xs)
            if spread > w * 0.15 and now - self._last_undo_time > 1.0:
                self.undo()
                self._last_undo_time = now
                self._shake_positions.clear()

    # ── History ───────────────────────────────────────────────────────────

    def _push_history(self):
        self._history.append(self.canvas.copy())
        if len(self._history) > self._max_history:
            self._history.pop(0)

    # ── HUD Rendering ─────────────────────────────────────────────────────

    def _draw_hud(self, frame):
        h, w = frame.shape[:2]

        # Top bar
        cv2.line(frame, (0, 48), (w, 48), (180, 180, 180), 1)
        cv2.putText(frame, "MODE: DRAWING", (12, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

        # Color swatch
        swatch_x = w - 48
        cv2.rectangle(frame, (swatch_x, 10), (swatch_x + 30, 38),
                      self.color, -1)
        cv2.rectangle(frame, (swatch_x, 10), (swatch_x + 30, 38),
                      (200, 200, 200), 1)

        # Brush size indicator
        cv2.circle(frame, (swatch_x - 24, 24), self.brush_size, (255, 255, 255), 1)

        # Corner brackets
        _draw_corner_brackets(frame)

        # Bottom hint
        hints = "Pinch=Draw | Fist=Erase | Peace=Color | 3Fingers=Size | Shake=Undo"
        _draw_bottom_bar(frame, hints)

    def _draw_color_picker(self, frame, hand_landmarks):
        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2

        # Semi-transparent backdrop
        overlay = frame.copy()
        cv2.circle(overlay, (cx, cy), 120, (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)

        cv2.putText(frame, "COLOR", (cx - 25, cy + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)

        for i, col in enumerate(COLORS):
            angle = (2 * math.pi * i) / len(COLORS) - math.pi / 2
            r = 80
            px = int(cx + r * math.cos(angle))
            py = int(cy + r * math.sin(angle))
            selected = col == self.color
            cv2.circle(frame, (px, py), 20 if selected else 14, col, -1)
            if selected:
                cv2.circle(frame, (px, py), 22, (255, 255, 255), 2)

        # Fingertip cursor
        if hand_landmarks:
            tip = _landmark_px(hand_landmarks.landmark[8], w, h)
            cv2.circle(frame, tip, 6, (255, 255, 255), 2)

    def _draw_brush_slider(self, frame, hand_landmarks):
        h, w = frame.shape[:2]
        cx = w // 2

        overlay = frame.copy()
        cv2.rectangle(overlay, (cx - 12, 60), (cx + 12, h - 60), (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)

        cv2.rectangle(frame, (cx - 12, 60), (cx + 12, h - 60), (180, 180, 180), 1)

        # Fill level
        fill_y = int(h - 60 - (self.brush_size / 30.0) * (h - 120))
        cv2.rectangle(frame, (cx - 10, fill_y), (cx + 10, h - 62), (255, 255, 255), -1)

        cv2.putText(frame, f"SIZE:{self.brush_size}", (cx - 25, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)


# ── Shared HUD helpers (used by all modes) ────────────────────────────────────

def _draw_corner_brackets(frame, color=(255, 255, 255), length=20, thickness=1):
    h, w = frame.shape[:2]
    pts = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    dirs = [(1, 1), (-1, 1), (1, -1), (-1, -1)]
    for (x, y), (dx, dy) in zip(pts, dirs):
        cv2.line(frame, (x, y), (x + dx * length, y), color, thickness)
        cv2.line(frame, (x, y), (x, y + dy * length), color, thickness)


def _draw_bottom_bar(frame, text, color=(180, 180, 180)):
    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, h - 28), (w, h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
    cv2.putText(frame, text, (8, h - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)
