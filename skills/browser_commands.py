"""
skills/browser_commands.py — Extracted browser execution logic for ARIA
========================================================================
Implements direct UI control, scroll, and Playwright actions without circular main.py imports.
"""
import re
import time
import threading

def handle_direct_ui_control(aria, inp, user_input):
    from skills.command_patterns import UI_SWITCH_TO_WORDS
    if any(x in inp for x in UI_SWITCH_TO_WORDS):
        app = inp
        for t in UI_SWITCH_TO_WORDS:
            app = app.replace(t, "").strip()
        ok, msg = aria.ui.focus_window(app)
        aria._speak(f"Switched to {app}." if ok else f"Couldn't find {app} open.")
        return "focused_app_" + app

    if "new tab" in inp:
        aria.ui.browser_new_tab()
        aria._speak("Opened a new tab.")
        return "opened_new_tab"

    if any(x in inp for x in ["close tab", "close the tab", "bar tab", "delete tab", "remove tab"]):
        aria.ui.browser_close_tab()
        aria._speak("Closed the tab.")
        return "closed_tab"
    if any(x in inp for x in ["close window", "close the window", "close chrome", "close browser", "close cross", "cross button", "press cross"]):
        aria.screen.press("alt", "f4")
        aria._speak("Closed the window.")
        return "closed_window"
    if any(x in inp for x in ["refresh page", "reload page", "refresh browser"]):
        aria.ui.browser_refresh()
        aria._speak("Refreshed.")
        return "refreshed_page"
    if "go back" in inp:
        aria.ui.browser_back()
        aria._speak("Going back.")
        return "navigated_back"
    if "go forward" in inp:
        aria.ui.browser_forward()
        aria._speak("Going forward.")
        return "navigated_forward"

    if "go to" in inp and any(b in inp for b in ["chrome", "edge", "firefox", "browser"]):
        url = re.sub(r'go to|in chrome|in edge|in browser|in firefox', '', inp).strip()
        if url and not url.startswith("http"):
            url = "https://" + url
        if url:
            ok, msg = aria.ui.browser_go_to(url)
            aria._speak(f"Going to {url}.")
            return "navigated_to_url_" + url

    if any(x in inp for x in ["what apps are open", "what is open", "list open apps", "show open apps"]):
        apps = aria.ui.get_open_apps()[:6]
        if apps:
            aria._speak(f"I can see these open: {', '.join(apps[:5])}.")
        else:
            aria._speak("I couldn't detect any open windows.")
        return "listed_open_apps"

    return "no_matching_direct_ui_action"


