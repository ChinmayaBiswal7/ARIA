import time
import json
import os
import threading
import urllib.request
import urllib.parse
import urllib.error

from skills.health_skill import HealthSkill
CONFIG_PATH = "firebase_config.json"
SERVICE_ACCOUNT_PATH = "serviceAccountKey.json"

# ── Optional: build a short-lived OAuth2 access token from the service account ──
def _get_access_token(service_account_path):
    """
    Mint a Google OAuth2 access token using the service-account private key.
    Requires only the stdlib + 'cryptography' (ships with firebase-admin).
    Falls back gracefully if cryptography is missing.
    """
    try:
        import base64, hashlib, struct, time as _t
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend

        with open(service_account_path) as f:
            sa = json.load(f)

        iat = int(_t.time())
        exp = iat + 3600
        header  = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=")
        payload = base64.urlsafe_b64encode(json.dumps({
            "iss":   sa["client_email"],
            "scope": "https://www.googleapis.com/auth/datastore",
            "aud":   "https://oauth2.googleapis.com/token",
            "iat":   iat,
            "exp":   exp,
        }).encode()).rstrip(b"=")

        signing_input = header + b"." + payload
        private_key = serialization.load_pem_private_key(
            sa["private_key"].encode(), password=None, backend=default_backend()
        )
        sig = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        jwt = signing_input + b"." + base64.urlsafe_b64encode(sig).rstrip(b"=")

        # Exchange JWT for access token
        token_url = "https://oauth2.googleapis.com/token"
        body = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion":  jwt.decode()
        }).encode()
        req = urllib.request.Request(token_url, data=body,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())["access_token"]

    except Exception as e:
        print(f"[FirebaseSync] Could not mint OAuth2 token: {e}")
        return None


