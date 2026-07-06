-- Trovee database schema

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    country_code TEXT DEFAULT 'US',
    currency_code TEXT DEFAULT 'USD',
    email_verified INTEGER DEFAULT 0,
    balance_usd_cents INTEGER DEFAULT 0,
    trust_level INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    purpose TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts INTEGER DEFAULT 0,
    consumed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount_usd_cents INTEGER NOT NULL,
    method TEXT NOT NULL,
    destination_details TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    requested_at TEXT DEFAULT (datetime('now')),
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS support_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    subject TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    emailed_ok INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token TEXT UNIQUE NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    asset TEXT NOT NULL,
    direction TEXT NOT NULL,
    duration_sec INTEGER NOT NULL,
    amount_usd_cents INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    outcome TEXT,
    profit_usd_cents INTEGER DEFAULT 0,
    opened_at TEXT DEFAULT (datetime('now')),
    closed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    method TEXT NOT NULL,
    card_type TEXT,
    code TEXT,
    value_usd REAL NOT NULL,
    credited_usd_cents INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    reviewed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS share_companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    ticker TEXT NOT NULL,
    description TEXT,
    logo_url TEXT,
    sector TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS share_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    plan_name TEXT DEFAULT '',
    shares_count INTEGER NOT NULL,
    price_usd_cents INTEGER NOT NULL,
    return_rate_pct REAL DEFAULT 12.0,
    duration_months INTEGER DEFAULT 12,
    is_active INTEGER DEFAULT 1,
    UNIQUE(company_id, plan_name),
    FOREIGN KEY (company_id) REFERENCES share_companies(id)
);

CREATE TABLE IF NOT EXISTS share_purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    company_id INTEGER NOT NULL,
    plan_id INTEGER NOT NULL,
    plan_name TEXT DEFAULT '',
    shares_count INTEGER NOT NULL,
    price_usd_cents INTEGER NOT NULL,
    return_rate_pct REAL DEFAULT 0,
    duration_months INTEGER DEFAULT 12,
    return_usd_cents INTEGER DEFAULT 0,
    total_payout_cents INTEGER DEFAULT 0,
    certificate_id TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    purchased_at TEXT DEFAULT (datetime('now')),
    maturity_date TEXT DEFAULT '',
    paid_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (company_id) REFERENCES share_companies(id),
    FOREIGN KEY (plan_id) REFERENCES share_plans(id)
);

CREATE TABLE IF NOT EXISTS wallet_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    address TEXT NOT NULL,
    logo_url TEXT DEFAULT '',
    qr_url TEXT DEFAULT '',
    sort_order INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);
