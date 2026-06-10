import time
import json
import threading
from typing import Dict, Any

from skills.base_agent import BaseAgent
from skills.blackboard import AriaBlackboard

try:
    import cv2
    from ultralytics import YOLO
except ImportError:
    cv2 = None
    YOLO = None

try:
    import mediapipe as mp
    import mediapipe.solutions.pose
    import mediapipe.solutions.hands
    import mediapipe.solutions.face_detection
except ImportError:
    mp = None

class AriaVisionAgent(BaseAgent):
    def __init__(self, aria_instance=None):
        super().__init__("VisionAgent", aria_instance)
        self.blackboard = AriaBlackboard()
        self.model = None
        
        self.pose_model = None
        self.hands_model = None
        self.face_model = None
        
        self._initialize_local_model()
        self._initialize_mediapipe()
        
        # Background continuous monitoring thread
        self._running = False
        self._thread = None
        self._start_continuous_monitoring()

    @property
    def aria_inst(self):
        if self.aria is None:
            try:
                from skills.agent_orchestrator import AriaMultiAgentOrchestrator
                self.aria = AriaMultiAgentOrchestrator().aria
            except Exception:
                pass
        return self.aria

    def _initialize_local_model(self):
        """Loads the pre-trained YOLOv8 nano weights file locally."""
        if YOLO is not None:
            try:
                # yolov8n.pt is already present in the project root folder
                self.model = YOLO("yolov8n.pt")
                print("[VisionAgent] Pre-trained YOLOv8n model initialized successfully.")
            except Exception as e:
                print(f"[VisionAgent] YOLOv8n model failed to initialize: {e}")

    def _initialize_mediapipe(self):
        """Loads MediaPipe models for pose, hand, and face tracking."""
        if mp is not None:
            try:
                self.pose_model = mp.solutions.pose.Pose(min_detection_confidence=0.5, model_complexity=0)
                self.hands_model = mp.solutions.hands.Hands(min_detection_confidence=0.5, max_num_hands=4)
                self.face_model = mp.solutions.face_detection.FaceDetection(min_detection_confidence=0.5)
                print("[VisionAgent] MediaPipe solutions initialized successfully.")
            except Exception as e:
                print(f"[VisionAgent] MediaPipe failed to initialize: {e}")

    def _start_continuous_monitoring(self):
        if self.model is not None and cv2 is not None:
            self._running = True
            self._thread = threading.Thread(target=self._continuous_loop, name="VisionAgentBackground", daemon=True)
            self._thread.start()
            print("[VisionAgent] Continuous room monitoring active (5s tick).")

    def stop(self):
        self._running = False
        if self._thread:
            try:
                self._thread.join(timeout=1.0)
            except Exception:
                pass
            print("[VisionAgent] Continuous room monitoring stopped.")

    def _run_detection(self, frame_bgr, source="webcam") -> dict:
        """Runs YOLOv8n and MediaPipe models on the given BGR frame."""
        if frame_bgr is None:
            return {}

        # 1. Run YOLOv8n
        detected_objects = []
        confidences = {}
        bounding_boxes = []
        yolo_people_count = 0

        if self.model is not None:
            try:
                results = self.model(frame_bgr, conf=0.60, verbose=False)[0]
                for box in results.boxes:
                    class_id = int(box.cls[0])
                    label = results.names[class_id]
                    conf = float(box.conf[0])
                    
                    if conf >= 0.60:
                        x1, y1, x2, y2 = box.xyxy[0]
                        x = int(x1)
                        y = int(y1)
                        w = int(x2 - x1)
                        h = int(y2 - y1)
                        
                        detected_objects.append(label)
                        confidences[label] = round(conf, 2)
                        bounding_boxes.append({
                            "label": label,
                            "confidence": round(conf, 2),
                            "x": x,
                            "y": y,
                            "w": w,
                            "h": h
                        })
                        if label == "person":
                            yolo_people_count += 1
            except Exception as e:
                print(f"[VisionAgent] YOLO detection error: {e}")

        # Convert to RGB for MediaPipe
        rgb_frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w = frame_bgr.shape[:2]

        # 2. Run MediaPipe Pose
        pose_detected = "none"
        pose_count = 0
        if self.pose_model is not None:
            try:
                pose_res = self.pose_model.process(rgb_frame)
                if pose_res.pose_landmarks:
                    pose_count = 1
                    lms = pose_res.pose_landmarks.landmark
                    # Heuristic for posture
                    try:
                        hip_y = float((lms[23].y + lms[24].y) / 2)
                        knee_y = float((lms[25].y + lms[26].y) / 2)
                        shoulder_y = float((lms[11].y + lms[12].y) / 2)
                        
                        # Extract visibility with type check
                        vis25 = getattr(lms[25], "visibility", 0.0)
                        vis26 = getattr(lms[26], "visibility", 0.0)
                        try:
                            vis25 = float(vis25)
                            vis26 = float(vis26)
                        except (ValueError, TypeError):
                            vis25 = 0.0
                            vis26 = 0.0

                        if vis25 > 0.5 and vis26 > 0.5:
                            hip_to_knee = abs(knee_y - hip_y)
                            shoulder_to_hip = abs(hip_y - shoulder_y)
                            if hip_to_knee < 0.5 * shoulder_to_hip:
                                pose_detected = "sitting"
                            else:
                                pose_detected = "standing"
                        else:
                            pose_detected = "detected"
                    except (ValueError, TypeError, AttributeError):
                        pose_detected = "detected"
            except Exception as e:
                print(f"[VisionAgent] MediaPipe Pose error: {e}")

        # 3. Run MediaPipe Hands
        hand_count = 0
        if self.hands_model is not None:
            try:
                hands_res = self.hands_model.process(rgb_frame)
                if hands_res.multi_hand_landmarks:
                    hand_count = len(hands_res.multi_hand_landmarks)
            except Exception as e:
                print(f"[VisionAgent] MediaPipe Hands error: {e}")

        # 4. Run MediaPipe Face
        face_count = 0
        recognized_people = []
        if self.face_model is not None:
            try:
                face_res = self.face_model.process(rgb_frame)
                if face_res.detections:
                    face_count = len(face_res.detections)
                    
                # Run Face Recognition (Person Memory) if faces are present
                if face_count > 0:
                    try:
                        from skills.face_embedder_tf import AriaFaceEmbedderTF
                        from skills.face_memory_store import AriaFaceMemoryStore
                        if not hasattr(self, "_face_embedder_tf") or self._face_embedder_tf is None:
                            self._face_embedder_tf = AriaFaceEmbedderTF()
                        if not hasattr(self, "_face_store") or self._face_store is None:
                            self._face_store = AriaFaceMemoryStore()
                        
                        emb = self._face_embedder_tf.get_embedding(frame_bgr, is_already_cropped=False)
                        if emb is not None:
                            match_res = self._face_store.search_face(emb, threshold=0.60)
                            name = match_res["name"]
                            confidence = match_res["confidence"]
                            if name != "Unknown":
                                recognized_people.append(name)
                                print(f"[VisionAgent] Recognized registered face: {name} (conf: {confidence:.2f})")
                                
                                # Run P5 Adaptive Person Memory check
                                try:
                                    from skills.adaptive_person_memory import AriaAdaptivePersonMemory
                                    if not hasattr(self, "_adaptive_memory") or self._adaptive_memory is None:
                                        self._adaptive_memory = AriaAdaptivePersonMemory(face_store_instance=self._face_store)
                                    
                                    face_roi = self._face_embedder_tf.extract_face_crop(frame_bgr, is_already_cropped=False)
                                    if face_roi is not None:
                                        learn_res = self._adaptive_memory.evaluate_and_learn_face(name, emb, face_roi, confidence)
                                        if "LEARNING_SUCCESS" in learn_res["status"]:
                                            print(f"[VisionAgent] ADAPTIVE: Learned new face angle for '{name}' successfully.")
                                except Exception as ae:
                                    print(f"[VisionAgent] Adaptive learning trigger error: {ae}")
                    except Exception as fe:
                        print(f"[VisionAgent] Face embedding/search failed: {fe}")
            except Exception as e:
                print(f"[VisionAgent] MediaPipe Face error: {e}")

        # Combine people counts
        people_count = max(face_count, pose_count, yolo_people_count)

        # 5. Check for Student ID Card (KIIT Card OCR Rule detection)
        id_card_details = None
        try:
            from skills.id_card_detector import AriaIDCardDetector
            if not hasattr(self, "_id_detector") or self._id_detector is None:
                self._id_detector = AriaIDCardDetector()
            id_res = self._id_detector.detect_id_card(frame_bgr)
            if id_res.get("is_id_card", False):
                id_card_details = {
                    "roll_number": id_res.get("roll_number"),
                    "extracted_name": id_res.get("extracted_name"),
                    "confidence": id_res.get("confidence")
                }
                print(f"[VisionAgent] Student ID Card detected! Roll: {id_card_details['roll_number']}")
        except Exception as e:
            print(f"[VisionAgent] ID Card detection error: {e}")

        # 6. Resolve room name from scene memory if available
        room_name = "unknown"
        aria = self.aria_inst
        if aria and getattr(aria, "memory_manager", None):
            mem = aria.memory_manager
            if getattr(mem, "scene_mem", None):
                try:
                    res = mem.scene_mem.recognize_scene(detected_objects)
                    if isinstance(res, tuple) and len(res) >= 1:
                        room_id = res[0]
                        if room_id:
                            room_name = room_id
                except Exception as e:
                    print(f"[VisionAgent] Scene recognition failed: {e}")

        timestamp = int(time.time())

        # Construct payload
        report = {
            "vision_people": people_count,
            "vision_people_names": recognized_people,
            "vision_objects": list(set(detected_objects)),
            "vision_faces": face_count,
            "vision_hands": hand_count,
            "vision_pose_detected": pose_detected,
            "confidences": confidences,
            "bounding_boxes": bounding_boxes,
            "observed_at": timestamp,
            "source": source,
            "room_name": room_name,
            "id_card_details": id_card_details
        }
        return report

    def _continuous_loop(self):
        while self._running:
            try:
                camera = None
                aria = self.aria_inst
                if aria and getattr(aria, "camera", None):
                    camera = aria.camera
                
                frame = None
                if camera and camera.available:
                    frame = camera.capture_frame_raw()

                if frame is not None:
                    report = self._run_detection(frame, source="webcam")
                    if report:
                        # Publish latest room_state
                        self.blackboard.publish(
                            topic="VISION",
                            key="room_state",
                            value=report,
                            source=self.agent_name,
                            ttl_hours=30.0 / 3600.0  # 30 seconds
                        )
                        # Publish latest room_state_latest
                        self.blackboard.publish(
                            topic="VISION",
                            key="room_state_latest",
                            value=report,
                            source=self.agent_name,
                            ttl_hours=30.0 / 3600.0
                        )
                        # Update room_state_history
                        self._update_blackboard_history(report)

                        # Trigger VisionMemoryAgent Difference Engine check
                        try:
                            from skills.agent_registry import registry
                            mem_agent = registry.get("visionmemoryagent")
                            if mem_agent:
                                mem_agent.run(
                                    task_id=f"AUTO_MEM_{report['observed_at']}",
                                    task_description="Continuous visual memory sweep",
                                    payload={
                                        "current_objects": report["vision_objects"],
                                        "confidences": report["confidences"],
                                        "current_people": report.get("vision_people_names", [])
                                    }
                                )
                        except Exception as ex:
                            print(f"[VisionAgent] Failed to trigger VisionMemoryAgent: {ex}")
            except Exception as e:
                # Keep loop quiet
                pass
            time.sleep(5.0)

    def _update_blackboard_history(self, report: dict):
        try:
            history = self.blackboard.read(topic="VISION", key="room_state_history")
            if not isinstance(history, list):
                history = []
            
            history.append({
                "timestamp": report["observed_at"],
                "objects": report["vision_objects"],
                "people": report["vision_people"],
                "faces": report["vision_faces"],
                "hands": report["vision_hands"]
            })
            history = history[-20:]
            self.blackboard.publish(
                topic="VISION",
                key="room_state_history",
                value=history,
                source=self.agent_name,
                ttl_hours=24
            )
        except Exception as e:
            print(f"[VisionAgent] Error updating blackboard history: {e}")

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        self.log_state_shift("RUNNING", "Analyzing environment scene...")

        if cv2 is None or self.model is None:
            self.log_state_shift("IDLE", "Aborted. OpenCV or YOLO libraries are missing.")
            return json.dumps({"error": "MISSING_DEPENDENCIES"})

        use_screenshot = payload.get("screenshot", False)
        target = payload.get("target", "")
        if isinstance(target, str) and ("screenshot" in target.lower() or "screen" in target.lower()):
            use_screenshot = True
        if "screenshot" in task_description.lower() or "screen" in task_description.lower():
            use_screenshot = True

        if use_screenshot:
            # Screenshot mode
            from vision import Vision
            vis = Vision()
            pil_img = vis.capture_screen()
            if pil_img is None:
                self.log_state_shift("IDLE", "Aborted. Screen capture returned None.")
                return json.dumps({"error": "SCREEN_CAPTURE_FAILED"})

            # Convert PIL image to BGR numpy array for YOLO
            import numpy as np
            frame_rgb = np.array(pil_img)
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

            # Run detection
            report = self._run_detection(frame_bgr, source="screenshot")

            # Extract text via OCR with confidence
            from skills.ocr_reader import OCRReader
            ocr_res = OCRReader().extract_text_with_confidence(pil_img)
            report["ocr_text"] = ocr_res.get("text", "")
            report["ocr_confidence"] = ocr_res.get("confidence", 0.0)

            # Publish to blackboard topic='VISION', key='screen_state'
            self.blackboard.publish(
                topic="VISION",
                key="screen_state",
                value=report,
                source=self.agent_name,
                ttl_hours=30.0 / 3600.0
            )

            # Gemini Vision escalation check
            if payload.get("deep_reasoning_requested", False) or "describe" in task_description.lower():
                return self._execute_gemini_vision_escalation(frame_bgr, report)

            self.log_state_shift("IDLE", f"Screen frame indexed: Found {len(report['vision_objects'])} items.")
            return json.dumps(report)

        else:
            # Webcam mode
            camera = getattr(self.aria_inst, "camera", None)
            frame_bgr = None
            if camera:
                if not camera.available:
                    camera.reacquire()
                if camera.available:
                    frame_bgr = camera.capture_frame_raw()

            # Fallback to local VideoCapture(0) if camera object unavailable
            if frame_bgr is None:
                print("[VisionAgent] Webcam singleton unavailable or returned None, attempting fallback...")
                cap = cv2.VideoCapture(0)
                if cap.isOpened():
                    ret, frame_bgr = cap.read()
                    cap.release()

            if frame_bgr is None:
                self.log_state_shift("IDLE", "Aborted. Webcam is unavailable.")
                return json.dumps({"error": "CAMERA_UNAVAILABLE"})

            report = self._run_detection(frame_bgr, source="webcam")

            # Publish to blackboard topic='VISION', key='room_state'
            self.blackboard.publish(
                topic="VISION",
                key="room_state",
                value=report,
                source=self.agent_name,
                ttl_hours=30.0 / 3600.0
            )
            # Publish to blackboard topic='VISION', key='room_state_latest'
            self.blackboard.publish(
                topic="VISION",
                key="room_state_latest",
                value=report,
                source=self.agent_name,
                ttl_hours=30.0 / 3600.0
            )
            self._update_blackboard_history(report)

            # Gemini Vision escalation check
            if payload.get("deep_reasoning_requested", False) or "describe" in task_description.lower():
                return self._execute_gemini_vision_escalation(frame_bgr, report)

            self.log_state_shift("IDLE", f"Sight frame indexed: Found {len(report['vision_objects'])} items.")
            return json.dumps(report)

    def _execute_gemini_vision_escalation(self, raw_frame, baseline_report: dict) -> str:
        """Calls Gemini Vision to analyze the room layout if deep reasoning is requested."""
        print("[VisionAgent] Escalating scene context to Gemini Vision core...")
        prompt = f"Describe exactly what is happening in the room layout based on this scene profile map matrix: {json.dumps(baseline_report)}"
        aria = self.aria_inst
        if aria and getattr(aria, "brain", None):
            try:
                import cv2
                from PIL import Image
                rgb_frame = cv2.cvtColor(raw_frame, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(rgb_frame)
                
                extended_description = aria.brain.think(prompt, image=pil_image)
                self.log_state_shift("IDLE", "Gemini Vision escalation completed.")
                return extended_description
            except Exception as e:
                return f"Cloud visual reasoning loop faulted: {e}"
        return "Brain or agent offline. Gemini escalation failed."
