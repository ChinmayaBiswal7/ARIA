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
        self.active_gesture = "None"
        self.hand_pos       = (0.5, 0.5)
        self.hand_size      = 0.0
        self.index_tip      = (0.5, 0.5)
        self.hand_visible   = False
        self.candidate_gesture = "None"
        self.candidate_gesture_start_time = 0.0
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
# Hologram colors (RGBA)
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

    @property
    def thread(self):
        return self._thread

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

        # Check action/transform commands first to avoid trigger collisions with model names
        if "move" in cmd:
            if "left" in cmd:
                self._queue_cmd("move:x:-0.3")
                return "Moving model left."
            elif "right" in cmd:
                self._queue_cmd("move:x:0.3")
                return "Moving model right."
            elif "up" in cmd:
                self._queue_cmd("move:y:0.3")
                return "Moving model up."
            elif "down" in cmd:
                self._queue_cmd("move:y:-0.3")
                return "Moving model down."
        
        if "rotate" in cmd:
            if "left" in cmd:
                self._queue_cmd("rotate:y:-15")
                return "Rotating model left."
            elif "right" in cmd:
                self._queue_cmd("rotate:y:15")
                return "Rotating model right."
            elif "up" in cmd:
                self._queue_cmd("rotate:x:-15")
                return "Rotating model up."
            elif "down" in cmd:
                self._queue_cmd("rotate:x:15")
                return "Rotating model down."

        if "bigger" in cmd or "larger" in cmd or "zoom in" in cmd or "scale up" in cmd:
            self._queue_cmd("scale:1.2")
            return "Making model bigger."
        elif "smaller" in cmd or "zoom out" in cmd or "scale down" in cmd:
            self._queue_cmd("scale:0.8")
            return "Making model smaller."

        if "reset" in cmd or "center" in cmd:
            self._queue_cmd("reset")
            return "Resetting model view."

        if "wireframe" in cmd:
            self._queue_cmd("wireframe")
            return "Toggling wireframe mode."

        if "explode" in cmd:
            self._queue_cmd("explode")
            return "Exploding model."

        if "show controls" in cmd or "controls" in cmd:
            self._queue_cmd("show_controls")
            return "Showing controls guide."

        if "change color" in cmd or "color" in cmd:
            for color in HOLO_COLORS:
                if color in cmd:
                    self._queue_cmd(f"color:{color}")
                    return f"Color changed to {color}."

        # Model creation/loading (check last to prevent collision)
        key = match_model(cmd)
        if key:
            self.load_model(key)
            return f"Loading {key} model."

        return None

    def update_hand(self, hand_landmarks, frame_w, frame_h):
        """
        Called every frame from ar_playground.py with the hand landmark object.
        Updates global gesture state for the Ursina thread to consume.
        """
        if hand_landmarks is None:
            with _gesture.lock:
                _gesture.hand_visible = False
                _gesture.active_gesture = "None"
                _gesture.candidate_gesture = "None"
                _gesture.candidate_gesture_start_time = 0.0
            return

        lms = hand_landmarks.landmark

        # Pinch: distance between index tip (8) and thumb tip (4)
        pinch_dist = math.hypot(lms[8].x - lms[4].x, lms[8].y - lms[4].y)
        pinching = pinch_dist < 0.08  # Increased pinch threshold for easier MOVE activation

        raw_gesture = "None"
        if pinching:
            raw_gesture = "MOVE"
        elif lms[8].y < lms[6].y:  # Simplified ROTATE check: index finger is extended (y decreases upwards)
            raw_gesture = "ROTATE"
        else:
            raw_gesture = "RELEASE"

        # Hand size: distance from wrist (0) to middle MCP (9)
        hand_size = math.hypot(lms[9].x - lms[0].x, lms[9].y - lms[0].y)

        # Silent hand logs unless transitions occur
        with _gesture.lock:
            import time
            now = time.time()
            if raw_gesture != _gesture.candidate_gesture:
                _gesture.candidate_gesture = raw_gesture
                _gesture.candidate_gesture_start_time = now
            
            # Check 0.1-second hold for extremely snappy controls
            target_gesture = _gesture.active_gesture
            if now - _gesture.candidate_gesture_start_time >= 0.1:
                target_gesture = _gesture.candidate_gesture

            # Transition logging
            if target_gesture != _gesture.active_gesture:
                print(f"[AR3D] Gesture changed -> {target_gesture}")
                if target_gesture == "MOVE":
                    print("MODEL MOVED")
                elif target_gesture == "ROTATE":
                    print("ROTATE DETECTED")

            _gesture.hand_visible   = True
            _gesture.active_gesture = target_gesture
            _gesture.hand_pos       = (lms[9].x, lms[9].y)
            _gesture.hand_size      = hand_size
            _gesture.index_tip      = (lms[8].x, lms[8].y)

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
        import os, time
        os.environ["VTK_SILENCE_GET_VOID_POINTER_WARNINGS"] = "1"
        os.environ["VTKWEB_DISABLE_LOGGING"] = "1"

        print("[AR3D Profiler] Thread started. Starting imports...")
        t_import = time.time()
        try:
            import vedo
            from vedo import Plotter, Sphere, load, Assembly, Text2D
        except ImportError:
            print("[AR3D] vedo not installed. Run: pip install vedo")
            self._running = False
            return
        print(f"[AR3D Profiler] Imports completed in {time.time() - t_import:.3f}s")

        print("[AR3D Profiler] Creating Plotter...")
        t_plotter = time.time()
        plt = vedo.Plotter(title="ARIA AR 3D Hologram",
                           bg="black", bg2=(0, 0, 40),
                           size=(900, 700),
                           offscreen=False)
        plt.renderer.SetAmbient((0.3, 0.3, 0.3))
        self._plt = plt
        print(f"[AR3D Profiler] Plotter created in {time.time() - t_plotter:.3f}s")

        # Default model (solid sphere + wireframe overlay)
        solid = vedo.Sphere(r=1, c="cyan", alpha=0.6)
        wire = solid.clone().wireframe(True).c("white").alpha(0.15)
        
        assembly = [vedo.Assembly(solid, wire)]
        needs_render = [False]

        # Create overlays
        help_overlay = vedo.Text2D(
            "👌 Pinch = Move  |  ☝️ One Finger = Rotate",
            pos="top-left",
            s=0.9,
            c="cyan",
            font="Courier",
            bg="black",
            alpha=0.8
        )
        gesture_overlay = vedo.Text2D(
            "",
            pos="top-right",
            s=0.9,
            c="white",
            font="Courier",
            bg="black",
            alpha=0.8
        )
        controls_text = (
            "👌 Pinch      = Move\n"
            "☝️ One Finger = Rotate\n"
            "✊ Fist       = Release"
        )
        controls_overlay = vedo.Text2D(
            controls_text,
            pos="bottom-left",
            s=0.9,
            c="gold",
            font="Courier",
            bg="black",
            alpha=0.9
        )
        
        print("[AR3D Profiler] Calling Plotter.show...")
        t_show = time.time()
        plt.show(assembly[0], help_overlay, gesture_overlay, interactive=False, resetcam=True)
        print(f"[AR3D Profiler] Plotter.show completed in {time.time() - t_show:.3f}s")


        prev_hand_pos = None
        prev_hand_size = None
        prev_index_pos = None
        rot_history_y = []
        rot_history_x = []
        was_generating = False
        gesture_display_expiry = 0.0
        controls_display_expiry = 0.0
        last_shown_gesture = "None"

        while self._running:
            cmds = self._pop_cmds()
            for cmd in cmds:
                if cmd == "quit":
                    self._running = False
                    break
                elif cmd.startswith("load:"):
                    key = cmd.split(":", 1)[1]

                    # ── 1. Try cloud stream first (no permanent disk use) ─────────────
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

                    # ── 2. Fall back to local assets folder ───────────────────────────
                    if not obj_path:
                        local = os.path.join(
                            os.path.dirname(os.path.abspath(__file__)),
                            "assets", "3d", f"{key}.obj"
                        )
                        if os.path.exists(local):
                            obj_path = local
                            print(f"[AR3D] Loading from local disk: {local}")
                        else:
                            print(f"[AR3D] No local file for '{key}' either — using procedural sphere.")

                    try:
                        if obj_path:
                            new_mesh = vedo.load(obj_path)
                        else:
                            new_mesh = vedo.Sphere(r=1)

                        # Print original bounds/center as requested by Issue 2
                        b = new_mesh.bounds()
                        center = new_mesh.center_of_mass()
                        print(f"[AR3D] Loaded Model: '{key}' (or fallback)")
                        print(f"[AR3D] original bounds: {b}")
                        print(f"[AR3D] original center: {center}")

                        # Shift to origin to center the model
                        new_mesh.shift(-center)
                        
                        # Normalize scale so maximum dimension is 2.0 (standard visible unit size)
                        dx, dy, dz = b[1] - b[0], b[3] - b[2], b[5] - b[4]
                        max_dim = max(dx, dy, dz)
                        if max_dim > 0:
                            scale_factor = 2.0 / max_dim
                            new_mesh.scale(scale_factor)
                            print(f"[AR3D] Normalized model size. Scaling by: {scale_factor:.4f} (max dim: {max_dim:.4f})")

                        new_mesh.compute_normals()
                        new_mesh.lighting("glossy")
                        new_mesh.c("cyan").alpha(0.7)
                        wire = new_mesh.clone()
                        wire.wireframe(True).c("white").alpha(0.15)
                        assembly[0] = vedo.Assembly(new_mesh, wire)
                        plt.clear()
                        plt.add(assembly[0], help_overlay, gesture_overlay)
                        plt.reset_camera()
                        needs_render[0] = True
                        print(f"[AR3D] Model loaded: {key}")

                        # Force AR3D window to topmost
                        try:
                            import ctypes
                            hwnd = ctypes.windll.user32.FindWindowW(None, "ARIA AR 3D Hologram")
                            if hwnd:
                                # -1 is HWND_TOPMOST, 2 | 1 | 0x0040 is SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
                                ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 2 | 1 | 0x0040)
                                print("[AR3D] Window forced to topmost via Win32 API.")
                        except Exception as win_err:
                            print(f"[AR3D] Could not set window topmost: {win_err}")
                        try:
                            import cv2
                            cv2.setWindowProperty("ARIA AR 3D Hologram", cv2.WND_PROP_TOPMOST, 1)
                        except Exception:
                            pass
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
                            center = solid.center_of_mass()
                            for m in subparts:
                                part_center = m.center_of_mass()
                                shift = (part_center - center) * 0.3
                                m.shift(shift)
                    except Exception as e:
                        print(f"[AR3D] Explode error: {e}")
                    needs_render[0] = True
                elif cmd == "reset":
                    plt.reset_camera()
                    if self._current_model_key:
                        self._queue_cmd(f"load:{self._current_model_key}")
                    needs_render[0] = True
                elif cmd.startswith("rotate:"):
                    _, axis, deg = cmd.split(":")
                    if axis == "y":
                        assembly[0].rotate_y(float(deg))
                    elif axis == "x":
                        assembly[0].rotate_x(float(deg))
                    needs_render[0] = True
                elif cmd.startswith("scale:"):
                    factor = float(cmd.split(":", 1)[1])
                    assembly[0].scale(factor)
                    needs_render[0] = True
                elif cmd.startswith("move:"):
                    _, axis, val = cmd.split(":")
                    shift_val = float(val)
                    if axis == "x":
                        assembly[0].shift([shift_val, 0, 0])
                    elif axis == "y":
                        assembly[0].shift([0, shift_val, 0])
                    elif axis == "z":
                        assembly[0].shift([0, 0, shift_val])
                    needs_render[0] = True
                elif cmd == "show_controls":
                    controls_display_expiry = time.time() + 10.0

            # Apply hand gesture rotation, scale, and movement
            with _gesture.lock:
                hand_vis = _gesture.hand_visible
                active_g = _gesture.active_gesture
                hand_pos = _gesture.hand_pos
                hand_size = _gesture.hand_size
                index_t  = _gesture.index_tip

            current_gesture_name = "None"
            if hand_vis and assembly[0]:
                if active_g == "MOVE":
                    if prev_hand_pos is not None:
                        dx = hand_pos[0] - prev_hand_pos[0]
                        dy = -(hand_pos[1] - prev_hand_pos[1])
                        # Deadzone 0.002 to filter noise but preserve slow movements
                        if abs(dx) > 0.002 or abs(dy) > 0.002:
                            assembly[0].shift([dx * 12.0, dy * 12.0, 0])
                            needs_render[0] = True
                            prev_hand_pos = hand_pos
                    else:
                        prev_hand_pos = hand_pos
                    current_gesture_name = "MOVE"
                    
                    # Reset other states
                    prev_hand_size = None
                    prev_index_pos = None
                    rot_history_y.clear()
                    rot_history_x.clear()
                    
                elif active_g == "ROTATE":
                    if prev_index_pos is not None:
                        dx = index_t[0] - prev_index_pos[0]
                        dy = -(index_t[1] - prev_index_pos[1])
                        # Deadzone 0.002 to filter noise but preserve slow movements
                        if abs(dx) > 0.002 or abs(dy) > 0.002:
                            rot_y = dx * 360  # Increased sensitivity
                            rot_x = -dy * 360
                            
                            # Smooth over 3 frames
                            rot_history_y.append(rot_y)
                            rot_history_x.append(rot_x)
                            if len(rot_history_y) > 3:
                                rot_history_y.pop(0)
                                rot_history_x.pop(0)
                            
                            avg_rot_y = sum(rot_history_y) / len(rot_history_y)
                            avg_rot_x = sum(rot_history_x) / len(rot_history_x)
                            
                            assembly[0].rotate_y(avg_rot_y)
                            assembly[0].rotate_x(avg_rot_x)
                            needs_render[0] = True
                            prev_index_pos = index_t
                    else:
                        prev_index_pos = index_t
                    current_gesture_name = "ROTATE"
                    
                    # Reset other states
                    prev_hand_pos = None
                    prev_hand_size = None
                    
                else: # RELEASE or None
                    prev_hand_pos = None
                    prev_hand_size = None
                    prev_index_pos = None
                    rot_history_y.clear()
                    rot_history_x.clear()
                    current_gesture_name = "RELEASE" if active_g == "RELEASE" else "None"
            else: # Hand not visible
                prev_hand_pos = None
                prev_hand_size = None
                prev_index_pos = None
                rot_history_y.clear()
                rot_history_x.clear()
                current_gesture_name = "No Hand"

            # Dynamic on-screen gesture indicator overlay
            if hand_vis:
                if active_g == "MOVE":
                    gesture_overlay.text("Gesture: 👌 MOVE (Pinching)")
                    gesture_overlay.c("green")
                elif active_g == "ROTATE":
                    gesture_overlay.text("Gesture: ☝️ ROTATE (Index Up)")
                    gesture_overlay.c("cyan")
                elif active_g == "RELEASE":
                    gesture_overlay.text("Gesture: ✋ RELEASE (Open)")
                    gesture_overlay.c("white")
                else:
                    gesture_overlay.text("Gesture: None")
                    gesture_overlay.c("gray")
            else:
                gesture_overlay.text("Gesture: ❌ No Hand Detected")
                gesture_overlay.c("red")

            # Show controls guide overlay (for 10 seconds)
            show_controls_now = time.time() < controls_display_expiry
            if show_controls_now:
                if controls_overlay not in plt.actors:
                    plt.add(controls_overlay)
            else:
                if controls_overlay in plt.actors:
                    plt.remove(controls_overlay)

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
                plt.add(help_overlay, gesture_overlay)
                
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
                plt.add(help_overlay, gesture_overlay)
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

        try:
            plt.close()
        except Exception as e:
            print(f"[AR3D] Error closing plotter: {e}")
        print("[AR3D] vedo window closed.")
