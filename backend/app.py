import os
import re
import jwt
import json
import uuid
import datetime
import traceback
from functools import wraps
from flask import Flask, request, jsonify, render_template, g, send_from_directory, redirect
from werkzeug.utils import secure_filename

from backend.db import get_db, init_db
from backend.security import hash_password, verify_password
from backend.email_otp import (
    generate_otp, hash_otp, verify_otp_code, otp_expiry_timestamp,
    send_otp_email, OTP_MAX_ATTEMPTS,
)
from backend.geo_currency import (
    get_currency_for_country, convert_usd_cents, get_withdrawal_methods,
    COUNTRY_CURRENCY, USD_EXCHANGE_RATES,
)
from backend.paystack_service import paystack

# ─── Configuration ──────────────────────────────────────────────
APP_SECRET = os.environ.get("TROVEE_APP_SECRET", "trovee-dev-secret-change-me-in-prod")
WITHDRAWAL_MINIMUM_USD_CENTS = 1
ADMIN_PASSWORD = os.environ.get("TROVEE_ADMIN_PASSWORD", "change-me-admin")

# Upload folder for gift card images
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'static', 'uploads', 'giftcards')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

app = Flask(__name__, template_folder="../frontend/templates", static_folder="../frontend/static")


# ─── Auth Helpers ──────────────────────────────────────────────

def make_token(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=30),
    }
    return jwt.encode(payload, APP_SECRET, algorithm="HS256")


def decode_token(token: str):
    try:
        payload = jwt.decode(token, APP_SECRET, algorithms=["HS256"])
        return payload.get("user_id")
    except jwt.PyJWTError:
        return None


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else None
        if not token:
            return jsonify({"error": "Authentication required."}), 401
        user_id = decode_token(token)
        if not user_id:
            return jsonify({"error": "Session expired or invalid. Please log in again."}), 401
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        db.close()
        if not user:
            return jsonify({"error": "Account not found."}), 401
        g.user = user
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Admin-Token", "")
        if token != ADMIN_PASSWORD:
            return jsonify({"error": "Not authorized."}), 401
        return f(*args, **kwargs)
    return wrapper


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,20}$")


# ─── Page Routes ──────────────────────────────────────────────

@app.route("/")
def page_landing():
    return render_template("landing.html")


@app.route("/login")
def page_login():
    return render_template("login.html")


@app.route("/signup")
def page_signup():
    return render_template("signup.html")


@app.route("/forgot-password")
def page_forgot_password():
    return render_template("forgot_password.html")


@app.route("/dashboard")
def page_dashboard():
    return render_template("dashboard.html")


@app.route("/withdraw")
def page_withdraw():
    return render_template("withdraw.html")


@app.route("/support")
def page_support_redirect():
    # The old email-based support ticket page has been retired in favour of
    # the in-app Messages chat.
    return redirect("/messages")


@app.route("/messages")
def page_messages():
    return render_template("messages.html")


@app.route("/admin")
def page_admin():
    return render_template("admin.html")


@app.route("/trading")
def page_trading():
    return render_template("trading.html")


@app.route("/deposit")
def page_deposit():
    return render_template("deposit.html")


@app.route("/shares")
def page_shares():
    return render_template("shares.html")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder + "/img", "favicon.ico")


@app.route("/sw.js")
def service_worker():
    # Served from the root (not /static/js/) so its default scope covers the whole app.
    response = send_from_directory(app.static_folder + "/js", "sw.js")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/manifest.webmanifest")
