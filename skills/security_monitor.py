import cv2
import time
import os
import threading
import datetime
import pyautogui
from PIL import Image
import io
import json

class SecurityMonitor:
    # State constants
    STATE_SAFE = "SAFE"
    STATE_OBSERVING = "OBSERVING"
    STATE_INTRUSION = "INTRUSION"
    STATE_ALERTED = "ALERTED"

    def __init__(self, aria=None, db_path=None):
        self.aria = aria
        self.db_path = db_path
        
        # State tracking
        self.state = self.STATE_SAFE
        self.unknown_start_time = None
        self.last_alert_time = 0
        self.alert_cooldown = 60  # seconds between alerts
        self.last_mouse_pos = None
        self.last_active_window = None
        
        # Level 3 tracking (Timeline / Active Use logging)
        self.incident_id = None
        self.incident_start_time = None
        self.incident_images = []
        self.incident_windows = set()
        self.incident_mouse_activity = False
        
        print("[SecurityMonitor] State Machine Initialized in SAFE state.")

    def _get_db(self):
        """Lazy load Firestore client from firebase_admin."""
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
            if not firebase_admin._apps:
                if os.path.exists("serviceAccountKey.json"):
                    cred = credentials.Certificate("serviceAccountKey.json")
                    firebase_admin.initialize_app(cred)
                else:
                    return None
            return firestore.client()
        except Exception as e:
            print(f"[SecurityMonitor] Failed to get Firestore client: {e}")
            return None

    def _get_storage_bucket(self):
        """Lazy load Firebase Storage bucket."""
        try:
            import firebase_admin
            from firebase_admin import storage
            if not firebase_admin._apps:
                from firebase_admin import credentials
                if os.path.exists("serviceAccountKey.json"):
                    cred = credentials.Certificate("serviceAccountKey.json")
                    firebase_admin.initialize_app(cred)
                else:
                    return None
            
            project_id = "aria-3e1da"
            if self.aria and hasattr(self.aria, 'firebase_sync') and self.aria.firebase_sync:
                project_id = getattr(self.aria.firebase_sync, 'project_id', project_id)
            return storage.bucket(f"{project_id}.firebasestorage.app")
        except Exception as e:
            print(f"[SecurityMonitor] Failed to get Storage bucket: {e}")
            return None

    def process_frame(self, frame, identified_user, similarity, owner_present):
        """
        Call this on every face detection frame.
        Evaluates the security state machine and triggers alerts/transitions.
        """
        # Privacy zone check first
        active_window = self.aria.context_skill.get_active_window() if self.aria else ""
        perception_allowed = True
        if self.aria and hasattr(self.aria, 'sandbox_safety'):
            perception_allowed = self.aria.sandbox_safety.is_perception_allowed(active_window)
            
        if not perception_allowed:
            # If perception is blocked mid-incident, immediately force SAFE state
            if self.state != self.STATE_SAFE:
                print(f"[SecurityMonitor] Privacy Zone activated ('{active_window}'). Transitioning to SAFE.")
                self._transition_to(self.STATE_SAFE)
            return

        now = time.time()
        is_unknown = (identified_user is None and frame is not None)
        
        # Check mouse activity
        mouse_moved = False
        try:
            current_mouse_pos = pyautogui.position()
            if self.last_mouse_pos is not None and current_mouse_pos != self.last_mouse_pos:
                mouse_moved = True
            self.last_mouse_pos = current_mouse_pos
        except Exception:
            pass

        # Check window title activity
        if active_window:
            if self.last_active_window is not None and active_window != self.last_active_window:
                if self.state in [self.STATE_OBSERVING, self.STATE_INTRUSION, self.STATE_ALERTED]:
                    self.incident_windows.add(active_window)
            self.last_active_window = active_window

        # State Machine Logic
        if self.state == self.STATE_SAFE:
            if is_unknown:
                self.unknown_start_time = now
                self.incident_mouse_activity = mouse_moved
                if active_window:
                    self.incident_windows = {active_window}
                else:
                    self.incident_windows = set()
                
                # Check for Level 2 immediate intrusion: unknown face + mouse movement + owner absent
                if mouse_moved and not owner_present:
                    print("[SecurityMonitor] SAFE -> INTRUSION (Immediate: Unknown face + Mouse movement + Owner absent)")
                    self._transition_to(self.STATE_INTRUSION, frame)
                    self._trigger_alert(frame, intrusion_immediate=True)
                    self._transition_to(self.STATE_ALERTED)
                else:
                    print("[SecurityMonitor] SAFE -> OBSERVING (Unknown face detected)")
                    self._transition_to(self.STATE_OBSERVING)

        elif self.state == self.STATE_OBSERVING:
            if not is_unknown:
                print("[SecurityMonitor] OBSERVING -> SAFE (Owner returned or unknown face left)")
                self._transition_to(self.STATE_SAFE)
            else:
                duration = now - self.unknown_start_time
                if mouse_moved:
                    self.incident_mouse_activity = True
                
                # Level 2 check: mouse moved during observation + owner absent
                if mouse_moved and not owner_present:
                    print("[SecurityMonitor] OBSERVING -> INTRUSION (Mouse activity detected while owner absent)")
                    self._transition_to(self.STATE_INTRUSION, frame)
                    self._trigger_alert(frame, intrusion_immediate=True)
                    self._transition_to(self.STATE_ALERTED)
                # Level 1 check: unknown face present > 10 seconds
                elif duration >= 10.0:
                    print(f"[SecurityMonitor] OBSERVING -> INTRUSION (Unknown face present for {duration:.1f}s)")
                    self._transition_to(self.STATE_INTRUSION, frame)
                    self._trigger_alert(frame, intrusion_immediate=False)
                    self._transition_to(self.STATE_ALERTED)

        elif self.state == self.STATE_INTRUSION:
            # Fallback in case of direct state injection
            print("[SecurityMonitor] INTRUSION -> ALERTED (Triggering alerts and uploading snapshots)")
            self._trigger_alert(frame, intrusion_immediate=(not is_unknown or (now - self.unknown_start_time < 10.0)))
            self._transition_to(self.STATE_ALERTED)

        elif self.state == self.STATE_ALERTED:
            # Check if situation cleared (owner returned or face has been absent)
            # If owner returned, transition to SAFE
            if identified_user in ["chinmay", "chinmaya"] and owner_present:
                print("[SecurityMonitor] ALERTED -> SAFE (Owner verified)")
                self._close_incident_log()
                self._transition_to(self.STATE_SAFE)
            elif not is_unknown:
                # If unknown face left for more than 10 seconds, transition back to SAFE
                if not hasattr(self, "_unknown_left_time") or self._unknown_left_time is None:
                    self._unknown_left_time = now
                elif now - self._unknown_left_time > 10.0:
                    print("[SecurityMonitor] ALERTED -> SAFE (Unknown face has left)")
                    self._close_incident_log()
                    self._transition_to(self.STATE_SAFE)
            else:
                self._unknown_left_time = None
                # Continue logging active use (Level 3)
                if mouse_moved:
                    self.incident_mouse_activity = True
                # Periodic snapshot during intrusion (every 10s)
                if now - self.last_alert_time > 10.0:
                    self._save_incident_frame(frame)
                    self.last_alert_time = now

    def _transition_to(self, new_state, frame=None):
        self.state = new_state
        if new_state == self.STATE_SAFE:
            self.unknown_start_time = None
            self.incident_id = None
            self.incident_start_time = None
            self.incident_images = []
            self.incident_windows = set()
            self.incident_mouse_activity = False
            self._unknown_left_time = None
        elif new_state == self.STATE_OBSERVING:
            pass
        elif new_state == self.STATE_INTRUSION:
            self.incident_id = f"inc_{int(time.time())}"
            self.incident_start_time = datetime.datetime.now().isoformat()
            if frame is not None:
                self._save_incident_frame(frame)
        elif new_state == self.STATE_ALERTED:
            self.last_alert_time = time.time()

    def _save_incident_frame(self, frame, prefix="face"):
        """Save a frame to Firebase Storage and add to incident images."""
        bucket = self._get_storage_bucket()
        if not bucket or frame is None:
            return None
        try:
            timestamp = int(time.time() * 1000)
            filename = f"security_incidents/{self.incident_id}/{prefix}_{timestamp}.jpg"
            
            # Encode frame to JPEG
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            img_bytes = buffer.tobytes()
            
            blob = bucket.blob(filename)
            blob.upload_from_string(img_bytes, content_type='image/jpeg')
            
            # Make readable
            try:
                blob.make_public()
                download_url = blob.public_url
            except Exception:
                try:
                    download_url = blob.generate_signed_url(expiration=datetime.timedelta(days=7))
                except Exception:
                    download_url = blob.public_url
                    
            self.incident_images.append(download_url)
            print(f"[SecurityMonitor] Saved incident image: {filename}")
            return download_url
        except Exception as e:
            print(f"[SecurityMonitor] Failed to upload incident image: {e}")
            return None

    def _capture_and_save_screenshot(self):
        """Take a desktop screenshot and upload to incident directory."""
        bucket = self._get_storage_bucket()
        if not bucket:
            return None
        try:
            timestamp = int(time.time() * 1000)
            filename = f"security_incidents/{self.incident_id}/screenshot_{timestamp}.jpg"
            
            screenshot = pyautogui.screenshot()
            # Compress to keep size low
            screenshot = screenshot.resize((1024, 576))
            buf = io.BytesIO()
            screenshot.save(buf, format='JPEG', quality=70)
            img_bytes = buf.getvalue()
            
            blob = bucket.blob(filename)
            blob.upload_from_string(img_bytes, content_type='image/jpeg')
            
            try:
                blob.make_public()
                download_url = blob.public_url
            except Exception:
                try:
                    download_url = blob.generate_signed_url(expiration=datetime.timedelta(days=7))
                except Exception:
                    download_url = blob.public_url
            
            self.incident_images.append(download_url)
            print(f"[SecurityMonitor] Saved incident screenshot: {filename}")
            return download_url
        except Exception as e:
            print(f"[SecurityMonitor] Failed to upload incident screenshot: {e}")
            return None

    def _trigger_alert(self, frame, intrusion_immediate=False):
        """Log the incident to Firestore and push an FCM notification."""
        db = self._get_db()
        if not db:
            print("[SecurityMonitor] No Firestore DB. Cannot store incident/send alert.")
            return

        # Upload desktop screenshot alongside face snapshot
        face_url = self.incident_images[0] if self.incident_images else self._save_incident_frame(frame)
        ss_url = self._capture_and_save_screenshot()

        # Get FCM token from Firestore
        token = self._get_fcm_token()
        if not token:
            print("[SecurityMonitor] No FCM registration token found in Firestore.")
            return

        # Construct payload
        title = "🚨 Possible Unauthorized Access" if intrusion_immediate else "👤 Unknown Person Detected"
        body = "Mouse activity detected while owner is absent." if intrusion_immediate else "Someone has been in front of your PC for 10 seconds."
        
        # Send via FCM
        try:
            from firebase_admin import messaging
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body
                ),
                data={
                    "open_security": "true",
                    "security_image_url": face_url or ss_url or "",
                    "incident_id": str(self.incident_id),
                    "immediate": "true" if intrusion_immediate else "false"
                },
                token=token
            )
            messaging.send(message)
            print(f"[SecurityMonitor] Push notification sent successfully to token: {token[:15]}...")
        except Exception as e:
            print(f"[SecurityMonitor] FCM send failed: {e}")

        # Initial write to security_incidents collection
        try:
            db.collection("security_incidents").document(self.incident_id).set({
                "incident_id": self.incident_id,
                "timestamp": self.incident_start_time,
                "images": self.incident_images,
                "windows_opened": list(self.incident_windows),
                "mouse_activity": self.incident_mouse_activity,
                "resolved": False,
                "type": "unauthorized_access" if intrusion_immediate else "unknown_face"
            })
            print(f"[SecurityMonitor] Logged incident {self.incident_id} to Firestore.")
        except Exception as e:
            print(f"[SecurityMonitor] Failed to write incident to Firestore: {e}")

    def _close_incident_log(self):
        """Update the final metadata.json / Firestore entry at the end of the incident."""
        db = self._get_db()
        if not db or not self.incident_id:
            return
        try:
            duration = int(time.time() - self.unknown_start_time) if self.unknown_start_time else 0
            db.collection("security_incidents").document(self.incident_id).update({
                "resolved": True,
                "resolved_at": datetime.datetime.now().isoformat(),
                "duration_seconds": duration,
                "images": self.incident_images,
                "windows_opened": list(self.incident_windows),
                "mouse_activity": self.incident_mouse_activity
            })
            print(f"[SecurityMonitor] Closed incident log {self.incident_id}. Duration: {duration}s")
            
            # Level 3: Upload metadata.json to Storage directory as requested
            bucket = self._get_storage_bucket()
            if bucket:
                metadata = {
                    "incident_id": self.incident_id,
                    "timestamp": self.incident_start_time,
                    "duration_seconds": duration,
                    "images": self.incident_images,
                    "windows_opened": list(self.incident_windows),
                    "mouse_activity": self.incident_mouse_activity
                }
                blob = bucket.blob(f"security_incidents/{self.incident_id}/metadata.json")
                blob.upload_from_string(
                    data=json.dumps(metadata, indent=2),
                    content_type='application/json'
                )
        except Exception as e:
            print(f"[SecurityMonitor] Failed to close incident log: {e}")

    def _get_fcm_token(self):
        """Fetch FCM registration token from Firestore."""
        db = self._get_db()
        if not db:
            return None
        try:
            doc = db.collection("aria_config").document("fcm").get()
            if doc.exists:
                return doc.to_dict().get("token")
        except Exception as e:
            print(f"[SecurityMonitor] Failed to retrieve FCM token: {e}")
        return None

    def handle_remote_check_in(self):
        """
        Level 5: Triggered by remote phone command.
        Captures webcam, desktop, uploads both, updates status with URLs, and pushes notification.
        """
        # Privacy zone check
        active_window = self.aria.context_skill.get_active_window() if self.aria else ""
        if self.aria and hasattr(self.aria, 'sandbox_safety'):
            if not self.aria.sandbox_safety.is_perception_allowed(active_window):
                msg = f"Check-in blocked: Privacy Zone active (Window: '{active_window}')."
                print(f"[SecurityMonitor] {msg}")
                if self.aria and hasattr(self.aria, 'firebase_sync') and self.aria.firebase_sync:
                    self.aria.firebase_sync.update_status(msg, status_str="idle")
                return

        print("[SecurityMonitor] Handling Remote Live Check-in Request...")
        
        # Capture raw frame if camera is available
        frame = None
        if self.aria and hasattr(self.aria, 'camera') and self.aria.camera.available:
            frame = self.aria.camera.capture_frame_raw()
            
        bucket = self._get_storage_bucket()
        db = self._get_db()
        if not bucket or not db:
            print("[SecurityMonitor] Storage or DB not available for Check-in.")
            return

        checkin_id = f"checkin_{int(time.time())}"
        face_url = ""
        ss_url = ""

        try:
            # 1. Upload webcam frame
            if frame is not None:
                filename = f"security_checkins/{checkin_id}/face.jpg"
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                img_bytes = buffer.tobytes()
                blob = bucket.blob(filename)
                blob.upload_from_string(img_bytes, content_type='image/jpeg')
                try:
                    blob.make_public()
                    face_url = blob.public_url
                except Exception:
                    try:
                        face_url = blob.generate_signed_url(expiration=datetime.timedelta(days=7))
                    except Exception:
                        face_url = blob.public_url

            # 2. Upload desktop screenshot
            try:
                filename = f"security_checkins/{checkin_id}/screenshot.jpg"
                screenshot = pyautogui.screenshot()
                screenshot = screenshot.resize((1024, 576))
                buf = io.BytesIO()
                screenshot.save(buf, format='JPEG', quality=70)
                img_bytes = buf.getvalue()
                blob = bucket.blob(filename)
                blob.upload_from_string(img_bytes, content_type='image/jpeg')
                try:
                    blob.make_public()
                    ss_url = blob.public_url
                except Exception:
                    try:
                        ss_url = blob.generate_signed_url(expiration=datetime.timedelta(days=7))
                    except Exception:
                        ss_url = blob.public_url
            except Exception as e:
                print(f"[SecurityMonitor] Check-in screenshot failed: {e}")

            # 3. Log check-in to Firestore
            db.collection("security_checkins").document(checkin_id).set({
                "checkin_id": checkin_id,
                "timestamp": datetime.datetime.now().isoformat(),
                "face_url": face_url,
                "screenshot_url": ss_url
            })

            # 4. Push FCM notification to phone
            token = self._get_fcm_token()
            if token:
                from firebase_admin import messaging
                message = messaging.Message(
                    notification=messaging.Notification(
                        title="📱 Live Check-in Complete",
                        body="View current desktop screenshot and camera feed."
                    ),
                    data={
                        "open_security": "true",
                        "security_image_url": face_url or ss_url or "",
                        "checkin_id": checkin_id
                    },
                    token=token
                )
                messaging.send(message)
                print(f"[SecurityMonitor] Check-in FCM sent.")

            # Update status in firebase_sync
            if self.aria and hasattr(self.aria, 'firebase_sync') and self.aria.firebase_sync:
                self.aria.firebase_sync.update_status(
                    f"Check-in complete: Camera={bool(face_url)}, Screen={bool(ss_url)}", 
                    status_str="idle"
                )
        except Exception as e:
            print(f"[SecurityMonitor] Check-in failed: {e}")
