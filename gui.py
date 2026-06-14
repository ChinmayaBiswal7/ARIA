# -*- coding: utf-8 -*-
"""
ARIA GUI - Jarvis-style 3D particle sphere
A cinematic holographic AI orb that reacts to ARIA's state.
"""

import sys
import math
import random
import time

from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout
from PyQt5.QtCore    import Qt, QTimer, QObject, pyqtSignal, QPoint
from PyQt5.QtGui     import (QPainter, QColor, QBrush, QPen, QFont,
                              QLinearGradient, QRadialGradient, QPainterPath,
                              QFontDatabase)

# ─── Thread-safe signal bridge ───────────────────────────────────────────────
class _Bridge(QObject):
    state_changed = pyqtSignal(str)
    text_updated  = pyqtSignal(str)
    user_updated  = pyqtSignal(str)
    wave_tick     = pyqtSignal()          # trigger waveform update from voice thread

_bridge = _Bridge()

def set_state(state: str):
    _bridge.state_changed.emit(state.upper())

def set_text(text: str):
    _bridge.text_updated.emit(text[:120])

def set_user(name: str):
    _bridge.user_updated.emit(name or "")

def trigger_wave():
    _bridge.wave_tick.emit()

def _gen_sphere(n=2000):
    """Generate n uniformly-distributed unit-sphere points using Fibonacci spiral (matches mobile)."""
    pts = []
    golden_ratio = (1.0 + 5.0**0.5) / 2.0
    golden_angle = (2.0 - golden_ratio) * (2.0 * math.pi)
    for i in range(n):
        z = 1.0 - (i / (n - 1.0)) * 2.0
        radius_at_z = math.sqrt(max(0.0, 1.0 - z * z))
        theta = i * golden_angle
        x = math.cos(theta) * radius_at_z
        y = math.sin(theta) * radius_at_z
        pts.append([x, y, z])
    return pts

# ─── State color palettes ─────────────────────────────────────────────────────
PALETTES = {
    "IDLE":      {"core": (0, 140, 255),   "glow": (0, 85, 204),     "line": (0, 140, 255)},
    "LISTENING": {"core": (0, 229, 255),   "glow": (0, 153, 255),    "line": (0, 229, 255)},
    "THINKING":  {"core": (139, 92, 246),  "glow": (59, 7, 100),     "line": (139, 92, 246)},
    "SPEAKING":  {"core": (16, 185, 129),  "glow": (6, 78, 59),      "line": (16, 185, 129)},
    "ERROR":     {"core": (255, 60, 60),    "glow": (180, 20, 20),    "line": (255, 60, 60)},
}

STATE_LAYERS = {
    "IDLE": {
        "back":   (0, 31, 102),     # #001F66 (dim navy)
        "middle": (0, 85, 204),     # #0055CC (royal blue)
        "front":  (0, 140, 255),    # #008CFF (neon blue)
    },
    "LISTENING": {
        "back":   (0, 34, 170),     # #0022AA (cobalt blue)
        "middle": (0, 153, 255),    # #0099FF (electric blue)
        "front":  (0, 229, 255),    # #00E5FF (cyan)
    },
    "SPEAKING": {
        "back":   (6, 78, 59),      # #064E3B (forest green)
        "middle": (16, 185, 129),   # #10B981 (emerald green)
        "front":  (245, 158, 11),   # #F59E0B (golden amber highlights)
    },
    "THINKING": {
        "back":   (59, 7, 100),     # #3B0764 (dark purple)
        "middle": (139, 92, 246),   # #8B5CF6 (violet)
        "front":  (192, 132, 252),  # #C084FC (light purple)
    },
    "ERROR": {
        "back":   (139, 20, 20),
        "middle": (220, 40, 40),
        "front":  (255, 60, 60),
    }
}

# ─── Caching systems for high-performance QColor, QBrush, and QPen lookup ──────
COLOR_CACHE = {}
BRUSH_CACHE = {}
PEN_CACHE = {}

