"""
ar_whiteboard.py — ARIA Advanced AR Suite
Mode: AR Whiteboard
Voice triggers: "AR whiteboard mode", "AR write mode"
Voice sub-commands: "clear board", "undo"

Features:
- Index finger draws characters on overlay canvas
- Pinch = pen lift (end of one character stroke)
- 1.5s idle after stroke = trigger recognition
- EMNIST model recognizes handwritten letters + digits
- Recognized char displayed on screen with confidence %
- Recognized char typed into active app via pyautogui
- "clear board" / "undo" voice commands
"""

import cv2
import numpy as np
import math
import time
import os
import threading

import pyautogui

from ar_drawing import _draw_corner_brackets, _draw_bottom_bar

# ── Optional TensorFlow/EMNIST ────────────────────────────────────────────────
_tf_available = False
_model = None

def _load_model():
    global _tf_available, _model
    model_path = os.path.join(os.path.dirname(__file__), "models", "emnist_model.h5")
    try:
        import tensorflow as tf
        if os.path.exists(model_path):
            _model = tf.keras.models.load_model(model_path)
            _tf_available = True
            print("[ARWhiteboard] EMNIST model loaded.")
        else:
            print(f"[ARWhiteboard] Model not found at {model_path}. "
                  "Download from: https://github.com/hosford42/EMNIST or train your own.")
    except Exception as e:
        print(f"[ARWhiteboard] TF not available or model load failed: {e}")

# Load model in background thread on import
threading.Thread(target=_load_model, daemon=True).start()

# EMNIST balanced label map (47 classes: 0-9, A-Z, a-z subset)
_EMNIST_LABELS = list("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabdefghnqrt")


def _landmark_px(lm, w, h):
    return int(lm.x * w), int(lm.y * h)


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


_fallback_templates = {}

