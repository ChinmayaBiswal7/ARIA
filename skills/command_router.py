"""
skills/command_router.py — Modular input command router for ARIA
===============================================================
Dispatches user utterances to corresponding feature helper methods.
This keeps the routing dispatcher thin and delegates actual execution.
"""

def handle_system(aria, inp, user_input, image=None):
    from skills.command_patterns import (
        STOP_WORDS, ADMIN_UNLOCK_WORDS, ADMIN_LOCK_WORDS, WEATHER_WORDS, GITHUB_WORDS,
        WORKSPACE_PREPARE_WORDS, WORKSPACE_STUDY_WORDS, WORKSPACE_CLOSE_WORDS,
        AUTONOMOUS_TASK_RUN_WORDS, AUTONOMOUS_TASK_CANCEL_WORDS, AUTONOMOUS_TASK_REPLAY_WORDS,
        OLLAMA_LAUNCH_WORDS, EXIT_APP_WORDS, GOODBYE_WORDS, RESET_MEMORY_WORDS,
        WINDOWS_OPEN_WORDS, PRESS_KEY_WORDS, TEACH_COMMAND_WORDS,
        LANGUAGE_HINDI_WORDS, LANGUAGE_TELUGU_WORDS, LANGUAGE_ENGLISH_WORDS, LANGUAGE_AUTO_WORDS,
        GESTURE_DISABLE_WORDS, GESTURE_ENABLE_WORDS
    )

    if inp in STOP_WORDS:
        aria._stop_cancel_command_helper()
        return {"handled": True, "action": "system", "response": "stop_cancel_command"}

    if any(x in inp for x in ADMIN_UNLOCK_WORDS + ADMIN_LOCK_WORDS):
        aria._security_admin_helper(inp)
        return {"handled": True, "action": "system", "response": "security_admin_command"}

    if any(x in inp for x in WEATHER_WORDS) or inp.startswith("github "):
        aria._weather_github_helper(inp, user_input)
        return {"handled": True, "action": "system", "response": "weather_github_command"}

    if (any(x in inp for x in WORKSPACE_PREPARE_WORDS + WORKSPACE_STUDY_WORDS + WORKSPACE_CLOSE_WORDS) or
        any(inp.startswith(prefix) for prefix in AUTONOMOUS_TASK_RUN_WORDS) or
        any(x in inp for x in AUTONOMOUS_TASK_CANCEL_WORDS) or
        inp.startswith("replay task ") or
        "ollama launch" in inp or any(inp.startswith(prefix) for prefix in OLLAMA_LAUNCH_WORDS) or
        any(x in inp for x in EXIT_APP_WORDS + GOODBYE_WORDS) or
        any(x in inp for x in RESET_MEMORY_WORDS) or
        any(x in inp for x in WINDOWS_OPEN_WORDS) or
        (inp.startswith("press ") and any(x in inp for x in ["ctrl", "alt", "enter", "escape", "tab", "delete", "win"])) or
        "minimize" in inp or "maximize" in inp or "close window" in inp or
        any(x in inp for x in TEACH_COMMAND_WORDS) or
        (aria.voice and any(x in inp for x in LANGUAGE_HINDI_WORDS + LANGUAGE_TELUGU_WORDS + LANGUAGE_ENGLISH_WORDS + LANGUAGE_AUTO_WORDS)) or
        any(x in inp for x in GESTURE_DISABLE_WORDS + GESTURE_ENABLE_WORDS)):
        aria._system_command_dispatcher_helper(inp, user_input)
        return {"handled": True, "action": "system", "response": "system_dispatcher_command"}

    return {"handled": False}


