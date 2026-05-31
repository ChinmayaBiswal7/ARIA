"""
ar_physics.py — ARIA Advanced AR Suite
Mode: Hand Physics
Voice triggers: "AR physics mode", "AR balls mode"

Features:
- 15 physics balls with gravity, bounce off edges
- Hand bounding box = solid collider
- Pinch + move = grab and throw balls
- Clap gesture = explosion blast
- Ball-ball collision
"""

import cv2
import numpy as np
import math
import random
import time
from ar_drawing import _draw_corner_brackets, _draw_bottom_bar


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _landmark_px(lm, w, h):
    return int(lm.x * w), int(lm.y * h)


# ── Ball ──────────────────────────────────────────────────────────────────────

class Ball:
    COLORS = [
        (255, 255, 255),
        (0, 210, 255),
        (0, 255, 130),
        (255, 90, 90),
        (255, 200, 0),
        (180, 80, 255),
        (255, 150, 0),
    ]

    def __init__(self, w, h, idx):
        self.r = random.randint(12, 22)
        self.x = float(random.randint(self.r, w - self.r))
        self.y = float(random.randint(self.r, h // 2))
        self.vx = random.uniform(-3, 3)
        self.vy = random.uniform(-2, 2)
        self.color = self.COLORS[idx % len(self.COLORS)]
        self.grabbed = False
        self.grab_offset = (0, 0)

    def update(self, w, h, gravity=0.45, damping=0.78):
        if self.grabbed:
            return
        self.vy += gravity
        self.x += self.vx
        self.y += self.vy

        # Bounce off edges
        if self.x - self.r < 0:
            self.x = float(self.r)
            self.vx = abs(self.vx) * damping
        if self.x + self.r > w:
            self.x = float(w - self.r)
            self.vx = -abs(self.vx) * damping
        if self.y - self.r < 0:
            self.y = float(self.r)
            self.vy = abs(self.vy) * damping
        if self.y + self.r > h:
            self.y = float(h - self.r)
            self.vy = -abs(self.vy) * damping
            self.vx *= 0.92  # floor friction

        # Speed cap
        speed = math.hypot(self.vx, self.vy)
        if speed > 25:
            self.vx = self.vx / speed * 25
            self.vy = self.vy / speed * 25

    def draw(self, frame):
        cx, cy = int(self.x), int(self.y)
        # Glow
        glow_col = tuple(min(255, c + 60) for c in self.color)
        cv2.circle(frame, (cx, cy), self.r + 4, glow_col, 1, cv2.LINE_AA)
        # Body
        cv2.circle(frame, (cx, cy), self.r, self.color, -1, cv2.LINE_AA)
        # Specular highlight
        hx = cx - self.r // 3
        hy = cy - self.r // 3
        cv2.circle(frame, (hx, hy), max(2, self.r // 4), (255, 255, 255), -1, cv2.LINE_AA)


# ── Main Mode Class ───────────────────────────────────────────────────────────

class ARPhysics:
    NUM_BALLS = 15

    def __init__(self, frame_w, frame_h):
        self.w = frame_w
        self.h = frame_h
        self.balls = [Ball(frame_w, frame_h, i) for i in range(self.NUM_BALLS)]
        self.label = "PHYSICS"

        # Grab state
        self._grabbed_ball = None
        self._prev_hand_pos = None
        self._hand_vel = (0.0, 0.0)

        # Clap detection
        self._prev_both_hands = None
        self._last_clap_time = 0

        # Explosion particles
        self._particles = []

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, frame, hand_landmarks, hand_landmarks_list=None):
        """
        hand_landmarks: first hand (mediapipe result)
        hand_landmarks_list: all hands (list) for clap detection
        """
        out = frame.copy()

        # Detect clap with 2 hands
        if hand_landmarks_list and len(hand_landmarks_list) >= 2:
            self._detect_clap(hand_landmarks_list, out)

        if hand_landmarks:
            self._handle_hand(hand_landmarks, out)
        else:
            self._release_grabbed()

        # Ball-ball collision
        self._resolve_ball_collisions()

        # Update + draw balls
        for ball in self.balls:
            ball.update(self.w, self.h)
            ball.draw(out)

        # Update + draw explosion particles
        self._update_particles(out)

        # HUD
        self._draw_hud(out)
        return out

    # ── Hand Interaction ──────────────────────────────────────────────────

    def _handle_hand(self, lms, frame):
        w, h = self.w, self.h

        # Get hand bounding box
        xs = [int(lm.x * w) for lm in lms.landmark]
        ys = [int(lm.y * h) for lm in lms.landmark]
        hx1, hx2 = min(xs) - 10, max(xs) + 10
        hy1, hy2 = min(ys) - 10, max(ys) + 10

        # Current fingertip
        tip = _landmark_px(lms.landmark[8], w, h)

        # Track hand velocity
        if self._prev_hand_pos:
            self._hand_vel = (
                tip[0] - self._prev_hand_pos[0],
                tip[1] - self._prev_hand_pos[1]
            )
        self._prev_hand_pos = tip

        # Pinch detection
        thb = _landmark_px(lms.landmark[4], w, h)
        pinching = _dist(tip, thb) < w * 0.06

        # Draw hand outline
        cv2.rectangle(frame, (hx1, hy1), (hx2, hy2), (200, 200, 200), 1)

        if pinching and self._grabbed_ball is None:
            # Try to grab nearest ball to fingertip
            for ball in self.balls:
                if _dist(tip, (ball.x, ball.y)) < ball.r + 20:
                    ball.grabbed = True
                    ball.grab_offset = (ball.x - tip[0], ball.y - tip[1])
                    self._grabbed_ball = ball
                    break

        if self._grabbed_ball:
            if pinching:
                # Move grabbed ball
                self._grabbed_ball.x = tip[0] + self._grabbed_ball.grab_offset[0]
                self._grabbed_ball.y = tip[1] + self._grabbed_ball.grab_offset[1]
                # Draw grab indicator
                cv2.line(frame, tip, (int(self._grabbed_ball.x), int(self._grabbed_ball.y)),
                         (255, 255, 255), 1, cv2.LINE_AA)
            else:
                # Release = throw
                self._grabbed_ball.vx = self._hand_vel[0] * 1.5
                self._grabbed_ball.vy = self._hand_vel[1] * 1.5
                self._grabbed_ball.grabbed = False
                self._grabbed_ball = None

        # Push non-grabbed balls away from hand box
        for ball in self.balls:
            if ball.grabbed:
                continue
            bx, by = int(ball.x), int(ball.y)
            # Simple AABB push
            if hx1 < bx < hx2 and hy1 < by < hy2:
                # Push out in direction of hand velocity
                push_x = self._hand_vel[0] * 0.8
                push_y = self._hand_vel[1] * 0.8
                ball.vx += push_x
                ball.vy += push_y - 3  # slight upward bias

    def _release_grabbed(self):
        if self._grabbed_ball:
            self._grabbed_ball.grabbed = False
            self._grabbed_ball = None
        self._prev_hand_pos = None

    # ── Clap Detection ────────────────────────────────────────────────────

    def _detect_clap(self, hands_list, frame):
        if len(hands_list) < 2:
            return
        now = time.time()
        if now - self._last_clap_time < 1.5:
            return

        h0 = hands_list[0]
        h1 = hands_list[1]
        w, h = self.w, self.h

        # Center of each palm
        p0 = _landmark_px(h0.landmark[9], w, h)
        p1 = _landmark_px(h1.landmark[9], w, h)
        dist = _dist(p0, p1)

        if dist < w * 0.12:
            self._explode()
            self._last_clap_time = now
            # Visual clap flash
            overlay = frame.copy()
            cv2.rectangle(overlay, (0, 0), (w, h), (255, 255, 255), -1)
            cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)

    def _explode(self):
        cx, cy = self.w // 2, self.h // 2
        for ball in self.balls:
            dx = ball.x - cx
            dy = ball.y - cy
            dist = max(1, math.hypot(dx, dy))
            force = 18.0
            ball.vx += (dx / dist) * force
            ball.vy += (dy / dist) * force

        # Spawn explosion particles
        for _ in range(40):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(4, 12)
            self._particles.append({
                'x': float(cx), 'y': float(cy),
                'vx': math.cos(angle) * speed,
                'vy': math.sin(angle) * speed,
                'life': 1.0,
                'color': random.choice(Ball.COLORS),
                'size': random.randint(2, 5)
            })

    # ── Ball-Ball Collision ───────────────────────────────────────────────

    def _resolve_ball_collisions(self):
        for i in range(len(self.balls)):
            for j in range(i + 1, len(self.balls)):
                a, b = self.balls[i], self.balls[j]
                if a.grabbed or b.grabbed:
                    continue
                dx = b.x - a.x
                dy = b.y - a.y
                dist = math.hypot(dx, dy)
                min_dist = a.r + b.r
                if dist < min_dist and dist > 0:
                    overlap = (min_dist - dist) / 2
                    nx, ny = dx / dist, dy / dist
                    a.x -= nx * overlap
                    a.y -= ny * overlap
                    b.x += nx * overlap
                    b.y += ny * overlap
                    # Exchange velocities along normal
                    dvx = a.vx - b.vx
                    dvy = a.vy - b.vy
                    dot = dvx * nx + dvy * ny
                    if dot > 0:
                        a.vx -= dot * nx * 0.9
                        a.vy -= dot * ny * 0.9
                        b.vx += dot * nx * 0.9
                        b.vy += dot * ny * 0.9

    # ── Particles ─────────────────────────────────────────────────────────

    def _update_particles(self, frame):
        alive = []
        for p in self._particles:
            p['x'] += p['vx']
            p['y'] += p['vy']
            p['vy'] += 0.3
            p['life'] -= 0.03
            if p['life'] > 0:
                alpha = p['life']
                col = tuple(int(c * alpha) for c in p['color'])
                cv2.circle(frame, (int(p['x']), int(p['y'])), p['size'], col, -1)
                alive.append(p)
        self._particles = alive

    # ── HUD ───────────────────────────────────────────────────────────────

    def _draw_hud(self, frame):
        h, w = frame.shape[:2]
        cv2.line(frame, (0, 48), (w, 48), (180, 180, 180), 1)
        cv2.putText(frame, "MODE: PHYSICS", (12, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, f"Balls: {self.NUM_BALLS}", (w - 90, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1, cv2.LINE_AA)
        _draw_corner_brackets(frame)
        _draw_bottom_bar(frame, "Pinch=Grab | Release=Throw | Clap=Explode")
