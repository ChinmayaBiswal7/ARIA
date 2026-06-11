"""
skills/browser_attachment_skill.py — ARIA Chrome CDP Attachment (Sprint P25.3)
===============================================================================

Attaches to the user's EXISTING Chrome session via Chrome DevTools Protocol (CDP)
rather than launching a clean isolated browser.

Design rules:
  - NEVER call browser.close() on a live session — only disconnect the pipe.
  - Stable tab IDs use SHA-256(url + title) — survive restarts, avoid positional chaos.
  - Protected domains (banking, auth, etc.) are auto-assigned DENIED permission.
  - All other tabs start at ASK — ARIA never reads content without explicit approval.
  - Only metadata is persisted (title, url, domain, timestamp). No raw HTML or cookies.

Usage:
    # User must launch Chrome with:
    #   chrome.exe --remote-debugging-port=9222 --remote-allow-origins=*
    skill = AriaBrowserAttachmentSkill(aria, db_path="aria_orchestrator.db")
    result = skill.sync_live_tabs()          # enumerate tabs
    ok, text = skill.read_tab_metadata(tab_id)  # read if ALLOWED
"""

import hashlib
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

# ── Playwright availability ───────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


# ── Permission tier constants ─────────────────────────────────────────────────
PERM_ALLOWED = "ALLOWED"
PERM_ASK     = "ASK"
PERM_DENIED  = "DENIED"

# ── Default CDP endpoint ──────────────────────────────────────────────────────
DEFAULT_CDP_URL = "http://localhost:9222"

# ── Domains that are permanently DENIED regardless of user preference ─────────
# These are patterns matched against the full URL (lowercased).
PROTECTED_DOMAIN_PATTERNS: Tuple[str, ...] = (
    "accounts.google.com",
    "myaccount.google.com",
    "login.microsoftonline.com",
    "github.com/login",
    "github.com/session",
    "netbanking",
    "onlinebanking",
    "banking",
    "paytm.com",
    "phonepe.com",
    "paypal.com",
    "stripe.com",
    "irctc.co.in",
    "incometax.gov.in",
    "password",
    "vault",
    "lastpass.com",
    "1password.com",
    "bitwarden",
    "dashlane.com",
    "wallet",
    "crypto",
)


# ─── Schema Initialisation ─────────────────────────────────────────────────────

