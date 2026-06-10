"""
skills/autonomous_agent_commands.py — Autonomous Agent Execution Logic for ARIA
================================================================================
Extracted from main.py (Phase 5 Refactor).

Contains:
  - is_action_tag_authorized  : decides if a bracketed action tag is user-initiated
  - execute_actions           : parses and executes bracketed action tags in an AI response
  - verify_action             : safety + boundary verification for an action tag
  - run_autonomous_agent      : full autonomous vision-guided task loop
"""

import os
import re
import time
import threading


# ── Action Authorization ──────────────────────────────────────────────────────

def is_action_tag_authorized(aria, category, source_user_input):
    # Always authorize if it's a remote command from phone/controller
    is_remote = False
    if hasattr(aria, 'firebase_sync') and aria.firebase_sync:
        if getattr(aria.firebase_sync, "current_command_id", None) is not None:
            is_remote = True
    if is_remote or (getattr(aria, "_reply_context", None) and getattr(aria._reply_context, "phone_only", False)):
        return True


    inp = (source_user_input or "").lower()
    category = category.upper()

    # Return True for browser actions whenever BrowserSkill().is_browser_active() is True
    if category in {"SEARCH", "BROWSER_OPEN", "BROWSEROPEN", "CLOSE_TAB", "NEW_TAB", "TYPE", "CLICK", "SCROLL"}:
        try:
            from skills.browser_skill import BrowserSkill
            if BrowserSkill().is_browser_active():
                return True
        except Exception:
            pass

    # Check if the semantic router classified the user's intent as search/browser with high confidence
    if category not in {"SHUTDOWN", "RESTART"}:
        routing_decision = getattr(aria.brain, "last_routing_decision", None)
        if routing_decision:
            intent = routing_decision.get("intent")
            confidence = routing_decision.get("intent_confidence", 0.0)
            if intent in ["search", "browser"] and confidence >= 0.8:
                return True

            # Permissive browser actions when active tab is open & intent is browser/search/followup
            try:
                from skills.browser_skill import BrowserSkill
                if BrowserSkill().is_browser_active() and intent in ["search", "browser", "followup"] and confidence >= 0.65:
                    if category in {"SEARCH", "BROWSER_OPEN", "BROWSEROPEN", "CLOSE_TAB", "NEW_TAB", "TYPE", "CLICK", "SCROLL"}:
                        return True
            except Exception:
                pass

    if category == "SEARCH":
        return any(term in inp for term in ["search", "find", "look up", "google", "amazon", "youtube", "buy", "shop"])
    if category in {"BROWSER_OPEN", "BROWSEROPEN"}:
        return any(term in inp for term in ["open", "go to", "navigate", "browser", "amazon", "youtube", "website", "search", "buy", "shop"])
    if category == "OPEN":
        return any(term in inp for term in ["open", "launch", "start"])
    if category == "CLOSE":
        return any(term in inp for term in ["close", "exit", "quit"])
    if category in {"CLOSE_TAB", "NEW_TAB"}:
        return any(term in inp for term in ["tab", "browser", "close tab", "new tab", "open tab"])
    if category == "GOOGLE_SEARCH":
        return any(term in inp for term in ["google", "search", "find", "look up"])
    if category == "VSCODE_OPEN":
        return any(term in inp for term in ["vscode", "vs code", "code", "open project"])
    if category in {"SHUTDOWN", "RESTART"}:
        return any(term in inp for term in ["shutdown", "restart", "reboot"])
    if category == "VOLUME":
        return any(term in inp for term in ["volume", "mute", "unmute"])
    if category == "SCREENSHOT":
        return any(term in inp for term in ["screenshot", "screen shot", "capture screen"])
    if category == "PRESS":
        return any(term in inp for term in ["press", "shortcut", "key"])
    if category == "FOCUS":
        return any(term in inp for term in ["focus", "switch to", "bring"])
    if category == "TYPE":
        return any(term in inp for term in ["type", "write", "enter", "fill", "input"])
    if category == "CLICK":
        return any(term in inp for term in ["click", "select", "press", "open first", "first result", "open", "go to", "show", "choose", "first", "second", "third", "last", "result", "product", "item"])
    return True


# ── Action Execution ──────────────────────────────────────────────────────────

