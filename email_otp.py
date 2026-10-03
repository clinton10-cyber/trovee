"""
OTP generation/verification and email delivery for Trovee.

DELIVERY METHODS (auto-detected from environment variables):
─────────────────────────────────────────────────────────────
1. Brevo HTTP API  ← recommended for Render.com (no SMTP port needed)
   Set: TROVEE_BREVO_API_KEY
   Get a free key at https://app.brevo.com → SMTP & API → API Keys
   Free tier: 300 emails/day, no credit card.

2. Gmail SMTP  ← works locally / Termux, blocked on Render free plan
   Set: TROVEE_GMAIL_APP_PASSWORD
   Requires Gmail 2FA + App Password from https://myaccount.google.com/apppasswords

If BOTH are set, Brevo is used (more reliable on cloud hosts).
If NEITHER is set, emails are skipped and the code is printed to the log
so you can still test OTP verification manually during development.
"""

import os
import ssl
import json
import urllib.request
import urllib.error
import smtplib
import secrets
import hashlib
import hmac
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

SENDER_EMAIL      = os.environ.get("TROVEE_SENDER_EMAIL", "")
SENDER_NAME       = os.environ.get("TROVEE_SENDER_NAME", "Trovee")
APP_PASSWORD      = os.environ.get("TROVEE_GMAIL_APP_PASSWORD", "")
BREVO_API_KEY     = os.environ.get("TROVEE_BREVO_API_KEY", "")
ADMIN_INBOX_EMAIL = os.environ.get("TROVEE_ADMIN_EMAIL", SENDER_EMAIL)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

OTP_LENGTH       = 6
OTP_TTL_MINUTES  = 5
OTP_MAX_ATTEMPTS = 5

_OTP_HASH_SECRET = os.environ.get("TROVEE_OTP_HASH_SECRET", "trovee-dev-secret-change-me")


# ── OTP helpers ────────────────────────────────────────────────────────────────

def generate_otp() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))


def hash_otp(code: str) -> str:
    return hmac.new(_OTP_HASH_SECRET.encode(), code.encode(), hashlib.sha256).hexdigest()


def verify_otp_code(code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(code), code_hash)