def handle_ar(aria, inp, user_input, image=None):
    from skills.command_patterns import DISABLE_AR_WORDS, AR_MODE_TRIGGERS, AR_ACTIVE_ONLY_TRIGGERS
    from skills.ar_commands import (
        handle_disable_ar_camera, handle_ar_subcommands, handle_start_ar_mode, handle_enable_ar_playground_generic
    )

    # 1. Disable AR triggers
    if any(x in inp for x in DISABLE_AR_WORDS):
        res = handle_disable_ar_camera(aria)
        return {"handled": True, "action": "ar", "response": res}

    # 2. Subcommands check when AR playground is active
    ar_playground_active = getattr(aria, 'ar_mode', False) or getattr(aria, 'ar_playground', None) is not None
    if ar_playground_active and getattr(aria, 'ar_playground', None):
        res = handle_ar_subcommands(aria, inp, user_input)
        if res != "no_matching_ar_subcommand":
            return {"handled": True, "action": "ar", "response": res}

    # 3. Check AR mode triggers to start/switch
    matched_mode = None
    for mode, triggers in AR_MODE_TRIGGERS.items():
        if any(t in inp for t in triggers):
            matched_mode = mode
            break

    if not matched_mode and ar_playground_active:
        for mode, triggers in AR_ACTIVE_ONLY_TRIGGERS.items():
            if any(t in inp for t in triggers):
                matched_mode = mode
                break

    if matched_mode:
        res = handle_start_ar_mode(aria, matched_mode)
        return {"handled": True, "action": "ar", "response": res}

    # 4. Enable AR Playground generic triggers
    if any(x in inp for x in ["enable ar playground", "ar playground on", "start ar mode", "ar mode on",
                              "ar playground", "start ar playground", "enable ar mode",
                              "enable air playground", "air playground on", "start air mode", "air mode on",
                              "air playground", "start air playground", "enable air mode"]):
        res = handle_enable_ar_playground_generic(aria)
        return {"handled": True, "action": "ar", "response": res}

    return {"handled": False}


def handle_browser(aria, inp, user_input, image=None):
    from skills.command_patterns import (
        UI_SWITCH_TO_WORDS, BROWSER_TAB_NEW_WORDS, BROWSER_NEWS_WORDS, BROWSER_TAB_CLOSE_WORDS,
        BROWSER_WINDOW_CLOSE_WORDS, BROWSER_REFRESH_WORDS, BROWSER_BACK_WORDS, BROWSER_FORWARD_WORDS,
        BROWSER_OPEN_APPS_WORDS, PRODUCT_CHEAPEST_WORDS, PLAYWRIGHT_PLAN_WORDS,
        PLAYWRIGHT_CLOSE_WORDS, PLAYWRIGHT_OPEN_WORDS, PLAYWRIGHT_ADD_CART_WORDS,
        PLAYWRIGHT_SUMMARIZE_WORDS, PLAYWRIGHT_FIRST_RESULT_WORDS
    )
    from skills.browser_commands import (
        handle_direct_ui_control, handle_scroll_command, handle_playwright_browser_actions
    )

    # Check deterministic browser request first
    if aria._handle_deterministic_browser_request(user_input):
        return {"handled": True, "action": "browser", "response": "deterministic_browser_request"}

    # Direct UI Control / Tab / Window
    if (any(x in inp for x in UI_SWITCH_TO_WORDS) or
        any(x in inp for x in BROWSER_TAB_NEW_WORDS + BROWSER_NEWS_WORDS + BROWSER_TAB_CLOSE_WORDS +
                            BROWSER_WINDOW_CLOSE_WORDS + BROWSER_REFRESH_WORDS + BROWSER_BACK_WORDS +
                            BROWSER_FORWARD_WORDS + BROWSER_OPEN_APPS_WORDS) or
        ("go to" in inp and any(b in inp for b in ["chrome", "edge", "firefox", "browser"]))):
        res = handle_direct_ui_control(aria, inp, user_input)
        return {"handled": True, "action": "browser", "response": res}

    # Scroll check
    if ("scroll to top" in inp or "scroll to the top" in inp or
        "scroll to bottom" in inp or "scroll to the bottom" in inp or
        "scroll down a little" in inp or "scroll a little down" in inp or "scroll a little" in inp or
        "scroll up a little" in inp or "scroll a little up" in inp or
        "scroll down more" in inp or "scroll more down" in inp or "scroll more" in inp or
        "scroll up more" in inp or "scroll more up" in inp or
        "scroll down" in inp or "scroll up" in inp or
        "page down" in inp or "page up" in inp):
        res = handle_scroll_command(aria, inp, user_input)
        return {"handled": True, "action": "browser", "response": res}

    # Playwright autonomous / specific actions
    has_complex_keyword = any(w in inp.split() for w in ["and", "under"]) or "summarize" in inp
    is_complex = ("amazon" in inp or "youtube" in inp or "wikipedia" in inp or "google" in inp) and has_complex_keyword

    if (any(inp.startswith(t) for t in PLAYWRIGHT_PLAN_WORDS) or is_complex or
        any(x in inp for x in PLAYWRIGHT_CLOSE_WORDS + PLAYWRIGHT_OPEN_WORDS + PLAYWRIGHT_ADD_CART_WORDS + PLAYWRIGHT_SUMMARIZE_WORDS) or
        inp.startswith("go to ") or inp.startswith("navigate to ") or
        "search amazon for " in inp or "amazon search " in inp or
        "search youtube for " in inp or "youtube search " in inp or
        any(x in inp for x in PLAYWRIGHT_FIRST_RESULT_WORDS) or
        ("fill " in inp and " with " in inp) or
        ("type " in inp and " in " in inp) or
        ("enter " in inp and " in " in inp) or
        (any(x in inp for x in PRODUCT_CHEAPEST_WORDS) and any(x in inp for x in ["page", "this", "keyboard", "product"]))):
        res = handle_playwright_browser_actions(aria, inp, user_input)
        return {"handled": True, "action": "browser", "response": res}

    return {"handled": False}


