import os
from dotenv import load_dotenv

load_dotenv()

class AriaSMTPConfig:
    def __init__(self):
        self.server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        
        # Read port, default to 465 (Implicit SSL). Fallback standard is 587 (STARTTLS)
        try:
            self.port = int(os.getenv("SMTP_PORT", "465"))
        except (ValueError, TypeError):
            self.port = 465
            
        self.sender_address = os.getenv("EMAIL_ADDRESS")
        self.app_password = os.getenv("EMAIL_PASSWORD")

    def validate_config(self):
        """Ensures both sender email address and SMTP password exist in .env."""
        return bool(self.sender_address and self.app_password)
