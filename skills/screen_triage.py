import os
import re
import json
import shutil
import subprocess
from skills.active_context import ActiveContext

class TriageResult:
    def __init__(self, error_found=False, error_type=None, confidence=0.0, file_name=None, line_number=None, explanation="", original_code="", corrected_code=""):
        self.error_found = error_found
        self.error_type = error_type
        self.confidence = confidence
        self.file_name = file_name
        self.line_number = line_number
        self.explanation = explanation
        self.original_code = original_code
        self.corrected_code = corrected_code

class AriaScreenTriage:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.pending_fix = None
        self._initialized = True

    def resolve_file_path(self, file_name):
        if not file_name:
            return None
        base_name = os.path.basename(file_name).strip()
        
        # Check active context
        context = ActiveContext()
        if context.active_file and os.path.basename(context.active_file) == base_name:
            if os.path.exists(context.active_file):
                return context.active_file
        
        # Search workspace
        workspace = r"C:\D FOLDER\Projects\AI"
        for root, dirs, files in os.walk(workspace):
            if any(x in root for x in ["aria_env", ".git", "__pycache__"]):
                continue
            if base_name in files:
                path = os.path.join(root, base_name)
                if os.path.exists(path):
                    return path
                    
        # Check parent folder
        parent = r"C:\D FOLDER\Projects"
        for root, dirs, files in os.walk(parent):
            if any(x in root for x in ["aria_env", ".git", "__pycache__"]):
                continue
            if base_name in files:
                path = os.path.join(root, base_name)
                if os.path.exists(path):
                    return path
        return None

    def triage_active_screen(self, aria):
        # Safety/Privacy Check
        active_window = aria.context_skill.get_active_window()
        if not aria.sandbox_safety.is_perception_allowed(active_window):
            print("[Screen Triage] Privacy Zone active. Perception blocked.")
            aria.safe_speak("Webcam or screen perception is currently blocked due to active workspace safety rules.")
            return "Perception blocked."

        print("[Screen Triage] Capturing screen image...")
        os.makedirs("scratch", exist_ok=True)
        temp_path = "scratch/active_screen_frame.png"
        try:
            screenshot = aria.screen.get_screen_image()
            screenshot.save(temp_path)
        except Exception as e:
            print(f"[Screen Triage] Screenshot capture failed: {e}")
            aria.safe_speak("I was unable to capture a screenshot of your screen.")
            return "Capture failed."

        prompt = (
            "Analyze this screenshot of the user's workspace.\n"
            "1. Identify if there is an active compilation error, crash log, terminal stack trace, or code bug visible.\n"
            "2. Extract the exact error message/type, file name, and line number if present.\n"
            "3. Formulate a plain-language explanation of why this error is happening and provide the corrected code patch block.\n\n"
            "You MUST output exactly one JSON object. Do not include any markdown format tags (like ```json). Return raw JSON text only.\n"
            "Format Required:\n"
            "{\n"
            '  "error_found": true/false,\n'
            '  "error_type": "SyntaxError" | "NameError" | etc. or null,\n'
            '  "confidence": score_between_0_and_1_indicating_relevance,\n'
            '  "file_name": "Simple file name containing error, e.g. main.py, or null if not found",\n'
            '  "line_number": integer_line_number_or_null,\n'
            '  "explanation": "Brief explanation...",\n'
            '  "original_code": "Exact line or block of code to be replaced, or null if not found. Must match existing file content exactly.",\n'
            '  "corrected_code": "Corrected drop-in replacement code, or null if not found"\n'
            "}\n"
        )

        try:
            print("[Screen Triage] Querying vision model...")
            response = aria.brain.think(prompt, image=screenshot)
            
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

            if not response:
                aria.safe_speak("I could not get a response from my vision layer.")
                return "Vision error."

            # Parse JSON
            clean = response.strip()
            match = re.search(r"(\{.*\})", clean, re.DOTALL)
            if match:
                clean = match.group(1).strip()
            else:
                for marker in ("```json", "```"):
                    if clean.startswith(marker):
                        clean = clean[len(marker):]
                if clean.endswith("```"):
                    clean = clean[:-3]
                clean = clean.strip()

            data = json.loads(clean)
            triage_res = TriageResult(
                error_found=data.get("error_found", False),
                error_type=data.get("error_type"),
                confidence=float(data.get("confidence", 0.0)),
                file_name=data.get("file_name"),
                line_number=data.get("line_number"),
                explanation=data.get("explanation", ""),
                original_code=data.get("original_code", ""),
                corrected_code=data.get("corrected_code", "")
            )

            # Store last error in ActiveContext
            if triage_res.error_found:
                ActiveContext().last_error = triage_res.explanation

            if not triage_res.error_found:
                aria.safe_speak("I looked at your screen but didn't detect any active compilation or runtime errors.")
                return "No errors."

            # Resolve file path
            resolved_path = self.resolve_file_path(triage_res.file_name)
            if not resolved_path:
                aria.safe_speak(f"I found a code error: {triage_res.explanation}, but I could not locate the file {triage_res.file_name} in the workspace.")
                return "File not resolved."

            print(f"[Screen Triage] Resolved path: {resolved_path}")
            
            # Stage fix details
            self.pending_fix = {
                "file_path": resolved_path,
                "line_number": triage_res.line_number,
                "original_code": triage_res.original_code,
                "corrected_code": triage_res.corrected_code,
                "explanation": triage_res.explanation,
                "confidence": triage_res.confidence,
                "error_type": triage_res.error_type
            }

            if triage_res.confidence > 0.8:
                file_base = os.path.basename(resolved_path)
                msg = (
                    f"I see an error: {triage_res.explanation}. "
                    f"I've generated a fix with {int(triage_res.confidence*100)}% confidence for {file_base}. "
                    f"Would you like me to write this fix to the file?"
                )
                aria.safe_speak(msg)
            else:
                self.pending_fix = None
                aria.safe_speak(f"I found a possible issue: {triage_res.explanation}, but my confidence score is low, sitting at {int(triage_res.confidence*100)} percent. I will not offer to auto-patch it.")

            return "Triage complete."

        except Exception as e:
            print(f"[Screen Triage] Triage execution failed: {e}")
            aria.safe_speak("I had an error during screen triage.")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return "Failed triage."

    def apply_fix(self, aria):
        if not self.pending_fix:
            aria.safe_speak("There is no pending fix to apply.")
            return "No pending fix."

        fix = self.pending_fix
        self.pending_fix = None

        file_path = fix["file_path"]
        orig = fix["original_code"]
        corrected = fix["corrected_code"]
        line_num = fix["line_number"]

        if not os.path.exists(file_path):
            aria.safe_speak("The file to patch no longer exists.")
            return "File missing."

        backup_path = file_path + ".bak"
        try:
            # 1. Create backup
            shutil.copy(file_path, backup_path)

            # 2. Perform patching
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if orig in content:
                new_content = content.replace(orig, corrected, 1)
            else:
                lines = content.splitlines()
                idx = line_num - 1 if line_num else -1
                if 0 <= idx < len(lines):
                    orig_lines = orig.splitlines()
                    if idx + len(orig_lines) <= len(lines):
                        chunk = lines[idx:idx+len(orig_lines)]
                        if [l.strip() for l in chunk] == [l.strip() for l in orig_lines]:
                            lines[idx:idx+len(orig_lines)] = corrected.splitlines()
                            new_content = "\n".join(lines)
                        else:
                            raise Exception("Code block mismatch near line number")
                    else:
                        raise Exception("Code block out of bounds near line number")
                else:
                    raise Exception("Original code snippet not found in target file")

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            # 3. Sandbox Validation Check
            if file_path.endswith(".py"):
                interpreter = r"C:\D FOLDER\Projects\AI\aria_env\Scripts\python.exe"
                if not os.path.exists(interpreter):
                    interpreter = "python"
                result = subprocess.run(
                    [interpreter, "-m", "py_compile", file_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                if result.returncode != 0:
                    shutil.copy(backup_path, file_path)
                    os.remove(backup_path)
                    aria.safe_speak("Sandbox validation failed. The patched code has compilation errors, so I rolled back the change.")
                    return "Validation failed, rolled back."

            if os.path.exists(backup_path):
                os.remove(backup_path)

            aria.safe_speak("Code fix applied and sandbox validation passed successfully.")
            return "Success."

        except Exception as patch_err:
            print(f"[Screen Triage] Patch error: {patch_err}")
            if os.path.exists(backup_path):
                shutil.copy(backup_path, file_path)
                os.remove(backup_path)
            aria.safe_speak(f"Failed to apply patch: {patch_err}. I restored the backup.")
            return "Patch error."

def handle_screen_triage(aria, inp, user_input, image=None):
    command_clean = user_input.lower().strip()
    triage = AriaScreenTriage()
    
    # 1. Confirmation intercepts
    if triage.pending_fix is not None:
        pending = triage.pending_fix
        triage.pending_fix = None
        
        if any(w in command_clean for w in ["no", "cancel", "abort", "don't", "stop", "reject"]):
            aria.safe_speak("Patch correction aborted.")
            return {"handled": True, "action": "screen_triage", "response": "aborted"}
        elif any(w in command_clean for w in ["yes", "confirm", "write", "do it", "sure", "ok", "okay", "apply", "patch", "fix"]):
            triage.pending_fix = pending
            res = triage.apply_fix(aria)
            return {"handled": True, "action": "screen_triage", "response": res}
        else:
            # Let fallback pass through but clear pending
            print("[Screen Triage] Non-confirm response received. Clearing staged patch.")
            
    # 2. General trigger routing
    res = triage.triage_active_screen(aria)
    return {"handled": True, "action": "screen_triage", "response": res}
