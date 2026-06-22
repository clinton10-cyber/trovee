"""
OTP generation/verification and email delivery via a Gmail account (SMTP with an
App Password). Also used to relay customer-support messages to the admin's inbox
without the user ever leaving the app.

SETUP REQUIRED (one-time, done by the Trovee operator, not by Claude):
1. The Gmail account sending mail (workspace4568@gmail.com) must have 2-Step
   Verification turned on: https://myaccount.google.com/security
2. Create an App Password: https://myaccount.google.com/apppasswords
   (choose app "Mail", device "Other", name it "Trovee")
3. Google gives you a 16-character password. Set it as an environment variable,
   never hardcode it in source:
       export TROVEE_GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
4. If using Google Workspace (not consumer Gmail), an admin may also need to allow
   "Less secure app access" / SMTP relay is OFF by default and App Passwords are the
   correct, secure approach — no extra step needed if 2FA + App Password are set.
"""

import os
import smtplib
import secrets
import hashlib
import hmac
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

SENDER_EMAIL = os.environ.get("TROVEE_SENDER_EMAIL", "workspace4568@gmail.com")
APP_PASSWORD = os.environ.get("TROVEE_GMAIL_APP_PASSWORD", "")
ADMIN_INBOX_EMAIL = os.environ.get("TROVEE_ADMIN_EMAIL", SENDER_EMAIL)
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

OTP_LENGTH = 6
OTP_TTL_MINUTES = 5
OTP_MAX_ATTEMPTS = 5

# Used only to hash OTPs at rest in the database (so a DB leak doesn't expose
# raw codes). Not a substitute for the App Password setup above.
_OTP_HASH_SECRET = os.environ.get("TROVEE_OTP_HASH_SECRET", "trovee-dev-secret-change-me")


def generate_otp() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))


def hash_otp(code: str) -> str:
    return hmac.new(_OTP_HASH_SECRET.encode(), code.encode(), hashlib.sha256).hexdigest()


def verify_otp_code(code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(code), code_hash)


def otp_expiry_timestamp() -> str:
    return (datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")


def _send_email(to_email: str, subject: str, html_body: str, plain_body: str) -> bool:
    """Send an email via Gmail SMTP. Returns True on success, False on failure
    (failures are logged, never raised to the user as a stack trace)."""
    if not APP_PASSWORD:
        print("[trovee] WARNING: TROVEE_GMAIL_APP_PASSWORD not set. Email not sent. "
              f"Would have sent to {to_email}: {subject}")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Trovee <{SENDER_EMAIL}>"
    msg["To"] = to_email
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SENDER_EMAIL, APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, [to_email], msg.as_string())
        return True
    except Exception as exc:
        print(f"[trovee] ERROR sending email to {to_email}: {exc}")
        return False


def send_otp_email(to_email: str, code: str, purpose: str = "signup") -> bool:
    subject = "Your Trovee verification code"
    purpose_line = {
        "signup": "to finish creating your Trovee account",
        "login": "to sign in to your Trovee account",
        "reset": "to reset your Trovee password",
        "withdrawal": "to confirm your withdrawal request",
    }.get(purpose, "to verify your identity")

    plain_body = (
        f"Your Trovee verification code is: {code}\n\n"
        f"Use this code {purpose_line}. It expires in {OTP_TTL_MINUTES} minutes.\n\n"
        f"If you did not request this code, you can safely ignore this email."
    )
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 32px 24px; background:#0B1220; color:#F7F8FA; border-radius:12px;">
      <div style="font-size:20px; font-weight:700; letter-spacing:0.5px; color:#C9A961; margin-bottom:24px;">TROVEE</div>
      <p style="font-size:15px; line-height:1.6; color:#CBD2DC;">Use this code {purpose_line}:</p>
      <div style="font-family: 'Courier New', monospace; font-size:36px; font-weight:700; letter-spacing:8px; color:#F7F8FA; background:#151E2E; padding:18px 0; text-align:center; border-radius:8px; margin:20px 0;">{code}</div>
      <p style="font-size:13px; color:#8A93A3;">This code expires in {OTP_TTL_MINUTES} minutes. Do not share it with anyone, including anyone claiming to be Trovee support.</p>
      <p style="font-size:12px; color:#5B6573; margin-top:28px;">If you did not request this code, you can safely ignore this email.</p>
    </div>
    """
    return _send_email(to_email, subject, html_body, plain_body)


def send_support_ticket_email(name: str, from_email: str, subject: str, message: str, ticket_id: int) -> bool:
    """Relay an in-app support message to the admin's inbox. The user stays inside
    the app; the operator reads/replies entirely from their own Gmail."""
    full_subject = f"[Trovee Support #{ticket_id}] {subject}"
    plain_body = (
        f"New support message from the Trovee app.\n\n"
        f"Ticket: #{ticket_id}\n"
        f"From: {name} <{from_email}>\n"
        f"Subject: {subject}\n\n"
        f"Message:\n{message}\n\n"
        f"---\nReply directly to {from_email} to respond, or use the admin panel."
    )
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 560px; margin:0 auto; padding:24px; border:1px solid #e4e4e4; border-radius:10px;">
      <h2 style="color:#0B1220; margin-top:0;">New support ticket #{ticket_id}</h2>
      <p><strong>From:</strong> {name} ({from_email})</p>
      <p><strong>Subject:</strong> {subject}</p>
      <div style="background:#f7f8fa; padding:16px; border-radius:8px; white-space:pre-wrap; color:#222;">{message}</div>
      <p style="margin-top:20px; font-size:13px; color:#777;">Reply directly to this user's email to respond, or use the Trovee admin panel.</p>
    </div>
    """
    return _send_email(ADMIN_INBOX_EMAIL, full_subject, html_body, plain_body)