def handle_identity(aria, inp, user_input, image=None):
    from skills.command_patterns import LEARN_FACE_WORDS, FACE_ID_TRIGGERS, LEARN_FACE_INTRO_WORDS
    from skills.identity_commands import check_face_intro_trigger, check_this_is_face, enroll_face, face_mode

    # 1. introduction & enrollment triggers
    face_trigger_found = None
    for t in LEARN_FACE_WORDS:
        if t in inp:
            face_trigger_found = t
            break

    if not face_trigger_found:
        for t in LEARN_FACE_INTRO_WORDS:
            if t in inp:
                face_trigger_found = check_face_intro_trigger(aria, inp, t)
                if face_trigger_found:
                    break

    if not face_trigger_found and "this is " in inp:
        is_face = check_this_is_face(aria, inp)
        if is_face:
            face_trigger_found = "this is me" if "me" in inp else "this is "

    if face_trigger_found:
        res = enroll_face(aria, inp, face_trigger_found, user_input)
        return {"handled": True, "action": "identity", "response": res}

    # 2. Camera mode toggle / identify around
    if any(x in inp for x in ["face mode", "person mode", "recognize me", "show me myself"] + FACE_ID_TRIGGERS) and not any(ar in inp for ar in ["ar ", "air "]):
        res = face_mode(aria, inp, user_input, image=image)
        return {"handled": True, "action": "identity", "response": res}

    return {"handled": False}