def handle_scroll_command(aria, inp, user_input):
    if "scroll to top" in inp or "scroll to the top" in inp:
        try:
            from skills.browser_skill import BrowserSkill
            bs = BrowserSkill()
            if aria.automation_mode and bs.is_browser_active():
                aria.last_automation_action_time = time.time()
                aria._speak("Scrolling to top.")
                aria._speak(bs.scroll("top"))
                return "scrolled_to_top_playwright"
        except Exception as e:
            print(f"[Main] Browser scroll fallback failed: {e}")
        aria.screen.press("ctrl+home")
        aria._speak("Scrolling to top.")
        return "scrolled_to_top_fallback"

    if "scroll to bottom" in inp or "scroll to the bottom" in inp:
        try:
            from skills.browser_skill import BrowserSkill
            bs = BrowserSkill()
            if aria.automation_mode and bs.is_browser_active():
                aria.last_automation_action_time = time.time()
                aria._speak("Scrolling to bottom.")
                aria._speak(bs.scroll("bottom"))
                return "scrolled_to_bottom_playwright"
        except Exception as e:
            print(f"[Main] Browser scroll fallback failed: {e}")
        aria.screen.press("ctrl+end")
        aria._speak("Scrolling to bottom.")
        return "scrolled_to_bottom_fallback"

    if "scroll down a little" in inp or "scroll a little down" in inp or "scroll a little" in inp:
        try:
            from skills.browser_skill import BrowserSkill
            bs = BrowserSkill()
            if aria.automation_mode and bs.is_browser_active():
                aria.last_automation_action_time = time.time()
                aria._speak("Scrolling down a little.")
                aria._speak(bs.scroll("down", "little"))
                return "scrolled_down_little_playwright"
        except Exception as e:
            print(f"[Main] Browser scroll fallback failed: {e}")
        aria.screen.scroll(2, "down")
        aria._speak("Scrolling down a little.")
        return "scrolled_down_little_fallback"

    if "scroll up a little" in inp or "scroll a little up" in inp:
        try:
            from skills.browser_skill import BrowserSkill
            bs = BrowserSkill()
            if aria.automation_mode and bs.is_browser_active():
                aria.last_automation_action_time = time.time()
                aria._speak("Scrolling up a little.")
                aria._speak(bs.scroll("up", "little"))
                return "scrolled_up_little_playwright"
        except Exception as e:
            print(f"[Main] Browser scroll fallback failed: {e}")
        aria.screen.scroll(2, "up")
        aria._speak("Scrolling up a little.")
        return "scrolled_up_little_fallback"

    if "scroll down more" in inp or "scroll more down" in inp or "scroll more" in inp:
        try:
            from skills.browser_skill import BrowserSkill
            bs = BrowserSkill()
            if aria.automation_mode and bs.is_browser_active():
                aria.last_automation_action_time = time.time()
                aria._speak("Scrolling down more.")
                aria._speak(bs.scroll("down", "more"))
                return "scrolled_down_more_playwright"
        except Exception as e:
            print(f"[Main] Browser scroll fallback failed: {e}")
        aria.screen.scroll(10, "down")
        aria._speak("Scrolling down more.")
        return "scrolled_down_more_fallback"

    if "scroll up more" in inp or "scroll more up" in inp:
        try:
            from skills.browser_skill import BrowserSkill
            bs = BrowserSkill()
            if aria.automation_mode and bs.is_browser_active():
                aria.last_automation_action_time = time.time()
                aria._speak("Scrolling up more.")
                aria._speak(bs.scroll("up", "more"))
                return "scrolled_up_more_playwright"
        except Exception as e:
            print(f"[Main] Browser scroll fallback failed: {e}")
        aria.screen.scroll(10, "up")
        aria._speak("Scrolling up more.")
        return "scrolled_up_more_fallback"

    if "scroll down" in inp or "page down" in inp:
        try:
            from skills.browser_skill import BrowserSkill
            bs = BrowserSkill()
            if aria.automation_mode and bs.is_browser_active():
                aria.last_automation_action_time = time.time()
                aria._speak("Scrolling down.")
                aria._speak(bs.scroll("down"))
                return "scrolled_down_page_playwright"
        except Exception as e:
            print(f"[Main] Browser scroll fallback failed: {e}")
        aria.screen.scroll(5, "down")
        aria._speak("Scrolling down.")
        return "scrolled_down_page_fallback"

    if "scroll up" in inp or "page up" in inp:
        try:
            from skills.browser_skill import BrowserSkill
            bs = BrowserSkill()
            if aria.automation_mode and bs.is_browser_active():
                aria.last_automation_action_time = time.time()
                aria._speak("Scrolling up.")
                aria._speak(bs.scroll("up"))
                return "scrolled_up_page_playwright"
        except Exception as e:
            print(f"[Main] Browser scroll fallback failed: {e}")
        aria.screen.scroll(5, "up")
        aria._speak("Scrolling up.")
        return "scrolled_up_page_fallback"

    return "no_matching_scroll_action"