def web_manifest():
    return send_from_directory(app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")


# ─── API: Geo / Currency ──────────────────────────────────────

@app.route("/api/geo/detect", methods=["GET"])
def api_geo_detect():
    country_code = (
        request.headers.get("CF-IPCountry")
        or request.headers.get("CloudFront-Viewer-Country")
        or request.args.get("country")
        or "US"
    ).upper()
    if country_code not in COUNTRY_CURRENCY:
        country_code = "US"
    currency_code, symbol, name = get_currency_for_country(country_code)
    return jsonify({
        "country_code": country_code,
        "currency_code": currency_code,
        "currency_symbol": symbol,
        "currency_name": name,
    })


# ─── API: Authentication ──────────────────────────────────────

@app.route("/api/auth/signup/start", methods=["POST"])
def api_signup_start():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    phone = (data.get("phone") or "").strip()
    password = data.get("password") or ""
    country_code = (data.get("country_code") or "US").upper()

    if not USERNAME_RE.match(username):
        return jsonify({"error": "Username must be 3-20 characters, letters, numbers, or underscores."}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"error": "Enter a valid email address."}), 400
    if "gmail.com" not in email:
        return jsonify({"error": "Please sign up with a Gmail address."}), 400
    if len(phone) < 7:
        return jsonify({"error": "Enter a valid phone number."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400

    db = get_db()
    existing = db.execute(
        "SELECT id FROM users WHERE email = ? OR username = ?", (email, username)
    ).fetchone()
    if existing:
        db.close()
        return jsonify({"error": "An account with that email or username already exists."}), 409

    code = generate_otp()
    code_hash = hash_otp(code)
    expires_at = otp_expiry_timestamp()
    pending_payload = json.dumps({
        "username": username, "email": email, "phone": phone,
        "password": password, "country_code": country_code,
    })
    db.execute(
        "INSERT INTO otp_codes (email, code_hash, purpose, expires_at) VALUES (?, ?, ?, ?)",
        (f"signup:{pending_payload}", code_hash, "signup", expires_at),
    )
    db.commit()
    db.close()

    sent = send_otp_email(email, code, purpose="signup")
    return jsonify({
        "message": "Verification code sent to your Gmail." if sent else "Code generated. Email delivery is not configured yet; check server logs.",
        "expires_in_seconds": 300,
        "email_sent": sent,
    })


@app.route("/api/auth/signup/verify", methods=["POST"])
def api_signup_verify():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()

    db = get_db()
    row = db.execute(
        "SELECT * FROM otp_codes WHERE email LIKE ? AND purpose = 'signup' AND consumed = 0 "
        "ORDER BY id DESC LIMIT 1",
        (f"signup:%{email}%",),
    ).fetchone()

    if not row:
        db.close()
        return jsonify({"error": "No pending signup found. Please start over."}), 400

    if row["attempts"] >= OTP_MAX_ATTEMPTS:
        db.close()
        return jsonify({"error": "Too many incorrect attempts. Please request a new code."}), 429

    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    if now > row["expires_at"]:
        db.close()
        return jsonify({"error": "This code has expired. Please request a new one."}), 400

    if not verify_otp_code(code, row["code_hash"]):
        db.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
        db.commit()
        db.close()
        return jsonify({"error": "Incorrect code. Please try again."}), 400

    payload_str = row["email"].split("signup:", 1)[1]
    payload = json.loads(payload_str)

    pw_hash, salt = hash_password(payload["password"])
    currency_code, _, _ = get_currency_for_country(payload["country_code"])
    cur = db.execute(
        "INSERT INTO users (username, email, phone, password_hash, password_salt, country_code, "
        "currency_code, email_verified) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
        (payload["username"], payload["email"], payload["phone"], pw_hash, salt,
         payload["country_code"], currency_code),
    )
    db.execute("UPDATE otp_codes SET consumed = 1 WHERE id = ?", (row["id"],))
    db.commit()
    user_id = cur.lastrowid
    db.close()

    token = make_token(user_id)
    return jsonify({"message": "Account created.", "token": token})


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or not verify_password(password, user["password_hash"], user["password_salt"]):
        db.close()
        return jsonify({"error": "Incorrect email or password."}), 401

    db.execute("UPDATE users SET last_login_at = datetime('now') WHERE id = ?", (user["id"],))
    db.commit()
    db.close()
    token = make_token(user["id"])
    return jsonify({"message": "Logged in.", "token": token})


@app.route("/api/auth/forgot-password/start", methods=["POST"])
def api_forgot_password_start():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()

    if not EMAIL_RE.match(email):
        return jsonify({"error": "Enter a valid email address."}), 400

    # Always return the same generic response whether or not the email is
    # registered, so this endpoint can't be used to find out who has an account.
    generic_response = jsonify({
        "message": "If that email has a Trovee account, we've sent a reset code to it.",
        "expires_in_seconds": 300,
    })

    db = get_db()
    user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if not user:
        db.close()
        return generic_response

    code = generate_otp()
    code_hash = hash_otp(code)
    expires_at = otp_expiry_timestamp()
    db.execute(
        "INSERT INTO otp_codes (email, code_hash, purpose, expires_at) VALUES (?, ?, ?, ?)",
        (email, code_hash, "reset", expires_at),
    )
    db.commit()
    db.close()

    send_otp_email(email, code, purpose="reset")
    return generic_response


@app.route("/api/auth/forgot-password/verify", methods=["POST"])
def api_forgot_password_verify():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    new_password = data.get("new_password") or ""

    if len(new_password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400

    db = get_db()
    row = db.execute(
        "SELECT * FROM otp_codes WHERE email = ? AND purpose = 'reset' AND consumed = 0 "
        "ORDER BY id DESC LIMIT 1",
        (email,),
    ).fetchone()

    if not row:
        db.close()
        return jsonify({"error": "No pending reset found. Please request a new code."}), 400

    if row["attempts"] >= OTP_MAX_ATTEMPTS:
        db.close()
        return jsonify({"error": "Too many incorrect attempts. Please request a new code."}), 429

    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    if now > row["expires_at"]:
        db.close()
        return jsonify({"error": "This code has expired. Please request a new one."}), 400

    if not verify_otp_code(code, row["code_hash"]):
        db.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
        db.commit()
        db.close()
        return jsonify({"error": "Incorrect code. Please try again."}), 400

    user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if not user:
        db.close()
        return jsonify({"error": "No account found for that email."}), 404

    pw_hash, salt = hash_password(new_password)
    db.execute(
        "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
        (pw_hash, salt, user["id"]),
    )
    db.execute("UPDATE otp_codes SET consumed = 1 WHERE id = ?", (row["id"],))
    db.commit()
    user_id = user["id"]
    db.close()

    token = make_token(user_id)
    return jsonify({"message": "Password updated.", "token": token})


@app.route("/api/auth/me", methods=["GET"])
@login_required
def api_me():
    u = g.user
    currency_code, symbol, name = get_currency_for_country(u["country_code"])
    balance_local = convert_usd_cents(u["balance_usd_cents"], currency_code)
    return jsonify({
        "username": u["username"], "email": u["email"], "phone": u["phone"],
        "country_code": u["country_code"], "currency_code": currency_code,
        "currency_symbol": symbol, "balance_usd_cents": u["balance_usd_cents"],
        "balance_local": balance_local, "trust_level": u["trust_level"],
        "exchange_rate": USD_EXCHANGE_RATES.get(currency_code, 1.0),
    })


# ─── API: Withdrawals ─────────────────────────────────────────

@app.route("/api/withdraw/methods", methods=["GET"])
@login_required
def api_withdraw_methods():
    methods, providers = get_withdrawal_methods(g.user["country_code"])
    currency_code, symbol, _ = get_currency_for_country(g.user["country_code"])
    return jsonify({
        "methods": methods,
        "mobile_money_providers": providers,
        "minimum_usd_cents": WITHDRAWAL_MINIMUM_USD_CENTS,
        "minimum_local": convert_usd_cents(WITHDRAWAL_MINIMUM_USD_CENTS, currency_code),
        "currency_symbol": symbol,
        "exchange_rate": USD_EXCHANGE_RATES.get(currency_code, 1.0),
    })


@app.route("/api/withdraw/request", methods=["POST"])
@login_required
def api_withdraw_request():
    data = request.get_json(force=True) or {}
    method = data.get("method")
    destination = (data.get("destination_details") or "").strip()
    amount_usd_cents = data.get("amount_usd_cents")

    if not isinstance(amount_usd_cents, int) or amount_usd_cents <= 0:
        return jsonify({"error": "Enter a valid withdrawal amount."}), 400
    if not destination:
        return jsonify({"error": "Provide your withdrawal destination details."}), 400

    valid_methods, _ = get_withdrawal_methods(g.user["country_code"])
    if method not in valid_methods:
        return jsonify({"error": "That withdrawal method is not available in your region."}), 400

    db = get_db()
    user = db.execute("SELECT balance_usd_cents FROM users WHERE id = ?", (g.user["id"],)).fetchone()
    if amount_usd_cents > user["balance_usd_cents"]:
        db.close()
        return jsonify({"error": "Withdrawal amount exceeds your available balance."}), 400

    db.execute(
        "INSERT INTO withdrawals (user_id, amount_usd_cents, method, destination_details) VALUES (?, ?, ?, ?)",
        (g.user["id"], amount_usd_cents, method, destination),
    )
    db.execute(
        "UPDATE users SET balance_usd_cents = balance_usd_cents - ? WHERE id = ?",
        (amount_usd_cents, g.user["id"]),
    )
    db.commit()
    db.close()
    return jsonify({"message": "Withdrawal requested. It is now pending review."})


@app.route("/api/withdraw/history", methods=["GET"])
@login_required
def api_withdraw_history():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM withdrawals WHERE user_id = ? ORDER BY requested_at DESC", (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify({"withdrawals": [dict(r) for r in rows]})


# ─── API: Messages (user-facing) ──────────────────────────────
# A "support account" is a completely normal-looking user account
# that an admin can flag and assign to one or more other users. While
# assigned, loading /messages on that support account shows a chat
# (or an inbox of chats, if assigned to several people) with the
# assigned user(s) instead of a generic support inbox. The assigned
# user never sees anything indicating who is on the other end — it
# just looks like they're messaging Trovee support. The admin can
# read and reply to every conversation without either side knowing.

def _active_assignments_for_support(db, support_user_id):
    return db.execute(
        "SELECT sa.*, u.username as target_username FROM support_assignments sa "
        "JOIN users u ON u.id = sa.target_user_id "
        "WHERE sa.support_user_id = ? AND sa.is_active = 1 "
        "ORDER BY sa.assigned_at DESC",
        (support_user_id,),
    ).fetchall()


def _current_chat_context(db):
    """Resolve the target_user_id and mode ('support' or 'user') for g.user.
    Only resolves to 'support' when there's exactly one active assignment —
    agents with multiple assigned users use the /api/messages/context +
    /api/messages/thread/<id> endpoints instead."""
    if g.user["is_support_account"]:
        assignments = _active_assignments_for_support(db, g.user["id"])
        if len(assignments) == 1:
            return assignments[0]["target_user_id"], "support"
    return g.user["id"], "user"


@app.route("/api/messages/context", methods=["GET"])
@login_required
def api_messages_context():
    db = get_db()
    if g.user["is_support_account"]:
        assignments = _active_assignments_for_support(db, g.user["id"])
        if assignments:
            conversations = []
            for a in assignments:
                target_id = a["target_user_id"]
                last = db.execute(
                    "SELECT body, sender, created_at FROM chat_messages "
                    "WHERE target_user_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                    (target_id,),
                ).fetchone()
                unread = db.execute(
                    "SELECT COUNT(*) as n FROM chat_messages "
                    "WHERE target_user_id = ? AND sender = 'user' AND is_read_support = 0",
                    (target_id,),
                ).fetchone()
                conversations.append({
                    "target_user_id": target_id,
                    "username": a["target_username"],
                    "last_message": last["body"] if last else None,
                    "last_message_at": last["created_at"] if last else None,
                    "unread_count": unread["n"] if unread else 0,
                })
            db.close()
            return jsonify({"role": "agent", "conversations": conversations})
    db.close()
    return jsonify({"role": "user"})


@app.route("/api/messages", methods=["GET"])
@login_required
def api_messages_get():
    db = get_db()
    target_id, mode = _current_chat_context(db)

    if mode == "support":
        other = db.execute("SELECT username FROM users WHERE id = ?", (target_id,)).fetchone()
        other_name = other["username"] if other else "User"
        db.execute(
            "UPDATE chat_messages SET is_read_support = 1 WHERE target_user_id = ? AND is_read_support = 0",
            (target_id,),
        )
    else:
        other_name = "Customer Care and Support"
        db.execute(
            "UPDATE chat_messages SET is_read_user = 1 WHERE target_user_id = ? AND is_read_user = 0",
            (target_id,),
        )
    db.commit()

    rows = db.execute(
        "SELECT id, sender, body, created_at FROM chat_messages "
        "WHERE target_user_id = ? ORDER BY created_at ASC, id ASC",
        (target_id,),
    ).fetchall()
    db.close()

    return jsonify({
        "mode": mode,
        "other_name": other_name,
        "messages": [dict(r) for r in rows],
    })


@app.route("/api/messages", methods=["POST"])
@login_required
def api_messages_send():
    data = request.get_json(force=True) or {}
    body = (data.get("message") or "").strip()
    if not body:
        return jsonify({"error": "Enter a message."}), 400
    if len(body) > 4000:
        return jsonify({"error": "Message is too long."}), 400

    db = get_db()
    target_id, mode = _current_chat_context(db)

    if mode == "support":
        db.execute(
            "INSERT INTO chat_messages (target_user_id, support_user_id, sender, body, "
            "is_read_user, is_read_support) VALUES (?, ?, 'support', ?, 0, 1)",
            (target_id, g.user["id"], body),
        )
    else:
        assignment = db.execute(
            "SELECT support_user_id FROM support_assignments WHERE target_user_id = ? AND is_active = 1 "
            "ORDER BY id DESC LIMIT 1",
            (target_id,),
        ).fetchone()
        support_user_id = assignment["support_user_id"] if assignment else None
        db.execute(
            "INSERT INTO chat_messages (target_user_id, support_user_id, sender, body, "
            "is_read_user, is_read_support) VALUES (?, ?, 'user', ?, 1, 0)",
            (target_id, support_user_id, body),
        )
    db.commit()
    db.close()
    return jsonify({"message": "Sent."})


def _validated_agent_target(db, target_user_id):
    """Confirm g.user is an agent actively assigned to target_user_id. Returns the target
    user's row (username, balance_usd_cents, currency_code) or None if not assigned."""
    if not g.user["is_support_account"]:
        return None
    row = db.execute(
        "SELECT u.username, u.balance_usd_cents, u.currency_code "
        "FROM support_assignments sa JOIN users u ON u.id = sa.target_user_id "
        "WHERE sa.support_user_id = ? AND sa.target_user_id = ? AND sa.is_active = 1",
        (g.user["id"], target_user_id),
    ).fetchone()
    return row


@app.route("/api/messages/thread/<int:target_user_id>", methods=["GET"])
@login_required
def api_messages_thread_get(target_user_id):
    db = get_db()
    target = _validated_agent_target(db, target_user_id)
    if not target:
        db.close()
        return jsonify({"error": "You are not assigned to this conversation."}), 403

    db.execute(
        "UPDATE chat_messages SET is_read_support = 1 WHERE target_user_id = ? AND is_read_support = 0",
        (target_user_id,),
    )
    db.commit()
    rows = db.execute(
        "SELECT id, sender, body, created_at FROM chat_messages "
        "WHERE target_user_id = ? ORDER BY created_at ASC, id ASC",
        (target_user_id,),
    ).fetchall()
    db.close()
    return jsonify({
        "mode": "support",
        "other_name": target["username"],
        "target_balance_usd_cents": target["balance_usd_cents"],
        "target_currency_code": target["currency_code"],
        "messages": [dict(r) for r in rows],
    })


@app.route("/api/messages/thread/<int:target_user_id>", methods=["POST"])
@login_required
def api_messages_thread_send(target_user_id):
    data = request.get_json(force=True) or {}
    body = (data.get("message") or "").strip()
    if not body:
        return jsonify({"error": "Enter a message."}), 400
    if len(body) > 4000:
        return jsonify({"error": "Message is too long."}), 400

    db = get_db()
    target = _validated_agent_target(db, target_user_id)
    if not target:
        db.close()
        return jsonify({"error": "You are not assigned to this conversation."}), 403

    db.execute(
        "INSERT INTO chat_messages (target_user_id, support_user_id, sender, body, "
        "is_read_user, is_read_support) VALUES (?, ?, 'support', ?, 0, 1)",
        (target_user_id, g.user["id"], body),
    )
    db.commit()
    db.close()
    return jsonify({"message": "Sent."})


@app.route("/api/messages/thread/<int:target_user_id>/balance", methods=["POST"])
@login_required
def api_messages_thread_balance(target_user_id):
    data = request.get_json(force=True) or {}
    amount_usd_cents = data.get("amount_usd_cents")
    mode = data.get("mode", "set")

    if not isinstance(amount_usd_cents, int):
        return jsonify({"error": "amount_usd_cents must be an integer."}), 400
    if mode not in ("set", "adjust"):
        return jsonify({"error": "mode must be 'set' or 'adjust'."}), 400

    db = get_db()
    target = _validated_agent_target(db, target_user_id)
    if not target:
        db.close()
        return jsonify({"error": "You are not assigned to this conversation."}), 403

    if mode == "set":
        if amount_usd_cents < 0:
            db.close()
            return jsonify({"error": "Balance cannot be negative."}), 400
        new_balance = amount_usd_cents
    else:
        new_balance = target["balance_usd_cents"] + amount_usd_cents
        if new_balance < 0:
            db.close()
            return jsonify({"error": "Adjustment would result in negative balance."}), 400

    db.execute("UPDATE users SET balance_usd_cents = ? WHERE id = ?", (new_balance, target_user_id))
    db.commit()
    db.close()
    return jsonify({"message": "Balance updated.", "new_balance_usd_cents": new_balance})


@app.route("/api/messages/unread-count", methods=["GET"])
@login_required
def api_messages_unread_count():
    db = get_db()
    if g.user["is_support_account"]:
        assignments = _active_assignments_for_support(db, g.user["id"])
        if assignments:
            target_ids = [a["target_user_id"] for a in assignments]
            placeholders = ",".join("?" for _ in target_ids)
            row = db.execute(
                f"SELECT COUNT(*) as n FROM chat_messages "
                f"WHERE target_user_id IN ({placeholders}) AND sender = 'user' AND is_read_support = 0",
                target_ids,
            ).fetchone()
            db.close()
            return jsonify({"unread": row["n"] if row else 0})
    row = db.execute(
        "SELECT COUNT(*) as n FROM chat_messages WHERE target_user_id = ? AND sender = 'support' AND is_read_user = 0",
        (g.user["id"],),
    ).fetchone()
    db.close()
    return jsonify({"unread": row["n"] if row else 0})


# ─── API: Admin ───────────────────────────────────────────────

@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    data = request.get_json(force=True) or {}
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"error": "Incorrect admin password."}), 401
    return jsonify({"token": ADMIN_PASSWORD})


@app.route("/api/admin/withdrawals", methods=["GET"])
@admin_required
def api_admin_withdrawals():
    db = get_db()
    rows = db.execute(
        "SELECT w.*, u.username, u.email FROM withdrawals w JOIN users u ON u.id = w.user_id "
        "ORDER BY w.requested_at DESC"
    ).fetchall()
    db.close()
    return jsonify({"withdrawals": [dict(r) for r in rows]})


@app.route("/api/admin/withdrawals/<int:withdrawal_id>/status", methods=["POST"])
@admin_required
def api_admin_withdrawal_update(withdrawal_id):
    data = request.get_json(force=True) or {}
    status = data.get("status")
    if status not in ("approved", "rejected", "paid", "pending"):
        return jsonify({"error": "Invalid status."}), 400

    db = get_db()
    withdrawal = db.execute("SELECT * FROM withdrawals WHERE id = ?", (withdrawal_id,)).fetchone()
    if not withdrawal:
        db.close()
        return jsonify({"error": "Withdrawal not found."}), 404

    if status == "rejected" and withdrawal["status"] != "rejected":
        db.execute(
            "UPDATE users SET balance_usd_cents = balance_usd_cents + ? WHERE id = ?",
            (withdrawal["amount_usd_cents"], withdrawal["user_id"]),
        )

    db.execute(
        "UPDATE withdrawals SET status = ?, processed_at = datetime('now') WHERE id = ?",
        (status, withdrawal_id),
    )
    db.commit()
    db.close()
    return jsonify({"message": "Withdrawal status updated."})


@app.route("/api/admin/users/<int:user_id>/balance", methods=["POST"])
@admin_required
def api_admin_user_balance(user_id):
    data = request.get_json(force=True) or {}
    amount_usd_cents = data.get("amount_usd_cents")
    mode = data.get("mode", "set")

    if not isinstance(amount_usd_cents, int):
        return jsonify({"error": "amount_usd_cents must be an integer."}), 400

    db = get_db()
    user = db.execute("SELECT id, balance_usd_cents FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        db.close()
        return jsonify({"error": "User not found."}), 404

    if mode == "set":
        if amount_usd_cents < 0:
            db.close()
            return jsonify({"error": "Balance cannot be negative."}), 400
        db.execute("UPDATE users SET balance_usd_cents = ? WHERE id = ?", (amount_usd_cents, user_id))
    elif mode == "adjust":
        new_balance = user["balance_usd_cents"] + amount_usd_cents
        if new_balance < 0:
            db.close()
            return jsonify({"error": "Adjustment would result in negative balance."}), 400
        db.execute("UPDATE users SET balance_usd_cents = ? WHERE id = ?", (new_balance, user_id))
    else:
        db.close()
        return jsonify({"error": "mode must be 'set' or 'adjust'."}), 400

    new_bal = db.execute("SELECT balance_usd_cents FROM users WHERE id = ?", (user_id,)).fetchone()["balance_usd_cents"]
    db.commit()
    db.close()
    return jsonify({"message": "Balance updated.", "new_balance_usd_cents": new_bal})


@app.route("/api/admin/users", methods=["GET"])
@admin_required
def api_admin_users():
    db = get_db()
    rows = db.execute(
        "SELECT id, username, email, phone, country_code, currency_code, "
        "balance_usd_cents, trust_level, is_support_account, created_at FROM users ORDER BY created_at DESC"
    ).fetchall()
    db.close()
    return jsonify({"users": [dict(r) for r in rows]})


@app.route("/api/admin/support-accounts", methods=["GET"])
@admin_required
def api_admin_support_accounts():
    db = get_db()
    accounts = db.execute(
        "SELECT id, username, email FROM users WHERE is_support_account = 1 ORDER BY username"
    ).fetchall()
    result = []
    for acc in accounts:
        targets = db.execute(
            "SELECT sa.target_user_id as id, u.username FROM support_assignments sa "
            "JOIN users u ON u.id = sa.target_user_id "
            "WHERE sa.support_user_id = ? AND sa.is_active = 1 ORDER BY u.username",
            (acc["id"],),
        ).fetchall()
        result.append({
            "id": acc["id"],
            "username": acc["username"],
            "email": acc["email"],
            "targets": [dict(t) for t in targets],
        })
    db.close()
    return jsonify({"accounts": result})


@app.route("/api/admin/support-accounts/<int:user_id>/toggle", methods=["POST"])
@admin_required
def api_admin_support_account_toggle(user_id):
    data = request.get_json(force=True) or {}
    enabled = bool(data.get("enabled", True))

    db = get_db()
    user = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        db.close()
        return jsonify({"error": "User not found."}), 404

    db.execute("UPDATE users SET is_support_account = ? WHERE id = ?", (1 if enabled else 0, user_id))
    if not enabled:
        db.execute(
            "UPDATE support_assignments SET is_active = 0, unassigned_at = datetime('now') "
            "WHERE support_user_id = ? AND is_active = 1",
            (user_id,),
        )
    db.commit()
    db.close()
    return jsonify({"message": "Support account updated." if enabled else "Support account disabled."})


@app.route("/api/admin/support-accounts/<int:user_id>/assign", methods=["POST"])
@admin_required
def api_admin_support_account_assign(user_id):
    data = request.get_json(force=True) or {}
    target_user_id = data.get("target_user_id")
    if not target_user_id:
        return jsonify({"error": "target_user_id is required."}), 400
    target_user_id = int(target_user_id)

    db = get_db()
    support_user = db.execute("SELECT id, is_support_account FROM users WHERE id = ?", (user_id,)).fetchone()
    if not support_user or not support_user["is_support_account"]:
        db.close()
        return jsonify({"error": "That account is not marked as a support account."}), 400

    target_user = db.execute("SELECT id FROM users WHERE id = ?", (target_user_id,)).fetchone()
    if not target_user:
        db.close()
        return jsonify({"error": "Target user not found."}), 404

    if target_user_id == int(user_id):
        db.close()
        return jsonify({"error": "A support account can't be assigned to itself."}), 400

    existing = db.execute(
        "SELECT id FROM support_assignments WHERE support_user_id = ? AND target_user_id = ? AND is_active = 1",
        (user_id, target_user_id),
    ).fetchone()
    if existing:
        db.close()
        return jsonify({"error": "Already assigned to that user."}), 400

    # A user can only be actively chatted with by one agent at a time — free up
    # any other agent currently assigned to this target. An agent, however, can
    # be assigned to as many different users as needed.
    db.execute(
        "UPDATE support_assignments SET is_active = 0, unassigned_at = datetime('now') "
        "WHERE target_user_id = ? AND is_active = 1",
        (target_user_id,),
    )
    db.execute(
        "INSERT INTO support_assignments (support_user_id, target_user_id, is_active) VALUES (?, ?, 1)",
        (user_id, target_user_id),
    )
    db.commit()
    db.close()
    return jsonify({"message": "Support account assigned."})


@app.route("/api/admin/support-accounts/<int:user_id>/unassign", methods=["POST"])
@admin_required
def api_admin_support_account_unassign(user_id):
    data = request.get_json(force=True) or {}
    target_user_id = data.get("target_user_id")

    db = get_db()
    if target_user_id:
        db.execute(
            "UPDATE support_assignments SET is_active = 0, unassigned_at = datetime('now') "
            "WHERE support_user_id = ? AND target_user_id = ? AND is_active = 1",
            (user_id, int(target_user_id)),
        )
    else:
        db.execute(
            "UPDATE support_assignments SET is_active = 0, unassigned_at = datetime('now') "
            "WHERE support_user_id = ? AND is_active = 1",
            (user_id,),
        )
    db.commit()
    db.close()
    return jsonify({"message": "Unassigned."})


@app.route("/api/admin/messages/<int:target_user_id>", methods=["GET"])
@admin_required
def api_admin_messages_thread(target_user_id):
    db = get_db()
    target = db.execute("SELECT id, username, email FROM users WHERE id = ?", (target_user_id,)).fetchone()
    if not target:
        db.close()
        return jsonify({"error": "User not found."}), 404
    assignment = db.execute(
        "SELECT sa.*, u.username as support_username FROM support_assignments sa "
        "JOIN users u ON u.id = sa.support_user_id "
        "WHERE sa.target_user_id = ? AND sa.is_active = 1 ORDER BY sa.id DESC LIMIT 1",
        (target_user_id,),
    ).fetchone()
    rows = db.execute(
        "SELECT id, sender, body, created_at FROM chat_messages "
        "WHERE target_user_id = ? ORDER BY created_at ASC, id ASC",
        (target_user_id,),
    ).fetchall()
    db.close()
    return jsonify({
        "target": dict(target),
        "assigned_support": dict(assignment) if assignment else None,
        "messages": [dict(r) for r in rows],
    })


@app.route("/api/admin/messages/<int:target_user_id>", methods=["POST"])
@admin_required
def api_admin_messages_send(target_user_id):
    data = request.get_json(force=True) or {}
    body = (data.get("message") or "").strip()
    if not body:
        return jsonify({"error": "Enter a message."}), 400

    db = get_db()
    target = db.execute("SELECT id FROM users WHERE id = ?", (target_user_id,)).fetchone()
    if not target:
        db.close()
        return jsonify({"error": "User not found."}), 404

    assignment = db.execute(
        "SELECT support_user_id FROM support_assignments WHERE target_user_id = ? AND is_active = 1 "
        "ORDER BY id DESC LIMIT 1",
        (target_user_id,),
    ).fetchone()
    support_user_id = assignment["support_user_id"] if assignment else None

    db.execute(
        "INSERT INTO chat_messages (target_user_id, support_user_id, sender, body, "
        "is_read_user, is_read_support) VALUES (?, ?, 'support', ?, 0, 1)",
        (target_user_id, support_user_id, body),
    )
    db.commit()
    db.close()
    return jsonify({"message": "Sent."})


@app.route("/api/admin/deposits", methods=["GET"])
@admin_required
def api_admin_deposits():
    db = get_db()
    rows = db.execute(
        "SELECT d.*, u.username, u.email FROM deposits d "
        "JOIN users u ON u.id = d.user_id "
        "ORDER BY d.created_at DESC"
    ).fetchall()
    db.close()
    return jsonify({"deposits": [dict(r) for r in rows]})


@app.route("/api/admin/deposits/<int:deposit_id>/review", methods=["POST"])
@admin_required
def api_admin_deposit_review(deposit_id):
    data = request.get_json(force=True) or {}
    status = data.get("status")
    if status not in ("confirmed", "rejected"):
        return jsonify({"error": "Status must be 'confirmed' or 'rejected'."}), 400

    db = get_db()
    dep = db.execute("SELECT * FROM deposits WHERE id = ?", (deposit_id,)).fetchone()
    if not dep:
        db.close()
        return jsonify({"error": "Deposit not found."}), 404

    credited = 0
    if status == "confirmed" and dep["status"] == "pending":
        credited = int(dep["value_usd"] * 100)
        db.execute(
            "UPDATE users SET balance_usd_cents = balance_usd_cents + ? WHERE id = ?",
            (credited, dep["user_id"])
        )

    db.execute(
        "UPDATE deposits SET status = ?, credited_usd_cents = ?, reviewed_at = datetime('now') WHERE id = ?",
        (status, credited, deposit_id)
    )
    db.commit()
    db.close()
    return jsonify({"message": f"Deposit {status}.", "credited_usd_cents": credited})


@app.route("/api/admin/deposits/stats", methods=["GET"])
@admin_required
def api_admin_deposits_stats():
    db = get_db()
    total = db.execute("SELECT COUNT(*) as count FROM deposits").fetchone()["count"]
    pending = db.execute("SELECT COUNT(*) as count FROM deposits WHERE status = 'pending'").fetchone()["count"]
    total_value = db.execute("SELECT SUM(value_usd) as total FROM deposits WHERE status = 'confirmed'").fetchone()["total"] or 0
    db.close()
    return jsonify({
        "total_deposits": total,
        "pending_deposits": pending,
        "total_value": total_value
    })


@app.route("/api/admin/withdrawals/stats", methods=["GET"])
@admin_required
def api_admin_withdrawals_stats():
    db = get_db()
    total = db.execute("SELECT COUNT(*) as count FROM withdrawals").fetchone()["count"]
    pending = db.execute("SELECT COUNT(*) as count FROM withdrawals WHERE status = 'pending'").fetchone()["count"]
    total_value = db.execute("SELECT SUM(amount_usd_cents) as total FROM withdrawals WHERE status = 'paid'").fetchone()["total"] or 0
    db.close()
    return jsonify({
        "total_withdrawals": total,
        "pending_withdrawals": pending,
        "total_value_cents": total_value,
        "total_value_usd": total_value / 100
    })


@app.route("/api/admin/paystack/settings", methods=["GET"])
@admin_required
def api_admin_paystack_settings_get():
    db = get_db()
    auto_approve = db.execute(
        "SELECT value FROM admin_settings WHERE key = 'paystack_withdrawals_auto_approve'"
    ).fetchone()
    enabled = db.execute(
        "SELECT value FROM admin_settings WHERE key = 'paystack_withdrawals_enabled'"
    ).fetchone()
    return jsonify({
        "auto_approve": bool(auto_approve and auto_approve["value"] == "1"),
        "enabled": bool(enabled and enabled["value"] == "1"),
        "configured": paystack.is_configured()
    })


@app.route("/api/admin/paystack/settings", methods=["POST"])
@admin_required
def api_admin_paystack_settings_update():
    data = request.get_json(force=True) or {}
    auto_approve = data.get("auto_approve", False)
    enabled = data.get("enabled", True)
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO admin_settings (key, value) VALUES ('paystack_withdrawals_auto_approve', ?)",
        ("1" if auto_approve else "0")
    )
    db.execute(
        "INSERT OR REPLACE INTO admin_settings (key, value) VALUES ('paystack_withdrawals_enabled', ?)",
        ("1" if enabled else "0")
    )
    db.commit()
    db.close()
    return jsonify({
        "message": "Settings updated.",
        "auto_approve": auto_approve,
        "enabled": enabled
    })


# ─── API: Trades ──────────────────────────────────────────────

@app.route("/api/trades/place", methods=["POST"])
@login_required
def api_trade_place():
    try:
        data = request.get_json(force=True) or {}
        asset = (data.get("asset") or "").strip()
        direction = data.get("direction")
        duration_sec = data.get("duration_sec")
        amount_usd_cents = data.get("amount_usd_cents")
        entry_price = data.get("entry_price")

        VALID_ASSETS = {"BTC/USD", "ETH/USD", "XAU/USD", "EUR/USD", "BNB/USD"}
        if asset not in VALID_ASSETS:
            return jsonify({"error": "Invalid asset."}), 400
        if direction not in ("up", "down"):
            return jsonify({"error": "Direction must be 'up' or 'down'."}), 400
        if not isinstance(duration_sec, int) or duration_sec not in (30, 60, 90, 120, 180, 360):
            return jsonify({"error": "Invalid duration."}), 400
        if not isinstance(amount_usd_cents, int) or amount_usd_cents < 1000:
            return jsonify({"error": "Minimum trade amount is $10."}), 400
        if not isinstance(entry_price, (int, float)) or entry_price <= 0:
            return jsonify({"error": "Invalid entry price."}), 400

        db = get_db()
        user = db.execute("SELECT balance_usd_cents FROM users WHERE id = ?", (g.user["id"],)).fetchone()
        if amount_usd_cents > user["balance_usd_cents"]:
            db.close()
            return jsonify({"error": "Insufficient balance."}), 400

        db.execute("UPDATE users SET balance_usd_cents = balance_usd_cents - ? WHERE id = ?",
                   (amount_usd_cents, g.user["id"]))
        cur = db.execute(
            "INSERT INTO trades (user_id, asset, direction, duration_sec, amount_usd_cents, entry_price) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (g.user["id"], asset, direction, duration_sec, amount_usd_cents, entry_price)
        )
        trade_id = cur.lastrowid
        if trade_id is None:
            db.close()
            return jsonify({"error": "Failed to create trade – please try again."}), 500
        new_balance = db.execute(
            "SELECT balance_usd_cents FROM users WHERE id = ?", (g.user["id"],)
        ).fetchone()["balance_usd_cents"]
        db.commit()
        db.close()
        return jsonify({
            "trade_id": trade_id,
            "message": "Trade placed.",
            "amount_usd_cents": amount_usd_cents,
            "new_balance_usd_cents": new_balance,
        })

    except Exception as e:
        print(f"[trovee] ERROR in /api/trades/place: {type(e).__name__}: {e}")
        traceback.print_exc()
        raise


@app.route("/api/trades/close", methods=["POST"])
@login_required
def api_trade_close():
    try:
        data = request.get_json(force=True) or {}
        trade_id = data.get("trade_id")
        exit_price = data.get("exit_price")

        if not isinstance(exit_price, (int, float)) or exit_price <= 0:
            return jsonify({"error": "Invalid exit price."}), 400

        db = get_db()
        trade = db.execute(
            "SELECT * FROM trades WHERE id = ? AND user_id = ? AND outcome IS NULL",
            (trade_id, g.user["id"])
        ).fetchone()
        if not trade:
            db.close()
            return jsonify({"error": "Trade not found or already closed."}), 404

        entry = trade["entry_price"]
        amount = trade["amount_usd_cents"]

        # Win/loss amount is the raw price movement itself — not a
        # percentage of the stake. Buy wins by however much price rose;
        # sell wins by however much price fell.
        if trade["direction"] == "up":
            price_delta = exit_price - entry
        else:
            price_delta = entry - exit_price

        profit_usd_cents = int(round(price_delta * 100))

        if profit_usd_cents > 0:
            outcome = "win"
        elif profit_usd_cents < 0:
            outcome = "loss"
        else:
            outcome = "draw"

        credit_back = amount + profit_usd_cents
        if credit_back < 0:
            credit_back = 0

        db.execute(
            "UPDATE trades SET exit_price = ?, outcome = ?, profit_usd_cents = ?, closed_at = datetime('now') WHERE id = ?",
            (exit_price, outcome, profit_usd_cents, trade_id)
        )
        if credit_back > 0:
            db.execute("UPDATE users SET balance_usd_cents = balance_usd_cents + ? WHERE id = ?",
                       (credit_back, g.user["id"]))
        new_balance = db.execute("SELECT balance_usd_cents FROM users WHERE id = ?", (g.user["id"],)).fetchone()["balance_usd_cents"]
        db.commit()
        db.close()

        return jsonify({
            "outcome": outcome,
            "amount_usd_cents": amount,
            "profit_usd_cents": profit_usd_cents,
            "credit_back_usd_cents": credit_back,
            "new_balance_usd_cents": new_balance,
        })
    except Exception as e:
        print(f"[trovee] ERROR in /api/trades/close: {type(e).__name__}: {e}")
        traceback.print_exc()
        raise


@app.route("/api/trades/history", methods=["GET"])
@login_required
def api_trades_history():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM trades WHERE user_id = ? AND outcome IS NOT NULL ORDER BY closed_at DESC LIMIT 50",
        (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify({"trades": [dict(r) for r in rows]})


# ─── API: Deposits ────────────────────────────────────────────

@app.route("/api/deposit/giftcard", methods=["POST"])
@login_required
def api_deposit_giftcard():
    try:
        if request.content_type and 'application/json' in request.content_type:
            data = request.get_json(force=True) or {}
            card_type = (data.get("card_type") or "").strip()
            code = (data.get("code") or "").strip()
            value_usd = data.get("value_usd")
            front_image_path = None
            back_image_path = None

            if not card_type or not code:
                return jsonify({"error": "Card type and code are required."}), 400
            if not isinstance(value_usd, (int, float)) or value_usd < 500:
                return jsonify({"error": "Minimum deposit value is $500."}), 400
        else:
            card_type = (request.form.get("card_type") or "").strip()
            code = (request.form.get("code") or "").strip()
            value_usd = request.form.get("value_usd", type=float)
            front_image = request.files.get('front_image')
            back_image = request.files.get('back_image')

            if not card_type or not code:
                return jsonify({"error": "Card type and code are required."}), 400
            if not isinstance(value_usd, (int, float)) or value_usd < 500:
                return jsonify({"error": "Minimum deposit value is $500."}), 400

            front_image_path = None
            back_image_path = None

            if front_image and front_image.filename:
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                ext = front_image.filename.rsplit('.', 1)[1].lower() if '.' in front_image.filename else 'jpg'
                filename = f"front_{uuid.uuid4().hex[:8]}_{int(datetime.datetime.now().timestamp())}.{ext}"
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                front_image.save(filepath)
                front_image_path = f"/static/uploads/giftcards/{filename}"
                print(f"[trovee] Saved front image: {filepath}")

            if back_image and back_image.filename:
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                ext = back_image.filename.rsplit('.', 1)[1].lower() if '.' in back_image.filename else 'jpg'
                filename = f"back_{uuid.uuid4().hex[:8]}_{int(datetime.datetime.now().timestamp())}.{ext}"
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                back_image.save(filepath)
                back_image_path = f"/static/uploads/giftcards/{filename}"
                print(f"[trovee] Saved back image: {filepath}")

        db = get_db()
        db.execute(
            "INSERT INTO deposits (user_id, method, card_type, code, value_usd, front_image_path, back_image_path) "
            "VALUES (?, 'giftcard', ?, ?, ?, ?, ?)",
            (g.user["id"], card_type, code, value_usd, front_image_path, back_image_path)
        )
        db.commit()
        db.close()
        return jsonify({"message": "Gift card submitted for review. Funds will be credited within 1–4 hours."})
    except Exception as e:
        print(f"[trovee] ERROR in giftcard deposit: {type(e).__name__}: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/deposit/history", methods=["GET"])
@login_required
def api_deposit_history():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM deposits WHERE user_id = ? ORDER BY created_at DESC",
        (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify({"deposits": [dict(r) for r in rows]})


@app.route("/api/deposit/wallets", methods=["GET"])
@login_required
def api_deposit_wallets():
    db = get_db()
    rows = db.execute(
        "SELECT id, display_name, address, logo_url, qr_url FROM wallet_configs "
        "WHERE is_active = 1 ORDER BY sort_order, id"
    ).fetchall()
    db.close()
    return jsonify({"wallets": [dict(r) for r in rows]})


# ─── API: Paystack ────────────────────────────────────────────

@app.route("/api/paystack/initialize", methods=["POST"])
@login_required
def api_paystack_initialize():
    data = request.get_json(force=True) or {}
    amount = data.get("amount")
    channels = data.get("channels", ["card"])

    if not amount or amount < 1:
        return jsonify({"error": "Enter a valid amount (minimum 1)."}), 400

    # Determine currency from user's country
    country = g.user["country_code"].upper()
    currency_map = {
        "NG": "NGN",
        "GH": "GHS",
        "KE": "KES",
        "ZA": "ZAR"
    }
    currency = currency_map.get(country, "NGN")

    if not paystack.is_configured():
        return jsonify({
            "status": "fallback",
            "link": "#",
            "message": "Paystack not configured.",
            "amount": amount,
            "currency": currency
        }), 200

    user_email = g.user["email"]
    reference = f"TROVEE-{g.user['id']}-{int(datetime.datetime.now().timestamp())}"

    response = paystack.initialize_payment(
        user_email=user_email,
        amount=amount,
        currency=currency,
        reference=reference,
        channels=channels
    )

    if response.get("status") == "success":
        return jsonify({
            "status": "success",
            "link": response.get("data", {}).get("link"),
            "reference": response.get("data", {}).get("reference"),
            "amount": amount,
            "currency": currency
        })
    else:
        return jsonify({
            "status": "error",
            "message": response.get("message", "Payment initialization failed.")
        }), 400


@app.route("/api/paystack/callback", methods=["GET"])
def api_paystack_callback():
    reference = request.args.get("reference")
    if not reference:
        return render_template("payment_failed.html", reason="No transaction reference provided.")

    response = paystack.verify_payment(reference)

    if response.get("status") == "fallback":
        return render_template("payment_success.html", amount=100, currency="NGN")

    if response.get("status") == "success":
        data = response.get("data", {})
        if data.get("status") == "success":
            try:
                parts = reference.split("-")
                user_id = int(parts[1]) if len(parts) > 1 else None
            except:
                user_id = None

            amount = data.get("amount", 0)
            currency = data.get("currency", "NGN")
            usd_cents = int(amount * 100)

            if user_id:
                db = get_db()
                db.execute(
                    "UPDATE users SET balance_usd_cents = balance_usd_cents + ? WHERE id = ?",
                    (usd_cents, user_id)
                )
                db.execute(
                    "INSERT INTO deposits (user_id, method, card_type, code, value_usd, status) "
                    "VALUES (?, 'paystack', ?, ?, ?, 'confirmed')",
                    (user_id, currency, reference, amount)
                )
                db.commit()
                db.close()

            return render_template("payment_success.html", amount=amount, currency=currency)
        else:
            return render_template("payment_failed.html", reason="Payment was not successful.")
    else:
        return render_template("payment_failed.html", reason=response.get("message", "Verification failed."))


@app.route("/api/paystack/webhook", methods=["POST"])
def api_paystack_webhook():
    signature = request.headers.get("x-paystack-signature")
    payload = request.data.decode("utf-8")

    if paystack.webhook_verify_signature(payload, signature):
        data = request.get_json()
        if data and data.get("event") == "charge.success":
            transaction_data = data.get("data", {})
            reference = transaction_data.get("reference")
            amount = transaction_data.get("amount", 0) / 100
            currency = transaction_data.get("currency", "NGN")
            user_email = transaction_data.get("customer", {}).get("email")

            try:
                parts = reference.split("-")
                user_id = int(parts[1]) if len(parts) > 1 else None
                if user_id:
                    usd_cents = int(amount * 100)
                    db = get_db()
                    db.execute(
                        "UPDATE users SET balance_usd_cents = balance_usd_cents + ? WHERE id = ?",
                        (usd_cents, user_id)
                    )
                    db.execute(
                        "INSERT INTO deposits (user_id, method, card_type, code, value_usd, status) "
                        "VALUES (?, 'paystack', ?, ?, ?, 'confirmed')",
                        (user_id, currency, reference, amount)
                    )
                    db.commit()
                    db.close()
                    return jsonify({"status": "received"}), 200
            except Exception as e:
                print(f"[trovee] Webhook error: {e}")
                return jsonify({"error": str(e)}), 500

    return jsonify({"status": "received"}), 200


@app.route("/api/paystack/status", methods=["GET"])
def api_paystack_status():
    return jsonify({
        "configured": paystack.is_configured(),
        "message": "Paystack is active" if paystack.is_configured() else "Paystack not configured."
    })


# ─── API: Shares ──────────────────────────────────────────────

@app.route("/api/shares/companies", methods=["GET"])
@login_required
def api_shares_companies():
    db = get_db()
    companies = db.execute(
        "SELECT c.*, COUNT(p.id) as plan_count FROM share_companies c "
        "LEFT JOIN share_plans p ON p.company_id = c.id AND p.is_active = 1 "
        "WHERE c.is_active = 1 GROUP BY c.id ORDER BY c.name"
    ).fetchall()
    db.close()
    return jsonify({"companies": [dict(c) for c in companies]})


@app.route("/api/shares/companies/<int:company_id>/plans", methods=["GET"])
@login_required
def api_shares_plans(company_id):
    db = get_db()
    company = db.execute("SELECT * FROM share_companies WHERE id = ? AND is_active = 1", (company_id,)).fetchone()
    if not company:
        db.close()
        return jsonify({"error": "Company not found."}), 404
    plans = db.execute(
        "SELECT * FROM share_plans WHERE company_id = ? AND is_active = 1 ORDER BY price_usd_cents",
        (company_id,)
    ).fetchall()
    db.close()
    return jsonify({"company": dict(company), "plans": [dict(p) for p in plans]})


@app.route("/api/shares/purchase", methods=["POST"])
@login_required
def api_shares_purchase():
    import uuid as uuid_lib
    from datetime import datetime, timedelta

    data = request.get_json(force=True) or {}
    plan_id = data.get("plan_id")
    company_id = data.get("company_id")
    multiplier = data.get("multiplier", 1)

    if not isinstance(multiplier, int) or multiplier < 1:
        multiplier = 1
    if multiplier > 100:
        multiplier = 100

    db = get_db()
    plan = db.execute(
        "SELECT p.*, c.name as company_name FROM share_plans p "
        "JOIN share_companies c ON c.id = p.company_id "
        "WHERE p.id = ? AND p.company_id = ? AND p.is_active = 1",
        (plan_id, company_id)
    ).fetchone()
    if not plan:
        db.close()
        return jsonify({"error": "Plan not found or no longer available."}), 404

    user = db.execute("SELECT * FROM users WHERE id = ?", (g.user["id"],)).fetchone()

    principal = plan["price_usd_cents"] * multiplier
    shares = plan["shares_count"] * multiplier

    if principal > user["balance_usd_cents"]:
        db.close()
        return jsonify({"error": "Insufficient balance. Please deposit funds first."}), 400

    rate = plan["return_rate_pct"]
    months = plan["duration_months"]
    return_cents = int(principal * (rate / 100) * (months / 12))
    total_payout = principal + return_cents
    maturity_date = (datetime.utcnow() + timedelta(days=months * 30)).strftime("%Y-%m-%d")
    cert_id = f"TRV-{uuid_lib.uuid4().hex[:8].upper()}"

    db.execute("UPDATE users SET balance_usd_cents = balance_usd_cents - ? WHERE id = ?",
               (principal, g.user["id"]))
    cur = db.execute(
        "INSERT INTO share_purchases "
        "(user_id, company_id, plan_id, plan_name, shares_count, price_usd_cents, "
        " return_rate_pct, duration_months, return_usd_cents, total_payout_cents, "
        " certificate_id, status, maturity_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
        (g.user["id"], company_id, plan_id, plan["plan_name"], shares,
         principal, rate, months, return_cents, total_payout, cert_id, maturity_date)
    )
    purchase_id = cur.lastrowid
    new_balance = db.execute(
        "SELECT balance_usd_cents FROM users WHERE id = ?", (g.user["id"],)
    ).fetchone()["balance_usd_cents"]
    db.commit()
    db.close()

    new_balance_local = convert_usd_cents(new_balance, g.user["currency_code"])

    return jsonify({
        "message": "Shares purchased successfully.",
        "certificate_id": cert_id,
        "purchase_id": purchase_id,
        "multiplier": multiplier,
        "shares_purchased": shares,
        "principal_usd_cents": principal,
        "return_usd_cents": return_cents,
        "total_payout_cents": total_payout,
        "maturity_date": maturity_date,
        "new_balance_usd_cents": new_balance,
        "new_balance_local": new_balance_local,
    })


@app.route("/api/shares/portfolio", methods=["GET"])
@login_required
def api_shares_portfolio():
    from datetime import datetime
    db = get_db()
    newly_paid = _process_matured_purchases(db, g.user["id"])
    rows = db.execute(
        "SELECT sp.*, c.name as company_name, c.ticker, c.sector, c.logo_url "
        "FROM share_purchases sp "
        "JOIN share_companies c ON c.id = sp.company_id "
        "WHERE sp.user_id = ? ORDER BY sp.purchased_at DESC",
        (g.user["id"],)
    ).fetchall()

    today = datetime.utcnow()
    portfolio = []
    for r in rows:
        p = dict(r)
        try:
            mat = datetime.strptime(p["maturity_date"], "%Y-%m-%d")
            days_remaining = max(0, (mat - today).days)
        except Exception:
            days_remaining = 0
        p["days_remaining"] = days_remaining
        p["is_matured"] = p["status"] in ("matured", "paid")
        p["progress_pct"] = min(100, max(0, round(
            100 - (days_remaining / max(1, p["duration_months"] * 30)) * 100
        )))
        portfolio.append(p)

    new_balance = db.execute(
        "SELECT balance_usd_cents FROM users WHERE id = ?", (g.user["id"],)
    ).fetchone()["balance_usd_cents"]
    db.close()

    return jsonify({
        "portfolio": portfolio,
        "newly_credited": [
            {"certificate_id": p["certificate_id"],
             "total_payout_cents": p["total_payout_cents"],
             "company_name": p.get("company_name", "")}
            for p in newly_paid
        ],
        "new_balance_usd_cents": new_balance,
    })


@app.route("/api/shares/portfolio/<int:purchase_id>", methods=["GET"])
@login_required
def api_shares_portfolio_detail(purchase_id):
    from datetime import datetime
    db = get_db()
    row = db.execute(
        "SELECT sp.*, c.name as company_name, c.ticker, c.sector, c.logo_url "
        "FROM share_purchases sp "
        "JOIN share_companies c ON c.id = sp.company_id "
        "WHERE sp.id = ? AND sp.user_id = ?",
        (purchase_id, g.user["id"])
    ).fetchone()
    db.close()
    if not row:
        return jsonify({"error": "Investment not found."}), 404
    p = dict(row)
    try:
        mat = datetime.strptime(p["maturity_date"], "%Y-%m-%d")
        p["days_remaining"] = max(0, (mat - datetime.utcnow()).days)
    except Exception:
        p["days_remaining"] = 0
    return jsonify(p)


@app.route("/api/shares/certificate/<cert_id>", methods=["GET"])
@login_required
def api_shares_certificate(cert_id):
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas

    db = get_db()
    purchase = db.execute(
        "SELECT sp.*, u.username, u.email, "
        "c.name as company_name, c.ticker, c.sector, c.description as company_desc, "
        "pl.plan_name, pl.return_rate_pct, pl.duration_months, pl.shares_count as plan_shares "
        "FROM share_purchases sp "
        "JOIN users u ON u.id = sp.user_id "
        "JOIN share_companies c ON c.id = sp.company_id "
        "JOIN share_plans pl ON pl.id = sp.plan_id "
        "WHERE sp.certificate_id = ? AND sp.user_id = ?",
        (cert_id, g.user["id"])
    ).fetchone()
    db.close()

    if not purchase:
        return jsonify({"error": "Certificate not found."}), 404

    p = dict(purchase)
    buf = io.BytesIO()
    w, h = A4
    c = rl_canvas.Canvas(buf, pagesize=A4)

    ink = colors.HexColor("#06080D")
    surface = colors.HexColor("#0F1923")
    paper = colors.HexColor("#F5F7FA")
    slate_soft = colors.HexColor("#8E96A6")
    accent = colors.HexColor("#0A84FF")
    accent_dim = colors.HexColor("#0A4F9A")
    teal = colors.HexColor("#2DD4BF")
    line_col = colors.HexColor("#1A2535")

    c.setFillColor(ink)
    c.rect(0, 0, w, h, fill=1, stroke=0)

    c.saveState()
    c.translate(w / 2, h / 2)
    c.rotate(35)
    c.setFillColor(accent)
    c.setFillAlpha(0.045)
    c.setFont("Helvetica-Bold", 130)
    c.drawCentredString(0, 0, "TROVEE")
    c.restoreState()

    margin = 14 * mm
    c.setStrokeColor(accent)
    c.setLineWidth(3)
    c.rect(margin, margin, w - 2*margin, h - 2*margin, fill=0, stroke=1)
    c.setStrokeColor(accent_dim)
    c.setLineWidth(1)
    c.rect(margin + 3*mm, margin + 3*mm, w - 2*margin - 6*mm, h - 2*margin - 6*mm, fill=0, stroke=1)

    def corner(cx, cy, flip_x=False, flip_y=False):
        sx = -1 if flip_x else 1
        sy = -1 if flip_y else 1
        size = 12 * mm
        c.setStrokeColor(accent)
        c.setLineWidth(1.5)
        c.line(cx, cy, cx + sx * size, cy)
        c.line(cx, cy, cx, cy + sy * size)
        c.setLineWidth(0.7)
        c.line(cx + sx * 3*mm, cy + sy * 3*mm, cx + sx * 9*mm, cy + sy * 3*mm)
        c.line(cx + sx * 3*mm, cy + sy * 3*mm, cx + sx * 3*mm, cy + sy * 9*mm)

    corner(margin, margin)
    corner(w - margin, margin, flip_x=True)
    corner(margin, h - margin, flip_y=True)
    corner(w - margin, h - margin, flip_x=True, flip_y=True)

    band_bottom = h - 58*mm
    band_height = 36*mm
    c.setFillColor(surface)
    c.rect(margin, band_bottom, w - 2*margin, band_height, fill=1, stroke=0)
    c.setStrokeColor(accent)
    c.setLineWidth(0.5)
    c.line(margin, band_bottom, w - margin, band_bottom)

    c.setFillColor(paper)
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(w / 2, h - 34*mm, "TROVEE")
    c.setFillColor(accent)
    c.setFont("Helvetica", 10)
    c.drawCentredString(w / 2, h - 41*mm, "INVESTMENT PLATFORM")

    title_y = h - 72*mm
    c.setFillColor(accent)
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(w / 2, title_y, "CERTIFICATE OF SHARE OWNERSHIP")

    line_y = title_y - 4*mm
    c.setStrokeColor(accent)
    c.setLineWidth(1)
    c.line(w/2 - 60*mm, line_y, w/2 + 60*mm, line_y)
    c.setStrokeColor(accent_dim)
    c.setLineWidth(0.4)
    c.line(w/2 - 45*mm, line_y - 2*mm, w/2 + 45*mm, line_y - 2*mm)

    y = line_y - 14*mm

    c.setFillColor(slate_soft)
    c.setFont("Helvetica", 9)
    c.drawCentredString(w / 2, y, "THIS CERTIFIES THAT")
    y -= 9*mm
    c.setFillColor(paper)
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(w / 2, y, p["username"])

    y -= 16*mm
    c.setFillColor(slate_soft)
    c.setFont("Helvetica", 9)
    c.drawCentredString(w / 2, y, "IS THE REGISTERED HOLDER OF")

    y -= 19*mm
    c.setFillColor(accent)
    c.setFont("Helvetica-Bold", 32)
    c.drawCentredString(w / 2, y, f"{p['shares_count']:,}")

    y -= 8*mm
    c.setFillColor(paper)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(w / 2, y, "SHARES")

    y -= 13*mm
    c.setFillColor(slate_soft)
    c.setFont("Helvetica", 9)
    c.drawCentredString(w / 2, y, "IN")

    y -= 11*mm
    c.setFillColor(paper)
    c.setFont("Helvetica-Bold", 19)
    c.drawCentredString(w / 2, y, p["company_name"])

    y -= 7*mm
    c.setFillColor(slate_soft)
    c.setFont("Helvetica", 9)
    c.drawCentredString(w / 2, y, f"({p['ticker']})  ·  {p['sector']}")

    y -= 14*mm
    grid_h = 26*mm
    grid_y = y - grid_h
    c.setFillColor(surface)
    c.roundRect(20*mm, grid_y, w - 40*mm, grid_h, 4*mm, fill=1, stroke=0)

    col_w = (w - 40*mm) / 4
    info_items = [
        ("Plan", p["plan_name"]),
        ("Return Rate", f"{p['return_rate_pct']:.1f}% p.a."),
        ("Duration", f"{p['duration_months']} months"),
        ("Investment", f"${p['price_usd_cents']/100:,.2f}"),
    ]
    for i, (lbl, val) in enumerate(info_items):
        cx = 20*mm + col_w * i + col_w / 2
        c.setFillColor(slate_soft)
        c.setFont("Helvetica", 8)
        c.drawCentredString(cx, grid_y + 16*mm, lbl.upper())
        c.setFillColor(accent)
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(cx, grid_y + 8*mm, val)

    y = grid_y - 13*mm

    c.setFillColor(slate_soft)
    c.setFont("Helvetica", 8)
    c.drawCentredString(w / 2, y, "CERTIFICATE NO.")
    y -= 6*mm
    c.setFillColor(paper)
    c.setFont("Courier-Bold", 13)
    c.drawCentredString(w / 2, y, p["certificate_id"])

    y -= 15*mm

    date_str = p["purchased_at"][:10]
    left_cx = w / 4
    right_cx = 3 * w / 4
    c.setFillColor(slate_soft)
    c.setFont("Helvetica", 8)
    c.drawCentredString(left_cx, y, "DATE OF ISSUE")
    c.drawCentredString(right_cx, y, "ACCOUNT EMAIL")
    y -= 6*mm
    c.setFillColor(paper)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(left_cx, y, date_str)
    c.drawCentredString(right_cx, y, p["email"])

    y -= 14*mm

    c.setStrokeColor(accent_dim)
    c.setLineWidth(0.5)
    c.line(w/2 - 40*mm, y, w/2 + 40*mm, y)
    c.setFillColor(slate_soft)
    c.setFont("Helvetica", 8)
    c.drawCentredString(w / 2, y - 5*mm, "AUTHORIZED SIGNATORY  ·  TROVEE INVESTMENT PLATFORM")

    c.setFillColor(colors.HexColor("#5B6573"))
    c.setFont("Helvetica", 7.5)
    footer_text = ("This certificate is issued by Trovee Investment Platform and confirms share ownership. "
                   "This is a digital investment certificate. For queries, contact support.")
    c.drawCentredString(w / 2, 20*mm, footer_text)

    c.save()
    buf.seek(0)

    from flask import send_file
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"Trovee-Certificate-{cert_id}.pdf"
    )


def _process_matured_purchases(db, user_id: int) -> list:
    from datetime import datetime
    today = datetime.utcnow().strftime("%Y-%m-%d")
    matured = db.execute(
        "SELECT * FROM share_purchases "
        "WHERE user_id = ? AND status = 'active' AND maturity_date <= ?",
        (user_id, today)
    ).fetchall()
    newly_paid = []
    for p in matured:
        p = dict(p)
        db.execute("UPDATE users SET balance_usd_cents = balance_usd_cents + ? WHERE id = ?",
                   (p["total_payout_cents"], user_id))
        db.execute("UPDATE share_purchases SET status = 'paid', paid_at = ? WHERE id = ?",
                   (datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), p["id"]))
        newly_paid.append(p)
    if newly_paid:
        db.commit()
    return newly_paid


# ─── API: Admin — Share Companies and Plans ──────────────────

@app.route("/api/admin/shares/companies", methods=["GET"])
@admin_required
def api_admin_shares_companies():
    db = get_db()
    companies = db.execute("SELECT * FROM share_companies ORDER BY name").fetchall()
    db.close()
    return jsonify({"companies": [dict(c) for c in companies]})


@app.route("/api/admin/shares/companies", methods=["POST"])
@admin_required
def api_admin_shares_company_create():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    ticker = (data.get("ticker") or "").strip().upper()
    description = (data.get("description") or "").strip()
    logo_url = (data.get("logo_url") or "").strip()
    sector = (data.get("sector") or "").strip()

    if not name or not ticker:
        return jsonify({"error": "Company name and ticker are required."}), 400

    db = get_db()
    existing = db.execute("SELECT id FROM share_companies WHERE name = ?", (name,)).fetchone()
    if existing:
        db.close()
        return jsonify({"error": "A company with that name already exists."}), 409
    cur = db.execute(
        "INSERT INTO share_companies (name, ticker, description, logo_url, sector) VALUES (?, ?, ?, ?, ?)",
        (name, ticker, description, logo_url, sector)
    )
    db.commit()
    db.close()
    return jsonify({"message": "Company created.", "id": cur.lastrowid})


@app.route("/api/admin/shares/companies/<int:company_id>", methods=["PUT"])
@admin_required
def api_admin_shares_company_update(company_id):
    data = request.get_json(force=True) or {}
    db = get_db()
    db.execute(
        "UPDATE share_companies SET name=?, ticker=?, description=?, logo_url=?, sector=?, is_active=? WHERE id=?",
        (data.get("name"), data.get("ticker", "").upper(), data.get("description", ""),
         data.get("logo_url", ""), data.get("sector", ""), 1 if data.get("is_active", True) else 0, company_id)
    )
    db.commit()
    db.close()
    return jsonify({"message": "Company updated."})


@app.route("/api/admin/shares/companies/<int:company_id>", methods=["DELETE"])
@admin_required
def api_admin_shares_company_delete(company_id):
    db = get_db()
    company = db.execute("SELECT id FROM share_companies WHERE id = ?", (company_id,)).fetchone()
    if not company:
        db.close()
        return jsonify({"error": "Company not found."}), 404
    db.execute("UPDATE share_plans SET is_active = 0 WHERE company_id = ?", (company_id,))
    purchases = db.execute(
        "SELECT COUNT(*) as n FROM share_purchases WHERE company_id = ?", (company_id,)
    ).fetchone()["n"]
    if purchases > 0:
        db.execute("UPDATE share_companies SET is_active = 0 WHERE id = ?", (company_id,))
        db.commit()
        db.close()
        return jsonify({"message": "Company deactivated (has existing purchases — records preserved).", "soft_delete": True})
    db.execute("DELETE FROM share_companies WHERE id = ?", (company_id,))
    db.commit()
    db.close()
    return jsonify({"message": "Company deleted.", "soft_delete": False})


@app.route("/api/admin/shares/companies/<int:company_id>/plans", methods=["GET"])
@admin_required
def api_admin_shares_company_plans(company_id):
    db = get_db()
    plans = db.execute("SELECT * FROM share_plans WHERE company_id = ? ORDER BY price_usd_cents", (company_id,)).fetchall()
    db.close()
    return jsonify({"plans": [dict(p) for p in plans]})


@app.route("/api/admin/shares/plans", methods=["POST"])
@admin_required
def api_admin_shares_plan_create():
    data = request.get_json(force=True) or {}
    company_id = data.get("company_id")
    plan_name = (data.get("plan_name") or "").strip()
    shares_count = data.get("shares_count")
    price_usd = data.get("price_usd")
    return_rate = data.get("return_rate_pct", 12.0)
    duration = data.get("duration_months", 12)

    if not all([company_id, plan_name, shares_count, price_usd]):
        return jsonify({"error": "All fields required."}), 400

    db = get_db()
    cur = db.execute(
        "INSERT INTO share_plans (company_id, plan_name, shares_count, price_usd_cents, return_rate_pct, duration_months) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (company_id, plan_name, int(shares_count), int(float(price_usd) * 100), float(return_rate), int(duration))
    )
    db.commit()
    db.close()
    return jsonify({"message": "Plan created.", "id": cur.lastrowid})


@app.route("/api/admin/shares/plans/<int:plan_id>", methods=["DELETE"])
@admin_required
def api_admin_shares_plan_delete(plan_id):
    db = get_db()
    db.execute("UPDATE share_plans SET is_active = 0 WHERE id = ?", (plan_id,))
    db.commit()
    db.close()
    return jsonify({"message": "Plan removed."})


@app.route("/api/admin/shares/purchases", methods=["GET"])
@admin_required
def api_admin_shares_purchases():
    from datetime import datetime
    db = get_db()
    rows = db.execute(
        "SELECT sp.*, u.username, u.email, c.name as company_name "
        "FROM share_purchases sp "
        "JOIN users u ON u.id = sp.user_id "
        "JOIN share_companies c ON c.id = sp.company_id "
        "ORDER BY sp.purchased_at DESC"
    ).fetchall()
    db.close()

    today = datetime.utcnow()
    purchases = []
    for r in rows:
        p = dict(r)
        try:
            mat = datetime.strptime(p["maturity_date"], "%Y-%m-%d")
            p["days_remaining"] = max(0, (mat - today).days)
            p["is_overdue"] = p["status"] == "active" and mat < today
        except Exception:
            p["days_remaining"] = 0
            p["is_overdue"] = False
        purchases.append(p)

    return jsonify({"purchases": purchases})


@app.route("/api/admin/shares/purchases/<int:purchase_id>/payout", methods=["POST"])
@admin_required
def api_admin_shares_payout(purchase_id):
    from datetime import datetime
    db = get_db()
    p = db.execute(
        "SELECT sp.*, u.balance_usd_cents "
        "FROM share_purchases sp JOIN users u ON u.id = sp.user_id "
        "WHERE sp.id = ?", (purchase_id,)
    ).fetchone()
    if not p:
        db.close()
        return jsonify({"error": "Purchase not found."}), 404
    p = dict(p)
    if p["status"] == "paid":
        db.close()
        return jsonify({"error": "Returns already credited for this purchase."}), 400

    db.execute("UPDATE users SET balance_usd_cents = balance_usd_cents + ? WHERE id = ?",
               (p["total_payout_cents"], p["user_id"]))
    db.execute("UPDATE share_purchases SET status = 'paid', paid_at = ? WHERE id = ?",
               (datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), purchase_id))
    db.commit()
    db.close()
    return jsonify({
        "message": "Returns credited successfully.",
        "total_payout_cents": p["total_payout_cents"],
    })


