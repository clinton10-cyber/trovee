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
    purpose TEXT NOT NULL, -- 'signup' or 'login' or 'reset'
    expires_at TEXT NOT NULL,
    attempts INTEGER DEFAULT 0,
    consumed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount_usd_cents INTEGER NOT NULL,
    method TEXT NOT NULL, -- 'bank_transfer', 'mobile_money', 'paypal', 'crypto'
    destination_details TEXT NOT NULL,
    status TEXT DEFAULT 'pending', -- pending, approved, rejected, paid
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
    status TEXT DEFAULT 'open', -- open, replied, closed
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
    direction TEXT NOT NULL,       -- 'up' or 'down'
    duration_sec INTEGER NOT NULL,
    amount_usd_cents INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    outcome TEXT,                  -- 'win' or 'loss' or NULL (open)
    profit_usd_cents INTEGER DEFAULT 0,
    opened_at TEXT DEFAULT (datetime('now')),
    closed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    method TEXT NOT NULL,          -- 'btc' or 'giftcard'
    card_type TEXT,                -- for giftcard
    code TEXT,                     -- gift card code
    value_usd REAL NOT NULL,
    credited_usd_cents INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending', -- pending, confirmed, rejected
    created_at TEXT DEFAULT (datetime('now')),
    reviewed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS admin_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO admin_settings (key, value) VALUES ('btc_wallet_address', '');

-- Share companies and plans (admin-managed)
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
    plan_name TEXT NOT NULL,
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
    shares_count INTEGER NOT NULL,
    price_usd_cents INTEGER NOT NULL,
    certificate_id TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    purchased_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (company_id) REFERENCES share_companies(id),
    FOREIGN KEY (plan_id) REFERENCES share_plans(id)
);

-- Seed some default companies
INSERT OR IGNORE INTO share_companies (id, name, ticker, description, sector) VALUES
(1, 'TechNova Corp', 'TNC', 'Leading AI and cloud infrastructure provider', 'Technology'),
(2, 'GreenEnergy Ltd', 'GEL', 'Renewable energy and sustainable solutions', 'Energy'),
(3, 'FinBridge Inc', 'FBI', 'Digital banking and payment solutions', 'Finance');

INSERT OR IGNORE INTO share_plans (company_id, plan_name, shares_count, price_usd_cents, return_rate_pct, duration_months) VALUES
(1, 'Starter', 10, 10000, 10.0, 6),
(1, 'Growth', 50, 45000, 14.0, 12),
(1, 'Premium', 200, 150000, 18.0, 24),
(2, 'Starter', 10, 8000, 10.0, 6),
(2, 'Growth', 50, 38000, 13.0, 12),
(2, 'Premium', 200, 130000, 17.0, 24),
(3, 'Starter', 10, 12000, 11.0, 6),
(3, 'Growth', 50, 55000, 15.0, 12),
(3, 'Premium', 200, 180000, 20.0, 24);
