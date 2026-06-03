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


def handle_chief_of_staff(aria, inp, user_input, image=None):
    """
    Handles Chief of Staff voice commands:
    - Daily briefing / morning briefing / what's my status
    - Project priority / what should I work on
    - Mark task done / complete task
    - Add blocker / remove blocker
    - Update project focus
    - Log milestone
    """

    # ─ Personal OS Life Briefing ─
    LIFE_OS_TRIGGERS = [
        "life briefing", "personal system status", "personal status", "system balance"
    ]
    if any(t in inp for t in LIFE_OS_TRIGGERS):
        try:
            from skills.personal_os_reasoning import PersonalOSReasoningEngine
            pos = PersonalOSReasoningEngine()
            pressures = pos.compute_systemic_pressures()
            
            speech = f"Personal OS metrics compiled, Chinmay. Your biological energy rating is sitting at {pressures['raw_energy_score']} percent, "
            speech += f"with an overall life load score of {pressures['overall_life_load']} out of one point zero. "
            
            if "ACADEMIC_GUARD" in pressures["active_guards"]:
                speech += "Academic Guard is currently deployed. Project priorities are lowered to protect upcoming examination targets. "
            if "BURNOUT_PROTECTION" in pressures["active_guards"]:
                speech += "Burnout Protection is active, meaning I will prioritize short quick wins to avoid focus fatigue tonight. "
            if not pressures["active_guards"]:
                speech += "All strategic vectors look incredibly clean and balanced tonight."
                
            # Print detailed values on the console
            print("\n== PERSONAL OPERATING SYSTEM INTELLIGENCE ==\n"
                  f"Academic Pressure: {pressures['academic_pressure']:.2f}\n"
                  f"Energy Pressure:   {pressures['energy_pressure']:.2f}\n"
                  f"Routine Pressure:  {pressures['routine_pressure']:.2f}\n"
                  f"Overall Life Load: {pressures['overall_life_load']:.2f}\n"
                  f"Active Guards:     {', '.join(pressures['active_guards']) if pressures['active_guards'] else 'None'}\n")
                  
            aria._speak(speech)
        except Exception as e:
            aria._speak(f"Personal OS briefing error: {e}")
        return {"handled": True, "action": "chief_of_staff", "response": "life_briefing"}

    # ─ Daily Briefing triggers ─
    BRIEFING_TRIGGERS = [
        "daily briefing", "morning briefing", "give me a briefing",
        "what's my status", "what is my status", "project status",
        "briefing", "chief of staff", "status report", "project report",
        "morning report", "what should i work on today", "what's the plan"
    ]
    if any(t in inp for t in BRIEFING_TRIGGERS):
        try:
            from skills.daily_briefing import DailyBriefing
            owner = getattr(aria, "known_user", "Chinmay").capitalize()
            briefing_text = DailyBriefing().generate_short(owner_name=owner)
            aria._speak(briefing_text)
        except Exception as e:
            aria._speak(f"I couldn't generate the briefing right now. Error: {e}")
        return {"handled": True, "action": "chief_of_staff", "response": "daily_briefing"}

    # ─ Decision Engine / ROI Task Recommendation ─
    DECISION_TRIGGERS = [
        "what should i work on tonight", "what should i work on",
        "what should i do tonight", "what's my next move", "decide for me", "best task"
    ]
    if any(t in inp for t in DECISION_TRIGGERS):
        try:
            from skills.decision_engine import AriaDecisionEngine
            decision = AriaDecisionEngine().analyze_best_move()
            if decision["type"] == "CRITICAL_BLOCKER":
                resp = f"Warning! Project {decision['project'].replace('_', ' ')} is currently blocked. You should focus on resolving the blocker: {decision['reason']}"
            elif decision["type"] == "REST":
                resp = decision["reason"]
            else:
                resp = f"I recommend you work on the task: {decision['task']} in project {decision['project'].replace('_', ' ')}. Reasoning: {decision['reason']}"
            aria._speak(resp)
        except Exception as e:
            aria._speak(f"Decision engine error: {e}")
        return {"handled": True, "action": "chief_of_staff", "response": "decision_query"}

    # ─ Goal Drift Detection ─
    DRIFT_TRIGGERS = [
        "check goal drift", "any neglected goals", "check drift", "drift detector"
    ]
    if any(t in inp for t in DRIFT_TRIGGERS):
        try:
            from skills.drift_detector import AriaDriftDetector
            drifts = AriaDriftDetector().analyze_drift(threshold_days=7)
            if drifts:
                resp = "I've detected drift in the following goals: "
                for d in drifts:
                    resp += f"Project {d['entity'].replace('_', ' ')} has been idle for {d['days_idle']} days, last tracked via {d['last_tracked_via']}. "
            else:
                resp = "All goals are currently on track. No drift detected in the last seven days."
            aria._speak(resp)
        except Exception as e:
            aria._speak(f"Drift detector error: {e}")
        return {"handled": True, "action": "chief_of_staff", "response": "drift_query"}

    # ─ Weekly Review Summary ─
    WEEKLY_TRIGGERS = [
        "weekly review", "how was my week", "sunday review"
    ]
    if any(t in inp for t in WEEKLY_TRIGGERS):
        try:
            from skills.weekly_review import AriaWeeklyReview
            report = AriaWeeklyReview().compile_weekly_report()
            cleaned_report = report.replace("==", "").strip()
            print(f"\n{report}\n")
            aria._speak("I've compiled your weekly executive review on the console. Momentum winner is listed, along with neglected goals and accomplishments.")
        except Exception as e:
            aria._speak(f"Weekly review error: {e}")
        return {"handled": True, "action": "chief_of_staff", "response": "weekly_review"}

    # ─ Risk Projections & Warnings ─
    RISK_TRIGGERS = [
        "project risk", "what is at risk", "predict bottlenecks", "which project is most at risk"
    ]
    if any(t in inp for t in RISK_TRIGGERS):
        try:
            from skills.risk_predictor import AriaRiskPredictor
            predictor = AriaRiskPredictor()
            reports = predictor.analyze_all_risks()
            
            unstable = [r for r in reports if r["tier"] in ["ELEVATED", "CRITICAL"]]
            
            if "most at risk" in inp:
                if reports:
                    sorted_reports = sorted(reports, key=lambda x: x["risk_score"], reverse=True)
                    most_risk = sorted_reports[0]
                    if most_risk["risk_score"] > 0.1:
                        resp = (
                            f"The project most at risk is {most_risk['project'].replace('_', ' ')} "
                            f"with a risk score of {most_risk['risk_score']} out of one point zero, putting it in the {most_risk['tier']} risk tier. "
                            f"The main catalyst is: {most_risk['catalysts'][0]}"
                        )
                    else:
                        resp = "All projects are currently fully stable. No active risks detected."
                else:
                    resp = "I couldn't find any active projects to analyze risk for."
            else:
                if not unstable:
                    resp = "All projects are projecting as stable, Chinmay. Momentum vectors look clean across the board."
                else:
                    resp = "I've flagged potential risks on the following: "
                    for r in unstable:
                        resp += f"The {r['project'].replace('_', ' ')} vector is currently {r['tier']} with a score of {r['risk_score']}. Primary warning: {r['catalysts'][0]} "
            aria._speak(resp)
        except Exception as e:
            aria._speak(f"Risk predictor error: {e}")
        return {"handled": True, "action": "chief_of_staff", "response": "risk_query"}

    # ─ Opportunity queries ─
    OPPORTUNITY_TRIGGERS = [
        "any opportunities", "strategic ideas", "generate insights", "check opportunities"
    ]
    if any(t in inp for t in OPPORTUNITY_TRIGGERS):
        try:
            from skills.opportunity_detector import AriaOpportunityDetector
            detector = AriaOpportunityDetector()
            ideas = detector.log_and_rank_all()
            if not ideas:
                resp = "No explicit multi-node connections found in the graph right now, Chinmay. Keep updating my memory as ideas develop."
            else:
                top = ideas[0]
                resp = f"I found a strategic opportunity: {top['title']}. {top['description']}"
            aria._speak(resp)
        except Exception as e:
            aria._speak(f"Opportunity detector error: {e}")
        return {"handled": True, "action": "chief_of_staff", "response": "opportunity_query"}

    # ─ Feedback routing (accept/dismiss) ─
    import re
    feedback_match = re.search(r'(accept|dismiss)\s+opportunity\s+(.+)', inp, re.IGNORECASE)
    if feedback_match:
        action = feedback_match.group(1).strip().lower()
        title_query = feedback_match.group(2).strip()
        try:
            from skills.opportunity_detector import AriaOpportunityDetector
            detector = AriaOpportunityDetector()
            # Match title query against existing opportunities (case-insensitive substring match)
            import sqlite3
            conn = sqlite3.connect(detector.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT title FROM project_opportunity_history")
            all_titles = [r[0] for r in cursor.fetchall()]
            conn.close()
            
            matched_title = None
            for t in all_titles:
                if title_query.lower() in t.lower():
                    matched_title = t
                    break
            
            if matched_title:
                detector.process_opportunity_feedback(matched_title, action + "ed")
                aria._speak(f"Opportunity '{matched_title}' marked as {action}ed. Modifiers updated.")
            else:
                aria._speak(f"I couldn't find any generated opportunity matching '{title_query}'.")
        except Exception as e:
            aria._speak(f"Feedback processing error: {e}")
        return {"handled": True, "action": "chief_of_staff", "response": "opportunity_feedback"}

    # ─ Strategic Reflection patterns query ─
    REFLECTION_TRIGGERS = [
        "strategic reflection", "analyze patterns", "what are my habits", "reflection analyzer"
    ]
    if any(t in inp for t in REFLECTION_TRIGGERS):
        try:
            from skills.strategic_reflection import AriaStrategicReflection
            reflector = AriaStrategicReflection()
            rep = reflector.generate_reflection_report()
            
            # Formulate speech
            speech = "I have completed a strategic reflection over our execution history. "
            # Execution pattern
            exec_p = rep["execution_patterns"][0]
            speech += f"{exec_p} "
            # Blocker trend
            risk_p = rep["risk_patterns"][0]
            speech += f"My risk trend sweep notes that: {risk_p} "
            # Recommendation
            speech += f"To optimize your current workflow, my recommendation is: {rep['recommendation']}"
            
            # Print full formatted report to terminal for visibility
            full_report = reflector.get_reflection_context_string()
            print(f"\n{full_report}\n")
            
            aria._speak(speech)
        except Exception as e:
            aria._speak(f"Strategic reflection error: {e}")
        return {"handled": True, "action": "chief_of_staff", "response": "strategic_reflection"}



    # ─ Priority question ─
    PRIORITY_TRIGGERS = [
        "what's my top priority", "what is my top priority",
        "highest priority", "most important task", "what should i focus on"
    ]
    if any(t in inp for t in PRIORITY_TRIGGERS):
        try:
            from skills.priority_engine import PriorityEngine
            top = PriorityEngine().get_top_priority()
            if top:
                resp = (
                    f"Your highest priority is {top['project'].replace('_', ' ')} "
                    f"with a score of {top['priority_score']} out of ten. "
                    f"Current focus: {top['focus']}. Reason: {top['reason']}."
                )
            else:
                resp = "I couldn't determine a top priority. Make sure you have active projects."
            aria._speak(resp)
        except Exception as e:
            aria._speak(f"Priority engine error: {e}")
        return {"handled": True, "action": "chief_of_staff", "response": "priority_query"}

    # ─ Mark task done (e.g. "mark Native Android STT as done") ─
    import re
    done_match = re.search(
        r'(?:mark|complete|finish|done with|finished)\s+(.+?)\s+(?:as done|as complete|complete|done|finished)$',
        inp, re.IGNORECASE
    )
    if done_match:
        task_name = done_match.group(1).strip()
        try:
            from skills.project_state_manager import ProjectStateManager
            psm = ProjectStateManager()
            # Try to find which project contains this task
            projects = psm.get_all_projects()
            result = None
            for proj_name, proj_data in projects.items():
                pending_raw = proj_data.get("pending_tasks", [])
                pending = [(t["task_name"] if isinstance(t, dict) else t).lower() for t in pending_raw]
                if task_name.lower() in pending:
                    # Match the correct case and type
                    real_task_obj = next(t for t in pending_raw if (t["task_name"] if isinstance(t, dict) else t).lower() == task_name.lower())
                    real_task_name = real_task_obj["task_name"] if isinstance(real_task_obj, dict) else real_task_obj
                    result = psm.complete_task(proj_name, real_task_name)
                    break
            if result:
                aria._speak(f"Got it. I've marked '{task_name}' as complete. {result}")
            else:
                aria._speak(f"I couldn't find a task called '{task_name}' in your pending lists.")
        except Exception as e:
            aria._speak(f"Error completing task: {e}")
        return {"handled": True, "action": "chief_of_staff", "response": "task_complete"}

    # ─ Add blocker (e.g. "add blocker Android SDK missing") ─
    blocker_match = re.search(r'(?:add blocker|log blocker|there\'?s? a blocker|blocked by)\s+(.+)', inp, re.IGNORECASE)
    if blocker_match:
        blocker_text = blocker_match.group(1).strip()
        try:
            from skills.project_state_manager import ProjectStateManager
            psm = ProjectStateManager()
            ranked = list(psm.get_all_projects().keys())
            if ranked:
                top_project = ranked[0]
                result = psm.add_blocker(top_project, blocker_text)
                aria._speak(f"Blocker logged for {top_project.replace('_', ' ')}: {blocker_text}")
            else:
                aria._speak("No active projects found to attach the blocker to.")
        except Exception as e:
            aria._speak(f"Error logging blocker: {e}")
        return {"handled": True, "action": "chief_of_staff", "response": "blocker_added"}

    # ─ Log milestone (e.g. "log milestone Phase 4 complete") ─
    milestone_match = re.search(r'(?:log milestone|milestone|achieved)\s+(.+)', inp, re.IGNORECASE)
    if milestone_match:
        milestone_text = milestone_match.group(1).strip()
        try:
            from skills.project_state_manager import ProjectStateManager
            psm = ProjectStateManager()
            projects = psm.get_all_projects()
            if projects:
                top_project = list(projects.keys())[0]
                psm.log_milestone(top_project, milestone_text, importance=9)
                aria._speak(f"Milestone logged: {milestone_text}. Added to {top_project.replace('_', ' ')} timeline.")
            else:
                aria._speak("No active projects to log a milestone for.")
        except Exception as e:
            aria._speak(f"Error logging milestone: {e}")
        return {"handled": True, "action": "chief_of_staff", "response": "milestone_logged"}

    # ─ Update focus (e.g. "update focus to Face confidence tuning") ─
    focus_match = re.search(r'(?:update focus to|focus on|switch focus to|change focus to)\s+(.+)', inp, re.IGNORECASE)
    if focus_match:
        new_focus = focus_match.group(1).strip()
        try:
            from skills.project_state_manager import ProjectStateManager
            psm = ProjectStateManager()
            projects = psm.get_all_projects()
            if projects:
                top_project = list(projects.keys())[0]
                psm.update_focus(top_project, new_focus)
                aria._speak(f"Focus updated to '{new_focus}' for {top_project.replace('_', ' ')}.")
            else:
                aria._speak("No active project to update focus for.")
        except Exception as e:
            aria._speak(f"Error updating focus: {e}")
        return {"handled": True, "action": "chief_of_staff", "response": "focus_updated"}

    return {"handled": False}

