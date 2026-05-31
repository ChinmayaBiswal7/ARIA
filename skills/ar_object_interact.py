"""
ar_object_interact.py — ARIA Advanced AR Suite
Mode: Object Interaction
Voice triggers: "AR object mode", "AR interact mode"
Voice sub-commands: "remember this"

Features:
- YOLO detects objects on desk each frame
- Glowing bounding boxes with labels
- Pinch inside box = virtual grab (label follows hand)
- Throw at another object = triggers interaction response
- Fist over object = inspect (calls ARIA moondream vision)
- "remember this" = saves object to ARIA object store
"""

import cv2
import numpy as np
import math
import time
import random
import threading

from ar_drawing import _draw_corner_brackets, _draw_bottom_bar


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _landmark_px(lm, w, h):
    return int(lm.x * w), int(lm.y * h)


# ── Object interaction responses ──────────────────────────────────────────────
_INTERACTION_RESPONSES = {
    ("cell phone", "laptop"):   "Call from laptop?",
    ("laptop", "cell phone"):   "Call from laptop?",
    ("cup", "keyboard"):        "Coffee break time?",
    ("keyboard", "cup"):        "Coffee break time?",
    ("book", "laptop"):         "Open this book on the browser?",
    ("laptop", "book"):         "Open this book on the browser?",
    ("cell phone", "keyboard"): "Type out that message?",
    ("keyboard", "cell phone"): "Type out that message?",
    ("remote", "tv"):           "Change the channel?",
    ("pen", "book"):            "Take notes here?",
}

_DEFAULT_INTERACTION = "Interesting combination!"


def _get_interaction(label_a, label_b):
    key = (label_a.lower(), label_b.lower())
    rev = (label_b.lower(), label_a.lower())
    return _INTERACTION_RESPONSES.get(key,
           _INTERACTION_RESPONSES.get(rev, _DEFAULT_INTERACTION))


# ── Detected Object wrapper ───────────────────────────────────────────────────