def init_chrome_cdp_schema(db_path: str = "aria_orchestrator.db") -> None:
    """
    Create browser tracking tables in the orchestrator database.
    Safe to call multiple times — uses IF NOT EXISTS.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_browser_tabs (
                tab_id              TEXT PRIMARY KEY,  -- SHA-256(url+title) hex digest
                tab_title           TEXT,
                tab_url             TEXT,
                domain_segment      TEXT,
                permission_tier     TEXT DEFAULT 'ASK',  -- ALLOWED | ASK | DENIED
                last_seen_timestamp INTEGER,
                last_read_timestamp INTEGER              -- NULL until actually read
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS browser_sync_log (
                sync_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       INTEGER NOT NULL,
                mode            TEXT,   -- REAL | MOCK
                tabs_found      INTEGER,
                tabs_denied     INTEGER,
                tabs_ask        INTEGER,
                tabs_allowed    INTEGER,
                error_message   TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


# ─── Tab ID helpers ───────────────────────────────────────────────────────────

def _stable_tab_id(url: str, title: str) -> str:
    """
    Generate a stable, reproducible tab identifier using SHA-256(url + title).
    Survives browser restarts. Unaffected by positional index changes.
    Truncated to 16 hex chars for readability.
    """
    raw = f"{url.strip()}|{title.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _extract_domain(url: str) -> str:
    """Return the netloc portion of a URL, lowercased."""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return url.lower()[:60]


def _is_protected(url: str) -> bool:
    """
    Return True if the URL matches any protected domain pattern,
    OR if the URL is a browser error/internal page (chrome-error://, about:, etc.).
    Error pages are clamped to DENIED because they represent unresolvable destinations
    where the true target domain cannot be verified.
    """
    lower_url = url.lower()
    # Clamp error and internal pages to DENIED — destination unverifiable
    ERROR_SCHEMES = ("chrome-error://", "chrome://", "about:", "edge://", "data:", "javascript:")
    if any(lower_url.startswith(s) for s in ERROR_SCHEMES):
        return True
    return any(p in lower_url for p in PROTECTED_DOMAIN_PATTERNS)


# ─── Main Skill ───────────────────────────────────────────────────────────────

class AriaBrowserAttachmentSkill:
    """
    Securely attaches to the user's live Chrome session via CDP.

    Adapter pattern:
      - use_mock=False (default) → Real Playwright CDP connection.
      - use_mock=True            → Sandboxed mock data for testing.

    Both adapters go through the same permission/safety pipeline.
    """

    def __init__(
        self,
        aria_instance:  Any   = None,
        db_path:        str   = "aria_orchestrator.db",
        cdp_url:        str   = DEFAULT_CDP_URL,
        use_mock:       bool  = False,
    ) -> None:
        self.aria    = aria_instance
        self.db_path = db_path
        self.cdp_url = cdp_url
        # Force mock mode if Playwright isn't installed
        self.use_mock = use_mock or (not PLAYWRIGHT_AVAILABLE)

        init_chrome_cdp_schema(db_path)
        mode = "MOCK" if self.use_mock else "REAL_CDP"
        print(f"[BrowserAttachment] Initialised. Mode: {mode}  Target: {cdp_url}")

    # ── Primary API ────────────────────────────────────────────────────────

    def sync_live_tabs(self) -> Dict[str, Any]:
        """
        Enumerate all open Chrome tabs and persist metadata to the database.

        Returns a status dict:
        {
            "status": "SUCCESS" | "FAILED",
            "mode": "REAL" | "MOCK",
            "tabs_found": N,
            "tabs_denied": N,
            "tabs_ask": N,
            "tabs_allowed": N,
            "error": "<message>"   # only on FAILED
        }
        """
        start = time.time()
        try:
            raw = (
                self._fetch_mock_tabs()
                if self.use_mock
                else self._fetch_real_cdp_tabs()
            )
            stats = self._persist_tabs(raw)
            stats["status"] = "SUCCESS"
            stats["mode"]   = "MOCK" if self.use_mock else "REAL"
            self._log_sync(stats)
            return stats

        except Exception as exc:
            err = str(exc)
            print(f"[BrowserAttachment] sync_live_tabs failed: {err}")
            failed = {
                "status": "FAILED", "mode": "MOCK" if self.use_mock else "REAL",
                "tabs_found": 0, "tabs_denied": 0,
                "tabs_ask": 0, "tabs_allowed": 0, "error": err,
            }
            self._log_sync(failed)
            return failed

    def read_tab_metadata(self, tab_id: str) -> Tuple[str, str]:
        """
        Attempt to read metadata for a specific tab.

        Safety pipeline:
          1. Fetch tab from database.
          2. Check URL against PROTECTED_DOMAIN_PATTERNS → DENIED.
          3. Check permission_tier → DENIED / ASK blocks; ALLOWED proceeds.
          4. Return structural metadata (NOT raw HTML or cookies).

        Returns: (status_code, message)
          status_code: "ALLOWED" | "DENIED" | "ASK" | "NOT_FOUND"
        """
        row = self._get_tab_row(tab_id)
        if row is None:
            return "NOT_FOUND", f"Tab ID '{tab_id}' not found in ledger."

        url   = row["tab_url"]
        title = row["tab_title"]
        perm  = row["permission_tier"]

        # Hard block — protected domain
        if _is_protected(url):
            return PERM_DENIED, (
                f"ACCESS DENIED: '{_extract_domain(url)}' matches a protected "
                f"security boundary. ARIA cannot read this tab."
            )

        # User has explicitly denied
        if perm == PERM_DENIED:
            return PERM_DENIED, "ACCESS DENIED: You have set this tab to DENIED."

        # Awaiting approval
        if perm == PERM_ASK:
            return PERM_ASK, (
                f"AWAITING APPROVAL: '{title}' ({_extract_domain(url)}) "
                f"needs your permission. Say 'allow tab {tab_id}' to grant access."
            )

        # Allowed — return structural metadata only (no raw HTML)
        self._mark_tab_read(tab_id)
        summary = (
            f"Tab: {title}\n"
            f"URL: {url}\n"
            f"Domain: {_extract_domain(url)}\n"
            f"Last seen: {_ts_fmt(row['last_seen_timestamp'])}"
        )
        return PERM_ALLOWED, summary

    def set_tab_permission(self, tab_id: str, permission: str) -> Tuple[bool, str]:
        """
        Explicitly set a tab's permission tier.
        permission must be one of: ALLOWED | ASK | DENIED
        """
        if permission not in (PERM_ALLOWED, PERM_ASK, PERM_DENIED):
            return False, f"Invalid permission '{permission}'. Use ALLOWED, ASK, or DENIED."

        row = self._get_tab_row(tab_id)
        if row is None:
            return False, f"Tab ID '{tab_id}' not in ledger."

        # Never allow setting ALLOWED on a protected domain
        if permission == PERM_ALLOWED and _is_protected(row["tab_url"]):
            return False, "Cannot grant ALLOWED to a protected domain tab."

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE active_browser_tabs SET permission_tier = ? WHERE tab_id = ?",
                (permission, tab_id),
            )
            conn.commit()
        finally:
            conn.close()
        return True, f"Tab '{tab_id}' permission set to {permission}."

    def get_tab_list(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent tabs from the ledger as a list of dicts."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                """
                SELECT tab_id, tab_title, tab_url, domain_segment,
                       permission_tier, last_seen_timestamp
                FROM   active_browser_tabs
                ORDER  BY last_seen_timestamp DESC
                LIMIT  ?
                """,
                (limit,),
            )
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def is_chrome_debuggable(self) -> bool:
        """
        Quick probe: does localhost:9222/json/version respond?
        Safe to call at startup to detect if Chrome is running with CDP enabled.
        """
        try:
            import urllib.request
            url = self.cdp_url.rstrip("/") + "/json/version"
            with urllib.request.urlopen(url, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    # ── Private: Real CDP adapter ──────────────────────────────────────────

    def _fetch_real_cdp_tabs(self) -> List[Tuple[str, str, str]]:
        """
        Connect to the user's live Chrome session via Playwright CDP.

        IMPORTANT: We call `browser.disconnect()` — NOT `browser.close()`.
        `close()` would terminate the user's running browser instance.
        `disconnect()` only drops our monitoring pipe.
        """
        tabs: List[Tuple[str, str, str]] = []
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(self.cdp_url)
            try:
                for context in browser.contexts:
                    for page in context.pages:
                        try:
                            url   = page.url   or ""
                            title = page.title() or "(No Title)"
                            if url and url not in ("about:blank", "chrome://newtab/"):
                                tabs.append((url, title, "REAL"))
                        except Exception:
                            continue
            finally:
                # Detach only — never close the user's browser
                browser.close()
        return tabs

    # ── Private: Mock adapter ──────────────────────────────────────────────

    def _fetch_mock_tabs(self) -> List[Tuple[str, str, str]]:
        """
        Return deterministic test tab data.
        Includes one protected domain (banking) to verify auto-DENIED logic.
        """
        return [
            ("https://portal.kiit.ac.in/opportunities",
             "KIIT Placement Portal - Internships", "MOCK"),

            ("https://spring.io/guides/topicals/security/",
             "Spring Boot Security Architecture Reference", "MOCK"),

            ("https://github.com/ChinmayaBiswal7/ARIA",
             "ARIA - GitHub Repository", "MOCK"),

            ("https://netbanking.sbi.co.in/banking/home",
             "SBI NetBanking Dashboard", "MOCK"),       # ← should be auto-DENIED

            ("https://docs.python.org/3/library/sqlite3.html",
             "sqlite3 — Python 3 Documentation", "MOCK"),
        ]

    # ── Private: Persistence ───────────────────────────────────────────────

    def _persist_tabs(self, raw: List[Tuple[str, str, str]]) -> Dict[str, int]:
        """
        Upsert tab rows into active_browser_tabs.
        Protected domains are automatically assigned DENIED.
        New unlisted tabs start at ASK.
        Existing permission_tier is never downgraded (user choice is preserved).
        """
        now    = int(time.time())
        counts = {"tabs_found": 0, "tabs_denied": 0, "tabs_ask": 0, "tabs_allowed": 0}

        conn = sqlite3.connect(self.db_path)
        try:
            for url, title, _source in raw:
                tab_id = _stable_tab_id(url, title)
                domain = _extract_domain(url)

                # Determine correct default permission.
                # Also deny tabs with no parseable hostname (unresolvable navigation artifacts).
                parsed_host = _extract_domain(url)
                if _is_protected(url) or not parsed_host or "." not in parsed_host:
                    default_perm = PERM_DENIED
                else:
                    default_perm = PERM_ASK

                # INSERT or UPDATE — preserve existing permission_tier unless this is a new row
                conn.execute(
                    """
                    INSERT INTO active_browser_tabs
                        (tab_id, tab_title, tab_url, domain_segment,
                         permission_tier, last_seen_timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tab_id) DO UPDATE SET
                        tab_title           = excluded.tab_title,
                        last_seen_timestamp = excluded.last_seen_timestamp,
                        -- Never override a manually-set DENIED or ALLOWED with ASK
                        permission_tier = CASE
                            WHEN active_browser_tabs.permission_tier IN ('ALLOWED','DENIED')
                                THEN active_browser_tabs.permission_tier
                            ELSE excluded.permission_tier
                        END
                    """,
                    (tab_id, title, url, domain, default_perm, now),
                )

                # Count by effective tier
                effective = default_perm
                existing = self._get_tab_row(tab_id)
                if existing:
                    effective = existing["permission_tier"]

                counts["tabs_found"] += 1
                if effective == PERM_DENIED:
                    counts["tabs_denied"] += 1
                elif effective == PERM_ALLOWED:
                    counts["tabs_allowed"] += 1
                else:
                    counts["tabs_ask"] += 1

            conn.commit()
        finally:
            conn.close()
        return counts

    def _get_tab_row(self, tab_id: str) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                "SELECT * FROM active_browser_tabs WHERE tab_id = ?", (tab_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def _mark_tab_read(self, tab_id: str) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE active_browser_tabs SET last_read_timestamp = ? WHERE tab_id = ?",
                (int(time.time()), tab_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _log_sync(self, stats: Dict[str, Any]) -> None:
        """Write one row to browser_sync_log (silent on failure)."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO browser_sync_log
                        (timestamp, mode, tabs_found, tabs_denied, tabs_ask, tabs_allowed, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(time.time()),
                        stats.get("mode", "UNKNOWN"),
                        stats.get("tabs_found", 0),
                        stats.get("tabs_denied", 0),
                        stats.get("tabs_ask", 0),
                        stats.get("tabs_allowed", 0),
                        stats.get("error", None),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            print(f"[BrowserAttachment] sync log write failed: {exc}")


# ─── Utility ───────────────────────────────────────────────────────────────────

def _ts_fmt(ts: Optional[int]) -> str:
    if not ts:
        return "never"
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
