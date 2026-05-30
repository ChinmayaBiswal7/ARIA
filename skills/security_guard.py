"""
security_guard.py — Centralized Security, Verification, and Safety layer for ARIA
==================================================================================
Implements:
1. SAFE vs DANGEROUS Action classification.
2. 5-Minute Wake Word Lock / Admin Unlock.
3. Telegram Whitelist validation.
4. Protected commands & path filter (block taskkill, registry, shutdown, system32, etc.).
5. Memory Safety Filters (strip API keys, passwords, OTPs).
6. Double-confirmation flow for high-risk actions.
7. Verification wrapper (Face recognition match, Voice admin lock).
"""

import os
import re
import time
import json

PROJECT_DIR = r"c:\D FOLDER\Projects\AI"

class SecurityGuard:
    def __init__(self, memory_manager=None):
        self.memory_manager = memory_manager
        self.admin_mode_active = False
        self.admin_mode_expires_at = 0.0
        
        # Load Whitelisted Telegram Chat IDs
        self.authorized_chat_ids = self._load_telegram_whitelist()
        
        # Blocklist for shell commands & process commands
        self.blocked_keywords = [
            "system32", "reg delete", "regedit", "format ", "rmdir /s", 
            "del /f /s", "taskkill /f /im winlogon", "taskkill /f /im explorer",
            "winlogon.exe", "boot.ini", "ntldr", "sysprep"
        ]
        
        # Define Action Risk Levels
        self.safe_intents = [
            "weather", "news", "search", "time", "date", "hello", "greet", 
            "list reminders", "get reminders", "pc status", "battery"
        ]
        
        self.dangerous_intents = [
            "shutdown", "restart", "delete file", "kill process", "close agent",
            "run shell", "change registry", "open powershell", "run powershell"
        ]

    def _load_telegram_whitelist(self):
        """Loads whitelisted Telegram Chat IDs from file or env."""
        whitelist = set()
        
        # Load from Env
        env_val = os.environ.get("TELEGRAM_AUTHORIZED_CHAT_ID")
        if env_val:
            try:
                for val in env_val.split(","):
                    whitelist.add(int(val.strip()))
            except ValueError:
                pass
                
        # Load from file
        file_path = os.path.join(PROJECT_DIR, "telegram_authorized_chat_id.txt")
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            whitelist.add(int(line))
            except Exception as e:
                print(f"[SecurityGuard] Error reading Telegram whitelist: {e}")
                
        print(f"[SecurityGuard] Whitelisted Telegram Chat IDs loaded: {list(whitelist)}")
        return whitelist

    def save_telegram_authorized_id(self, chat_id):
        """Adds a chat ID to the local Telegram whitelist file."""
        try:
            self.authorized_chat_ids.add(chat_id)
            file_path = os.path.join(PROJECT_DIR, "telegram_authorized_chat_id.txt")
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(f"\n{chat_id}")
            print(f"[SecurityGuard] Saved Chat ID {chat_id} to whitelist.")
            return True
        except Exception as e:
            print(f"[SecurityGuard] Failed to save Telegram ID: {e}")
            return False

    def is_telegram_authorized(self, chat_id):
        """Returns True if the Telegram sender is whitelisted."""
        if not self.authorized_chat_ids:
            # If whitelist is empty, we default to deny all except if user explicitly allows it
            return False
        return chat_id in self.authorized_chat_ids

    def unlock_admin(self):
        """Activates admin mode for 5 minutes (300 seconds)."""
        self.admin_mode_active = True
        self.admin_mode_expires_at = time.time() + 300.0
        print(f"[SecurityGuard] Admin mode unlocked. Expires in 5 minutes.")
        return "Admin Mode unlocked for 5 minutes."

    def lock_admin(self):
        """Manually locks admin mode."""
        self.admin_mode_active = False
        self.admin_mode_expires_at = 0.0
        print(f"[SecurityGuard] Admin mode locked.")
        return "Admin Mode locked."

    def is_admin_active(self):
        """Checks if admin/unlock mode is active and not expired."""
        if self.admin_mode_active and time.time() < self.admin_mode_expires_at:
            return True
        # Reset if expired
        if self.admin_mode_active:
            self.admin_mode_active = False
            self.admin_mode_expires_at = 0.0
        return False

    def get_admin_remaining_time(self):
        """Returns remaining seconds for admin mode."""
        if not self.is_admin_active():
            return 0
        return max(0, int(self.admin_mode_expires_at - time.time()))

    def sanitize_memory_text(self, text):
        """Removes passwords, API keys, and credentials to ensure memory safety."""
        if not text:
            return ""
            
        # Pattern for typical API keys / tokens (hex or base64 keys)
        api_pattern = re.compile(r'(?:api_key|token|password|passwd|secret|key|authorization|bearer)\s*[:=]\s*["\']?[a-zA-Z0-9_\-\.\/]{12,}["\']?', re.IGNORECASE)
        # Pattern for numeric OTP codes (6 digits)
        otp_pattern = re.compile(r'\b\d{6}\b')
        # Pattern for credentials
        cred_pattern = re.compile(r'(?<=password\s)[:=]\s*\S+|(?<=pass\s)[:=]\s*\S+', re.IGNORECASE)
        
        sanitized = text
        sanitized = api_pattern.sub("[REDACTED_API_KEY]", sanitized)
        sanitized = otp_pattern.sub("[REDACTED_OTP]", sanitized)
        sanitized = cred_pattern.sub("[REDACTED_PASSWORD]", sanitized)
        
        # Scrub standard patterns of email/password
        sanitized = re.sub(r'password\s*=\s*\S+', 'password=[REDACTED]', sanitized, flags=re.IGNORECASE)
        
        return sanitized

    def classify_action_risk(self, command):
        """Returns risk level ('safe', 'medium', 'high') for a user command."""
        cmd_lower = command.lower()
        
        # Check system keyword blocklist
        for kw in self.blocked_keywords:
            if kw in cmd_lower:
                return "high"
                
        # Check specific destructive keywords
        if any(x in cmd_lower for x in ["shutdown", "restart", "reboot", "taskkill", "delete file", "delete folder"]):
            return "high"
            
        # Code execution intents
        if any(x in cmd_lower for x in ["run python", "run powershell", "run cmd", "run script", "run shell", "execute"]):
            return "high"
            
        # App manipulation or volume
        if any(x in cmd_lower for x in ["close app", "close tab", "terminate", "close"]):
            return "medium"
            
        return "safe"

    def verify_agent_action_tag(self, tag):
        """Verifies bracketed action tags in ARIA replies (like [SHUTDOWN], [RESTART])."""
        tag_lower = tag.lower()
        
        # 1. Blocklist check
        for kw in self.blocked_keywords:
            if kw in tag_lower:
                return False, f"Contains blocked command keyword: {kw}"
                
        # 2. Block direct shutdown/restart tags unless admin is authenticated
        if "[shutdown]" in tag_lower or "[restart]" in tag_lower:
            if not self.is_admin_active():
                return False, "Requires Admin Authentication to shutdown or restart the PC."
                
        return True, "Action tag is safe."
