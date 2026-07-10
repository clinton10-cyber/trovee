"""
Trovee database layer — supports both SQLite and PostgreSQL.
Now with detailed logging for debugging and bandwidth monetization.
"""

import os
import sqlite3

DATABASE_URL = os.environ.get("TROVEE_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
USE_POSTGRES = bool(DATABASE_URL)

_default_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "trovee.db")
DB_PATH = os.environ.get("TROVEE_DB_PATH", _default_db)
if not USE_POSTGRES and not os.path.exists(os.path.dirname(DB_PATH)):
    DB_PATH = "/tmp/trovee.db"

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def get_db():
    if USE_POSTGRES:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        conn.autocommit = False
        return _PgWrapper(conn)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


class _PgWrapper:
    def __init__(self, conn):
        self._conn = conn
        self._cur = conn.cursor()
        self._last_insert_id = None

    def execute(self, sql, params=()):
        pg_sql = sql.replace("?", "%s")
        pg_sql = pg_sql.replace("datetime('now')", "now()")

        if "INSERT" in pg_sql.upper():
            if "INSERT OR IGNORE" in pg_sql.upper():
                pg_sql = pg_sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
                if "ON CONFLICT" not in pg_sql.upper():
                    pg_sql += " ON CONFLICT DO NOTHING"
            elif "INSERT OR REPLACE" in pg_sql.upper():
                pg_sql = pg_sql.replace("INSERT OR REPLACE INTO", "INSERT INTO")

        if pg_sql.strip().upper().startswith("INSERT") and "RETURNING" not in pg_sql.upper():
            pg_sql += " RETURNING id"

        self._cur.execute(pg_sql, params)

        if pg_sql.strip().upper().startswith("INSERT"):
            row = self._cur.fetchone()
            self._last_insert_id = row["id"] if row else None
        else:
            self._last_insert_id = None

        return self

    def fetchone(self):
        row = self._cur.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(r) for r in self._cur.fetchall()]

    @property
    def lastrowid(self):
        return self._last_insert_id

    def commit(self):
        self._conn.commit()

    def close(self):
        self._cur.close()
        self._conn.close()


def _schema_for_postgres(sql: str) -> str:
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    sql = sql.replace("INTEGER PRIMARY KEY", "INTEGER PRIMARY KEY")
    sql = sql.replace("datetime('now')", "now()")
    lines = sql.split("\n")
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("INSERT INTO share_companies") or \
           stripped.startswith("INSERT INTO share_plans") or \
           stripped.startswith("INSERT OR IGNORE INTO admin_settings") or \
           stripped.startswith("INSERT INTO admin_settings"):
            continue
        out.append(line)
    return "\n".join(out)


def init_db():
    with open(SCHEMA_PATH, "r") as f:
        schema = f.read()

    if USE_POSTGRES:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cur = conn.cursor()
        pg_schema = _schema_for_postgres(schema)
        for stmt in pg_schema.split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    cur.execute(stmt)
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        print(f"[trovee] DB init warning: {e}")
        _migrate_postgres(cur)
        cur.close()
        _seed_defaults(conn)
        conn.close()
        print(f"[trovee] PostgreSQL database initialized.")
    else:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        schema_lines = schema.split("\n")
        clean_schema = "\n".join(
            line for line in schema_lines
            if not line.strip().startswith("INSERT INTO share_companies")
            and not line.strip().startswith("INSERT INTO share_plans")
            and not line.strip().startswith("INSERT OR IGNORE INTO admin_settings")
            and not line.strip().startswith("INSERT INTO admin_settings")
        )
        conn.executescript(clean_schema)
        _migrate_sqlite(conn)
        _seed_defaults(conn)
        conn.commit()
        conn.close()
        print(f"[trovee] SQLite database initialized at {DB_PATH}")


