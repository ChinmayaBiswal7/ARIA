"""
skills/gesture_control.py

Hand Gesture Control for ARIA — v2 (Shared Camera, Simplified)
================================================================
Uses MediaPipe 0.10 Tasks API (HandLandmarker) + PyAutoGUI.

KEY DESIGN DECISIONS
--------------------
1. No own camera — accepts a frame_provider() callable that returns a BGR
   numpy array. Pass camera.capture_frame_raw so the gesture thread shares
   ARIA's existing webcam instead of fighting over /dev/video0.

2. Stable features first (v1 set):
     ✅ Cursor movement (EMA smoothed, dead-zone gated)
     ✅ Left click (index + thumb pinch)
     ✅ Scroll (two fingers raised, vertical hand movement)
   Advanced gestures (volume, ARIA events) are OFF by default.

3. 20 fps loop — enough for smooth tracking, keeps CPU reasonable.

Voice commands (handled in main.py):
    "enable gesture control" / "gesture mode on"
    "disable gesture control" / "gesture mode off"
"""

import os
import threading
import time
import math
import urllib.request
from dataclasses import dataclass
from collections import deque

import cv2
import pyautogui

# ─── MediaPipe import ─────────────────────────────────────────────────────────
try:
    import mediapipe as mp
    from mediapipe.tasks import python as _mp_python
    from mediapipe.tasks.python import vision as _mp_vision
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    print("[GestureControl] mediapipe not available — gesture control disabled.")

# ─── Model ────────────────────────────────────────────────────────────────────
_SKILL_DIR  = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SKILL_DIR)
_MODEL_DIR  = os.path.join(_PROJECT_DIR, "models")
_MODEL_PATH = os.path.join(_MODEL_DIR, "hand_landmarker.task")
_MODEL_URL  = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)

# ─── Tuning constants ─────────────────────────────────────────────────────────
pyautogui.FAILSAFE = False
pyautogui.PAUSE    = 0.0

# Cursor active tracking zone (normalized boundaries in camera space)
ACTIVE_X_MIN = 0.35
ACTIVE_X_MAX = 0.65
ACTIVE_Y_MIN = 0.40
ACTIVE_Y_MAX = 0.60

# Dynamic cursor smoothing (alpha weights)
MIN_ALPHA    = 0.15        # Low alpha = high smoothing for precise targeting
MAX_ALPHA    = 0.80        # High alpha = fast response for swift movement
DEADZONE_PX   = 4          # pixel dead-zone — ignore tiny tremors

# Left click pinch (index tip 8 + thumb tip 4)
PINCH_THRESH  = 0.040      # normalised distance to fire a click (tuned up from 0.025 for better reliability)
PINCH_RELEASE_THRESH = 0.070 # hysteresis release threshold to reset click state (tuned up from 0.050)
CLICK_COOL    = 0.45       # minimum seconds between clicks (fallback)

# Scroll (index 8 + middle 12 raised, hand moves vertically)
SCROLL_DEAD   = 0.012      # normalised vertical delta below which we ignore
SCROLL_SCALE  = 15         # multiplier → pyautogui scroll units
SCROLL_COOL   = 0.08       # seconds between scroll ticks

# Volume control (Index + Middle + Ring up, hand moves vertically)
VOLUME_DEAD   = 0.012      # normalised vertical delta below which we ignore
VOLUME_COOL   = 0.15       # seconds between volume keystrokes

# Frame rate — gesture thread sleeps to this interval
FRAME_INTERVAL = 1.0 / 30  # 30 fps for smoother tracking

# ─── Iron Man Layer 2/3/4 ─ State Machine + Spatial Mapper + Drag ────────────

@dataclass
class GestureFrame:
    """Snapshot of one hand's state emitted by GestureStateMachine."""
    gesture: str          # open_palm / fist / point / pinch / two_finger / thumbs_down / unknown
    hold_time: float      # seconds the same gesture has been held continuously
    velocity: tuple       # (vx, vy) — normalised frame-to-frame palm delta, averaged over 5 frames
    palm_center: tuple    # (px, py) — normalised 0-1, middle-MCP (landmark 9) proxy
    fingers: list         # [thumb, index, middle, ring, pinky] — bool
    lm: object = None     # raw MediaPipe landmark list (for special checks)


@dataclass
class ARIACommand:
    """High-level ARIA action emitted by SpatialCommandMapper."""
    action: str
    direction: str = ""
    x: int = 0
    y: int = 0


# Velocity threshold (normalised units/frame) to trigger a swipe command.
# 0.12 is deliberate — higher than 0.08 to avoid false triggers from
# ordinary cursor-range hand movement.
SWIPE_VEL_THRESHOLD = 0.12