def handle_playwright_browser_actions(aria, inp, user_input):
    from skills.command_patterns import (
        PLAYWRIGHT_PLAN_WORDS, PLAYWRIGHT_CLOSE_WORDS, PLAYWRIGHT_OPEN_WORDS, PLAYWRIGHT_SUMMARIZE_WORDS,
        PLAYWRIGHT_FIRST_RESULT_WORDS, PLAYWRIGHT_ADD_CART_WORDS, PRODUCT_CHEAPEST_WORDS
    )
    
    if any(x in inp for x in PRODUCT_CHEAPEST_WORDS) and any(x in inp for x in ["page", "this", "keyboard", "product"]):
        try:
            from skills.browser_skill import BrowserSkill
            bs = BrowserSkill()
            if bs.is_browser_active():
                aria.automation_mode = True
                aria.last_automation_action_time = time.time()
                aria._speak(bs.cheapest_visible_item())
                return "checked_cheapest_product"
        except Exception as e:
            print(f"[Main] Cheapest visible item check failed: {e}")
            
    agent_trigger_found = None
    for t in PLAYWRIGHT_PLAN_WORDS:
        if inp.startswith(t):
            agent_trigger_found = t
            break
            
    has_complex_keyword = any(w in inp.split() for w in ["and", "under"]) or "summarize" in inp
    is_complex = ("amazon" in inp or "youtube" in inp or "wikipedia" in inp or "google" in inp) and has_complex_keyword

    if agent_trigger_found or is_complex:
        goal = inp
        if agent_trigger_found:
            goal = inp.replace(agent_trigger_found, "", 1).strip()
        
        from skills.agent_planner import AgentPlanner
        def run_agent_async():
            planner = AgentPlanner(aria.brain)
            result_msg = planner.run_task(goal, speak_callback=aria._speak)
            aria._speak(result_msg)
            
        threading.Thread(target=run_agent_async, daemon=True).start()
        aria._mark_conversation_activity(wake_reason="active_task")
        return "launched_agent_for_" + goal

    if any(x in inp for x in PLAYWRIGHT_CLOSE_WORDS):
        aria.automation_mode = False
        from skills.browser_skill import BrowserSkill
        res = BrowserSkill().close_browser()
        aria._speak(res)
        return "closed_browser"

    if any(x in inp for x in PLAYWRIGHT_OPEN_WORDS):
        aria.automation_mode = True
        aria.last_automation_action_time = time.time()
        aria._speak("Opening browser.")
        from skills.browser_skill import BrowserSkill
        success, msg = BrowserSkill().start_browser()
        aria._speak(msg)
        return "opened_browser"

    if inp.startswith("go to ") or inp.startswith("navigate to "):
        aria.automation_mode = True
        aria.last_automation_action_time = time.time()
        url = inp.replace("go to ", "").replace("navigate to ", "").strip()
        aria._speak(f"Navigating to {url}.")
        from skills.browser_skill import BrowserSkill
        res = BrowserSkill().navigate(url)
        aria._speak(res)
        return "navigated_to_" + url

    if "search amazon for " in inp or "amazon search " in inp:
        aria.automation_mode = True
        aria.last_automation_action_time = time.time()
        product = inp.replace("search amazon for ", "").replace("amazon search ", "").strip()
        aria._speak(f"Searching Amazon for {product}.")
        from skills.browser_skill import BrowserSkill
        res = BrowserSkill().search_amazon(product)
        aria._speak(res)
        return "searched_amazon_for_" + product
        
    if "search youtube for " in inp or "youtube search " in inp:
        aria.automation_mode = True
        aria.last_automation_action_time = time.time()
        query = inp.replace("search youtube for ", "").replace("youtube search ", "").strip()
        aria._speak(f"Searching YouTube for {query}.")
        from skills.browser_skill import BrowserSkill
        res = BrowserSkill().search_youtube(query)
        aria._speak(res)
        return "searched_youtube_for_" + query

    if any(x in inp for x in PLAYWRIGHT_FIRST_RESULT_WORDS):
        from skills.browser_skill import BrowserSkill
        bs = BrowserSkill()
        if bs.is_browser_active():
            bs._update_page_state()
            cards = bs.page_state.get("cards", [])
            if cards:
                matched_card, score = aria.brain._find_best_card_match(user_input, cards)
                if matched_card and score >= 0.5:
                    aria.automation_mode = True
                    aria.last_automation_action_time = time.time()
                    title = matched_card.get("text", "").split("\n")[0].strip()[:60]
                    aria._speak(f"Clicking {title}.")
                    res = bs.click_element(matched_card.get("aria_id"))
                    print(f"[Main/BrowserIntercept] Clicked matched card {matched_card.get('aria_id')} (score: {score:.2f}) instead of default first result. Result: {res}")
                    return "clicked_matched_card_" + matched_card.get("aria_id")
        aria.automation_mode = True
        aria.last_automation_action_time = time.time()
        aria._speak("Clicking the first result.")
        res = bs.click_first_result()
        aria._speak(res)
        return "clicked_first_result"

    if any(x in inp for x in PLAYWRIGHT_ADD_CART_WORDS):
        aria.automation_mode = True
        aria.last_automation_action_time = time.time()
        aria._speak("Adding to cart.")
        from skills.browser_skill import BrowserSkill
        res = BrowserSkill().click_add_to_cart()
        aria._speak(res)
        return "added_to_cart"

    if "fill " in inp and " with " in inp:
        aria.automation_mode = True
        aria.last_automation_action_time = time.time()
        parts = inp.replace("fill ", "", 1).split(" with ", 1)
        field = parts[0].strip()
        value = parts[1].strip()
        aria._speak(f"Typing {value} in {field}.")
        from skills.browser_skill import BrowserSkill
        res = BrowserSkill().fill_element(field, value)
        aria._speak(res)
        return f"filled_field_{field}_with_{value}"

    if "type " in inp and " in " in inp:
        aria.automation_mode = True
        aria.last_automation_action_time = time.time()
        parts = inp.replace("type ", "", 1).split(" in ", 1)
        value = parts[0].strip()
        field = parts[1].strip()
        aria._speak(f"Typing {value} in {field}.")
        from skills.browser_skill import BrowserSkill
        res = BrowserSkill().fill_element(field, value)
        aria._speak(res)
        return f"typed_{value}_in_field_{field}"

    if "enter " in inp and " in " in inp:
        aria.automation_mode = True
        aria.last_automation_action_time = time.time()
        parts = inp.replace("enter ", "", 1).split(" in ", 1)
        value = parts[0].strip()
        field = parts[1].strip()
        aria._speak(f"Typing {value} in {field}.")
        from skills.browser_skill import BrowserSkill
        res = BrowserSkill().fill_element(field, value)
        aria._speak(res)
        return f"entered_{value}_in_field_{field}"

    if any(x in inp for x in PLAYWRIGHT_SUMMARIZE_WORDS):
        if aria.automation_mode:
            aria.last_automation_action_time = time.time()
        from skills.browser_skill import BrowserSkill
        res = BrowserSkill().summarize_page(aria.brain)
        aria._speak(res)
        return "summarized_page"

    return "no_matching_playwright_action"