def get_color(r, g, b, a):
    key = (r, g, b, a)
    if key not in COLOR_CACHE:
        COLOR_CACHE[key] = QColor(r, g, b, a)
    return COLOR_CACHE[key]

def get_brush(r, g, b, a):
    key = (r, g, b, a)
    if key not in BRUSH_CACHE:
        BRUSH_CACHE[key] = QBrush(get_color(r, g, b, a))
    return BRUSH_CACHE[key]

def get_pen(r, g, b, a, width=1.0):
    key = (r, g, b, a, width)
    if key not in PEN_CACHE:
        PEN_CACHE[key] = QPen(get_color(r, g, b, a), width)
    return PEN_CACHE[key]


# ─── Main Sphere Canvas ───────────────────────────────────────────────────────
class SphereCanvas(QWidget):
    """Renders the animated 3D holographic sphere."""

    CONNECT_DIST = 0.45                  # max distance to draw a connection line (matches mobile maxConnectDist = 0.45f)
    N_POINTS     = 1000                  # 1000 points (optimizes CPU performance on desktop while keeping high density)
    FPS          = 60

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(340, 340)
        self.setMaximumSize(340, 340)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Sphere data
        random.seed(42)
        self._base_pts = _gen_sphere(self.N_POINTS)
        self._particle_speeds = [0.3 + random.random() * 1.0 for _ in range(self.N_POINTS)]
        self._particle_phases = [random.random() * 2.0 * math.pi for _ in range(self.N_POINTS)]

        # Animation state
        self._ry    = 0.0    # Y rotation angle
        self._rx    = 0.35   # X tilt forward (matches mobile rx = 0.35f)
        self._pulse = 1.0    # core pulse scale
        self._time  = 0.0
        self._real_time = 0.0  # Real time elapsed in seconds for camera float
        self._state = "IDLE"
        self._vol   = 0.0    # sound amplitude
        self._wave  = [random.uniform(0.1, 0.4) for _ in range(24)]  # waveform bars

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000 // self.FPS)

    def set_state(self, state):
        if state == "OFFLINE":
            self._state = "ERROR"
        else:
            self._state = state if state in PALETTES else "IDLE"
        self.update()

    def push_wave(self):
        """Animate waveform (call when speaking)."""
        self._wave = [abs(math.sin(self._time * 8 + i * 0.7)) * random.uniform(0.4, 1.0)
                      for i in range(24)]

    def _speed(self):
        return {"IDLE": 0.003, "LISTENING": 0.008, "THINKING": 0.015,
                "SPEAKING": 0.020, "ERROR": 0.025}.get(self._state, 0.005)

    def _tick(self):
        dt = 1.0 / self.FPS
        self._real_time += dt

        # Determine Y rotation speed based on active state (matches mobile speed values)
        speed = {
            "OFFLINE": 0.0004,
            "LISTENING": 0.012,
            "THINKING": 0.022,
            "SPEAKING": 0.016,
        }.get(self._state, 0.003)

        speed_factor = 60.0 / self.FPS
        self._time += speed * speed_factor
        self._ry = (self._ry + speed * speed_factor) % (2.0 * math.pi)

        # Real-time simulated sound amplitude based on state
        self._vol = 0.0
        if self._state in ["LISTENING", "SPEAKING"]:
            if self._state == "SPEAKING":
                self._vol = 0.12 + abs(math.sin(self._time * 5.5)) * 0.22
            else:  # LISTENING
                self._vol = 0.03 + abs(math.sin(self._time * 15.0) * math.cos(self._time * 4.0)) * 0.18

        # Pulse core breathing envelope (matches mobile: 1.0 + sin(time * 1.8) * 0.04)
        self._pulse = 1.0 + math.sin(self._time * 1.8) * 0.04

        # Waveform updates
        if self._state in ["LISTENING", "SPEAKING"]:
            active_vol = self._vol if self._vol > 0 else 0.05
            self._wave = [
                active_vol * (0.6 + random.uniform(0.0, 0.4)) + abs(math.sin(self._time * 5.0 + idx * 0.3)) * 0.15
                for idx in range(24)
            ]
        else:
            decay = 0.92 ** (30.0 / self.FPS)
            self._wave = [max(0.05, w * decay) for w in self._wave]

        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        pal  = PALETTES[self._state]
        cr, cg, cb   = pal["core"]
        gr, gg, gb   = pal["glow"]
        lr, lg, lb   = pal["line"]

        cx = self.width()  // 2
        cy = self.height() // 2
        # Match mobile drawing radius = width * 0.38f (using full width/height minimum)
        R  = int(min(self.width(), self.height()) * 0.38 * self._pulse)

        # Simulated mouth-flap speaker level to look alive even in room silence (copied from mobile)
        active_vol = self._vol
        if self._state == "SPEAKING" and active_vol < 0.05:
            active_vol = 0.12 + abs(math.sin(self._time * 5.5)) * 0.22

        # ── 1. Background ambient glow (using mobile alpha & color values) ──
        bg_r = int(R * 1.55) # matches mobile glowRadius = radius * 1.55f
        if R <= 0 or bg_r <= 0:
            p.end()
            return
        
        glow_alpha = 0.05 if self._state == "ERROR" else (0.10 + active_vol * 0.18)
        grad_bg = QRadialGradient(cx, cy, bg_r)
        grad_bg.setColorAt(0.0, get_color(cr, cg, cb, int(glow_alpha * 255)))
        grad_bg.setColorAt(1.0, get_color(5, 8, 20, 0))
        p.setBrush(QBrush(grad_bg))
        p.setPen(Qt.NoPen)
        p.drawEllipse(cx - bg_r, cy - bg_r, bg_r * 2, bg_r * 2)

        # ── 2. Radial Equalizer sweep spikes (VFX hologram wave, matches mobile) ──
        if (self._state in ["LISTENING", "SPEAKING"]) and active_vol > 0.05:
            spike_count = 36
            angle_step = (2.0 * math.pi) / spike_count
            spike_alpha = int((0.2 + active_vol * 0.45) * 255)
            p.setPen(get_pen(cr, cg, cb, spike_alpha, 2.0))
            
            for i in range(spike_count):
                angle = i * angle_step + self._time * 0.35
                wave_amp = active_vol * (0.4 + 0.6 * math.sin(self._time * 8.5 + i))
                
                start_r = R * 0.95
                end_r = R * (0.95 + wave_amp * 0.55)
                
                sx = int(cx + math.cos(angle) * start_r)
                sy = int(cy + math.sin(angle) * start_r)
                ex = int(cx + math.cos(angle) * end_r)
                ey = int(cy + math.sin(angle) * end_r)
                
                p.drawLine(sx, sy, ex, ey)

        # ── 3. Simulated organic camera floating drift (for continuous parallax) ──
        # Computes continuous low-frequency drift to shift front & back layers
        float_x = math.sin(self._real_time * 1.5) * 6.0
        float_y = math.cos(self._real_time * 1.2) * 6.0

        # ── 4. Project 3D Nodes using mobile camera equations & layer shifts ──
        projected = []
        
        cosY = math.cos(self._ry)
        sinY = math.sin(self._ry)
        cosX = math.cos(self._rx)
        sinX = math.sin(self._rx)
        
        camDistance = 3.2 # matches mobile camDistance = 3.2f

        for idx, pt in enumerate(self._base_pts):
            # Rotate Y
            x1 = pt[0] * cosY + pt[2] * sinY
            y1 = pt[1]
            z1 = -pt[0] * sinY + pt[2] * cosY

            # Rotate X
            x2 = x1
            y2 = y1 * cosX - z1 * sinX
            z2 = y1 * sinX + z1 * cosX

            displacement = 1.0
            if self._state == "THINKING":
                # Vortex effect: spiral around Z-axis and pull inward
                vortex_angle = self._time * 2.8 + z2 * 4.5
                c = math.cos(vortex_angle)
                s = math.sin(vortex_angle)
                rxNew = x2 * c - y2 * s
                ryNew = x2 * s + y2 * c
                x2 = rxNew
                y2 = ryNew
                displacement = 0.68 + 0.32 * abs(math.sin(self._time * 1.5 + self._particle_phases[idx]))
            elif self._state in ["LISTENING", "SPEAKING"]:
                # Audio spike ripple
                ripple = math.sin(self._time * 18.0 * self._particle_speeds[idx] + self._particle_phases[idx])
                displacement = 1.0 + (ripple * active_vol * 0.12) + (active_vol * 0.20)
            else:
                # Gentle idle drift
                displacement = 1.0 + math.sin(self._time * 2.2 * self._particle_speeds[idx] + self._particle_phases[idx]) * 0.02

            # Camera perspective scaling
            scaleFactor = camDistance / (camDistance + z2 * 0.6)

            # Continuous parallax layer translation
            shiftX = float_x * z2
            shiftY = float_y * z2

            px_ = int(cx + x2 * R * displacement * scaleFactor + shiftX)
            py_ = int(cy - y2 * R * displacement * scaleFactor + shiftY)
            
            projected.append((px_, py_, z2, scaleFactor))

        # ── 5. Draw connection lines (Both hemispheres with depth fade, matching mobile) ────
        connect_dist_sq = self.CONNECT_DIST ** 2
        step_i = 8
        step_j = 12
        for i in range(0, len(self._base_pts), step_i):
            pt_i = self._base_pts[i]
            proji = projected[i]
            for j in range(i + 1, len(self._base_pts), step_j):
                pt_j = self._base_pts[j]
                dx = pt_i[0] - pt_j[0]
                dy = pt_i[1] - pt_j[1]
                dz = pt_i[2] - pt_j[2]
                dist_sq = dx*dx + dy*dy + dz*dz
                if dist_sq < connect_dist_sq:
                    projj = projected[j]
                    z_avg = (proji[2] + projj[2]) / 2.0
                    depth_fade = 0.15 + 0.85 * ((z_avg + 1.0) / 2.0)
                    alpha = 0.15 * depth_fade * (1.0 + active_vol * 1.5)
                    if self._state == "ERROR":
                        alpha *= 0.1
                    alpha_val = max(0.01, min(0.5, alpha))
                    alpha_int = int(alpha_val * 255)
                    p.setPen(get_pen(cr, cg, cb, alpha_int, 1.0))
                    p.drawLine(proji[0], proji[1], projj[0], projj[1])

        # ── 6. Draw sorted nodes (back to front) with nested core glow ─────
        sorted_indices = sorted(range(len(projected)), key=lambda idx: projected[idx][2])
        core_drawn = False

        for idx in sorted_indices:
            px_, py_, z2, scaleFactor = projected[idx]

            # Draw core glow at the exact z = 0 boundary
            if not core_drawn and z2 >= 0.0:
                core_r = int(R * 0.24) # matches mobile coreRadius = radius * 0.24f
                core_glow = int(core_r * (1.1 + active_vol * 2.0))
                if core_glow > 0:
                    grad = QRadialGradient(cx, cy, core_glow)
                    core_alpha = 0.3 if self._state == "ERROR" else 0.85
                    grad.setColorAt(0.0, get_color(cr, cg, cb, int(core_alpha * 255)))
                    grad.setColorAt(0.4, get_color(cr, cg, cb, int(core_alpha * 60)))
                    grad.setColorAt(1.0, get_color(5, 8, 20, 0))
                    p.setBrush(QBrush(grad))
                    p.setPen(Qt.NoPen)
                    p.drawEllipse(cx - core_glow, cy - core_glow, core_glow * 2, core_glow * 2)
                core_drawn = True

            # Determine dynamic depth layer
            if z2 < -0.3:
                layer = "back"
                base_size = 1.8
                base_alpha = 0.20
            elif z2 < 0.3:
                layer = "middle"
                base_size = 3.2
                base_alpha = 0.55
            else:
                layer = "front"
                base_size = 5.2
                base_alpha = 0.85

            brightness = (z2 + 1.0) / 2.0
            size = base_size * brightness * (1.0 + active_vol * 0.5) * scaleFactor
            alpha_int = int(base_alpha * (0.25 + 0.75 * brightness) * (0.25 if self._state == "ERROR" else 1.0) * 255)

            # Dynamic layer-wise colors
            colors = STATE_LAYERS.get(self._state, STATE_LAYERS["IDLE"])
            layer_col = colors[layer]
            
            p.setBrush(get_brush(layer_col[0], layer_col[1], layer_col[2], alpha_int))
            p.setPen(Qt.NoPen)
            p.drawEllipse(int(px_ - size / 2.0), int(py_ - size / 2.0), int(max(1.0, size)), int(max(1.0, size)))

        # Fallback to make sure core is drawn
        if not core_drawn:
            core_r = int(R * 0.24)
            core_glow = int(core_r * (1.1 + active_vol * 2.0))
            if core_glow > 0:
                grad = QRadialGradient(cx, cy, core_glow)
                core_alpha = 0.3 if self._state == "ERROR" else 0.85
                grad.setColorAt(0.0, get_color(cr, cg, cb, int(core_alpha * 255)))
                grad.setColorAt(0.4, get_color(cr, cg, cb, int(core_alpha * 60)))
                grad.setColorAt(1.0, get_color(5, 8, 20, 0))
                p.setBrush(QBrush(grad))
                p.setPen(Qt.NoPen)
                p.drawEllipse(cx - core_glow, cy - core_glow, core_glow * 2, core_glow * 2)

        # ── 7. Bottom Visualizer wave bars ─────────────────────────────────
        bar_count = len(self._wave)
        bar_w     = 6
        bar_gap   = 3
        total_w   = bar_count * (bar_w + bar_gap)
        bx_start  = cx - total_w // 2
        by_base   = cy + int(min(cx, cy) * 0.62 * self._pulse) + 14
        max_bar_h = 28

        for i, amp in enumerate(self._wave):
            bh    = max(3, int(amp * max_bar_h))
            bx    = bx_start + i * (bar_w + bar_gap)
            alpha = int(80 + 140 * amp)
            p.setBrush(get_brush(cr, cg, cb, alpha))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(bx, by_base - bh, bar_w, bh * 2, 2, 2)
        p.end()