class GestureStateMachine:
    """
    Layer 2 — converts raw MediaPipe landmarks into a named GestureFrame.

    Tracks:
      - current gesture name (classified from finger state + pinch distance)
      - hold time (seconds the same gesture has been held without changing)
      - palm velocity (rolling 5-frame average of palm-center displacement)
    """

    def __init__(self):
        self.current_gesture = "unknown"
        self.gesture_start_time = time.time()
        self.prev_palm_center = None
        self.velocity_buffer = deque(maxlen=5)

    # ── Classifier ────────────────────────────────────────────────────────────

    def _classify(self, lm, fingers: list) -> str:
        """
        Priority order:
          1. pinch   (index tip + thumb tip distance < 0.055)
          2. thumbs_down  (4 fingers folded, thumb pointing DOWN)
          3. open_palm    (all 4 fingers extended)
          4. fist         (all 4 fingers curled, thumb not down)
          5. point        (index only)
          6. two_finger   (index + middle only)
          7. unknown
        """
        # 1. Pinch — takes highest priority
        if _dist(lm[4], lm[8]) < 0.055:
            return "pinch"

        f = fingers  # [thumb, index, middle, ring, pinky]

        # 2 / 4. All four fingers curled (fist or thumbs_down)
        if not f[1] and not f[2] and not f[3] and not f[4]:
            palm_len = _dist(lm[0], lm[9])
            if palm_len > 0:
                four_folded = (
                    lm[8].y > lm[6].y and lm[12].y > lm[10].y and
                    lm[16].y > lm[14].y and lm[20].y > lm[18].y
                )
                if (four_folded and lm[4].y > lm[3].y and
                        _dist(lm[4], lm[9]) > palm_len * 1.2):
                    return "thumbs_down"
            return "fist"

        # 3. Open palm — all four fingers up
        if f[1] and f[2] and f[3] and f[4]:
            return "open_palm"

        # 5. Point — index only
        if f[1] and not f[2] and not f[3] and not f[4]:
            return "point"

        # 6. Two-finger scroll pose
        if f[1] and f[2] and not f[3] and not f[4]:
            return "two_finger"

        return "unknown"

    # ── Palm centre (stable landmark) ─────────────────────────────────────────

    @staticmethod
    def _get_palm_center(lm) -> tuple:
        """Middle MCP (landmark 9) — stable, minimally affected by finger extension."""
        return (lm[9].x, lm[9].y)

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, lm) -> GestureFrame:
        fingers = _fingers_up(lm)
        gesture = self._classify(lm, fingers)
        palm_center = self._get_palm_center(lm)

        # Rolling velocity — palm displacement per tick
        if self.prev_palm_center is not None:
            dx = palm_center[0] - self.prev_palm_center[0]
            dy = palm_center[1] - self.prev_palm_center[1]
            self.velocity_buffer.append((dx, dy))
        self.prev_palm_center = palm_center

        # Hold time — resets to 0 whenever the classified gesture changes
        if gesture == self.current_gesture:
            hold_time = time.time() - self.gesture_start_time
        else:
            self.current_gesture = gesture
            self.gesture_start_time = time.time()
            hold_time = 0.0

        n = max(len(self.velocity_buffer), 1)
        avg_vx = sum(v[0] for v in self.velocity_buffer) / n
        avg_vy = sum(v[1] for v in self.velocity_buffer) / n

        return GestureFrame(
            gesture=gesture,
            hold_time=hold_time,
            velocity=(avg_vx, avg_vy),
            palm_center=palm_center,
            fingers=fingers,
            lm=lm,
        )

    def reset(self):
        self.current_gesture = "unknown"
        self.gesture_start_time = time.time()
        self.prev_palm_center = None
        self.velocity_buffer.clear()