# ─── API: Admin — Wallet Configs ─────────────────────────────

@app.route("/api/admin/wallets", methods=["GET"])
@admin_required
def api_admin_wallets_get():
    db = get_db()
    rows = db.execute("SELECT * FROM wallet_configs ORDER BY sort_order, id").fetchall()
    db.close()
    return jsonify({"wallets": [dict(r) for r in rows]})


@app.route("/api/admin/wallets", methods=["POST"])
@admin_required
def api_admin_wallets_add():
    data = request.get_json(force=True) or {}
    display_name = (data.get("display_name") or "").strip()
    address = (data.get("address") or "").strip()
    qr_url = (data.get("qr_url") or "").strip()
    sort_order = int(data.get("sort_order") or 0)

    if not display_name or not address:
        return jsonify({"error": "Name and address are required."}), 400

    db = get_db()
    logo_url = (data.get("logo_url") or "").strip()
    cur = db.execute(
        "INSERT INTO wallet_configs (display_name, address, logo_url, qr_url, sort_order) VALUES (?, ?, ?, ?, ?)",
        (display_name, address, logo_url, qr_url, sort_order)
    )
    wid = cur.lastrowid
    db.commit()
    db.close()
    return jsonify({"id": wid, "message": "Wallet added."})


@app.route("/api/admin/wallets/<int:wallet_id>", methods=["PUT"])
@admin_required
def api_admin_wallets_update(wallet_id):
    data = request.get_json(force=True) or {}
    display_name = (data.get("display_name") or "").strip()
    address = (data.get("address") or "").strip()
    logo_url = (data.get("logo_url") or "").strip()
    qr_url = (data.get("qr_url") or "").strip()
    sort_order = int(data.get("sort_order") or 0)
    is_active = int(bool(data.get("is_active", True)))

    if not display_name or not address:
        return jsonify({"error": "Name and address are required."}), 400

    db = get_db()
    db.execute(
        "UPDATE wallet_configs SET display_name=?, address=?, logo_url=?, qr_url=?, sort_order=?, is_active=? WHERE id=?",
        (display_name, address, logo_url, qr_url, sort_order, is_active, wallet_id)
    )
    db.commit()
    db.close()
    return jsonify({"message": "Wallet updated."})


