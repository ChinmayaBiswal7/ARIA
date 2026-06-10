import time
import json
import threading
from typing import Dict, Any, List, Tuple

# Safe library loading
try:
    import cv2
    import mediapipe as mp
except ImportError:
    cv2 = None
    mp = None

from skills.base_agent import BaseAgent
from skills.blackboard import AriaBlackboard

class AriaGestureAgent(BaseAgent):
    def __init__(self, aria_instance=None):
        super().__init__("GestureAgent", aria_instance)
        self.blackboard = AriaBlackboard()
        self.mp_hands = None
        self.hands_recognizer = None
        
        self._running = False
        self._thread = None
        self._gesture_buffer = []
        self._last_published_gesture = "UNKNOWN"
        self._gesture_history = []
        
        self._init_perception_layer()

    @property
    def aria_inst(self):
        if self.aria is None:
            try:
                from skills.agent_orchestrator import AriaMultiAgentOrchestrator
                self.aria = AriaMultiAgentOrchestrator().aria
            except Exception:
                pass
        return self.aria

    def _init_perception_layer(self):
        """Initializes the MediaPipe localized tracking pipeline."""
        global mp
        if mp is not None:
            try:
                self.mp_hands = mp.solutions.hands
                self.hands_recognizer = self.mp_hands.Hands(
                    static_image_mode=False,
                    max_num_hands=1,
                    min_detection_confidence=0.70,
                    min_tracking_confidence=0.70
                )
                print("[GestureAgent] MediaPipe localized hand landmark tracking layer online.")
            except Exception as e:
                print(f"[GestureAgent] MediaPipe initialization error: {e}")

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        command = payload.get("command", "start").lower().strip()
        if command == "start":
            self.start_monitoring()
            return json.dumps({"status": "SUCCESS", "message": "Gesture monitoring loop started in background."})
        elif command == "stop":
            self.stop_monitoring()
            return json.dumps({"status": "SUCCESS", "message": "Gesture monitoring loop stopped."})
        elif command == "status":
            return json.dumps({"status": "SUCCESS", "is_running": self._running})
        else:
            return json.dumps({"status": "FAILED", "error": f"Unknown command: {command}"})

    def start_monitoring(self):
        """Starts the background loop thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="AriaGestureMonitor")
        self._thread.start()
        print("[GestureAgent] Background monitoring loop started.")

    def stop_monitoring(self):
        """Stops the background loop thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        print("[GestureAgent] Background monitoring loop stopped.")

    def _monitor_loop(self):
        """Continuous monitoring loop: Camera -> MediaPipe -> Gesture Recognition -> Blackboard."""
        while self._running:
            t0 = time.time()
            try:
                aria_ctx = self.aria_inst
                if aria_ctx and hasattr(aria_ctx, "camera") and aria_ctx.camera:
                    # Capture raw BGR frame from the shared camera singleton
                    frame = aria_ctx.camera.capture_frame_raw()
                    if frame is not None:
                        self._process_frame(frame)
            except Exception as e:
                print(f"[GestureAgent] Error in monitor loop step: {e}")
            
            # Sleep to regulate loop rate to ~5-10 Hz (every 100-200ms)
            elapsed = time.time() - t0
            sleep_time = 0.15 - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _process_frame(self, frame):
        """Processes a single BGR frame and extracts gestures."""
        if self.hands_recognizer is None:
            return
            
        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands_recognizer.process(rgb_frame)
        
        detected_gesture = "UNKNOWN"
        confidence = 0.0
        hand = "RIGHT"
        
        if results.multi_hand_landmarks:
            hand_landmarks = results.multi_hand_landmarks[0]
            detected_gesture = self._evaluate_geometric_heuristics(hand_landmarks.landmark)
            if detected_gesture != "UNKNOWN":
                confidence = 0.90  # High confidence for heuristic match
                if results.multi_handedness:
                    # MediaPipe gives classification labels ("Left" / "Right")
                    hand = results.multi_handedness[0].classification[0].label.upper()
            else:
                # Hand is visible but unrecognized by heuristics -> Fallback to TF landmark classifier
                try:
                    from skills.gesture_classifier_tf import AriaGestureClassifierTF
                    if not hasattr(self, "_tf_classifier") or self._tf_classifier is None:
                        self._tf_classifier = AriaGestureClassifierTF()
                    tf_label, tf_conf = self._tf_classifier.predict(hand_landmarks.landmark)
                    if tf_label != "UNKNOWN" and tf_conf >= 0.85:
                        detected_gesture = tf_label
                        confidence = tf_conf
                        if results.multi_handedness:
                            hand = results.multi_handedness[0].classification[0].label.upper()
                        print(f"[GestureAgent] TF Classifier detected custom gesture: {detected_gesture} (conf: {tf_conf:.2f})")
                    else:
                        confidence = 0.50
                except Exception as ex:
                    print(f"[GestureAgent] TF Classifier fallback failed: {ex}")
                    confidence = 0.50
        else:
            # No hand detected -> 100% confidence it is UNKNOWN (used for resetting state)
            detected_gesture = "UNKNOWN"
            confidence = 1.0
            
        # Confidence threshold gating: ignore borderline gesture readings (confidence < 0.80)
        if confidence < 0.80:
            return
            
        # Enqueue to temporal smoothing buffer (require 3 consecutive identical frames)
        self._gesture_buffer.append(detected_gesture)
        if len(self._gesture_buffer) > 3:
            self._gesture_buffer.pop(0)
            
        if len(self._gesture_buffer) == 3 and all(g == detected_gesture for g in self._gesture_buffer):
            # Publish state only if it changed from the last published gesture
            if detected_gesture != self._last_published_gesture:
                gesture_payload = {
                    "gesture": detected_gesture,
                    "confidence": confidence,
                    "hand": hand,
                    "timestamp": int(time.time())
                }
                
                # Publish state to Blackboard
                self.blackboard.publish(
                    topic="vision",
                    key="gesture_state",
                    value=gesture_payload,
                    source=self.agent_name,
                    ttl_hours=1
                )
                
                self._last_published_gesture = detected_gesture
                
                # Add to history
                self._gesture_history.append(gesture_payload)
                if len(self._gesture_history) > 20:
                    self._gesture_history.pop(0)
                    
                # Publish updated history to Blackboard
                self.blackboard.publish(
                    topic="vision",
                    key="gesture_history",
                    value=self._gesture_history,
                    source=self.agent_name,
                    ttl_hours=1
                )
                print(f"[GestureAgent] Smooth gesture detected and published: {detected_gesture} ({hand})")

    def _evaluate_geometric_heuristics(self, landmarks) -> str:
        """Determines gestures deterministically using relative hand joint vectors."""
        try:
            wrist = landmarks[0]
            thumb_tip = landmarks[4]
            thumb_ip = landmarks[3]
            thumb_mcp = landmarks[2]
            
            index_tip = landmarks[8]
            index_pip = landmarks[6]
            index_mcp = landmarks[5]
            
            middle_tip = landmarks[12]
            middle_pip = landmarks[10]
            middle_mcp = landmarks[9]
            
            ring_tip = landmarks[16]
            ring_pip = landmarks[14]
            
            pinky_tip = landmarks[20]
            pinky_pip = landmarks[18]
            
            # Extensions
            index_ext = index_tip.y < index_pip.y
            middle_ext = middle_tip.y < middle_pip.y
            ring_ext = ring_tip.y < ring_pip.y
            pinky_ext = pinky_tip.y < pinky_pip.y
            
            # Check if main four fingers are folded down in palm
            four_folded = (
                index_tip.y > index_pip.y and
                middle_tip.y > middle_pip.y and
                ring_tip.y > ring_pip.y and
                pinky_tip.y > pinky_pip.y
            )
            
            # Thumbs Up: 4 folded, thumb tip pointing UP
            if four_folded and thumb_tip.y < thumb_ip.y and thumb_tip.y < middle_mcp.y:
                return "THUMBS_UP"
                
            # Thumbs Down: 4 folded, thumb tip pointing DOWN
            if four_folded and thumb_tip.y > thumb_ip.y and thumb_tip.y > middle_mcp.y:
                return "THUMBS_DOWN"
                
            # Open Palm: all fingers extended pointing UP
            if index_ext and middle_ext and ring_ext and pinky_ext and thumb_tip.y < thumb_mcp.y:
                return "OPEN_PALM"
                
        except Exception as e:
            print(f"[GestureAgent] Error parsing heuristics: {e}")
            
        return "UNKNOWN"