def handle_memory(aria, inp, user_input, image=None):
    from skills.command_patterns import (
        REMINDER_ADD_WORDS, REMINDER_GET_WORDS, REMINDER_CLEAR_WORDS, FOLDER_REMEMBER_WORDS,
        PERSONAL_BRAIN_WORDS, GUIDE_ME_WORDS, OPEN_FOLDER_WORDS, WHATSAPP_SEND_WORDS, WHATSAPP_MESSAGE_WORDS,
        ROOM_LEARN_TRIGGERS, ROOM_QUERY_TRIGGERS, OBJECT_IDENTIFY_TRIGGERS, SCREENSHOT_TAKE_WORDS,
        SCREEN_READ_TRIGGERS, SMART_CLICK_TRIGGERS, OBJECT_LIST_WORDS, LEARN_OBJECT_WORDS
    )
    from skills.memory_commands import (
        handle_reminders, handle_folders_whatsapp, handle_personal_notes_pc_status,
        handle_screen_screenshot_vision, enroll_object, handle_room_learning, handle_object_identification
    )

    # 1. Reminders
    if (any(x in inp for x in REMINDER_ADD_WORDS + REMINDER_GET_WORDS + REMINDER_CLEAR_WORDS)):
        res = handle_reminders(aria, inp, user_input)
        return {"handled": True, "action": "memory", "response": res}

    # 2. Folders and WhatsApp
    if (any(x in inp for x in FOLDER_REMEMBER_WORDS + OPEN_FOLDER_WORDS + WHATSAPP_SEND_WORDS + WHATSAPP_MESSAGE_WORDS)):
        res = handle_folders_whatsapp(aria, inp, user_input)
        return {"handled": True, "action": "memory", "response": res}

    # 3. Personal Notes, Goals, Prefs, guides, PC status
    if (any(x in inp for x in PERSONAL_BRAIN_WORDS + GUIDE_ME_WORDS) or
        any(aria.normalizer_val.lower().startswith(prefix) if hasattr(aria, 'normalizer_val') else inp.startswith(prefix) for prefix in ["remember that ", "remember i ", "remember my ", "i need to ", "i have to ", "i should ", "i want to "]) or
        any(aria.normalizer_val.lower().startswith(prefix) if hasattr(aria, 'normalizer_val') else inp.startswith(prefix) for prefix in ["i don't need to ", "i dont need to ", "i should not ", "don't let me ", "dont let me ", "my goal is ", "goal is ", "i like ", "i prefer ", "my preference is "]) or
        any(x in inp for x in ["pc status", "system status", "check status", "how is my pc", "pc context", "battery"])):
        res = handle_personal_notes_pc_status(aria, inp, user_input)
        return {"handled": True, "action": "memory", "response": res}

    # 4. Screenshots & Screen description
    if (any(x in inp for x in SCREENSHOT_TAKE_WORDS + SCREEN_READ_TRIGGERS + SMART_CLICK_TRIGGERS) or
        (("click" in inp or "tap" in inp or "press" in inp or "open" in inp) and any(w in inp for w in ["corner", "center", "middle", "left", "right", "top", "bottom", "taskbar", "start", "desktop", "tray", "close button", "minimize", "maximize button"])) or
        any(x in inp for x in ["what's on my screen", "what is on my screen", "read my screen", "what do you see on screen"])):
        res = handle_screen_screenshot_vision(aria, inp, user_input)
        return {"handled": True, "action": "memory", "response": res}

    # 5. Smart learning (Objects only)
    object_trigger_found = None
    for t in LEARN_OBJECT_WORDS:
        if t in inp:
            object_trigger_found = t
            break

    if not object_trigger_found and "this is " in inp:
        is_face = check_this_is_face(aria, inp)
        if not is_face:
            object_trigger_found = "this is "

    if object_trigger_found:
        res = enroll_object(aria, inp, object_trigger_found, user_input)
        return {"handled": True, "action": "memory", "response": res}

    # 6. Room learn & query
    if (any(t in inp for t in ROOM_LEARN_TRIGGERS) or
        (image is None and any(x in inp for x in ROOM_QUERY_TRIGGERS))):
        res = handle_room_learning(aria, inp, user_input, image=image)
        return {"handled": True, "action": "memory", "response": res}

    # 7. Object identify & listing
    if (((image is None and aria._is_camera_visual_question(inp)) or
         (image is None and any(x in inp for x in OBJECT_IDENTIFY_TRIGGERS)) or
         any(x in inp for x in OBJECT_LIST_WORDS + ["object mode", "thing mode", "identify objects", "show objects"]))):
        res = handle_object_identification(aria, inp, user_input, image=image)
        return {"handled": True, "action": "memory", "response": res}

    return {"handled": False}