# ─── ARIA Window ──────────────────────────────────────────────────────────────
class ARIAWindow(QWidget):

    def __init__(self):
        super().__init__()
        self._drag_pos = None
        self._setup_window()
        self._setup_ui()
        self._connect_signals()
        self.show()

    def _setup_window(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        scr  = QApplication.primaryScreen().size()
        W, H = 360, 520
        self.setGeometry(scr.width() - W - 24, 24, W, H)
        self.setWindowTitle("ARIA")

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Glass card ────
        self._card = QWidget(self)
        self._card.setObjectName("card")
        self._card.setStyleSheet("""
            QWidget#card {
                background: rgba(5, 8, 20, 215);
                border-radius: 28px;
                border: 1px solid rgba(0, 200, 255, 30);
            }
        """)
        outer.addWidget(self._card)

        vl = QVBoxLayout(self._card)
        vl.setContentsMargins(18, 14, 18, 18)
        vl.setSpacing(6)

        # ── Title bar ────
        title_row = QHBoxLayout()

        dot_lbl = QLabel()
        dot_lbl.setFixedSize(8, 8)
        dot_lbl.setStyleSheet("background: #00ccff; border-radius: 4px;")

        name_lbl = QLabel("A R I A")
        name_lbl.setStyleSheet(
            "color: rgba(0,210,255,220); font-size: 13px; font-weight: bold; "
            "letter-spacing: 6px; font-family: 'Segoe UI';"
        )

        self._user_lbl = QLabel("")
        self._user_lbl.setStyleSheet(
            "color: rgba(0,200,255,150); font-size: 10px; font-style: italic; font-family: 'Segoe UI';"
        )

        close_lbl = QLabel("  x  ")
        close_lbl.setStyleSheet(
            "color: rgba(255,255,255,60); font-size: 14px; font-family: 'Segoe UI';"
        )
        close_lbl.setCursor(Qt.PointingHandCursor)
        close_lbl.mousePressEvent = lambda e: self.hide()

        title_row.addWidget(dot_lbl)
        title_row.addSpacing(6)
        title_row.addWidget(name_lbl)
        title_row.addStretch()
        title_row.addWidget(self._user_lbl)
        title_row.addWidget(close_lbl)
        vl.addLayout(title_row)

        # ── Sphere ────
        sphere_row = QHBoxLayout()
        sphere_row.setAlignment(Qt.AlignCenter)
        self._sphere = SphereCanvas()
        sphere_row.addWidget(self._sphere)
        vl.addLayout(sphere_row)

        # ── Status ────
        self._status_lbl = QLabel("IDLE")
        self._status_lbl.setAlignment(Qt.AlignCenter)
        self._status_lbl.setStyleSheet(
            "color: rgba(0,180,255,160); font-size: 10px; letter-spacing: 5px;"
            "font-family: 'Segoe UI'; margin-top: 2px;"
        )
        vl.addWidget(self._status_lbl)

        # ── Divider ────
        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: rgba(0,180,255,25);")
        vl.addWidget(divider)

        # ── Transcript ────
        self._text_lbl = QLabel("Say 'Hey ARIA' or speak a command...")
        self._text_lbl.setWordWrap(True)
        self._text_lbl.setAlignment(Qt.AlignCenter)
        self._text_lbl.setMinimumHeight(55)
        self._text_lbl.setStyleSheet(
            "color: rgba(180,210,240,180); font-size: 11px; line-height: 1.6;"
            "font-family: 'Segoe UI'; padding: 4px 8px;"
        )
        vl.addWidget(self._text_lbl)

    def _connect_signals(self):
        _bridge.state_changed.connect(self._on_state)
        _bridge.text_updated.connect(self._on_text)
        _bridge.user_updated.connect(self._on_user)
        _bridge.wave_tick.connect(self._sphere.push_wave)

    def _on_state(self, s):
        if s == "OFFLINE":
            s = "ERROR"
        self._sphere.set_state(s)
        self._status_lbl.setText(s)

        colors = {
            "IDLE":      "rgba(80,140,220,180)",
            "LISTENING": "rgba(0,220,255,230)",
            "THINKING":  "rgba(255,165,0,230)",
            "SPEAKING":  "rgba(170,60,255,230)",
            "ERROR":     "rgba(255,80,80,230)",
        }
        c = colors.get(s, "rgba(80,140,220,180)")
        self._status_lbl.setStyleSheet(
            f"color: {c}; font-size: 10px; letter-spacing: 5px;"
            "font-family: 'Segoe UI'; margin-top: 2px;"
        )

    def _on_text(self, t):
        self._text_lbl.setText(t)

    def _on_user(self, n):
        self._user_lbl.setText(f"  {n}  " if n else "")

    # ── Drag ──────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.LeftButton and self._drag_pos:
            self.move(e.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def close_cleanly(self):
        """Cleanly stop canvas timer and close window."""
        try:
            self._sphere._timer.stop()
            print("[GUI] Stopped SphereCanvas refresh timer.")
        except Exception:
            pass
        self.close()

    def closeEvent(self, event):
        self.close_cleanly()
        event.accept()


# ─── Launch helper ────────────────────────────────────────────────────────────
def run_app():
    app = QApplication.instance() or QApplication(sys.argv)
    win = ARIAWindow()
    return app, win


if __name__ == "__main__":
    app, win = run_app()
    # Demo: cycle states
    import threading
    def demo():
        import time
        for s in ["IDLE", "LISTENING", "THINKING", "SPEAKING", "IDLE"]:
            time.sleep(2)
            set_state(s)
            set_text(f"State is now: {s}")
    threading.Thread(target=demo, daemon=True).start()
    sys.exit(app.exec_())
