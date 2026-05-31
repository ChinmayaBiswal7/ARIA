"""
skills/ar_commands.py — Extracted AR execution logic for ARIA
============================================================
Implements AR camera disable, subcommands parsing, and mode starts without circular main.py imports.
"""
import time

def handle_disable_ar_camera(aria):
    try:
        import time
        stopped_something = False
        
        print("[AR Disable] Step 1: Stopping playground and 3D mode...")
        if getattr(aria, "ar_mode", False) or getattr(aria, "ar_playground", None) is not None:
            if aria.ar_playground:
                try:
                    thread_obj = aria.ar_playground.thread
                    aria.ar_playground.stop()
                    if thread_obj:
                        thread_obj.join(timeout=1.0)
                    print(
                        f"[AR Disable] Playground thread alive: "
                        f"{thread_obj.is_alive() if thread_obj else False}"
                    )
                except Exception as pe:
                    print(f"[AR Disable] Step 1 Error (playground stop): {pe}")
            stopped_something = True
        
        print("[AR Disable] Step 2: Stopping vision learner camera...")
        if hasattr(aria, "vision_learner") and aria.vision_learner.running:
            try:
                aria.vision_learner.stop_camera()
            except Exception as ve:
                print(f"[AR Disable] Step 2 Error (vision stop): {ve}")
            aria._speak("Camera closed.")
            stopped_something = True
        
        # Synchronization delay to let background threads finish loop exits and self-destroy windows
        print("[AR Disable] Sync pause (0.2s) for background cleanup...")
        time.sleep(0.2)
        
        print("[AR Disable] Step 3: Clearing state variables...")
        aria.ar_playground = None
        aria.ar_mode = False
        aria.current_model = None
        aria.active_gesture = None
        
        if stopped_something:
            aria._speak("AR Playground stopped.")
        else:
            aria._speak("Camera and AR mode are already off.")
        
        print("[AR Disable] Step 4: Releasing camera...")
        try:
            aria._check_and_release_camera()
        except Exception as re:
            print(f"[AR Disable] Step 4 Error (camera release): {re}")
            
        print("[AR Disable] Complete.")
        return "disabled_ar_camera"
    except Exception as e:
        print(f"[Camera/AR] Failed to stop: {e}")
        aria._speak("Could not stop camera or AR mode.")
        return "disable_ar_camera_failed"


def handle_ar_subcommands(aria, inp, user_input):
    if any(x in inp for x in ["clear board", "clear canvas", "clear whiteboard"]):
        aria.ar_playground.handle_subcommand("clear_board")
        aria._speak("Board cleared.")
        return "cleared_board"
    elif "undo" in inp:
        aria.ar_playground.handle_subcommand("undo")
        aria._speak("Undone.")
        return "undone"
    elif any(x in inp for x in ["next mask", "change mask"]):
        aria.ar_playground.handle_subcommand("next_mask")
        aria._speak("Swapping to next mask.")
        return "swapped_next_mask"
    elif any(x in inp for x in ["previous mask", "prev mask"]):
        aria.ar_playground.handle_subcommand("prev_mask")
        aria._speak("Swapping to previous mask.")
        return "swapped_prev_mask"
    elif any(x in inp for x in ["remember this", "save this"]):
        aria.ar_playground.handle_subcommand("remember_current")
        aria._speak("Remembering current object.")
        return "remembered_current_object"
    elif any(p in inp for p in ["create a", "create an", "generate a", "show me a", "load a", "make a"]):
        res = aria.ar_playground.handle_subcommand(inp)
        if res:
            aria._speak(res)
        return "created_3d_model_" + inp.replace("create a", "").strip()
    elif any(p in inp for p in [
        "load the", "show me the model", "show the model", "show me the",
        "load model", "display the", "put up the", "put the"
    ]):
        model_key = getattr(aria, "_last_model_key", None)
        for word in inp.split():
            cleaned = word.strip(".,!?")
            if cleaned in ["dragon", "bunny", "car", "spaceship", "robot", "teapot",
                           "lamborghini", "armadillo", "cow", "crystal", "helmet",
                           "earth", "planet", "dna", "torus", "solar"]:
                model_key = cleaned
                aria._last_model_key = model_key
                break
        if model_key:
            res = aria.ar_playground.handle_subcommand(f"load the {model_key}")
            if res:
                aria._speak(res)
            return "loaded_model_" + model_key
        else:
            res = aria.ar_playground.handle_subcommand(inp)
            if res:
                aria._speak(res)
            return "loaded_generic_model"
    elif "ready" in inp and any(w in inp for w in ["tell", "notify", "wait", "once", "when", "is", "check", "model"]):
        is_gen = False
        if hasattr(aria.ar_playground, '_model_gen') and aria.ar_playground._model_gen:
            is_gen = aria.ar_playground._model_gen._generating
        if is_gen:
            aria._speak("Still generating, I will notify you automatically when done.")
            return "checked_model_ready_generating"
        else:
            aria._speak("The model is ready.")
            return "checked_model_ready_finished"
    elif any(p in inp for p in [
        "rotate left", "rotate right", "rotate up", "rotate down",
        "make it bigger", "make it smaller", "zoom in", "zoom out",
        "reset view", "show wireframe", "explode model", "explode it",
        "change color", "change colour", "move", "rotate", "make", "reset", "center",
        "show controls", "controls"
    ]):
        res = aria.ar_playground.handle_subcommand(inp)
        if res:
            aria._speak(res)
        return "transformed_model_" + inp.replace(" ", "_")
    else:
        try:
            from skills.ar_3d_mode import match_model
            key = match_model(inp)
            if key:
                aria._last_model_key = key
                res = aria.ar_playground.handle_subcommand(inp)
                if res:
                    aria._speak(res)
                else:
                    aria._speak(f"Loading {key}...")
                return "loaded_matched_model_" + key
        except Exception:
            pass
    return "no_matching_ar_subcommand"