class SpatialCommandMapper:
    """
    Layer 3 — translates a GestureFrame into an ARIACommand.

    Design principles:
      - Velocity-based intent: slow hand ≠ command, fast flick = command.
      - Hold-time confirmation: prevents accidental triggers.
      - Pinch-engage gate: cursor only moves while pinch is held (≥ 0.18 s);
        a quick tap (< 0.18 s) fires a click instead.
      - Gesture isolation: open_palm wake (≥ 0.8 s) and swipe (< 0.5 s)
        do not overlap — no ghost wake during swipe.
      - thumbs_down → stop speaking (separate from open_palm entirely).
    """

    def __init__(self):
        # Pinch-engage mode
        self._pinch_start: float | None = None
        self._engage = False          # True while pinch held ≥ 0.18s

        # Single-fire guards (prevent re-triggering within same gesture hold)
        self._wake_armed = False
        self._stop_armed = False

        # Throw machine
        self._throw_primed = False
        self._throw_prime_time = 0.0

        # Cooldowns
        self._last_swipe_time = 0.0
        self._swipe_cool = 0.8        # min seconds between tab switches
        self._last_scroll_time = 0.0
        self._scroll_cool = 0.12

    def process(self, frame: GestureFrame) -> "ARIACommand | None":
        g = frame.gesture
        vx, vy = frame.velocity
        hold = frame.hold_time
        now = time.time()
        speed = math.sqrt(vx ** 2 + vy ** 2)

        # ── PINCH: engage cursor mode ─────────────────────────────────────────
        # Sustained pinch (≥ 0.18 s) → engage cursor, hand tracks screen.
        # Quick tap (< 0.18 s release) → left click.
        if g == "pinch":
            if self._pinch_start is None:
                self._pinch_start = now
            pinch_hold = now - self._pinch_start
            if pinch_hold >= 0.18:
                self._engage = True
                return ARIACommand(action="move_cursor")
            return None   # still within tap window — wait
        else:
            if self._pinch_start is not None:
                pinch_hold = now - self._pinch_start
                self._pinch_start = None
                if pinch_hold < 0.18 and not self._engage:
                    self._engage = False
                    return ARIACommand(action="mouse_click")
            self._engage = False

        # ── THUMBS DOWN: stop speaking ────────────────────────────────────────
        # Clearly separated from open-palm — no ambiguity.
        if g == "thumbs_down":
            if not self._stop_armed and hold >= 0.25:
                self._stop_armed = True
                return ARIACommand(action="stop_speaking")
        else:
            self._stop_armed = False

        # ── OPEN PALM: throw (if primed) then wake (static) then swipe (fast) ──
        if g == "open_palm":
            # Throw check takes HIGHEST priority inside open_palm.
            # If throw is primed, this frame is either a throw or a no-op —
            # we never let a coincidental swipe fire while the user is flicking.
            if self._throw_primed:
                if now - self._throw_prime_time < 1.2:
                    if speed > 0.10:
                        self._throw_primed = False
                        direction = "right" if vx > 0 else "left"
                        return ARIACommand(action="throw_window", direction=direction)
                    # Primed but not fast enough yet — keep waiting
                    return None
                else:
                    # Prime expired without a flick — clear it and swallow this
                    # open-palm frame so the user's "give up" motion isn't
                    # misread as a tab swipe.
                    self._throw_primed = False
                    return None

            # Wake: static hold >= 0.8s — speed must be below swipe threshold
            # so a swipe-that-slows-down never double-fires as wake.
            if hold >= 0.8 and speed < SWIPE_VEL_THRESHOLD:
                if not self._wake_armed:
                    self._wake_armed = True
                    return ARIACommand(action="wake_aria")
            else:
                self._wake_armed = False

            # Swipe tab: fast lateral motion, hold < 0.5s
            # (long holds are wake candidates, not swipes)
            if hold < 0.5 and now - self._last_swipe_time > self._swipe_cool:
                if vx > SWIPE_VEL_THRESHOLD:
                    self._last_swipe_time = now
                    return ARIACommand(action="switch_tab", direction="right")
                if vx < -SWIPE_VEL_THRESHOLD:
                    self._last_swipe_time = now
                    return ARIACommand(action="switch_tab", direction="left")

            # Vertical scroll via open palm
            if now - self._last_scroll_time > self._scroll_cool:
                if vy < -SWIPE_VEL_THRESHOLD:
                    self._last_scroll_time = now
                    return ARIACommand(action="scroll", direction="up")
                if vy > SWIPE_VEL_THRESHOLD:
                    self._last_scroll_time = now
                    return ARIACommand(action="scroll", direction="down")

        else:
            self._wake_armed = False

        # ── FIST: prime window throw ──────────────────────────────────────────
        if g == "fist":
            if hold >= 0.5:
                self._throw_primed = True
                self._throw_prime_time = now
            return None   # fist itself fires no command

        # Expire stale throw prime
        if g not in ("fist", "open_palm") and now - self._throw_prime_time > 1.2:
            self._throw_primed = False

        return None

    def reset(self):
        self._pinch_start = None
        self._engage = False
        self._wake_armed = False
        self._stop_armed = False
        self._throw_primed = False
        self._last_swipe_time = 0.0
        self._last_scroll_time = 0.0


