"""
skills/identity_commands.py — Extracted Identity execution logic for ARIA
==========================================================================
Organized into sections: Introductions, Enrollment, and Face recognition mode.
Does not import main.py directly.
"""
import time
import cv2
import numpy as np

# -----------------------------------------------------------------------------
# Utility Imports / Fallbacks
# -----------------------------------------------------------------------------
try:
    from gui import set_user
except ImportError:
    def set_user(u): pass

# -----------------------------------------------------------------------------
# Section 1: Face Introductions & Helper Checks
# -----------------------------------------------------------------------------
def check_face_intro_trigger(aria, inp, t):
    idx = inp.find(t)
    prefix = inp[:idx].lower().strip()
    for greeting in ["hello", "hi", "hey aria", "hey", "aria", "ok", "okay"]:
        if prefix.startswith(greeting):
            prefix = prefix[len(greeting):].strip()
        if prefix.endswith(greeting):
            prefix = prefix[:-len(greeting)].strip()
    prefix = prefix.strip(",.?! ")
    
    clause_words = ["where", "what", "who", "how", "why", "when", "while", "if", "that", "because", "since", "although", "there", "here", "know"]
    if not prefix and not any(w in inp.lower().split() for w in clause_words):
        return t
    return None


def check_this_is_face(aria, inp):
    ar_terms = ["ar mode", "ar playground", "air mode", "air playground", "piano mode", "wand mode", "pet mode", "flower mode", "garden mode"]
    if not any(term in inp.lower() for term in ar_terms):
        raw_suffix = inp.split("this is ", 1)[1].strip()
        if any(raw_suffix.lower().startswith(w) for w in ["a ", "an ", "the "]):
            return False
        return True
    return False


# -----------------------------------------------------------------------------
# Section 2: Face Enrollment Logic
# -----------------------------------------------------------------------------
def enroll_face(aria, inp, face_trigger_found, user_input):
    new_name = ""
    if face_trigger_found == "this is me":
        new_name = aria.known_user.title() if (aria.known_user and aria.known_user != "Guest") else "User"
    else:
        raw_input = inp.split(face_trigger_found, 1)[1].strip()
        cleaned = True
        while cleaned:
            cleaned = False
            for clean_word in ["a ", "an ", "the ", "me ", "i am ", "i'm ", "im ", "my name is ", "called ", "named ", "holding "]:
                if raw_input.lower().startswith(clean_word):
                    raw_input = raw_input[len(clean_word):].strip()
                    cleaned = True
        
        stop_phrases = [" which", " that", ". ", "!", "?", " holding", " and", " is ", " for "]
        obj_name = raw_input
        for stop in stop_phrases:
            if stop in obj_name:
                obj_name = obj_name.split(stop)[0].strip()
        new_name = obj_name.title()

    words = new_name.split()
    invalid_verbs = ["saying", "telling", "asking", "talking", "showing", "looking", "trying", "searching", "sorry", "not", "just", "sure", "going", "doing", "thinking", "having", "getting", "sitting", "working", "standing", "reading", "writing"]
    if not new_name or len(words) > 3 or (len(words) > 0 and words[0].lower() in invalid_verbs):
        return "invalid_name_" + new_name

    if not aria.vision_learner.running:
        if getattr(aria, "airtouch_mode", False):
            aria._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
            return "enroll_aborted_airtouch_active"
        if not aria.camera or not aria.camera.available:
            aria.camera.reacquire()
        aria._speak("Let me open my camera to look.")
        aria.vision_learner.mode = "both"
        aria.vision_learner.start_camera(frame_provider=aria.camera.capture_frame_raw)
        for _ in range(30):
            time.sleep(0.1)
            with aria.vision_learner._lock:
                if aria.vision_learner.current_frame is not None: break

    with aria.vision_learner._lock:
        frame = aria.vision_learner.current_frame.copy() if aria.vision_learner.current_frame is not None else None
    
    if frame is None:
        aria._speak("I can't see anything. Please make sure the camera is working.")
        return "enroll_failed_no_camera_frame"

    if not hasattr(frame, "shape") or len(frame.shape) < 2:
        aria._speak("I can't see anything clearly. Please look straight at the camera and try again.")
        return "enroll_failed_corrupted_frame"
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    faces = []
    if w >= 30 and h >= 30:
        try:
            faces = aria.memory.face_cascade.detectMultiScale(gray, 1.3, 5)
        except Exception as e:
            print(f"[Main] Face detection error: {e}")
    
    if len(faces) > 0:
        aria._speak(f"I see a face. Let's enroll you, {new_name}. Please stay still and look straight at the camera.")
        aria._wait_for_speech()
        
        embeddings = []
        def capture_and_embed():
            with aria.vision_learner._lock:
                f = aria.vision_learner.current_frame.copy() if aria.vision_learner.current_frame is not None else None
            if f is not None and hasattr(f, "shape") and len(f.shape) >= 2:
                fh, fw = f.shape[:2]
                if fw >= 40 and fh >= 40:
                    try:
                        emb = aria.memory.memory_manager.embedder.get_embedding(f)
                        if emb:
                            embeddings.append(emb)
                    except Exception as e:
                        print(f"[Main] Embedding capture error: {e}")

        time.sleep(0.5)
        for _ in range(3):
            capture_and_embed()
            time.sleep(0.1)
        
        aria._speak("Now turn your head slightly to the left.")
        aria._wait_for_speech()
        time.sleep(1.0)
        for _ in range(3):
            capture_and_embed()
            time.sleep(0.1)
        
        aria._speak("Great. Now turn your head slightly to the right.")
        aria._wait_for_speech()
        time.sleep(1.0)
        for _ in range(3):
            capture_and_embed()
            time.sleep(0.1)

        aria._speak("Now tilt your head slightly up and down.")
        aria._wait_for_speech()
        time.sleep(1.0)
        for _ in range(3):
            capture_and_embed()
            time.sleep(0.1)

        if len(embeddings) >= 4:
            avg_emb = np.mean(embeddings, axis=0)
            norm = np.linalg.norm(avg_emb)
            if norm > 0:
                avg_emb = avg_emb / norm
            
            if aria.memory.add_face(new_name, embedding=avg_emb.tolist()):
                aria.known_user = new_name
                set_user(new_name)
                aria.face_match_history = []
                aria.known_user_confidence = "high"
                aria.last_identity_match_time = time.time()
                aria._speak(f"Enrollment complete! I've successfully saved a multi-angle representation of your face, {new_name}.")
                return "enrolled_face_" + new_name
            else:
                aria._speak("Something went wrong while saving your face embeddings. Please try again.")
                return "enroll_failed_db_error"
        else:
            aria._speak("I couldn't capture enough clear angles of your face. Please ensure you are well-lit and try again.")
            return "enroll_failed_insufficient_angles"
    else:
        aria._speak("I don't see a face to enroll. Please look straight at the camera and try again.")
        return "enroll_failed_no_face_detected"


