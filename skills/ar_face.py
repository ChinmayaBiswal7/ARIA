"""
ar_face.py — ARIA Advanced AR Suite
Mode: Face AR Overlays
Voice triggers: "AR face mode", "AR mask mode"
Sub-mode switch: "next mask" / "previous mask"

Masks available:
  0 - Cyber Visor    : glowing line visor across eyes
  1 - Neon Skull     : bone structure overlay
  2 - Data Stream    : matrix chars raining from forehead
  3 - Crown          : geometric crown anchored to forehead
  4 - Sunglasses     : flat vector shades on eyes
"""

import cv2
import numpy as np
import math
import random
import time

import mediapipe as mp

from ar_drawing import _draw_corner_brackets, _draw_bottom_bar

# ── FaceMesh setup ────────────────────────────────────────────────────────────
_mp_face = mp.solutions.face_mesh
_face_mesh = _mp_face.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

MASK_NAMES = ["CYBER VISOR", "NEON SKULL", "DATA STREAM", "CROWN", "SUNGLASSES"]

# Key FaceMesh landmark indices
_LEFT_EYE_OUTER  = 33
_RIGHT_EYE_OUTER = 263
_LEFT_EYE_INNER  = 133
_RIGHT_EYE_INNER = 362
_NOSE_TIP        = 1
_FOREHEAD        = 10
_CHIN            = 152
_LEFT_CHEEK      = 234
_RIGHT_CHEEK     = 454
_LEFT_EYE_TOP    = 159
_RIGHT_EYE_TOP   = 386
_LEFT_EYE_BOT    = 145
_RIGHT_EYE_BOT   = 374


def _lm(landmarks, idx, w, h):
    l = landmarks[idx]
    return int(l.x * w), int(l.y * h)


# ── Matrix char pool ──────────────────────────────────────────────────────────
_MATRIX_CHARS = list("01アイウエオカキクケコサシスセソタチツテトナニヌネノ@#$%&")


