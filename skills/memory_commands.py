"""
skills/memory_commands.py — Extracted Memory execution logic for ARIA
======================================================================
Organized into sections: Personal Memory vs Vision Memory.
Does not import main.py directly.
"""
import re
import os
import glob
import time
import io
import base64
from PIL import Image
import cv2

# -----------------------------------------------------------------------------
# Utility Imports / Fallbacks
# -----------------------------------------------------------------------------
try:
    from gui import set_state, set_text
except ImportError:
    def set_state(s): pass
    def set_text(t): pass

# -----------------------------------------------------------------------------
# Section 1: Personal Memory (Notes, Reminders, Folders, WhatsApp, PC Status)
# -----------------------------------------------------------------------------
def handle_reminders(aria, inp, user_input):
    from skills.command_patterns import REMINDER_GET_WORDS, REMINDER_CLEAR_WORDS
    if "remind me to " in inp:
        raw_task = user_input.split("remind me to", 1)[1].strip()
        task, due, due_at = aria.memory_skill.parse_reminder_text(raw_task)
        resp = aria.memory_skill.add_reminder(task, due, due_at)
        aria._speak(resp)
        return "added_reminder_" + task

    if any(x in inp for x in REMINDER_GET_WORDS):
        resp = aria.memory_skill.get_pending_reminders()
        aria._speak(resp)
        return "listed_reminders"

    if any(x in inp for x in REMINDER_CLEAR_WORDS):
        resp = aria.memory_skill.clear_reminders()
        aria._speak(resp)
        return "cleared_reminders"

    return "no_matching_reminder_action"


def handle_folders_whatsapp(aria, inp, user_input):
    from skills.command_patterns import FOLDER_REMEMBER_WORDS, OPEN_FOLDER_WORDS, WHATSAPP_SEND_WORDS
    if any(x in inp for x in FOLDER_REMEMBER_WORDS):
        match = re.search(r'(?:remember folder|remember this folder)\s+(.+?)\s+as\s+(.+)', inp)
        if match:
            path = match.group(1).strip()
            name = match.group(2).strip()
            resp = aria.memory_skill.save_folder(name, path)
            aria._speak(resp)
            return "remembered_folder_" + name
        else:
            aria._speak("To remember a folder, say: remember folder [path] as [name]")
            return "remember_folder_syntax_error"

    if any(x in inp for x in OPEN_FOLDER_WORDS):
        path_match = re.search(r'(?:open folder|go to folder|navigate to)\s+(.+)', inp)
        if path_match:
            folder_name = path_match.group(1).strip()
            FOLDER_MAP = {
                "downloads": os.path.expanduser("~/Downloads"),
                "documents": os.path.expanduser("~/Documents"),
                "desktop": os.path.expanduser("~/Desktop"),
                "pictures": os.path.expanduser("~/Pictures"),
                "music": os.path.expanduser("~/Music"),
                "videos": os.path.expanduser("~/Videos"),
                "ai": r"C:\D FOLDER\Projects\AI",
                "projects": r"C:\D FOLDER\Projects",
                "screenshot": r"C:\D FOLDER\Projects\AI",
                "screenshots": r"C:\D FOLDER\Projects\AI",
                "screenshot folder": r"C:\D FOLDER\Projects\AI",
            }
            folder_path = FOLDER_MAP.get(folder_name.lower(), folder_name)
            if aria.screen.open_folder(folder_path):
                aria._speak(f"Opened the {folder_name} folder for you.")
                return "opened_folder_" + folder_name
            else:
                aria._speak(f"I couldn't find the folder {folder_name}. Please check the path.")
                return "open_folder_failed_" + folder_name
        return "open_folder_failed_no_match"

    if any(x in inp for x in WHATSAPP_SEND_WORDS):
        ai_dir = r"C:\D FOLDER\Projects\AI"
        shots = sorted(glob.glob(os.path.join(ai_dir, "screenshot_*.png")), reverse=True)
        if not shots:
            aria._speak("I couldn't find any screenshots to send. Take one first by saying take screenshot.")
            return "whatsapp_send_failed_no_screenshot"
        latest = shots[0]
        aria._speak("Who do you want to send the screenshot to on WhatsApp?")
        set_state("LISTENING")
        contact = aria.voice.listen(timeout=8)
        if not contact:
            aria._speak("I didn't catch the name. Try again.")
            return "whatsapp_send_failed_no_recipient"
        aria._speak(f"Sending the screenshot to {contact} on WhatsApp Web now.")
        aria.screen.send_whatsapp_file(contact, latest)
        aria._speak(f"WhatsApp Web is open with {contact} selected. Please click the attachment icon to attach the file. The path is already copied.")
        return "whatsapp_sent_screenshot_to_" + contact

    if "send whatsapp" in inp or "whatsapp message" in inp or ("send" in inp and "whatsapp" in inp):
        aria._speak("Who do you want to message on WhatsApp?")
        set_state("LISTENING")
        contact = aria.voice.listen(timeout=8)
        if not contact:
            aria._speak("I didn't catch the name. Try again.")
            return "whatsapp_msg_failed_no_recipient"
        aria._speak(f"What message should I send to {contact}?")
        set_state("LISTENING")
        message = aria.voice.listen(timeout=12)
        if not message:
            aria._speak("I didn't catch the message. Try again.")
            return "whatsapp_msg_failed_no_message"
        aria._speak(f"Sending '{message}' to {contact} on WhatsApp Web now.")
        result = aria.screen.send_whatsapp_message(contact, message)
        aria._speak("Done! Message sent.")
        return "whatsapp_msg_sent_to_" + contact

    return "no_matching_folders_whatsapp_action"