@app.route("/api/admin/wallets/<int:wallet_id>", methods=["DELETE"])
@admin_required
def api_admin_wallets_delete(wallet_id):
    db = get_db()
    db.execute("DELETE FROM wallet_configs WHERE id = ?", (wallet_id,))
    db.commit()
    db.close()
    return jsonify({"message": "Wallet deleted."})


@app.route("/api/admin/currencies", methods=["GET"])
@admin_required
def api_admin_currencies():
    db = get_db()
    users = db.execute("""
        SELECT id, email, username, country_code, currency_code, balance_usd_cents
        FROM users
        ORDER BY created_at DESC
    """).fetchall()
    db.close()
    result = []
    for u in users:
        _, symbol, _ = get_currency_for_country(u["country_code"])
        balance_local = convert_usd_cents(u["balance_usd_cents"], u["currency_code"])
        result.append({
            "id": u["id"],
            "email": u["email"],
            "username": u["username"],
            "currency_code": u["currency_code"],
            "currency_symbol": symbol,
            "balance_local": balance_local,
        })
    return jsonify({"users": result})


@app.route("/api/admin/currencies/migrate", methods=["POST"])
@admin_required
def api_admin_currencies_migrate():
    data = request.get_json() or {}
    user_id = data.get("user_id")
    new_currency = data.get("currency_code")

    if not user_id or not new_currency:
        return jsonify({"error": "user_id and currency_code required"}), 400

    if new_currency not in USD_EXCHANGE_RATES:
        return jsonify({"error": f"Currency {new_currency} not supported"}), 400

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    old_currency = user["currency_code"]
    if old_currency == new_currency:
        db.close()
        return jsonify({"error": "Same currency, no migration needed"}), 400

    db.execute(
        "UPDATE users SET currency_code = ? WHERE id = ?",
        (new_currency, user_id)
    )
    db.commit()
    db.close()

    return jsonify({
        "message": f"Currency migrated from {old_currency} to {new_currency}",
        "user_id": user_id,
        "old_currency": old_currency,
        "new_currency": new_currency,
    })


