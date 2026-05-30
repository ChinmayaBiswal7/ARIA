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

    def __init__(self, frame_provider):
        if not MEDIAPIPE_AVAILABLE:
            raise RuntimeError("mediapipe is not installed.")
        self._frame_provider = frame_provider
        self._running        = False
        self._thread         = None

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

    def _process(self, lm):
        """Run all gesture checks for one frame's landmarks."""
        fingers = _fingers_up(lm)
        now     = time.time()
        self._move_cursor(lm)
        self._check_click(lm, fingers, now)
        self._check_right_click(lm, fingers, now)
        self._check_double_click(lm, fingers, now)
        self._check_drag_and_drop(lm, fingers, now)
        self._check_scroll(lm, fingers, now)
        self._check_volume(lm, fingers, now)

    def _reset_state(self):
        """Reset smoothing and pinch/drag states when hand leaves frame."""
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
            print("[GestureControl] [drag] Drag released automatically because hand left frame.")

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


def start_gesture_control(frame_provider) -> str:
    """
    Start gesture control using the provided frame_provider callable.
    frame_provider() must return a BGR numpy array or None.

    Typically called as:
        start_gesture_control(aria.camera.capture_frame_raw)
    """
    global _controller
    if not MEDIAPIPE_AVAILABLE:
        return "Gesture control unavailable — mediapipe is not installed."
    with _ctrl_lock:
        if _controller is not None and _controller._running:
            return "Gesture control is already active."
        _controller = GestureController(frame_provider=frame_provider)
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