class ARFace:

    def __init__(self, frame_w, frame_h):
        self.w = frame_w
        self.h = frame_h
        self.mask_idx = 0
        self.label = "FACE AR"

        # Data stream state
        self._streams = []
        self._last_stream_spawn = 0

        # Skull flicker
        self._skull_alpha = 1.0
        self._skull_dir = -0.02

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, frame):
        """Run FaceMesh internally and apply current mask. Returns annotated frame."""
        out = frame.copy()
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = _face_mesh.process(rgb)

        if results.multi_face_landmarks:
            lms = results.multi_face_landmarks[0].landmark
            self._apply_mask(out, lms)
        else:
            # No face — show scanning animation
            self._draw_scan_animation(out)

        self._draw_hud(out)
        return out

    def next_mask(self):
        self.mask_idx = (self.mask_idx + 1) % len(MASK_NAMES)
        self._streams.clear()

    def prev_mask(self):
        self.mask_idx = (self.mask_idx - 1) % len(MASK_NAMES)
        self._streams.clear()

    # ── Mask Dispatcher ───────────────────────────────────────────────────

    def _apply_mask(self, frame, lms):
        {
            0: self._mask_cyber_visor,
            1: self._mask_neon_skull,
            2: self._mask_data_stream,
            3: self._mask_crown,
            4: self._mask_sunglasses,
        }[self.mask_idx](frame, lms)

    # ── Mask 0: Cyber Visor ───────────────────────────────────────────────

    def _mask_cyber_visor(self, frame, lms):
        w, h = self.w, self.h
        le_o = _lm(lms, _LEFT_EYE_OUTER,  w, h)
        re_o = _lm(lms, _RIGHT_EYE_OUTER, w, h)
        le_i = _lm(lms, _LEFT_EYE_INNER,  w, h)
        re_i = _lm(lms, _RIGHT_EYE_INNER, w, h)

        # Extend visor beyond eye corners
        margin = int((re_o[0] - le_o[0]) * 0.25)
        vx1 = le_o[0] - margin
        vx2 = re_o[0] + margin
        vy  = (le_o[1] + re_o[1]) // 2
        eye_h = int(abs(
            _lm(lms, _LEFT_EYE_TOP, w, h)[1] - _lm(lms, _LEFT_EYE_BOT, w, h)[1]
        ) * 1.6)

        # Visor body (semi-transparent)
        overlay = frame.copy()
        cv2.rectangle(overlay, (vx1, vy - eye_h), (vx2, vy + eye_h), (0, 180, 255), -1)
        cv2.addWeighted(overlay, 0.28, frame, 0.72, 0, frame)

        # Visor edges
        cv2.rectangle(frame, (vx1, vy - eye_h), (vx2, vy + eye_h), (0, 220, 255), 1)

        # Horizontal scan line
        scan_y = vy - eye_h + int((time.time() * 60) % (eye_h * 2))
        cv2.line(frame, (vx1, scan_y), (vx2, scan_y), (0, 255, 255), 1)

        # Bridge connecting lenses
        cv2.line(frame, le_i, re_i, (0, 220, 255), 2)

        # Side stripes to ears
        ear_l = _lm(lms, _LEFT_CHEEK,  w, h)
        ear_r = _lm(lms, _RIGHT_CHEEK, w, h)
        cv2.line(frame, (vx1, vy), ear_l, (0, 180, 255), 1)
        cv2.line(frame, (vx2, vy), ear_r, (0, 180, 255), 1)

        # Glow dots at corners
        for pt in [(vx1, vy - eye_h), (vx2, vy - eye_h),
                   (vx1, vy + eye_h), (vx2, vy + eye_h)]:
            cv2.circle(frame, pt, 4, (0, 255, 255), -1)

    # ── Mask 1: Neon Skull ────────────────────────────────────────────────

    def _mask_neon_skull(self, frame, lms):
        w, h = self.w, self.h

        # Animate alpha flicker
        self._skull_alpha += self._skull_dir
        if self._skull_alpha < 0.6 or self._skull_alpha > 1.0:
            self._skull_dir *= -1

        col = tuple(int(c * self._skull_alpha) for c in (80, 255, 80))

        # Eye sockets (ellipses around eyes)
        le_c = _lm(lms, 468, w, h) if len(lms) > 468 else _lm(lms, _LEFT_EYE_OUTER, w, h)
        re_c = _lm(lms, 473, w, h) if len(lms) > 473 else _lm(lms, _RIGHT_EYE_OUTER, w, h)
        eye_rx = abs(_lm(lms, _LEFT_EYE_INNER, w, h)[0] - _lm(lms, _LEFT_EYE_OUTER, w, h)[0])
        eye_ry = max(6, eye_rx // 2)

        cv2.ellipse(frame, le_c, (eye_rx, eye_ry), 0, 0, 360, col, 1)
        cv2.ellipse(frame, re_c, (eye_rx, eye_ry), 0, 0, 360, col, 1)

        # Nose outline
        nose = _lm(lms, _NOSE_TIP, w, h)
        nose_w = eye_rx // 2
        cv2.line(frame, (nose[0] - nose_w, nose[1] - nose_w),
                 (nose[0], nose[1] + nose_w), col, 1)
        cv2.line(frame, (nose[0] + nose_w, nose[1] - nose_w),
                 (nose[0], nose[1] + nose_w), col, 1)

        # Teeth / jaw line using lower face landmarks
        jaw_pts = [lms[i] for i in [58, 172, 136, 150, 149, 176, 148, 152,
                                     377, 400, 378, 379, 365, 288]]
        jaw_px = [(int(l.x * w), int(l.y * h)) for l in jaw_pts]
        for i in range(len(jaw_px) - 1):
            cv2.line(frame, jaw_px[i], jaw_px[i+1], col, 1)

        # Forehead curve
        forehead_pts = [lms[i] for i in [10, 338, 297, 332, 284, 251,
                                          389, 356, 454, 323, 361, 288]]
        fh_px = [(int(l.x * w), int(l.y * h)) for l in forehead_pts]
        for i in range(len(fh_px) - 1):
            cv2.line(frame, fh_px[i], fh_px[i+1], col, 1)

        # Cheekbones
        lc = _lm(lms, _LEFT_CHEEK,  w, h)
        rc = _lm(lms, _RIGHT_CHEEK, w, h)
        chin = _lm(lms, _CHIN, w, h)
        cv2.line(frame, le_c, lc, col, 1)
        cv2.line(frame, re_c, rc, col, 1)
        cv2.line(frame, lc, chin, col, 1)
        cv2.line(frame, rc, chin, col, 1)

    # ── Mask 2: Data Stream ───────────────────────────────────────────────

    def _mask_data_stream(self, frame, lms):
        w, h = self.w, self.h
        now = time.time()

        # Spawn new streams from forehead every 0.1s
        forehead = _lm(lms, _FOREHEAD, w, h)
        if now - self._last_stream_spawn > 0.08:
            jitter = random.randint(-40, 40)
            self._streams.append({
                'x': forehead[0] + jitter,
                'y': forehead[1],
                'chars': [random.choice(_MATRIX_CHARS) for _ in range(random.randint(4, 10))],
                'speed': random.uniform(3, 8),
                'life': 1.0,
                'color_idx': random.random()
            })
            self._last_stream_spawn = now

        # Update and draw streams
        alive = []
        for s in self._streams:
            s['y'] += s['speed']
            s['life'] -= 0.012
            if s['life'] > 0 and s['y'] < h + 20:
                for i, ch in enumerate(s['chars']):
                    cy = int(s['y']) - i * 14
                    if 0 < cy < h:
                        alpha = s['life'] * (1 - i / len(s['chars']))
                        green = int(255 * alpha)
                        bright = int(200 * alpha)
                        col = (0, bright, 0) if i > 0 else (0, 255, 0)
                        cv2.putText(frame, ch, (s['x'], cy),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.35,
                                    col, 1, cv2.LINE_AA)
                alive.append(s)
        self._streams = alive[-60:]  # cap

        # Face outline in green
        outline_ids = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323,
                       361, 288, 397, 365, 379, 378, 400, 377, 152, 148,
                       176, 149, 150, 136, 172, 58, 132, 93, 234, 127,
                       162, 21, 54, 103, 67, 109, 10]
        pts = [(int(lms[i].x * w), int(lms[i].y * h)) for i in outline_ids]
        for i in range(len(pts) - 1):
            cv2.line(frame, pts[i], pts[i+1], (0, 180, 0), 1)

    # ── Mask 3: Crown ────────────────────────────────────────────────────

    def _mask_crown(self, frame, lms):
        w, h = self.w, self.h
        forehead = _lm(lms, _FOREHEAD, w, h)
        lc = _lm(lms, _LEFT_CHEEK,  w, h)
        rc = _lm(lms, _RIGHT_CHEEK, w, h)

        crown_w = abs(rc[0] - lc[0])
        crown_h = int(crown_w * 0.45)
        cx = forehead[0]
        base_y = forehead[1] - int(crown_h * 0.15)

        gold = (0, 210, 255)
        gold_dark = (0, 150, 200)

        # Base band
        cv2.rectangle(frame,
                      (cx - crown_w // 2, base_y),
                      (cx + crown_w // 2, base_y + int(crown_h * 0.25)),
                      gold_dark, -1)
        cv2.rectangle(frame,
                      (cx - crown_w // 2, base_y),
                      (cx + crown_w // 2, base_y + int(crown_h * 0.25)),
                      gold, 1)

        # Three peaks
        peaks = [
            (cx, base_y - crown_h),
            (cx - crown_w // 3, base_y - int(crown_h * 0.65)),
            (cx + crown_w // 3, base_y - int(crown_h * 0.65)),
        ]
        bases = [
            (cx - int(crown_w * 0.12), base_y),
            (cx - crown_w // 2 + 4, base_y),
            (cx + crown_w // 2 - 4, base_y),
        ]
        bases_right = [
            (cx + int(crown_w * 0.12), base_y),
            (cx - crown_w // 3 + int(crown_w * 0.1), base_y),
            (cx + crown_w // 3 + int(crown_w * 0.1), base_y),
        ]

        for peak, bl, br in zip(peaks, bases, bases_right):
            pts = np.array([bl, peak, br], np.int32)
            cv2.fillPoly(frame, [pts], gold_dark)
            cv2.polylines(frame, [pts], True, gold, 1, cv2.LINE_AA)

        # Gem at center peak
        gem_cx, gem_cy = peaks[0]
        gem_cy += int(crown_h * 0.1)
        cv2.circle(frame, (gem_cx, gem_cy), 6, (0, 100, 255), -1)
        cv2.circle(frame, (gem_cx, gem_cy), 6, gold, 1)
        cv2.circle(frame, (gem_cx - 2, gem_cy - 2), 2, (200, 200, 255), -1)

    # ── Mask 4: Sunglasses ────────────────────────────────────────────────

    def _mask_sunglasses(self, frame, lms):
        w, h = self.w, self.h
        le_o = _lm(lms, _LEFT_EYE_OUTER,  w, h)
        re_o = _lm(lms, _RIGHT_EYE_OUTER, w, h)
        le_i = _lm(lms, _LEFT_EYE_INNER,  w, h)
        re_i = _lm(lms, _RIGHT_EYE_INNER, w, h)
        le_t = _lm(lms, _LEFT_EYE_TOP,    w, h)
        re_t = _lm(lms, _RIGHT_EYE_TOP,   w, h)
        le_b = _lm(lms, _LEFT_EYE_BOT,    w, h)
        re_b = _lm(lms, _RIGHT_EYE_BOT,   w, h)

        def eye_rect(outer, inner, top, bot, margin=6):
            x1 = outer[0] - margin
            x2 = inner[0] + margin
            y1 = top[1] - margin
            y2 = bot[1] + margin
            return (min(x1, x2), y1), (max(x1, x2), y2)

        # Lenses (dark fill)
        overlay = frame.copy()
        l_tl, l_br = eye_rect(le_o, le_i, le_t, le_b, margin=8)
        r_tl, r_br = eye_rect(re_i, re_o, re_t, re_b, margin=8)

        for tl, br in [(l_tl, l_br), (r_tl, r_br)]:
            lx1, ly1 = tl
            lx2, ly2 = br
            rx = (lx2 - lx1) // 2
            ry = (ly2 - ly1) // 2
            cx_ = (lx1 + lx2) // 2
            cy_ = (ly1 + ly2) // 2
            cv2.ellipse(overlay, (cx_, cy_), (rx, ry), 0, 0, 360, (10, 10, 10), -1)

        cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)

        # Lens borders
        for tl, br in [(l_tl, l_br), (r_tl, r_br)]:
            lx1, ly1 = tl
            lx2, ly2 = br
            rx = (lx2 - lx1) // 2
            ry = (ly2 - ly1) // 2
            cx_ = (lx1 + lx2) // 2
            cy_ = (ly1 + ly2) // 2
            cv2.ellipse(frame, (cx_, cy_), (rx, ry), 0, 0, 360, (200, 200, 200), 2)

        # Bridge
        cv2.line(frame, le_i, re_i, (200, 200, 200), 2)

        # Arms to ears
        lc = _lm(lms, _LEFT_CHEEK,  w, h)
        rc = _lm(lms, _RIGHT_CHEEK, w, h)
        cv2.line(frame, le_o, lc, (200, 200, 200), 2)
        cv2.line(frame, re_o, rc, (200, 200, 200), 2)

        # Glare on left lens
        gl_x = l_tl[0] + (l_br[0] - l_tl[0]) // 4
        gl_y = l_tl[1] + (l_br[1] - l_tl[1]) // 4
        cv2.line(frame, (gl_x, gl_y), (gl_x + 8, gl_y + 4),
                 (220, 220, 220), 1, cv2.LINE_AA)

    # ── Scan Animation (no face) ──────────────────────────────────────────

    def _draw_scan_animation(self, frame):
        h, w = frame.shape[:2]
        t = time.time()
        scan_y = int((math.sin(t * 1.5) * 0.4 + 0.5) * h)
        cv2.line(frame, (0, scan_y), (w, scan_y), (0, 255, 150), 1)
        cv2.putText(frame, "SCANNING FOR FACE...", (w // 2 - 100, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 150), 1, cv2.LINE_AA)

    # ── HUD ───────────────────────────────────────────────────────────────

    def _draw_hud(self, frame):
        h, w = frame.shape[:2]
        cv2.line(frame, (0, 48), (w, 48), (180, 180, 180), 1)
        cv2.putText(frame, f"MODE: FACE AR  [{MASK_NAMES[self.mask_idx]}]", (12, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        _draw_corner_brackets(frame)
        _draw_bottom_bar(frame, "Say 'next mask' / 'previous mask' to switch")
