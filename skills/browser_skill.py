import os
import time
import threading
import urllib.parse
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

# false = headed (watch browser) for daily use, true = headless for testing/CI
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"

class BrowserSkill:
    """Manages headed Playwright browser control with automatic headless fallback and recovery."""
    _thread_local = threading.local()
    _instances_lock = threading.Lock()
    _active_instances = []

    def __new__(cls, *args, **kwargs):
        if not hasattr(cls._thread_local, "instance"):
            instance = super(BrowserSkill, cls).__new__(cls)
            instance.playwright = None
            instance.browser = None
            instance.context = None
            instance.page = None
            instance.page_state = {}
            instance.action_history = []
            instance._initialized = True
            cls._thread_local.instance = instance
            with cls._instances_lock:
                cls._active_instances.append(instance)
        return cls._thread_local.instance

    def __init__(self):
        pass

    def start_browser(self, headless: bool = BROWSER_HEADLESS):
        """
        Starts browser in headed mode by default.
        Auto-falls back to headless if headed launch fails.
        """
        if self.playwright is None:
            try:
                self.playwright = sync_playwright().start()
            except Exception as e:
                print(f"[BrowserSkill] Playwright initialization failed: {e}")
                return False, f"Playwright failed: {e}"

        try:
            print(f"[BrowserSkill] Launching {'headless' if headless else 'headed'} browser...")
            self.browser = self.playwright.chromium.launch(
                headless=headless,
                args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
            )
            # Create a context with viewport maximized
            self.context = self.browser.new_context(no_viewport=True)
            self.page = self.context.new_page()
            print(f"[BrowserSkill] Browser started successfully.")
            return True, "Opened browser."

        except Exception as e:
            print(f"[BrowserSkill] Launch failed: {e}")
            if not headless:
                print("[BrowserSkill] Falling back to headless mode...")
                try:
                    self.browser = self.playwright.chromium.launch(
                        headless=True,
                        args=["--disable-blink-features=AutomationControlled"]
                    )
                    self.context = self.browser.new_context()
                    self.page = self.context.new_page()
                    print("[BrowserSkill] Headless fallback successful.")
                    return True, "Opened browser in headless fallback."
                except Exception as e2:
                    print(f"[BrowserSkill] Headless fallback also failed: {e2}")
                    self.close_browser()
                    return False, f"Failed to start browser: {e2}"
            else:
                self.close_browser()
                return False, f"Failed to start browser: {e}"

    def _ensure_browser(self):
        """
        Auto-recovery: restart browser if dead.
        Call this before every page action.
        """
        if self.browser is None:
            print("[BrowserSkill] Browser not running — starting...")
            self.start_browser()
            return

        try:
            if self.page is None or self.page.is_closed():
                print("[BrowserSkill] Page closed — recreating...")
                self.page = self.context.new_page()
            else:
                self._update_page_state()
        except Exception:
            print("[BrowserSkill] Context dead — full browser restart...")
            self.close_browser()
            self.start_browser()

        # Print browser action debug context
        if self.is_browser_active():
            print(f"[BrowserSkill DEBUG] Browser Active: True")
            if self.page_state:
                print(f"[BrowserSkill DEBUG] Current URL: {self.page_state.get('url', 'unknown')}")
                print(f"[BrowserSkill DEBUG] DOM Inputs: {len(self.page_state.get('inputs', []))}")
                print(f"[BrowserSkill DEBUG] DOM Buttons: {len(self.page_state.get('buttons', []))}")
                print(f"[BrowserSkill DEBUG] DOM Links: {len(self.page_state.get('links', []))}")
                print(f"[BrowserSkill DEBUG] DOM Cards: {len(self.page_state.get('cards', []))}")
                print(f"[BrowserSkill DEBUG] Using: DOM mode")
            else:
                print(f"[BrowserSkill DEBUG] Using: Screen vision fallback (stale DOM)")
        else:
            print(f"[BrowserSkill DEBUG] Browser Active: False")

    def is_browser_active(self):
        """Checks if the browser, context, and page are initialized and not closed."""
        try:
            return (self.browser is not None and 
                    self.context is not None and 
                    self.page is not None and 
                    not self.page.is_closed())
        except Exception:
            return False

    def navigate(self, url):
        """Navigate current tab to specified URL with auto-recovery."""
        self._ensure_browser()

        if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("file:///"):
            url = "https://" + url

        try:
            print(f"[BrowserSkill] Navigating to {url}...")
            self.page.goto(url, wait_until="load", timeout=20000)
            
            # Navigation readiness validation
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=10000)
                self.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
                
            # Stabilization wait
            if "amazon" in url.lower():
                try:
                    self.page.wait_for_selector("input", timeout=5000)
                except Exception:
                    pass
                time.sleep(3.0)  # 3-second stabilization wait for Amazon
            else:
                time.sleep(1.5)  # 1.5-second general stabilization wait
                
            self._update_page_state()
            self.record_action("navigate", url, success=True)
            return f"Navigated to {url}."
        except Exception as e:
            print(f"[BrowserSkill] Navigation failed: {e} — retrying after recovery...")
            self._ensure_browser()
            try:
                self.page.goto(url, wait_until="load", timeout=20000)
                try:
                    self.page.wait_for_load_state("domcontentloaded", timeout=10000)
                    self.page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                if "amazon" in url.lower():
                    try:
                        self.page.wait_for_selector("input", timeout=5000)
                    except Exception:
                        pass
                    time.sleep(3.0)
                else:
                    time.sleep(1.5)
                self._update_page_state()
                self.record_action("navigate", url, success=True)
                return f"Navigated to {url}."
            except Exception as e2:
                self.record_action("navigate", url, success=False)
                return f"Navigation failed: {e2}"

    def close_browser(self):
        """Closes browser and resets references across all threads cleanly."""
        # 1. First, attempt a normal clean shutdown of the current thread's browser
        try:
            if self.page and not self.page.is_closed():
                self.page.close()
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except Exception as e:
            print(f"[BrowserSkill] Normal close error: {e}")
        finally:
            self.browser = None
            self.page = None
            self.context = None
            self.playwright = None
            with self._instances_lock:
                if self in self._active_instances:
                    self._active_instances.remove(self)

        # 2. To avoid EPIPE / zombie processes when closed from a different thread (e.g., shutdown thread),
        # force terminate the Playwright driver process for any other active thread-local instances.
        with self._instances_lock:
            remaining = list(self._active_instances)
        
        for inst in remaining:
            try:
                if inst.playwright and hasattr(inst.playwright, "_impl_obj"):
                    impl = inst.playwright._impl_obj
                    if hasattr(impl, "_connection"):
                        conn = impl._connection
                        if hasattr(conn, "_transport"):
                            trans = conn._transport
                            if hasattr(trans, "_proc") and trans._proc:
                                print(f"[BrowserSkill] Shutting down Playwright driver process (PID: {trans._proc.pid}) from cleanup thread...")
                                trans._proc.kill()
            except Exception as e:
                print(f"[BrowserSkill] Thread-cross driver kill failed: {e}")
            finally:
                inst.browser = None
                inst.page = None
                inst.context = None
                inst.playwright = None
                with self._instances_lock:
                    if inst in self._active_instances:
                        self._active_instances.remove(inst)
                        
        return "Closed browser."

    def search_google(self, query):
        """Navigate to Google Search for query with automatic DuckDuckGo fallback and context reset if blocked."""
        self._ensure_browser()
        try:
            print(f"[BrowserSkill] Searching Google for '{query}'...")
            encoded = urllib.parse.quote(query)
            url = f"https://www.google.com/search?q={encoded}"
            res_msg = self.navigate(url)
            
            # Check for Google security/bot block sorry page
            if self.page and "sorry/index" in self.page.url:
                print("[BrowserSkill] Google block page detected! Resetting session context and falling back to DuckDuckGo...")
                try:
                    self.context.close()
                except Exception:
                    pass
                self.context = self.browser.new_context(no_viewport=True)
                self.page = self.context.new_page()
                
                # Fallback to DuckDuckGo
                ddg_url = f"https://duckduckgo.com/?q={encoded}"
                print(f"[BrowserSkill] Falling back to DuckDuckGo search: {ddg_url}")
                res_msg = self.navigate(ddg_url)
                if "failed" in res_msg.lower():
                    print(f"[BrowserSkill] DuckDuckGo fallback search failed: {res_msg}")
                    return False, f"Google search blocked, and DuckDuckGo fallback failed: {res_msg}"
                print("[BrowserSkill] DuckDuckGo fallback search loaded successfully.")
                return True, f"Google blocked request; successfully searched DuckDuckGo for '{query}'."

            if "failed" in res_msg.lower():
                print(f"[BrowserSkill] Google search failed: {res_msg}")
                return False, f"Google search failed: {res_msg}"
            print(f"[BrowserSkill] Google search loaded successfully.")
            return True, f"Searched Google for '{query}'."
        except Exception as e:
            print(f"[BrowserSkill] Google search failed: {e}")
            return False, f"Google search failed: {e}"

    def search_amazon(self, product_name):
        """Navigate to Amazon (if not already there) and search for product."""
        self._ensure_browser()
        print(f"[BrowserSkill] Searching Amazon for '{product_name}'...")

        try:
            current_url = self.page.url
            if "amazon" not in current_url:
                self.navigate("https://www.amazon.in")
            else:
                try:
                    self.page.wait_for_load_state("domcontentloaded", timeout=5000)
                    self.page.wait_for_selector("input", timeout=5000)
                except Exception:
                    pass

            search_selectors = ["input#twotabsearchtextbox", "input[name='field-keywords']", "input.nav-input"]
            search_input = None
            for sel in search_selectors:
                try:
                    self.page.wait_for_selector(sel, state="visible", timeout=3000)
                    search_input = self.page.locator(sel)
                    break
                except Exception:
                    continue

            if not search_input:
                print("[BrowserSkill] Amazon search box not found.")
                return "I can't see the Amazon page fully loaded yet."

            search_input.fill(product_name)
            
            submit_selectors = ["input#nav-search-submit-button", "input[type='submit']", ".nav-search-submit"]
            submit_button = None
            for sel in submit_selectors:
                try:
                    self.page.wait_for_selector(sel, state="visible", timeout=2000)
                    submit_button = self.page.locator(sel)
                    break
                except Exception:
                    continue

            if submit_button:
                submit_button.click()
            else:
                self.page.keyboard.press("Enter")

            try:
                self.page.wait_for_load_state("load", timeout=10000)
            except Exception:
                pass
            print(f"[BrowserSkill] Amazon search submitted successfully for '{product_name}'.")
            self._update_page_state()
            self.record_action("search_amazon", product_name, success=True)
            return f"Searching Amazon for '{product_name}'."
        except Exception as e:
            print(f"[BrowserSkill] Amazon search failed: {e}")
            return f"Amazon search failed: {e}"

    def search_youtube(self, query):
        """Navigate to YouTube and search for video query."""
        self._ensure_browser()
        print(f"[BrowserSkill] Searching YouTube for '{query}'...")

        try:
            current_url = self.page.url
            if "youtube.com" not in current_url:
                self.navigate("https://www.youtube.com")

            search_input = self.page.locator("input#search")
            if not search_input.is_visible(timeout=5000):
                search_input = self.page.locator("input[name='search_query']")

            search_input.fill(query)
            
            search_button = self.page.locator("button#search-icon-legacy")
            if search_button.is_visible(timeout=2000):
                search_button.click()
            else:
                self.page.keyboard.press("Enter")

            print(f"[BrowserSkill] YouTube search submitted successfully for '{query}'.")
            self._update_page_state()
            self.record_action("search_youtube", query, success=True)
            return f"Searching YouTube for '{query}'."
        except Exception as e:
            print(f"[BrowserSkill] YouTube search failed: {e}")
            return f"YouTube search failed: {e}"

    def search_in_page(self, query):
        """Generic in-page search. Finds a visible search input on the active page, fills it, and submits."""
        self._ensure_browser()
        print(f"[BrowserSkill] Searching in-page for '{query}'...")
        
        # 1. Update page state to get fresh inputs
        self._update_page_state()
        
        # 2. Try to find a search input from inputs list
        search_input = None
        
        # Look for input elements that are visible in the viewport first
        visible_inputs = [inp for inp in self.page_state.get("inputs", []) if inp.get("is_visible_in_viewport")]
        if not visible_inputs:
            visible_inputs = self.page_state.get("inputs", [])
            
        # Prioritize inputs with search-related placeholders or aria-labels
        for inp in visible_inputs:
            text = (inp.get("text") or "").lower()
            placeholder = (inp.get("placeholder") or "").lower()
            role = (inp.get("role") or "").lower()
            if "search" in text or "search" in placeholder or "search" in role:
                search_input = inp
                break
                
        # If not found, look for any text input that might be a search input
        if not search_input and visible_inputs:
            for inp in visible_inputs:
                role = (inp.get("role") or "").lower()
                if role in ["text", "search"]:
                    search_input = inp
                    break
            if not search_input:
                search_input = visible_inputs[0] # Fallback to the first input
                
        if search_input:
            aria_id = search_input.get("aria_id")
            print(f"[BrowserSkill] Found potential search input: {aria_id}")
            fill_res = self.fill_element(aria_id, query)
            if "Error" not in fill_res:
                self.page.keyboard.press("Enter")
                # Wait for navigation/results
                try:
                    self.page.wait_for_load_state("load", timeout=5000)
                except Exception:
                    pass
                self._update_page_state()
                self.record_action("search_in_page", query, success=True)
                return f"Searched in-page for '{query}'."
                
        # Fallback to selectors if DOM Memory didn't find it
        search_selectors = [
            "input[type='search']",
            "input[name='q']",
            "input[name='query']",
            "input[placeholder*='search' i]",
            "input[placeholder*='Search' i]",
            "input.nav-input",
            "input[type='text']"
        ]
        for sel in search_selectors:
            try:
                loc = self.page.locator(sel).first
                if loc.is_visible(timeout=1000):
                    loc.fill(query)
                    self.page.keyboard.press("Enter")
                    try:
                        self.page.wait_for_load_state("load", timeout=5000)
                    except Exception:
                        pass
                    self._update_page_state()
                    self.record_action("search_in_page", query, success=True)
                    return f"Searched in-page for '{query}' using selector '{sel}'."
            except Exception:
                continue
                
        return "Could not find a valid search input on the active page."

    def click_first_result(self):
        """Detect current domain and click the first search result."""
        self._ensure_browser()
        print("[BrowserSkill] Clicking first result on screen...")

        current_url = self.page.url.lower()
        try:
            if "amazon" in current_url:
                # Find organic search items and skip sponsored
                items_locator = self.page.locator(".s-result-item[data-component-type='s-search-result']")
                count = items_locator.count()
                print(f"[BrowserSkill] Found {count} search result items on Amazon.")
                for i in range(count):
                    item = items_locator.nth(i)
                    try:
                        inner_text = item.inner_text().lower()
                        # Skip if it contains sponsored label/text
                        if "sponsored" in inner_text or "ad" in inner_text.split():
                            print(f"[BrowserSkill] Skipping sponsored item {i}")
                            continue

                        link_selectors = [
                            "h2 a.a-link-normal",
                            "[data-component-type='s-product-image'] a",
                            "a.a-link-normal"
                        ]
                        for sel in link_selectors:
                            link_loc = item.locator(sel).first
                            if link_loc.is_visible(timeout=1000):
                                href = link_loc.get_attribute("href")
                                if href:
                                    if "slredirect" in href or "/gp/slredirect/" in href:
                                        continue
                                    if href.startswith("/"):
                                        base = "https://www.amazon.in" if "amazon.in" in current_url else "https://www.amazon.com"
                                        href = base + href
                                    print(f"[BrowserSkill] Navigating to organic Amazon product link: {href}")
                                    self.page.goto(href)
                                else:
                                    print(f"[BrowserSkill] Clicking organic Amazon product element")
                                    link_loc.click()
                                self.record_action("click_first_result", "Amazon organic", success=True)
                                return "Clicked first product result."
                    except Exception as item_err:
                        print(f"[BrowserSkill] Error checking organic item {i}: {item_err}")
                        continue

                # Fallback to general list of selectors
                selectors = [
                    "h2 a.a-link-normal",
                    "[data-component-type='s-product-image'] a",
                    ".s-result-item h2 a"
                ]
                for sel in selectors:
                    locators = self.page.locator(sel)
                    for idx in range(locators.count()):
                        locator = locators.nth(idx)
                        if locator.is_visible(timeout=1000):
                            href = locator.get_attribute("href")
                            if href and ("slredirect" in href or "/gp/slredirect/" in href):
                                print(f"[BrowserSkill] Skipping sponsored product link redirect: {href}")
                                continue
                            if href:
                                if href.startswith("/"):
                                    base = "https://www.amazon.in" if "amazon.in" in current_url else "https://www.amazon.com"
                                    href = base + href
                                print(f"[BrowserSkill] Navigating to Amazon product link: {href}")
                                self.page.goto(href)
                            else:
                                locator.click()
                            self.record_action("click_first_result", "Amazon fallback", success=True)
                            return "Clicked first product result."
                print("[BrowserSkill] Amazon product link not found.")
                return "Could not find a valid Amazon product link to click."

            elif "youtube" in current_url:
                selectors = [
                    "ytd-video-renderer a#video-title",
                    "#video-title-link",
                    "a.ytd-video-renderer"
                ]
                for sel in selectors:
                    locator = self.page.locator(sel).first
                    if locator.is_visible(timeout=3000):
                        print("[BrowserSkill] Clicking YouTube video link")
                        locator.click()
                        print("[BrowserSkill] Playing first video result successfully.")
                        self.record_action("click_first_result", "YouTube", success=True)
                        return "Playing first video result."
                print("[BrowserSkill] YouTube video link not found.")
                return "Could not find a valid YouTube video link to click."

            elif "google" in current_url or "duckduckgo" in current_url:
                # Organic link selectors, bypassing ads
                selectors = [
                    "#search a", 
                    ".g a", 
                    ".yuRUbf a",
                    ".result__title a",
                    "a.result__url",
                    "a"
                ]
                for sel in selectors:
                    locators = self.page.locator(sel)
                    count = locators.count()
                    for idx in range(count):
                        loc = locators.nth(idx)
                        try:
                            if loc.is_visible(timeout=1000):
                                href = loc.get_attribute("href")
                                if href:
                                    if "/aclk" in href or "google.com/aclk" in href or "adurl" in href:
                                        print(f"[BrowserSkill] Skipping Google Ad/Sponsored link: {href}")
                                        continue
                                    if "google.com" in href and not href.startswith("https://google.com/search") and any(x in href for x in ["/search?", "/support", "/preferences", "/accounts"]):
                                        continue
                                    if href.startswith("/") or href.startswith("#") or "javascript:" in href:
                                        continue
                                    if "duckduckgo.com/y.js" in href or "/y.js?" in href:
                                        print(f"[BrowserSkill] Skipping DuckDuckGo Ad/Sponsored link: {href}")
                                        continue
                                    print(f"[BrowserSkill] Clicking organic search result link: {href}")
                                    self.page.goto(href)
                                    self.record_action("click_first_result", f"Search link: {href}", success=True)
                                    return f"Clicked first result link: {href}"
                        except Exception as e:
                            print(f"[BrowserSkill] Error checking link index {idx}: {e}")
                            continue
                print("[BrowserSkill] No organic search result link found.")
                return "Could not find a valid organic result link to click."

            else:
                # Check cards first
                cards = self.page_state.get("cards", [])
                visible_cards = [c for c in cards if c.get("is_visible_in_viewport")]
                if not visible_cards:
                    visible_cards = cards
                if visible_cards:
                    first_card_id = visible_cards[0].get("aria_id")
                    print(f"[BrowserSkill] Clicking first visible card: {first_card_id}")
                    click_res = self.click_aria_id(first_card_id)
                    if "Error" not in click_res:
                        return f"Clicked first result card: {first_card_id}"
                
                link = self.page.locator("a").first
                if link.is_visible(timeout=2000):
                    print("[BrowserSkill] Clicking first generic link on page")
                    link.click()
                    print("[BrowserSkill] Clicked first generic link successfully.")
                    self.record_action("click_first_result", "Generic link", success=True)
                    return "Clicked first link."
                print("[BrowserSkill] No clickable links or cards found on page.")
                return "No clickable links or cards found on page."
        except Exception as e:
            print(f"[BrowserSkill] Click first result failed: {e}")
            return f"Failed to click first result: {e}"

    def click_add_to_cart(self):
        """Click Amazon's 'Add to Cart' button."""
        self._ensure_browser()
        print("[BrowserSkill] Clicking Add to Cart button...")

        try:
            selectors = [
                "input#add-to-cart-button",
                "#add-to-cart-button",
                "input[name='submit.add-to-cart']",
                "[data-button-id='add-to-cart']",
                "#buybox-insert"
            ]
            
            button = None
            for sel in selectors:
                try:
                    loc = self.page.locator(sel).first
                    if loc.is_visible(timeout=3000):
                        button = loc
                        break
                except Exception:
                    continue

            if button:
                button.click()
                print("[BrowserSkill] Clicked Add to Cart button.")
                time.sleep(2.0)
                self.record_action("click_add_to_cart", "Add to Cart button", success=True)
                return "Clicked Add to Cart."
            print("[BrowserSkill] Add to Cart button not found.")
            return "Add to Cart button not found on this page."
        except Exception as e:
            print(f"[BrowserSkill] Click Add to Cart failed: {e}")
            return f"Failed to click Add to Cart: {e}"

    def scroll(self, direction="down", amount="normal"):
        """Scroll the page down, up, to top, or to bottom with custom amounts."""
        self._ensure_browser()
        print(f"[BrowserSkill] Scrolling page {direction} (amount: {amount})...")

        try:
            before = self.page.evaluate(
                """() => ({
                    x: window.scrollX,
                    y: window.scrollY,
                    h: document.documentElement.scrollTop || document.body.scrollTop || 0
                })"""
            )
            
            direction_clean = direction.lower().strip()
            amount_clean = amount.lower().strip()
            
            if direction_clean == "top":
                self.page.evaluate(
                    """() => {
                        window.scrollTo(0, 0);
                        const candidates = [document.scrollingElement, document.documentElement, document.body].filter(Boolean);
                        for (const el of candidates) {
                            if (el) el.scrollTop = 0;
                        }
                    }"""
                )
                self.page.mouse.wheel(0, -100000)
            elif direction_clean == "bottom":
                self.page.evaluate(
                    """() => {
                        window.scrollTo(0, document.documentElement.scrollHeight || document.body.scrollHeight);
                        const candidates = [document.scrollingElement, document.documentElement, document.body].filter(Boolean);
                        for (const el of candidates) {
                            if (el) el.scrollTop = el.scrollHeight;
                        }
                    }"""
                )
                self.page.mouse.wheel(0, 100000)
            else:
                # Custom scroll factors
                if amount_clean == "little":
                    factor = 0.15
                    wheel_delta = 150
                elif amount_clean == "more":
                    factor = 0.60
                    wheel_delta = 600
                else:  # normal
                    factor = 0.30
                    wheel_delta = 300
                    
                if direction_clean == "up":
                    factor = -factor
                    wheel_delta = -wheel_delta
                    
                self.page.evaluate(
                    f"""() => {{
                        const candidates = [document.scrollingElement, document.documentElement, document.body]
                            .filter(Boolean);
                        const delta = window.innerHeight * {factor};
                        let scrolled = false;
                        for (const el of candidates) {{
                            const beforeTop = el.scrollTop;
                            el.scrollBy(0, delta);
                            if (el.scrollTop !== beforeTop) scrolled = true;
                        }}
                        window.scrollBy(0, delta);
                    }}"""
                )
                self.page.mouse.wheel(0, wheel_delta)
                
            self.page.wait_for_timeout(250)
            after = self.page.evaluate(
                """() => ({
                    x: window.scrollX,
                    y: window.scrollY,
                    h: document.documentElement.scrollTop || document.body.scrollTop || 0
                })"""
            )
            moved = before != after
            self.record_action("scroll", f"{direction}_{amount}", success=moved)
            if moved:
                print(f"[BrowserSkill] Scrolled page {direction} ({amount}).")
                self._update_page_state()
                return f"Scrolled {direction}."
            print("[BrowserSkill] Scroll command did not move the page.")
            return "I tried to scroll, but the page did not move. The browser page may not be focused or scrollable."
        except Exception as e:
            print(f"[BrowserSkill] Scroll failed: {e}")
            return f"Failed to scroll: {e}"

    def cheapest_visible_item(self):
        """Return the cheapest visible priced item from the current page state."""
        self._ensure_browser()
        self._update_page_state()
        import re

        candidates = []
        for group in ("cards", "buttons", "links"):
            for item in self.page_state.get(group, []):
                if not item.get("is_visible_in_viewport", True):
                    continue
                text = " ".join((item.get("text") or "").split())
                if not text:
                    continue
                prices = []
                for match in re.finditer(r"₹\s*([0-9][0-9,]*(?:\.\d+)?)", text):
                    try:
                        prices.append(float(match.group(1).replace(",", "")))
                    except ValueError:
                        pass
                if prices:
                    name = re.split(r"₹\s*[0-9]", text, maxsplit=1)[0].strip(" -|")
                    candidates.append((min(prices), name or text[:90], text[:220]))

        if not candidates:
            return "I can see the page, but I couldn't detect visible prices in the current view."

        price, name, text = min(candidates, key=lambda row: row[0])
        return f"The cheapest visible option I can see is {name} at about ₹{price:,.0f}."

    def click_element(self, text_or_selector):
        """Generically click an element by text, selector, or semantic reference with safety checks."""
        self._ensure_browser()
        print(f"[BrowserSkill] Attempting click on '{text_or_selector}'...")

        # Safety Check
        safety_words = ["buy", "checkout", "payment", "place order", "purchase", "delete", "remove", "pay", "confirm buy"]
        target_lower = text_or_selector.lower().strip()
        if any(w in target_lower for w in safety_words):
            print(f"[BrowserSkill] Blocked click on dangerous action: '{text_or_selector}'")
            return f"Action blocked for security. Automatic checkouts or deletions require manual confirmation."

        # 0. Check if target is already a direct aria_id
        if text_or_selector.startswith(("button_", "link_", "input_", "card_")):
            return self.click_aria_id(text_or_selector)

        # 1. Try to resolve semantically first (e.g. "second product", "search box")
        semantic_id = self.resolve_semantic_target(text_or_selector)
        if semantic_id:
            print(f"[BrowserSkill] Resolved semantic target '{text_or_selector}' to '{semantic_id}'")
            return self.click_aria_id(semantic_id)

        try:
            # Handle generic search field focus/click commands
            search_field_commands = ["search box", "search field", "click search box", "click search field", "search input", "input search", "search bar"]
            if any(cmd == target_lower or target_lower in cmd for cmd in search_field_commands) or "search" in target_lower:
                search_selectors = [
                    "input[type='search']",
                    "input[name='q']",
                    "input[name='query']",
                    "input#twotabsearchtextbox",
                    "input[name='field-keywords']",
                    "input[placeholder*='search' i]",
                    "input[placeholder*='Search' i]",
                    "input.nav-input",
                    "input[type='text']"
                ]
                for sel in search_selectors:
                    try:
                        loc = self.page.locator(sel).first
                        if loc.is_visible(timeout=1000):
                            loc.click()
                            print(f"[BrowserSkill] Clicked search field using selector '{sel}'.")
                            is_no_op = self.record_action("click_element", sel, success=True)
                            if is_no_op:
                                return f"Clicked search field but page state did not change."
                            return f"Clicked search field."
                    except Exception:
                        continue

            if text_or_selector.startswith(".") or text_or_selector.startswith("#") or text_or_selector.startswith("input[") or text_or_selector.startswith("button["):
                self.page.locator(text_or_selector).first.click()
                print(f"[BrowserSkill] Clicked element matching selector '{text_or_selector}' successfully.")
                is_no_op = self.record_action("click_element", text_or_selector, success=True)
                if is_no_op:
                    return f"Clicked element matching selector '{text_or_selector}' but page state did not change."
                return f"Clicked element matching selector '{text_or_selector}'."
            else:
                loc = self.page.get_by_text(text_or_selector, exact=False).first
                if not loc.is_visible(timeout=2000):
                    loc = self.page.get_by_role("button", name=text_or_selector, exact=False).first
                if not loc.is_visible(timeout=2000):
                    loc = self.page.get_by_role("link", name=text_or_selector, exact=False).first
                
                loc.click()
                print(f"[BrowserSkill] Clicked text/role element '{text_or_selector}' successfully.")
                is_no_op = self.record_action("click_element", text_or_selector, success=True)
                if is_no_op:
                    return f"Clicked '{text_or_selector}' but page state did not change."
                return f"Clicked '{text_or_selector}'."
        except Exception as e:
            print(f"[BrowserSkill] Click on '{text_or_selector}' failed: {e}")
            self.record_action("click_element", text_or_selector, success=False)
            return f"Click failed: {e}"

    def fill_element(self, text_or_selector, value):
        """Find an input field by placeholder, label, name, selector, or semantic ID, and fill it with value."""
        self._ensure_browser()
        print(f"[BrowserSkill] Attempting to fill '{text_or_selector}' with value '{value}'...")

        # 0. Check if target is already a direct input aria_id
        target_aria_id = None
        if text_or_selector.startswith("input_"):
            target_aria_id = text_or_selector
        else:
            semantic_id = self.resolve_semantic_target(text_or_selector)
            if semantic_id and semantic_id.startswith("input_"):
                target_aria_id = semantic_id

        if target_aria_id:
            # Click and fill using coordinates/selectors
            # Let's find element details
            found_el = None
            for el in self.page_state.get('inputs', []):
                if el.get('aria_id') == target_aria_id:
                    found_el = el
                    break
            if found_el:
                bbox = found_el.get('bbox', {})
                cx = bbox.get('x', 0) + (bbox.get('width', 0) // 2)
                cy = bbox.get('y', 0) + (bbox.get('height', 0) // 2)
                try:
                    self.page.mouse.click(cx, cy)
                    # Double click to select all text first (safety clearance)
                    self.page.mouse.click(cx, cy, click_count=2)
                    self.page.keyboard.press("Control+A")
                    self.page.keyboard.press("Backspace")
                    self.page.keyboard.type(value)
                    is_no_op = self.record_action("fill", target_aria_id, success=True)
                    if is_no_op:
                        return f"Filled {target_aria_id} with '{value}' but page state did not change."
                    return f"Filled {target_aria_id} with '{value}'."
                except Exception as e:
                    print(f"[BrowserSkill] Fill semantic target '{target_aria_id}' failed: {e}")

        try:
            if text_or_selector.startswith(".") or text_or_selector.startswith("#") or text_or_selector.startswith("input["):
                self.page.locator(text_or_selector).first.fill(value)
                print(f"[BrowserSkill] Filled input matching selector '{text_or_selector}' successfully.")
                self.record_action("fill", text_or_selector, success=True)
                return f"Filled input matching '{text_or_selector}' with '{value}'."
            
            locators = [
                self.page.get_by_placeholder(text_or_selector, exact=False).first,
                self.page.get_by_label(text_or_selector, exact=False).first,
                self.page.locator(f"input[name*='{text_or_selector}']").first,
                self.page.locator(f"input[placeholder*='{text_or_selector}']").first
            ]
            for loc in locators:
                try:
                    if loc.is_visible(timeout=1500):
                        loc.fill(value)
                        print(f"[BrowserSkill] Filled text/label field '{text_or_selector}' successfully.")
                        self.record_action("fill", text_or_selector, success=True)
                        return f"Filled '{text_or_selector}' with '{value}'."
                except Exception:
                    continue

            self.page.keyboard.type(value)
            print(f"[BrowserSkill] Typed '{value}' into active page via keyboard.")
            self.record_action("fill_keyboard", value, success=True)
            return f"Typed '{value}' into page."
        except Exception as e:
            print(f"[BrowserSkill] Fill element '{text_or_selector}' failed: {e}")
            self.record_action("fill", text_or_selector, success=False)
            return f"Failed to fill input: {e}"

    def extract_page_content(self):
        """
        Extract detailed information (title, price, rating, reviews, bullets, description)
        from the active page DOM, optimized for Amazon and with general schema.org fallbacks.
        """
        self._ensure_browser()
        if not self.is_browser_active():
            return {}

        extractor_js = """
        () => {
            const info = {
                title: "",
                price: "",
                rating: "",
                review_count: "",
                bullets: [],
                description: "",
                is_product: false
            };

            try {
                const url = window.location.href;
                const isAmazon = url.includes("amazon.com") || url.includes("amazon.in") || url.includes("amazon.co.uk") || url.includes("amazon.ca") || url.includes("amazon.de");

                if (isAmazon) {
                    // Amazon Title
                    const titleEl = document.querySelector("#productTitle");
                    if (titleEl) info.title = titleEl.innerText.trim();

                    // Amazon Price
                    const priceOffscreen = document.querySelector(".a-price .a-offscreen");
                    if (priceOffscreen) {
                        info.price = priceOffscreen.innerText.trim();
                    } else {
                        const priceOurPrice = document.querySelector("#priceblock_ourprice, #priceblock_dealprice, .a-price-whole");
                        if (priceOurPrice) {
                            const priceSymbol = document.querySelector(".a-price-symbol");
                            const priceFraction = document.querySelector(".a-price-fraction");
                            const symbolStr = priceSymbol ? priceSymbol.innerText.trim() : "";
                            const fractionStr = priceFraction ? priceFraction.innerText.trim() : "";
                            info.price = symbolStr + priceOurPrice.innerText.trim() + (fractionStr ? "." + fractionStr : "");
                        }
                    }
                    if (!info.price) {
                        const genericPrice = document.querySelector("#price, .price, .a-color-price");
                        if (genericPrice) info.price = genericPrice.innerText.trim();
                    }

                    // Amazon Rating
                    const ratingEl = document.querySelector("#acrPopover, span.a-icon-alt, #acrCustomerReviewLink");
                    if (ratingEl) {
                        const text = ratingEl.innerText || ratingEl.textContent || "";
                        const match = text.match(/([0-9.]+\\s*(?:out of|from)\\s*[0-9.]+)/i) || text.match(/([0-9.]+)\\s*stars/i);
                        if (match) {
                            info.rating = match[0].trim();
                        } else if (text.trim()) {
                            info.rating = text.trim();
                        }
                    }
                    if (info.rating && (info.rating.includes("out of") || info.rating.includes("/"))) {
                        const parts = info.rating.split(/out of|\\//i);
                        if (parts.length > 0) {
                            info.rating = parts[0].trim() + " / 5";
                        }
                    }

                    // Amazon Review Count
                    const reviewsEl = document.querySelector("#acrCustomerReviewText");
                    if (reviewsEl) info.review_count = reviewsEl.innerText.trim();

                    // Amazon Features / Bullets
                    const bulletEls = document.querySelectorAll("#feature-bullets ul li span.a-list-item");
                    if (bulletEls.length > 0) {
                        bulletEls.forEach(el => {
                            const text = el.innerText.trim();
                            if (text && !text.startsWith("Make sure this fits")) {
                                info.bullets.push(text);
                            }
                        });
                    }

                    // Amazon Description
                    const descEl = document.querySelector("#productDescription");
                    if (descEl) info.description = descEl.innerText.trim();

                    info.is_product = !!(info.title && (info.price || info.rating));
                } else {
                    // Generic page extraction
                    info.title = document.title;

                    // Try to identify price
                    const priceSelectors = [
                        "[class*='price' i]", "[id*='price' i]", ".amount", ".price", 
                        "span.price-item", "div.product-price", ".product-price-amount"
                    ];
                    const pricePattern = /(?:[\\$\\u20AC\\u00A3\\u20B9]|rs\\.?)\\s*\\d+(?:[\\.,]\\d+)?/i;
                    for (const selector of priceSelectors) {
                        try {
                            const el = document.querySelector(selector);
                            if (el && el.innerText) {
                                const text = el.innerText.trim();
                                if (pricePattern.test(text)) {
                                    info.price = text;
                                    break;
                                }
                            }
                        } catch(e) {}
                    }
                    
                    if (!info.price) {
                        const matches = document.body.innerText.match(pricePattern);
                        if (matches) {
                            info.price = matches[0];
                        }
                    }

                    // Try to identify rating
                    const ratingSelectors = [
                        "[class*='rating' i]", "[id*='rating' i]", "[class*='star' i]", 
                        ".rating", ".stars"
                    ];
                    for (const selector of ratingSelectors) {
                        try {
                            const el = document.querySelector(selector);
                            if (el && el.innerText) {
                                const text = el.innerText.trim();
                                if (text.match(/[0-9.]+\\s*[\\/\\s]\\s*[0-5]/) || text.match(/[0-9.]+\\s*stars/i)) {
                                    info.rating = text;
                                    break;
                                }
                            }
                        } catch(e) {}
                    }

                    // Try metadata description
                    const metaDesc = document.querySelector("meta[name='description']");
                    if (metaDesc) info.description = metaDesc.getAttribute("content") || "";

                    // Schema.org metadata LD+JSON
                    const ldJsonEls = document.querySelectorAll("script[type='application/ld+json']");
                    ldJsonEls.forEach(el => {
                        try {
                            const data = JSON.parse(el.textContent);
                            const processGraph = (graph) => {
                                if (graph && graph["@type"] === "Product") {
                                    info.is_product = true;
                                    if (graph.name) info.title = graph.name;
                                    if (graph.description) info.description = graph.description;
                                    if (graph.offers) {
                                        const offers = graph.offers;
                                        if (offers.price) {
                                            const currency = offers.priceCurrency || "$";
                                            info.price = currency + offers.price;
                                        } else if (Array.isArray(offers) && offers[0] && offers[0].price) {
                                            const currency = offers[0].priceCurrency || "$";
                                            info.price = currency + offers[0].price;
                                        }
                                    }
                                    if (graph.aggregateRating) {
                                        info.rating = `${graph.aggregateRating.ratingValue} / 5`;
                                        info.review_count = graph.aggregateRating.reviewCount || graph.aggregateRating.ratingCount || "";
                                    }
                                }
                            };
                            if (data) {
                                if (Array.isArray(data)) {
                                    data.forEach(item => processGraph(item));
                                } else if (data["@graph"] && Array.isArray(data["@graph"])) {
                                    data["@graph"].forEach(item => processGraph(item));
                                } else {
                                    processGraph(data);
                                }
                            }
                        } catch(e) {}
                    });
                }
            } catch(outerErr) {}

            // Final text cleanups
            info.title = (info.title || "").trim();
            info.price = (info.price || "").trim();
            info.rating = (info.rating || "").trim();
            info.review_count = (info.review_count || "").trim();
            info.description = (info.description || "").trim();
            info.bullets = info.bullets.map(b => b.trim()).filter(b => b.length > 0).slice(0, 8);

            return info;
        }
        """
        try:
            return self.page.evaluate(extractor_js) or {}
        except Exception as e:
            print(f"[BrowserSkill] DOM page content extraction failed: {e}")
            return {}

    def summarize_page(self, brain=None):
        """Extract visible text from page and summarize it using local generative model."""
        self._ensure_browser()
        print("[BrowserSkill] Summarizing page text content...")

        try:
            text = self.page.evaluate("document.body.innerText")
            if not text or not text.strip():
                print("[BrowserSkill] No readable text found on page.")
                return "The page has no readable text."

            truncated_text = text.strip()[:6000]
            
            if brain:
                prompt = (
                    f"Provide a concise summary of the following webpage text. "
                    f"Focus on key articles, headlines, or main purposes of the site:\n\n"
                    f"{truncated_text}"
                )
                summary = brain.think(prompt)
                print("[BrowserSkill] Page summarized successfully using brain model.")
                return summary
            else:
                print("[BrowserSkill] No brain model provided. Returning text preview.")
                return f"Here is the text preview: {truncated_text[:300]}..."
        except Exception as e:
            print(f"[BrowserSkill] Page summarization failed: {e}")
            return f"Failed to read page text: {e}"

    def _update_page_state(self):
        """Evaluates browser-side script to extract interactive elements and update page_state."""
        if not self.is_browser_active():
            self.page_state = {}
            return
            
        extractor_js = """
        () => {
            const scrollY = window.scrollY || window.pageYOffset || 0;
            const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
            const documentHeight = document.documentElement.scrollHeight || document.body.scrollHeight || 0;
            
            const getBoundingBox = (el) => {
                const rect = el.getBoundingClientRect();
                return {
                    x: Math.round(rect.left + window.scrollX),
                    y: Math.round(rect.top + window.scrollY),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    top: Math.round(rect.top),
                    bottom: Math.round(rect.bottom),
                    left: Math.round(rect.left),
                    right: Math.round(rect.right)
                };
            };

            const isVisibleInViewport = (rect) => {
                return rect.bottom > 0 && rect.top < window.innerHeight && rect.right > 0 && rect.left < window.innerWidth;
            };

            const isElementVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return !!(rect.width || rect.height || el.getClientRects().length) &&
                       style.visibility !== 'hidden' &&
                       style.display !== 'none' &&
                       parseFloat(style.opacity || '1') > 0.05;
            };

            const cleanText = (txt) => {
                return (txt || "").replace(/\\s+/g, ' ').trim();
            };

            const inputs = [];
            const buttons = [];
            const links = [];
            const cards = [];

            // 1. Inputs
            const inputEls = Array.from(document.querySelectorAll("input, textarea, [role='textbox']"));
            let inputCount = 0;
            inputEls.forEach(el => {
                if (!isElementVisible(el)) return;
                const type = el.tagName.toLowerCase() === 'textarea' ? 'textarea' : (el.getAttribute('type') || 'text');
                if (['submit', 'button', 'image', 'checkbox', 'radio'].includes(type)) return;
                
                const rect = getBoundingBox(el);
                inputs.push({
                    aria_id: `input_${inputCount++}`,
                    role: type,
                    text: cleanText(el.value || el.placeholder || el.getAttribute('placeholder') || el.getAttribute('aria-label') || ""),
                    placeholder: el.placeholder || el.getAttribute('placeholder') || "",
                    bbox: rect,
                    is_visible_in_viewport: isVisibleInViewport(el.getBoundingClientRect())
                });
            });

            // 2. Buttons
            const buttonEls = Array.from(document.querySelectorAll("button, input[type='button'], input[type='submit'], [role='button'], .btn, .button"));
            let buttonCount = 0;
            buttonEls.forEach(el => {
                if (!isElementVisible(el)) return;
                const rect = getBoundingBox(el);
                buttons.push({
                    aria_id: `button_${buttonCount++}`,
                    role: 'button',
                    text: cleanText(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || ""),
                    bbox: rect,
                    is_visible_in_viewport: isVisibleInViewport(el.getBoundingClientRect())
                });
            });

            // 3. Links
            const linkEls = Array.from(document.querySelectorAll("a[href]"));
            let linkCount = 0;
            linkEls.forEach(el => {
                if (!isElementVisible(el)) return;
                const rect = getBoundingBox(el);
                links.push({
                    aria_id: `link_${linkCount++}`,
                    role: 'link',
                    text: cleanText(el.innerText || el.textContent || el.getAttribute('title') || ""),
                    href: el.getAttribute('href'),
                    bbox: rect,
                    is_visible_in_viewport: isVisibleInViewport(el.getBoundingClientRect())
                });
            });

            // 4. Cards
            const cardSelectors = [
                ".s-result-item[data-component-type='s-search-result']",
                "ytd-video-renderer",
                "ytd-rich-item-renderer",
                ".result-item"
            ];
            let cardCount = 0;
            cardSelectors.forEach(sel => {
                Array.from(document.querySelectorAll(sel)).forEach(el => {
                    if (!isElementVisible(el)) return;
                    const rect = getBoundingBox(el);
                    cards.push({
                        aria_id: `card_${cardCount++}`,
                        role: 'card',
                        text: cleanText(el.innerText || el.textContent || ""),
                        bbox: rect,
                        is_visible_in_viewport: isVisibleInViewport(el.getBoundingClientRect())
                    });
                });
            });

            return {
                url: window.location.href,
                title: document.title,
                scroll_y: scrollY,
                viewport_height: viewportHeight,
                document_height: documentHeight,
                inputs,
                buttons,
                links,
                cards
            };
        }
        """
        try:
            state = self.page.evaluate(extractor_js)
            if state:
                self.page_state = state
                print(f"[BrowserSkill] Updated DOM Memory: {len(state['inputs'])} inputs, {len(state['buttons'])} buttons, {len(state['links'])} links, {len(state['cards'])} cards.")
        except Exception as e:
            print(f"[BrowserSkill] DOM extraction failed: {e}")
            self.page_state = {}

    def _compute_page_fingerprint(self):
        """Generates a stable state hash using URL, scroll position, layout metrics, and DOM structure."""
        if not self.page_state:
            return None
            
        import hashlib
        
        # 1. Compile signature of all interactive elements
        elements_signature = []
        interactive_count = 0
        total_text_length = 0
        
        for category in ['inputs', 'buttons', 'links', 'cards']:
            for el in self.page_state.get(category, []):
                interactive_count += 1
                text_val = el.get('text', '')
                total_text_length += len(text_val)
                elements_signature.append(f"{el.get('aria_id')}:{el.get('role')}:{text_val[:40]}")
                
        # 2. Compute DOM structure hash
        dom_sig_str = "||".join(elements_signature)
        dom_structure_hash = hashlib.md5(dom_sig_str.encode('utf-8')).hexdigest()
        
        # 3. Combine with URL, scroll/viewport metrics, interactive count, and text length
        url = self.page_state.get('url', '')
        scroll_y = self.page_state.get('scroll_y', 0)
        viewport_height = self.page_state.get('viewport_height', 0)
        document_height = self.page_state.get('document_height', 0)
        
        combined_sig = (
            f"URL:{url}||"
            f"ScrollY:{scroll_y}||"
            f"ViewportH:{viewport_height}||"
            f"DocumentH:{document_height}||"
            f"InteractiveCount:{interactive_count}||"
            f"TextLength:{total_text_length}||"
            f"DOMHash:{dom_structure_hash}"
        )
        
        return hashlib.md5(combined_sig.encode('utf-8')).hexdigest()

    def record_action(self, action_type, target, success=True):
        """Record the action and calculate before/after page fingerprint changes for loop prevention."""
        # Calculate fingerprint before action
        fp_before = self._compute_page_fingerprint()
        
        # After executing, update page state and compute new fingerprint
        time.sleep(0.5) # Allow page to process layout updates
        self._update_page_state()
        fp_after = self._compute_page_fingerprint()
        
        print("DEBUG RECORD_ACTION fp_before:", fp_before)
        print("DEBUG RECORD_ACTION fp_after:", fp_after)
        
        is_no_op = False
        if fp_before is not None and fp_after is not None and fp_before == fp_after:
            is_no_op = True
            print(f"[BrowserSkill] Loop Prevention: Detected NO-OP. Action '{action_type}' on '{target}' did not change screen state.")
            
        self.action_history.append({
            "action": action_type,
            "target": target,
            "success": success,
            "fp_before": fp_before,
            "fp_after": fp_after,
            "fingerprint_before": fp_before,
            "fingerprint_after": fp_after,
            "is_no_op": is_no_op,
            "timestamp": time.time()
        })
        
        # Keep action history size bounded
        if len(self.action_history) > 50:
            self.action_history.pop(0)
            
        return is_no_op

    def click_aria_id(self, aria_id):
        """Click an element by its unique aria_id from page_state."""
        self._ensure_browser()
        print(f"[BrowserSkill] Attempting click on ARIA ID '{aria_id}'...")
        
        # Find element details
        found_el = None
        for category in ['inputs', 'buttons', 'links', 'cards']:
            for el in self.page_state.get(category, []):
                if el.get('aria_id') == aria_id:
                    found_el = el
                    break
            if found_el:
                break
                
        if not found_el:
            print(f"[BrowserSkill] ARIA ID '{aria_id}' not found in current page state.")
            return f"Error: Target {aria_id} not found."
            
        # Target coordinate-based click
        bbox = found_el.get('bbox', {})
        cx = bbox.get('x', 0) + (bbox.get('width', 0) // 2)
        cy = bbox.get('y', 0) + (bbox.get('height', 0) // 2)
        
        # If it is a card element, try to click the first anchor tag inside it instead
        if aria_id.startswith("card_"):
            try:
                anchor_info = self.page.evaluate(
                    """([cx, cy]) => {
                        let el = document.elementFromPoint(cx - window.scrollX, cy - window.scrollY);
                        if (!el) return null;
                        let container = el;
                        while (container && container !== document.body) {
                            if (container.matches(".s-result-item, ytd-video-renderer, ytd-rich-item-renderer, .result-item") || container.getAttribute("role") === "card" || container.className.includes("card")) {
                                break;
                            }
                            container = container.parentElement;
                        }
                        if (!container || container === document.body) {
                            container = el.closest("[class*='card'], [id*='card'], .s-result-item");
                        }
                        if (!container) container = el;
                        const anchor = container.querySelector("a");
                        if (anchor) {
                            const rect = anchor.getBoundingClientRect();
                            return {
                                href: anchor.getAttribute("href") || "",
                                x: Math.round(rect.left + window.scrollX),
                                y: Math.round(rect.top + window.scrollY),
                                width: Math.round(rect.width),
                                height: Math.round(rect.height)
                            };
                        }
                        return null;
                    }""",
                    [cx, cy]
                )
                if anchor_info:
                    href = anchor_info.get("href", "")
                    cx = anchor_info['x'] + (anchor_info['width'] // 2)
                    cy = anchor_info['y'] + (anchor_info['height'] // 2)
                    print(f"[Browser] Card click redirected to anchor: {href}")
                    print(f"[Browser] Clicking anchor center: ({cx}, {cy})")
            except Exception as e:
                print(f"[BrowserSkill] Failed to resolve inner anchor tag for card '{aria_id}': {e}")

        try:
            self.page.mouse.click(cx, cy)
            print(f"[BrowserSkill] Clicked coordinates ({cx}, {cy}) for target '{aria_id}'.")
            
            # Record action outcome and check for no-op
            is_no_op = self.record_action("click", aria_id, success=True)
            if is_no_op:
                return f"Clicked {aria_id} but page state did not change."
            return f"Clicked element {aria_id}."
        except Exception as e:
            print(f"[BrowserSkill] Click on ARIA ID '{aria_id}' failed: {e}")
            self.record_action("click", aria_id, success=False)
            return f"Failed to click {aria_id}: {e}"

    def resolve_semantic_target(self, query):
        """Resolves target names or relative positions (e.g. 'second link') into matching aria_id targets."""
        self._update_page_state()
        if not self.page_state:
            return None
            
        query_lower = query.lower().strip()
        if not query_lower:
            return None
        
        # Check relative positions (e.g. 'first link', 'second product')
        relative_words = {
            "first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4,
            "1st": 0, "2nd": 1, "3rd": 2, "4th": 3, "5th": 4,
            "number one": 0, "number two": 1, "number three": 2
        }
        
        target_idx = None
        target_category = None
        
        for word, idx in relative_words.items():
            if word in query_lower:
                target_idx = idx
                break
                
        if "link" in query_lower:
            target_category = 'links'
        elif "button" in query_lower:
            target_category = 'buttons'
        elif "input" in query_lower or "search" in query_lower:
            target_category = 'inputs'
        elif "product" in query_lower or "card" in query_lower or "item" in query_lower or "video" in query_lower:
            target_category = 'cards'
            
        # Match relative query: e.g. "second link"
        if target_idx is not None and target_category is not None:
            elements = self.page_state.get(target_category, [])
            # Filter visible in viewport first
            visible_elements = [el for el in elements if el.get('is_visible_in_viewport')]
            if not visible_elements:
                visible_elements = elements # fallback to all
                
            if len(visible_elements) > target_idx:
                return visible_elements[target_idx].get('aria_id')
                
        # String match search
        best_match = None
        best_score = 0.0
        
        for category in ['inputs', 'buttons', 'links', 'cards']:
            for el in self.page_state.get(category, []):
                el_text = el.get('text', '').lower()
                el_placeholder = el.get('placeholder', '').lower()
                
                # Check exact or substring overlap
                score = 0.0
                if query_lower == el_text or query_lower == el_placeholder:
                    score = 1.0
                elif el_text and (query_lower in el_text or el_text in query_lower):
                    score = 0.8
                elif el_placeholder and query_lower in el_placeholder:
                    score = 0.7
                    
                if score > best_score:
                    best_score = score
                    best_match = el.get('aria_id')
                    
        return best_match
