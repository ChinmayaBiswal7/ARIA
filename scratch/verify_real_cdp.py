import subprocess
import time
import os
import sqlite3
from playwright.sync_api import sync_playwright
from skills.browser_attachment_skill import AriaBrowserAttachmentSkill

db_path = "aria_orchestrator.db"
profile_dir = r"C:\Users\KIIT\AppData\Local\Temp\chrome-cdp-test-profile"

print("[Verify] Starting Chrome with debugging port 9222...")
chrome_proc = subprocess.Popen([
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "--remote-debugging-port=9222",
    "--remote-allow-origins=*",
    f"--user-data-dir={profile_dir}",
    "--no-first-run",
    "--no-default-browser-check",
    "--headless"
])

time.sleep(4)  # Wait for Chrome to initialize

try:
    print("[Verify] Testing remote debugging port connection...")
    skill = AriaBrowserAttachmentSkill(db_path=db_path, cdp_url="http://127.0.0.1:9222", use_mock=False)
    if not skill.is_chrome_debuggable():
        print("[Verify] ERROR: Chrome debugging port is not responding!")
        chrome_proc.terminate()
        exit(1)
        
    print("[Verify] Chrome debugging port is active. Connecting via Playwright...")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        
        # 1. Open a regular tab (github.com)
        page1 = context.new_page()
        try:
            page1.goto("https://github.com/ChinmayaBiswal7/ARIA")
        except Exception as e:
            print(f"[Verify] (Note) github.com goto failed: {e}")
        
        # 2. Open a protected tab (netbanking)
        page2 = context.new_page()
        try:
            page2.goto("https://netbanking.sbi.co.in/banking/home")
        except Exception as e:
            print(f"[Verify] (Note) netbanking goto failed: {e}")
        
        # 3. Open another regular tab (spring.io)
        page3 = context.new_page()
        try:
            page3.goto("https://spring.io")
        except Exception as e:
            print(f"[Verify] (Note) spring.io goto failed: {e}")
        
        print("[Verify] Tabs opened in Chrome session.")
        browser.close()

    print("[Verify] Running sync_live_tabs()...")
    sync_stats = skill.sync_live_tabs()
    print("[Verify] Sync Stats:", sync_stats)
    
    # Check tabs in database
    tabs = skill.get_tab_list(limit=10)
    print("\n[Verify] Active Browser Tabs Ledger:")
    github_tab_id = None
    banking_tab_id = None
    
    for t in tabs:
        print(f" - ID: {t['tab_id']} | Tier: {t['permission_tier']} | Title: {t['tab_title']} | URL: {t['tab_url']}")
        if "github.com" in t['tab_url']:
            github_tab_id = t['tab_id']
        elif "netbanking" in t['tab_url']:
            banking_tab_id = t['tab_id']

    # Test permission and reading gates
    if github_tab_id:
        print(f"\n[Verify] Testing Read/Permission on GitHub Tab ({github_tab_id}):")
        # Should be PERM_ASK initially
        status, text = skill.read_tab_metadata(github_tab_id)
        print(f"  - Initial Read: Status={status} | Message={text}")
        
        # Allow it
        success, msg = skill.set_tab_permission(github_tab_id, "ALLOWED")
        print(f"  - Set to ALLOWED: Success={success} | Message={msg}")
        
        # Read again (should succeed)
        status, text = skill.read_tab_metadata(github_tab_id)
        print(f"  - Read After ALLOWED: Status={status}\n---\n{text}\n---")
        
    if banking_tab_id:
        print(f"\n[Verify] Testing Read/Permission on Protected NetBanking Tab ({banking_tab_id}):")
        # Should be PERM_DENIED initially
        status, text = skill.read_tab_metadata(banking_tab_id)
        print(f"  - Initial Read: Status={status} | Message={text}")
        
        # Try to ALLOW it (should fail)
        success, msg = skill.set_tab_permission(banking_tab_id, "ALLOWED")
        print(f"  - Try to Set to ALLOWED: Success={success} | Message={msg}")
        
        # Read again (should still be blocked)
        status, text = skill.read_tab_metadata(banking_tab_id)
        print(f"  - Read After Try: Status={status} | Message={text}")

finally:
    print("\n[Verify] Cleaning up: Terminating Chrome process...")
    chrome_proc.terminate()
    chrome_proc.wait()
    print("[Verify] Done.")