# -----------------------------------------------------------------------------
# Section 3: Face Recognition & Camera Mode
# -----------------------------------------------------------------------------
def face_mode(aria, inp, user_input, image=None):
    from skills.command_patterns import FACE_ID_TRIGGERS
    aria.vision_learner.mode = "face"
    if not aria.vision_learner.running:
        if getattr(aria, "airtouch_mode", False):
            aria._speak("The camera is currently released for AirTouch. Please disable AirTouch first.")
            return "face_mode_aborted_airtouch_active"
        if not aria.camera or not aria.camera.available:
            aria.camera.reacquire()
        aria.vision_learner.start_camera(frame_provider=aria.camera.capture_frame_raw)
        for _ in range(30):
            time.sleep(0.1)
            with aria.vision_learner._lock:
                if aria.vision_learner.current_frame is not None:
                    break

    is_query = any(x in inp for x in FACE_ID_TRIGGERS)
    if is_query:
        with aria.vision_learner._lock:
            frame = aria.vision_learner.current_frame.copy() if aria.vision_learner.current_frame is not None else None
        
        if frame is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = aria.memory.detect_faces(gray, scale_factor=1.3, min_neighbors=5)
            if len(faces) > 0:
                fx, fy, fw, fh = faces[0]
                face_crop = frame[fy:fy+fh, fx:fx+fw]
                name = aria.memory.identify_face(face_crop)
                if name and name != "Unknown":
                    aria._speak(f"I can see {name} in the room.")
                    return "identified_face_" + name
                else:
                    aria._speak("I see a face in the room, but I don't recognize them.")
                    return "identified_face_unknown"
            else:
                aria._speak("I don't see any faces in the room right now.")
                return "no_faces_detected"
        else:
            aria._speak("I couldn't access the camera to check.")
            return "query_failed_no_camera_frame"

    aria._speak("Switching to Person Mode. I will now help you recognize faces.")
    return "activated_person_mode"
