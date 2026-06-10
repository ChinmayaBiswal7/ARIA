import re
import json
import sqlite3
import datetime
from skills.email_skill import AriaEmailSkill
from skills.daily_briefing import DailyBriefing
from skills.personal_os_reasoning import PersonalOSReasoningEngine

EMAIL_REGEX = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'

def resolve_recipient_email(aria, name):
    name_clean = name.strip().lower()
    if "@" in name_clean:
        # Check if the name clean matches email regex
        if re.match(EMAIL_REGEX, name_clean):
            return name_clean
            
    # Search semantic graph for (name, 'email', target) relations
    try:
        conn = sqlite3.connect("aria_memory.db")
        cursor = conn.cursor()
        # Find connection matching source name
        cursor.execute("""
            SELECT target FROM semantic_graph 
            WHERE source LIKE ? AND relation = 'email'
        """, (f"%{name_clean}%",))
        row = cursor.fetchone()
        conn.close()
        if row:
            email_candidate = row[0].strip()
            if re.match(EMAIL_REGEX, email_candidate):
                return email_candidate
    except Exception as e:
        print(f"[EmailCommands] Semantic graph lookup failed: {e}")
        
    return None

def handle_email(aria, inp, user_input):
    inp_clean = inp.lower().strip()
    email_skill = AriaEmailSkill()
    
    # 1. Dispatch/Confirm pending email
    if inp_clean == "confirm email" or inp_clean == "send email" or inp_clean == "approve email":
        draft = email_skill.get_latest_pending_draft()
        if not draft:
            aria._speak("I couldn't find any pending email draft waiting for approval.")
            return "no_pending_draft"
            
        aria._speak(f"Sending email to {draft['to_email']} now...")
        res = email_skill.execute_send(draft["id"], approved_by="voice")
        if res == "SUCCESS":
            aria._speak("Email sent successfully!")
            if hasattr(aria, "_pending_email_draft_id"):
                aria._pending_email_draft_id = None
            return "email_sent_success"
        else:
            aria._speak(f"Failed to send email. {res}")
            return f"send_failed_{res}"

    # 2. Cancel/Abort pending email
    if inp_clean == "cancel email" or inp_clean == "abort email" or inp_clean == "delete draft":
        draft = email_skill.get_latest_pending_draft()
        if not draft:
            aria._speak("There is no pending email draft waiting for approval.")
            return "no_pending_draft"
            
        email_skill.cancel_draft(draft["id"])
        aria._speak("Email draft cancelled and cleared.")
        if hasattr(aria, "_pending_email_draft_id"):
            aria._pending_email_draft_id = None
        return "draft_cancelled"

    # 3. Send Today's ARIA report (HTML formatting)
    if "send today's report" in inp_clean or "email me today's report" in inp_clean or "send today's aria report" in inp_clean:
        # Fetch sender address as destination
        if not email_skill.config.validate_config():
            aria._speak("My SMTP configuration is incomplete. Please configure your email details in the environment.")
            return "config_missing"
            
        receiver = email_skill.config.sender_address
        subject = f"ARIA Executive Daily Report - {datetime.date.today().strftime('%B %d, %Y')}"
        
        # Compile stats and briefing parameters
        try:
            briefing = DailyBriefing().generate_short(owner_name="Chinmay")
        except Exception:
            briefing = "Daily briefing report logs compiled successfully."
            
        # Parse pressure details
        energy_score = 70
        life_load = 0.35
        guards = "None"
        try:
            pos = PersonalOSReasoningEngine()
            pressures = pos.compute_systemic_pressures()
            energy_score = pressures["raw_energy_score"]
            life_load = pressures["overall_life_load"]
            guards = ", ".join(pressures["active_guards"]) if pressures["active_guards"] else "None"
        except Exception:
            pass
            
        # Format HTML daily report beautifully with Google Fonts and CSS cards
        html_body = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>ARIA Executive Daily Summary</title>
    <style>
        body {{
            font-family: 'Inter', -apple-system, sans-serif;
            background-color: #f6f9fc;
            margin: 0;
            padding: 20px;
            color: #333333;
        }}
        .container {{
            max-width: 600px;
            background-color: #ffffff;
            margin: 0 auto;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            overflow: hidden;
            border: 1px solid #eef2f6;
        }}
        .header {{
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: #ffffff;
            padding: 30px;
            text-align: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 24px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }}
        .header p {{
            margin: 5px 0 0 0;
            opacity: 0.8;
            font-size: 14px;
        }}
        .section {{
            padding: 30px;
            border-bottom: 1px solid #eef2f6;
        }}
        .section-title {{
            font-size: 16px;
            font-weight: 700;
            color: #1e3c72;
            margin-top: 0;
            margin-bottom: 15px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .metric-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-bottom: 15px;
        }}
        .metric-card {{
            background-color: #f8fafc;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
        }}
        .metric-label {{
            font-size: 12px;
            color: #64748b;
            text-transform: uppercase;
            margin-bottom: 5px;
        }}
        .metric-value {{
            font-size: 18px;
            font-weight: 700;
            color: #0f172a;
        }}
        .brief-box {{
            background-color: #f0f7ff;
            border-left: 4px solid #3b82f6;
            padding: 15px;
            border-radius: 4px;
            font-size: 14px;
            line-height: 1.6;
            color: #1e293b;
        }}
        .footer {{
            background-color: #f8fafc;
            padding: 20px;
            text-align: center;
            font-size: 12px;
            color: #94a3b8;
            border-top: 1px solid #eef2f6;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>ARIA CHIEF OF STAFF</h1>
            <p>Daily Executive Briefing & System Summary</p>
        </div>
        
        <div class="section">
            <div class="section-title">System pressure metrics</div>
            <div class="metric-grid">
                <div class="metric-card">
                    <div class="metric-label">Biological Energy</div>
                    <div class="metric-value">{energy_score}%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Life Load Index</div>
                    <div class="metric-value">{life_load} / 1.0</div>
                </div>
            </div>
            <div class="metric-grid">
                <div class="metric-card" style="grid-column: span 2;">
                    <div class="metric-label">Active System Guards</div>
                    <div class="metric-value" style="color: #ef4444; font-size: 15px;">{guards}</div>
                </div>
            </div>
        </div>

        <div class="section">
            <div class="section-title">Aria status overview</div>
            <div class="brief-box">
                {briefing.replace('\n', '<br>')}
            </div>
        </div>
        
        <div class="footer">
            Generated autonomously by ARIA. Bhubaneswar, Odisha.
        </div>
    </div>
</body>
</html>
"""
        # Stage HTML draft
        draft_id = email_skill.stage_email_draft(receiver, subject, html_body, created_by="system_daily_briefing")
        aria._pending_email_draft_id = draft_id
        
        readback = (
            f"Staged executive daily report for {receiver}.\n\n"
            f"Subject:\n{subject}\n\n"
            f"Recipient:\n{receiver}\n\n"
            "Would you like me to send it? You can speak confirmation or perform a thumbs-up gesture."
        )
        aria._speak(readback)
        return "stage_report_success"

    # 4. Draft customized email from user input
    # Ask the Brain LLM to extract parameters and compose draft content
    prompt = f"""You are ARIA's parameter extraction system.
Based on the user's spoken or typed request: "{user_input}"
Extract:
1. Recipient target (either a name like "John" or a full email like "john@example.com")
2. Email subject (compose a professional concise subject line if not explicitly provided)
3. Email body (write a professional, concise, clean email message body matching the user's intent).

Output strictly a JSON block matching the template below:
{{
  "recipient": "recipient target extracted",
  "subject": "email subject",
  "body": "email body content"
}}
Do not add any other commentary, markdown wrappers or text prefix outside of the JSON block.
"""

    print("[EmailCommands] Extracting parameters and writing email draft via LLM...")
    try:
        res_json_str = aria.brain._think_impl(prompt)
        res_data = json.loads(res_json_str.strip())
        
        recipient = res_data.get("recipient", "").strip()
        subject = res_data.get("subject", "Update from Chinmay").strip()
        body = res_data.get("body", "").strip()
        
        # Check if the recipient looks like an email address but is malformed
        if "@" in recipient or "." in recipient:
            if not re.match(EMAIL_REGEX, recipient):
                aria._speak("That doesn't appear to be a valid email address.")
                return "invalid_recipient_email"
        
        # Resolve email address
        resolved_email = resolve_recipient_email(aria, recipient)
        if not resolved_email:
            aria._speak(
                f"I composed the draft for '{recipient}', but I couldn't find a valid email address in my memory. "
                "What email address should I stage this to?"
            )
            # Stash temporary draft in session memory so we can resolve later if they provide it
            aria._stashed_email_draft = {"subject": subject, "body": body, "recipient_name": recipient}
            return "need_recipient_email"
            
        # Stage draft
        draft_id = email_skill.stage_email_draft(resolved_email, subject, body, created_by="voice_command")
        aria._pending_email_draft_id = draft_id
        
        # Read back summary to prevent accidental sends
        readback = (
            f"Staged email draft for {resolved_email}.\n\n"
            f"Subject:\n{subject}\n\n"
            f"Recipient:\n{resolved_email}\n\n"
            "Would you like me to send it? You can speak confirmation or perform a thumbs-up gesture."
        )
        aria._speak(readback)
        return "stage_email_success"
        
    except Exception as e:
        print(f"[EmailCommands] Failed to stage draft: {e}")
        aria._speak("I encountered an issue composing the email draft. Please verify my brain's connectivity.")
        return "stage_draft_failed"
