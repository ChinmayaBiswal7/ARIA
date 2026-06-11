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
    import re
    from skills.command_patterns import (
        REMINDER_ADD_WORDS, REMINDER_GET_WORDS, REMINDER_CLEAR_WORDS, FOLDER_REMEMBER_WORDS,
        PERSONAL_BRAIN_WORDS, GUIDE_ME_WORDS, LAST_SESSION_WORDS, OPEN_FOLDER_WORDS, WHATSAPP_SEND_WORDS, WHATSAPP_MESSAGE_WORDS,
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
    if (any(x in inp for x in PERSONAL_BRAIN_WORDS + GUIDE_ME_WORDS + LAST_SESSION_WORDS) or
        any(aria.normalizer_val.lower().startswith(prefix) if hasattr(aria, 'normalizer_val') else inp.startswith(prefix) for prefix in ["remember that ", "remember i ", "remember my ", "i need to ", "i have to ", "i should ", "i want to "]) or
        any(aria.normalizer_val.lower().startswith(prefix) if hasattr(aria, 'normalizer_val') else inp.startswith(prefix) for prefix in ["i don't need to ", "i dont need to ", "i should not ", "don't let me ", "dont let me ", "my goal is ", "goal is ", "i like ", "i prefer ", "my preference is "]) or
        any(x in inp for x in ["pc status", "system status", "check status", "how is my pc", "pc context", "battery"]) or
        re.search(r"(cpu|ram|memory|battery|system|disk).*(usage|status|stats|percent|level|info|how much)", user_input.lower()) or
        re.search(r"(how (much|many)|what).*(cpu|ram|memory|battery|disk)", user_input.lower())):
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

    # ─ Chief of Staff Status / Executive Audit ─
    COS_STATUS_TRIGGERS = [
        "chief of staff status", "executive audit", "cos status", "chief of staff report"
    ]
    if any(t in inp for t in COS_STATUS_TRIGGERS):
        try:
            from skills.blackboard import AriaBlackboard
            blackboard = AriaBlackboard()
            # Read the latest cached decision block from the blackboard
            latest_decision_key = "executive_decision_AUTO_CLOCK"
            record = blackboard.read("coach", latest_decision_key)
            
            if not record:
                # Try finding any general decision log
                all_coach = blackboard.get_all("coach").get("coach", {})
                for key, val in all_coach.items():
                    if key.startswith("executive_decision_"):
                        record = val.get("value")
                        break
            
            if not record:
                speech = "The Chief of Staff Agent is currently idling inside her routine background monitoring loops, Chinmaya."
                aria._speak(speech)
                print(speech)
            else:
                decision = record.get("decision", record)
                actions = decision.get("actions", decision.get("actions_to_take", []))
                reasoning = decision.get("strategic_reasoning", "No anomalies detected.")
                at_risk = decision.get("campaign_at_risk", False)
                campaign_id = decision.get("target_campaign_id", "None")
                
                actions_str = ", ".join([f"{a.get('action_type')} ({a.get('target_agent')}): {a.get('payload_description')}" for a in actions])
                
                speech = f"Chief of Staff report compiled. Stance: {'Action deployed' if at_risk else 'Nominal constraints'}. Reasoning: {reasoning}"
                if actions:
                    speech += f" Executed actions: {actions_str}."
                else:
                    speech += " No overrides deployed."
                
                # Print detailed values on the console
                print("\n== CHIEF OF STAFF EXECUTIVE AUDIT ==\n"
                      f"Campaign ID:  {campaign_id}\n"
                      f"At Risk:      {at_risk}\n"
                      f"Reasoning:    {reasoning}\n"
                      f"Actions:\n" + "\n".join([f"  - {a.get('action_type')} targeting {a.get('target_agent')}: {a.get('payload_description')}" for a in actions]) + "\n")
                      
                aria._speak(speech)
        except Exception as e:
            aria._speak(f"Chief of staff status error: {e}")
        return {"handled": True, "action": "chief_of_staff", "response": "cos_status"}

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


def handle_email(aria, inp, user_input, image=None):
    import re
    inp_clean = inp.lower().strip()
    
    # 1. Check if we have an active conversational confirmation flow for email
    pending_draft_id = getattr(aria, "_pending_email_draft_id", None)
    if pending_draft_id is not None:
        # Clear the flag so it doesn't persist beyond this conversational turn
        setattr(aria, "_pending_email_draft_id", None)
        
        from skills.email_skill import AriaEmailSkill
        email_skill = AriaEmailSkill()
        
        # Negative/cancel response first to prevent false-positives (e.g. "don't send" matching "send")
        if any(w in inp_clean for w in ["no", "cancel", "abort", "don't", "delete"]):
            email_skill.cancel_draft(pending_draft_id)
            aria._speak("Email draft cancelled and cleared.")
            return {"handled": True, "action": "email", "response": "draft_cancelled"}
            
        # Affirmative response
        elif any(w in inp_clean for w in ["yes", "confirm", "send", "approve", "go ahead", "do it", "sure"]):
            aria._speak("Sending email now...")
            res = email_skill.execute_send(pending_draft_id, approved_by="voice")
            if res == "SUCCESS":
                aria._speak("Email sent successfully!")
                return {"handled": True, "action": "email", "response": "email_sent_success"}
            else:
                aria._speak(f"Failed to send email. {res}")
                return {"handled": True, "action": "email", "response": f"send_failed_{res}"}
            
        # Any other input: we clear the pending state, but do NOT mark handled so it passes through
        print(f"[EmailCommands] Email confirmation follow-up cancelled because input '{inp}' did not match yes/no.")

    # 2. Check if we have a stashed email draft waiting for a recipient email address
    stashed_draft = getattr(aria, "_stashed_email_draft", None)
    if stashed_draft is not None:
        from skills.email_commands import EMAIL_REGEX
        # Try to extract an email address from the user's input
        emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', inp)
        if emails:
            email_candidate = emails[0].strip()
            if re.match(EMAIL_REGEX, email_candidate):
                setattr(aria, "_stashed_email_draft", None)
                from skills.email_skill import AriaEmailSkill
                email_skill = AriaEmailSkill()
                draft_id = email_skill.stage_email_draft(
                    email_candidate, 
                    stashed_draft["subject"], 
                    stashed_draft["body"], 
                    created_by="voice_command"
                )
                aria._pending_email_draft_id = draft_id
                
                readback = (
                    f"Staged email draft for {email_candidate}.\n\n"
                    f"Subject:\n{stashed_draft['subject']}\n\n"
                    f"Recipient:\n{email_candidate}\n\n"
                    "Would you like me to send it? You can speak confirmation or perform a thumbs-up gesture."
                )
                aria._speak(readback)
                return {"handled": True, "action": "email", "response": "stage_email_success"}
            else:
                aria._speak("That doesn't appear to be a valid email address.")
                return {"handled": True, "action": "email", "response": "invalid_email"}
        elif "@" in inp or "." in inp:
            aria._speak("That doesn't appear to be a valid email address.")
            return {"handled": True, "action": "email", "response": "invalid_email"}

    # 3. Check general email triggers
    email_triggers = [
        "confirm email", "send email", "approve email",
        "cancel email", "abort email", "delete draft",
        "send today's report", "email me today's report", "send today's aria report",
        "email to", "draft email", "send email to", "send an email", "write an email"
    ]
    
    if any(t in inp_clean for t in email_triggers) or inp_clean.startswith("email "):
        from skills.email_commands import handle_email as handle_email_cmd
        res = handle_email_cmd(aria, inp, user_input)
        return {"handled": True, "action": "email", "response": res}
        
    return {"handled": False}


def handle_screen_triage_wrapper(aria, inp, user_input, image=None):
    from skills.command_patterns import SCREEN_TRIAGE_TRIGGERS
    from skills.screen_triage import handle_screen_triage, AriaScreenTriage
    
    triage = AriaScreenTriage()
    
    # 1. If there's an active confirmation block staged, intercept immediately
    if triage.pending_fix is not None:
        return handle_screen_triage(aria, inp, user_input, image=image)
        
    # 2. Or check explicit triggers
    if any(t in inp for t in SCREEN_TRIAGE_TRIGGERS):
        return handle_screen_triage(aria, inp, user_input, image=image)
        
    return {"handled": False}


def handle_cognitive_planning(aria, inp, user_input, image=None):
    from skills.command_patterns import COGNITIVE_PLANNING_TRIGGERS
    from skills.learning_skill import AriaLearningSkill
    
    if any(t in inp for t in COGNITIVE_PLANNING_TRIGGERS):
        clean_goal = user_input.lower().replace("help me study for", "").replace("help me prepare for", "").replace("study plan for", "").replace("plan the goal", "").replace("orchestrate task", "").strip()
        skill = AriaLearningSkill()
        res = skill.orchestrate_study_goal(aria, clean_goal)
        return {"handled": True, "action": "learning_skill", "response": res}
        
    return {"handled": False}


def handle_career(aria, inp, user_input, image=None):
    from skills.career_agent import CareerAgent
    import re
    inp_clean = inp.lower().strip()
    
    # Check if there's a match for bookmarking a job
    bookmark_match = re.search(r'(?:bookmark|add)\s+job:?\s*(.+?)\s*-\s*(.+?)\s*-\s*(http\S+)', user_input, re.IGNORECASE)
    if bookmark_match:
        company = bookmark_match.group(1).strip()
        role = bookmark_match.group(2).strip()
        link = bookmark_match.group(3).strip()
        
        agent = CareerAgent()
        opp_id = agent.add_opportunity(company=company, role=role, apply_link=link, source_type='MANUAL')
        aria._speak(f"Successfully bookmarked job: {role} at {company} (ID: {opp_id}). Firestore synced.")
        return {"handled": True, "action": "career", "response": "job_bookmarked"}

    # Update job status
    status_match = re.search(r'(?:update|set)\s+job\s+(\d+)\s+(?:status\s+)?to\s+(bookmarked|applied|interviewing|rejected|offered)', inp_clean, re.IGNORECASE)
    if status_match:
        opp_id = int(status_match.group(1))
        new_status = status_match.group(2).strip()
        
        agent = CareerAgent()
        opp = agent.get_opportunity(opp_id)
        if opp:
            agent.update_opportunity(opp_id, {"status": new_status})
            aria._speak(f"Job application status for {opp['company']} ({opp['role']}) updated to {new_status}.")
        else:
            aria._speak(f"Could not find a job opportunity with ID {opp_id}.")
        return {"handled": True, "action": "career", "response": "job_status_updated"}


    # Codeforces stats
    if "codeforces stats" in inp_clean:
        username = "chinmaya"
        name_match = re.search(r'codeforces stats for\s+(\S+)', inp_clean, re.IGNORECASE)
        if name_match:
            username = name_match.group(1).strip()
        else:
            agent = CareerAgent()
            try:
                with agent._get_connection() as conn:
                    row = conn.execute("SELECT value FROM user_preferences WHERE key = 'codeforces_username'").fetchone()
                    if row: username = row['value']
            except Exception:
                pass
                
        agent = CareerAgent()
        stats = agent.get_codeforces_stats(username)
        if stats and not stats.get("error"):
            resp = f"Codeforces stats for {username}: Rating is {stats['rating']} (Max: {stats['max_rating']}). Rank: {stats['rank']} (Max: {stats['max_rank']})."
            aria._speak(resp)
        else:
            aria._speak(f"Failed to retrieve Codeforces stats for {username}: {stats.get('error', 'Unknown error')}")
        return {"handled": True, "action": "career", "response": "codeforces_stats"}

    # GitHub stats
    if "github stats" in inp_clean:
        username = "chinmaya"
        name_match = re.search(r'github stats for\s+(\S+)', inp_clean, re.IGNORECASE)
        if name_match:
            username = name_match.group(1).strip()
        else:
            agent = CareerAgent()
            try:
                with agent._get_connection() as conn:
                    row = conn.execute("SELECT value FROM user_preferences WHERE key = 'github_username'").fetchone()
                    if row: username = row['value']
            except Exception:
                pass
                
        agent = CareerAgent()
        stats = agent.get_github_stats(username)
        if stats and not stats.get("error"):
            resp = f"GitHub stats for {username}: Current Daily Streak is {stats['streak']} day(s). Weekly commits in last 7 days: {stats['weekly_commits']}."
            aria._speak(resp)
        else:
            aria._speak(f"Failed to retrieve GitHub stats for {username}: {stats.get('error', 'Unknown error')}")
        return {"handled": True, "action": "career", "response": "github_stats"}

    # Resume/Job matching
    match_trigger = re.search(r'(?:analyze match for|match job|resume match)\s+(.+)', user_input, re.IGNORECASE | re.DOTALL)
    if match_trigger:
        job_desc = match_trigger.group(1).strip()
        aria._speak("Analyzing job description match against your skills and projects from the Knowledge Graph...")
        
        agent = CareerAgent()
        match_data = agent.match_resume_to_job(job_desc)
        score = match_data.get("match_score", 0)
        matching = match_data.get("matching_skills", [])
        gaps = match_data.get("gaps", [])
        recs = match_data.get("recommendations", [])
        
        resp = f"Evaluation complete. Match score is {score} percent. "
        if matching:
            resp += f"Matching skills identified: {', '.join(matching[:4])}. "
        if gaps:
            resp += f"Identified skill gaps: {', '.join(gaps[:3])}. "
        if recs:
            resp += f"Top recommendation: {recs[0]}"
            
        print(f"\n== RESUME MATCH REPORT ==\nScore: {score}%\nMatching: {matching}\nGaps: {gaps}\nRecs: {recs}\n")
        aria._speak(resp)
        return {"handled": True, "action": "career", "response": "resume_matched"}

    # Search job/internship opportunities
    search_match = re.search(r'(?:find|search|show|get|check|look\s+for)\s+(?:some\s+)?(.+?)\s*(?:internships?|jobs?|vacanc(?:y|ies))', user_input, re.IGNORECASE)
    is_general_search = ("internship" in inp_clean or "job" in inp_clean or "vacancy" in inp_clean) and any(v in inp_clean for v in ["find", "search", "show", "get", "look for"])
    
    if search_match or is_general_search:
        target_query = search_match.group(1).strip() if search_match else user_input
        target_query = re.sub(r'\b(find|search|show|get|check|look|for|some)\b', '', target_query, flags=re.IGNORECASE).strip()
        if not target_query:
            target_query = "tech"
            
        aria._speak(f"Searching public feeds for '{target_query}' opportunities...")
        agent = CareerAgent()
        jobs = agent.search_job_opportunities(target_query)
        if not jobs:
            aria._speak("No matching opportunities found on public feeds.")
        else:
            aria._speak(f"Evaluating profile match scores for the top {len(jobs)} matches...")
            summary = []
            for j in jobs[:3]:
                # Build rich context so LLM can give a meaningful score
                tags_str = ", ".join(j.get("tags", [])) if j.get("tags") else ""
                job_desc = (
                    f"Role: {j['role']}\n"
                    f"Company: {j['company']}\n"
                    f"Location: {j.get('location', 'Remote')}\n"
                    f"Skills / Tags: {tags_str or 'software engineering'}"
                )
                match_res = agent.match_resume_to_job(job_desc)
                score = match_res.get("match_score", 50)
                
                # Add to SQLite database
                opp_id = agent.add_opportunity(
                    company=j["company"],
                    role=j["role"],
                    location=j.get("location"),
                    apply_link=j.get("apply_link"),
                    match_score=float(score),
                    status="bookmarked",
                    source_type="IMPORT"
                )
                
                summary.append(f"{j['role']} at {j['company']} - Match: {score}%")
            
            aria._speak(f"Top matches: {'; '.join(summary)}. Added to your application tracker.")
        return {"handled": True, "action": "career", "response": "job_search"}

    # List career opportunities
    if any(t in inp_clean for t in ["career list", "job list", "my applications", "career applications", "career"]):
        agent = CareerAgent()
        opps = agent.get_opportunities()
        if not opps:
            aria._speak("You have no bookmarked or tracked job applications yet. Say 'bookmark job: Company - Role - Link' to add one.")
        else:
            summary = f"You are currently tracking {len(opps)} career opportunities. "
            top_3 = opps[:3]
            details = []
            for o in top_3:
                details.append(f"{o['role']} at {o['company']} (Status: {o['status']})")
            summary += "Recent items include: " + "; ".join(details) + "."
            
            print("\n== TRACKED CAREER OPPORTUNITIES ==")
            print(f"{'ID':<3} | {'Company':<15} | {'Role':<20} | {'Status':<12} | {'Score':<5} | {'Deadline':<10}")
            print("-" * 75)
            for o in opps:
                score_str = f"{o.get('match_score')}%" if o.get('match_score') else "N/A"
                print(f"{o.get('id'):<3} | {o.get('company')[:15]:<15} | {o.get('role')[:20]:<20} | {o.get('status'):<12} | {score_str:<5} | {o.get('deadline') or 'None':<10}")
            print()
            aria._speak(summary)
        return {"handled": True, "action": "career", "response": "career_list"}

    return {"handled": False}


def handle_orchestration(aria, inp, user_input, image=None):
    from skills.agent_coordinator import AgentCoordinator
    inp_clean = inp.lower().strip()
    
    # Heuristic for complex multitask or explicit orchestration
    # Check if there are multiple verbs in the sentence
    verbs = ["search", "find", "check", "summarize", "monitor", "track", "analyze", "bookmark", "run", "get"]
    count = sum(1 for v in verbs if v in inp_clean)
    has_conjunction = " and " in inp_clean or "," in inp_clean or " then " in inp_clean or " & " in inp_clean
    
    # If the user explicitly uses "orchestrate" or "campaign" or "coordinator"
    is_explicit = "orchestrate" in inp_clean or "campaign" in inp_clean or "coordinator" in inp_clean
    
    if (count >= 2 and has_conjunction) or is_explicit:
        coordinator = AgentCoordinator(aria)
        aria._speak("Decomposing multi-action request into specialized agents...")
        res = coordinator.coordinate_campaign(user_input)
        aria._speak(f"Orchestration completed successfully. Here are the results:\n{res}")
        return {"handled": True, "action": "orchestration", "response": res}
        
    return {"handled": False}


def handle_missions(aria, inp, user_input, image=None):
    inp_clean = inp.lower().strip()
    
    # If the request is to monitor or create a recurring scheduler mission
    if any(t in inp_clean for t in ["monitor", "mission", "track daily", "daily check"]):
        print(f"[MissionManager] Mission created: {user_input}")
        
        # Optionally register this as a task in task manager
        task_manager = getattr(aria.brain, "semantic_router", None)
        if task_manager:
            task_manager = getattr(task_manager, "task_manager", None)
        if task_manager:
            task_manager.start_task(f"Mission: {user_input}")
            
        aria._speak(f"Mission created successfully. Active monitoring has been initiated.")
        return {"handled": True, "action": "missions", "response": "mission_created"}
        
    return {"handled": False}


def handle_vision(aria, inp, user_input, image=None):
    """Voice router handling local sight lookups, screen analysis, room changes, and cloud reasoning escalation."""
    inp_clean = inp.lower().strip()
    
    # Check trigger phrases
    is_what_do_you_see = "what do you see" in inp_clean
    is_scan_room = "scan room" in inp_clean
    is_analyze_camera = "analyze camera" in inp_clean
    is_describe_happening = "describe what is happening" in inp_clean or "describe what's happening" in inp_clean
    
    is_analyze_screen = "what is on my screen" in inp_clean or "what's on my screen" in inp_clean or "analyze screen" in inp_clean or "read screen" in inp_clean or "read text" in inp_clean
    
    is_count_people = "count people" in inp_clean or "how many people" in inp_clean or "number of people" in inp_clean
    is_what_changed = "what changed" in inp_clean or "what has changed" in inp_clean or "what was on my desk" in inp_clean
    is_show_changes = "show last changes" in inp_clean or "show changes" in inp_clean or "visual history" in inp_clean
    is_when_appear = "when did" in inp_clean and ("appear" in inp_clean or "placed" in inp_clean or "arrive" in inp_clean or "on my desk" in inp_clean)
    is_when_removed = "when was" in inp_clean and ("removed" in inp_clean or "disappear" in inp_clean or "vanish" in inp_clean or "taken" in inp_clean or "leave" in inp_clean or "left" in inp_clean)
    is_how_long = "how long has" in inp_clean or "how long was" in inp_clean or "duration of" in inp_clean or "how long have" in inp_clean
    is_profile_status = "profile completeness" in inp_clean or "profile status" in inp_clean or "my profile" in inp_clean
    is_habit_status = "habit statistics" in inp_clean or "productivity report" in inp_clean or "my focus stats" in inp_clean or "habit status" in inp_clean
    is_dataset_status = "dataset status" in inp_clean or "habit dataset size" in inp_clean or "dataset size" in inp_clean
    is_habit_predict = "habit prediction" in inp_clean or "predict next session" in inp_clean or "study forecast" in inp_clean
    is_retrain_model = "retrain habit model" in inp_clean
    
    if (is_what_do_you_see or is_scan_room or is_analyze_camera or is_describe_happening or 
        is_analyze_screen or is_count_people or is_what_changed or is_show_changes or 
        is_when_appear or is_when_removed or is_how_long or is_profile_status or is_habit_status or is_dataset_status or
        is_habit_predict or is_retrain_model):
        
        # Handle historical queries using VisionMemoryAgent
        if (is_what_changed or is_show_changes or is_when_appear or is_when_removed or 
            is_how_long or is_profile_status or is_habit_status or is_dataset_status or
            is_habit_predict or is_retrain_model):
            from skills.agent_registry import registry
            mem_wrapper = registry.get("visionmemoryagent")
            if not mem_wrapper:
                aria._speak("Vision memory agent is not registered.")
                return {"handled": True, "action": "vision", "response": "not_registered"}
            
            mem_agent = mem_wrapper.agent
            response = ""
            
            if is_what_changed:
                response = mem_agent.query_what_changed()
            elif is_show_changes:
                response = mem_agent.query_show_last_changes()
            elif is_when_appear:
                import re
                match = re.search(r"did\s+(?:the\s+)?(.+?)\s+(?:appear|placed|arrive|on)", inp_clean)
                if match:
                    item = match.group(1).strip()
                    response = mem_agent.query_when_appear(item)
                else:
                    words = inp_clean.replace("when did", "").replace("appear", "").replace("placed", "").replace("the", "").strip().split()
                    item = words[0] if words else ""
                    if item:
                        response = mem_agent.query_when_appear(item)
                    else:
                        response = "Could you please specify which object you want to look up, Chinmaya?"
            elif is_when_removed:
                import re
                match = re.search(r"was\s+(?:the\s+)?(.+?)\s+(?:removed|disappear|vanish|taken|leave|left)", inp_clean)
                if match:
                    item = match.group(1).strip()
                    response = mem_agent.query_when_removed(item)
                else:
                    words = inp_clean.replace("when was", "").replace("removed", "").replace("disappear", "").replace("the", "").strip().split()
                    item = words[0] if words else ""
                    if item:
                        response = mem_agent.query_when_removed(item)
                    else:
                        response = "Could you please specify which object you want to look up, Chinmaya?"
            elif is_how_long:
                import re
                match = re.search(r"(?:has|was|is|of|have)\s+(?:the\s+)?(.+?)\s+(?:been|stayed|on|off|present|at|in|left|$)", inp_clean)
                if match:
                    item = match.group(1).strip()
                    response = mem_agent.query_duration(item)
                else:
                    words = inp_clean.replace("how long", "").replace("has", "").replace("was", "").replace("the", "").replace("been", "").strip().split()
                    item = words[0] if words else ""
                    if item:
                        response = mem_agent.query_duration(item)
                    else:
                        response = "Could you please specify which object or person you want to query, Chinmaya?"
            elif is_profile_status:
                try:
                    import sqlite3
                    db_path = "aria_orchestrator.db"
                    conn = sqlite3.connect(db_path)
                    conn.row_factory = sqlite3.Row
                    try:
                        cursor = conn.execute("""
                            SELECT captured_angles_count, recognition_count, lighting_conditions 
                            FROM person_profile_evolution 
                            WHERE LOWER(person_name) = 'chinmaya'
                        """)
                        row = cursor.fetchone()
                    finally:
                        conn.close()
                        
                    if not row:
                        response = "No evolutionary tracking data logged yet for Chinmaya."
                    else:
                        angles = row["captured_angles_count"]
                        total_looks = row["recognition_count"]
                        lights = row["lighting_conditions"]
                        completeness = min(100, int((angles / 30) * 100))
                        response = (
                            f"Profile Evolution Analysis for Chinmaya:\n"
                            f"- Profile Completeness: {completeness}%\n"
                            f"- Captured Angular Nodes: {angles} unique viewpoints registered\n"
                            f"- Distinct Lighting Zones: {lights} conditions tracked\n"
                            f"- Total Verifications: {total_looks} successful validations logged."
                        )
                except Exception as ex:
                    response = f"Failed to retrieve profile evolutionary metrics: {ex}"
            elif is_habit_status:
                try:
                    from skills.blackboard import AriaBlackboard
                    blackboard = AriaBlackboard()
                    stats = blackboard.read("habits", "weekly_analytics")
                    
                    if not stats:
                        response = "I am still compiling your baseline visual timeline data layers, Chinmaya. Continue your normal routines."
                    else:
                        trend_sign = "+" if stats.get("trend_percentage", 0.0) >= 0.0 else ""
                        response = (
                            f"### Productivity Profile & Habit Analytics for Chinmaya:\n"
                            f"- **Productivity Score:** {stats.get('productivity_score', 0)}/100\n"
                            f"- **Verified Focus Runs:** {stats.get('total_sessions', 0)} sessions tracked\n"
                            f"- **Average Work Window:** {stats.get('average_session_minutes', 0)} minutes per session\n"
                            f"- **Peak Production Stretch:** {stats.get('longest_session_minutes', 0)} minutes straight\n"
                            f"- **Weekly Presence Hours:** {stats.get('weekly_presence_hours', 0.0)} hours (last week: {stats.get('last_week_presence_hours', 0.0)}h)\n"
                            f"- **Activity Trend:** {trend_sign}{stats.get('trend_percentage', 0.0)}%\n"
                            f"- **Average Start Time:** {stats.get('average_start_hour', 0):02d}:00\n"
                            f"- **Average End Time:** {stats.get('average_end_hour', 0):02d}:00\n"
                            f"- **Most Active Day:** {stats.get('most_active_day', 'N/A')}\n"
                            f"- **Current Focus Streak:** {stats.get('current_focus_streak', 0)} minutes\n"
                            f"- **Longest Streak:** {stats.get('longest_focus_streak', 0)} minutes\n"
                            f"- **Sessions Today:** {stats.get('sessions_today', 0)}"
                        )
                except Exception as ex:
                    response = f"Failed to retrieve habit analytics: {ex}"
            elif is_dataset_status:
                try:
                    from skills.agent_registry import registry
                    wrapper = registry.get("habitdatasetmonitoragent")
                    if not wrapper:
                        response = "Habit dataset monitor agent is not registered."
                    else:
                        stats_str = wrapper.run("TSK_MON", "get dataset stats", {})
                        stats = json.loads(stats_str)
                        
                        ready_label = "READY" if stats.get("ready_for_neural_training") else "COLLECTING"
                        topics = stats.get("topic_distributions", {})
                        topics_list = [f"  - {k}: {v}" for k, v in topics.items()]
                        topics_str = "\n".join(topics_list) if topics_list else "  - None"
                        
                        gates = stats.get("gates", {})
                        min_gate = gates.get("minimum", {})
                        rec_gate = gates.get("recommended", {})
                        ideal_gate = gates.get("ideal", {})
                        
                        response = (
                            f"### ARIA Habit Dataset Status Dashboard:\n"
                            f"- **Sessions Collected:** {stats.get('total_sessions', 0)} sessions logged\n"
                            f"- **Days Covered:** {stats.get('days_covered', 0)} days\n"
                            f"- **Dataset Status:** {ready_label} (Status: {stats.get('training_status', 'UNKNOWN')})\n"
                            f"\n"
                            f"**Neural Training Gateways:**\n"
                            f"- Minimum Gate (100 sessions / 14 days): {'✅ MET' if min_gate.get('met') else '❌ NOT MET'}\n"
                            f"- Recommended Gate (300 sessions / 21 days): {'✅ MET' if rec_gate.get('met') else '❌ NOT MET'}\n"
                            f"- Ideal Gate (500 sessions / 42 days): {'✅ MET' if ideal_gate.get('met') else '❌ NOT MET'}\n"
                            f"\n"
                            f"**Seeded Study Topic Splits:**\n"
                            f"{topics_str}"
                        )
                except Exception as ex:
                    response = f"Failed to retrieve habit dataset stats: {ex}"
            elif is_habit_predict:
                try:
                    from skills.agent_registry import registry
                    wrapper = registry.get("neuralhabitengineagent")
                    if not wrapper:
                        response = "Neural habit engine agent is not registered."
                    else:
                        forecast_str = wrapper.run("TSK_PRED", "predict habits", {})
                        forecast = json.loads(forecast_str)
                        
                        prob = int(forecast.get("predicted_probability", 0.0) * 100)
                        dur = forecast.get("expected_duration", 0)
                        topic = forecast.get("predicted_topic", "UNKNOWN")
                        conf = int(forecast.get("confidence", 0.0) * 100)
                        recs = forecast.get("recommended_resources", [])
                        
                        recs_str = "\n".join([f"- {r}" for r in recs]) if recs else "- None"
                        
                        now_h = time.localtime().tm_hour
                        ampm = "PM" if now_h >= 12 else "AM"
                        display_h = now_h % 12
                        if display_h == 0:
                            display_h = 12
                        
                        trained_label = "Neural Model" if forecast.get("is_trained") else "Rule-based Fallback (Dormant)"
                        
                        response = (
                            f"You usually begin studying around {display_h} {ampm}.\n\n"
                            f"Predicted topic:\n"
                            f"**{topic}**\n\n"
                            f"Expected duration:\n"
                            f"**{dur} minutes**\n\n"
                            f"Confidence:\n"
                            f"**{conf}%** (Method: {trained_label})\n\n"
                            f"Probability: {prob}%\n\n"
                            f"Recommended Resources:\n"
                            f"{recs_str}"
                        )
                except Exception as ex:
                    response = f"Failed to run habit prediction: {ex}"
            elif is_retrain_model:
                try:
                    from skills.agent_registry import registry
                    monitor_wrapper = registry.get("habitdatasetmonitoragent")
                    if not monitor_wrapper:
                        response = "Habit dataset monitor agent is not registered."
                    else:
                        stats_str = monitor_wrapper.run("TSK_MON", "get dataset stats", {})
                        stats = json.loads(stats_str)
                        is_ready = stats.get("ready_for_neural_training", False)
                        sessions = stats.get("total_sessions", 0)
                        days = stats.get("days_covered", 0)
                        
                        if is_ready:
                            from train_habit_model import run_training_pipeline
                            success = run_training_pipeline()
                            if success:
                                meta_path = "models/habit_predictor_meta.json"
                                accuracy = 1.0
                                val_prob_acc = 1.0
                                dur_mae = 0.0
                                if os.path.exists(meta_path):
                                    with open(meta_path, "r", encoding="utf-8") as f:
                                        meta = json.load(f)
                                    accuracy = meta.get("val_topic_accuracy", meta.get("accuracy", 1.0))
                                    val_prob_acc = meta.get("val_probability_accuracy", 1.0)
                                    dur_mae = meta.get("duration_mae", 0.0)
                                    
                                response = (
                                    f"### Neural Habit Model Retraining Successful!\n"
                                    f"- **Status:** Trained & Saved\n"
                                    f"- **Sessions Utilized:** {sessions}\n"
                                    f"- **Days Covered:** {days}\n"
                                    f"- **Validation Topic Accuracy:** {accuracy * 100:.1f}%\n"
                                    f"- **Validation Probability Accuracy:** {val_prob_acc * 100:.1f}%\n"
                                    f"- **Validation Duration MAE:** {dur_mae:.1f} minutes"
                                )
                                # Reload engine model if registered
                                engine_wrapper = registry.get("neuralhabitengineagent")
                                if engine_wrapper and engine_wrapper.agent:
                                    engine_wrapper.agent.load_model()
                            else:
                                response = "Failed to run neural habit model training pipeline."
                        else:
                            confidence = min(sessions / 100.0, days / 14.0) * 100.0
                            response = (
                                f"### Neural Habit Retraining Gated\n"
                                f"Training is disabled until the dataset gate passes.\n"
                                f"- **Required:** 100 sessions AND 14 days\n"
                                f"- **Current Progress:** {sessions}/100 sessions, {days}/14 days\n"
                                f"- **Retraining Gate Readiness:** {confidence:.1f}%"
                            )
                except Exception as ex:
                    response = f"Failed to retrain habit model: {ex}"
 
            aria._speak(response)
            return {"handled": True, "action": "vision", "response": response}

        # Resolve visionagent from registry
        from skills.agent_registry import registry
        agent = registry.get("visionagent")
        if not agent:
            aria._speak("Vision agent is not registered.")
            return {"handled": True, "action": "vision", "response": "not_registered"}

        # Otherwise run agent
        screenshot_mode = is_analyze_screen
        deep_reasoning = is_describe_happening or is_analyze_camera
        
        payload = {
            "screenshot": screenshot_mode,
            "deep_reasoning_requested": deep_reasoning
        }
        
        if deep_reasoning:
            aria._speak("Analyzing room scene mechanics via multimodal analysis pass. One moment.")
        elif screenshot_mode:
            aria._speak("Capturing screen and performing visual analysis...")
        elif is_count_people:
            aria._speak("Scanning the environment to count people...")
        else:
            aria._speak("Scanning the environment using camera...")
            
        try:
            import time
            task_id = f"TSK_VIS_{int(time.time())}"
            raw_res = agent.run(task_id, user_input, payload)
            
            if deep_reasoning:
                aria._speak(raw_res)
                return {"handled": True, "action": "vision", "response": raw_res}
                
            import json
            data = json.loads(raw_res)
            
            if screenshot_mode:
                objects = ", ".join(data.get("vision_objects", []))
                ocr_snippet = data.get("ocr_text", "")
                conf = data.get("ocr_confidence", 0.0)
                if ocr_snippet:
                    ocr_readout = ocr_snippet[:200].replace("\n", " ")
                    aria._speak(f"Screen analysis complete. I detect: {objects or 'no distinct objects'}. Extracted text: {ocr_readout} (OCR confidence: {conf:.2f})")
                else:
                    aria._speak(f"Screen analysis complete. I detect: {objects or 'no distinct objects'}. No readable text was extracted.")
            elif is_count_people:
                ppl = data.get("vision_people", 0)
                faces = data.get("vision_faces", 0)
                hands = data.get("vision_hands", 0)
                aria._speak(f"I count {ppl} people in the room. I detected {faces} faces and {hands} hands.")
            else:
                objects = ", ".join(data.get("vision_objects", []))
                ppl = data.get("vision_people", 0)
                room = data.get("room_name", "unknown")
                posture = data.get("vision_pose_detected", "none")
                
                posture_phrase = ""
                if posture in ("sitting", "standing"):
                    posture_phrase = f" appearing to be {posture}"
                
                room_phrase = ""
                if room != "unknown":
                    room_phrase = f" in the {room}"
                
                aria._speak(f"Local scan complete{room_phrase}. My camera detects {ppl} people{posture_phrase}. Objects identified: {objects or 'none'}.")
                
            return {"handled": True, "action": "vision", "response": raw_res}
        except Exception as e:
            err_msg = f"Vision sweep encountered an error: {e}"
            print(f"[VisionHandler] Error: {e}")
            aria._speak("I scanned the station array deck but encountered a data parsing anomaly.")
            return {"handled": True, "action": "vision", "response": err_msg}
            
    return {"handled": False}


def handle_rag_search(aria, inp, user_input, image=None):
    """Router for local-first RAG Knowledge Search Agent."""
    inp_clean = inp.lower().strip()
    
    # Check trigger phrases
    is_rebuild = any(x in inp_clean for x in [
        "rebuild rag", "refresh knowledge vault", "rebuild knowledge index", 
        "rebuild knowledge vault", "refresh rag", "rebuild index"
    ])
    
    is_search = any(x in inp_clean for x in [
        "search notes", "search vault", "find in notes", "query notes",
        "search projects", "which projects use", "search resume",
        "what does my notes say", "what do my notes say", "what did my notes say"
    ])
    
    if is_rebuild or is_search:
        from skills.agent_registry import registry
        agent = registry.get("knowledgesearchagent")
        if not agent:
            aria._speak("Knowledge search agent is not registered.")
            return {"handled": True, "action": "rag_search", "response": "not_registered"}
            
        import time
        task_id = f"TSK_RAG_{int(time.time())}"
        
        # Pass the original user input as query, or check if it's a rebuild action
        if is_rebuild:
            aria._speak("Rebuilding knowledge vault index. This may take a moment...")
            payload = {"action": "rebuild"}
            desc = "Rebuild knowledge index"
        else:
            aria._speak("Searching my knowledge vault and memories...")
            payload = {"query": user_input}
            desc = f"Search query: {user_input}"
            
        try:
            # Set the aria instance on the wrapper agent just in case
            agent.aria = aria
            raw_res = agent.run(task_id, desc, payload)
            
            import json
            data = json.loads(raw_res)
            
            if is_rebuild:
                status = data.get("action", "SUCCESS")
                if status == "REBUILT":
                    aria._speak("Knowledge vault index rebuild completed successfully.")
                else:
                    aria._speak("Knowledge vault index is up to date. No changes detected.")
            else:
                answer = data.get("answer", "")
                if answer:
                    aria._speak(answer)
                else:
                    aria._speak("I searched the vault but couldn't find any relevant results or synthesize an answer.")
                    
            return {"handled": True, "action": "rag_search", "response": raw_res}
        except Exception as e:
            err_msg = f"Knowledge search encountered an error: {e}"
            print(f"[RAGSearchHandler] Error: {e}")
            aria._speak("I encountered an issue querying the knowledge search engine.")
            return {"handled": True, "action": "rag_search", "response": err_msg}
            
    return {"handled": False}


def handle_code_search(aria, inp, user_input, image=None):
    """Router for codebase intelligence and code RAG agent."""
    inp_clean = inp.lower().strip()
    
    # Check trigger phrases
    is_rebuild = any(x in inp_clean for x in [
        "rebuild code index", "refresh codebase index", 
        "rebuild codebase index", "refresh code index"
    ])
    
    is_search = any(x in inp_clean for x in [
        "search code", "search codebase", "find in code", "where is class", 
        "where is function", "how is", "implemented", "explain code"
    ])
    
    if is_rebuild or is_search:
        from skills.agent_registry import registry
        agent = registry.get("codesearchagent")
        if not agent:
            aria._speak("Code search agent is not registered.")
            return {"handled": True, "action": "code_search", "response": "not_registered"}
            
        import time
        task_id = f"TSK_CODE_{int(time.time())}"
        
        if is_rebuild:
            aria._speak("Indexing AST nodes from python files. This may take a moment...")
            payload = {"action": "rebuild"}
            desc = "Rebuild codebase code index"
        else:
            aria._speak("Scanning codebase structures and symbols...")
            payload = {"query": user_input}
            desc = f"Code query: {user_input}"
            
        try:
            agent.aria = aria
            raw_res = agent.run(task_id, desc, payload)
            
            import json
            data = json.loads(raw_res)
            
            if is_rebuild:
                status = data.get("action", "SUCCESS")
                if status == "REBUILT":
                    aria._speak("Codebase index rebuild completed successfully.")
                else:
                    aria._speak("Codebase index is up to date.")
            else:
                answer = data.get("answer", "")
                if answer:
                    aria._speak(answer)
                else:
                    aria._speak("I scanned the codebase but couldn't find any matching definitions or explain it.")
                    
            return {"handled": True, "action": "code_search", "response": raw_res}
        except Exception as e:
            err_msg = f"Code search encountered an error: {e}"
            print(f"[CodeSearchHandler] Error: {e}")
            aria._speak("I encountered an issue querying the codebase search engine.")
            return {"handled": True, "action": "code_search", "response": err_msg}
            
    return {"handled": False}


def handle_architecture_query(aria, inp, user_input, image=None):
    """Router for codebase dependency graph analysis and architecture agent."""
    inp_clean = inp.lower().strip()
    
    # Check trigger phrases
    is_search = any(x in inp_clean for x in [
        "dependency graph", "ripple impact", "execution path", "trace path", 
        "circular dependencies", "dependencies of", "what depends on",
        "architectural stats", "architecture stats"
    ])
    
    if is_search:
        from skills.agent_registry import registry
        agent = registry.get("architectureagent")
        if not agent:
            aria._speak("Architecture agent is not registered.")
            return {"handled": True, "action": "architecture_query", "response": "not_registered"}
            
        import time
        task_id = f"TSK_ARCH_{int(time.time())}"
        
        # Decide action based on text
        action = "trace_impact"
        if "circle" in inp_clean or "cycle" in inp_clean or "circular" in inp_clean:
            action = "detect_cycles"
        elif "stat" in inp_clean or "summary" in inp_clean or "metric" in inp_clean:
            action = "stats"
        elif "path" in inp_clean or "flow" in inp_clean or "route" in inp_clean:
            action = "trace_path"
            
        aria._speak("Mapping system dependency graphs...")
        
        payload = {
            "query": user_input,
            "action": action
        }
        
        try:
            agent.aria = aria
            raw_res = agent.run(task_id, f"Architecture analysis: {user_input}", payload)
            
            import json
            data = json.loads(raw_res)
            answer = data.get("answer", "")
            if answer:
                aria._speak(answer)
            else:
                aria._speak("I mapped the codebase dependencies but couldn't synthesize a briefing report.")
                
            return {"handled": True, "action": "architecture_query", "response": raw_res}
        except Exception as e:
            err_msg = f"Architecture engine query encountered an error: {e}"
            print(f"[ArchitectureHandler] Error: {e}")
            aria._speak("I encountered an issue querying the dependency architecture map.")
            return {"handled": True, "action": "architecture_query", "response": err_msg}
            
    return {"handled": False}


def handle_research_query(aria, inp, user_input, image=None):
    """Router for deep multi-source research agent."""
    inp_clean = inp.lower().strip()
    
    # Check trigger phrases
    is_research = any(x in inp_clean for x in [
        "compile a research report on", "compile research report on",
        "research topic", "deep research on", "research on", "compile report on"
    ]) or inp_clean.startswith("research ")
    
    if is_research:
        from skills.agent_registry import registry
        agent = registry.get("researchagent")
        if not agent:
            aria._speak("Research agent is not registered.")
            return {"handled": True, "action": "research_query", "response": "not_registered"}
            
        import time
        task_id = f"TSK_RES_{int(time.time())}"
        
        aria._speak("Assembling local contexts and generating research briefing via Vertex AI...")
        
        # Extract the research target query (strip prefix)
        target = user_input
        prefixes = ["compile a research report on", "compile research report on",
                    "research topic", "deep research on", "research on", "compile report on", "research"]
        target_clean = inp_clean
        for prefix in prefixes:
            if target_clean.startswith(prefix):
                target_clean = target_clean[len(prefix):].strip()
                # Find corresponding casing in user_input
                idx = user_input.lower().find(target_clean)
                if idx != -1:
                    target = user_input[idx:].strip()
                break
                
        payload = {
            "query": target
        }
        
        try:
            agent.aria = aria
            raw_res = agent.run(task_id, f"Research query: {target}", payload)
            
            import json
            data = json.loads(raw_res)
            report = data.get("report", "")
            if report:
                aria._speak(report)
            else:
                aria._speak("I performed the research search but could not compile a report.")
                
            return {"handled": True, "action": "research_query", "response": raw_res}
        except Exception as e:
            err_msg = f"Research engine pass encountered an error: {e}"
            print(f"[ResearchHandler] Error: {e}")
            aria._speak("I encountered an issue compiling the research report.")
            return {"handled": True, "action": "research_query", "response": err_msg}
            
    return {"handled": False}


def handle_task_planning(aria, inp, user_input, image=None):
    """Router for deep task graph planner."""
    inp_clean = inp.lower().strip()
    
    # Check trigger phrases
    is_planning = any(x in inp_clean for x in [
        "plan goal:", "generate task plan for", "generate plan for",
        "task plan for", "plan campaign for", "create plan for"
    ]) or inp_clean.startswith("plan ")
    
    if is_planning:
        from skills.agent_registry import registry
        agent = registry.get("planningagent")
        if not agent:
            aria._speak("Task planning agent is not registered.")
            return {"handled": True, "action": "task_planning", "response": "not_registered"}
            
        import time
        task_id = f"TSK_PLAN_{int(time.time())}"
        
        # Extract the goal (strip prefix)
        goal = user_input
        prefixes = ["plan goal:", "generate task plan for", "generate plan for",
                    "task plan for", "plan campaign for", "create plan for", "plan"]
        goal_clean = inp_clean
        for prefix in prefixes:
            if goal_clean.startswith(prefix):
                goal_clean = goal_clean[len(prefix):].strip()
                # Find corresponding casing in user_input
                idx = user_input.lower().find(goal_clean)
                if idx != -1:
                    goal = user_input[idx:].strip()
                break
                
        aria._speak(f"Compiling structured task graph plan for objective: '{goal}'...")
        
        payload = {
            "goal": goal,
            "research_context": "No supplemental background context compiled."
        }
        
        # Gather recent Blackboard research briefings to feed into the planner's research_context
        try:
            from skills.blackboard import AriaBlackboard
            bb = AriaBlackboard()
            research_data = bb.get_all("research")
            if research_data:
                relevant_briefings = []
                for key, data in research_data.get("research", {}).items():
                    val = data.get("value")
                    if isinstance(val, dict) and "report" in val:
                        query = val.get("query", "")
                        relevant_briefings.append(f"Research on '{query}':\n{val['report']}")
                if relevant_briefings:
                    payload["research_context"] = "\n\n".join(relevant_briefings[:2])
        except Exception as e:
            print(f"[TaskPlannerRouter] Error reading blackboard research context: {e}")
            
        try:
            agent.aria = aria
            raw_res = agent.run(task_id, f"Plan goal: {goal}", payload)
            
            import json
            data = json.loads(raw_res)
            plan = data.get("plan", {})
            if data.get("status") == "SUCCESS" and plan:
                aria._speak(f"Draft plan created for '{plan.get('goal')}' with {len(plan.get('tasks', []))} tasks and {len(plan.get('milestones', []))} milestones. Staged under key 'taskplan_{task_id}' for your review.")
            elif data.get("status") == "INVALID_PLAN":
                aria._speak(f"Plan generation failed validation check: {data.get('error', 'Unknown error')}")
            else:
                aria._speak("I generated the plan but failed to parse it or save it.")
                
            return {"handled": True, "action": "task_planning", "response": raw_res}
        except Exception as e:
            err_msg = f"Task planning engine pass encountered an error: {e}"
            print(f"[TaskPlannerHandler] Error: {e}")
            aria._speak("I encountered an issue generating the task graph plan.")
            return {"handled": True, "action": "task_planning", "response": err_msg}
            
    return {"handled": False}


def handle_gesture_monitoring(aria, inp, user_input, image=None):
    """Router for gesture detection background agent loop control."""
    inp_clean = inp.lower().strip()
    
    start_triggers = [
        "start gesture monitoring", "enable gesture detection", 
        "gesture detection on", "gesture monitoring loop on", 
        "gesture agent start", "start gesture tracking"
    ]
    stop_triggers = [
        "stop gesture monitoring", "disable gesture detection", 
        "gesture detection off", "gesture monitoring loop off", 
        "gesture agent stop", "stop gesture tracking"
    ]
    
    is_start = any(t in inp_clean for t in start_triggers)
    is_stop = any(t in inp_clean for t in stop_triggers)
    
    if is_start or is_stop:
        from skills.agent_registry import registry
        agent_wrapper = registry.get("gestureagent")
        if not agent_wrapper:
            aria._speak("Gesture agent is not registered.")
            return {"handled": True, "action": "gesture_monitoring", "response": "not_registered"}
            
        import time
        task_id = f"TSK_GES_{int(time.time())}"
        
        command = "start" if is_start else "stop"
        payload = {"command": command}
        
        try:
            agent_wrapper.aria = aria
            raw_res = agent_wrapper.run(task_id, f"Gesture agent command: {command}", payload)
            
            import json
            data = json.loads(raw_res)
            if data.get("status") == "SUCCESS":
                aria._speak(data.get("message", "Gesture command processed."))
            else:
                aria._speak("I encountered an issue controlling the gesture monitoring loop.")
                
            return {"handled": True, "action": "gesture_monitoring", "response": raw_res}
        except Exception as e:
            err_msg = f"Gesture routing process encountered an error: {e}"
            print(f"[GestureRouter] Error: {e}")
            aria._speak("I encountered an issue executing the gesture monitoring command.")
            return {"handled": True, "action": "gesture_monitoring", "response": err_msg}
            
    return {"handled": False}


def handle_personal_coach(aria, inp, user_input, image=None):
    """
    Routes commands for the Personal AI Coach:
    - show today's brief, daily brief, coach status, evening review, weekly review
    """
    inp_clean = inp.lower().strip()
    
    is_daily_brief = any(t in inp_clean for t in ["show today's brief", "daily brief", "coach status", "morning brief"])
    is_evening_review = "evening review" in inp_clean
    is_weekly_review = "weekly review" in inp_clean or "sunday review" in inp_clean

    if is_daily_brief or is_evening_review or is_weekly_review:
        from skills.blackboard import AriaBlackboard
        blackboard = AriaBlackboard()
        
        # Load registry to find personal coach agent if we need fallback generation
        from skills.agent_registry import registry
        coach_wrapper = registry.get("personalcoachagent")
        
        if is_daily_brief:
            # Try to read daily_brief from blackboard
            brief = blackboard.read("coach", "daily_brief")
            if not brief:
                # If not present, try to generate it now
                if coach_wrapper and coach_wrapper.agent:
                    try:
                        brief = coach_wrapper.agent.run("TSK_COACH_DAILY", "generate daily brief", {"type": "daily_brief"})
                    except Exception as e:
                        print(f"[PersonalCoachRouter] Failed to generate brief on demand: {e}")
            
            if brief:
                aria._speak(brief)
                return {"handled": True, "action": "personal_coach", "response": brief}
            else:
                resp = "I don't have a daily brief compiled yet, and I was unable to generate one at the moment."
                aria._speak(resp)
                return {"handled": True, "action": "personal_coach", "response": resp}
                
        elif is_evening_review:
            brief = blackboard.read("coach", "evening_review")
            if not brief:
                if coach_wrapper and coach_wrapper.agent:
                    try:
                        brief = coach_wrapper.agent.run("TSK_COACH_EVENING", "generate evening review", {"type": "evening_review"})
                    except Exception as e:
                        print(f"[PersonalCoachRouter] Failed to generate evening review on demand: {e}")
            
            if brief:
                aria._speak(brief)
                return {"handled": True, "action": "personal_coach", "response": brief}
            else:
                resp = "I don't have an evening review compiled yet, and I was unable to generate one at the moment."
                aria._speak(resp)
                return {"handled": True, "action": "personal_coach", "response": resp}
                
        elif is_weekly_review:
            brief = blackboard.read("coach", "weekly_review")
            if not brief:
                if coach_wrapper and coach_wrapper.agent:
                    try:
                        brief = coach_wrapper.agent.run("TSK_COACH_WEEKLY", "generate weekly review", {"type": "weekly_review"})
                    except Exception as e:
                        print(f"[PersonalCoachRouter] Failed to generate weekly review on demand: {e}")
            
            if brief:
                aria._speak(brief)
                return {"handled": True, "action": "personal_coach", "response": brief}
            else:
                resp = "I don't have a weekly coach review compiled yet, and I was unable to generate one at the moment."
                aria._speak(resp)
                return {"handled": True, "action": "personal_coach", "response": resp}
                
    return {"handled": False}


def handle_self_improvement(aria, inp, user_input, image=None):
    """
    Routes commands for the Self-Improvement Ledger & Graph Reasoning:
    - show accuracy metrics, self-evaluation status, prediction ledger status
    - check campaign bottlenecks, check bottlenecks, graph blockers
    - run weekly reflection, strategic audit, run strategic reflection
    """
    clean_text = inp.lower().strip()
    from skills.self_improvement_core import AriaSelfImprovementCore
    si_core = AriaSelfImprovementCore()

    # Triggers for accuracy metrics / ledger status
    ACCURACY_TRIGGERS = ["show accuracy metrics", "self-evaluation status", "prediction ledger status", "ledger status"]
    if any(t in clean_text for t in ACCURACY_TRIGGERS):
        import sqlite3
        import glob
        try:
            with sqlite3.connect(si_core.db_path) as conn:
                # Predictions counts
                cursor = conn.execute("SELECT COUNT(*) FROM prediction_ledger")
                pred_total = cursor.fetchone()[0]
                cursor = conn.execute("SELECT COUNT(*) FROM prediction_ledger WHERE accuracy_score IS NOT NULL")
                pred_resolved = cursor.fetchone()[0]
                cursor = conn.execute("SELECT AVG(accuracy_score) FROM prediction_ledger WHERE accuracy_score IS NOT NULL")
                pred_avg = cursor.fetchone()[0]

                # Interventions counts
                cursor = conn.execute("SELECT COUNT(*) FROM intervention_ledger")
                inter_total = cursor.fetchone()[0]
                cursor = conn.execute("SELECT COUNT(*) FROM intervention_ledger WHERE success_score IS NOT NULL")
                inter_resolved = cursor.fetchone()[0]
                cursor = conn.execute("SELECT AVG(success_score) FROM intervention_ledger WHERE success_score IS NOT NULL")
                inter_avg = cursor.fetchone()[0]
        except Exception as e:
            msg = f"Failed to fetch ledger metrics: {e}"
            aria._speak("I encountered an issue querying the evaluation ledger.")
            return {"handled": True, "action": "self_improvement", "response": msg}

        rate = round(pred_avg * 100, 0) if pred_resolved and pred_avg is not None else 0
        i_rate = round(inter_avg * 100, 0) if inter_resolved and inter_avg is not None else 0
        
        # Habit dataset counts
        dataset_dir = "data/habit_dataset"
        import os
        files = glob.glob(os.path.join(dataset_dir, "session_*.json")) if os.path.exists(dataset_dir) else []
        total_sessions = len(files)
        unique_days = set()
        for f in files:
            try:
                import json
                with open(f, "r", encoding="utf-8") as file:
                    data = json.load(file)
                if "date" in data:
                    unique_days.add(data["date"])
            except Exception:
                continue
        days_count = len(unique_days)
        
        # Reflection readiness check
        is_ready = (pred_total >= 100) and (inter_total >= 50) and (days_count >= 14)
        ready_str = "YES" if is_ready else "NO (Accumulating data: predictions >= 100, interventions >= 50, habit days >= 14)"

        # Continuous retraining gate check (500 sessions and 60 days required)
        is_gate_unlocked = (total_sessions >= 500) and (days_count >= 60)
        gate_status = "[UNLOCKED]" if is_gate_unlocked else "[LOCKED] (Collecting Data: sessions >= 500, unique days >= 60)"

        resp = (
            f"### ARIA Ledger Status Dashboard\n\n"
            f"**Predictions:**\n"
            f"  - Total: {pred_total}\n"
            f"  - Resolved: {pred_resolved}\n"
            f"  - Accuracy: {int(rate)}%\n\n"
            f"**Interventions:**\n"
            f"  - Total: {inter_total}\n"
            f"  - Resolved: {inter_resolved}\n"
            f"  - Success Rate: {int(i_rate)}%\n\n"
            f"**Habit Dataset:**\n"
            f"  - Sessions: {total_sessions}\n"
            f"  - Days: {days_count}\n\n"
            f"**Reflection Ready:**\n"
            f"  - {ready_str}\n\n"
            f"**Continuous Neural Retraining Gate:**\n"
            f"  - {gate_status}"
        )
        
        aria._speak(f"Here is the ledger status, Chinmaya. Calculated prediction accuracy is {int(rate)} percent and intervention success rate is {int(i_rate)} percent.")
        print(resp)
        return {"handled": True, "action": "self_improvement", "response": resp}

    # Triggers for campaign bottlenecks
    BOTTLENECK_TRIGGERS = ["check campaign bottlenecks", "check bottlenecks", "graph blockers"]
    if any(t in clean_text for t in BOTTLENECK_TRIGGERS):
        issues = si_core.identify_campaign_bottlenecks("Java Internship")
        if not issues:
            resp = "All connected graph dependency pathways are clear and on schedule, Chinmaya."
            aria._speak(resp)
            return {"handled": True, "action": "self_improvement", "response": resp}
        
        resp = "### ARIA Knowledge Graph Reasoning Report:\n" + "\n".join([f"- {issue}" for issue in issues])
        aria._speak("I found some campaign bottlenecks in the dependency graph.")
        print(resp)
        return {"handled": True, "action": "self_improvement", "response": resp}

    # Triggers for strategic reflection / weekly reflection
    REFLECTION_TRIGGERS = ["run weekly reflection", "strategic audit", "run strategic reflection"]
    if any(t in clean_text for t in REFLECTION_TRIGGERS):
        if hasattr(aria, "vertex_bridge") and aria.vertex_bridge:
            try:
                reflection_brief = si_core.execute_sunday_reflection_pass(aria.vertex_bridge)
                aria._speak("Strategic reflection pass completed. Check details on console.")
                print(reflection_brief)
                return {"handled": True, "action": "self_improvement", "response": reflection_brief}
            except Exception as e:
                msg = f"Failed to run weekly reflection: {e}"
                aria._speak("I encountered an issue compiling the weekly strategic reflection.")
                return {"handled": True, "action": "self_improvement", "response": msg}
        
        # Fallback if vertex bridge is missing on aria
        from skills.vertex_bridge import AriaVertexBridge
        bridge = AriaVertexBridge()
        try:
            reflection_brief = si_core.execute_sunday_reflection_pass(bridge)
            aria._speak("Strategic reflection pass completed via local bridge.")
            print(reflection_brief)
            return {"handled": True, "action": "self_improvement", "response": reflection_brief}
        except Exception as e:
            msg = f"Failed to run weekly reflection: {e}"
            aria._speak("I encountered an issue compiling the weekly strategic reflection.")
            return {"handled": True, "action": "self_improvement", "response": msg}

    # Triggers for collaborative workforce coordination (Sprint P15)
    WORKFORCE_TRIGGERS = ["trigger collaborative plan", "run workforce matrix"]
    if any(t in clean_text for t in WORKFORCE_TRIGGERS):
        # Fetch active campaign or default
        campaign_id = "CAMP_WF_ACTIVE"
        milestone_id = "MS_WF_ACTIVE"
        try:
            with sqlite3.connect(si_core.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM campaigns WHERE status = 'RUNNING' LIMIT 1")
                row = cursor.fetchone()
                if row:
                    campaign_id = row[0]
                cursor.execute("SELECT id FROM campaign_milestones WHERE campaign_id = ? LIMIT 1", (campaign_id,))
                row = cursor.fetchone()
                if row:
                    milestone_id = row[0]
        except Exception:
            pass

        from skills.multi_agent_workforce import AriaCollaborativeWorkforceManager
        manager = AriaCollaborativeWorkforceManager(aria, si_core.db_path)
        
        result = manager.coordinate_parallel_campaign_pass(
            campaign_id=campaign_id,
            milestone_id=milestone_id,
            broad_goal="Get a Java Placement Internship"
        )
        
        task_list_str = "\n".join([f"  - Activated Task: {t_id}" for t_id in result["injected_task_ids"]])
        resp = (
            f"### ARIA Multi-Agent Workgroup Summary\n"
            f"- **Operational Stance:** {result['status']}\n"
            f"- **Session ID:** {result['session_id']}\n"
            f"- **Departments Coordinated Successfully:** {', '.join(result['sources_coordinated'])}\n"
            f"- **Synthesized Tasks Generated:** {result['tasks_generated_count']}\n"
            f"- **Peer-Review Alignment Score:** {result['review_score']}\n"
            f"**Active Workspace Task Tree Lines:**\n{task_list_str}"
        )
        aria._speak("Multi-agent collaborative workgroup planning complete.")
        print(resp)
        return {"handled": True, "action": "self_improvement", "response": resp}

    # Triggers for running learning calibration (Sprint P20)
    CALIBRATION_TRIGGERS = ["run learning calibration", "calibrate policies", "run policy calibration"]
    if any(t in clean_text for t in CALIBRATION_TRIGGERS):
        from skills.learning_engine import AriaLongTermLearningEngine
        engine = AriaLongTermLearningEngine(si_core.db_path)
        calibrations = engine.run_nightly_policy_calibration()
        
        resp = (
            f"### ARIA Policy Calibration Summary\n"
            f"- **Duration Policies Calibrated/Updated:** {calibrations['duration_policies_updated']}\n"
            f"- **Simulation Bias Calibrated:** {'Yes' if calibrations['simulation_bias_updated'] else 'No'}\n"
            f"- **Burnout Threshold Calibrated:** {'Yes' if calibrations['burnout_threshold_updated'] else 'No'}\n"
            f"- **Ineffective Policies Retired:** {calibrations['policies_retired']}\n"
        )
        aria._speak("Policy calibration sweep completed successfully, Chinmaya.")
        print(resp)
        return {"handled": True, "action": "self_improvement", "response": resp}

    # Triggers for showing operational policies (Sprint P20)
    SHOW_POLICIES_TRIGGERS = ["show operational policies", "show policies", "list operational policies"]
    if any(t in clean_text for t in SHOW_POLICIES_TRIGGERS):
        from skills.learning_engine import AriaLongTermLearningEngine
        import sqlite3
        resp = "### ARIA System Operational Policies\n\n"
        try:
            with sqlite3.connect(si_core.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT policy_id, policy_type, policy_key, policy_value, confidence, sample_size, status, policy_version, created_at, last_applied
                    FROM system_operational_policies
                """)
                rows = cursor.fetchall()
                if not rows:
                    resp += "No operational policies found in database."
                else:
                    resp += "| Policy ID | Type | Key | Value | Conf | N | Status | Ver | Last Applied |\n"
                    resp += "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
                    for row in rows:
                        last_app = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["last_applied"])) if row["last_applied"] else "Never"
                        resp += f"| {row['policy_id']} | {row['policy_type']} | {row['policy_key']} | {row['policy_value']} | {row['confidence']} | {row['sample_size']} | {row['status']} | {row['policy_version']} | {last_app} |\n"
        except Exception as e:
            resp += f"Error loading policies: {e}"
        aria._speak("Here is the list of current system operational policies.")
        print(resp)
        return {"handled": True, "action": "self_improvement", "response": resp}

    # Triggers for opportunity discovery (Sprint P21)
    OPPORTUNITY_TRIGGERS = ["scan opportunities", "discover opportunities", "run opportunity scan"]
    if any(t in clean_text for t in OPPORTUNITY_TRIGGERS):
        from skills.opportunity_discovery import AriaOpportunityDiscoveryEngine
        engine = AriaOpportunityDiscoveryEngine(si_core.db_path)
        engine.seed_market_listings()
        cleaned = engine.nightly_opportunity_cleanup()
        proposals = engine.evaluate_and_score_opportunities(aria)
        
        # Automate Opportunity Readiness Campaigns generation for recommended listings
        for p in proposals:
            if p.get("recommended") == "YES" and p.get("missing_skills"):
                try:
                    from skills.chief_of_staff_agent import AriaChiefOfStaffAgent
                    cos = AriaChiefOfStaffAgent(aria)
                    cos._stage_opportunity_readiness_campaign(p)
                except Exception as ex:
                    print(f"[CommandRouter] Failed to stage readiness campaign for {p['opportunity_id']}: {ex}")

        resp = (
            f"### ARIA Opportunity Discovery Scan Summary\n"
            f"- **Opportunities Scanned:** {len(proposals)}\n"
            f"- **Recommended Proposals Staged:** {len([p for p in proposals if p['recommended'] == 'YES'])}\n"
            f"- **Expired Listings Cleaned:** {cleaned}\n"
        )
        aria._speak("Proactive opportunity discovery scan completed successfully.")
        print(resp)
        return {"handled": True, "action": "self_improvement", "response": resp}

    SHOW_PROPOSALS_TRIGGERS = ["show opportunity proposals", "show proposals", "list proposals"]
    if any(t in clean_text for t in SHOW_PROPOSALS_TRIGGERS):
        import sqlite3
        resp = "### ARIA Active Opportunity Proposals\n\n"
        try:
            with sqlite3.connect(si_core.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT opportunity_id, title, provider, source, required_skills, missing_skills, estimated_preparation_hours, career_value, application_deadline, match_score, roi_score, status
                    FROM external_opportunities
                    WHERE status = 'PROPOSED'
                """)
                rows = cursor.fetchall()
                if not rows:
                    resp += "No active opportunity proposals found. Run 'scan opportunities' first."
                else:
                    resp += "| Opportunity ID | Title | Provider | Source | Match | ROI | Missing Skills | Prep (Hrs) | Status |\n"
                    resp += "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
                    for row in rows:
                        missing = json.loads(row["missing_skills"]) if row["missing_skills"] else []
                        missing_str = ", ".join(missing) if missing else "None"
                        match_pct = f"{int(row['match_score'] * 100)}%" if row["match_score"] is not None else "0%"
                        roi_val = f"{row['roi_score']:.2f}" if row["roi_score"] is not None else "0.00"
                        resp += f"| {row['opportunity_id']} | {row['title']} | {row['provider']} | {row['source']} | {match_pct} | {roi_val} | {missing_str} | {row['estimated_preparation_hours']} | {row['status']} |\n"
        except Exception as e:
            resp += f"Error loading proposals: {e}"
        aria._speak("Here are the active opportunity proposals.")
        print(resp)
        return {"handled": True, "action": "self_improvement", "response": resp}

    # Triggers for what if simulation queries (Sprint P18)
    if clean_text.startswith("what if"):
        from skills.simulation_engine import AriaSimulationEngine
        from skills.blackboard import AriaBlackboard
        
        bb = AriaBlackboard()
        all_system = bb.get_all(topic="system").get("system", {})
        
        latest_plan = None
        latest_time = 0
        for key, entry in all_system.items():
            if key.startswith("taskplan_"):
                updated_at = entry.get("updated_at", 0)
                if updated_at > latest_time:
                    latest_time = updated_at
                    latest_plan = entry.get("value")
                    
        if latest_plan and isinstance(latest_plan, dict):
            proposed_tasks = latest_plan.get("tasks", [])
        else:
            # Fallback mock tasks representing standard study topics
            proposed_tasks = [
                {"id": "T1", "description": "Configure Spring Boot security settings", "priority": "HIGH", "agent_target": "CodingAgent"},
                {"id": "T2", "description": "Implement LeetCode graph traversal problems", "priority": "MEDIUM", "agent_target": "CodingAgent"},
                {"id": "T3", "description": "Revise DBMS normal forms", "priority": "LOW", "agent_target": "LearningAgent"}
            ]
            
        sim_engine = AriaSimulationEngine(si_core.db_path)
        res = sim_engine.run_what_if_analysis(user_input, proposed_tasks)
        
        resp = (
            f"### ARIA Future Simulation: What-If Analysis\n"
            f"**Query Parameter:** '{res['query']}'\n\n"
            f"- **Projected Completion Probability:** {int(res['completion_probability'] * 100)}%\n"
            f"- **Burnout Vulnerability Vector:** {int(res['burnout_risk'] * 100)}%\n"
            f"- **Resource Allocation Efficiency:** {int(res['resource_cost_minutes'])}m (Cost) | Score: {res['executive_score']}\n"
            f"- **Expected Delay:** {res['expected_delay_days']} days\n\n"
            f"**Strategic Guidance:** {res['strategic_guidance']}"
        )
        aria._speak("I have projected the simulated futures for your query.")
        print(resp)
        return {"handled": True, "action": "self_improvement", "response": resp}

    # ─ Triggers for Personal OS / Life OS stats (Sprint P22) ─
    LIFE_OS_STATS_TRIGGERS = ["life os stats", "personal os stats", "system balance"]
    if any(t in clean_text for t in LIFE_OS_STATS_TRIGGERS):
        try:
            from skills.personal_os_reasoning import PersonalOSReasoningEngine
            pos = PersonalOSReasoningEngine()
            pressures = pos.compute_systemic_pressures()
            
            resp = (
                f"### ARIA Personal Life OS Dashboard\n"
                f"- **Current State:** `{pressures.get('life_state', 'NORMAL')}`\n"
                f"- **Overall Life Load Index:** {pressures.get('overall_life_load', 0.0):.2f} / 1.0 (Burnout Policy Limit: {pressures.get('burnout_limit_policy', 0.70):.2f})\n"
                f"- **Academic Pressure Score:** {pressures.get('academic_pressure', 0.0):.2f}\n"
                f"- **Energy Pressure Score:** {pressures.get('energy_pressure', 0.0):.2f} (Calculated Biological Energy: {pressures.get('raw_energy_score', 70)}%)\n"
                f"- **Routine Density Pressure:** {pressures.get('routine_pressure', 0.0):.2f}\n"
                f"- **Hourly Circadian focus multiplier:** {pressures.get('circadian_focus_multiplier', 1.0):.1f}x\n"
                f"- **Rolling Sleep Stats (7-Day):** Average: {pressures.get('rolling_sleep_avg', 7.5):.1f} hrs | Cumulative Sleep Debt: {pressures.get('sleep_debt', 0.0):.1f} hrs\n"
                f"- **Rolling Step Count (7-Day Avg):** {pressures.get('rolling_steps_avg', 5000):,} steps\n"
                f"- **Active Safety Guards Deployed:** {', '.join(pressures.get('active_guards', [])) if pressures.get('active_guards') else 'None'}\n"
            )
            aria._speak(f"Personal OS dashboard compiled. Current state is {pressures.get('life_state', 'NORMAL')}.")
            print(resp)
            return {"handled": True, "action": "self_improvement", "response": resp}
        except Exception as e:
            msg = f"Failed to compile Life OS dashboard: {e}"
            aria._speak("I could not compile the Life OS dashboard at this moment.")
            return {"handled": True, "action": "self_improvement", "response": msg}

    if clean_text.startswith("log sleep"):
        parts = clean_text.split()
        if len(parts) >= 3:
            try:
                hours = float(parts[2])
                quality = parts[3] if len(parts) > 3 else "Unknown"
                quality = quality.capitalize()
                from skills.health_skill import HealthSkill
                hs = HealthSkill()
                hs.save_fitness_metrics(sleep_hours=hours, sleep_quality=quality)
                msg = f"Logged sleep: {hours} hours (Quality: {quality}) successfully."
                aria._speak(msg)
                return {"handled": True, "action": "self_improvement", "response": msg}
            except Exception as e:
                msg = f"Failed to log sleep: {e}"
                aria._speak("I encountered an issue parsing the sleep metrics.")
                return {"handled": True, "action": "self_improvement", "response": msg}
        else:
            msg = "Usage: log sleep <hours> <quality>"
            aria._speak(msg)
            return {"handled": True, "action": "self_improvement", "response": msg}

    if clean_text.startswith("log fitness"):
        parts = clean_text.split()
        if len(parts) >= 3:
            try:
                steps = int(parts[2])
                calories = float(parts[3]) if len(parts) > 3 else 0.0
                from skills.health_skill import HealthSkill
                hs = HealthSkill()
                hs.save_fitness_metrics(steps=steps, calories=calories)
                msg = f"Logged activity: {steps} steps, {calories} kcal successfully."
                aria._speak(msg)
                return {"handled": True, "action": "self_improvement", "response": msg}
            except Exception as e:
                msg = f"Failed to log fitness: {e}"
                aria._speak("I encountered an issue parsing the fitness metrics.")
                return {"handled": True, "action": "self_improvement", "response": msg}
        else:
            msg = "Usage: log fitness <steps> [calories]"
            aria._speak(msg)
            return {"handled": True, "action": "self_improvement", "response": msg}

    if clean_text.startswith("add calendar"):
        parts = clean_text.split()
        if len(parts) >= 4:
            try:
                import re
                import sqlite3
                match = re.search(r'add calendar\s+(\S+)\s+"([^"]+)"\s+(\S+)(?:\s+(\d+))?', clean_text)
                if not match:
                    match = re.search(r'add calendar\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(\d+))?', clean_text)
                    if not match:
                        msg = 'Usage: add calendar <type> "<title>" <epoch_or_day> [criticality]'
                        aria._speak(msg)
                        return {"handled": True, "action": "self_improvement", "response": msg}
                    event_type, title, time_val, crit = match.groups()
                else:
                    event_type, title, time_val, crit = match.groups()
                
                crit_val = int(crit) if crit else 5
                
                try:
                    timestamp = int(time_val)
                    day_of_week = "None"
                except ValueError:
                    timestamp = 0
                    day_of_week = time_val.capitalize()
                    
                from skills.personal_os_reasoning import PersonalOSReasoningEngine
                pos = PersonalOSReasoningEngine()
                
                conn = sqlite3.connect(pos.db_path)
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO life_calendar (timestamp, day_of_week, event_type, title, criticality)
                    VALUES (?, ?, ?, ?, ?)
                """, (timestamp, day_of_week, event_type, title, crit_val))
                conn.commit()
                conn.close()
                
                msg = f"Added calendar event: '{title}' ({event_type}) on {time_val} with criticality {crit_val}."
                aria._speak(msg)
                return {"handled": True, "action": "self_improvement", "response": msg}
            except Exception as e:
                msg = f"Failed to add calendar event: {e}"
                aria._speak("I encountered an issue adding the calendar event.")
                return {"handled": True, "action": "self_improvement", "response": msg}
        else:
            msg = 'Usage: add calendar <type> "<title>" <epoch_or_day> [criticality]'
            aria._speak(msg)
            return {"handled": True, "action": "self_improvement", "response": msg}

    # ── P24 Stage 2: Executive stage control & telemetry ──────────────
    if clean_text.startswith("set executive stage"):
        parts = clean_text.split()
        if len(parts) >= 4:
            try:
                stage = int(parts[3])
                if stage not in (1, 2, 3):
                    raise ValueError("Stage must be 1, 2, or 3")
                from skills.executive_brain import AriaExecutiveBrain
                brain = AriaExecutiveBrain(aria_instance=aria, db_path=si_core.db_path)
                brain.set_active_stage(stage)
                msg = f"Executive active stage manually set to Stage {stage}."
                aria._speak(msg)
                return {"handled": True, "action": "self_improvement", "response": msg}
            except Exception as e:
                msg = f"Failed to set executive stage: {e}"
                aria._speak(msg)
                return {"handled": True, "action": "self_improvement", "response": msg}
        else:
            msg = "Usage: set executive stage <1|2|3>"
            aria._speak(msg)
            return {"handled": True, "action": "self_improvement", "response": msg}

    if any(t in clean_text for t in ["show executive stats", "show executive status", "show executive brain stats"]):
        try:
            from skills.executive_brain import AriaExecutiveBrain
            brain = AriaExecutiveBrain(aria_instance=aria, db_path=si_core.db_path)
            stage = brain.get_active_stage()
            summary = brain.alignment_summary()
            
            stage_desc = {
                1: "Stage 1: Shadow Mode (Passive Observation)",
                2: "Stage 2: Advisory Mode (Blackboard Advisories)",
                3: "Stage 3: Autonomous Mode (Direct Governance)"
            }.get(stage, f"Unknown Stage ({stage})")
            
            if "message" in summary:
                resp = (
                    f"### ARIA Executive Brain Status\n\n"
                    f"- **Active Governance Stage:** `{stage_desc}`\n"
                    f"- **Ledger Stats:** {summary['message']}\n"
                )
            else:
                eligible = "YES" if summary.get("stage2_eligible", False) else "NO"
                resp = (
                    f"### ARIA Executive Brain Status\n\n"
                    f"- **Active Governance Stage:** `{stage_desc}`\n"
                    f"- **Total Shadow Passes:** {summary.get('total_passes', 0)}\n"
                    f"- **Resolved Outcomes:** {summary.get('resolved_decisions', 0)} / 10 required for Stage 2\n"
                    f"- **Average Weighted Alignment:** {int(summary.get('avg_weighted_alignment', 0.0) * 100)}% / 85% required\n"
                    f"- **Directive Hit Rate:** {int(summary.get('directive_hit_rate', 0.0) * 100)}%\n"
                    f"- **Domain Hit Rate:** {int(summary.get('domain_hit_rate', 0.0) * 100)}%\n"
                    f"- **Learning Loop Wins:** Brain: {summary.get('brain_wins', 0)} | Chief of Staff: {summary.get('chief_of_staff_wins', 0)} | Ties: {summary.get('ties', 0)}\n"
                    f"- **Stage 2 Auto-Promotion Eligible:** `{eligible}`\n"
                )
            aria._speak(f"Executive Brain dashboard compiled. Active stage is {stage_desc.split(':')[0]}.")
            print(resp)
            return {"handled": True, "action": "self_improvement", "response": resp}
        except Exception as e:
            msg = f"Failed to fetch executive stats: {e}"
            aria._speak("I encountered an issue compiling the Executive Brain status.")
            return {"handled": True, "action": "self_improvement", "response": msg}

    return {"handled": False}


def handle_desktop_control(aria, inp, user_input, image=None):
    """
    Routes desktop control commands (Sprint P25.2) through AriaDesktopControlSkill.

    Handled triggers (checked against lowercase inp):
      - 'focus window <title>'   → focus_window()
      - 'type text <text>'       → type_text()
      - 'send hotkey <keys>'     → send_hotkey()
      - 'click <control name>'   → click_control()
      - 'read selected text'     → read_selected_text()
      - 'desktop log' / 'action ledger' → show recent ledger entries
      - 'desktop safety summary' → show safety tier counts
    """
    clean = inp.lower().strip()

    # Trigger guard — only handle known desktop control prefixes
    DESKTOP_TRIGGERS = [
        "focus window", "focus the window",
        "type text", "type into",
        "send hotkey", "press hotkey",
        "click control", "click the",
        "read selected text", "read selection", "what is selected",
        "desktop log", "action ledger", "desktop audit",
        "desktop safety summary", "control ledger",
    ]
    if not any(t in clean for t in DESKTOP_TRIGGERS):
        return {"handled": False}

    from skills.desktop_control_skill import AriaDesktopControlSkill

    # Lazily create a single shared instance on the aria object
    if not hasattr(aria, "desktop_control_skill") or aria.desktop_control_skill is None:
        aria.desktop_control_skill = AriaDesktopControlSkill(aria)

    ctrl: AriaDesktopControlSkill = aria.desktop_control_skill

    # ── focus window <keyword> ──────────────────────────────────────────────
    if clean.startswith("focus window ") or clean.startswith("focus the window "):
        keyword = (
            user_input.lower()
            .replace("focus window", "")
            .replace("focus the window", "")
            .strip()
        )
        success, msg = ctrl.focus_window(keyword)
        aria._speak(msg)
        return {"handled": True, "action": "desktop_control", "response": msg}

    # ── type text <content> ─────────────────────────────────────────────────
    if clean.startswith("type text ") or clean.startswith("type into "):
        text = (
            user_input
            .replace("type text ", "", 1)
            .replace("type into ", "", 1)
            .strip()
        )
        safety_level, success, msg = ctrl.type_text(text)
        if safety_level == "CONFIRM" and not success:
            aria._speak(
                "That application requires your confirmation before I can type. "
                "Shall I proceed? Say 'confirm typing' to allow."
            )
        else:
            aria._speak(msg)
        return {"handled": True, "action": "desktop_control", "response": msg}

    # ── confirm typing (follow-up approval) ────────────────────────────────
    if "confirm typing" in clean:
        # Re-run the last type_text action with user_confirmed=True
        # We store the pending text on the aria object for this follow-up flow
        pending = getattr(aria, "_pending_type_text", None)
        if pending:
            safety_level, success, msg = ctrl.type_text(pending, user_confirmed=True)
            aria._pending_type_text = None
            aria._speak(msg)
        else:
            msg = "No pending typing action found."
            aria._speak(msg)
        return {"handled": True, "action": "desktop_control", "response": msg}

    # ── send hotkey <combo> ─────────────────────────────────────────────────
    if clean.startswith("send hotkey ") or clean.startswith("press hotkey "):
        keys = (
            user_input.lower()
            .replace("send hotkey", "")
            .replace("press hotkey", "")
            .strip()
        )
        safety_level, success, msg = ctrl.send_hotkey(keys)
        if safety_level == "CONFIRM" and not success:
            aria._speak(
                f"The hotkey '{keys}' requires your confirmation before I execute it. "
                "Say 'confirm hotkey' to allow."
            )
            aria._pending_hotkey = keys
        else:
            aria._speak(msg)
        return {"handled": True, "action": "desktop_control", "response": msg}

    # ── confirm hotkey (follow-up approval) ────────────────────────────────
    if "confirm hotkey" in clean:
        pending_key = getattr(aria, "_pending_hotkey", None)
        if pending_key:
            safety_level, success, msg = ctrl.send_hotkey(pending_key, user_confirmed=True)
            aria._pending_hotkey = None
            aria._speak(msg)
        else:
            msg = "No pending hotkey action found."
            aria._speak(msg)
        return {"handled": True, "action": "desktop_control", "response": msg}

    # ── click control <name> ────────────────────────────────────────────────
    if clean.startswith("click control ") or clean.startswith("click the "):
        ctrl_name = (
            user_input
            .replace("click control ", "", 1)
            .replace("click the ", "", 1)
            .strip()
        )
        success, msg = ctrl.click_control(ctrl_name)
        aria._speak(msg)
        return {"handled": True, "action": "desktop_control", "response": msg}

    # ── read selected text ──────────────────────────────────────────────────
    if any(t in clean for t in ["read selected text", "read selection", "what is selected"]):
        success, result = ctrl.read_selected_text()
        if success:
            aria._speak(f"Selected text: {result[:200]}")
        else:
            aria._speak(result)
        return {"handled": True, "action": "desktop_control", "response": result}

    # ── desktop log / action ledger ─────────────────────────────────────────
    if any(t in clean for t in ["desktop log", "action ledger", "desktop audit", "control ledger"]):
        rows = ctrl.get_recent_actions(limit=8)
        if not rows:
            resp = "The desktop action ledger is currently empty."
            aria._speak(resp)
            return {"handled": True, "action": "desktop_control", "response": resp}

        lines = ["### ARIA Desktop Action Ledger (Last 8 entries)\n"]
        for r in rows:
            import datetime
            ts = datetime.datetime.fromtimestamp(r["timestamp"]).strftime("%H:%M:%S")
            cfm = " [CONFIRMED]" if r.get("confirmed_by_user") else ""
            lines.append(
                f"  `{ts}` [{r['action_type']}] {r['target_process_name']} — "
                f"**{r['safety_level']}**{cfm} → {r['execution_result']}"
            )
        resp = "\n".join(lines)
        aria._speak("Here is the recent desktop action audit log.")
        print(resp)
        return {"handled": True, "action": "desktop_control", "response": resp}

    # ── desktop safety summary ──────────────────────────────────────────────
    if "desktop safety summary" in clean:
        summary = ctrl.get_safety_summary()
        safe_c    = summary.get("SAFE", 0)
        confirm_c = summary.get("CONFIRM", 0)
        blocked_c = summary.get("BLOCKED", 0)
        resp = (
            f"### Desktop Control Safety Summary\n"
            f"- **SAFE** actions executed: {safe_c}\n"
            f"- **CONFIRM** actions intercepted: {confirm_c}\n"
            f"- **BLOCKED** actions rejected: {blocked_c}"
        )
        aria._speak(f"Safety summary — {safe_c} safe, {confirm_c} confirm intercepts, {blocked_c} blocked.")
        print(resp)
        return {"handled": True, "action": "desktop_control", "response": resp}

    return {"handled": False}


def handle_chrome_cdp(aria, inp, user_input, image=None):
    """
    Routes Chrome CDP Browser Attachment commands (Sprint P25.3) through AriaBrowserAttachmentSkill.
    """
    clean = inp.lower().strip()

    CDP_TRIGGERS = [
        "sync browser tabs", "scan browser",
        "show open tabs", "browser tabs", "browser status",
        "read tab",
        "allow tab",
        "deny tab",
        "chrome debuggable", "is chrome running"
    ]
    if not any(t in clean for t in CDP_TRIGGERS):
        return {"handled": False}

    from skills.browser_attachment_skill import AriaBrowserAttachmentSkill

    if not hasattr(aria, "browser_attachment_skill") or aria.browser_attachment_skill is None:
        aria.browser_attachment_skill = AriaBrowserAttachmentSkill(aria)

    skill: AriaBrowserAttachmentSkill = aria.browser_attachment_skill

    # ── sync browser tabs / scan browser ──────────────────────────────────────────
    if "sync browser tabs" in clean or "scan browser" in clean:
        stats = skill.sync_live_tabs()
        if stats.get("status") == "SUCCESS":
            msg = (
                f"Browser tabs synchronized successfully ({stats['mode']} mode).\n"
                f"- Tabs found: {stats['tabs_found']}\n"
                f"- Auto-denied (protected): {stats['tabs_denied']}\n"
                f"- Awaiting approval (ASK): {stats['tabs_ask']}\n"
                f"- Previously allowed: {stats['tabs_allowed']}"
            )
            aria._speak(f"Browser sync complete. Found {stats['tabs_found']} tabs.")
        else:
            msg = f"Failed to sync browser tabs: {stats.get('error', 'unknown error')}"
            aria._speak("I encountered an error trying to synchronize browser tabs.")
        return {"handled": True, "action": "browser_cdp", "response": msg}

    # ── show open tabs / browser tabs / browser status ───────────────────────────
    if any(t in clean for t in ["show open tabs", "browser tabs", "browser status"]):
        tabs = skill.get_tab_list(limit=20)
        if not tabs:
            msg = "No browser tabs found in the ledger. Run 'sync browser tabs' to scan."
            aria._speak(msg)
            return {"handled": True, "action": "browser_cdp", "response": msg}

        lines = ["### ARIA Active Browser Tabs Ledger\n"]
        for t in tabs:
            import datetime
            ts = datetime.datetime.fromtimestamp(t['last_seen_timestamp']).strftime("%H:%M:%S")
            lines.append(
                f"- **{t['tab_id']}** | {t['tab_title'][:50]} | `{t['permission_tier']}` | {t['domain_segment']} (seen {ts})"
            )
        msg = "\n".join(lines)
        aria._speak("Here is the list of active browser tabs.")
        return {"handled": True, "action": "browser_cdp", "response": msg}

    # ── read tab <id> ─────────────────────────────────────────────────────────────
    if clean.startswith("read tab "):
        tab_id = clean.replace("read tab", "").strip()
        status_code, text = skill.read_tab_metadata(tab_id)
        if status_code == "ALLOWED":
            aria._speak(f"Successfully read tab metadata for {tab_id}.")
        else:
            aria._speak(text)
        return {"handled": True, "action": "browser_cdp", "response": text}

    # ── allow tab <id> ────────────────────────────────────────────────────────────
    if clean.startswith("allow tab "):
        tab_id = clean.replace("allow tab", "").strip()
        success, text = skill.set_tab_permission(tab_id, "ALLOWED")
        aria._speak(text)
        return {"handled": True, "action": "browser_cdp", "response": text}

    # ── deny tab <id> ─────────────────────────────────────────────────────────────
    if clean.startswith("deny tab "):
        tab_id = clean.replace("deny tab", "").strip()
        success, text = skill.set_tab_permission(tab_id, "DENIED")
        aria._speak(text)
        return {"handled": True, "action": "browser_cdp", "response": text}

    # ── chrome debuggable / is chrome running ─────────────────────────────────────
    if "chrome debuggable" in clean or "is chrome running" in clean:
        is_debug = skill.is_chrome_debuggable()
        if is_debug:
            msg = "Chrome is running with remote debugging enabled on port 9222."
            aria._speak(msg)
        else:
            msg = "Chrome remote debugging port (9222) is not responding. Please launch Chrome with --remote-debugging-port=9222."
            aria._speak("Chrome debugging is not available.")
        return {"handled": True, "action": "browser_cdp", "response": msg}

    return {"handled": False}


def handle_vscode_bridge(aria, inp, user_input, image=None):
    """
    Routes VS Code Intelligence Bridge commands (Sprint P25.4) through AriaVsCodeBridgeSkill.
    """
    clean = inp.lower().strip()

    VSCODE_TRIGGERS = [
        "workspace status", "vscode status", "code status",
        "workspace summary", "vscode summary", "code summary",
        "active file", "what file", "current file",
        "code errors", "diagnostics", "workspace errors",
        "my selection", "selected code",
        "start vscode bridge", "start code bridge",
        "bridge status", "vscode bridge"
    ]
    if not any(t in clean for t in VSCODE_TRIGGERS):
        return {"handled": False}

    if not hasattr(aria, "vscode_bridge_server") or aria.vscode_bridge_server is None:
        from skills.vscode_bridge_skill import AriaVsCodeBridgeServer
        db_path = getattr(aria, "db_path", "aria_orchestrator.db")
        aria.vscode_bridge_server = AriaVsCodeBridgeServer(db_path=db_path)

    if not hasattr(aria, "vscode_bridge_skill") or aria.vscode_bridge_skill is None:
        from skills.vscode_bridge_skill import AriaVsCodeBridgeSkill
        db_path = getattr(aria, "db_path", "aria_orchestrator.db")
        aria.vscode_bridge_skill = AriaVsCodeBridgeSkill(db_path=db_path, server=aria.vscode_bridge_server)

    server = aria.vscode_bridge_server
    skill = aria.vscode_bridge_skill

    # Lazy start the server for status/query commands if not already running
    if not server.is_running() and not any(t in clean for t in ["bridge status", "vscode bridge"]):
        server.start()

    # ── start vscode bridge / start code bridge ───────────────────────────
    if "start vscode bridge" in clean or "start code bridge" in clean:
        success = server.start()
        if success:
            msg = "VS Code Bridge HTTP server started on http://127.0.0.1:9821."
            aria._speak("VS Code bridge is now running.")
        else:
            msg = "Failed to start VS Code Bridge (is Flask installed?)."
            aria._speak("I failed to start the VS Code bridge.")
        return {"handled": True, "action": "vscode_bridge", "response": msg}

    # ── bridge status / vscode bridge ─────────────────────────────────────
    if any(t in clean for t in ["bridge status", "vscode bridge"]):
        is_alive = skill.is_bridge_server_alive()
        status_str = "active and listening on http://127.0.0.1:9821" if is_alive else "offline (not running)"
        msg = f"VS Code Bridge is currently {status_str}."
        aria._speak(f"VS Code bridge is {'active' if is_alive else 'offline'}.")
        return {"handled": True, "action": "vscode_bridge", "response": msg}

    # ── workspace status / vscode status / code status / summary ──────────
    if any(t in clean for t in ["workspace status", "vscode status", "code status", "workspace summary", "vscode summary", "code summary"]):
        summary = skill.format_workspace_summary()
        snap = skill.get_workspace_snapshot()
        if snap:
            import os
            filename = os.path.basename(snap.get("active_file", "")) if snap.get("active_file") else "no file"
            aria._speak(f"VS Code status: active file is {filename}.")
        else:
            aria._speak("No active VS Code workspace data is available yet.")
        return {"handled": True, "action": "vscode_bridge", "response": summary}

    # ── active file / what file / current file ───────────────────────────
    if any(t in clean for t in ["active file", "what file", "current file"]):
        active = skill.get_active_file()
        if active:
            msg = f"The active file in VS Code is:\n`{active}`"
            import os
            aria._speak(f"The active file is {os.path.basename(active)}.")
        else:
            msg = "No active file is currently reported by VS Code."
            aria._speak("No active file is open in VS Code.")
        return {"handled": True, "action": "vscode_bridge", "response": msg}

    # ── code errors / diagnostics / workspace errors ─────────────────────
    if any(t in clean for t in ["code errors", "diagnostics", "workspace errors"]):
        sev = "ERROR" if "error" in clean else None
        diags = skill.get_diagnostics(limit=20, severity=sev)
        if not diags:
            msg = "No diagnostics were reported for the active file."
            aria._speak("No workspace errors reported.")
        else:
            lines = ["### VS Code Diagnostics Log\n"]
            for d in diags:
                lines.append(f"- **{d['severity']}** | `{d['file_name']}` (line {d['line_number']}): {d['message']}")
            msg = "\n".join(lines)
            aria._speak(f"Found {len(diags)} diagnostics in the log.")
        return {"handled": True, "action": "vscode_bridge", "response": msg}

    # ── my selection / selected code ──────────────────────────────────────
    if any(t in clean for t in ["my selection", "selected code"]):
        selection = skill.get_selection()
        if selection:
            msg = f"Current VS Code selection:\n```\n{selection}\n```"
            aria._speak("Here is your current selection in VS Code.")
        else:
            msg = "No text is currently selected in VS Code."
            aria._speak("No text is currently selected in VS Code.")
        return {"handled": True, "action": "vscode_bridge", "response": msg}

    return {"handled": False}


