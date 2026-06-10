import unittest
from unittest.mock import MagicMock, patch, ANY
import sqlite3
import datetime
import time

from skills.email_skill import AriaEmailSkill, DB_PATH
from skills.email_commands import handle_email, resolve_recipient_email, EMAIL_REGEX
from skills.command_router import handle_email as router_handle_email

class TestEmailSkill(unittest.TestCase):
    def setUp(self):
        # We will use a separate mock database path or clean the table before running
        self.conn = sqlite3.connect(DB_PATH)
        cursor = self.conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS pending_emails")
        self.conn.commit()
        
        # Insert test data into semantic graph for name resolution
        cursor.execute("DROP TABLE IF EXISTS semantic_graph")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS semantic_graph (
                source TEXT,
                relation TEXT,
                target TEXT
            )
        """)
        cursor.execute("INSERT INTO semantic_graph VALUES ('john', 'email', 'john@example.com')")
        cursor.execute("INSERT INTO semantic_graph VALUES ('alice', 'email', 'alice@invalid')") # Invalid email
        self.conn.commit()

    def tearDown(self):
        cursor = self.conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS pending_emails")
        cursor.execute("DROP TABLE IF EXISTS semantic_graph")
        self.conn.commit()
        self.conn.close()

    def test_database_initialization_and_migration(self):
        # Initializing the skill should create the table with all audit columns
        skill = AriaEmailSkill()
        
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(pending_emails)")
        cols = [r[1] for r in cursor.fetchall()]
        
        self.assertIn("id", cols)
        self.assertIn("to_email", cols)
        self.assertIn("subject", cols)
        self.assertIn("body", cols)
        self.assertIn("status", cols)
        self.assertIn("created_at", cols)
        self.assertIn("approved_at", cols)
        self.assertIn("sent_at", cols)
        self.assertIn("expires_at", cols)
        self.assertIn("created_by", cols)
        self.assertIn("approved_by", cols)

    def test_stage_draft_persistence(self):
        skill = AriaEmailSkill()
        draft_id = skill.stage_email_draft(
            to_email="test@example.com",
            subject="Hello World",
            body="This is a test body.",
            created_by="voice_command"
        )
        
        draft = skill.get_latest_pending_draft()
        self.assertIsNotNone(draft)
        self.assertEqual(draft["id"], draft_id)
        self.assertEqual(draft["to_email"], "test@example.com")
        self.assertEqual(draft["subject"], "Hello World")
        self.assertEqual(draft["body"], "This is a test body.")
        self.assertEqual(draft["created_by"], "voice_command")
        
        # Verify expiry is set to roughly 7 days from now
        expires = datetime.datetime.strptime(draft["expires_at"], "%Y-%m-%d %H:%M:%S")
        now = datetime.datetime.now()
        diff = expires - now
        self.assertTrue(6.9 < (diff.total_seconds() / 86400) <= 7.0)

    @patch('smtplib.SMTP_SSL')
    @patch('smtplib.SMTP')
    def test_execute_send_ssl_and_starttls(self, mock_smtp, mock_smtp_ssl):
        # 1. Setup config mock for SSL (port 465)
        skill = AriaEmailSkill()
        skill.config.server = "smtp.test.com"
        skill.config.port = 465
        skill.config.sender_address = "sender@test.com"
        skill.config.app_password = "password"
        
        draft_id = skill.stage_email_draft("receiver@test.com", "Test SSL", "SSL Body", created_by="test_run")
        
        # Execute SSL send
        res = skill.execute_send(draft_id, approved_by="gesture")
        self.assertEqual(res, "SUCCESS")
        
        # Verify SSL called
        mock_smtp_ssl.assert_called_once_with("smtp.test.com", 465, timeout=10)
        
        # Verify status flipped to 'sent' and approved_by is set
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM pending_emails WHERE id = ?", (draft_id,))
            row = dict(cursor.fetchone())
            self.assertEqual(row["status"], "sent")
            self.assertEqual(row["approved_by"], "gesture")
            self.assertIsNotNone(row["approved_at"])
            self.assertIsNotNone(row["sent_at"])

        # 2. Setup config mock for STARTTLS (port 587)
        skill_tls = AriaEmailSkill()
        skill_tls.config.server = "smtp.test.com"
        skill_tls.config.port = 587
        skill_tls.config.sender_address = "sender@test.com"
        skill_tls.config.app_password = "password"
        
        draft_tls_id = skill_tls.stage_email_draft("receiver@test.com", "Test TLS", "TLS Body", created_by="test_run")
        
        # Execute TLS send
        res_tls = skill_tls.execute_send(draft_tls_id, approved_by="voice")
        self.assertEqual(res_tls, "SUCCESS")
        
        # Verify STARTTLS called
        mock_smtp.assert_called_once_with("smtp.test.com", 587, timeout=10)
        mock_smtp.return_value.__enter__.return_value.starttls.assert_called_once()
        
        # Verify database fields
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM pending_emails WHERE id = ?", (draft_tls_id,))
            row = dict(cursor.fetchone())
            self.assertEqual(row["status"], "sent")
            self.assertEqual(row["approved_by"], "voice")

    def test_rate_limiting_enforcement(self):
        skill = AriaEmailSkill()
        skill.config.sender_address = "sender@test.com"
        skill.config.app_password = "password"
        
        # Pre-fill database with 20 sent emails in the last hour
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            for i in range(20):
                cursor.execute("""
                    INSERT INTO pending_emails (to_email, subject, body, status, created_at, expires_at, sent_at)
                    VALUES ('test@test.com', 'subject', 'body', 'sent', ?, ?, ?)
                """, (now_str, now_str, now_str))
            conn.commit()
            
        # Try sending the 21st email
        draft_id = skill.stage_email_draft("receiver@test.com", "21st Email", "Body", created_by="test")
        res = skill.execute_send(draft_id)
        self.assertIn("Rate limit exceeded", res)

    def test_draft_auto_expiry(self):
        skill = AriaEmailSkill()
        
        # Insert a pending draft that expired 2 hours ago
        expired_dt = datetime.datetime.now() - datetime.timedelta(hours=2)
        expired_str = expired_dt.strftime("%Y-%m-%d %H:%M:%S")
        created_str = (expired_dt - datetime.timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO pending_emails (to_email, subject, body, status, created_at, expires_at)
                VALUES ('expired@test.com', 'Old Subject', 'Old Body', 'pending', ?, ?)
            """, (created_str, expired_str))
            expired_id = cursor.lastrowid
            conn.commit()

        # Querying should trigger auto-expiry and return None
        draft = skill.get_latest_pending_draft()
        self.assertIsNone(draft)
        
        # Verify status in database is now 'expired'
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM pending_emails WHERE id = ?", (expired_id,))
            status = cursor.fetchone()[0]
            self.assertEqual(status, "expired")

    def test_recipient_email_address_resolution(self):
        aria = MagicMock()
        
        # Resolves via exact email address
        self.assertEqual(resolve_recipient_email(aria, "test@example.com"), "test@example.com")
        self.assertEqual(resolve_recipient_email(aria, "  TEST@EXAMPLE.COM  "), "test@example.com")
        
        # Resolves name in semantic graph
        self.assertEqual(resolve_recipient_email(aria, "john"), "john@example.com")
        
        # Returns None for invalid format or unresolved names
        self.assertIsNone(resolve_recipient_email(aria, "unknown"))
        self.assertIsNone(resolve_recipient_email(aria, "alice")) # Resolves but invalid format

    def test_conversational_confirm_cancel_router(self):
        aria = MagicMock()
        aria._stashed_email_draft = None
        aria._pending_email_draft_id = 999
        
        # 1. Test "yes" confirmation
        with patch('skills.email_skill.AriaEmailSkill.execute_send') as mock_send:
            mock_send.return_value = "SUCCESS"
            
            res = router_handle_email(aria, "yes", "yes")
            self.assertTrue(res["handled"])
            self.assertEqual(res["response"], "email_sent_success")
            mock_send.assert_called_once_with(999, approved_by="voice")
            self.assertIsNone(getattr(aria, "_pending_email_draft_id"))

        # 2. Test "cancel" response
        aria._stashed_email_draft = None
        aria._pending_email_draft_id = 888
        with patch('skills.email_skill.AriaEmailSkill.cancel_draft') as mock_cancel:
            res = router_handle_email(aria, "no, don't send", "no, don't send")
            self.assertTrue(res["handled"])
            self.assertEqual(res["response"], "draft_cancelled")
            mock_cancel.assert_called_once_with(888)
            self.assertIsNone(getattr(aria, "_pending_email_draft_id"))

    def test_conversational_stashed_draft_followup(self):
        aria = MagicMock()
        aria._pending_email_draft_id = None
        aria._stashed_email_draft = {
            "subject": "Stashed Subject",
            "body": "Stashed Body",
            "recipient_name": "unknown"
        }
        
        # Input with valid email address should stage the draft
        with patch('skills.email_skill.AriaEmailSkill.stage_email_draft') as mock_stage:
            mock_stage.return_value = 123
            res = router_handle_email(aria, "recipient email is test@example.com", "recipient email is test@example.com")
            
            self.assertTrue(res["handled"])
            self.assertEqual(res["response"], "stage_email_success")
            mock_stage.assert_called_once_with(
                "test@example.com", "Stashed Subject", "Stashed Body", created_by="voice_command"
            )
            self.assertEqual(aria._pending_email_draft_id, 123)
            self.assertIsNone(getattr(aria, "_stashed_email_draft"))

        # Input with invalid email address should reject
        aria = MagicMock()
        aria._pending_email_draft_id = None
        aria._stashed_email_draft = {
            "subject": "Stashed Subject",
            "body": "Stashed Body",
            "recipient_name": "unknown"
        }
        res_invalid = router_handle_email(aria, "send to invalid@email", "send to invalid@email")
        self.assertTrue(res_invalid["handled"])
        self.assertEqual(res_invalid["response"], "invalid_email")
        self.assertIsNotNone(getattr(aria, "_stashed_email_draft")) # Still stashed

if __name__ == "__main__":
    unittest.main()