def otp_expiry_timestamp() -> str:
    return (datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")


# ── Email delivery ─────────────────────────────────────────────────────────────

def _send_via_brevo(to_email: str, subject: str, html_body: str, plain_body: str) -> bool:
    """Send via Brevo HTTP API with automatic key rotation.
    
    Set multiple keys as comma-separated in TROVEE_BREVO_API_KEY:
    e.g. TROVEE_BREVO_API_KEY=key1,key2,key3
    When one key hits its daily limit (402/429), the next is tried automatically.
    """
    keys = [k.strip() for k in BREVO_API_KEY.split(",") if k.strip()]
    if not keys:
        print("[trovee] Brevo: no API keys configured.")
        return False

    payload = {
        "sender":  {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "to":      [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_body,
        "textContent": plain_body,
    }

    for i, key in enumerate(keys):
        req = urllib.request.Request(
            "https://api.brevo.com/v3/smtp/email",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "api-key": key,
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status in (200, 201):
                    print(f"[trovee] Brevo key {i+1}/{len(keys)}: email sent to {to_email}")
                    return True
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            if exc.code in (402, 429):
                # Daily limit hit — try next key
                print(f"[trovee] Brevo key {i+1}/{len(keys)} limit reached (HTTP {exc.code}), trying next key...")
                continue
            print(f"[trovee] Brevo key {i+1}/{len(keys)} HTTP {exc.code}: {body}")
            return False
        except Exception as exc:
            print(f"[trovee] Brevo key {i+1}/{len(keys)} error: {type(exc).__name__}: {exc}")
            return False

    print(f"[trovee] Brevo: all {len(keys)} keys exhausted — daily limits reached.")
    return False


def _send_via_smtp(to_email: str, subject: str, html_body: str, plain_body: str) -> bool:
    """Send via Gmail SMTP. Tries port 465/SSL first, falls back to 587/STARTTLS."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body,  "html"))

    # Try port 465 (SSL) first — sometimes open on Render free tier
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as server:
            server.login(SENDER_EMAIL, APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, [to_email], msg.as_string())
        print(f"[trovee] SMTP 465/SSL: email sent to {to_email}")
        return True
    except smtplib.SMTPAuthenticationError as exc:
        print(f"[trovee] SMTP AUTH ERROR on 465 — check TROVEE_GMAIL_APP_PASSWORD. Details: {exc}")
        return False
    except Exception as exc:
        print(f"[trovee] SMTP 465 failed ({type(exc).__name__}: {exc}), trying 587/STARTTLS...")

    # Fall back to port 587 STARTTLS
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SENDER_EMAIL, APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, [to_email], msg.as_string())
        print(f"[trovee] SMTP 587/STARTTLS: email sent to {to_email}")
        return True
    except smtplib.SMTPAuthenticationError as exc:
        print(f"[trovee] SMTP AUTH ERROR on 587 — check TROVEE_GMAIL_APP_PASSWORD. Details: {exc}")
        return False
    except Exception as exc:
        print(f"[trovee] SMTP 587 also failed: {type(exc).__name__}: {exc}")
        return False


def _send_email(to_email: str, subject: str, html_body: str, plain_body: str) -> bool:
    """Route to Brevo (preferred) or SMTP depending on which env var is set."""
    if BREVO_API_KEY:
        return _send_via_brevo(to_email, subject, html_body, plain_body)
    if APP_PASSWORD:
        return _send_via_smtp(to_email, subject, html_body, plain_body)
    # Neither configured — dev/test mode: log the content so OTP can be read from logs.
    print(f"[trovee] WARNING: no email provider configured.")
    print(f"[trovee] Would send to {to_email}: {subject}")
    print(f"[trovee] Plain body: {plain_body}")
    return False


# ── OTP email ──────────────────────────────────────────────────────────────────

def send_otp_email(to_email: str, code: str, purpose: str = "signup") -> bool:
    import random
    subjects = [
        "Your Trovee verification code",
        f"Trovee: {code} is your verification code",
        "Verify your Trovee account",
        f"[Trovee] Your one-time code: {code}",
        "Complete your Trovee sign-up",
    ]
    subject = random.choice(subjects)
    purpose_line = {
        "signup":     "to finish creating your Trovee account",
        "login":      "to sign in to your Trovee account",
        "reset":      "to reset your Trovee password",
        "withdrawal": "to confirm your withdrawal request",
    }.get(purpose, "to verify your identity")

    plain_body = (
        f"Your Trovee verification code is: {code}\n\n"
        f"Use this code {purpose_line}. It expires in {OTP_TTL_MINUTES} minutes.\n\n"
        f"If you did not request this code, you can safely ignore this email."
    )
    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;
                padding:32px 24px;background:#0B1220;color:#F7F8FA;border-radius:12px;">
      <div style="font-size:20px;font-weight:700;letter-spacing:0.5px;
                  color:#0A84FF;margin-bottom:24px;">TROVEE</div>
      <p style="font-size:15px;line-height:1.6;color:#CBD2DC;">
        Use this code {purpose_line}:
      </p>
      <div style="font-family:'Courier New',monospace;font-size:36px;font-weight:700;
                  letter-spacing:8px;color:#F7F8FA;background:#151E2E;
                  padding:18px 0;text-align:center;border-radius:8px;margin:20px 0;">
        {code}
      </div>
      <p style="font-size:13px;color:#8A93A3;">
        This code expires in {OTP_TTL_MINUTES} minutes.
        Do not share it with anyone, including anyone claiming to be Trovee support.
      </p>
      <p style="font-size:12px;color:#5B6573;margin-top:28px;">
        If you did not request this code, you can safely ignore this email.
      </p>
    </div>
    """
    return _send_email(to_email, subject, html_body, plain_body)


# ── Support ticket email ────────────────────────────────────────────────────────

def send_support_ticket_email(
    name: str, from_email: str, subject: str, message: str, ticket_id: int
) -> bool:
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
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;
                padding:24px;border:1px solid #e4e4e4;border-radius:10px;">
      <h2 style="color:#0B1220;margin-top:0;">New support ticket #{ticket_id}</h2>
      <p><strong>From:</strong> {name} ({from_email})</p>
      <p><strong>Subject:</strong> {subject}</p>
      <div style="background:#f7f8fa;padding:16px;border-radius:8px;
                  white-space:pre-wrap;color:#222;">{message}</div>
      <p style="margin-top:20px;font-size:13px;color:#777;">
        Reply directly to this user's email to respond, or use the Trovee admin panel.
      </p>
    </div>
    """
    return _send_email(ADMIN_INBOX_EMAIL, full_subject, html_body, plain_body)
