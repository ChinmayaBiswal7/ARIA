import subprocess
import os
import time
import webbrowser

class WorkspaceSkill:
    """Orchestrates multi-step configurations (preps) for study, coding, and focus."""

    def __init__(self, memory_skill, automation, screen):
        self.memory = memory_skill
        self.automation = automation
        self.screen = screen

    def prepare_ml_workspace(self):
        """Prepares the ML and AI development workspace."""
        steps = []
        
        # 1. Retrieve coding folder
        path = self.memory.get_folder_path("ml project")
        if not path:
            path = r"C:\D FOLDER\Projects\AI"
            
        steps.append(f"Opening VS Code in {path}")
        # Launch VS Code in that folder
        try:
            subprocess.Popen(f'code "{path}"', shell=True)
        except Exception:
            pass
            
        time.sleep(1.0)
        
        # 2. Open browser resources
        steps.append("Opening web resources for ML")
        webbrowser.open("https://github.com")
        webbrowser.open("https://huggingface.co/datasets")
        
        time.sleep(0.5)

        # 3. Open Explorer
        steps.append("Opening project folder in File Explorer")
        self.screen.open_folder(path)

        return "ML Workspace set up complete! Opened VS Code, Hugging Face Datasets, and File Explorer: " + ", ".join(steps)

    def study_mode(self):
        """Minimize distractions: close Steam/Discord, set volume, open notes."""
        steps = []
        
        # 1. Close distractions
        steps.append("Closing Discord and Steam")
        self.automation.close_app("discord")
        self.automation.close_app("steam")
        
        # 2. Open notes
        notes_path = self.memory.get_folder_path("notes")
        if notes_path and os.path.exists(notes_path):
            steps.append("Opening notes folder")
            self.screen.open_folder(notes_path)
            
        # 3. Mute or reduce volume
        steps.append("Adjusting system volume for study")
        # Simulating volume down keys
        for _ in range(5):
            self.screen.press("volumedown")

        return "Focus study mode activated! " + ". ".join(steps)

    def close_workspace(self):
        """Close browser, VS Code, and terminal windows to clean up."""
        self.automation.close_app("chrome")
        self.automation.close_app("code")
        self.automation.close_app("explorer")
        return "Cleaned up workspace. Active windows closed."