class GestureDragMachine:
    """
    Layer 4 — 4-state drag: IDLE → GRABBING → DRAGGING → IDLE.

    Activation guard: only arms when fist is formed in the tab-bar zone
    (top TAB_BAR_Y_MAX of the normalised frame). Closing your fist anywhere
    else does NOT trigger a drag — preventing accidental tab moves.

    Timeline:
        fist appears in tab zone   → GRABBING
        fist held ≥ 0.4 s          → DRAGGING (mouseDown fires)
        fist released               → IDLE     (mouseUp fires)
        non-fist before 0.4 s      → cancel back to IDLE
    """

    GRAB_CONFIRM_TIME = 0.40   # seconds of fist hold before mouseDown fires
    TAB_BAR_Y_MAX     = 0.08   # top 8% of normalised frame ≈ browser tab bar

    def __init__(self, screen_w: int, screen_h: int):
        self._state = "IDLE"           # IDLE | GRABBING | DRAGGING
        self._grab_start_time = 0.0
        self._grab_start_pos: tuple = (0, 0)
        self._sw = screen_w
        self._sh = screen_h

    def update(self, frame: GestureFrame) -> None:
        """Execute mouse side-effects; called every frame from _process."""
        g = frame.gesture
        px, py = frame.palm_center
        sx = int(px * self._sw)
        sy = int(py * self._sh)
        now = time.time()

        if self._state == "IDLE":
            if g == "fist" and py < self.TAB_BAR_Y_MAX:
                self._state = "GRABBING"
                self._grab_start_time = now
                self._grab_start_pos = (sx, sy)
                print(f"[GestureDrag] Grab intent at ({sx},{sy}) — tab-bar zone")

        elif self._state == "GRABBING":
            if g != "fist":
                self._state = "IDLE"
                print("[GestureDrag] Grab cancelled — fist released before confirm")
                return
            if now - self._grab_start_time >= self.GRAB_CONFIRM_TIME:
                self._state = "DRAGGING"
                gx, gy = self._grab_start_pos
                pyautogui.mouseDown(gx, gy, _pause=False)
                print(f"[GestureDrag] Drag confirmed — mouseDown at ({gx},{gy})")

        elif self._state == "DRAGGING":
            if g == "fist":
                pyautogui.moveTo(sx, sy, _pause=False)
            else:
                # Any non-fist gesture = release
                pyautogui.mouseUp(_pause=False)
                self._state = "IDLE"
                print(f"[GestureDrag] Drag released — mouseUp at ({sx},{sy})")

    def abort(self):
        """Immediately release mouse if dragging (hand loss / shutdown)."""
        if self._state == "DRAGGING":
            try:
                pyautogui.mouseUp(_pause=False)
            except Exception:
                pass
            print("[GestureDrag] Drag aborted — mouseUp (forced)")
        self._state = "IDLE"


# ─── Model auto-download ──────────────────────────────────────────────────────

def _ensure_model() -> bool:
    """Download hand_landmarker.task if not already present. Returns success."""
    os.makedirs(_MODEL_DIR, exist_ok=True)
    if os.path.exists(_MODEL_PATH):
        return True
    print("[GestureControl] Downloading hand_landmarker.task (~7.5 MB)...")
    try:
        urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
        print(f"[GestureControl] Model saved: {_MODEL_PATH}")
        return True
    except Exception as e:
        print(f"[GestureControl] Model download failed: {e}")
        return False

# ─── Landmark helpers ─────────────────────────────────────────────────────────

def _dist(a, b) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)


def _fingers_up(lm) -> list[bool]:
    """
    Returns [thumb, index, middle, ring, pinky].
    lm = list of NormalizedLandmark (x, y, z in [0,1]).
    """
    thumb = lm[4].y < lm[3].y or lm[4].x < lm[3].x   # up or laterally extended
    return [
        thumb,
        lm[8].y  < lm[6].y,    # index
        lm[12].y < lm[10].y,   # middle
        lm[16].y < lm[14].y,   # ring
        lm[20].y < lm[18].y,   # pinky
    ]


# ─── Gesture Controller ───────────────────────────────────────────────────────

