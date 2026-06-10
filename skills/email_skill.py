import sqlite3
import smtplib
import os
import time
import datetime
from email.message import EmailMessage
from skills.smtp_config import AriaSMTPConfig

DB_PATH = "aria_memory.db"
MAX_EMAILS_PER_HOUR = 20

class AriaEmailSkill:
    def __init__(self):
        self.config = AriaSMTPConfig()
        self._init_db()
        self.expire_old_drafts()

    def _get_connection(self):
        return sqlite3.connect(DB_PATH)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_emails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    to_email TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    approved_at TEXT,
                    sent_at TEXT,
                    expires_at TEXT NOT NULL,
                    created_by TEXT,
                    approved_by TEXT
                )
            """)
            # Check for missing audit columns and alter table if needed
            cursor.execute("PRAGMA table_info(pending_emails)")
            columns = [info[1] for info in cursor.fetchall()]
            if "created_by" not in columns:
                cursor.execute("ALTER TABLE pending_emails ADD COLUMN created_by TEXT")
            if "approved_by" not in columns:
                cursor.execute("ALTER TABLE pending_emails ADD COLUMN approved_by TEXT")
            conn.commit()

    def stage_email_draft(self, to_email, subject, body, created_by=None):
        now_dt = datetime.datetime.now()
        created_at = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        
        # Default expiry is 7 days from now
        expires_dt = now_dt + datetime.timedelta(days=7)
        expires_at = expires_dt.strftime("%Y-%m-%d %H:%M:%S")
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO pending_emails (to_email, subject, body, status, created_at, expires_at, created_by)
                VALUES (?, ?, ?, 'pending', ?, ?, ?)
            """, (to_email.strip(), subject.strip(), body, created_at, expires_at, created_by))
            draft_id = cursor.lastrowid
            conn.commit()
        return draft_id

    def get_latest_pending_draft(self):
        self.expire_old_drafts()
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, to_email, subject, body, created_at, expires_at, created_by, approved_by 
                FROM pending_emails 
                WHERE status = 'pending' 
                ORDER BY id DESC LIMIT 1
            """)
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def get_all_pending_drafts(self):
        self.expire_old_drafts()
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, to_email, subject, body, created_at, expires_at, created_by, approved_by 
                FROM pending_emails 
                WHERE status = 'pending' 
                ORDER BY id DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def is_rate_limited(self):
        # Calculate hourly threshold timestamp
        hour_ago_dt = datetime.datetime.now() - datetime.timedelta(hours=1)
        hour_ago = hour_ago_dt.strftime("%Y-%m-%d %H:%M:%S")
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM pending_emails 
                WHERE status = 'sent' AND sent_at >= ?
            """, (hour_ago,))
            sent_count = cursor.fetchone()[0]
            
        return sent_count >= MAX_EMAILS_PER_HOUR

    def expire_old_drafts(self):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE pending_emails 
                SET status = 'expired' 
                WHERE status = 'pending' AND expires_at <= ?
            """, (now,))
            conn.commit()

    def execute_send(self, draft_id, approved_by=None):
        self.expire_old_drafts()
        if not self.config.validate_config():
            return "Configuration missing: EMAIL_ADDRESS and EMAIL_PASSWORD must be configured in your environment."

        if self.is_rate_limited():
            return f"Rate limit exceeded: ARIA is limited to sending a maximum of {MAX_EMAILS_PER_HOUR} emails per hour."

        # Fetch draft
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM pending_emails WHERE id = ? AND status = 'pending'", (draft_id,))
            draft = cursor.fetchone()

        if not draft:
            return f"No pending draft found with ID {draft_id}."

        try:
            msg = EmailMessage()
            msg["Subject"] = draft["subject"]
            msg["From"] = self.config.sender_address
            msg["To"] = draft["to_email"]
            
            body = draft["body"]
            if body.strip().startswith("<!DOCTYPE html>") or body.strip().startswith("<html"):
                msg.set_content(body, subtype="html")
            else:
                msg.set_content(body)

            # Connect and send
            if self.config.port == 465:
                # SSL
                with smtplib.SMTP_SSL(self.config.server, self.config.port, timeout=10) as server:
                    server.login(self.config.sender_address, self.config.app_password)
                    server.send_message(msg)
            else:
                # STARTTLS
                with smtplib.SMTP(self.config.server, self.config.port, timeout=10) as server:
                    server.starttls()
                    server.login(self.config.sender_address, self.config.app_password)
                    server.send_message(msg)

            # Record timestamps in DB
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE pending_emails 
                    SET status = 'sent', approved_at = ?, sent_at = ?, approved_by = ? 
                    WHERE id = ?
                """, (now, now, approved_by, draft_id))
                conn.commit()

            return "SUCCESS"
        except Exception as e:
            return f"SMTP Connection breakdown: {str(e)}"

    def cancel_draft(self, draft_id):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE pending_emails SET status = 'cancelled' WHERE id = ?", (draft_id,))
            conn.commit()
        return "Draft cancelled successfully."
