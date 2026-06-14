"""
vision_learn.py - Real-time object recognition + learning for ARIA
==================================================================
- Opens an OpenCV camera window with live detection overlay
- Voice command "this is a [name]" -> captures & stores the object
- Voice command "what is this" -> identifies using YOLO + feature matching
- Stores images + metadata persistently in object_store/
"""

import cv2
import os
import json
import time
import threading
import numpy as np
from datetime import datetime


# ── Optional YOLO ─────────────────────────────────────────────────────────────
# We check for availability via find_spec (fast, doesn't load/import the module)
# and only import it inside the background thread to prevent blocking boot.
import importlib.util
_YOLO_AVAILABLE = importlib.util.find_spec("ultralytics") is not None


# ─────────────────────────────────────────────────────────────────────────────
class VisionLearner:
    """
    Real-time object detection + learning using OpenCV.
    Uses YOLOv8 nano if installed, else ORB feature-matching.
    """

    WINDOW  = "ARIA Vision"
    STORE   = "object_store"
    META    = "object_store/objects.json"

    # ─────────────────────────────────────────────────────────
    def __init__(self):
        os.makedirs(self.STORE, exist_ok=True)

        self.cap           = None
        self.running       = False
        self.current_frame = None   # latest raw BGR frame
        self._lock         = threading.Lock()
        self._thread       = None
        self._label_flash  = None   # (text, color, expire_time)

        # ORB for feature matching (no internet needed)
        self.orb     = cv2.ORB_create(nfeatures=600)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

        # YOLO
        self.yolo = None
        if _YOLO_AVAILABLE:
            def _load_yolo():
                try:
                    from ultralytics import YOLO as _YOLO
                    self.yolo = _YOLO("yolov8n.pt")   # auto-downloads ~6 MB on first run
                    print("[Vision] YOLOv8n loaded.")
                except Exception as e:
                    print(f"[Vision] YOLO load failed: {e}")
            threading.Thread(target=_load_yolo, daemon=True).start()
        else:
            print("[Vision] ultralytics not installed — using feature matching only.")
            print("[Vision]  To enable YOLO: pip install ultralytics")


        self.mode = "both" # "object", "face", or "both"
        self.face_mem = None # will be set by ARIA instance
        
        self._load_meta()
        print(f"[Vision] Loaded {len(self.object_meta)} learned object(s). Mode: {self.mode}")

    # ── Metadata ──────────────────────────────────────────────
    def _load_meta(self):
        if os.path.exists(self.META):
            try:
                with open(self.META, "r") as f:
                    self.object_meta = json.load(f)
                return
            except Exception:
                pass
        self.object_meta = {}   # name -> list of image paths

    def _save_meta(self):
        with open(self.META, "w") as f:
            json.dump(self.object_meta, f, indent=2)

    # ── Camera loop ───────────────────────────────────────────
    def start_camera(self, frame_provider=None):
        """Open the OpenCV window and start capturing."""
        if self.running:
            print("[Vision] Camera already running.")
            return True

        if frame_provider is not None:
            self.frame_provider = frame_provider
            self.cap = None
        else:
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                print("[Vision] Cannot open camera.")
                return False

            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS,          30)

            self.cap = cap
            def default_provider():
                ret, frame = cap.read()
                return frame if ret else None
            self.frame_provider = default_provider

        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def _loop(self):
        """Main camera + display loop (runs in background thread)."""
        while self.running:
            frame = self.frame_provider()
            if frame is None:
                time.sleep(0.05)
                continue

            with self._lock:
                self.current_frame = frame.copy()

            display = frame.copy()

            # ── MODE 1: OBJECTS (YOLO + LEARNED) ──────────────────────────
            if self.mode in ["object", "both"]:
                if self.yolo:
                    try:
                        results = self.yolo(frame, verbose=False, conf=0.45)
                        for r in results:
                            for box in r.boxes:
                                x1, y1, x2, y2 = map(int, box.xyxy[0])
                                conf  = float(box.conf[0])
                                cls   = int(box.cls[0])
                                label = r.names[cls]
                                # Draw box
                                cv2.rectangle(display, (x1, y1), (x2, y2), (0, 220, 255), 2)
                                # Label background
                                (tw, th), _ = cv2.getTextSize(f"{label}", cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                                cv2.rectangle(display, (x1, y1 - th - 8), (x1 + tw + 6, y1), (0, 220, 255), -1)
                                cv2.putText(display, f"{label}", (x1 + 3, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
                    except Exception: pass

            # ── MODE 2: FACES (RECOGNITION) ─────────────────────────
            if self.mode in ["face", "both"]:
                if self.face_mem:
                    # Detect faces using Haar Cascades from face_memory
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces = self.face_mem.detect_faces(gray, scale_factor=1.3, min_neighbors=5)
                    for (fx, fy, fw, fh) in faces:
                        # Draw blue box for faces
                        cv2.rectangle(display, (fx, fy), (fx+fw, fy+fh), (255, 150, 50), 2)
                        # Identify
                        name = self.face_mem.identify_face(frame[fy:fy+fh, fx:fx+fw], is_already_cropped=True)
                        # Label
                        (tw, th), _ = cv2.getTextSize(name.upper(), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                        cv2.rectangle(display, (fx, fy - th - 8), (fx + tw + 6, fy), (255, 150, 50), -1)
                        cv2.putText(display, name.upper(), (fx + 3, fy - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            # ── UI overlay ──────────────────────────────────────
            h, w = display.shape[:2]

            # Dark top bar
            overlay = display.copy()
            cv2.rectangle(overlay, (0, 0), (w, 42), (10, 10, 25), -1)
            cv2.addWeighted(overlay, 0.7, display, 0.3, 0, display)

            cv2.putText(display, "ARIA VISION", (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 220, 255), 2)

            mode_txt = f"{self.mode.upper()} MODE"
            color = (0, 220, 255) if self.mode == "object" else (255, 150, 50)
            cv2.putText(display, mode_txt, (w - 140, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            # Bottom bar
            cv2.rectangle(display, (0, h - 38), (w, h), (10, 10, 25), -1)
            hint = "Say 'this is a [name]' to learn  |  'what is this?' to identify  |  Q to close"
            cv2.putText(display, hint, (8, h - 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 160, 180), 1)

            # Flash label (triggered by learn/identify)
            now = time.time()
            if self._label_flash and now < self._label_flash[2]:
                text, color = self._label_flash[0], self._label_flash[1]
                (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
                tx = (w - tw) // 2
                # Semi-transparent background pill
                pad = 12
                cv2.rectangle(display,
                               (tx - pad, h // 2 - th - pad),
                               (tx + tw + pad, h // 2 + pad),
                               (10, 10, 25), -1)
                cv2.putText(display, text, (tx, h // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)

            # Learned count
            n_obj = len(self.object_meta)
            cv2.putText(display, f"Learned: {n_obj}", (10, h - 46),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 200, 100), 1)

            cv2.imshow(self.WINDOW, display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:   # Q or ESC
                break

        self._cleanup()

    def _cleanup(self):
        self.running = False
        if self.cap:
            self.cap.release()
            self.cap = None
        try:
            cv2.destroyWindow(self.WINDOW)
        except Exception:
            pass
        print("[Vision] Camera closed.")

    def stop_camera(self):
        self.running = False

    # ── Flash helper ──────────────────────────────────────────
    def _flash(self, text, color=(0, 220, 255), duration=2.5):
        self._label_flash = (text, color, time.time() + duration)

    # ── Learn ─────────────────────────────────────────────────
    def capture_and_learn(self, name):
        """
        Capture the current frame and save it as a named object.
        Returns (success: bool, message: str)
        """
        with self._lock:
            if self.current_frame is None:
                return False, "Camera is not active. Say 'show camera' first."
            frame = self.current_frame.copy()

        # Save image
        safe  = name.replace(" ", "_").lower()
        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{safe}_{ts}.jpg"
        path  = os.path.join(self.STORE, fname)

        ok = cv2.imwrite(path, frame)
        if not ok:
            return False, f"Could not save image for {name}."

        # Update metadata
        if name not in self.object_meta:
            self.object_meta[name] = []
        self.object_meta[name].append(path)
        # Keep at most 10 samples per object
        if len(self.object_meta[name]) > 10:
            self.object_meta[name] = self.object_meta[name][-10:]
        self._save_meta()

        self._flash(f"LEARNED: {name.upper()}", (50, 255, 100))
        print(f"[Vision] Learned '{name}' -> {path}")
        return True, path

    # ── Identify ──────────────────────────────────────────────
    def identify_object(self):
        """
        Identify what's in the current frame.
        Returns a human-readable string.
        """
        with self._lock:
            if self.current_frame is None:
                return "Camera is not active. Say 'show camera' first."
            frame = self.current_frame.copy()

        results = []

        # ── YOLO first ──────────────────────────────────────
        if self.yolo:
            try:
                yolo_res = self.yolo(frame, verbose=False, conf=0.45)
                for r in yolo_res:
                    for box in r.boxes:
                        conf  = float(box.conf[0])
                        label = r.names[int(box.cls[0])]
                        # Deprioritize 'person' ONLY in object-only mode
                        if self.mode == "object" and label == "person":
                            conf *= 0.5
                        results.append((label, conf, "yolo"))
            except Exception as e:
                print(f"[Vision] YOLO identify error: {e}")

        # ── Feature matching against stored objects ──────────
        if self.object_meta:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            kp, desc = self.orb.detectAndCompute(gray, None)

            if desc is not None:
                best_name  = None
                best_score = 0.0

                for name, paths in self.object_meta.items():
                    scores = []
                    for p in paths[-5:]:   # use last 5 samples
                        if not os.path.exists(p):
                            continue
                        ref = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
                        if ref is None:
                            continue
                        # Match resolution for better feature scale
                        ref = cv2.resize(ref, (frame.shape[1], frame.shape[0]))
                        _, ref_desc = self.orb.detectAndCompute(ref, None)
                        if ref_desc is None or len(ref_desc) < 10:
                            continue
                        matches = self.matcher.match(desc, ref_desc)
                        matches = sorted(matches, key=lambda m: m.distance)[:30]
                        if matches:
                            good = [m for m in matches if m.distance < 60]
                            if good:
                                scores.append(len(good) / (np.mean([m.distance for m in good]) + 1))

                    if scores:
                        avg = np.mean(scores)
                        if avg > best_score:
                            best_score = avg
                            best_name  = name

                if best_name and best_score > 1.2:
                    # 'learned' objects get a MASSIVE boost in confidence
                    results.append((best_name, 0.99, "learned"))

        if not results:
            text = "I don't recognise anything here. Say 'this is a [name]' to teach me."
            self._flash("UNKNOWN", (255, 80, 80))
            return text

        # Sort results: Learned objects always come FIRST now
        results.sort(key=lambda x: (1 if x[2] == "learned" else 0, x[1]), reverse=True)

        # Format response
        top = results[:2] # Just show the top 2
        parts = []
        has_learned = any(r[2] == "learned" for r in top)

        for name, conf, src in top:
            # If we found a learned object, ignore generic 'person' in the speech
            if has_learned and name == "person":
                continue
            
            if src == "learned":
                parts.append(f"the {name} you taught me")
            else:
                parts.append(f"a {name}")

        response = "I can see: " + " and ".join(parts) + "."
        self._flash(top[0][0].upper(), (0, 220, 255))
        return response

    # ── Describe scene ────────────────────────────────────────
    def describe_scene(self):
        """
        Returns a quick YOLO scene description without opening a new window.
        """
        with self._lock:
            if self.current_frame is None:
                return "Camera is not active."
            frame = self.current_frame.copy()

        if not self.yolo:
            return "YOLO is not installed. I can only identify objects I have specifically learned."

        try:
            results = self.yolo(frame, verbose=False, conf=0.4)
            seen = {}
            for r in results:
                for box in r.boxes:
                    label = r.names[int(box.cls[0])]
                    seen[label] = seen.get(label, 0) + 1

            if not seen:
                return "I don't see any recognisable objects right now."

            parts = []
            for label, count in seen.items():
                parts.append(f"{count} {label}" if count > 1 else f"a {label}")
            return "I can see: " + ", ".join(parts) + "."
        except Exception as e:
            return f"Scene description failed: {e}"

    def get_detected_objects(self, conf=0.4):
        """
        Run YOLO on the current frame and return a list of all detected object labels.
        """
        with self._lock:
            if self.current_frame is None:
                return []
            frame = self.current_frame.copy()

        if not self.yolo:
            return []

        try:
            results = self.yolo(frame, verbose=False, conf=conf)
            detected = []
            for r in results:
                for box in r.boxes:
                    label = r.names[int(box.cls[0])]
                    detected.append(label)
            return detected
        except Exception as e:
            print(f"[Vision] get_detected_objects error: {e}")
            return []

    # ── List learned objects ──────────────────────────────────
    def list_learned(self):
        if not self.object_meta:
            return "I haven't learned any objects yet."
        names = list(self.object_meta.keys())
        return "I know: " + ", ".join(names) + f". ({len(names)} total)"

    # ── Forget ────────────────────────────────────────────────
    def forget_object(self, name):
        if name in self.object_meta:
            del self.object_meta[name]
            self._save_meta()
            return True
        return False