class GestureController:
    """
    Processes hand landmarks from a shared camera stream and issues
    PyAutoGUI mouse actions.

    Parameters
    ----------
    frame_provider : callable() → np.ndarray | None
        Called each tick; should return a BGR frame from the shared webcam,
        or None if the camera is temporarily busy / unavailable.
    """

    def __init__(self, frame_provider, callback=None):
        if not MEDIAPIPE_AVAILABLE:
            raise RuntimeError("mediapipe is not installed.")
        self._frame_provider = frame_provider
        self._callback       = callback
        self._running        = False
        self._thread         = None
        
        # High-level gesture states
        self._wave_cooldown = 0.0
        self._confirm_cooldown = 0.0
        self._cancel_cooldown = 0.0
        self._x_history = []

        # Cursor EMA state
        self._sx: float | None = None
        self._sy: float | None = None

        # Pinch click and drag states
        self._is_pinched  = False
        self._is_right_pinched = False
        self._is_double_pinched = False
        self._is_drag_pinched = False
        self._is_dragging = False

        # Timing
        self._last_click  = 0.0
        self._last_scroll = 0.0
        self._last_vol = 0.0

        # Gesture references
        self._prev_mid_y: float | None = None
        self._prev_vol_y: float | None = None

        # Latest landmarks from async MP callback (written in callback, read in loop)
        self._latest_lm   = None
        self._lm_lock     = threading.Lock()

        # FPS tracking
        self._fps_frames = 0
        self._fps_t0     = 0.0

        self._sw, self._sh = pyautogui.size()

        # ── Iron Man Layers 2/3/4 ─────────────────────────────────────────────
        self._state_machine  = GestureStateMachine()
        self._spatial_mapper = SpatialCommandMapper()
        self._drag_machine   = GestureDragMachine(screen_w=self._sw, screen_h=self._sh)

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="GestureControl"
        )
        self._thread.start()
        print("[GestureControl] Thread started.")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        print("[GestureControl] Thread stopped.")

    # ── MediaPipe async callback ───────────────────────────────────────────────

    def _on_result(self, result, _output_image, _timestamp_ms):
        hands_count = len(result.hand_landmarks) if result.hand_landmarks else 0
        if not hasattr(self, '_last_hands_count'):
            self._last_hands_count = -1
        if hands_count != self._last_hands_count:
            print(f"[GestureControl] Hand detection state: {hands_count} hand(s) detected.")
            self._last_hands_count = hands_count

        lm = result.hand_landmarks[0] if result.hand_landmarks else None
        with self._lm_lock:
            self._latest_lm = lm

    # ── Per-frame processing ──────────────────────────────────────────────────

    def _move_cursor(self, lm):
        """
        Map index fingertip (landmark 8) → screen coordinates using active zone,
        and apply dynamic cursor acceleration (variable smoothing based on speed).
        """
        print(f"[GestureControl] Moving cursor. Index finger: x={lm[8].x:.4f}, y={lm[8].y:.4f}")
        # Clamp to the active tracking zone
        clamped_x = max(ACTIVE_X_MIN, min(ACTIVE_X_MAX, lm[8].x))
        clamped_y = max(ACTIVE_Y_MIN, min(ACTIVE_Y_MAX, lm[8].y))

        # Normalize to [0, 1] range within active zone
        norm_x = (clamped_x - ACTIVE_X_MIN) / (ACTIVE_X_MAX - ACTIVE_X_MIN)
        norm_y = (clamped_y - ACTIVE_Y_MIN) / (ACTIVE_Y_MAX - ACTIVE_Y_MIN)

        # Scale to screen dimensions
        raw_x = norm_x * self._sw
        raw_y = norm_y * self._sh

        if self._sx is None:
            self._sx, self._sy = raw_x, raw_y
            alpha = MAX_ALPHA
        else:
            # Calculate distance (velocity proxy) from the last smoothed position
            dist = math.sqrt((raw_x - self._sx) ** 2 + (raw_y - self._sy) ** 2)

            # Linear interpolation of alpha based on travel distance:
            # Slow (< 10px) = high smoothing (alpha=0.15)
            # Fast (> 150px) = low smoothing (alpha=0.80)
            if dist < 10.0:
                alpha = MIN_ALPHA
            elif dist > 150.0:
                alpha = MAX_ALPHA
            else:
                alpha = MIN_ALPHA + (MAX_ALPHA - MIN_ALPHA) * ((dist - 10.0) / 140.0)

        # Apply dynamic smoothing (EMA)
        self._sx = alpha * raw_x + (1 - alpha) * self._sx
        self._sy = alpha * raw_y + (1 - alpha) * self._sy

        tx, ty = int(self._sx), int(self._sy)
        cx, cy = pyautogui.position()
        if abs(tx - cx) > DEADZONE_PX or abs(ty - cy) > DEADZONE_PX:
            pyautogui.moveTo(tx, ty, _pause=False)

    def _check_click(self, lm, fingers, now):
        """Index + thumb pinch → left click (using release-state tracking for debouncing)."""
        if not fingers[1]:           # index must be up
            self._is_pinched = False
            return

        current_dist = _dist(lm[4], lm[8])

        if current_dist < PINCH_THRESH:
            if not self._is_pinched and (now - self._last_click > CLICK_COOL):
                pyautogui.click(_pause=False)
                self._is_pinched = True
                self._last_click = now
                print(f"[GestureControl] [click] Left click (pinch detected, dist: {current_dist:.4f})")
        elif current_dist > PINCH_RELEASE_THRESH:
            if self._is_pinched:
                self._is_pinched = False
                print(f"[GestureControl] [click] Pinch released (dist: {current_dist:.4f})")

    def _check_right_click(self, lm, fingers, now):
        """Middle + thumb pinch → right click."""
        if not fingers[2]:           # middle must be up
            self._is_right_pinched = False
            return

        current_dist = _dist(lm[4], lm[12])

        if current_dist < PINCH_THRESH:
            if not self._is_right_pinched and (now - self._last_click > CLICK_COOL):
                pyautogui.rightClick(_pause=False)
                self._is_right_pinched = True
                self._last_click = now
                print(f"[GestureControl] [click] Right click (pinch detected, dist: {current_dist:.4f})")
        elif current_dist > PINCH_RELEASE_THRESH:
            if self._is_right_pinched:
                self._is_right_pinched = False
                print(f"[GestureControl] [click] Right pinch released (dist: {current_dist:.4f})")

    def _check_double_click(self, lm, fingers, now):
        """Pinky + thumb pinch → double click."""
        if not fingers[4]:           # pinky must be up
            self._is_double_pinched = False
            return

        current_dist = _dist(lm[4], lm[20])

        if current_dist < PINCH_THRESH:
            if not self._is_double_pinched and (now - self._last_click > CLICK_COOL):
                pyautogui.doubleClick(_pause=False)
                self._is_double_pinched = True
                self._last_click = now
                print(f"[GestureControl] [click] Double click (pinch detected, dist: {current_dist:.4f})")
        elif current_dist > PINCH_RELEASE_THRESH:
            if self._is_double_pinched:
                self._is_double_pinched = False
                print(f"[GestureControl] [click] Double pinch released (dist: {current_dist:.4f})")

    def _check_drag_and_drop(self, lm, fingers, now):
        """Ring + thumb pinch → mouse hold/drag, release → mouse up."""
        if not fingers[3]:           # ring must be up
            if self._is_dragging:
                pyautogui.mouseUp(_pause=False)
                self._is_dragging = False
                print("[GestureControl] [drag] Drag released (ring finger went down)")
            self._is_drag_pinched = False
            return

        current_dist = _dist(lm[4], lm[16])

        if current_dist < PINCH_THRESH:
            if not self._is_drag_pinched:
                pyautogui.mouseDown(_pause=False)
                self._is_drag_pinched = True
                self._is_dragging = True
                print(f"[GestureControl] [drag] Drag started / mouse down (dist: {current_dist:.4f})")
        elif current_dist > PINCH_RELEASE_THRESH:
            if self._is_drag_pinched:
                pyautogui.mouseUp(_pause=False)
                self._is_drag_pinched = False
                self._is_dragging = False
                print(f"[GestureControl] [drag] Drag released / mouse up (dist: {current_dist:.4f})")

    def _check_scroll(self, lm, fingers, now):
        """Index + middle up, ring + pinky down → vertical scroll."""
        if fingers[1] and fingers[2] and not fingers[3] and not fingers[4]:
            mid_y = lm[12].y
            if self._prev_mid_y is not None and now - self._last_scroll > SCROLL_COOL:
                delta = self._prev_mid_y - mid_y    # + = hand moved up
                if abs(delta) > SCROLL_DEAD:
                    pyautogui.scroll(int(delta * SCROLL_SCALE), _pause=False)
                    self._last_scroll = now
            self._prev_mid_y = mid_y
        else:
            self._prev_mid_y = None

    def _check_volume(self, lm, fingers, now):
        """Index + Middle + Ring up, Pinky down → hand moves vertically to control volume."""
        if fingers[1] and fingers[2] and fingers[3] and not fingers[4]:
            mid_y = lm[12].y
            if self._prev_vol_y is not None and now - self._last_vol > VOLUME_COOL:
                delta = self._prev_vol_y - mid_y
                if abs(delta) > VOLUME_DEAD:
                    if delta > 0:
                        pyautogui.press('volumeup', _pause=False)
                        print("[GestureControl] [volume] Volume Up")
                    else:
                        pyautogui.press('volumedown', _pause=False)
                        print("[GestureControl] [volume] Volume Down")
                    self._last_vol = now
            self._prev_vol_y = mid_y
        else:
            self._prev_vol_y = None

    def _check_high_level_events(self, lm, fingers, now) -> bool:
        # Distance-based folding checks
        palm_len = _dist(lm[0], lm[9])
        if palm_len == 0:
            return False
            
        index_dist = _dist(lm[8], lm[9])
        middle_dist = _dist(lm[12], lm[9])
        ring_dist = _dist(lm[16], lm[9])
        pinky_dist = _dist(lm[20], lm[9])
        
        # Folded state definition: tips are close to the middle MCP (palm center)
        fingers_folded = (index_dist < palm_len * 1.1 and 
                          middle_dist < palm_len * 1.1 and 
                          ring_dist < palm_len * 1.1 and 
                          pinky_dist < palm_len * 1.1)
                          
        # 1. Thumbs Up (GESTURE_CONFIRM)
        if fingers_folded and fingers[0] and lm[4].y < lm[2].y:
            if _dist(lm[4], lm[9]) > palm_len * 1.2:
                if now - self._confirm_cooldown > 2.0:
                    print("[GestureControl] Thumbs Up detected (Confirm)")
                    self._confirm_cooldown = now
                    if self._callback:
                        self._callback("GESTURE_CONFIRM")
                return True
                
        # 2. Thumbs Down (GESTURE_CANCEL)
        if fingers_folded and lm[4].y > lm[2].y:
            if _dist(lm[4], lm[9]) > palm_len * 1.2:
                if now - self._cancel_cooldown > 2.0:
                    print("[GestureControl] Thumbs Down detected (Cancel)")
                    self._cancel_cooldown = now
                    if self._callback:
                        self._callback("GESTURE_CANCEL")
                return True

        # 3. Horizontal Wave Detection (GESTURE_WAKE)
        self._x_history.append(lm[9].x)
        if len(self._x_history) > 25:
            self._x_history.pop(0)

        # Check for wave gesture: all fingers open (index, middle, ring, pinky)
        if fingers[1] and fingers[2] and fingers[3] and fingers[4]:
            if len(self._x_history) >= 15:
                deltas = []
                for i in range(1, len(self._x_history)):
                    d = self._x_history[i] - self._x_history[i-1]
                    if abs(d) > 0.002:
                        deltas.append(d)
                
                sign_changes = 0
                prev_sign = None
                for d in deltas:
                    sign = 1 if d > 0 else -1
                    if prev_sign is not None and sign != prev_sign:
                        sign_changes += 1
                    prev_sign = sign
                
                total_abs_movement = sum(abs(d) for d in deltas)
                if sign_changes >= 3 and total_abs_movement > 0.12:
                    if now - self._wave_cooldown > 3.0:
                        print(f"[GestureControl] Wave detected! Sign changes: {sign_changes}, movement: {total_abs_movement:.3f}")
                        self._wave_cooldown = now
                        self._x_history.clear()
                        if self._callback:
                            self._callback("GESTURE_WAKE")
                    return True
                    
        return False

    def _move_cursor_palm(self, lm, pt=None):
        """
        Cursor tracking used during pinch-engage mode.
        Tracks palm center (lm[9]) or the supplied normalised (pt) coordinate,
        with the same dynamic EMA smoothing as _move_cursor.
        """
        raw_x_n, raw_y_n = pt if pt is not None else (lm[9].x, lm[9].y)

        # Clamp to active zone (reuse same constants for consistency)
        clamped_x = max(ACTIVE_X_MIN, min(ACTIVE_X_MAX, raw_x_n))
        clamped_y = max(ACTIVE_Y_MIN, min(ACTIVE_Y_MAX, raw_y_n))
        norm_x = (clamped_x - ACTIVE_X_MIN) / (ACTIVE_X_MAX - ACTIVE_X_MIN)
        norm_y = (clamped_y - ACTIVE_Y_MIN) / (ACTIVE_Y_MAX - ACTIVE_Y_MIN)
        raw_x = norm_x * self._sw
        raw_y = norm_y * self._sh

        if self._sx is None:
            self._sx, self._sy = raw_x, raw_y
        else:
            dist = math.sqrt((raw_x - self._sx) ** 2 + (raw_y - self._sy) ** 2)
            if dist < 10.0:
                alpha = MIN_ALPHA
            elif dist > 150.0:
                alpha = MAX_ALPHA
            else:
                alpha = MIN_ALPHA + (MAX_ALPHA - MIN_ALPHA) * ((dist - 10.0) / 140.0)
            self._sx = alpha * raw_x + (1 - alpha) * self._sx
            self._sy = alpha * raw_y + (1 - alpha) * self._sy

        tx, ty = int(self._sx), int(self._sy)
        cx, cy = pyautogui.position()
        if abs(tx - cx) > DEADZONE_PX or abs(ty - cy) > DEADZONE_PX:
            pyautogui.moveTo(tx, ty, _pause=False)

    def _execute(self, command: ARIACommand, frame: GestureFrame) -> None:
        """Dispatch an ARIACommand to the appropriate system action."""
        action = command.action

        if action == "move_cursor":
            # Cursor tracks palm center while pinch is held
            self._move_cursor_palm(frame.lm, pt=frame.palm_center)

        elif action == "mouse_click":
            now = time.time()
            if now - self._last_click > CLICK_COOL:
                pyautogui.click(_pause=False)
                self._last_click = now
                print("[GestureControl] [Iron Man] Left click (quick pinch tap)")

        elif action == "wake_aria":
            print("[GestureControl] [Iron Man] GESTURE_WAKE — open palm hold")
            if self._callback:
                self._callback("GESTURE_WAKE")

        elif action == "stop_speaking":
            print("[GestureControl] [Iron Man] GESTURE_STOP — thumbs down")
            if self._callback:
                self._callback("GESTURE_STOP")

        elif action == "switch_tab":
            key = "ctrl+tab" if command.direction == "right" else "ctrl+shift+tab"
            pyautogui.hotkey(*key.split("+"), _pause=False)
            print(f"[GestureControl] [Iron Man] Switch tab {command.direction}")

        elif action == "scroll":
            amount = -3 if command.direction == "up" else 3
            pyautogui.scroll(amount, _pause=False)

        elif action == "throw_window":
            arrow = "right" if command.direction == "right" else "left"
            pyautogui.hotkey("win", "shift", arrow, _pause=False)
            print(f"[GestureControl] [Iron Man] Throw window {command.direction}")

    def _process(self, lm):
        """
        Iron Man 3-layer gesture pipeline:
          lm → GestureStateMachine → GestureFrame
             → SpatialCommandMapper → ARIACommand
             → _execute()  (fires system action)
          GestureDragMachine runs in parallel for tab-zone drag/drop.

        Legacy high-level events (wave, thumbs-up confirm) are still checked
        first so existing voice-email confirm / cancel gestures keep working.
        """
        fingers = _fingers_up(lm)
        now = time.time()

        # ── Legacy high-level events (wave / thumbs-up confirm) ───────────────
        # These take priority so existing callback wiring is not broken.
        if self._check_high_level_events(lm, fingers, now):
            # Reset Iron Man layers on high-level trigger to avoid ghost state
            self._state_machine.reset()
            self._spatial_mapper.reset()
            return

        # ── Layer 2: classify gesture + compute hold/velocity ─────────────────
        frame = self._state_machine.update(lm)

        # ── Layer 3: map to command ───────────────────────────────────────────
        command = self._spatial_mapper.process(frame)
        if command:
            self._execute(command, frame)

        # ── Layer 4: drag machine (parallel, side-effect only) ────────────────
        self._drag_machine.update(frame)

    def _reset_state(self):
        """Reset all state when hand leaves the camera frame."""
        # Legacy cursor / click / scroll state
        self._sx = self._sy = None
        self._prev_mid_y = None
        self._prev_vol_y = None
        self._is_pinched = False
        self._is_right_pinched = False
        self._is_double_pinched = False
        self._is_drag_pinched = False
        if self._is_dragging:
            pyautogui.mouseUp(_pause=False)
            self._is_dragging = False
            print("[GestureControl] [drag] Drag released automatically (hand left frame)")
        # Iron Man layer reset
        self._state_machine.reset()
        self._spatial_mapper.reset()
        self._drag_machine.abort()

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _run(self):
        if not _ensure_model():
            print("[GestureControl] Cannot start — model file unavailable.")
            self._running = False
            return

        base_opts = _mp_python.BaseOptions(model_asset_path=_MODEL_PATH)
        options   = _mp_vision.HandLandmarkerOptions(
            base_options               = base_opts,
            running_mode               = _mp_vision.RunningMode.LIVE_STREAM,
            num_hands                  = 1,
            min_hand_detection_confidence = 0.70,
            min_hand_presence_confidence  = 0.60,
            min_tracking_confidence       = 0.60,
            result_callback            = self._on_result,
        )

        try:
            with _mp_vision.HandLandmarker.create_from_options(options) as landmarker:
                print("[GestureControl] HandLandmarker ready — sharing camera stream.")
                ts = 0  # monotonically increasing timestamp for MediaPipe

                while self._running:
                    t0 = time.time()

                    # ── Get frame from shared camera ──────────────────────────
                    frame = self._frame_provider()

                    if frame is None:
                        # Camera temporarily busy — back off briefly
                        time.sleep(0.05)
                        continue

                    # ── Feed to MediaPipe ─────────────────────────────────────
                    flipped = cv2.flip(frame, 1)            # mirror
                    rgb     = cv2.cvtColor(flipped, cv2.COLOR_BGR2RGB)
                    mp_img  = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    
                    # MediaPipe LIVE_STREAM mode requires monotonically increasing millisecond timestamps
                    current_ts = int(time.time() * 1000)
                    if current_ts <= ts:
                        current_ts = ts + 1
                    ts = current_ts
                    
                    landmarker.detect_async(mp_img, ts)

                    # ── Process latest result ─────────────────────────────────
                    with self._lm_lock:
                        lm = self._latest_lm

                    if lm is not None:
                        try:
                            self._process(lm)
                        except Exception as e:
                            print(f"[GestureControl] Processing error: {e}")
                    else:
                        self._reset_state()

                    # ── Throttle to ~20 fps ───────────────────────────────────
                    elapsed = time.time() - t0
                    sleep   = FRAME_INTERVAL - elapsed
                    if sleep > 0:
                        time.sleep(sleep)

                    # ── FPS counter (logs every 5 s) ──────────────────────────
                    self._fps_frames += 1
                    now_t = time.time()
                    if now_t - self._fps_t0 >= 5.0:
                        if self._fps_t0 > 0:
                            fps = self._fps_frames / (now_t - self._fps_t0)
                            print(f"[GestureControl] FPS: {fps:.1f}")
                        self._fps_frames = 0
                        self._fps_t0     = now_t

        except Exception as e:
            print(f"[GestureControl] Fatal error in run loop: {e}")
        finally:
            self._running = False
            print("[GestureControl] Loop exited.")


# ─── Module-level singleton ───────────────────────────────────────────────────

_controller: GestureController | None = None
_ctrl_lock = threading.Lock()


def is_active() -> bool:
    return _controller is not None and _controller._running


def start_gesture_control(frame_provider, callback=None) -> str:
    """
    Start gesture control using the provided frame_provider callable.
    frame_provider() must return a BGR numpy array or None.

    Typically called as:
        start_gesture_control(aria.camera.capture_frame_raw, callback=aria._gesture_event_callback)
    """
    global _controller
    if not MEDIAPIPE_AVAILABLE:
        return "Gesture control unavailable — mediapipe is not installed."
    with _ctrl_lock:
        if _controller is not None and _controller._running:
            return "Gesture control is already active."
        _controller = GestureController(frame_provider=frame_provider, callback=callback)
        _controller.start()
    return "Gesture control enabled. I can track your hand movements."


def stop_gesture_control() -> str:
    global _controller
    with _ctrl_lock:
        if _controller is None or not _controller._running:
            return "Gesture control is not currently active."
        _controller.stop()
        _controller = None
    return "Gesture control disabled."
