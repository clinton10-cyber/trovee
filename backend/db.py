"""
Trovee database layer — supports both SQLite and PostgreSQL.
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
    cur = conn.cursor()
    
    # Clear old hardcoded wallets and companies
    try:
        if USE_POSTGRES:
            cur.execute("DELETE FROM share_purchases")
            cur.execute("DELETE FROM share_plans")
            cur.execute("DELETE FROM share_companies")
            cur.execute("DELETE FROM wallet_configs")
        else:
            cur.execute("DELETE FROM share_purchases")
            cur.execute("DELETE FROM share_plans")
            cur.execute("DELETE FROM share_companies")
            cur.execute("DELETE FROM wallet_configs")
    except Exception as e:
        print(f"Cleanup warning: {e}")

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

    wallets = [
        ("Tron (TRX)", "THDIfueyo1qDUgURk1SHBGP7ot1vdL3n0",
         "https://cryptologos.cc/logos/tron-trx-logo.svg",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=THDIfueyo1qDUgURk1SHBGP7ot1vdL3n0", 1),
        ("USDT (BSC)", "0x8cC0E5BD37159D8D136DC95b9ddBa8fb82461aD9",
         "https://cryptologos.cc/logos/tether-usdt-logo.svg",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=0x8cC0E5BD37159D8D136DC95b9ddBa8fb82461aD9", 2),
        ("Solana (SOL)", "B6U7L2orf9yfivdmNPHAPKUH4x8gedkbUUveKtXboovTI",
         "https://cryptologos.cc/logos/solana-sol-logo.svg",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=B6U7L2orf9yfivdmNPHAPKUH4x8gedkbUUveKtXboovTI", 3),
        ("BNB (BSC)", "0x8cC0E5BD37159D8D136DC95b9ddBa8fb82461aD9",
         "https://cryptologos.cc/logos/binance-coin-bnb-logo.svg",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=0x8cC0E5BD37159D8D136DC95b9ddBa8fb82461aD9", 4),
        ("Ethereum (ETH)", "0x8cC0E5BD37159D8D136DC95b9ddBa8fb82461aD9",
         "https://cryptologos.cc/logos/ethereum-eth-logo.svg",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=0x8cC0E5BD37159D8D136DC95b9ddBa8fb82461aD9", 5),
    ]
    for w in wallets:
        insert_wallet(*w)

    companies = [
        ("Apple Inc", "AAPL", "Technology - Smartphones, Computers", "https://logo.clearbit.com/apple.com", "Technology"),
        ("Microsoft Corporation", "MSFT", "Technology - Software, Cloud", "https://logo.clearbit.com/microsoft.com", "Technology"),
        ("Tesla Inc", "TSLA", "Automotive - Electric Vehicles", "https://logo.clearbit.com/tesla.com", "Automotive"),
        ("Amazon.com Inc", "AMZN", "E-commerce - Cloud Services", "https://logo.clearbit.com/amazon.com", "E-commerce"),
        ("Alphabet Inc", "GOOGL", "Technology - Search, Ads", "https://logo.clearbit.com/google.com", "Technology"),
        ("Meta Platforms", "META", "Technology - Social Media", "https://logo.clearbit.com/facebook.com", "Technology"),
        ("NVIDIA Corporation", "NVDA", "Technology - AI Chips", "https://logo.clearbit.com/nvidia.com", "Technology"),
        ("Berkshire Hathaway", "BRK", "Finance - Investment", "https://logo.clearbit.com/berkshirehathaway.com", "Finance"),
        ("JPMorgan Chase", "JPM", "Finance - Banking", "https://logo.clearbit.com/jpmorganchase.com", "Finance"),
        ("Visa Inc", "V", "Finance - Payments", "https://logo.clearbit.com/visa.com", "Finance"),
        ("Mastercard Inc", "MA", "Finance - Payments", "https://logo.clearbit.com/mastercard.com", "Finance"),
        ("Netflix Inc", "NFLX", "Media - Streaming", "https://logo.clearbit.com/netflix.com", "Media"),
        ("Disney Company", "DIS", "Media - Entertainment", "https://logo.clearbit.com/disney.com", "Media"),
        ("Coca-Cola Company", "KO", "Consumer - Beverages", "https://logo.clearbit.com/coca-cola.com", "Consumer"),
        ("McDonald Corporation", "MCD", "Consumer - Food & Beverage", "https://logo.clearbit.com/mcdonalds.com", "Consumer"),
        ("Nike Inc", "NKE", "Consumer - Sportswear", "https://logo.clearbit.com/nike.com", "Consumer"),
        ("Johnson & Johnson", "JNJ", "Healthcare - Pharmaceuticals", "https://logo.clearbit.com/jnj.com", "Healthcare"),
        ("UnitedHealth Group", "UNH", "Healthcare - Insurance", "https://logo.clearbit.com/unitedhealthgroup.com", "Healthcare"),
        ("Pfizer Inc", "PFE", "Healthcare - Pharmaceuticals", "https://logo.clearbit.com/pfizer.com", "Healthcare"),
        ("AbbVie Inc", "ABBV", "Healthcare - Pharmaceuticals", "https://logo.clearbit.com/abbvie.com", "Healthcare"),
        ("Intel Corporation", "INTC", "Technology - Semiconductors", "https://logo.clearbit.com/intel.com", "Technology"),
        ("Qualcomm Inc", "QCOM", "Technology - Semiconductors", "https://logo.clearbit.com/qualcomm.com", "Technology"),
        ("Advanced Micro Devices", "AMD", "Technology - Semiconductors", "https://logo.clearbit.com/amd.com", "Technology"),
        ("Broadcom Inc", "AVGO", "Technology - Semiconductors", "https://logo.clearbit.com/broadcom.com", "Technology"),
        ("Taiwan Semiconductor", "TSM", "Technology - Semiconductors", "https://logo.clearbit.com/tsmc.com", "Technology"),
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

    plan_templates = [
        ("Apple Inc", [("Basic", 10, 15000, 12.0, 12), ("Premium", 50, 75000, 15.0, 24)]),
        ("Microsoft Corporation", [("Basic", 10, 32000, 12.0, 12), ("Premium", 50, 160000, 15.0, 24)]),
        ("Tesla Inc", [("Basic", 10, 24000, 14.0, 12), ("Premium", 50, 120000, 17.0, 24)]),
        ("Amazon.com Inc", [("Basic", 10, 16000, 11.0, 12), ("Premium", 50, 80000, 13.0, 24)]),
        ("Alphabet Inc", [("Basic", 10, 14500, 12.0, 12), ("Premium", 50, 72500, 15.0, 24)]),
        ("Meta Platforms", [("Basic", 10, 32000, 13.0, 12), ("Premium", 50, 160000, 16.0, 24)]),
        ("NVIDIA Corporation", [("Basic", 10, 87000, 16.0, 12), ("Premium", 50, 435000, 19.0, 24)]),
        ("Berkshire Hathaway", [("Basic", 10, 42500, 10.0, 12), ("Premium", 50, 212500, 12.0, 24)]),
        ("JPMorgan Chase", [("Basic", 10, 18000, 11.0, 12), ("Premium", 50, 90000, 13.0, 24)]),
        ("Visa Inc", [("Basic", 10, 25000, 12.0, 12), ("Premium", 50, 125000, 14.0, 24)]),
        ("Mastercard Inc", [("Basic", 10, 18000, 11.0, 12), ("Premium", 50, 90000, 13.0, 24)]),
        ("Netflix Inc", [("Basic", 10, 35000, 13.0, 12), ("Premium", 50, 175000, 15.0, 24)]),
        ("Disney Company", [("Basic", 10, 26000, 12.0, 12), ("Premium", 50, 130000, 14.0, 24)]),
        ("Coca-Cola Company", [("Basic", 10, 6500, 9.0, 12), ("Premium", 50, 32500, 11.0, 24)]),
        ("McDonald Corporation", [("Basic", 10, 8500, 10.0, 12), ("Premium", 50, 42500, 12.0, 24)]),
        ("Nike Inc", [("Basic", 10, 12000, 11.0, 12), ("Premium", 50, 60000, 13.0, 24)]),
        ("Johnson & Johnson", [("Basic", 10, 17000, 11.0, 12), ("Premium", 50, 85000, 13.0, 24)]),
        ("UnitedHealth Group", [("Basic", 10, 16000, 11.0, 12), ("Premium", 50, 80000, 13.0, 24)]),
        ("Pfizer Inc", [("Basic", 10, 5500, 9.0, 12), ("Premium", 50, 27500, 11.0, 24)]),
        ("AbbVie Inc", [("Basic", 10, 6500, 10.0, 12), ("Premium", 50, 32500, 12.0, 24)]),
        ("Intel Corporation", [("Basic", 10, 34000, 13.0, 12), ("Premium", 50, 170000, 15.0, 24)]),
        ("Qualcomm Inc", [("Basic", 10, 16000, 12.0, 12), ("Premium", 50, 80000, 14.0, 24)]),
        ("Advanced Micro Devices", [("Basic", 10, 14000, 12.0, 12), ("Premium", 50, 70000, 14.0, 24)]),
        ("Broadcom Inc", [("Basic", 10, 56000, 14.0, 12), ("Premium", 50, 280000, 16.0, 24)]),
        ("Taiwan Semiconductor", [("Basic", 10, 95000, 15.0, 12), ("Premium", 50, 475000, 17.0, 24)]),
    ]

    for company_name, plans in plan_templates:
        for plan_name, shares, price_usd, rate, months in plans:
            insert_plan(company_name, plan_name, shares, price_usd, rate, months)

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
        ("deposits", "front_image_path", "TEXT"),
        ("deposits", "back_image_path", "TEXT"),
        ("users", "is_support_account", "INTEGER DEFAULT 0"),
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
        ("deposits", "front_image_path", "TEXT"),
        ("deposits", "back_image_path", "TEXT"),
        ("users", "is_support_account", "INTEGER DEFAULT 0"),
    ]
    for table, col, col_def in migrations:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
            print(f"[trovee] Migration: added {table}.{col}")
        except Exception:
            pass


if __name__ == "__main__":
    init_db()