def send_fcm_approval_push(action_tag: str, risk_level: str,
                            description: str = "",
                            service_account_path: str = SERVICE_ACCOUNT_PATH,
                            config_path: str = CONFIG_PATH) -> bool:
    """
    Send an FCM push notification to the registered Android device asking
    the user to approve or reject a HIGH/CRITICAL ARIA action.

    Flow:
      1. Read project_id from firebase_config.json
      2. Read device FCM token from Firestore  (aria_config/fcm.token)
      3. Mint an OAuth2 access token from the service account key
      4. POST to FCM HTTP v1  messages:send  endpoint
      5. Return True on success, False on any failure (caller continues)
    """
    import json, os, urllib.request, urllib.error

    # 1. Read project id
    project_id = ""
    try:
        with open(config_path) as _f:
            project_id = json.load(_f).get("project_id", "").strip()
    except Exception as _e:
        print(f"[FCMApproval] Cannot read firebase_config.json: {_e}")
        return False
    if not project_id:
        print("[FCMApproval] project_id missing – cannot push FCM.")
        return False

    # 2. Read FCM token from Firestore via firebase-admin (already initialised by main process)
    fcm_token = None
    try:
        import firebase_admin
        from firebase_admin import firestore as _fs
        if firebase_admin._apps:
            _db = _fs.client()
            _doc = _db.collection("aria_config").document("fcm").get()
            if _doc.exists:
                fcm_token = _doc.to_dict().get("token")
    except Exception as _e:
        print(f"[FCMApproval] Firestore token read failed: {_e}")

    if not fcm_token:
        print("[FCMApproval] No FCM device token registered – cannot push notification.")
        return False

    # 3. Mint OAuth2 access token (reuse existing helper, but need FCM scope)
    try:
        import base64, time as _time
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend

        with open(service_account_path) as _sf:
            _sa = json.load(_sf)

        _iat = int(_time.time())
        _exp = _iat + 3600
        _header  = base64.urlsafe_b64encode(
            json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=")
        _payload = base64.urlsafe_b64encode(json.dumps({
            "iss":   _sa["client_email"],
            "scope": "https://www.googleapis.com/auth/firebase.messaging",
            "aud":   "https://oauth2.googleapis.com/token",
            "iat":   _iat,
            "exp":   _exp,
        }).encode()).rstrip(b"=")
        _signing_input = _header + b"." + _payload
        _private_key = serialization.load_pem_private_key(
            _sa["private_key"].encode(), password=None, backend=default_backend())
        _sig = _private_key.sign(_signing_input, padding.PKCS1v15(), hashes.SHA256())
        _jwt = (_signing_input + b"." + base64.urlsafe_b64encode(_sig).rstrip(b"=")).decode()

        _token_body = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion":  _jwt
        }).encode()
        _treq = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=_token_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(_treq, timeout=10) as _tr:
            access_token = json.loads(_tr.read())["access_token"]
    except Exception as _e:
        print(f"[FCMApproval] OAuth2 token mint failed: {_e}")
        return False

    # 4. Send FCM v1 message
    risk_emoji = "🔴" if risk_level == "CRITICAL" else "🟠"
    body_text = description or action_tag
    # Truncate body if long
    if len(body_text) > 120:
        body_text = body_text[:117] + "..."

    fcm_payload = json.dumps({
        "message": {
            "token": fcm_token,
            "notification": {
                "title": f"{risk_emoji} ARIA Approval Required ({risk_level})",
                "body": body_text
            },
            "data": {
                "type": "approval_request",
                "action_tag": action_tag,
                "risk_level": risk_level,
                "open_tab": "approvals"
            },
            "android": {
                "priority": "HIGH",
                "notification": {
                    "channel_id": "aria_approvals",
                    "notification_priority": "PRIORITY_MAX",
                    "visibility": "PUBLIC",
                    "default_vibrate_timings": "true",
                    "default_sound": "true"
                }
            }
        }
    }).encode()

    fcm_url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    _freq = urllib.request.Request(
        fcm_url,
        data=fcm_payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(_freq, timeout=10) as _fr:
            _resp = json.loads(_fr.read())
            print(f"[FCMApproval] Push sent successfully: {_resp.get('name', 'OK')}")
            return True
    except urllib.error.HTTPError as _he:
        _err_body = _he.read().decode("utf-8", errors="replace")
        print(f"[FCMApproval] FCM HTTP error {_he.code}: {_err_body[:200]}")
        return False
    except Exception as _e:
        print(f"[FCMApproval] FCM push failed: {_e}")
        return False


def sync_profile_to_firestore(snapshot):
    """
    Sync user profile insights snapshot to Firestore 'profile_insights/latest' document.
    """
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        
        # Resolve service account path relative to workspace root
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sa_path = os.path.join(base_path, SERVICE_ACCOUNT_PATH)
        
        if not firebase_admin._apps:
            if os.path.exists(sa_path):
                cred = credentials.Certificate(sa_path)
                firebase_admin.initialize_app(cred)
            else:
                print(f"[FirebaseSync] Service account key not found at {sa_path}. Skipping firestore sync.")
                return False
                
        db = firestore.client()
        doc_ref = db.collection("profile_insights").document("latest")
        doc_ref.set(snapshot)
        print("[FirebaseSync] Profile insights successfully synced to Firestore.")
        return True
    except Exception as e:
        print(f"[FirebaseSync] Profile insights sync failed: {e}")
        return False


class FirebaseSync:
    """Listens to Cloud Firestore to execute remote commands.

    Priority:
      1. firebase-admin SDK with real-time on_snapshot listener  (fastest, no polling)
      2. Authenticated REST polling every 2 s using service-account OAuth2 token
      3. Unauthenticated REST polling (only works if Firestore rules are open)
    """

    def __init__(self, command_callback=None):
        self.callback         = command_callback
        self.enabled          = False
        self.status           = "IDLE"
        self.project_id       = ""
        self.running          = False
        self.last_cmd_id      = None
        self.last_cmd_ts      = 0          # secondary dedup via timestamp
        self.command_start_cutoff_ms = time.time() * 1000
        self.firestore_client = None
        self.listener         = None
        self._access_token    = None
        self._token_expiry    = 0
        self.status_updated_during_cmd = False
        self.current_command_id = None
        self.last_message     = "ARIA online. Ready."
        self.first_read_done  = False
        self.screenshot_quality = "medium"
        self.health_skill     = HealthSkill()
        self.vault_dir        = "data/knowledge_vault"
        self._vscode_bridge_skill = None
        self._browser_attachment_skill = None
        self.last_activity_time = 0.0
        self._load_config()

    # ── Config ────────────────────────────────────────────────────────────────
    def _load_config(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH) as f:
                    config = json.load(f)
                self.enabled    = config.get("enabled", False)
                self.project_id = config.get("project_id", "").strip()
            except Exception as e:
                print(f"[FirebaseSync] Error loading config: {e}")

    def _normalize_command_ts(self, cmd_ts):
        try:
            ts = float(cmd_ts)
        except (TypeError, ValueError):
            return 0
        # Phone commands use Date.now() milliseconds. Accept seconds too.
        if 0 < ts < 10_000_000_000:
            ts *= 1000
        return ts

    def _is_fresh_command(self, cmd_id, cmd_text, cmd_ts):
        if not cmd_text:
            return False

        # If we have never recorded any command, treat it as the initial one (sanity fallback)
        if self.last_cmd_id is None:
            self.last_cmd_id = cmd_id
            self.last_cmd_ts = self._normalize_command_ts(cmd_ts)
            return False

        new_id = cmd_id and cmd_id != self.last_cmd_id
        if not new_id:
            return False

        self.last_cmd_id = cmd_id
        self.last_cmd_ts = self._normalize_command_ts(cmd_ts)
        return True

    # ── SDK Init ──────────────────────────────────────────────────────────────
    def _init_sdk(self):
        """Attempts to load secure firebase-admin SDK if credentials exist."""
        if not os.path.exists(SERVICE_ACCOUNT_PATH):
            return False
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore

            if not firebase_admin._apps:
                cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
                firebase_admin.initialize_app(cred)

            self.firestore_client = firestore.client()
            print("[FirebaseSync] Secure Firebase Admin SDK initialized.")
            return True
        except ImportError:
            print("[FirebaseSync] 'firebase-admin' not installed. Run: pip install firebase-admin")
        except Exception as e:
            print(f"[FirebaseSync] SDK init failed: {e}")
        return False

    # ── OAuth2 token (for authenticated REST) ─────────────────────────────────
    def _get_bearer_token(self):
        """Return a valid OAuth2 bearer token, refreshing if needed."""
        if not os.path.exists(SERVICE_ACCOUNT_PATH):
            return None
        now = time.time()
        if self._access_token and now < self._token_expiry - 60:
            return self._access_token
        token = _get_access_token(SERVICE_ACCOUNT_PATH)
        if token:
            self._access_token = token
            self._token_expiry = now + 3600
            print("[FirebaseSync] OAuth2 access token refreshed.")
        return token

    def _get_telemetry(self):
        cpu_percent = 0.0
        ram_gb = 0.0
        try:
            import psutil
            cpu_percent = psutil.cpu_percent()
            ram_gb = psutil.virtual_memory().used / (1024.0 ** 3)
        except Exception:
            pass

        vscode_connected = False
        chrome_connected = False
        vscode_active_file = ""
        vscode_git_branch = ""
        vscode_errors = 0
        vscode_warnings = 0
        chrome_active_title = ""
        chrome_active_url = ""

        try:
            from skills.vscode_bridge_skill import AriaVsCodeBridgeSkill
            if not getattr(self, "_vscode_bridge_skill", None):
                self._vscode_bridge_skill = AriaVsCodeBridgeSkill()
            skill = self._vscode_bridge_skill
            vscode_connected = skill.is_bridge_server_alive()
            if vscode_connected:
                snap = skill.get_workspace_snapshot()
                if snap:
                    full_path = snap.get("active_file", "")
                    vscode_active_file = os.path.basename(full_path) if full_path else ""
                    vscode_git_branch = snap.get("git_branch", "")
                    vscode_errors = snap.get("error_count", 0)
                    vscode_warnings = snap.get("warning_count", 0)
        except Exception:
            pass

        chrome_tabs_count = 0
        try:
            from skills.browser_attachment_skill import AriaBrowserAttachmentSkill
            if not getattr(self, "_browser_attachment_skill", None):
                self._browser_attachment_skill = AriaBrowserAttachmentSkill()
            skill = self._browser_attachment_skill
            chrome_connected = skill.is_chrome_debuggable()
            if chrome_connected:
                # Throttle Chrome tab sync to once every 12 seconds to save CPU/CDP overhead
                now_t = time.time()
                last_sync = getattr(self, "_last_chrome_tab_sync", 0.0)
                if now_t - last_sync >= 12.0:
                    try:
                        skill.sync_live_tabs()
                    except Exception:
                        pass
                    self._last_chrome_tab_sync = now_t

                tabs = skill.get_tab_list(limit=500)
                chrome_tabs_count = len(tabs)
                if tabs:
                    chrome_active_title = tabs[0].get("tab_title", "")
                    chrome_active_url = tabs[0].get("tab_url", "")
        except Exception:
            pass

        return {
            "cpu_percent":          cpu_percent,
            "ram_gb":               ram_gb,
            "vscode_connected":     vscode_connected,
            "chrome_connected":     chrome_connected,
            "vscode_active_file":   vscode_active_file,
            "vscode_git_branch":    vscode_git_branch,
            "vscode_errors":        vscode_errors,
            "vscode_warnings":      vscode_warnings,
            "chrome_active_title":  chrome_active_title,
            "chrome_active_url":    chrome_active_url,
            "chrome_tabs_count":    chrome_tabs_count
        }

    # ── Status update ─────────────────────────────────────────────────────────
    def update_status(self, message, status_str="idle"):
        """Pushes status update back to Firestore (phone sees this)."""
        if not self.enabled or not self.project_id:
            return

        if status_str != "thinking":
            self.status_updated_during_cmd = True

        # Cache/update the last message
        if message:
            self.last_message = message
        else:
            message = getattr(self, "last_message", "ARIA online. Ready.")

        command_id = getattr(self, "current_command_id", None)

        def _do_update_async():
            sw, sh = 1920, 1080
            try:
                import pyautogui
                sw, sh = pyautogui.size()
            except Exception:
                pass

            telemetry = self._get_telemetry()

            if self.firestore_client:
                try:
                    data = {
                        "status":             status_str,
                        "last_response":      message,
                        "timestamp":          time.time(),
                        "reply_target":       "phone" if command_id else "laptop",
                        "screen_w":           sw,
                        "screen_h":           sh,
                        "screenshot_quality": self.screenshot_quality,
                    }
                    data.update(telemetry)
                    if command_id:
                        data["command_id"] = command_id
                    self.firestore_client.collection("status").document("latest").set(data, merge=True)
                    return
                except Exception as e:
                    print(f"[FirebaseSync] SDK status update failed: {e}")

            # REST fallback
            url = (f"https://firestore.googleapis.com/v1/projects/{self.project_id}"
                   f"/databases/(default)/documents/status/latest")
            payload = {"fields": {
                "status":             {"stringValue": status_str},
                "last_response":      {"stringValue": message},
                "timestamp":          {"doubleValue": time.time()},
                "reply_target":       {"stringValue": "phone" if command_id else "laptop"},
                "screen_w":           {"integerValue": sw},
                "screen_h":           {"integerValue": sh},
                "screenshot_quality": {"stringValue": self.screenshot_quality},
                "cpu_percent":        {"doubleValue": telemetry["cpu_percent"]},
                "ram_gb":             {"doubleValue": telemetry["ram_gb"]},
                "vscode_connected":   {"booleanValue": telemetry["vscode_connected"]},
                "chrome_connected":   {"booleanValue": telemetry["chrome_connected"]},
                "vscode_active_file": {"stringValue": telemetry["vscode_active_file"]},
                "vscode_git_branch":  {"stringValue": telemetry["vscode_git_branch"]},
                "vscode_errors":      {"integerValue": telemetry["vscode_errors"]},
                "vscode_warnings":    {"integerValue": telemetry["vscode_warnings"]},
                "chrome_active_title":{"stringValue": telemetry["chrome_active_title"]},
                "chrome_active_url":  {"stringValue": telemetry["chrome_active_url"]},
                "chrome_tabs_count":  {"integerValue": telemetry["chrome_tabs_count"]},
            }}
            if command_id:
                payload["fields"]["command_id"] = {"stringValue": command_id}
            try:
                headers = {"Content-Type": "application/json"}
                token = self._get_bearer_token()
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                             headers=headers, method="PATCH")
                with urllib.request.urlopen(req, timeout=10):
                    pass
            except Exception as e:
                print(f"[FirebaseSync] REST status update failed: {e}")

        import threading
        threading.Thread(target=_do_update_async, daemon=True).start()

    # ── SDK real-time snapshot callback ───────────────────────────────────────
    def _on_sdk_snapshot(self, doc_snapshot, changes, read_time):
        for doc in doc_snapshot:
            if not doc.exists:
                continue
            data     = doc.to_dict()
            cmd_id   = data.get("id")
            cmd_text = data.get("text")
            cmd_ts   = data.get("timestamp", 0)
            image_b64 = data.get("image_b64")

            # Ignore whatever command is already in Firestore at startup
            if not self.first_read_done:
                self.first_read_done = True
                self.last_cmd_id = cmd_id
                self.last_cmd_ts = self._normalize_command_ts(cmd_ts)
                print(f"[FirebaseSync] Initial SDK startup command ignored: '{cmd_text}' (id={cmd_id})")
                continue

            if self._is_fresh_command(cmd_id, cmd_text, cmd_ts):
                self.last_activity_time = time.time()
                if cmd_text == "[PING]":
                    continue
                print(f"[FirebaseSync] SDK command received: '{cmd_text}' (id={cmd_id})")
                threading.Thread(target=self._execute_remote_command,
                                 args=(cmd_text, image_b64, cmd_id), daemon=True).start()

    # ── REST polling loop (fallback) ──────────────────────────────────────────
    def _poll_rest_loop(self):
        """Authenticated REST polling — used when firebase-admin SDK is unavailable."""
        print("[FirebaseSync] REST polling mode active (2 s interval).")
        self.update_status("ARIA online. Ready.")

        consecutive_errors = 0
        while self.running:
            url = (f"https://firestore.googleapis.com/v1/projects/{self.project_id}"
                   f"/databases/(default)/documents/commands/latest")
            try:
                headers = {}
                token = self._get_bearer_token()
                if token:
                    headers["Authorization"] = f"Bearer {token}"

                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())

                consecutive_errors = 0

                if data and "fields" in data:
                    fields   = data["fields"]
                    cmd_id   = fields.get("id",        {}).get("stringValue")
                    cmd_text = fields.get("text",       {}).get("stringValue")
                    cmd_ts   = fields.get("timestamp",  {}).get("integerValue") or \
                               fields.get("timestamp",  {}).get("doubleValue", 0)
                    cmd_ts   = float(cmd_ts) if cmd_ts else 0
                    image_b64 = fields.get("image_b64", {}).get("stringValue")

                    if not self.first_read_done:
                        self.first_read_done = True
                        self.last_cmd_id = cmd_id
                        self.last_cmd_ts = self._normalize_command_ts(cmd_ts)
                        print(f"[FirebaseSync] Initial REST startup command ignored: '{cmd_text}' (id={cmd_id})")
                        continue

                    if self._is_fresh_command(cmd_id, cmd_text, cmd_ts):
                        self.last_activity_time = time.time()
                        if cmd_text == "[PING]":
                            continue
                        print(f"[FirebaseSync] REST command received: '{cmd_text}' (id={cmd_id})")
                        threading.Thread(target=self._execute_remote_command,
                                         args=(cmd_text, image_b64, cmd_id), daemon=True).start()

                # Also poll health/latest
                url_health = (f"https://firestore.googleapis.com/v1/projects/{self.project_id}"
                       f"/databases/(default)/documents/health/latest")
                try:
                    req_health = urllib.request.Request(url_health, headers=headers, method="GET")
                    with urllib.request.urlopen(req_health, timeout=10) as resp_health:
                        h_data = json.loads(resp_health.read().decode())
                        if h_data and "fields" in h_data:
                            hf = h_data["fields"]
                            steps = int(hf.get("steps", {}).get("integerValue", 0))
                            cals = float(hf.get("calories", {}).get("doubleValue", 0.0) or hf.get("calories", {}).get("integerValue", 0))
                            slp = float(hf.get("sleepHours", {}).get("doubleValue", 0.0) or hf.get("sleepHours", {}).get("integerValue", 0))
                            sq = hf.get("sleepQuality", {}).get("stringValue", "Unknown")
                            hr = int(hf.get("heartRate", {}).get("integerValue", 0))
                            spo2 = float(hf.get("spo2", {}).get("doubleValue", 0.0) or hf.get("spo2", {}).get("integerValue", 0))
                            ts = float(hf.get("timestamp", {}).get("doubleValue", time.time()) or hf.get("timestamp", {}).get("integerValue", time.time()))
                            
                            self.health_skill.save_fitness_metrics(
                                steps=steps, calories=cals, sleep_hours=slp,
                                sleep_quality=sq, heart_rate=hr, spo2=spo2, timestamp=ts
                            )
                except Exception as e:
                    pass

                # Also poll scanned_documents where synced_to_pc == false
                url_scans = (f"https://firestore.googleapis.com/v1/projects/{self.project_id}"
                             f"/databases/(default)/documents:runQuery")
                scans_payload = {
                    "structuredQuery": {
                        "from": [{"collectionId": "scanned_documents"}],
                        "where": {
                            "fieldFilter": {
                                "field": {"fieldPath": "synced_to_pc"},
                                "op": "EQUAL",
                                "value": {"booleanValue": False}
                            }
                        }
                    }
                }
                try:
                    headers_scans = {"Content-Type": "application/json"}
                    if token:
                        headers_scans["Authorization"] = f"Bearer {token}"
                    req_scans = urllib.request.Request(url_scans, data=json.dumps(scans_payload).encode(),
                                                       headers=headers_scans, method="POST")
                    with urllib.request.urlopen(req_scans, timeout=10) as resp_scans:
                        scans_data = json.loads(resp_scans.read().decode())
                        if isinstance(scans_data, list):
                            for doc_wrapper in scans_data:
                                if doc_wrapper and "document" in doc_wrapper:
                                    doc_info = doc_wrapper["document"]
                                    name_parts = doc_info["name"].split("/")
                                    doc_id = name_parts[-1]
                                    fields = doc_info.get("fields", {})
                                    
                                    data = {}
                                    for k, v in fields.items():
                                        val_type = list(v.keys())[0]
                                        data[k] = v[val_type]
                                        if val_type == "integerValue":
                                            data[k] = int(data[k])
                                        elif val_type == "doubleValue":
                                            data[k] = float(data[k])
                                        elif val_type == "booleanValue":
                                            data[k] = bool(data[k])
                                    
                                    if not data.get("synced_to_pc", False):
                                        print(f"[FirebaseSync] REST document scan received: {doc_id}")
                                        threading.Thread(target=self._process_incoming_scan, args=(doc_id, data), daemon=True).start()
                except Exception as e:
                    pass

            except urllib.error.HTTPError as e:
                consecutive_errors += 1
                body = e.read().decode(errors="ignore") if e.fp else ""
                print(f"[FirebaseSync] HTTP {e.code} polling Firestore: {body[:200]}")
                if e.code == 401 or e.code == 403:
                    # Force token refresh on auth failure
                    self._access_token = None
                if consecutive_errors >= 5:
                    print("[FirebaseSync] Too many errors — pausing 30 s before retry.")
                    time.sleep(30)
                    consecutive_errors = 0
            except urllib.error.URLError as e:
                consecutive_errors += 1
                print(f"[FirebaseSync] Network error: {e.reason}")
            except Exception as e:
                consecutive_errors += 1
                print(f"[FirebaseSync] Unexpected polling error: {e}")

            # Yield CPU/network if voice listening is active
            aria = self._get_aria_instance()
            if aria and aria.voice and hasattr(aria.voice, "listening_active") and aria.voice.listening_active.is_set():
                time.sleep(5.0)
            else:
                time.sleep(2.0)

    # ── Command execution ─────────────────────────────────────────────────────
    def _execute_remote_command(self, cmd_text, image_b64=None, cmd_id=None):
        try:
            print(f"[FirebaseSync] Executing remote command: '{cmd_text}'")
            
            # Intercept screenshot quality config commands from phone
            if cmd_text.lower().startswith("screenshot quality "):
                q = cmd_text.lower().replace("screenshot quality ", "").strip()
                if q in ["low", "medium", "high"]:
                    self.screenshot_quality = q
                    print(f"[FirebaseSync] Screenshot quality set to {q}")
                    self.update_status(f"Screenshot quality set to {q}", status_str="idle")
                    self.capture_and_upload_screenshot()
                    return

            self.current_command_id = cmd_id
            self.status_updated_during_cmd = False
            self.update_status(f"Executing: {cmd_text}", status_str="thinking")
            
            # Decode base64 image if present
            image = None
            if image_b64:
                try:
                    import base64
                    import io
                    from PIL import Image
                    if "," in image_b64:
                        image_b64 = image_b64.split(",")[1]
                    img_bytes = base64.b64decode(image_b64)
                    image = Image.open(io.BytesIO(img_bytes))
                    print(f"[FirebaseSync] Decoded remote image: {image.size}")
                except Exception as e:
                    print(f"[FirebaseSync] Failed to decode image: {e}")
            
            self.callback(cmd_text, image=image, remote=True)
            if not self.status_updated_during_cmd:
                self.update_status(f"Done: {cmd_text}", status_str="idle")
            
            # Immediately capture and upload screenshot for fast phone feedback
            self.capture_and_upload_screenshot()
        except Exception as e:
            print(f"[FirebaseSync] Command execution error: {e}")
            if not self.status_updated_during_cmd:
                self.update_status(f"Error: {e}", status_str="idle")
        finally:
            self.current_command_id = None

    def _grab_screen(self):
        # Method 1: mss (Fastest, ~10ms)
        try:
            import mss
            from PIL import Image
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                if img:
                    return img
        except Exception as e:
            print(f"[FirebaseSync] mss screen grab failed: {e}")

        # Method 2: PIL ImageGrab
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            if img:
                return img
        except Exception as e:
            print(f"[FirebaseSync] PIL ImageGrab failed: {e}")

        # Method 3: PyAutoGUI
        try:
            import pyautogui
            img = pyautogui.screenshot()
            if img:
                return img
        except Exception as e:
            print(f"[FirebaseSync] PyAutoGUI screen grab failed: {e}")

        # Method 4: PyQt5 (if QApplication is running)
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                screen = app.primaryScreen()
                if screen:
                    qpixmap = screen.grabWindow(0)
                    import io
                    from PIL import Image
                    buf = io.BytesIO()
                    qpixmap.save(buf, "PNG")
                    buf.seek(0)
                    img = Image.open(buf)
                    img.load()  # Force load image data
                    if img:
                        return img
        except Exception as e:
            print(f"[FirebaseSync] PyQt5 screen grab failed: {e}")

        raise Exception("All screenshot grab methods failed")

    def capture_and_upload_screenshot(self):
        """Captures the current screen, compresses it, and updates Firestore doc status/latest."""
        try:
            import io
            import base64
            from PIL import Image

            # Take screenshot using robust multi-tier fallback
            img = self._grab_screen()
            
            is_active = (time.time() - getattr(self, 'last_activity_time', 0.0)) < 45.0
            
            # Set target width, height, and JPEG compression quality based on preference and activity state
            if self.screenshot_quality == "low":
                w, h = 800, 450
                quality = 35 if is_active else 15
            elif self.screenshot_quality == "high":
                w, h = 1440, 810
                quality = 65 if is_active else 40
            else:  # medium
                w, h = 1120, 630
                quality = 45 if is_active else 25

            # Resize using bilinear for speed & quality and save optimized JPEG
            resample_filter = getattr(Image, "Resampling", Image).BILINEAR
            img = img.resize((w, h), resample=resample_filter)
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=quality, optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode()
            
            # Write to Firestore
            if self.firestore_client:
                doc_ref = self.firestore_client.collection("status").document("latest")
                doc_ref.update({"screenshot": b64})
            else:
                # REST fallback
                url = (f"https://firestore.googleapis.com/v1/projects/{self.project_id}"
                       f"/databases/(default)/documents/status/latest?updateMask.fieldPaths=screenshot")
                payload = {"fields": {
                    "screenshot": {"stringValue": b64}
                }}
                headers = {"Content-Type": "application/json"}
                token = self._get_bearer_token()
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                             headers=headers, method="PATCH")
                with urllib.request.urlopen(req, timeout=5):
                    pass
        except Exception as e:
            print(f"[FirebaseSync] Screenshot capture/upload failed: {e}")

    def _screenshot_loop(self):
        """Periodically uploads screenshot to Firebase so phone sees PC screen updates."""
        print("[FirebaseSync] Screenshot loop started.")
        while self.running:
            # 1. Determine active vs standby sleep time
            is_active = (time.time() - getattr(self, 'last_activity_time', 0.0)) < 45.0
            sleep_time = 0.25 if is_active else 3.0
            
            # 2. Segmented sleep to maintain clean thread shutdown responsiveness
            steps = int(sleep_time / 0.05)
            for _ in range(steps):
                if not self.running:
                    return
                time.sleep(0.05)
                
            if not self.running:
                return

            # 3. Yield CPU/network if voice session is active
            aria = self._get_aria_instance()
            if aria and aria.voice and (
                aria.voice.is_speaking
                or getattr(aria.voice, 'recording_active', False)
                or getattr(aria.voice, 'vad_detecting_speech', False)
                or (hasattr(aria.voice, "listening_active") and aria.voice.listening_active.is_set())
            ):
                if not getattr(self, "_paused_ss_log", False):
                    print("[FirebaseSync] Voice session active. Yielding screenshot loop (sleeping 1.0s)...")
                    self._paused_ss_log = True
                time.sleep(1.0)
                continue
            self._paused_ss_log = False

            # 4. Capture and upload
            self.capture_and_upload_screenshot()

    # ── Heartbeat Loop ────────────────────────────────────────────────────────
    def _heartbeat_loop(self):
        """Periodically updates status timestamp so phone client knows the server is alive."""
        print("[FirebaseSync] Heartbeat loop started.")
        while self.running:
            telemetry = self._get_telemetry()
            if self.firestore_client:
                try:
                    doc_ref = self.firestore_client.collection("status").document("latest")
                    update_data = {
                        "timestamp": time.time(),
                    }
                    update_data.update(telemetry)
                    doc_ref.update(update_data)
                except Exception:
                    # Fallback to set if doc doesn't exist yet
                    try:
                        doc_ref.set({
                            "status": "idle",
                            "last_response": "ARIA online. How can I help you?",
                            "timestamp": time.time(),
                            **telemetry
                        }, merge=True)
                    except Exception as ex:
                        print(f"[FirebaseSync] Heartbeat set failed: {ex}")
            else:
                # REST PATCH updateMask
                fields_to_update = ["timestamp", "cpu_percent", "ram_gb", "vscode_connected", "chrome_connected", 
                                    "vscode_active_file", "vscode_git_branch", "vscode_errors", "vscode_warnings", 
                                    "chrome_active_title", "chrome_active_url", "chrome_tabs_count"]
                mask_query = "&".join([f"updateMask.fieldPaths={f}" for f in fields_to_update])
                url = (f"https://firestore.googleapis.com/v1/projects/{self.project_id}"
                       f"/databases/(default)/documents/status/latest?{mask_query}")
                payload = {"fields": {
                    "timestamp":          {"doubleValue": time.time()},
                    "cpu_percent":        {"doubleValue": telemetry["cpu_percent"]},
                    "ram_gb":             {"doubleValue": telemetry["ram_gb"]},
                    "vscode_connected":   {"booleanValue": telemetry["vscode_connected"]},
                    "chrome_connected":   {"booleanValue": telemetry["chrome_connected"]},
                    "vscode_active_file": {"stringValue": telemetry["vscode_active_file"]},
                    "vscode_git_branch":  {"stringValue": telemetry["vscode_git_branch"]},
                    "vscode_errors":      {"integerValue": telemetry["vscode_errors"]},
                    "vscode_warnings":    {"integerValue": telemetry["vscode_warnings"]},
                    "chrome_active_title":{"stringValue": telemetry["chrome_active_title"]},
                    "chrome_active_url":  {"stringValue": telemetry["chrome_active_url"]},
                    "chrome_tabs_count":  {"integerValue": telemetry["chrome_tabs_count"]},
                }}
                try:
                    headers = {"Content-Type": "application/json"}
                    token = self._get_bearer_token()
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                                 headers=headers, method="PATCH")
                    with urllib.request.urlopen(req, timeout=5):
                        pass
                except Exception as e:
                    print(f"[FirebaseSync] REST heartbeat failed: {e}")
            # Yield CPU/network if voice listening is active
            aria = self._get_aria_instance()
            if aria and aria.voice and hasattr(aria.voice, "listening_active") and aria.voice.listening_active.is_set():
                time.sleep(8.0)
            else:
                time.sleep(3.0)

    # ── Start / Stop ──────────────────────────────────────────────────────────
    def start(self):
        if not self.enabled:
            print("[FirebaseSync] Disabled in firebase_config.json.")
            return
        if not self.project_id or "your-firebase-project" in self.project_id:
            print("[FirebaseSync] Invalid project_id in firebase_config.json.")
            return

        self.status = "INITIALIZING"
        self.running = True
        self.command_start_cutoff_ms = time.time() * 1000

        def _start_background():
            try:
                # Start background heartbeat thread
                self.hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
                self.hb_thread.start()

                # Start background screenshot thread
                self.ss_thread = threading.Thread(target=self._screenshot_loop, daemon=True)
                self.ss_thread.start()

                # 1. Try firebase-admin SDK (real-time, no polling)
                if self._init_sdk():
                    try:
                        doc_ref = self.firestore_client.collection("commands").document("latest")
                        self.listener = doc_ref.on_snapshot(self._on_sdk_snapshot)
                        
                        health_ref = self.firestore_client.collection("health").document("latest")
                        self.health_listener = health_ref.on_snapshot(self._on_health_snapshot)

                        scans_ref = self.firestore_client.collection("scanned_documents")
                        scans_query = scans_ref.where("synced_to_pc", "==", False)
                        self.scans_listener = scans_query.on_snapshot(self._on_scans_snapshot)
                        
                        self.update_status("ARIA online. Ready.", status_str="idle")
                        print("[FirebaseSync] Real-time SDK listener started. OK")

                        # Also start voice audio listener for phone push-to-talk
                        try:
                            from skills.api_integrations import APIIntegrations
                            integrations = APIIntegrations()
                            self._voice_listener = VoiceAudioListener(
                                self.firestore_client, self.callback, integrations
                            )
                            self._voice_listener.start()
                        except Exception as ve:
                            print(f"[FirebaseSync] VoiceAudioListener init failed: {ve}")

                        # Start WebRTC stream server
                        try:
                            from skills.webrtc_stream import AriaWebRtcStreamServer
                            self._webrtc_server = AriaWebRtcStreamServer(self.firestore_client)
                            self._webrtc_server.start()
                        except Exception as we:
                            print(f"[FirebaseSync] Failed to initialize WebRTC server: {we}")

                        self.status = "READY"
                        return
                    except Exception as e:
                        print(f"[FirebaseSync] SDK listener failed: {e}. Falling back to REST polling.")

                # 2. Fallback: authenticated REST polling
                self.thread = threading.Thread(target=self._poll_rest_loop, daemon=True)
                self.thread.start()
                self.status = "READY"
            except Exception as e:
                print(f"[FirebaseSync] Background start failed: {e}")
                self.status = "FAILED"

        threading.Thread(target=_start_background, daemon=True).start()

    def stop(self):
        self.running = False
        if hasattr(self, '_voice_listener') and self._voice_listener:
            try:
                self._voice_listener.stop()
            except Exception:
                pass
        if hasattr(self, '_webrtc_server') and self._webrtc_server:
            try:
                self._webrtc_server.stop()
            except Exception:
                pass
        if self.listener:
            try:
                self.listener.unsubscribe()
            except Exception:
                pass
        if hasattr(self, 'health_listener') and self.health_listener:
            try:
                self.health_listener.unsubscribe()
            except Exception:
                pass
        if hasattr(self, 'scans_listener') and self.scans_listener:
            try:
                self.scans_listener.unsubscribe()
            except Exception:
                pass

        # Write offline status before shutting down (graceful stop)
        if self.enabled and self.project_id:
            if self.firestore_client:
                try:
                    self.firestore_client.collection("status").document("latest").update({
                        "status": "offline",
                        "timestamp": time.time(),
                        "vscode_connected": False,
                        "chrome_connected": False
                    })
                    print("[FirebaseSync] Graceful offline status pushed to Firestore.")
                except Exception as e:
                    print(f"[FirebaseSync] Failed to set offline status on stop: {e}")
            else:
                try:
                    fields_to_update = ["status", "timestamp", "vscode_connected", "chrome_connected"]
                    mask_query = "&".join([f"updateMask.fieldPaths={f}" for f in fields_to_update])
                    url = (f"https://firestore.googleapis.com/v1/projects/{self.project_id}"
                           f"/databases/(default)/documents/status/latest?{mask_query}")
                    payload = {"fields": {
                        "status":             {"stringValue": "offline"},
                        "timestamp":          {"doubleValue": time.time()},
                        "vscode_connected":   {"booleanValue": False},
                        "chrome_connected":   {"booleanValue": False}
                    }}
                    headers = {"Content-Type": "application/json"}
                    token = self._get_bearer_token()
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                                 headers=headers, method="PATCH")
                    with urllib.request.urlopen(req, timeout=5):
                        pass
                    print("[FirebaseSync] Graceful REST offline status pushed to Firestore.")
                except Exception as e:
                    print(f"[FirebaseSync] Failed to set REST offline status on stop: {e}")

    def _on_health_snapshot(self, doc_snapshot, changes, read_time):
        for doc in doc_snapshot:
            if not doc.exists:
                continue
            data = doc.to_dict()
            steps = data.get("steps", 0)
            calories = float(data.get("calories", 0.0))
            sleep_hours = float(data.get("sleepHours", 0.0))
            sleep_quality = data.get("sleepQuality", "Unknown")
            heart_rate = data.get("heartRate", 0)
            spo2 = float(data.get("spo2", 0.0))
            timestamp = data.get("timestamp", time.time())
            
            # Print without spamming
            self.health_skill.save_fitness_metrics(
                steps=steps,
                calories=calories,
                sleep_hours=sleep_hours,
                sleep_quality=sleep_quality,
                heart_rate=heart_rate,
                spo2=spo2,
                timestamp=timestamp
            )

    def _on_scans_snapshot(self, col_snapshot, changes, read_time):
        for change in changes:
            if change.type.name in ["ADDED", "MODIFIED"]:
                doc = change.document
                data = doc.to_dict()
                if not data.get("synced_to_pc", False):
                    print(f"[FirebaseSync] New document scan snapshot received: {doc.id}")
                    threading.Thread(target=self._process_incoming_scan, args=(doc.id, data), daemon=True).start()

    def _get_aria_instance(self):
        if self.callback and hasattr(self.callback, "__self__"):
            return self.callback.__self__
        try:
            main_mod = __import__('__main__')
            return getattr(main_mod, 'instance', None) or getattr(main_mod, 'aria_instance', None)
        except Exception:
            return None

    def _calculate_jaccard_similarity(self, text1: str, text2: str) -> float:
        import re
        words1 = set(re.findall(r'\w+', text1.lower()))
        words2 = set(re.findall(r'\w+', text2.lower()))
        if not words1 and not words2:
            return 1.0
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        return len(intersection) / len(union)

    def _classify_topic_with_gemini(self, text: str) -> str:
        aria = self._get_aria_instance()
        if aria and getattr(aria, "brain", None):
            prompt = f"""
            You are ARIA's topic classification brain.
            Analyze the following text extracted via OCR and classify it into exactly one of these topics:
            DBMS, OS, CN, JAVA, DSA, GENERAL.

            Respond with ONLY the topic name (e.g. "DBMS"). Do not include any explanation or extra text.

            == EXTRACTED TEXT ==
            {text[:2000]}
            """
            try:
                result = aria.brain.think(prompt).strip().upper()
                valid_topics = ["DBMS", "OS", "CN", "JAVA", "DSA", "GENERAL"]
                for t in valid_topics:
                    if t in result:
                        return t
            except Exception as e:
                print(f"[FirebaseSync] Gemini classification failed: {e}")
        
        # Fallback to simple keyword heuristics
        text_lower = text.lower()
        if any(w in text_lower for w in ["database", "dbms", "sql", "transaction", "isolation", "query"]):
            return "DBMS"
        if any(w in text_lower for w in ["process", "thread", "scheduling", "semaphore", "deadlock", "memory management"]):
            return "OS"
        if any(w in text_lower for w in ["ip address", "tcp", "udp", "routing", "network", "packet", "http"]):
            return "CN"
        if any(w in text_lower for w in ["java", "class", "interface", "polymorphism", "inheritance", "garbage collection"]):
            return "JAVA"
        if any(w in text_lower for w in ["array", "list", "tree", "graph", "binary search", "sorting", "dsa"]):
            return "DSA"
        return "GENERAL"

    def _download_scan_image(self, image_path: str, local_dest: str):
        try:
            from firebase_admin import storage
            bucket = storage.bucket(f"{self.project_id}.firebasestorage.app")
            blob = bucket.blob(image_path)
            os.makedirs(os.path.dirname(local_dest), exist_ok=True)
            blob.download_to_filename(local_dest)
            print(f"[FirebaseSync] Scanned image downloaded to: {local_dest}")
            return True
        except Exception as e:
            print(f"[FirebaseSync] Failed to download scan image: {e}")
            return False

    def _process_incoming_scan(self, doc_id: str, data: dict):
        try:
            import re
            text = data.get("text", "").strip()
            title = data.get("title", f"scan_{int(time.time())}").strip()
            
            if not text:
                print(f"[FirebaseSync] Incoming scan {doc_id} has empty text. Skipping.")
                return

            self.update_status(f"Ingesting scan: {title}...", status_str="thinking")

            # 1. Jaccard similarity duplicate check
            is_duplicate = False
            duplicate_source = ""
            vault_dir = self.vault_dir
            if os.path.exists(vault_dir):
                for root, _, files in os.walk(vault_dir):
                    for file in files:
                        if file.endswith(".txt"):
                            file_path = os.path.join(root, file)
                            try:
                                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                                    existing_text = f.read()
                                similarity = self._calculate_jaccard_similarity(text, existing_text)
                                if similarity > 0.85:
                                    is_duplicate = True
                                    duplicate_source = file
                                    break
                            except Exception as ex:
                                print(f"[FirebaseSync] Error checking duplicate against {file}: {ex}")

            if is_duplicate:
                print(f"[FirebaseSync] Duplicate detected: incoming scan matches '{duplicate_source}' (>85% Jaccard). Skipping.")
                if self.firestore_client:
                    self.firestore_client.collection("scanned_documents").document(doc_id).update({
                        "synced_to_pc": True,
                        "synced_at": time.time(),
                        "sync_status": f"SKIPPED_DUPLICATE_OF_{duplicate_source}"
                    })
                self.update_status(f"Skipped duplicate scan matching '{duplicate_source}'", status_str="idle")
                return

            # 2. Topic classification
            topic = self._classify_topic_with_gemini(text)
            print(f"[FirebaseSync] Scan classified as: {topic}")

            # 3. Clean title for filename
            clean_title = re.sub(r'[^a-zA-Z0-9_\- ]', '', title).strip().replace(" ", "_").lower()
            if not clean_title:
                clean_title = f"scan_{int(time.time())}"

            # 4. Download image locally if available
            image_path = data.get("image_path")
            local_image_path = ""
            if image_path:
                local_image_name = f"{clean_title}_{int(time.time())}.jpg"
                local_dest = os.path.join(vault_dir, topic.lower(), "images", local_image_name)
                if self._download_scan_image(image_path, local_dest):
                    local_image_path = local_dest

            # 5. Write text file to topic directory under vault
            topic_dir = os.path.join(vault_dir, topic.lower())
            os.makedirs(topic_dir, exist_ok=True)
            txt_path = os.path.join(topic_dir, f"{clean_title}.txt")
            
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"--- METADATA ---\n")
                f.write(f"Title: {title}\n")
                f.write(f"Topic: {topic}\n")
                f.write(f"OCR Confidence: {data.get('ocr_confidence', 0.0):.2f}\n")
                f.write(f"Source: mobile_scan\n")
                if local_image_path:
                    f.write(f"Image Path: {local_image_path}\n")
                f.write(f"Created At: {data.get('created_at', '')}\n")
                f.write(f"Synced At: {time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())}\n")
                f.write(f"----------------\n\n")
                f.write(text)

            print(f"[FirebaseSync] Saved scan document to: {txt_path}")

            # 6. Trigger incremental re-indexing
            from skills.knowledge_search_agent import AriaKnowledgeSearchAgent
            agent = AriaKnowledgeSearchAgent(self._get_aria_instance(), vault_dir=vault_dir)
            agent.rebuild_knowledge_index()

            # 7. Update Firestore status
            if self.firestore_client:
                self.firestore_client.collection("scanned_documents").document(doc_id).update({
                    "synced_to_pc": True,
                    "synced_at": time.time(),
                    "sync_status": "SUCCESS",
                    "assigned_topic": topic
                })

            self.update_status(f"Ingested '{title}' into Knowledge Vault ({topic})", status_str="idle")
        except Exception as e:
            print(f"[FirebaseSync] Scan processing error: {e}")
            self.update_status(f"Scan ingestion failed: {e}", status_str="idle")

    def upload_pending_images(self, image_gen):
        if not self.firestore_client:
            print("[FirebaseSync] SDK not initialized. Skipping image upload.")
            return

        pending = image_gen.get_pending_uploads()
        if not pending:
            return

        print(f"[FirebaseSync] Uploading {len(pending)} image(s) to Firebase Storage...")
        try:
            from firebase_admin import storage
            bucket = storage.bucket(f"{self.project_id}.firebasestorage.app")
            
            for local_path in pending:
                try:
                    filename = os.path.basename(local_path)
                    blob = bucket.blob(f"aria-images/{filename}")
                    blob.upload_from_filename(local_path)
                    print(f"[FirebaseSync] Uploaded: {filename}")
                    image_gen.mark_uploaded(local_path)
                except Exception as e:
                    print(f"[FirebaseSync] Upload failed for {local_path}: {e}")
        except Exception as e:
            print(f"[FirebaseSync] Firebase Storage access failed: {e}")