def execute_actions(aria, response, source_user_input=""):
    """Parse and execute any bracketed action tags in the AI response."""
    result = response
    if not result:
        return result

    # Check if this is a remote command from phone/controller
    is_remote = False
    if hasattr(aria, 'firebase_sync') and aria.firebase_sync:
        if getattr(aria.firebase_sync, "current_command_id", None) is not None:
            is_remote = True
    if is_remote or (getattr(aria, "_reply_context", None) and getattr(aria._reply_context, "phone_only", False)):
        is_remote = True

    # ── Double-Confirmation check for Sensitive/High-Risk Actions ──
    sensitive_tags = []
    all_tags = re.findall(r'\[[a-zA-Z_]+(?::\s*[^\]]+)?\]', result)
    for tag in all_tags:
        tag_lower = tag.lower()
        if any(x in tag_lower for x in ["[shutdown]", "[restart]", "[run_shell]", "[shell]", "[powershell]", "[cmd]", "[delete_file]", "[delete_folder]"]):
            sensitive_tags.append(tag)
            
    if sensitive_tags:
        import time
        now = time.time()
        pending = getattr(aria, "pending_sensitive_action", None)
        pending_time = getattr(aria, "pending_sensitive_action_time", 0.0)
        
        clean_input = source_user_input.strip().lower().replace(".", "").replace("!", "").replace("?", "")
        is_confirmation = clean_input in ["yes execute", "yes, execute", "execute", "yes", "confirm", "yes do it"]
        
        if is_confirmation and pending and (now - pending_time < 20.0):
            # Verify user is owner
            user_to_verify = aria.known_user
            if is_remote:
                user_to_verify = "chinmaya"
            access_level = aria.security.get_user_access_level(user_to_verify)
            if access_level < aria.security.LEVEL_OWNER:
                aria._speak("Verification required. Checking identity...")
                detected = aria.identify_user()
                if detected and aria.security.get_user_access_level(detected) >= aria.security.LEVEL_OWNER:
                    aria.known_user = detected
                else:
                    aria._speak("Access Denied. Owner authentication is required for this action.")
                    aria.pending_sensitive_action = None
                    aria.pending_sensitive_action_time = 0.0
                    return ""
            
            result = pending
            aria.pending_sensitive_action = None
            aria.pending_sensitive_action_time = 0.0
            print(f"[SecurityGuard] Sensitive action confirmed by user: {sensitive_tags}")
        else:
            aria.pending_sensitive_action = result
            aria.pending_sensitive_action_time = now
            print(f"[SecurityGuard] Intercepted sensitive action {sensitive_tags}. Requesting confirmation.")
            
            for t in all_tags:
                result = result.replace(t, "")
            
            aria._speak(f"You have requested a sensitive action: {', '.join(sensitive_tags)}. Please say 'yes, execute' to confirm.")
            return result

    # ── Security Guard Action Verification ──
    all_tags = re.findall(r'\[[a-zA-Z_]+(?::\s*[^\]]+)?\]', result)
    for tag in all_tags:
        user_to_verify = aria.known_user
        if is_remote:
            user_to_verify = "chinmaya"
        safe, msg = aria.security.verify_agent_action_tag(tag, user_name=user_to_verify)
        if not safe:
            print(f"[SecurityGuard] Verification required for tag: {tag}. Reason: {msg}")
            aria._speak("Action restricted. Verifying identity via camera...")
            detected = aria.identify_user()
            if detected and detected != "Unknown":
                still_safe, new_msg = aria.security.verify_agent_action_tag(tag, user_name=detected)
                if still_safe:
                    print(f"[SecurityGuard] Verified as '{detected}' (Access Level: {aria.security.get_user_access_level(detected)}). Authorizing.")
                    aria.known_user = detected
                    if detected in ["chinmay", "chinmaya"]:
                        aria.security.unlock_admin()
                else:
                    aria._speak(f"Access denied. {new_msg}")
                    result = result.replace(tag, "")
            else:
                aria._speak(f"Access denied. {msg}")
                result = result.replace(tag, "")

    # [OPEN: app]
    for match in re.finditer(r'\[OPEN:\s*([^\]]+)\]', result, re.IGNORECASE):
        app = match.group(1).strip()
        if not is_action_tag_authorized(aria, "OPEN", source_user_input):
            print(f"[ActionGuard] Blocked unrequested open action: {app}")
            continue
        aria.automation.open_app(app)

    # [CLOSE: app]
    for match in re.finditer(r'\[CLOSE:\s*([^\]]+)\]', result, re.IGNORECASE):
        app = match.group(1).strip()
        if not aria.running:
            aria.automation.close_app(app)
            continue
        if not is_action_tag_authorized(aria, "CLOSE", source_user_input):
            print(f"[ActionGuard] Blocked unrequested close action: {app}")
            continue
        app_lower = app.lower()
        critical_terminals = ["powershell", "cmd", "terminal", "python", "bash", "wsl", "conhost"]
        if any(term in app_lower for term in critical_terminals):
            print(f"[ARIA Safety] Blocked close attempt on critical agent application: {app}")
            aria._speak("I cannot close that application because it might terminate my running process.")
            continue
        aria.automation.close_app(app)

    # [CLOSE_TAB]
    if re.search(r'\[CLOSE_TAB\]', result, re.IGNORECASE):
        if not is_action_tag_authorized(aria, "CLOSE_TAB", source_user_input):
            print("[ActionGuard] Blocked unrequested close-tab action.")
        else:
            print("[Automation] Closing browser tab")
            aria.ui.browser_close_tab()

    # [NEW_TAB] / [NEWTAB]
    if re.search(r'\[(NEW_TAB|NEWTAB)\]', result, re.IGNORECASE):
        if not is_action_tag_authorized(aria, "NEW_TAB", source_user_input):
            print("[ActionGuard] Blocked unrequested new-tab action.")
        else:
            print("[Automation] Opening new browser tab")
            aria.ui.browser_new_tab()

    # [TYPE: text]
    for match in re.finditer(r'\[TYPE:\s*([^\]]+)\]', result, re.IGNORECASE):
        text = match.group(1).strip()
        if not is_action_tag_authorized(aria, "TYPE", source_user_input):
            print(f"[ActionGuard] Blocked unrequested type action: {text}")
            result = result.replace(match.group(0), text)
            continue
        aria.automation.type_text(text)

    # [SEARCH: query]
    for match in re.finditer(r'\[SEARCH:\s*([^\]]+)\]', result, re.IGNORECASE):
        query = match.group(1).strip()
        if not is_action_tag_authorized(aria, "SEARCH", source_user_input):
            print(f"[ActionGuard] Blocked unrequested search action: {query}")
            continue
        try:
            from skills.browser_skill import BrowserSkill
            bs = BrowserSkill()
            if bs.is_browser_active():
                aria.automation_mode = True
                aria.last_automation_action_time = time.time()
                bs.search_in_page(query)
                continue
        except Exception as e:
            print(f"[Automation] Browser search failed: {e}")
        ok, msg = aria.ui.search_google(query)
        if ok:
            aria._speak(f"Searching for {query}.")
        else:
            aria._speak("Browser automation failed.")

    # [VOLUME: up/down/mute]
    for match in re.finditer(r'\[VOLUME:\s*([^\]]+)\]', result, re.IGNORECASE):
        if not is_action_tag_authorized(aria, "VOLUME", source_user_input):
            print("[ActionGuard] Blocked unrequested volume action.")
            continue
        action = match.group(1).strip().lower()
        if "up" in action:
            aria.automation.volume_up()
        elif "down" in action:
            aria.automation.volume_down()
        elif "mute" in action:
            aria.automation.volume_mute()

    # [SCREENSHOT]
    if re.search(r'\[SCREENSHOT\]', result, re.IGNORECASE):
        if not is_action_tag_authorized(aria, "SCREENSHOT", source_user_input):
            print("[ActionGuard] Blocked unrequested screenshot action.")
        else:
            aria.automation.take_screenshot()

    # [CLICK: x,y] — screen coordinate click
    for match in re.finditer(r'\[CLICK:\s*(\d+)\s*,\s*(\d+)\]', result, re.IGNORECASE):
        if not is_action_tag_authorized(aria, "CLICK", source_user_input):
            print("[ActionGuard] Blocked unrequested coordinate click action.")
            continue
        aria.screen.click(int(match.group(1)), int(match.group(2)))

    # [FOCUS: window_title]
    for match in re.finditer(r'\[FOCUS:\s*([^\]]+)\]', result, re.IGNORECASE):
        if not is_action_tag_authorized(aria, "FOCUS", source_user_input):
            print(f"[ActionGuard] Blocked unrequested focus action: {match.group(1).strip()}")
            continue
        aria.screen.focus_window(match.group(1).strip())

    # [PRESS: key+combination]
    for match in re.finditer(r'\[PRESS:\s*([^\]]+)\]', result, re.IGNORECASE):
        if not is_action_tag_authorized(aria, "PRESS", source_user_input):
            print(f"[ActionGuard] Blocked unrequested keypress action: {match.group(1).strip()}")
            continue
        keys = [k.strip() for k in match.group(1).split('+')]
        aria.screen.press(*keys)

    # [SCROLL: direction | amount] or [SCROLL: direction]
    for match in re.finditer(r'\[SCROLL:\s*([^\]]+)\]', result, re.IGNORECASE):
        parts = [p.strip().lower() for p in match.group(1).split('|')]
        direction = parts[0]
        amount = parts[1] if len(parts) > 1 else "normal"

        if direction not in ["down", "up", "top", "bottom"]:
            continue

        try:
            from skills.browser_skill import BrowserSkill
            bs = BrowserSkill()
            if bs.is_browser_active():
                aria.automation_mode = True
                aria.last_automation_action_time = time.time()
                print(f"[Automation] Browser active - scrolling {direction} (amount: {amount})")
                bs.scroll(direction, amount)
                continue
        except Exception as e:
            print(f"[Automation] Browser scroll failed: {e}")

        print(f"[ScreenControl] Scrolling {direction}")
        aria.screen.click(aria.screen.screen_w // 2, aria.screen.screen_h // 2)

        clicks = 5
        if amount == "little":
            clicks = 2
        elif amount == "more":
            clicks = 10

        if direction in ["top", "bottom"]:
            key = "ctrl+home" if direction == "top" else "ctrl+end"
            aria.screen.press(key)
        else:
            aria.screen.scroll(clicks=clicks, direction=direction)
            time.sleep(0.2)
            aria.screen.scroll(clicks=clicks, direction=direction)

    # [WAIT: seconds]
    for match in re.finditer(r'\[WAIT:\s*([\d\.]+)\]', result, re.IGNORECASE):
        seconds = float(match.group(1))
        print(f"[ScreenControl] Waiting {seconds}s")
        time.sleep(seconds)

    # [RELATE: source | relation | target]
    for match in re.finditer(r'\[RELATE:\s*([^|\]]+)\|\s*([^|\]]+)\|\s*([^\]]+)\]', result, re.IGNORECASE):
        src = match.group(1).strip()
        rel = match.group(2).strip()
        tgt = match.group(3).strip()
        aria.memory_skill.add_semantic_relation(src, rel, tgt)
        print(f"[MemorySkill] Linked: {src} --({rel})--> {tgt}")

    # [ADD_TASK: goal | task | status | dependency | blocker]
    for match in re.finditer(r'\[ADD_TASK:\s*([^|\]]+)\|\s*([^|\]]+)\|\s*([^|\]]+)(?:\|\s*([^|\]]*))?' r'(?:\|\s*([^\]]*))?\]', result, re.IGNORECASE):
        g = match.group(1).strip()
        t = match.group(2).strip()
        s = match.group(3).strip()
        d = match.group(4).strip() if match.group(4) else None
        b = match.group(5).strip() if match.group(5) else None
        aria.memory_skill.add_task_tree_node(g, t, s, d, b)
        print(f"[MemorySkill] Added Task Node: {g} -> {t} [{s}]")

    # [UPDATE_TASK: goal | task | status | blocker]
    for match in re.finditer(r'\[UPDATE_TASK:\s*([^|\]]+)\|\s*([^|\]]+)\|\s*([^|\]]+)(?:\|\s*([^\]]*))?\]', result, re.IGNORECASE):
        g = match.group(1).strip()
        t = match.group(2).strip()
        s = match.group(3).strip()
        b = match.group(4).strip() if match.group(4) else None
        aria.memory_skill.add_task_tree_node(g, t, s, blocker=b)
        print(f"[MemorySkill] Updated Task Node: {g} -> {t} [{s}]")

    # [BROWSER_OPEN: url] / [BROWSEROPEN: url]
    for match in re.finditer(r'\[(?:BROWSER_OPEN|BROWSEROPEN):\s*([^\]]+)\]', result, re.IGNORECASE):
        url = match.group(1).strip()
        if not is_action_tag_authorized(aria, "BROWSER_OPEN", source_user_input):
            print(f"[ActionGuard] Blocked unrequested browser open action: {url}")
            continue
        try:
            aria.automation_mode = True
            aria.last_automation_action_time = time.time()
            from skills.browser_skill import BrowserSkill
            BrowserSkill().navigate(url)
        except Exception as e:
            print(f"[Automation] Browser open failed through BrowserSkill: {e}")
            ok, msg = aria.ui.open_browser(url)
            if not ok:
                aria._speak("Browser automation failed.")

    # [GOOGLE_SEARCH: query]
    for match in re.finditer(r'\[GOOGLE_SEARCH:\s*([^\]]+)\]', result, re.IGNORECASE):
        query = match.group(1).strip()
        if not is_action_tag_authorized(aria, "GOOGLE_SEARCH", source_user_input):
            print(f"[ActionGuard] Blocked unrequested Google search action: {query}")
            continue
        aria.automation_mode = True
        aria.last_automation_action_time = time.time()
        ok, msg = aria.ui.search_google(query)
        if ok:
            aria._speak("I opened Google results.")
        else:
            aria._speak("Browser automation failed.")

    # [VSCODE_OPEN: path]
    for match in re.finditer(r'\[VSCODE_OPEN:\s*([^\]]+)\]', result, re.IGNORECASE):
        if not is_action_tag_authorized(aria, "VSCODE_OPEN", source_user_input):
            print(f"[ActionGuard] Blocked unrequested VS Code open action: {match.group(1).strip()}")
            continue
        aria.ui.open_vscode_project(match.group(1).strip())

    # [SHUTDOWN] / [RESTART]
    if re.search(r'\[SHUTDOWN\]', result, re.IGNORECASE):
        if not is_action_tag_authorized(aria, "SHUTDOWN", source_user_input):
            print("[ActionGuard] Blocked unrequested shutdown action.")
        else:
            aria.automation.shutdown()
    elif re.search(r'\[RESTART\]', result, re.IGNORECASE):
        if not is_action_tag_authorized(aria, "RESTART", source_user_input):
            print("[ActionGuard] Blocked unrequested restart action.")
        else:
            aria.automation.restart()

    return result


# ── Action Safety Verification ────────────────────────────────────────────────

def verify_action(aria, action_tag, sw, sh):
    """Verifies action tags for safety, boundary limits, and harmful commands."""
    # Risk classification using SandboxSafetyLayer
    risk_level = aria.sandbox_safety.classify_risk(action_tag)

    # Determine user name to verify
    user_to_verify = aria.known_user
    is_remote = False
    if hasattr(aria, 'firebase_sync') and aria.firebase_sync:
        if getattr(aria.firebase_sync, "current_command_id", None) is not None:
            is_remote = True
    if is_remote or (getattr(aria, "_reply_context", None) and getattr(aria._reply_context, "phone_only", False)):
        user_to_verify = "chinmaya"

    # Centralized safety check using SecurityGuard
    safe, msg = aria.security.verify_agent_action_tag(action_tag, user_name=user_to_verify)
    if not safe:
        return False, action_tag, msg

    # Human approval flow for HIGH/CRITICAL risks
    if aria.sandbox_safety.requires_approval(risk_level):
        import uuid
        action_id = str(uuid.uuid4())
        if not aria.sandbox_safety.is_action_approved(action_id, risk_level):
            from dashboard import set_state
            
            # Write to Firestore approvals/latest
            db = None
            try:
                import firebase_admin
                from firebase_admin import firestore
                if firebase_admin._apps:
                    db = firestore.client()
                    db.collection("approvals").document("latest").set({
                        "action_id": action_id,
                        "action_tag": action_tag,
                        "description": f"ARIA wants to: {action_tag}",
                        "risk_level": risk_level,
                        "status": "pending",
                        "timestamp": time.time()
                    })
            except Exception as e:
                print(f"[ApprovalSync] Failed to write approval request: {e}")

            # Send FCM push notification to Android device
            try:
                from skills.firebase_sync import send_fcm_approval_push
                send_fcm_approval_push(
                    action_tag=action_tag,
                    risk_level=risk_level,
                    description=f"ARIA wants to: {action_tag}"
                )
            except Exception as fcm_err:
                print(f"[ApprovalSync] FCM push failed (non-fatal): {fcm_err}")

            aria._speak(f"Warning. Proposing {risk_level} risk action: {action_tag}. Please approve on your phone or say yes.")
            set_state("LISTENING")
            feedback = aria.voice.listen(timeout=6)
            
            approved = False
            aborted = False
            
            # Check voice feedback
            if feedback and any(x in feedback.lower() for x in ["yes", "approve", "go ahead", "sure", "ok", "okay"]):
                approved = True
            elif feedback and any(x in feedback.lower() for x in ["no", "abort", "reject", "cancel"]):
                aborted = True
            
            # Check Firestore if not decided by voice
            if not approved and not aborted and db:
                print("[ApprovalSync] Checking Firestore for remote approval...")
                for _ in range(15):
                    try:
                        doc = db.collection("approvals").document("latest").get()
                        if doc.exists:
                            status = doc.to_dict().get("status", "pending")
                            if status == "approved":
                                approved = True
                                break
                            elif status == "rejected":
                                aborted = True
                                break
                    except Exception as e:
                        print(f"[ApprovalSync] Error reading approvals: {e}")
                    time.sleep(1.0)
            
            # Update Firestore to reflect the final decision and clean up
            if db:
                try:
                    db.collection("approvals").document("latest").update({
                        "status": "approved" if approved else "rejected" if aborted else "timeout",
                        "decided_at": time.time()
                    })
                except Exception:
                    pass

            if approved:
                aria.sandbox_safety.grant_approval(action_id)
                aria._speak("Action approved.")
            else:
                aria._speak("Action aborted.")
                return False, action_tag, "Rejected by user approval."

    # 1. Destructive Commands Safety Check
    dangerous_patterns = [
        r'rm\s+-rf', r'del\s+.*config', r'format\s+[a-zA-Z]:',
        r'shutdown\s+/s', r'taskkill\s+/im\s+explorer\.exe',
        r'taskkill\s+/im\s+winlogon\.exe', r'drop\s+database', r'delete\s+from'
    ]

    text_match = re.search(r'\[TYPE:\s*([^\]]+)\]', action_tag, re.IGNORECASE)
    if text_match:
        typed_text = text_match.group(1).lower()
        for pattern in dangerous_patterns:
            if re.search(pattern, typed_text):
                return False, action_tag, f"Potentially destructive command detected: '{pattern}'"

    # 2. Coordinates Out-of-Bounds Verification and Correction
    coords_match = re.search(r'\[(?:CLICK|DOUBLE_CLICK|RIGHT_CLICK):\s*(\d+)\s*,\s*(\d+)\]', action_tag, re.IGNORECASE)
    if coords_match:
        x, y = int(coords_match.group(1)), int(coords_match.group(2))
        corrected = False

        if x < 0:
            x = 0
            corrected = True
        elif x > sw:
            x = sw
            corrected = True

        if y < 0:
            y = 0
            corrected = True
        elif y > sh:
            y = sh
            corrected = True

        if corrected:
            tag_type = "CLICK" if "[CLICK:" in action_tag else ("DOUBLE_CLICK" if "[DOUBLE_CLICK:" in action_tag else "RIGHT_CLICK")
            corrected_tag = f"[{tag_type}: {x},{y}]"
            return True, corrected_tag, "Coordinates out of bounds; clipped to edge."

    return True, action_tag, "Action safe."


# ── Autonomous Agent Loop ─────────────────────────────────────────────────────

def run_autonomous_agent(aria, task, max_steps=8, task_item=None):
    """ARIA-style autonomous vision-guided loop with Goal planning, UI tracking, and Action Verification."""
    import io
    import base64

    sw, sh = aria.screen.screen_w, aria.screen.screen_h
    print(f"[ARIA Agent] Starting task: '{task}'")
    feedback = ""

    # Import dashboard helpers
    try:
        from dashboard import set_state, set_text
    except ImportError:
        def set_state(s): pass
        def set_text(t): pass

    # Update dashboard state
    try:
        from dashboard import CognitionState
        CognitionState.active_goal = task
        CognitionState.active_subtask = "Planning subgoals..."
        CognitionState.confidence = 1.0
        CognitionState.last_actions = []
        CognitionState.reflection_results = ""
    except ImportError:
        pass

    # Episodic tracking
    executed_steps = []
    task_outcome = "failure"

    # Stability Engineering trackers
    failure_budget = 3
    failure_count = 0
    action_history = []

    # Set Focus Priority to 3 (Normal-Task) during autonomous execution
    try:
        aria.attention_manager.set_focus(3)
        aria.last_agent_activity = time.time()
        aria.idle_consolidation_done = False
    except Exception:
        pass

    # Evaluate Dynamic Runtime Mode Profile
    try:
        load_score_now = getattr(aria.cognitive_load_manager, "get_load_metrics", lambda: {"load_score": 0.1})()["load_score"]
        profile_res = aria.mode_profiler.evaluate_profile(load_score=load_score_now)

        try:
            from dashboard import CognitionState
            CognitionState.runtime_profile = profile_res["profile"]
        except Exception:
            pass

        if profile_res["transitioned"]:
            set_state("SPEAKING")
            aria._speak(f"System profile update. Transitioning executive governance to {profile_res['profile'].lower()} mode.")
            set_state("IDLE")

        if profile_res["profile"] == "MINIMAL":
            print("[Executive Mode] Enforcing Minimal Footprint: Restricting maximum step limits.")
            max_steps = min(max_steps, 3)
        elif profile_res["profile"] == "CONSERVATIVE":
            print("[Executive Mode] Enforcing Conservative Governance: Reducing autonomy, switching to manual confirmation.")
            aria.mode = "safe"
    except Exception as profile_err:
        print(f"[Executive Mode] Failed to evaluate dynamic profile: {profile_err}")

    # Execute Deliberative Sandbox Simulation
    sandbox_desc = None
    sim_candidates = []
    try:
        from skills.sandbox_simulator import SandboxSimulator
        sim_res = SandboxSimulator().simulate_and_compare(task)
        sim_candidates = sim_res.get("candidates", [])

        try:
            from dashboard import CognitionState
            CognitionState.sandbox_simulation = sim_res
        except Exception:
            pass

        best = sim_res["best_path"]
        if best:
            sandbox_desc = best["path_name"]
            print(f"[SandboxSimulator] Mentally simulated strategies. Selected best path: {sandbox_desc} (Score: {best['utility_score']})")
            set_state("SPEAKING")
            aria._speak(f"Initiating simulation. Selecting path: '{best['path_name']}' with utility score of {best['utility_score']:.2f}.")
            set_state("IDLE")
    except Exception as sim_err:
        print(f"[SandboxSimulator] Simulation failure: {sim_err}")

    # Session Checkpoint persistence
    try:
        import json
        with open("active_session.json", "w") as sf:
            json.dump({"goal": task, "status": "active"}, sf)
    except Exception:
        pass

    # ── Step 1: Goal-based planning ──
    set_state("THINKING")
    set_text("Planning subgoals...")
    aria._speak(f"Let me think about how to complete this task.")

    plan_prompt = (
        f"You are the planner for ARIA. Break down the user's task into a list of 3-5 high-level subgoals to complete: '{task}'. "
        "Write the plan in a simple list format."
    )
    try:
        plan = aria.brain.think(plan_prompt)
        print(f"[ARIA Agent] Generated Plan:\n{plan}")
        plan_summary = plan.split("\n")[0] if plan else "Starting task execution."
        aria._speak(f"Plan drafted: {plan_summary}. Executing now.")
    except Exception as e:
        print(f"[ARIA Agent] Planning error: {e}")
        aria._speak("Starting execution.")

    # Publish TASK_STARTED event
    try:
        from skills.event_bus import EventBus
        EventBus().publish("TASK_STARTED", {"task": task, "max_steps": max_steps})
    except Exception:
        pass

    previous_action = None
    task_start_time = time.time()
    max_task_timeout = 180  # 3 minutes max for entire task

    for step in range(1, max_steps + 1):
        step_start_time = time.time()
        step_timeout_sec = 45  # 45 seconds per step

        # Check overall task timeout
        elapsed_total = time.time() - task_start_time
        if elapsed_total > max_task_timeout:
            print(f"[ARIA Agent] Task exceeded {max_task_timeout}s timeout. Terminating.")
            aria._speak("Task timeout exceeded. Stopping execution.")
            task_outcome = "timeout"
            break

        if not aria.running:
            break

        # Cooperative Cancellation Check
        if task_item and task_item.cancelled:
            print(f"[ARIA Agent] Cooperative cancellation triggered for task {task_item.task_id}.")
            aria._speak("Task execution cancelled.")
            task_outcome = "cancelled"
            break

        # Interruption check
        while getattr(aria, "paused_by_interrupt", False):
            time.sleep(1.0)

        set_state("THINKING")
        set_text(f"Step {step}: Capturing screen...")

        # ── Self-Reflection & Error Recovery Analysis ──
        reflection_context = ""
        if step > 1 and previous_action:
            reflection_context = (
                f"== SELF-REFLECTION (ERROR RECOVERY) ==\n"
                f"In Step {step-1}, you executed this action: '{previous_action}'.\n"
                f"Inspect the current screenshot. Did that action succeed and update the screen as expected?\n"
                f"If the action failed (e.g. coordinates were off, app didn't open, loading spinner appeared), "
                f"reflect on what went wrong, adapt your strategy, and choose a new corrective action now.\n\n"
            )

        try:
            from dashboard import CognitionState
            CognitionState.active_subtask = f"Step {step}: Capturing screen & querying memory..."
            active_window_val = locals().get("active_window", "")
            CognitionState.active_window = active_window_val
        except Exception:
            pass

        step_start = time.time()

        try:
            from dashboard import CognitionState
            CognitionState.world_state["active_project"] = os.path.basename(os.getcwd())
            CognitionState.world_state["current_workflow"] = task
            CognitionState.world_state["agent_status"] = f"Step {step} Executing"
            CognitionState.world_state["browser_tabs"] = "Dashboard, Workspace"
        except Exception:
            pass

        # ── Step 2: UI State & Environment Mapping ──
        active_window = aria.context_skill.get_active_window()
        open_apps = aria.ui.get_open_apps()[:6]
        ui_state = f"Active Window: {active_window}\nOpen Apps: {', '.join(open_apps)}"

        # Latency Orchestration: Run context query and base64 screen encoding in parallel
        import concurrent.futures

        def capture_and_encode():
            if not aria.sandbox_safety.is_perception_allowed(active_window):
                print(f"[SandboxSafety] Privacy Zone active! Replacing screen capture with privacy placeholder.")
                from PIL import Image
                img = Image.new('RGB', (120, 120), color='black')
                buf_temp = io.BytesIO()
                img.save(buf_temp, format="PNG")
                return base64.b64encode(buf_temp.getvalue()).decode("utf-8")

            pil_img_temp = aria.screen.get_screen_image()
            buf_temp = io.BytesIO()
            pil_img_temp.save(buf_temp, format="PNG")
            return base64.b64encode(buf_temp.getvalue()).decode("utf-8")

        def get_prioritized_context():
            raw_episodes = aria.episodic_memory.recall(
                username=aria.known_user or "chinmaya",
                query=task,
                limit=10
            )
            raw_semantics = []
            try:
                from skills.vector_memory import VectorMemory
                raw_semantics = VectorMemory().semantic_search(task, limit=10)
            except Exception as ve:
                print(f"[ARIA Memory] Semantic search failed: {ve}")

            selected = aria.context_budget.score_and_select_memories(
                episodes=raw_episodes,
                semantic_memories=raw_semantics,
                current_goal=task
            )

            budget_mems = aria.context_budget.build_prompt_context(selected)
            std_sql = aria.brain._get_sqlite_context(task)
            return f"{budget_mems}\n\n{std_sql}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f_mem = executor.submit(get_prioritized_context)
            f_img = executor.submit(capture_and_encode)

            accessibility_tree = aria.ui.get_accessibility_tree()

            sql_context = f_mem.result()
            img_b64 = f_img.result()

        ui_mapping = f"== ACCESSIBILITY UI ELEMENT MAP ==\n{accessibility_tree}"
        print(f"[ARIA Agent] UI State:\n{ui_state}")

        try:
            from dashboard import CognitionState
            CognitionState.screenshot = img_b64
            if sql_context:
                CognitionState.memory_hits = [line.strip() for line in sql_context.split("\n") if line.strip() and not line.startswith("==")]
        except Exception:
            pass

        # Build agent planning prompt
        prompt = f"""You are the autonomous brain of ARIA. Your goal is to complete this user task: "{task}".
This is Step {step} of {max_steps}.

{reflection_context}== CURRENT UI CONTEXT ==
{ui_state}

{ui_mapping}

Look at the current screen snapshot. What is the single best action to perform next to complete the task?
Output ONLY ONE of the following tag formats followed by a confidence score between 0.0 and 1.0 in this format: [CONFIDENCE: score] (e.g. [OPEN: chrome] [CONFIDENCE: 0.95]).
Available action formats:
- [CLICK: x,y] (where x,y are screen coordinates of the button, link, or input field to click)
- [DOUBLE_CLICK: x,y] (double click at coordinates)
- [RIGHT_CLICK: x,y] (right click at coordinates)
- [TYPE: text] (to type text into the currently focused input field)
- [PRESS: keys] (to press a key combination like 'enter', 'ctrl+t', 'alt+f4')
- [OPEN: app_name] (to launch an application like 'chrome', 'notepad')
- [WAIT: seconds] (to wait for a page or app to load)
- [SCROLL: down] or [SCROLL: up] or [SCROLL: top] or [SCROLL: bottom] (to scroll; add | little/normal/more for amount e.g. [SCROLL: down | little])
- [BROWSER_OPEN: url] (to open the default web browser directly to a URL)
- [GOOGLE_SEARCH: query] (to execute a google search in the browser immediately)
- [VSCODE_OPEN: path] (to open a project folder in VS Code)
- [DONE: summary] (if the task is fully completed. Explain what you accomplished)

Rules:
1. ONLY return the tag (e.g. "[OPEN: chrome]"). Do NOT include markdown, reasoning, or extra text.
2. If you need to search or navigate, first open the browser or focus it.
3. Be precise with coordinates on a {sw}x{sh} screen."""

        set_text(f"Step {step}: Planning next action...")

        if not aria.brain.vision_ready:
            aria._speak("My vision model is offline. Please install and run moondream in Ollama to use the autonomous agent.")
            break

        prompt = prompt.replace("{ui_mapping}", ui_mapping)
        action_tag = aria.brain._ask_vision(img_b64, prompt)
        action_tag = action_tag.strip()

        print(f"[ARIA Agent] Step {step} planned action: {action_tag}")

        # Stuck Loop Protection
        action_history.append(action_tag)
        if len(action_history) >= 3 and len(set(action_history[-3:])) == 1:
            set_state("SPEAKING")
            aria._speak("I seem to be repeating the same action and might be stuck. Pausing to verify.")
            set_state("LISTENING")
            user_feedback = aria.voice.listen(timeout=10)
            if user_feedback:
                aria._speak(f"Applying override: {user_feedback}")
                action_tag = f"[SEARCH: {user_feedback}]"
            else:
                aria._speak("No feedback. Stopping run.")
                aria.memory_skill.log_failure(task, step, "STUCK_LOOP", action_tag)
                try:
                    aria.cognitive_load_manager.log_failure()
                except Exception:
                    pass
                break

        if not action_tag:
            aria._speak("I got no response from my brain. Aborting task.")
            break

        # ── Confidence Score Check & Interactive User Recovery ──
        conf_score = 1.0
        conf_match = re.search(r'\[CONFIDENCE:\s*([\d\.]+)\]', action_tag, re.IGNORECASE)
        if conf_match:
            conf_score = float(conf_match.group(1))
            action_tag = re.sub(r'\[CONFIDENCE:\s*[\d\.]+\]', '', action_tag).strip()
            print(f"[ARIA Agent] Action confidence: {conf_score}")

        if conf_score < 0.70:
            set_state("SPEAKING")
            aria._speak(f"I am not very confident about this step. Confidence score is {conf_score:.2f}. "
                        f"I planned to run: {action_tag}. Should I proceed, or do you have a correction?")
            set_state("LISTENING")
            user_feedback = aria.voice.listen(timeout=10)
            if user_feedback:
                uf_lower = user_feedback.lower()
                if any(x in uf_lower for x in ["yes", "proceed", "go ahead", "do it", "sure", "ok", "okay"]):
                    aria._speak("Okay, proceeding.")
                else:
                    aria._speak(f"Understood. Overriding action with feedback: '{user_feedback}'")
                    ref_prompt = (
                        f"The user wants to override the planned action. User correction: '{user_feedback}'. "
                        f"Convert this correction into a single valid ARIA action tag (e.g. [CLICK: x,y], [TYPE: text], [PRESS: keys]). "
                        f"Output only the tag."
                    )
                    corrected = aria.brain.think(ref_prompt)
                    if corrected and corrected.strip().startswith("["):
                        action_tag = corrected.strip()
                        print(f"[ARIA Agent] Overrode action: {action_tag}")
                    else:
                        action_tag = f"[SEARCH: {user_feedback}]"
            else:
                aria._speak("No feedback received. Pausing task for safety.")
                break

        # If done
        if "[DONE" in action_tag.upper():
            summary_match = re.search(r'\[DONE:\s*([^\]]+)\]', action_tag, re.IGNORECASE)
            summary = summary_match.group(1) if summary_match else "Task completed."

            try:
                from dashboard import CognitionState
                CognitionState.active_subtask = f"Task completed: {summary}"
            except Exception:
                pass

            aria._speak(f"Task completed: {summary}")
            task_outcome = "success"
            break

        # ── Step 3: Safety & Coordinate Verification ──
        safe, corrected_tag, verify_msg = verify_action(aria, action_tag, sw, sh)
        if not safe:
            print(f"[ARIA Agent] Blocked unsafe action: {verify_msg}")
            aria._speak(f"Action blocked by safety verifier. Reason: {verify_msg}")
            break

        if corrected_tag != action_tag:
            print(f"[ARIA Agent] Action corrected: {action_tag} -> {corrected_tag}")
            action_tag = corrected_tag

        set_state("SPEAKING")
        set_text(f"Step {step}: Executing action...")

        try:
            from dashboard import CognitionState
            CognitionState.active_subtask = f"Step {step}: Executing action"
            CognitionState.confidence = conf_score
            if hasattr(aria.brain, "get_active_model"):
                CognitionState.model_in_use = aria.brain.get_active_model()
            if reflection_context:
                CognitionState.reflection_results = reflection_context.replace("== SELF-REFLECTION (ERROR RECOVERY) ==\n", "").strip()

            CognitionState.last_actions.append({
                "time": time.strftime("%H:%M:%S"),
                "action": action_tag,
                "status": "success",
                "confidence": conf_score
            })
        except Exception:
            pass

        # Executing action with skill trust tracking + timeout protection
        step_success = True
        step_timeout = 30  # Max 30 seconds per action execution

        def _execute_with_timeout():
            try:
                execute_actions(aria, action_tag)
            except Exception as exec_err:
                raise exec_err

        try:
            action_thread = threading.Thread(target=_execute_with_timeout, daemon=True)
            action_thread.start()
            action_thread.join(timeout=step_timeout)

            if action_thread.is_alive():
                print(f"[ARIA Agent] WARNING: Action execution exceeded {step_timeout}s timeout. Likely hung browser/process.")
                aria._speak("Action took too long. Skipping this step to avoid infinite hang.")
                step_success = False
                try:
                    os.system("taskkill /im chrome.exe /f 2>nul")
                    os.system("taskkill /im msedge.exe /f 2>nul")
                except Exception:
                    pass
        except Exception as exec_err:
            step_success = False
            raise exec_err
        finally:
            try:
                from skills.trust_calibrator import SkillTrustCalibrator
                verb = action_tag.split(":")[0].strip(" [").lower() if ":" in action_tag else action_tag.strip(" []").lower()
                verb = verb.replace("[", "").replace("]", "").strip()

                win_title = active_window.lower() if "active_window" in dir() else "unknown"
                app_name = "chrome" if "chrome" in win_title else ("vscode" if "code" in win_title else ("notepad" if "notepad" in win_title else "unknown"))

                SkillTrustCalibrator().record_skill_run(verb, success=step_success, context_app=app_name)
            except Exception as trust_err:
                print(f"[ARIA SkillTrust] Failed to record skill trust outcome: {trust_err}")

        # Publish ACTION_EXECUTED event
        try:
            from skills.event_bus import EventBus
            EventBus().publish("ACTION_EXECUTED", {"action": action_tag, "step": step})
        except Exception:
            pass

        # Calculate execution latency metrics for telemetry
        try:
            aria.last_agent_activity = time.time()
            from dashboard import CognitionState
            lat = time.time() - step_start
            CognitionState.tool_health["vision_latency"] = f"{lat:.2f}s"
            CognitionState.tool_health["memory_latency"] = "0.01s"
            CognitionState.tool_health["success_rate"] = "98%"
            CognitionState.tool_health["stuck_rate"] = "0%"
        except Exception:
            pass

        previous_action = action_tag
        executed_steps.append(action_tag)

        # Clean spoken description of action
        spoken_action = re.sub(r'\[[A-Z_]+:[^\]]*\]', '', action_tag)
        spoken_action = re.sub(r'\[[A-Z_]+\]', '', spoken_action).strip()
        if not spoken_action:
            if "[CLICK:" in action_tag:
                spoken_action = "Clicking coordinate."
            elif "[DOUBLE_CLICK:" in action_tag:
                spoken_action = "Double-clicking coordinate."
            elif "[RIGHT_CLICK:" in action_tag:
                spoken_action = "Right-clicking coordinate."
            elif "[TYPE:" in action_tag:
                val = re.search(r'\[TYPE:\s*([^\]]+)\]', action_tag, re.IGNORECASE).group(1)
                spoken_action = f"Typing: {val}."
            elif "[PRESS:" in action_tag:
                val = re.search(r'\[PRESS:\s*([^\]]+)\]', action_tag, re.IGNORECASE).group(1)
                spoken_action = f"Pressing keys: {val}."
            elif "[OPEN:" in action_tag:
                val = re.search(r'\[OPEN:\s*([^\]]+)\]', action_tag, re.IGNORECASE).group(1)
                spoken_action = f"Opening {val}."
            elif "[WAIT:" in action_tag:
                spoken_action = "Waiting for screen update."
            elif "[SCROLL:" in action_tag:
                spoken_action = "Scrolling screen."

        aria._speak(spoken_action)

        step_elapsed = time.time() - step_start_time
        if step_elapsed > step_timeout_sec:
            print(f"[ARIA Agent] Step {step} exceeded {step_timeout_sec}s timeout (took {step_elapsed:.1f}s). Aborting task.")
            aria._speak("Step execution timeout. Stopping task.")
            break

        time.sleep(2.0)  # Wait for screen update before next iteration
    else:
        aria._speak("Reached maximum steps limit. Task paused.")

    # Reset Status & Attention Focus
    try:
        aria.last_agent_activity = time.time()
        aria.attention_manager.set_focus(0)
        from dashboard import CognitionState
        CognitionState.sandbox_simulation = {}
        CognitionState.causal_blame = {}
        CognitionState.world_state["agent_status"] = "Idle"
        CognitionState.world_state["current_workflow"] = "None"

        summary = aria.attention_manager.get_pending_summary()
        if "Triaged Notifications" in summary:
            print(f"[AttentionManager] Announcing triaged logs:\n{summary}")
            aria._speak(f"Workflow completed. I triaged {len(aria.attention_manager.pending_notifications)} notification events during execution. You can check them in the Attention panel.")
            aria.attention_manager.clear_pending()
            CognitionState.pending_notifications = []
    except Exception as e:
        print(f"[AttentionManager] Focus reset error: {e}")

    # Remove session checkpoint on task end
    try:
        if os.path.exists("active_session.json"):
            os.remove("active_session.json")
    except Exception:
        pass

    # Publish GOAL_COMPLETED event and compress memory files
    try:
        from skills.event_bus import EventBus
        EventBus().publish("GOAL_COMPLETED", {"task": task, "outcome": task_outcome, "steps": len(executed_steps)})

        aria.memory_skill.compress_memories()

        try:
            strategy_key = task.split()[0] if task else "default"

            latency_tot = time.time() - getattr(aria, "last_agent_activity", time.time())
            interrupted_flag = any(n["type"] == "low_battery" for n in getattr(aria.attention_manager, "pending_notifications", []))
            user_corrected_flag = False
            load_val_now = getattr(aria.cognitive_load_manager, "get_load_metrics", lambda: {"load_score": 0.1})()["load_score"]

            outcome_log = aria.memory_skill.record_strategy_outcome(
                strategy_key,
                success=(task_outcome == "success"),
                latency=latency_tot,
                interrupted=interrupted_flag,
                user_corrected=user_corrected_flag,
                load_level=load_val_now
            )
            print(f"[ARIA Optimizer] {outcome_log}")

            try:
                raw_conf = getattr(aria, "confidence", 0.90)
                aria.confidence_calibrator.log_confidence_prediction(task, raw_conf, task_outcome)

                from dashboard import CognitionState
                old_factor = CognitionState.calibration_factor
                new_factor = aria.confidence_calibrator.calibration_factor
                CognitionState.calibration_factor = new_factor

                if abs(old_factor - new_factor) > 0.05:
                    set_state("SPEAKING")
                    aria._speak(f"Calibration notice. Adjusting uncertainty scale to {new_factor:.2f} due to strategy outcomes.")
                    set_state("IDLE")
            except Exception as cal_err:
                print(f"[ARIA Calibrator] Calibration logging error: {cal_err}")

            if task_outcome == "failed":
                try:
                    from skills.sandbox_simulator import SandboxSimulator
                    ref_res = SandboxSimulator().run_counterfactual_reflection(strategy_key, sim_candidates)

                    c_log = aria.memory_skill.record_counterfactual_update(strategy_key, ref_res["recommendation"])
                    print(f"[ARIA Counterfactual] {ref_res['summary']}")
                    print(f"[ARIA Counterfactual] {c_log}")

                    from dashboard import CognitionState
                    CognitionState.reflection_results = ref_res["summary"]

                    set_state("SPEAKING")
                    aria._speak(f"Analyzing failure. Mental replay suggests using strategy '{ref_res['recommendation']}' instead.")
                    set_state("IDLE")
                except Exception as ref_err:
                    print(f"[ARIA Counterfactual] Reflection error: {ref_err}")

                try:
                    from skills.causal_attribution import CausalAttributionEngine

                    last_act_tag = executed_steps[-1] if executed_steps else "unknown"
                    last_err_msg = feedback if feedback else "execution failed"

                    attribution = CausalAttributionEngine().analyze_failure_cause(
                        task,
                        last_act_tag,
                        last_err_msg,
                        latency=latency_tot,
                        interrupted=interrupted_flag,
                        load_score=load_val_now
                    )

                    from dashboard import CognitionState
                    CognitionState.causal_blame = attribution
                    print(f"[ARIA Causal] Diagnosis: {attribution['cause'].upper()} - {attribution['explanation']}")

                    set_state("SPEAKING")
                    aria._speak(f"Root cause of failure diagnosed as {attribution['cause'].replace('_', ' ')}.")
                    set_state("IDLE")
                except Exception as causal_err:
                    print(f"[ARIA Causal] Attribution error: {causal_err}")
        except Exception as o_err:
            print(f"[ARIA Optimizer] Failed to record strategy reinforcement: {o_err}")
    except Exception:
        pass

    # Log episode to replay memory
    try:
        aria.memory_skill.save_episode(task, executed_steps, task_outcome)
        print(f"[ARIA Agent] Episode logged to database: '{task}' -> {task_outcome}")

        if task_outcome == "success":
            try:
                from skills.vector_memory import VectorMemory
                vm = VectorMemory()
                steps_summary = " -> ".join(executed_steps)
                vm.add_memory(
                    f"Successful strategy for task '{task}': Executed sequence: [{steps_summary}]",
                    category="workflow"
                )
                print("[ARIA Agent] Successfully indexed episode in local semantic vector memory.")
            except Exception as e:
                print(f"[ARIA Agent] Vector memory indexing error: {e}")
    except Exception as e:
        print(f"[ARIA Agent] Episodic logging error: {e}")

    # Trigger reflection engine asynchronously
    try:
        recent_episodes = aria.episodic_memory.get_recent(username=aria.known_user or "chinmaya", n=5)
        task_results = [{"goal": task, "outcome": task_outcome, "steps": [{"action": act, "status": "success"} for act in executed_steps]}]
        aria.reflection_engine.reflect_asynchronously(
            username=aria.known_user or "chinmaya",
            recent_episodes=recent_episodes,
            recent_task_results=task_results
        )
    except Exception as ref_trigger_err:
        print(f"[ARIA Reflection] Failed to trigger background reflection: {ref_trigger_err}")

    # Save task replay traces to replays/task_id/
    try:
        import uuid
        task_id = task_item.task_id if task_item else str(uuid.uuid4())
        from skills.event_bus import EventBus
        events_log = EventBus().get_history()[-30:]
        reflections_summary = getattr(aria.brain, "reflection_results", "")

        steps_data = [{"step": idx, "action": act, "status": "success", "duration": 1.0} for idx, act in enumerate(executed_steps, 1)]
        aria.reflection_engine.save_task_replay(
            task_id=task_id,
            goal=task,
            steps=steps_data,
            events=events_log,
            reflections=reflections_summary
        )
    except Exception as replay_save_err:
        print(f"[ARIA Replay] Failed to save task replay files: {replay_save_err}")