def handle_start_ar_mode(aria, matched_mode):
    try:
        if aria.gesture_mode:
            from skills.gesture_control import stop_gesture_control
            stop_gesture_control()
            aria.gesture_mode = False
        if hasattr(aria, 'vision_learner') and aria.vision_learner.running:
            aria.vision_learner.stop_camera()
        
        if not aria.camera:
            from camera import Camera
            aria.camera = Camera()
        elif not aria.camera.available:
            aria.camera.reacquire()
        if not aria.camera or not aria.camera.available:
            aria._speak("Webcam is unavailable right now.")
            return "start_ar_failed_camera_unavailable"
        
        from skills.ar_playground import ARPlayground
        if not aria.ar_playground:
            yolo_model = getattr(aria.vision_learner, 'yolo', None)
            aria.ar_playground = ARPlayground(
                frame_provider=aria.camera.capture_frame_raw,
                yolo_model=yolo_model,
                aria_brain=aria.brain,
                aria_speak=aria._speak,
                aria_instance=aria
            )
        aria.ar_playground.start()
        aria.ar_mode = True

        aria.ar_playground.set_mode(matched_mode)
        
        mode_speak_names = {
            "wand": "Magic Wand mode active.",
            "flowers": "Flower Garden mode active.",
            "piano": "Air Piano mode active.",
            "pet": "Virtual Pet mode active.",
            "drawing": "AR Drawing Canvas mode active.",
            "physics": "Hand Physics mode active.",
            "face": "Face AR Overlays active.",
            "pose": "Pose Detection active.",
            "whiteboard": "AR Whiteboard active.",
            "object": "Object Interaction active.",
            "ar3d": "AR 3D Hologram mode active. Say 'create a dragon' to start."
        }
        aria._speak(mode_speak_names[matched_mode])
        return "started_ar_mode_" + matched_mode
    except Exception as e:
        print(f"[ARPlayground] Mode set failed: {e}")
        aria._speak("Failed to configure AR mode.")
        return "start_ar_failed_exception"


def handle_enable_ar_playground_generic(aria):
    try:
        if aria.gesture_mode:
            from skills.gesture_control import stop_gesture_control
            stop_gesture_control()
            aria.gesture_mode = False
        if hasattr(aria, 'vision_learner') and aria.vision_learner.running:
            aria.vision_learner.stop_camera()
        
        if not aria.camera:
            from camera import Camera
            aria.camera = Camera()
        elif not aria.camera.available:
            aria.camera.reacquire()
        if not aria.camera or not aria.camera.available:
            aria._speak("Webcam is unavailable right now.")
            return "enable_ar_failed_camera_unavailable"
        
        from skills.ar_playground import ARPlayground, MEDIAPIPE_AVAILABLE
        if not MEDIAPIPE_AVAILABLE:
            aria._speak("AR Playground is unavailable. MediaPipe is not installed.")
            return "enable_ar_failed_mediapipe_missing"
        if not aria.ar_playground:
            yolo_model = getattr(aria.vision_learner, 'yolo', None)
            aria.ar_playground = ARPlayground(
                frame_provider=aria.camera.capture_frame_raw,
                yolo_model=yolo_model,
                aria_brain=aria.brain,
                aria_speak=aria._speak,
                aria_instance=aria
            )
        success = aria.ar_playground.start()
        if success:
            aria.ar_mode = True
            aria._speak("AR Playground enabled. Wave your hand in front of the camera!")
            return "enabled_ar_playground_generic"
        else:
            aria._speak("Sorry, I could not start the AR Playground.")
            return "enable_ar_failed_start_error"
    except Exception as e:
        print(f"[ARPlayground] Failed to start: {e}")
        aria._speak("Could not start AR Playground.")
        return "enable_ar_failed_exception"