def handle_personal_notes_pc_status(aria, inp, user_input):
    from skills.command_patterns import PERSONAL_BRAIN_WORDS, GUIDE_ME_WORDS
    if any(x in inp for x in PERSONAL_BRAIN_WORDS):
        aria._speak(aria.memory_skill.get_personal_brain_summary())
        return "retrieved_personal_brain_summary"

    if any(x in inp for x in GUIDE_ME_WORDS):
        summary = aria.memory_skill.get_personal_brain_summary()
        prompt = (
            "Use this local personal memory and current context to suggest what I should do next. "
            "Keep it practical and short.\n\n" + summary
        )
        response = aria.brain.think(
            prompt,
            user_name=aria.known_user,
            user_similarity=aria.known_user_similarity,
            user_confidence=aria.known_user_confidence,
            emotional_tone=getattr(aria, "current_user_emotion", "neutral")
        )
        aria._speak(response)
        return "provided_guidance"

    if any(aria.normalizer_val.lower().startswith(prefix) if hasattr(aria, 'normalizer_val') else inp.startswith(prefix) for prefix in ["remember that ", "remember i ", "remember my "]):
        note = re.sub(r'(?i)^remember\s+(that|i|my)\s+', '', user_input).strip()
        aria._speak(aria.memory_skill.add_personal_note("fact", note))
        return "added_note_fact"

    if any(aria.normalizer_val.lower().startswith(prefix) if hasattr(aria, 'normalizer_val') else inp.startswith(prefix) for prefix in ["i need to ", "i have to ", "i should "]):
        task = re.sub(r'(?i)^(i need to|i have to|i should)\s+', '', user_input).strip()
        aria._speak(aria.memory_skill.add_personal_note("need_to_do", task))
        return "added_note_todo"

    if any(aria.normalizer_val.lower().startswith(prefix) if hasattr(aria, 'normalizer_val') else inp.startswith(prefix) for prefix in ["i don't need to ", "i dont need to ", "i should not ", "don't let me ", "dont let me "]):
        avoid = re.sub(r"(?i)^(i don't need to|i dont need to|i should not|don't let me|dont let me)\s+", "", user_input).strip()
        aria._speak(aria.memory_skill.add_personal_note("avoid", avoid))
        return "added_note_avoid"

    if any(aria.normalizer_val.lower().startswith(prefix) if hasattr(aria, 'normalizer_val') else inp.startswith(prefix) for prefix in ["my goal is ", "goal is "]):
        goal = re.sub(r'(?i)^(my goal is|goal is)\s+', '', user_input).strip()
        aria._speak(aria.memory_skill.add_personal_note("goal", goal))
        return "added_note_goal"

    if inp.startswith("i want to "):
        from skills.routing_policy import is_actionable_execution_request
        goal = re.sub(r'(?i)^i want to\s+', '', user_input).strip()
        if not is_actionable_execution_request(user_input):
            aria._speak(aria.memory_skill.add_personal_note("goal", goal))
            return "added_note_goal"
        print("[Main/IntentGuard] 'I want to' contains action cues. Routing to execution, not goal storage.")

    if any(aria.normalizer_val.lower().startswith(prefix) if hasattr(aria, 'normalizer_val') else inp.startswith(prefix) for prefix in ["i like ", "i prefer ", "my preference is "]):
        pref = re.sub(r'(?i)^(i like|i prefer|my preference is)\s+', '', user_input).strip()
        aria._speak(aria.memory_skill.add_personal_note("preference", pref))
        return "added_note_preference"

    if any(x in inp for x in ["pc status", "system status", "check status", "how is my pc", "pc context"]):
        summary = aria.context_skill.get_context_summary()
        aria._speak("Reading current PC status.")
        print(summary)
        batt = aria.context_skill.get_battery_percent()
        wifi = aria.context_skill.get_wifi_status()
        ac = aria.context_skill.get_active_window()
        aria._speak(f"Battery is at {aria.context_skill.get_battery_percent() if batt is not None else 'unknown'} percent, wifi is {wifi}, and active app is {ac[:40]}.")
        return "read_pc_status"

    if "battery" in inp and any(x in inp for x in ["level", "percent", "status", "check"]):
        batt = aria.context_skill.get_battery_percent()
        chg = aria.context_skill.get_charging_status()
        if batt is not None:
            state = "charging" if chg else "discharging"
            aria._speak(f"Your battery level is {batt} percent and is currently {state}.")
            return f"checked_battery_{batt}_percent"
        else:
            aria._speak("I couldn't read the battery level. If this is a desktop, it might not have one.")
            return "checked_battery_unavailable"

    return "no_matching_personal_notes_action"