# ───────────────────────────────────────────────────────────────────────────────
# VoiceAudioListener — Phone push-to-talk → Firebase Storage → Groq Whisper
# ───────────────────────────────────────────────────────────────────────────────
class VoiceAudioListener:
    """
    Watches the Firestore 'voice_audio' collection for new documents.
    When a new unprocessed entry appears (uploaded by phone push-to-talk),
    downloads the audio from Firebase Storage, runs Groq Whisper STT,
    and fires the command callback with the transcript.

    Architecture:
        Phone mic → MediaRecorder → Firebase Storage upload
                                   → Firestore {url, processed:false}
                                              ↓  (on_snapshot)
        VoiceAudioListener → download → temp .webm → Groq Whisper → callback()
    """

    def __init__(self, firestore_client, command_callback, integrations):
        self.db            = firestore_client
        self.callback      = command_callback
        self.integrations  = integrations
        self.listener      = None
        self._seen_ids     = set()   # dedup guard
        self._start_time   = time.time()
        print("[VoiceAudio] VoiceAudioListener initialized.")

    def start(self):
        col_ref = self.db.collection("voice_audio")
        self.listener = col_ref.on_snapshot(self._on_snapshot)
        print("[VoiceAudio] Listening for push-to-talk voice clips...")

    def stop(self):
        if self.listener:
            try:
                self.listener.unsubscribe()
            except Exception:
                pass
        print("[VoiceAudio] Listener stopped.")

    def _on_snapshot(self, col_snapshot, changes, read_time):
        for change in changes:
            if change.type.name not in ("ADDED", "MODIFIED"):
                continue
            doc = change.document
            data = doc.to_dict()
            if not data:
                continue

            # Skip already-processed or docs from before we started
            if data.get("processed", False):
                continue
            doc_ts = data.get("timestamp_ms", 0) / 1000.0
            if doc_ts < self._start_time - 5:
                # Mark old pre-existing docs so we don't re-process on restart
                if doc.id not in self._seen_ids:
                    self._seen_ids.add(doc.id)
                continue
            if doc.id in self._seen_ids:
                continue
            self._seen_ids.add(doc.id)

            url  = data.get("url", "")
            audio_base64 = data.get("audio_base64", "")
            if not url and not audio_base64:
                continue

            # Process in background so listener isn't blocked
            threading.Thread(
                target=self._handle_voice_clip,
                args=(doc.id, url, audio_base64),
                daemon=True
            ).start()

    def _set_transcribing(self, doc_id):
        try:
            self.db.collection("voice_audio").document(doc_id).update({
                "transcribing": True
            })
        except Exception as e:
            print(f"[VoiceAudio] Could not mark transcribing: {e}")

    def _handle_voice_clip(self, doc_id, audio_url, audio_base64=None):
        import tempfile
        tmp_path = None
        transcript = ""
        try:
            print(f"[Laptop] voice_audio doc received: {doc_id}")
            self._set_transcribing(doc_id)

            # Save audio content to a temp WebM file
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                tmp_path = tmp.name
                if audio_base64:
                    print(f"[Laptop] Decoding audio from Base64...")
                    import base64
                    audio_data = base64.b64decode(audio_base64)
                    tmp.write(audio_data)
                    print(f"[Laptop] Decoded audio: {len(audio_data)} bytes")
                elif audio_url:
                    print(f"[VoiceAudio] Downloading from storage URL: {audio_url}...")
                    import urllib.request as ureq
                    with ureq.urlopen(audio_url, timeout=15) as resp:
                        tmp.write(resp.read())
                else:
                    raise ValueError("No audio data or URL provided")

            print(f"[VoiceAudio] Saved to {tmp_path}, transcribing with Groq Whisper...")

            # Transcribe via Groq Whisper
            transcript = self.integrations.transcribe_audio_groq(tmp_path)

            if not transcript or not transcript.strip():
                print("[VoiceAudio] Empty transcript — ignoring.")
                transcript = ""
                return

            transcript = transcript.strip()
            print(f"[Laptop] Whisper result: \"{transcript}\"")

            # Fire command callback (same as text command from phone)
            threading.Thread(
                target=self.callback,
                args=(transcript,),
                kwargs={"remote": True},
                daemon=True
            ).start()

        except Exception as e:
            print(f"[VoiceAudio] Error processing clip: {e}")
        finally:
            # Clean up temp file
            if tmp_path:
                try:
                    import os as _os
                    _os.unlink(tmp_path)
                except Exception:
                    pass
            # Always mark processed to prevent re-processing, storing the transcript
            self._mark_processed(doc_id, transcript)

    def _mark_processed(self, doc_id, transcript=""):
        try:
            self.db.collection("voice_audio").document(doc_id).update({
                "processed": True,
                "transcript": transcript,
                "processed_at": time.time()
            })
        except Exception as e:
            print(f"[VoiceAudio] Could not mark processed: {e}")
