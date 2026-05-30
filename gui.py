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


def _gen_sphere(n=110):
    """Generate n uniformly-distributed unit-sphere points using Fibonacci spiral."""
    pts = []
    for i in range(n):
        phi = math.acos(-1 + (2 * i) / n)
        theta = math.sqrt(n * math.pi) * phi
        x = math.sin(phi) * math.cos(theta)
        y = math.sin(phi) * math.sin(theta)
        z = math.cos(phi)
        pts.append([x, y, z])
    return pts

def _rot_y(pts, a):
    c, s = math.cos(a), math.sin(a)
    return [[p[0]*c + p[2]*s,  p[1], -p[0]*s + p[2]*c] for p in pts]

def _rot_x(pts, a):
    c, s = math.cos(a), math.sin(a)
    return [[p[0], p[1]*c - p[2]*s, p[1]*s + p[2]*c] for p in pts]


# ─── State color palettes ─────────────────────────────────────────────────────
PALETTES = {
    "IDLE":      {"core": (60, 100, 180),  "glow": (30,  60, 140),  "line": (40, 80, 160)},
    "LISTENING": {"core": (0,  220, 255),  "glow": (0,  160, 200),  "line": (0, 180, 220)},
    "THINKING":  {"core": (255, 170,  0),  "glow": (200, 120,  0),  "line": (220, 150, 0)},
    "SPEAKING":  {"core": (160,  50, 255), "glow": (110,  20, 200), "line": (140, 40, 230)},
    "ERROR":     {"core": (255,  60,  60), "glow": (180,  20,  20), "line": (220, 40, 40)},
}