def _get_fallback_templates():
    global _fallback_templates
    if _fallback_templates:
        return _fallback_templates
    for char in _EMNIST_LABELS:
        tpl = np.zeros((28, 28), dtype=np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.65
        thickness = 2
        (w, h), baseline = cv2.getTextSize(char, font, font_scale, thickness)
        x = max(0, (28 - w) // 2)
        y = max(0, (28 + h) // 2 - 1)
        cv2.putText(tpl, char, (x, y), font, font_scale, 255, thickness, cv2.LINE_AA)
        _fallback_templates[char] = tpl
    return _fallback_templates

def _run_fallback_recognition(crop):
    try:
        if crop is None or crop.size == 0:
            return "?", 0.0
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 30, 255, cv2.THRESH_BINARY)
        pts = cv2.findNonZero(thresh)
        if pts is not None:
            x, y, w, h = cv2.boundingRect(pts)
            char_crop = thresh[y:y+h, x:x+w]
            size = max(w, h)
            pad_x = (size - w) // 2
            pad_y = (size - h) // 2
            padded = cv2.copyMakeBorder(char_crop, pad_y, pad_y, pad_x, pad_x, cv2.BORDER_CONSTANT, value=0)
            resized = cv2.resize(padded, (28, 28), interpolation=cv2.INTER_AREA)
        else:
            resized = cv2.resize(thresh, (28, 28), interpolation=cv2.INTER_AREA)
        templates = _get_fallback_templates()
        best_char = "?"
        best_score = -1.0
        for char, tpl in templates.items():
            res = cv2.matchTemplate(resized, tpl, cv2.TM_CCORR_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            if max_val > best_score:
                best_score = max_val
                best_char = char
        conf = float(best_score) if best_score > 0 else 0.0
        if conf < 0.25:
            return "?", 0.0
        return best_char, conf
    except Exception as e:
        print(f"[ARWhiteboard] Fallback template matching failed: {e}")
        return "?", 0.0


class ARWhiteboard:

    def __init__(self, frame_w, frame_h):
        self.w = frame_w
        self.h = frame_h
        self.label = "WHITEBOARD"

        # Drawing canvas (persistent per char)
        self._stroke_canvas = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)
        self._full_canvas    = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)

        # Stroke tracking
        self._pen_down = False
        self._prev_pt  = None
        self._last_draw_time = time.time()
        self._recognizing = False

        # Current stroke bounding box
        self._stroke_pts = []

        # Recognized text buffer
        self._text_buffer = []
        self._last_result  = ""
        self._last_conf    = 0.0
        self._show_result_until = 0

        # Cursor position for text output
        self._cursor_x = 20
        self._cursor_y = self.h - 60

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, frame, hand_landmarks):
        out = frame.copy()

        if hand_landmarks:
            self._handle_hand(hand_landmarks, out)
            # Auto-recognize after 1.5s idle
            if (self._stroke_pts and
                    not self._recognizing and
                    time.time() - self._last_draw_time > 1.5):
                self._trigger_recognition()

        # Blend full canvas onto frame
        mask = cv2.cvtColor(self._full_canvas, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(mask, 1, 255, cv2.THRESH_BINARY)
        region = cv2.bitwise_and(self._full_canvas, self._full_canvas, mask=mask)
        out = cv2.addWeighted(out, 1.0, region, 0.80, 0)

        # Blend current stroke canvas
        mask2 = cv2.cvtColor(self._stroke_canvas, cv2.COLOR_BGR2GRAY)
        _, mask2 = cv2.threshold(mask2, 1, 255, cv2.THRESH_BINARY)
        region2 = cv2.bitwise_and(self._stroke_canvas, self._stroke_canvas, mask=mask2)
        out = cv2.addWeighted(out, 1.0, region2, 0.90, 0)

        # Result flash
        if time.time() < self._show_result_until:
            self._draw_result_panel(out)

        self._draw_text_buffer(out)
        self._draw_hud(out)
        return out

    def clear_board(self):
        self._stroke_canvas[:] = 0
        self._full_canvas[:] = 0
        self._stroke_pts.clear()
        self._text_buffer.clear()

    def undo(self):
        if self._text_buffer:
            self._text_buffer.pop()

    # ── Hand Handling ─────────────────────────────────────────────────────

    def _handle_hand(self, lms, frame):
        w, h = self.w, self.h
        tip = _landmark_px(lms.landmark[8], w, h)
        thb = _landmark_px(lms.landmark[4], w, h)
        pinching = _dist(tip, thb) < w * 0.06

        # Draw cursor circle
        col = (200, 200, 200) if pinching else (255, 255, 255)
        cv2.circle(frame, tip, 6, col, 2, cv2.LINE_AA)

        if pinching:
            # Pen lift — finalize stroke
            if self._pen_down:
                self._pen_down = False
                self._prev_pt = None
        else:
            # Pen down — draw
            if not self._pen_down:
                self._pen_down = True

            if self._prev_pt:
                cv2.line(self._stroke_canvas, self._prev_pt, tip,
                         (255, 255, 255), 3, cv2.LINE_AA)
                cv2.line(self._stroke_canvas, self._prev_pt, tip,
                         (200, 200, 200), 1, cv2.LINE_AA)
            self._prev_pt = tip
            self._stroke_pts.append(tip)
            self._last_draw_time = time.time()

    # ── Recognition ───────────────────────────────────────────────────────

    def _trigger_recognition(self):
        if not self._stroke_pts:
            return
        self._recognizing = True

        # Crop bounding box of stroke with padding
        xs = [p[0] for p in self._stroke_pts]
        ys = [p[1] for p in self._stroke_pts]
        pad = 20
        x1 = max(0, min(xs) - pad)
        y1 = max(0, min(ys) - pad)
        x2 = min(self.w, max(xs) + pad)
        y2 = min(self.h, max(ys) + pad)

        crop = self._stroke_canvas[y1:y2, x1:x2]

        # Clear stroke canvas, merge into full canvas
        self._full_canvas = cv2.addWeighted(
            self._full_canvas, 1.0, self._stroke_canvas, 1.0, 0)
        self._stroke_canvas[:] = 0
        self._stroke_pts.clear()

        # Run recognition in background
        threading.Thread(
            target=self._recognize_crop,
            args=(crop,),
            daemon=True
        ).start()

    def _recognize_crop(self, crop):
        char, conf = self._run_emnist(crop)
        self._last_result = char
        self._last_conf   = conf
        self._show_result_until = time.time() + 2.5
        self._text_buffer.append(char)

        # Type into active app
        try:
            pyautogui.typewrite(char, interval=0.05)
        except Exception:
            pass

        self._recognizing = False

    def _run_emnist(self, crop):
        """Run EMNIST inference or fall back to template matching."""
        if _tf_available and _model is not None:
            try:
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                resized = cv2.resize(gray, (28, 28))
                # EMNIST is transposed
                resized = np.transpose(resized)
                inp = resized.astype(np.float32) / 255.0
                inp = inp.reshape(1, 28, 28, 1)
                preds = _model.predict(inp, verbose=0)[0]
                idx  = int(np.argmax(preds))
                conf = float(preds[idx])
                char = _EMNIST_LABELS[idx] if idx < len(_EMNIST_LABELS) else "?"
                return char, conf
            except Exception as e:
                print(f"[ARWhiteboard] Inference error: {e}")

        # Fallback: run template matching fallback
        return _run_fallback_recognition(crop)

    # ── Drawing ───────────────────────────────────────────────────────────

    def _draw_result_panel(self, frame):
        w, h = self.w, self.h
        px, py = w // 2, h // 2 - 30
        overlay = frame.copy()
        cv2.rectangle(overlay, (px - 60, py - 50), (px + 60, py + 30),
                      (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
        cv2.rectangle(frame, (px - 60, py - 50), (px + 60, py + 30),
                      (200, 200, 200), 1)

        # Char
        cv2.putText(frame, self._last_result, (px - 18, py + 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 2, cv2.LINE_AA)
        # Confidence
        cv2.putText(frame,
                    f"{int(self._last_conf * 100)}%",
                    (px - 22, py + 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1, cv2.LINE_AA)

    def _draw_text_buffer(self, frame):
        if not self._text_buffer:
            return
        text = "".join(self._text_buffer)
        h, w = frame.shape[:2]
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, h - 56), (w, h - 30), (15, 15, 15), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
        cv2.putText(frame, f"TEXT: {text}", (8, h - 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    def _draw_hud(self, frame):
        h, w = frame.shape[:2]
        cv2.line(frame, (0, 48), (w, 48), (180, 180, 180), 1)
        cv2.putText(frame, "MODE: WHITEBOARD", (12, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

        # Recognizing indicator
        if self._recognizing:
            cv2.putText(frame, "...", (w - 40, 32),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)

        _draw_corner_brackets(frame)
        _draw_bottom_bar(frame,
            "Draw=Write | Pinch=Lift | 1.5s idle=Recognize | Say 'clear board' or 'undo'")