# -----------------------------------------------------------------------------
# Section 2: Vision Memory (Screenshots, Object/Room Scanning & Visual Matching)
# -----------------------------------------------------------------------------
def handle_screen_screenshot_vision(aria, inp, user_input):
    from skills.command_patterns import SCREENSHOT_TAKE_WORDS, SCREEN_READ_TRIGGERS, SMART_CLICK_TRIGGERS
    if any(x in inp for x in SCREENSHOT_TAKE_WORDS):
        path = aria.screen.take_screenshot()
        aria._speak(f"Screenshot saved!")
        return "took_screenshot_saved"

    if any(x in inp for x in SCREEN_READ_TRIGGERS):
        set_state("THINKING")
        set_text("Reading screen...")
        aria._speak("Reading your screen now.")
        aria._answer_with_screen_image(user_input)
        return "described_screen"

    if any(t in inp for t in SMART_CLICK_TRIGGERS) and aria.brain.vision_ready:
        target = inp
        for t in SMART_CLICK_TRIGGERS:
            target = target.replace(t, "").strip()
        target = target.strip(" .,?") or "anything on screen"

        set_state("THINKING")
        set_text(f"Reading screen for: {target}")
        aria._speak("Looking at your screen now.")

        pil_img = aria.screen.get_screen_image()
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        sw, sh = aria.screen.screen_w, aria.screen.screen_h
        set_text(f"Vision AI looking for: {target}")
        vision_result = aria.brain.think_with_screen(img_b64, target, sw, sh)

        if vision_result is not None:
            if vision_result.startswith("FOUND:"):
                location_desc = vision_result[6:].strip()
                cx, cy = aria.brain.parse_location_to_coords(location_desc, sw, sh)
                aria.screen.click(cx, cy)
                aria._speak(f"Found it. It is at the {location_desc}. Clicking now.")
                return "clicked_target_" + target
            else:
                clean = re.sub(r'[*#`_]', '', vision_result).strip()
                aria._speak(clean[:300] if clean else "I couldn't find that on your screen.")
                return "described_target_not_found"
        else:
            aria._speak("Vision model had an error. Try again.")
            return "vision_model_error"

    if ("click" in inp or "tap" in inp or "press" in inp or "open" in inp) and any(w in inp for w in ["corner", "center", "middle", "left", "right", "top", "bottom", "taskbar", "start", "desktop", "tray", "close button", "minimize", "maximize button"]):
        sw, sh = aria.screen.screen_w, aria.screen.screen_h
        margin = 40

        REGIONS = {
            ("top left",):                  (margin,        margin,       "top-left corner"),
            ("top right",):                 (sw - margin,   margin,       "top-right corner"),
            ("bottom left",):               (margin,        sh - margin,  "bottom-left corner"),
            ("bottom right",):              (sw - margin,   sh - margin,  "bottom-right corner"),
            ("top center", "top middle"):   (sw // 2,       margin,       "top center"),
            ("bottom center", "bottom middle", "taskbar center"): (sw // 2, sh - 25, "taskbar center"),
            ("left center", "left side"):   (margin,        sh // 2,      "left side"),
            ("right center", "right side"):  (sw - margin,   sh // 2,      "right side"),
            ("center", "middle", "screen center"): (sw // 2, sh // 2,    "screen center"),
            ("start menu", "start button", "windows button"): (25, sh - 25, "Start menu"),
            ("taskbar",):                   (sw // 2,       sh - 25,      "taskbar"),
            ("notification", "system tray", "tray"): (sw - 60, sh - 25, "system tray"),
            ("close button", "close window button"): (sw - 25, 15,      "close button"),
            ("maximize button",):           (sw - 65,       15,           "maximize button"),
            ("minimize button",):           (sw - 105,      15,           "minimize button"),
        }

        clicked_region = None
        for phrases, (cx, cy, label) in REGIONS.items():
            if any(p in inp for p in phrases):
                clicked_region = (cx, cy, label)
                break

        if not clicked_region:
            if "top" in inp and "left" not in inp and "right" not in inp:
                clicked_region = (sw // 2, margin, "top area")
            elif "bottom" in inp and "left" not in inp and "right" not in inp:
                clicked_region = (sw // 2, sh - 25, "bottom area / taskbar")
            elif "left" in inp:
                clicked_region = (margin, sh // 2, "left side")
            elif "right" in inp:
                clicked_region = (sw - margin, sh // 2, "right side")

        if clicked_region:
            cx, cy, label = clicked_region
            double = "double" in inp
            right  = "right click" in inp or "right-click" in inp
            if right:
                aria.screen.right_click(cx, cy)
                aria._speak(f"Right-clicked the {label}.")
            elif double:
                aria.screen.double_click(cx, cy)
                aria._speak(f"Double-clicked the {label}.")
            else:
                aria.screen.click(cx, cy)
                aria._speak(f"Clicked the {label}.")
            return "clicked_region_" + label

    if any(x in inp for x in ["what's on my screen", "what is on my screen", "read my screen", "what do you see on screen"]):
        img = aria.screen.get_screen_image()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        aria._speak("I can see your screen. Let me describe what's there. I see a Windows desktop with open windows and applications. For full screen reading, I need the vision model. Say 'take screenshot' and I can save it for you.")
        return "described_screen_basic"

    return "no_matching_screen_vision_action"


def enroll_object(aria, inp, object_trigger_found, user_input):
    raw_input = inp.split(object_trigger_found, 1)[1].strip()
    cleaned = True
    while cleaned:
        cleaned = False
        for clean_word in ["a ", "an ", "the ", "me ", "i am ", "i'm ", "im ", "my name is ", "called ", "named ", "holding "]:
            if raw_input.lower().startswith(clean_word):
                raw_input = raw_input[len(clean_word):].strip()
                cleaned = True
    
    stop_phrases = [" which", " that", ". ", "!", "?", " holding", " and", " is ", " for "]
    obj_name = raw_input
    for stop in stop_phrases:
        if stop in obj_name:
            obj_name = obj_name.split(stop)[0].strip()
    new_name = obj_name.title()

    words = new_name.split()
    invalid_verbs = ["saying", "telling", "asking", "talking", "showing", "looking", "trying", "searching", "sorry", "not", "just", "sure", "going", "doing", "thinking", "having", "getting", "sitting", "working", "standing", "reading", "writing"]
    if not new_name or len(words) > 3 or (len(words) > 0 and words[0].lower() in invalid_verbs):
        return "invalid_object_name_" + new_name

    if not aria.vision_learner.running:
        if getattr(aria, "airtouch_mode", False):
            aria._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
            return "object_learning_aborted_airtouch_active"
        if not aria.camera or not aria.camera.available:
            aria.camera.reacquire()
        aria._speak("Let me open my camera to look.")
        aria.vision_learner.mode = "both"
        aria.vision_learner.start_camera(frame_provider=aria.camera.capture_frame_raw)
        for _ in range(30):
            time.sleep(0.1)
            with aria.vision_learner._lock:
                if aria.vision_learner.current_frame is not None: break

    with aria.vision_learner._lock:
        frame = aria.vision_learner.current_frame.copy() if aria.vision_learner.current_frame is not None else None
    
    if frame is None:
        aria._speak("I can't see anything. Please make sure the camera is working.")
        return "object_learning_failed_no_camera_frame"

    aria._speak(f"I'll learn this object as {new_name}.")
    success, msg = aria.vision_learner.capture_and_learn(new_name)
    if success:
        aria._speak(f"Got it! I have learned what a {new_name} looks like.")
        return "learned_object_" + new_name
    else:
        aria._speak(msg)
        return "object_learning_failed_" + msg


def handle_room_learning(aria, inp, user_input, image=None):
    from skills.command_patterns import ROOM_LEARN_TRIGGERS, ROOM_QUERY_TRIGGERS
    
    matched_trigger = None
    for t in ROOM_LEARN_TRIGGERS:
        if t in inp:
            matched_trigger = t
            break
            
    if matched_trigger:
        raw_room = inp.split(matched_trigger, 1)[1].strip()
        cleaned = True
        while cleaned:
            cleaned = False
            for clean_word in ["a ", "an ", "the "]:
                if raw_room.lower().startswith(clean_word):
                    raw_room = raw_room[len(clean_word):].strip()
                    cleaned = True
        
        stop_phrases = [". ", "!", "?", " and"]
        room_name = raw_room
        for stop in stop_phrases:
            if stop in room_name:
                room_name = room_name.split(stop)[0].strip()
        
        room_name = room_name.title()
        
        if not aria.vision_learner.running:
            if getattr(aria, "airtouch_mode", False):
                aria._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
                return "room_learning_aborted_airtouch_active"
            if not aria.camera or not aria.camera.available:
                aria.camera.reacquire()
            aria._speak("Let me open my camera to scan the room.")
            aria.vision_learner.start_camera(frame_provider=aria.camera.capture_frame_raw)
            for _ in range(30):
                time.sleep(0.1)
                with aria.vision_learner._lock:
                    if aria.vision_learner.current_frame is not None:
                        break
                        
        detected = aria.vision_learner.get_detected_objects()
        if not detected:
            aria._speak("I can't see enough objects clearly to characterize this room. Please make sure the lighting is good.")
            return "room_learning_failed_no_detected_objects"
            
        success, msg = aria.memory.memory_manager.scene_mem.learn_scene(room_name, detected)
        aria._speak(msg)
        return "learned_room_" + room_name

    if image is None and any(x in inp for x in ROOM_QUERY_TRIGGERS):
        if not aria.vision_learner.running:
            if getattr(aria, "airtouch_mode", False):
                aria._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
                return "room_query_aborted_airtouch_active"
            if not aria.camera or not aria.camera.available:
                aria.camera.reacquire()
            aria._speak("Let me open the camera to look around.")
            aria.vision_learner.start_camera(frame_provider=aria.camera.capture_frame_raw)
            for _ in range(30):
                time.sleep(0.1)
                with aria.vision_learner._lock:
                    if aria.vision_learner.current_frame is not None:
                        break
                        
        detected = aria.vision_learner.get_detected_objects()
        room_name, sim, description = aria.memory.memory_manager.scene_mem.recognize_scene(detected)
        aria._speak(description)
        return "recognized_room_" + room_name

    return "no_matching_room_action"


def handle_object_identification(aria, inp, user_input, image=None):
    from skills.command_patterns import CAMERA_OPEN_TRIGGERS, OBJECT_LIST_WORDS, OBJECT_IDENTIFY_TRIGGERS
    if image is None and aria._is_camera_visual_question(inp):
        aria._answer_with_camera_image(user_input)
        return "answered_camera_visual_question"

    _visual_question_triggers = [
        "holding", "person is holding", "person holding", "he is holding",
        "she is holding", "they are holding", "in his hand", "in her hand",
        "in their hand", "what is in front of me", "what is in my hand",
        "what am i holding"
    ]
    if image is None and any(x in inp for x in _visual_question_triggers):
        if not aria.vision_learner.running:
            if getattr(aria, "airtouch_mode", False):
                aria._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
                return "object_id_aborted_airtouch_active"
            if not aria.camera or not aria.camera.available:
                aria.camera.reacquire()
            aria._speak("Let me look through the camera.")
            aria.vision_learner.start_camera(frame_provider=aria.camera.capture_frame_raw)
            for _ in range(30):
                time.sleep(0.1)
                with aria.vision_learner._lock:
                    if aria.vision_learner.current_frame is not None:
                        break

        with aria.vision_learner._lock:
            frame = aria.vision_learner.current_frame.copy() if aria.vision_learner.current_frame is not None else None

        if frame is None:
            aria._speak("I can't see anything right now. Please make sure the camera is working.")
            return "object_id_failed_no_camera_frame"

        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            camera_image = Image.fromarray(rgb)
            print(f"[Main] Visual question routed with camera frame: {camera_image.size}")

            response = aria.brain.think(
                user_input,
                image=camera_image,
                user_name=aria.known_user,
                user_similarity=aria.known_user_similarity,
                user_confidence=aria.known_user_confidence,
                emotional_tone=getattr(aria, "current_user_emotion", "neutral")
            )
            response_lower = response.lower() if response else ""
            non_visual_response = any(x in response_lower for x in [
                "visual information", "can't see", "cannot see", "i'm ready",
                "tell me what to open", "open, search, or automate"
            ])
            if response and not non_visual_response:
                spoken = re.sub(r'\[[A-Z]+:[^\]]*\]', '', response)
                spoken = re.sub(r'\[[A-Z]+\]', '', spoken).strip()
                aria._speak(spoken or aria.vision_learner.identify_object())
                return "visual_question_llm_answered"
            else:
                result = aria.vision_learner.identify_object()
                aria._speak(result)
                return "visual_question_opencv_answered_" + result
        except Exception as e:
            print(f"[Main] Visual question error: {e}")
            result = aria.vision_learner.identify_object()
            aria._speak(result)
            return "visual_question_error_fallback_" + result

    if image is None and any(x in inp for x in [
        "what is this", "what is tihis", "what's this", "what am i holding", 
        "identify this", "identfy this", "idenfty this", "what do you see", 
        "what is in the room", "whats in the room", "what's in the room", 
        "whats around you", "what's around you", "what is around you", "what do you see around you",
        "what is around", "whats around", "what's around", "what is in front of me", "what is in front of you"
    ]):
        if not aria.vision_learner.running:
            if getattr(aria, "airtouch_mode", False):
                aria._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
                return "object_id_aborted_airtouch_active"
            if not aria.camera or not aria.camera.available:
                aria.camera.reacquire()
            aria._speak("Let me open my camera to see.")
            aria.vision_learner.start_camera(frame_provider=aria.camera.capture_frame_raw)
            for _ in range(30):
                time.sleep(0.1)
                with aria.vision_learner._lock:
                    if aria.vision_learner.current_frame is not None:
                        break

        result = aria.vision_learner.identify_object()
        aria._speak(result)
        return "identified_object_" + result

    if any(x in inp for x in ["object mode", "thing mode", "identify objects", "show objects"]) and not any(ar in inp for ar in ["ar ", "air "]):
        aria.vision_learner.mode = "object"
        if not aria.vision_learner.running:
            if getattr(aria, "airtouch_mode", False):
                aria._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
                return "object_mode_aborted_airtouch_active"
            if not aria.camera or not aria.camera.available:
                aria.camera.reacquire()
            aria.vision_learner.start_camera(frame_provider=aria.camera.capture_frame_raw)
        aria._speak("Switching to Object Mode. I am now looking for things you taught me.")
        return "switched_to_object_mode"

    if any(x in inp for x in CAMERA_OPEN_TRIGGERS):
        aria.vision_learner.mode = "object" 
        already = aria.vision_learner.running
        if already:
            aria._speak("Camera is already on. Go ahead and show me the objects!")
            return "camera_already_on"

        if getattr(aria, "airtouch_mode", False):
            aria._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
            return "camera_open_aborted_airtouch_active"
        if not aria.camera or not aria.camera.available:
            aria.camera.reacquire()

        if aria.vision_learner.start_camera(frame_provider=aria.camera.capture_frame_raw):
            aria._speak(
                "Camera is now open! Hold an object in front of me and say "
                "this is a and the object name, and I will learn it."
            )
            return "opened_camera"
        else:
            aria._speak("I had trouble opening the camera. Is your webcam connected?")
            return "camera_open_failed"

    if any(x in inp for x in OBJECT_LIST_WORDS):
        list_msg = aria.vision_learner.list_learned()
        aria._speak(list_msg)
        return "listed_learned_objects"

    return "no_matching_object_id_action"
