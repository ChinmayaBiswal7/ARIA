"""
ar_3d_mode.py — ARIA Advanced AR Suite
Mode: AR 3D Hologram Viewer
Voice triggers: "enable AR 3D mode", "AR 3D mode"
Model commands: "create a dragon", "create iron man helmet",
                "create earth", "create human heart", "create solar system"
View commands:  "rotate left/right/up/down", "make it bigger/smaller",
                "reset view", "show wireframe", "change color to red/blue/green",
                "explode model", "zoom in/out"

Architecture:
  - vedo 3D library (pip install vedo) for rendering
  - Runs in its own thread with its own window
  - MediaPipe hand landmarks passed in from ar_playground.py
  - Gesture mapper: rotate, zoom, grab, explode
  - Hologram color + wireframe settings
  - Model generator: loads from library OR calls Shap-E for AI generation
"""

import threading
import time
import math
import os
import sys
import numpy as np

# ── Gesture state shared between threads ──────────────────────────────────────
class GestureState:
    def __init__(self):
        self.rotate_x   = 0.0
        self.rotate_y   = 0.0
        self.zoom       = 1.0
        self.grabbed    = False
        self.grab_pos   = (0.0, 0.0)
        self.explode     = False
        self.reset       = False
        self.pinch_dist  = 0.0
        self.hand_visible = False
        self.lock = threading.Lock()

_gesture = GestureState()


# ── Model Library (built-in procedural models) ────────────────────────────────
# Maps keywords → builder function name
MODEL_KEYWORDS = {
    "dragon":        "build_dragon",
    "iron man":      "build_iron_man_helmet",
    "helmet":        "build_iron_man_helmet",
    "earth":         "build_earth",
    "planet":        "build_earth",
    "heart":         "build_heart",
    "human heart":   "build_heart",
    "solar system":  "build_solar_system",
    "car":           "build_car",
    "formula":       "build_car",
    "skull":         "build_skull",
    "dna":           "build_dna",
    "crystal":       "build_crystal",
    "robot":         "build_robot",
    "diamond":       "build_diamond",
    "torus":         "build_torus",
}


def match_model(cmd):
    """Return model key from voice command string."""
    cmd_lower = cmd.lower()
    for key in MODEL_KEYWORDS:
        if key in cmd_lower:
            return key
    return None


# ── Hologram color palette ────────────────────────────────────────────────────
HOLO_COLORS = {
    "blue":   (0.1, 0.6, 1.0, 0.85),
    "cyan":   (0.0, 0.9, 1.0, 0.85),
    "green":  (0.1, 1.0, 0.4, 0.85),
    "red":    (1.0, 0.2, 0.2, 0.85),
    "gold":   (1.0, 0.8, 0.1, 0.85),
    "white":  (0.9, 0.9, 1.0, 0.85),
    "purple": (0.7, 0.1, 1.0, 0.85),
}