# ─── Main Sphere Canvas ───────────────────────────────────────────────────────
class SphereCanvas(QWidget):
    """Renders the animated 3D holographic sphere."""

    ORBIT_RADII  = [0.40, 0.55, 0.72]   # relative to sphere radius
    CONNECT_DIST = 0.72                  # max distance to draw a connection line
    N_POINTS     = 110
    FPS          = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(340, 340)
        self.setMaximumSize(340, 340)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Sphere data
        random.seed(42)
        self._base_pts = _gen_sphere(self.N_POINTS)
        self._pts      = [p[:] for p in self._base_pts]   # current rotated pts

        # Animation state
        self._ry    = 0.0    # Y rotation angle
        self._rx    = 0.12   # X tilt (fixed)
        self._pulse = 1.0    # core pulse scale
        self._pdx   = 0.008  # pulse delta
        self._time  = 0.0
        self._state = "IDLE"
        self._vol   = 0.0    # sound amplitude
        self._wave  = [random.uniform(0.1, 0.4) for _ in range(24)]  # waveform bars

        # Ring angles for orbit lines
        self._orbit_angles = [random.uniform(0, 360) for _ in self.ORBIT_RADII]

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000 // self.FPS)

    def set_state(self, state):
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
        self._time += 0.033
        
        # Real-time simulated sound amplitude based on state
        self._vol = 0.0
        if self._state in ["LISTENING", "SPEAKING"]:
            if self._state == "SPEAKING":
                self._vol = 0.12 + abs(math.sin(self._time * 7.5)) * 0.28
            else:  # LISTENING
                self._vol = 0.03 + abs(math.sin(self._time * 15.0) * math.cos(self._time * 4.0)) * 0.18

        speed = self._speed()
        self._ry += speed

        # Rotate points
        pts = _rot_y(self._base_pts, self._ry)
        self._pts = _rot_x(pts, self._rx)

        # Pulse
        pulse_speed = {"IDLE": 0.006, "LISTENING": 0.014, "THINKING": 0.020,
                       "SPEAKING": 0.025, "ERROR": 0.030}.get(self._state, 0.010)
        pulse_range = {"IDLE": (0.96, 1.04), "LISTENING": (0.88, 1.12),
                       "THINKING": (0.92, 1.08), "SPEAKING": (0.82, 1.18),
                       "ERROR": (0.85, 1.15)}.get(self._state, (0.96, 1.04))
        self._pulse += pulse_speed * self._pdx
        if self._pulse > pulse_range[1] or self._pulse < pulse_range[0]:
            self._pdx *= -1

        # Orbit ring angles react to volume
        for i in range(len(self._orbit_angles)):
            orbit_speed = 0.4 * (i + 1) * (1.0 + self._vol * 3.5)
            self._orbit_angles[i] = (self._orbit_angles[i] + orbit_speed) % 360

        # Waveform updates
        if self._state in ["LISTENING", "SPEAKING"]:
            active_vol = self._vol if self._vol > 0 else 0.05
            self._wave = [
                active_vol * (0.6 + random.uniform(0.0, 0.4)) + abs(math.sin(self._time * 5.0 + idx * 0.3)) * 0.15
                for idx in range(24)
            ]
        else:
            self._wave = [max(0.05, w * 0.92) for w in self._wave]

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
        R  = int(min(cx, cy) * 0.62 * self._pulse)   # sphere display radius

        # ── 1. Background ambient glow ──────────────────────────────────────
        bg_r = int(R * 1.5)
        if R <= 0 or bg_r <= 0:
            p.end()
            return
        grad_bg = QRadialGradient(cx, cy, bg_r)
        grad_bg.setColorAt(0.0, QColor(gr, gg, gb, int(50 * (1.0 + self._vol))))
        grad_bg.setColorAt(1.0, QColor(5, 8, 20, 0))
        p.setBrush(QBrush(grad_bg))
        p.setPen(Qt.NoPen)
        p.drawEllipse(cx - bg_r, cy - bg_r, bg_r * 2, bg_r * 2)

        # ── 2. Segmented Orbit rings (Jarvis HUD markings) ──────────────────
        for idx, frac in enumerate(self.ORBIT_RADII):
            r_orb = int(R * (1.2 + frac * 0.45))
            angle = self._orbit_angles[idx]
            
            # Base thin dashboard orbit line
            pen_bg = QPen(QColor(lr, lg, lb, 20), 1.0)
            p.setPen(pen_bg)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(cx - r_orb, cy - r_orb, r_orb * 2, r_orb * 2)
            
            # Rotating thick indicators
            pen_seg = QPen(QColor(cr, cg, cb, 180), 2.5)
            p.setPen(pen_seg)
            for a in [0, 120, 240]:
                start_angle = int((angle + a - 6) * 16)
                span_angle = int(12 * 16)
                p.drawArc(cx - r_orb, cy - r_orb, r_orb * 2, r_orb * 2, start_angle, span_angle)

        # ── 3. Radial Equalizer sweep spikes (VFX hologram wave) ───────────
        if self._state in ["LISTENING", "SPEAKING"]:
            spike_count = 30
            angle_step = (2.0 * math.pi) / spike_count
            p.setPen(QPen(QColor(lr, lg, lb, 95), 1.0))
            
            for i in range(spike_count):
                angle = i * angle_step + self._time * 0.5
                wave_amp = self._wave[i % len(self._wave)]
                
                start_r = R * 0.95
                end_r = R * (0.95 + wave_amp * 0.6)
                
                sx = int(cx + math.cos(angle) * start_r)
                sy = int(cy + math.sin(angle) * start_r * 0.8) # elliptical projection
                ex = int(cx + math.cos(angle) * end_r)
                ey = int(cy + math.sin(angle) * end_r * 0.8)
                
                p.drawLine(sx, sy, ex, ey)

        # ── 4. Project 3D Nodes with sound displacement ────────────────────
        projected = []
        for idx, pt in enumerate(self._pts):
            disp = 1.0
            if self._state in ["LISTENING", "SPEAKING"]:
                phase = (idx * 0.15) + self._time * 18.0
                ripple = math.sin(phase)
                disp = 1.0 + (ripple * self._vol * 0.10) + (self._vol * 0.12)
            else:
                disp = 1.0 + math.sin(self._time * 2.0 + idx * 0.1) * 0.02

            px_ = int(cx + pt[0] * R * disp)
            py_ = int(cy - pt[1] * R * disp)
            z_  = pt[2]             # -1 (back) ... +1 (front)
            projected.append((px_, py_, z_))

        # ── 5. Draw connection lines (Foreground only - performance optimized)
        for i in range(0, len(self._pts), 3):
            if self._pts[i][2] < -0.25:
                continue
            for j in range(i + 1, len(self._pts), 4):
                if self._pts[j][2] < -0.25:
                    continue
                dist = math.sqrt(sum((self._pts[i][k] - self._pts[j][k])**2 for k in range(3)))
                if dist < self.CONNECT_DIST:
                    z_avg = (self._pts[i][2] + self._pts[j][2]) / 2
                    alpha = int(max(0, min(65, (z_avg + 1) * 30 + 10)))
                    line_col = QColor(lr, lg, lb, alpha)
                    p.setPen(QPen(line_col, 0.7))
                    p.drawLine(projected[i][0], projected[i][1],
                               projected[j][0], projected[j][1])

        # ── 6. Draw sorted nodes (back to front) ───────────────────────────
        sorted_indices = sorted(range(len(projected)), key=lambda idx: projected[idx][2])
        for idx in sorted_indices:
            px_, py_, z_ = projected[idx]
            brightness = (z_ + 1) / 2        # 0..1
            size_factor = 1.0 + self._vol * 1.2
            size = max(1.5, 4.5 * brightness * size_factor)
            alpha_ = int(80 + 175 * brightness)
            col = QColor(
                int(lr + (cr - lr) * brightness),
                int(lg + (cg - lg) * brightness),
                int(lb + (cb - lb) * brightness),
                alpha_
            )
            p.setBrush(QBrush(col))
            p.setPen(Qt.NoPen)
            p.drawEllipse(int(px_ - size / 2), int(py_ - size / 2), int(size), int(size))

        # ── 7. Central Morphing Core glow ──────────────────────────────────
        core_r = int(R * 0.22)
        core_glow = int(core_r * (1.25 + self._vol * 2.0))
        grad = QRadialGradient(cx, cy, core_glow)
        grad.setColorAt(0.0, QColor(cr, cg, cb, 210))
        grad.setColorAt(0.3, QColor(cr, cg, cb, 80))
        grad.setColorAt(1.0, QColor(gr, gg, gb, 0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawEllipse(cx - core_glow, cy - core_glow, core_glow * 2, core_glow * 2)

        # ── 8. Bottom Visualizer wave bars ─────────────────────────────────
        bar_count = len(self._wave)
        bar_w     = 6
        bar_gap   = 3
        total_w   = bar_count * (bar_w + bar_gap)
        bx_start  = cx - total_w // 2
        by_base   = cy + R + 14
        max_bar_h = 28

        for i, amp in enumerate(self._wave):
            bh    = max(3, int(amp * max_bar_h))
            bx    = bx_start + i * (bar_w + bar_gap)
            alpha = int(80 + 140 * amp)
            bar_c = QColor(cr, cg, cb, alpha)
            p.setBrush(QBrush(bar_c))
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