@app.route("/api/admin/currencies/migrate-bulk", methods=["POST"])
@admin_required
def api_admin_currencies_migrate_bulk():
    data = request.get_json() or {}
    from_currency = data.get("from_currency")
    to_currency = data.get("to_currency")

    if not from_currency or not to_currency:
        return jsonify({"error": "from_currency and to_currency required"}), 400

    if to_currency not in USD_EXCHANGE_RATES:
        return jsonify({"error": f"Currency {to_currency} not supported"}), 400

    db = get_db()
    users = db.execute(
        "SELECT id FROM users WHERE currency_code = ?", (from_currency,)
    ).fetchall()

    if not users:
        db.close()
        return jsonify({"message": f"No users found with currency {from_currency}.", "migrated_count": 0})

    db.execute(
        "UPDATE users SET currency_code = ? WHERE currency_code = ?",
        (to_currency, from_currency)
    )
    db.commit()
    db.close()

    return jsonify({
        "message": f"Migrated {len(users)} user(s) from {from_currency} to {to_currency}.",
        "migrated_count": len(users),
        "from_currency": from_currency,
        "to_currency": to_currency,
    })


# ─── Error Handlers ──────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": f"Route not found: {request.method} {request.path}"}), 404
    return e


@app.errorhandler(405)
def method_not_allowed(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": f"Method {request.method} not allowed on {request.path}"}), 405
    return e


@app.errorhandler(400)
def bad_request(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Invalid or missing JSON body."}), 400
    return e


@app.errorhandler(500)
def internal_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Internal server error. Please try again."}), 500
    return e


@app.errorhandler(Exception)
def handle_unexpected(e):
    print(f"[trovee] UNHANDLED ERROR: {type(e).__name__}: {e}")
    traceback.print_exc()
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        if request.path.startswith("/api/"):
            return jsonify({"error": e.description or str(e)}), e.code
        return e
    if request.path.startswith("/api/"):
        return jsonify({"error": "Something went wrong. Please try again."}), 500
    raise e


print("[trovee] app.py loaded — all routes registered")

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