# ── AR3DMode main class ───────────────────────────────────────────────────────
class AR3DMode:

    def __init__(self, aria_brain=None):
        self._brain       = aria_brain
        self._thread      = None
        self._running     = False
        self._app         = None
        self.label        = "AR 3D"
        self._model_gen   = None

        # Current state
        self._current_model_key = None
        self._holo_color        = "blue"
        self._wireframe         = False
        self._exploded          = False
        self._scale             = 1.0

        # Command queue (thread-safe)
        self._cmd_queue = []
        self._cmd_lock  = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(target=self._run_ursina, daemon=True)
        self._thread.start()
        print("[AR3D] Viewer started.")

    def stop(self):
        self._running = False
        self._queue_cmd("quit")
        # Free any active cloud temp file
        _active_tmp = getattr(self, "_active_tmp_path", None)
        if _active_tmp:
            try:
                from skills.model_cloud_manager import ModelCloudManager
                ModelCloudManager().free_temp(_active_tmp)
            except Exception:
                pass
            self._active_tmp_path = None
        print("[AR3D] Viewer stopped.")


    def load_model(self, model_key):
        """Queue a model load by keyword."""
        self._current_model_key = model_key
        self._queue_cmd(f"load:{model_key}")

    def voice_command(self, cmd):
        """Pass a voice command string for processing."""
        cmd = cmd.lower().strip()

        # Model creation
        key = match_model(cmd)
        if key:
            self.load_model(key)
            return f"Loading {key} model."

        # View commands
        if "rotate left"  in cmd: self._queue_cmd("rotate:y:-3")
        elif "rotate right" in cmd: self._queue_cmd("rotate:y:3")
        elif "rotate up"    in cmd: self._queue_cmd("rotate:x:-3")
        elif "rotate down"  in cmd: self._queue_cmd("rotate:x:3")
        elif "bigger" in cmd or "larger" in cmd or "zoom in" in cmd:
            self._queue_cmd("scale:1.2")
        elif "smaller" in cmd or "zoom out" in cmd:
            self._queue_cmd("scale:0.8")
        elif "reset" in cmd:
            self._queue_cmd("reset")
        elif "wireframe" in cmd:
            self._queue_cmd("wireframe")
        elif "explode" in cmd:
            self._queue_cmd("explode")
        elif "change color" in cmd or "color" in cmd:
            for color in HOLO_COLORS:
                if color in cmd:
                    self._queue_cmd(f"color:{color}")
                    return f"Color changed to {color}."
        return None

    def update_hand(self, hand_landmarks, frame_w, frame_h):
        """
        Called every frame from ar_playground.py with the hand landmark object.
        Updates global gesture state for the Ursina thread to consume.
        """
        if hand_landmarks is None:
            with _gesture.lock:
                _gesture.hand_visible = False
            return

        lms = hand_landmarks.landmark
        w, h = frame_w, frame_h

        def px(idx):
            return lms[idx].x * w, lms[idx].y * h

        index_tip = px(8)
        thumb_tip  = px(4)
        middle_tip = px(12)
        wrist      = px(0)

        # Pinch distance (index + thumb)
        pinch = math.hypot(index_tip[0] - thumb_tip[0],
                           index_tip[1] - thumb_tip[1])
        pinching = pinch < w * 0.07

        # Two-finger zoom: distance between index and middle fingertip
        two_finger_dist = math.hypot(index_tip[0] - middle_tip[0],
                                     index_tip[1] - middle_tip[1]) / w

        # Fist detection
        tips = [8, 12, 16, 20]
        pips = [6, 10, 14, 18]
        folded = sum(1 for t, p in zip(tips, pips)
                     if lms[t].y > lms[p].y)
        fist = folded >= 3

        # Palm open (all fingers extended)
        extended = sum(1 for t, p in zip(tips, pips)
                       if lms[t].y < lms[p].y)
        palm_open = extended >= 4

        with _gesture.lock:
            _gesture.hand_visible = True
            _gesture.grabbed      = pinching
            _gesture.grab_pos     = (lms[9].x - 0.5, -(lms[9].y - 0.5))
            _gesture.pinch_dist   = two_finger_dist
            _gesture.explode      = fist
            _gesture.reset        = palm_open

    # ── Command Queue ─────────────────────────────────────────────────────────

    def _queue_cmd(self, cmd):
        with self._cmd_lock:
            self._cmd_queue.append(cmd)

    def _pop_cmds(self):
        with self._cmd_lock:
            cmds = self._cmd_queue[:]
            self._cmd_queue.clear()
        return cmds

    # ── Ursina Thread ─────────────────────────────────────────────────────────

    def _run_ursina(self):
        import os
        os.environ["VTK_SILENCE_GET_VOID_POINTER_WARNINGS"] = "1"
        os.environ["VTKWEB_DISABLE_LOGGING"] = "1"

        try:
            import vedo
            from vedo import Plotter, Sphere, load, Assembly
        except ImportError:
            print("[AR3D] vedo not installed. Run: pip install vedo")
            self._running = False
            return

        plt = vedo.Plotter(title="ARIA AR 3D Hologram",
                           bg="black", bg2=(0, 0, 40),
                           size=(900, 700),
                           offscreen=False)
        plt.renderer.SetAmbient((0.3, 0.3, 0.3))
        self._plt = plt

        # Default model (solid sphere + wireframe overlay)
        solid = vedo.Sphere(r=1, c="cyan", alpha=0.6)
        wire = solid.clone().wireframe(True).c("white").alpha(0.15)
        
        assembly = [vedo.Assembly(solid, wire)]
        needs_render = [False]
        
        plt.show(assembly[0], interactive=False, resetcam=True)

        prev_grab_pos = None
        prev_pinch = 0.0
        was_generating = False

        while self._running:
            cmds = self._pop_cmds()
            for cmd in cmds:
                if cmd == "quit":
                    self._running = False
                    break
                elif cmd.startswith("load:"):
                    key = cmd.split(":", 1)[1]

                    # \u2500\u2500 1. Try cloud stream first (no permanent disk use) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
                    obj_path = None
                    _active_tmp = getattr(self, "_active_tmp_path", None)
                    try:
                        from skills.model_cloud_manager import ModelCloudManager
                        mcm = ModelCloudManager()
                        if mcm.is_available(key):
                            tmp = mcm.stream_to_temp(key)
                            if tmp:
                                obj_path = str(tmp)
                                # Free previous temp if there was one
                                if _active_tmp:
                                    mcm.free_temp(_active_tmp)
                                self._active_tmp_path = tmp
                                print(f"[AR3D] Cloud stream ready: {tmp}")
                    except Exception as cloud_err:
                        print(f"[AR3D] Cloud stream skipped: {cloud_err}")

                    # \u2500\u2500 2. Fall back to local assets folder \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
                    if not obj_path:
                        local = os.path.join(
                            os.path.dirname(os.path.abspath(__file__)),
                            "assets", "3d", f"{key}.obj"
                        )
                        if os.path.exists(local):
                            obj_path = local
                            print(f"[AR3D] Loading from local disk: {local}")
                        else:
                            print(f"[AR3D] No local file for '{key}' either \u2014 using procedural sphere.")

                    try:
                        if obj_path:
                            new_mesh = vedo.load(obj_path)
                        else:
                            new_mesh = vedo.Sphere(r=1)
                        new_mesh.compute_normals()
                        new_mesh.lighting("glossy")
                        new_mesh.c("cyan").alpha(0.7)
                        wire = new_mesh.clone()
                        wire.wireframe(True).c("white").alpha(0.15)
                        assembly[0] = vedo.Assembly(new_mesh, wire)
                        plt.clear()
                        plt.add(assembly[0])
                        plt.reset_camera()
                        needs_render[0] = True
                        print(f"[AR3D] Model loaded: {key}")
                    except Exception as e:
                        import traceback; traceback.print_exc()

                elif cmd.startswith("color:"):
                    color_name = cmd.split(":", 1)[1]
                    parts = assembly[0].unpack() if hasattr(assembly[0], "unpack") else [assembly[0]]
                    parts[0].c(color_name)
                    needs_render[0] = True
                elif cmd == "wireframe":
                    parts = assembly[0].unpack() if hasattr(assembly[0], "unpack") else [assembly[0]]
                    solid = parts[0]
                    solid.wireframe(not solid.GetProperty().GetRepresentation())
                    needs_render[0] = True
                elif cmd == "explode":
                    try:
                        parts = assembly[0].unpack() if hasattr(assembly[0], "unpack") else [assembly[0]]
                        solid = parts[0]
                        subparts = solid.splitByConnectivity()
                        if len(subparts) > 1:
                            center = solid.centerOfMass()
                            for m in subparts:
                                part_center = m.centerOfMass()
                                shift = (part_center - center) * 0.3
                                m.shift(shift)
                    except Exception as e:
                        print(f"[AR3D] Explode error: {e}")
                    needs_render[0] = True
                elif cmd == "reset":
                    plt.reset_camera()
                    needs_render[0] = True
                elif cmd.startswith("rotate:"):
                    _, axis, deg = cmd.split(":")
                    if axis == "y":
                        assembly[0].rotate_y(float(deg))
                    elif axis == "x":
                        assembly[0].rotate_x(float(deg))
                    needs_render[0] = True

            # Apply hand gesture rotation & zoom
            with _gesture.lock:
                hand_vis = _gesture.hand_visible
                grabbed  = _gesture.grabbed
                grab_pos = _gesture.grab_pos
                pinch_d  = _gesture.pinch_dist

            # Rotation
            if grabbed and hand_vis and assembly[0]:
                if prev_grab_pos is not None:
                    dx = grab_pos[0] - prev_grab_pos[0]
                    dy = grab_pos[1] - prev_grab_pos[1]
                    assembly[0].rotate_y(dx * 180)
                    assembly[0].rotate_x(-dy * 180)
                    needs_render[0] = True
                prev_grab_pos = grab_pos
            else:
                prev_grab_pos = None

            # Zoom
            if pinch_d > 0 and assembly[0]:
                if prev_pinch > 0:
                    zoom_delta = (pinch_d - prev_pinch) * 5
                    if abs(zoom_delta) > 0.01:
                        assembly[0].scale(1 + zoom_delta)
                        needs_render[0] = True
                prev_pinch = pinch_d
            else:
                prev_pinch = 0.0

            # Draw progress bar when generating
            is_generating = False
            if self._model_gen and self._model_gen._generating:
                is_generating = True
                prog = self._model_gen.progress
                msg  = self._model_gen.progress_msg

                # Coordinates in 3D world space
                bar_y_bottom = -2.8
                bar_y_top    = -2.4
                bar_x_left   = -3.0
                bar_x_right  =  3.0
                fill_x_right = bar_x_left + (6.0 * prog / 100)
                text_y = -2.2

                # Background bar
                bar_bg = vedo.Rectangle(
                    [bar_x_left, bar_y_bottom], [bar_x_right, bar_y_top]
                ).c("gray").alpha(0.3)

                # Filled portion
                bar_fill = vedo.Rectangle(
                    [bar_x_left, bar_y_bottom], [fill_x_right, bar_y_top]
                ).c("cyan").alpha(0.8)

                # Text label
                label = vedo.Text3D(
                    f"{msg}  {prog}%",
                    pos=(bar_x_left, text_y, 0),
                    s=0.15, c="white"
                )

                plt.clear()
                plt.add(bar_bg, bar_fill, label)
                if assembly[0]:
                    plt.add(assembly[0])
                
                plt.reset_camera()
                plt.camera.SetPosition(0, 0, 8)
                plt.camera.SetFocalPoint(0, 0, 0)
                
                needs_render[0] = True
                was_generating = True
            elif was_generating:
                # Generation just finished, clear and restore only the model assembly
                plt.clear()
                if assembly[0]:
                    plt.add(assembly[0])
                plt.reset_camera()
                needs_render[0] = True
                was_generating = False

            if plt.interactor:
                plt.interactor.ProcessEvents()
            
            if needs_render[0]:
                plt.render()
                needs_render[0] = False
            else:
                plt.render()
            time.sleep(0.05)

        plt.close()
        print("[AR3D] vedo window closed.")
