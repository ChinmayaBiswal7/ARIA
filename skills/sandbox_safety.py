"""
skills/sandbox_safety.py — ARIA Sandbox Safety & Privacy Zone Manager
=====================================================================
Classifies action risk levels into LOW, MEDIUM, HIGH, CRITICAL.
Enforces human approval for HIGH and CRITICAL risks.
Manages privacy zones where camera/microphone perception is temporarily disabled.
"""

import time
import re
from typing import Dict, Any, Tuple, List

class SandboxSafetyLayer:
    def __init__(self):
        # Admin approval flags
        self.human_approved_ids = set()
        
        # Privacy zone config
        self.privacy_keywords = [
            "bitwarden", "keepass", "password", "bank", "paypal", "stripe",
            "whatsapp", "signal", "telegram", "messenger", "private", "incognito"
        ]
        self.privacy_mode_active = False
        self.privacy_mode_expires_at = 0.0

    # ── Risk Classification ──────────────────────────────────────────────

    def classify_risk(self, action_tag: str) -> str:
        """
        Classifies an action tag into LOW, MEDIUM, HIGH, CRITICAL risk.
        """
        t = action_tag.lower().strip()
        
        # 1. CRITICAL: System manipulation, destructive commands, direct code execution
        if any(w in t for w in ["shutdown", "restart", "reboot", "format"]):
            return "CRITICAL"
        if "[type:" in t:
            # Check for destructive shell commands
            typed_text = re.search(r'\[type:\s*([^\]]+)\]', t)
            if typed_text:
                cmd = typed_text.group(1).lower()
                if any(w in cmd for w in ["rm ", "del ", "format ", "taskkill", "drop database", "sh ", "bash "]):
                    return "CRITICAL"
        
        # 2. HIGH: System tool run, registry modification, browser file uploads
        if any(w in t for w in ["reg delete", "regedit", "powershell", "cmd.exe", "delete file", "delete folder"]):
            return "HIGH"

        # 3. MEDIUM: GUI clicks, key presses, application closing
        if any(w in t for w in ["click:", "double_click:", "right_click:", "press:", "close:"]):
            return "MEDIUM"

        # 4. LOW: Reading, searching, opening browsers, wait
        return "LOW"

    def requires_approval(self, risk_level: str) -> bool:
        """Returns True if the risk level requires human intervention."""
        return risk_level in ["HIGH", "CRITICAL"]

    def grant_approval(self, action_id: str):
        """Grants human approval for a specific action transaction."""
        self.human_approved_ids.add(action_id)

    def is_action_approved(self, action_id: str, risk_level: str) -> bool:
        """Checks if a critical/high risk action was already approved."""
        if not self.requires_approval(risk_level):
            return True
        return action_id in self.human_approved_ids

    # ── Privacy Zones ────────────────────────────────────────────────────

    def enter_privacy_mode(self, duration_minutes: float = 10.0):
        """Disables perception (webcam, mic) for the specified minutes."""
        self.privacy_mode_active = True
        self.privacy_mode_expires_at = time.time() + (duration_minutes * 60.0)
        print(f"[SandboxSafety] Privacy Mode active for {duration_minutes} minutes.")

    def exit_privacy_mode(self):
        """Explicitly exits privacy mode."""
        self.privacy_mode_active = False
        self.privacy_mode_expires_at = 0.0
        print("[SandboxSafety] Privacy Mode deactivated.")

    def check_active_window_privacy(self, window_title: str) -> bool:
        """
        Dynamically detects if active window matches known sensitive keywords
        indicating a privacy zone.
        """
        w_lower = window_title.lower()
        for keyword in self.privacy_keywords:
            if keyword in w_lower:
                return True
        return False

    def is_perception_allowed(self, current_window_title: str) -> bool:
        """
        Main gatekeeper: determines if camera/mic perception is safe to run.
        """
        # 1. Check manual timer override
        if self.privacy_mode_active:
            if time.time() < self.privacy_mode_expires_at:
                return False
            else:
                self.privacy_mode_active = False  # Timer expired
                
        # 2. Check dynamic window title
        if self.check_active_window_privacy(current_window_title):
            return False

        return True
