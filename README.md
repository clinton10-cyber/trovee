# Trovee

A legitimate micro-task earnings and investment web app. Users complete short surveys and watch sponsored videos, earn real fixed payouts, invest in company share plans with downloadable PDF certificates, and withdraw via bank transfer, mobile money, PayPal, or crypto. Supports 150+ countries with automatic local currency detection.

---

## Quick start (local development)

```
cd trovee
pip install flask PyJWT reportlab
cp .env.example .env        # fill in your values (see below)
bash start.sh
# Open http://localhost:5000
```

---

## One-time Gmail setup (required for OTP and support emails)

1. Go to **myaccount.google.com/security** and turn on **2-Step Verification** for `workspace4568@gmail.com`.
2. Go to **myaccount.google.com/apppasswords**.
3. Create a new app password: App = Mail, Device = Other, Name = Trovee.
4. Copy the 16-character password Google shows you.
5. Paste it into `.env` as `TROVEE_GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx`.

That is the only credential setup required. All OTP codes and support tickets will now flow through that Gmail.

---

## Environment variables

| Variable | Description |
|---|---|
| `TROVEE_SENDER_EMAIL` | Gmail address that sends OTPs |
| `TROVEE_GMAIL_APP_PASSWORD` | 16-char App Password from Google |
| `TROVEE_ADMIN_EMAIL` | Where support ticket emails are delivered |
| `TROVEE_APP_SECRET` | Secret for signing JWT session tokens |
| `TROVEE_OTP_HASH_SECRET` | Secret for hashing OTP codes at rest |
| `TROVEE_ADMIN_PASSWORD` | Password for the /admin panel |

---

## Pages

| URL | Description |
|---|---|
| `/` | Landing page |
| `/signup` | Create account (username, Gmail, phone, password + OTP) |
| `/login` | Log in |
| `/dashboard` | Balance, daily progress, task preview |
| `/tasks` | Full task list with completion flow |
| `/withdraw` | Request withdrawal, view history |
| `/support` | In-app messaging (relays to your Gmail) |
| `/admin` | Operator panel: tickets, withdrawals, users |

---

## Deployment (Render / Railway / PythonAnywhere)

1. Push this folder to a GitHub repo.
2. On Render: New Web Service, build command `pip install flask PyJWT gunicorn`, start command `gunicorn backend.app:app --bind 0.0.0.0:$PORT`.
3. Add all `.env` variables as environment variables in the Render dashboard.
4. The database file lives at `backend/instance/trovee.db`. For production, mount a persistent disk at `/home/trovee/backend/instance/` so the database survives deploys.

---

## Security notes

- Passwords are hashed with PBKDF2-SHA256 (260,000 rounds) using Python's stdlib `hashlib`. No external bcrypt dependency needed.
- OTP codes are never stored in plaintext. Only an HMAC-SHA256 hash is stored. A leaked database cannot reveal valid codes.
- JWT tokens are signed with HS256 and expire after 30 days.
- The admin panel requires a separate `X-Admin-Token` header, independent of user JWTs.
- All SQL queries use parameterised placeholders (no string interpolation). No SQL injection surface.
- In production, serve over HTTPS and set `SESSION_COOKIE_SECURE=True` in Flask config.

---

## Earning model (transparent, not investment-based)

| Task | Payout | Daily limit |
|---|---|---|
| Survey (4-8 min) | $0.60 - $1.30 | 4 surveys/day |
| Sponsored video (30-60 sec) | $0.08 - $0.15 | 10 videos/day |
| **Daily cap** | **$5.00** | Resets at midnight UTC |
| **Minimum withdrawal** | **$5.00** | Clearly disclosed |

All amounts stored internally in USD cents, displayed in the user's local currency using a fixed FX rate table (swap for a live API in production).