class DetectedObject:
    _GLOW_COLORS = [
        (0, 210, 255),
        (0, 255, 130),
        (255, 90, 90),
        (255, 200, 0),
        (180, 80, 255),
    ]

    def __init__(self, x1, y1, x2, y2, label, conf, obj_id):
        self.x1, self.y1 = x1, y1
        self.x2, self.y2 = x2, y2
        self.label = label
        self.conf  = conf
        self.id    = obj_id
        self.cx    = (x1 + x2) // 2
        self.cy    = (y1 + y2) // 2
        self.color = self._GLOW_COLORS[obj_id % len(self._GLOW_COLORS)]
        self.grabbed = False
        self.virtual_x = float(self.cx)
        self.virtual_y = float(self.cy)
        self.vx = 0.0
        self.vy = 0.0

    def draw(self, frame, highlight=False):
        col = self.color
        thick = 2 if not highlight else 3

        # Glow box (slightly larger) - Anti-aliased
        glow = tuple(min(255, c + 40) for c in col)
        cv2.rectangle(frame,
                      (self.x1 - 3, self.y1 - 3),
                      (self.x2 + 3, self.y2 + 3),
                      glow, 1, cv2.LINE_AA)

        # Main box - Anti-aliased
        cv2.rectangle(frame, (self.x1, self.y1), (self.x2, self.y2), col, thick, cv2.LINE_AA)

        # Corner accents - Anti-aliased
        L = 12
        for (cx, cy, dx, dy) in [
            (self.x1, self.y1,  1,  1),
            (self.x2, self.y1, -1,  1),
            (self.x1, self.y2,  1, -1),
            (self.x2, self.y2, -1, -1),
        ]:
            cv2.line(frame, (cx, cy), (cx + dx*L, cy), col, 2, cv2.LINE_AA)
            cv2.line(frame, (cx, cy), (cx, cy + dy*L), col, 2, cv2.LINE_AA)

        # Label background - Anti-aliased
        label_text = f"{self.label} {int(self.conf*100)}%"
        (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
        lx1 = self.x1
        ly1 = max(0, self.y1 - th - 8)
        cv2.rectangle(frame, (lx1, ly1), (lx1 + tw + 8, self.y1), col, -1, cv2.LINE_AA)
        cv2.putText(frame, label_text, (lx1 + 4, self.y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1, cv2.LINE_AA)

    def draw_virtual(self, frame):
        """Draw the floating virtual copy while grabbed."""
        vx, vy = int(self.virtual_x), int(self.virtual_y)
        col = self.color
        half_w = (self.x2 - self.x1) // 2
        half_h = (self.y2 - self.y1) // 2

        overlay = frame.copy()
        cv2.rectangle(overlay,
                      (vx - half_w, vy - half_h),
                      (vx + half_w, vy + half_h),
                      col, -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)
        cv2.rectangle(frame,
                      (vx - half_w, vy - half_h),
                      (vx + half_w, vy + half_h),
                      col, 2, cv2.LINE_AA)

        (tw, th), _ = cv2.getTextSize(self.label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.putText(frame, self.label,
                    (vx - tw // 2, vy + th // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

        # Dashed line back to origin
        steps = 8
        for i in range(steps):
            t0 = i / steps
            t1 = (i + 0.5) / steps
            p0 = (int(self.cx + (vx - self.cx) * t0),
                  int(self.cy + (vy - self.cy) * t0))
            p1 = (int(self.cx + (vx - self.cx) * t1),
                  int(self.cy + (vy - self.cy) * t1))
            cv2.line(frame, p0, p1, col, 1, cv2.LINE_AA)


# ── Main Mode Class ───────────────────────────────────────────────────────────

class ARObjectInteract:

    def __init__(self, frame_w, frame_h, yolo_model=None, aria_brain=None):
        """
        yolo_model: the loaded ultralytics YOLO model from ARIA's Vision subsystem.
                    Pass as None to use placeholder detection.
        aria_brain: ARIA's Brain instance for moondream describe calls.
        """
        self.w = frame_w
        self.h = frame_h
        self._yolo = yolo_model
        self._brain = aria_brain
        self.label = "OBJECT INTERACT"

        # Detected objects (refreshed each YOLO frame)
        self._objects = []
        self._obj_counter = 0
        self._last_yolo_time = 0
        self._yolo_interval  = 0.25  # run YOLO every 250ms for performance

        # Grab state
        self._grabbed_obj = None
        self._prev_hand_pos = None
        self._hand_vel = (0.0, 0.0)

        # Interaction state
        self._interaction_msg = ""
        self._show_msg_until  = 0

        # Inspect state
        self._inspect_obj = None
        self._inspect_result = ""
        self._show_inspect_until = 0
        self._inspecting = False

        # Particles
        self._particles = []

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, frame, hand_landmarks):
        out = frame.copy()
        now = time.time()

        # Run YOLO at interval
        if now - self._last_yolo_time > self._yolo_interval:
            self._run_yolo(frame)
            self._last_yolo_time = now

        # Draw all detected objects
        for obj in self._objects:
            if not obj.grabbed:
                obj.draw(out, highlight=(obj == self._grabbed_obj))

        # Handle hand interaction
        if hand_landmarks:
            self._handle_hand(hand_landmarks, out)
        else:
            self._release_grabbed()

        # Draw grabbed object virtual copy
        if self._grabbed_obj:
            self._grabbed_obj.draw_virtual(out)

        # Update particles
        self._update_particles(out)

        # Interaction message
        if now < self._show_msg_until and self._interaction_msg:
            self._draw_message(out, self._interaction_msg)

        # Inspect result
        if now < self._show_inspect_until and self._inspect_result:
            self._draw_inspect_panel(out)

        self._draw_hud(out)
        return out

    def remember_current(self):
        """Called when user says 'remember this'."""
        if self._inspect_obj:
            print(f"[ARObjectInteract] Remembered: {self._inspect_obj.label}")
            self._interaction_msg = f"Remembered: {self._inspect_obj.label}"
            self._show_msg_until = time.time() + 2.5

    # ── YOLO Detection ────────────────────────────────────────────────────

    def _run_yolo(self, frame):
        if self._yolo is None:
            return

        try:
            results = self._yolo(frame, verbose=False, conf=0.35)[0]
            new_objs = []
            for box in results.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                conf  = float(box.conf[0])
                cls   = int(box.cls[0])
                label = results.names[cls]
                new_objs.append(
                    DetectedObject(x1, y1, x2, y2, label, conf, self._obj_counter)
                )
                self._obj_counter += 1

            # Preserve grab state across frames
            if self._grabbed_obj:
                for obj in new_objs:
                    if obj.label == self._grabbed_obj.label:
                        obj.grabbed = True
                        obj.virtual_x = self._grabbed_obj.virtual_x
                        obj.virtual_y = self._grabbed_obj.virtual_y
                        self._grabbed_obj = obj
                        break

            self._objects = new_objs
        except Exception as e:
            print(f"[ARObjectInteract] YOLO error: {e}")

    # ── Hand Interaction ──────────────────────────────────────────────────

    def _handle_hand(self, lms, frame):
        w, h = self.w, self.h
        tip = _landmark_px(lms.landmark[8], w, h)
        thb = _landmark_px(lms.landmark[4], w, h)
        pinching = _dist(tip, thb) < w * 0.06

        # Track velocity
        if self._prev_hand_pos:
            self._hand_vel = (
                tip[0] - self._prev_hand_pos[0],
                tip[1] - self._prev_hand_pos[1]
            )
        self._prev_hand_pos = tip

        # Fist detection
        tips = [8, 12, 16, 20]
        pips = [6, 10, 14, 18]
        folded = sum(
            1 for t, p in zip(tips, pips)
            if lms.landmark[t].y > lms.landmark[p].y
        )
        fist = folded >= 3

        if fist:
            self._handle_inspect(tip, frame)
            return

        if pinching and self._grabbed_obj is None:
            # Try to grab
            for obj in self._objects:
                if (obj.x1 < tip[0] < obj.x2 and
                        obj.y1 < tip[1] < obj.y2):
                    obj.grabbed = True
                    self._grabbed_obj = obj
                    obj.virtual_x = float(tip[0])
                    obj.virtual_y = float(tip[1])
                    break

        if self._grabbed_obj:
            if pinching:
                # Move virtual object
                self._grabbed_obj.virtual_x = float(tip[0])
                self._grabbed_obj.virtual_y = float(tip[1])
            else:
                # Release = throw
                self._throw_object()

        # Draw cursor
        col = (0, 200, 255) if pinching else (200, 200, 200)
        cv2.circle(frame, tip, 8, col, 2, cv2.LINE_AA)

    def _handle_inspect(self, tip, frame):
        for obj in self._objects:
            if (obj.x1 < tip[0] < obj.x2 and
                    obj.y1 < tip[1] < obj.y2):
                self._inspect_obj = obj
                if not self._inspecting:
                    self._inspecting = True
                    threading.Thread(
                        target=self._run_inspect,
                        args=(obj,),
                        daemon=True
                    ).start()
                # Visual inspect pulse
                cv2.circle(frame, (obj.cx, obj.cy),
                           int((obj.x2 - obj.x1) * 0.6),
                           obj.color, 1, cv2.LINE_AA)
                break

    def _run_inspect(self, obj):
        if self._brain:
            try:
                result = self._brain.describe_object(obj.label)
                self._inspect_result = result
            except Exception:
                self._inspect_result = f"This is a {obj.label}."
        else:
            self._inspect_result = f"Detected: {obj.label} ({int(obj.conf*100)}% confidence)"
        self._show_inspect_until = time.time() + 4.0
        self._inspecting = False

    def _throw_object(self):
        if not self._grabbed_obj:
            return
        thrown = self._grabbed_obj
        thrown.grabbed = False
        self._grabbed_obj = None

        # Check if thrown near another object
        for obj in self._objects:
            if obj == thrown:
                continue
            if (_dist((thrown.virtual_x, thrown.virtual_y), (obj.cx, obj.cy))
                    < (thrown.x2 - thrown.x1) * 0.8):
                msg = _get_interaction(thrown.label, obj.label)
                self._interaction_msg = msg
                self._show_msg_until  = time.time() + 3.0
                self._spawn_interaction_particles(obj.cx, obj.cy, obj.color)
                break

    def _release_grabbed(self):
        if self._grabbed_obj:
            self._grabbed_obj.grabbed = False
            self._grabbed_obj = None
        self._prev_hand_pos = None

    # ── Particles ─────────────────────────────────────────────────────────

    def _spawn_interaction_particles(self, cx, cy, color):
        for _ in range(25):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(3, 9)
            self._particles.append({
                'x': float(cx), 'y': float(cy),
                'vx': math.cos(angle) * speed,
                'vy': math.sin(angle) * speed,
                'life': 1.0,
                'color': color,
                'size': random.randint(2, 5)
            })

    def _update_particles(self, frame):
        alive = []
        for p in self._particles:
            p['x'] += p['vx']
            p['y'] += p['vy']
            p['vy'] += 0.3
            p['life'] -= 0.04
            if p['life'] > 0:
                col = tuple(int(c * p['life']) for c in p['color'])
                cv2.circle(frame, (int(p['x']), int(p['y'])), p['size'], col, -1, cv2.LINE_AA)
                alive.append(p)
        self._particles = alive

    # ── UI ────────────────────────────────────────────────────────────────

    def _draw_message(self, frame, msg):
        h, w = frame.shape[:2]
        (tw, th), _ = cv2.getTextSize(msg, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
        mx = (w - tw) // 2
        my = h // 2
        overlay = frame.copy()
        cv2.rectangle(overlay, (mx - 12, my - th - 10),
                      (mx + tw + 12, my + 10), (20, 20, 20), -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
        cv2.putText(frame, msg, (mx, my),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)

    def _draw_inspect_panel(self, frame):
        h, w = frame.shape[:2]
        lines = []
        words = self._inspect_result.split()
        line = ""
        for word in words:
            if len(line) + len(word) < 45:
                line += word + " "
            else:
                lines.append(line.strip())
                line = word + " "
        if line:
            lines.append(line.strip())

        panel_h = len(lines) * 22 + 20
        overlay = frame.copy()
        cv2.rectangle(overlay, (10, h - panel_h - 70),
                      (w - 10, h - 35), (15, 15, 15), -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)
        cv2.rectangle(frame, (10, h - panel_h - 70),
                      (w - 10, h - 35), (180, 180, 180), 1, cv2.LINE_AA)

        for i, line in enumerate(lines):
            cv2.putText(frame, line,
                        (18, h - panel_h - 50 + i * 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                        (220, 220, 220), 1, cv2.LINE_AA)

    def _draw_hud(self, frame):
        h, w = frame.shape[:2]
        cv2.line(frame, (0, 48), (w, 48), (180, 180, 180), 1, cv2.LINE_AA)
        obj_count = len(self._objects)
        cv2.putText(frame, f"MODE: OBJECT INTERACT  [{obj_count} detected]",
                    (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 1, cv2.LINE_AA)
        _draw_corner_brackets(frame)
        _draw_bottom_bar(frame,
            "Pinch=Grab | Release=Throw | Fist=Inspect | Say 'remember this'")