def _seed_defaults(conn):
    """
    Insert default wallets and share companies/plans with logos and QR codes.
    Progressive plans from $100 to $20,000+ for each company.
    """
    cur = conn.cursor()

    def insert_wallet(name, address, logo, qr, order):
        if USE_POSTGRES:
            cur.execute("SELECT id FROM wallet_configs WHERE display_name = %s", (name,))
        else:
            cur.execute("SELECT id FROM wallet_configs WHERE display_name = ?", (name,))
        if cur.fetchone() is not None:
            return
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO wallet_configs (display_name, address, logo_url, qr_url, sort_order) "
                "VALUES (%s, %s, %s, %s, %s)",
                (name, address, logo, qr, order)
            )
        else:
            cur.execute(
                "INSERT INTO wallet_configs (display_name, address, logo_url, qr_url, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, address, logo, qr, order)
            )

    # ─── Wallets ──────────────────────────────────────────────────
    wallets = [
        ("Bitcoin (BTC)", "bc1qegwjs26n6pt5mh0xlmpawkme98scdgn5al3wak",
         "https://assets.coingecko.com/coins/images/1/small/bitcoin.png",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=bc1qegwjs26n6pt5mh0xlmpawkme98scdgn5al3wak", 1),
        ("USDT TRC20", "TW6qVWsbPZ5fLneWanmkLH8mEVX1GMUYSn",
         "https://assets.coingecko.com/coins/images/325/small/Tether.png",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=TW6qVWsbPZ5fLneWanmkLH8mEVX1GMUYSn", 2),
        ("USDT ERC20", "0x6b916003441cdBe5b6d5FC947f38a25de234EeD6",
         "https://assets.coingecko.com/coins/images/325/small/Tether.png",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=0x6b916003441cdBe5b6d5FC947f38a25de234EeD6", 3),
        ("USDT Solana", "H8M9MvUBQkSfkR8QpQdjhBDKbgGXv52P2UjvC3rTRp8K",
         "https://assets.coingecko.com/coins/images/325/small/Tether.png",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=H8M9MvUBQkSfkR8QpQdjhBDKbgGXv52P2UjvC3rTRp8K", 4),
        ("Ethereum (ETH)", "0x6b916003441cdBe5b6d5FC947f38a25de234EeD6",
         "https://assets.coingecko.com/coins/images/279/small/ethereum.png",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=0x6b916003441cdBe5b6d5FC947f38a25de234EeD6", 5),
        ("Solana (SOL)", "H8M9MvUBQkSfkR8QpQdjhBDKbgGXv52P2UjvC3rTRp8K",
         "https://assets.coingecko.com/coins/images/4128/small/solana.png",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=H8M9MvUBQkSfkR8QpQdjhBDKbgGXv52P2UjvC3rTRp8K", 6),
        ("TON (Toncoin)", "UQBNib_qibCqn25M22ln5CToop4SAxBlHiQ0pouCkPj6ST2j",
         "https://assets.coingecko.com/coins/images/17980/small/ton.png",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=UQBNib_qibCqn25M22ln5CToop4SAxBlHiQ0pouCkPj6ST2j", 7),
        ("BNB (BSC)", "0x6b916003441cdBe5b6d5FC947f38a25de234EeD6",
         "https://assets.coingecko.com/coins/images/825/small/bnb-icon2_2x.png",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=0x6b916003441cdBe5b6d5FC947f38a25de234EeD6", 8),
        ("Litecoin (LTC)", "ltc1q7vyp9egglg2jzzfjy82cffkf5lpepzj92xwpxl",
         "https://assets.coingecko.com/coins/images/2/small/litecoin.png",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=ltc1q7vyp9egglg2jzzfjy82cffkf5lpepzj92xwpxl", 9),
    ]
    for w in wallets:
        insert_wallet(*w)

    # ─── Share Companies ─────────────────────────────────────────
    companies = [
        ("Tesla, Inc.", "TSLA",
         "Electric vehicles and clean energy",
         "https://upload.wikimedia.org/wikipedia/commons/thumb/b/bd/Tesla_Motors.svg/200px-Tesla_Motors.svg.png",
         "Automotive"),
        ("NVIDIA Corporation", "NVDA",
         "Graphics processing units and AI",
         "https://upload.wikimedia.org/wikipedia/commons/thumb/2/21/Nvidia_logo.svg/200px-Nvidia_logo.svg.png",
         "Technology"),
        ("Microsoft Corporation", "MSFT",
         "Software and cloud computing",
         "https://upload.wikimedia.org/wikipedia/commons/thumb/9/96/Microsoft_logo_%282012%29.svg/200px-Microsoft_logo_%282012%29.svg.png",
         "Technology"),
        ("Apple Inc.", "AAPL",
         "Consumer electronics and software",
         "https://upload.wikimedia.org/wikipedia/commons/thumb/f/fa/Apple_logo_black.svg/200px-Apple_logo_black.svg.png",
         "Technology"),
    ]
    company_ids = {}
    for name, ticker, desc, logo, sector in companies:
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO share_companies (name, ticker, description, logo_url, sector) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (name) DO NOTHING RETURNING id",
                (name, ticker, desc, logo, sector)
            )
            row = cur.fetchone()
            if row:
                company_ids[name] = row[0]
            else:
                cur.execute("SELECT id FROM share_companies WHERE name = %s", (name,))
                row = cur.fetchone()
                company_ids[name] = row[0] if row else None
        else:
            cur.execute(
                "INSERT OR IGNORE INTO share_companies (name, ticker, description, logo_url, sector) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, ticker, desc, logo, sector)
            )
            cur.execute("SELECT id FROM share_companies WHERE name = ?", (name,))
            row = cur.fetchone()
            company_ids[name] = row[0] if row else None

    # ─── Helper to insert a plan ────────────────────────────────
    def insert_plan(company_name, plan_name, shares, price_usd, rate, months):
        tid = company_ids.get(company_name)
        if not tid:
            return
        price_cents = int(price_usd * 100)
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO share_plans (company_id, plan_name, shares_count, price_usd_cents, return_rate_pct, duration_months) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (company_id, plan_name) DO NOTHING",
                (tid, plan_name, shares, price_cents, rate, months)
            )
        else:
            cur.execute(
                "INSERT OR IGNORE INTO share_plans (company_id, plan_name, shares_count, price_usd_cents, return_rate_pct, duration_months) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (tid, plan_name, shares, price_cents, rate, months)
            )

    # ─── Progressive Plans (for all companies) ──────────────────
    # These are inserted first so they appear at the top of the list
    progressive_plans = [
        ("Starter", 1, 100, 8.0, 6),
        ("Basic", 5, 500, 9.0, 6),
        ("Silver", 10, 1000, 10.0, 12),
        ("Gold", 25, 2500, 12.0, 12),
        ("Platinum", 50, 5000, 14.0, 18),
        ("Diamond", 100, 10000, 16.0, 18),
        ("Elite", 200, 20000, 18.0, 24),
    ]

    # Insert progressive plans for all companies
    for company in companies:
        for plan_name, shares, price_usd, rate, months in progressive_plans:
            insert_plan(company[0], plan_name, shares, price_usd, rate, months)

    # ─── Company-Specific High-End Plans ──────────────────────

    # Tesla: car models (continued from progressive plans)
    tesla_plans = [
        ("Model 3", 10, 45000, 12.0, 12),
        ("Model Y", 15, 55000, 13.5, 12),
        ("Model S", 20, 75000, 15.0, 18),
        ("Model X", 25, 90000, 16.0, 18),
        ("Cybertruck", 30, 100000, 18.0, 24),
    ]
    for plan_name, shares, price_usd, rate, months in tesla_plans:
        insert_plan("Tesla, Inc.", plan_name, shares, price_usd, rate, months)

    # NVIDIA
    nv_plans = [
        ("Growth", 12, 50000, 14.0, 12),
        ("Premium", 25, 100000, 18.0, 18),
        ("Enterprise", 50, 200000, 22.0, 24),
    ]
    for plan_name, shares, price_usd, rate, months in nv_plans:
        insert_plan("NVIDIA Corporation", plan_name, shares, price_usd, rate, months)

    # Microsoft
    ms_plans = [
        ("Growth", 15, 60000, 15.0, 12),
        ("Premium", 30, 120000, 19.0, 18),
        ("Enterprise", 60, 250000, 23.0, 24),
    ]
    for plan_name, shares, price_usd, rate, months in ms_plans:
        insert_plan("Microsoft Corporation", plan_name, shares, price_usd, rate, months)

    # Apple
    aa_plans = [
        ("Growth", 18, 70000, 14.5, 12),
        ("Premium", 35, 140000, 18.5, 18),
        ("Enterprise", 70, 280000, 22.5, 24),
    ]
    for plan_name, shares, price_usd, rate, months in aa_plans:
        insert_plan("Apple Inc.", plan_name, shares, price_usd, rate, months)

    conn.commit()


def _migrate_sqlite(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wallet_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT NOT NULL UNIQUE,
            address TEXT NOT NULL,
            logo_url TEXT DEFAULT '',
            qr_url TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    migrations = [
        ("share_purchases", "plan_name", "TEXT DEFAULT ''"),
        ("share_purchases", "return_rate_pct", "REAL DEFAULT 0"),
        ("share_purchases", "duration_months", "INTEGER DEFAULT 12"),
        ("share_purchases", "return_usd_cents", "INTEGER DEFAULT 0"),
        ("share_purchases", "total_payout_cents", "INTEGER DEFAULT 0"),
        ("share_purchases", "maturity_date", "TEXT DEFAULT ''"),
        ("share_purchases", "paid_at", "TEXT"),
        ("wallet_configs", "logo_url", "TEXT DEFAULT ''"),
        ("wallet_configs", "qr_url", "TEXT DEFAULT ''"),
        ("users", "bandwidth_consent", "INTEGER DEFAULT 0"),
        ("users", "bandwidth_providers", "TEXT DEFAULT ''"),
        ("users", "bandwidth_earnings", "TEXT DEFAULT '{}'"),
    ]
    existing = {(row[0], row[1]) for row in conn.execute(
        "SELECT m.name, p.name FROM sqlite_master m "
        "JOIN pragma_table_info(m.name) p WHERE m.type='table'"
    ).fetchall()}
    for table, col, col_def in migrations:
        if (table, col) not in existing:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
                print(f"[trovee] Migration: added {table}.{col}")
            except Exception as e:
                print(f"[trovee] Migration warning ({table}.{col}): {e}")


def _migrate_postgres(cur):
    migrations = [
        ("share_purchases", "plan_name", "TEXT NOT NULL DEFAULT ''"),
        ("share_purchases", "return_rate_pct", "REAL NOT NULL DEFAULT 0"),
        ("share_purchases", "duration_months", "INTEGER NOT NULL DEFAULT 12"),
        ("share_purchases", "return_usd_cents", "INTEGER NOT NULL DEFAULT 0"),
        ("share_purchases", "total_payout_cents", "INTEGER NOT NULL DEFAULT 0"),
        ("share_purchases", "maturity_date", "TEXT NOT NULL DEFAULT ''"),
        ("share_purchases", "paid_at", "TEXT"),
        ("wallet_configs", "logo_url", "TEXT DEFAULT ''"),
        ("wallet_configs", "qr_url", "TEXT DEFAULT ''"),
        ("users", "bandwidth_consent", "INTEGER DEFAULT 0"),
        ("users", "bandwidth_providers", "TEXT DEFAULT ''"),
        ("users", "bandwidth_earnings", "TEXT DEFAULT '{}'"),
    ]
    for table, col, col_def in migrations:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
            print(f"[trovee] Migration: added {table}.{col}")
        except Exception:
            pass


if __name__ == "__main__":
    init_db()
