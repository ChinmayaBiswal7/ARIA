import time
import json
import os
import threading
import urllib.request
import urllib.parse
import urllib.error

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

        sw, sh = 1920, 1080
        try:
            import pyautogui
            sw, sh = pyautogui.size()
        except Exception:
            pass

        if self.firestore_client:
            try:
                data = {
                    "status":        status_str,
                    "last_response": message,
                    "timestamp":     time.time(),
                    "reply_target":  "phone" if command_id else "laptop",
                    "screen_w":      sw,
                    "screen_h":      sh,
                }
                if command_id:
                    data["command_id"] = command_id
                self.firestore_client.collection("status").document("latest").set(data)
                
                # Clear command context after returning to idle
                if status_str == "idle":
                    self.current_command_id = None
                return
            except Exception as e:
                print(f"[FirebaseSync] SDK status update failed: {e}")

        # REST fallback
        url = (f"https://firestore.googleapis.com/v1/projects/{self.project_id}"
               f"/databases/(default)/documents/status/latest")
        payload = {"fields": {
            "status":        {"stringValue": status_str},
            "last_response": {"stringValue": message},
            "timestamp":     {"doubleValue": time.time()},
            "reply_target":  {"stringValue": "phone" if command_id else "laptop"},
            "screen_w":      {"integerValue": sw},
            "screen_h":      {"integerValue": sh},
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
            
            # Clear command context after returning to idle
            if status_str == "idle":
                self.current_command_id = None
        except Exception as e:
            print(f"[FirebaseSync] REST status update failed: {e}")

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
                        print(f"[FirebaseSync] REST command received: '{cmd_text}' (id={cmd_id})")
                        threading.Thread(target=self._execute_remote_command,
                                         args=(cmd_text, image_b64, cmd_id), daemon=True).start()

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

            time.sleep(2.0)

    # ── Command execution ─────────────────────────────────────────────────────
    def _execute_remote_command(self, cmd_text, image_b64=None, cmd_id=None):
        try:
            print(f"[FirebaseSync] Executing remote command: '{cmd_text}'")
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

    def capture_and_upload_screenshot(self):
        """Captures the current screen, compresses it, and updates Firestore doc status/latest."""
        try:
            import pyautogui
            import io
            import base64
            from PIL import Image

            # Take screenshot
            img = pyautogui.screenshot()
            # Resize to 960x540 for faster transmission
            img = img.resize((960, 540))
            # Save to JPEG bytes
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=60)
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
            # Wait 5 seconds between periodic uploads
            for _ in range(50):
                if not self.running:
                    break
                time.sleep(0.1)
            if self.running:
                self.capture_and_upload_screenshot()

    # ── Heartbeat Loop ────────────────────────────────────────────────────────
    def _heartbeat_loop(self):
        """Periodically updates status timestamp so phone client knows the server is alive."""
        print("[FirebaseSync] Heartbeat loop started.")
        while self.running:
            if self.firestore_client:
                try:
                    doc_ref = self.firestore_client.collection("status").document("latest")
                    # Try to only update timestamp to preserve current message/state
                    doc_ref.update({"timestamp": time.time()})
                except Exception:
                    # Fallback to set if doc doesn't exist yet
                    try:
                        doc_ref.set({
                            "status": "idle",
                            "last_response": "ARIA online. How can I help you?",
                            "timestamp": time.time()
                        })
                    except Exception as ex:
                        print(f"[FirebaseSync] Heartbeat set failed: {ex}")
            else:
                # REST PATCH updateMask
                url = (f"https://firestore.googleapis.com/v1/projects/{self.project_id}"
                       f"/databases/(default)/documents/status/latest?updateMask.fieldPaths=timestamp")
                payload = {"fields": {
                    "timestamp": {"doubleValue": time.time()}
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
            time.sleep(3.0)

    # ── Start / Stop ──────────────────────────────────────────────────────────
    def start(self):
        if not self.enabled:
            print("[FirebaseSync] Disabled in firebase_config.json.")
            return
        if not self.project_id or "your-firebase-project" in self.project_id:
            print("[FirebaseSync] Invalid project_id in firebase_config.json.")
            return

        self.running = True
        self.command_start_cutoff_ms = time.time() * 1000

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
                self.update_status("ARIA online. Ready.", status_str="idle")
                print("[FirebaseSync] Real-time SDK listener started. OK")
                return
            except Exception as e:
                print(f"[FirebaseSync] SDK listener failed: {e}. Falling back to REST polling.")

        # 2. Fallback: authenticated REST polling
        self.thread = threading.Thread(target=self._poll_rest_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.listener:
            try:
                self.listener.unsubscribe()
            except Exception:
                pass
