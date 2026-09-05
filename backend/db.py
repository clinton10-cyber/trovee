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
    # NOTE: previously this wiped share_purchases/share_plans/share_companies/
    # wallet_configs on every startup. Removed — the inserts below are already
    # idempotent (ON CONFLICT DO NOTHING / INSERT OR IGNORE / upsert), so
    # defaults still get seeded on a fresh DB without erasing real user data
    # (purchases, admin-added wallets, etc.) on every restart.

    # Single source of truth for wallets — upserts on every restart so
    # re-deploys correct stale data instead of creating duplicate rows
    # under a second display_name for the same coin.
    wallets = [
        ("Solana (SOL)", "GFV7t2bFf9yfivdmNPHAPXL4x8gzdkGuLvzKtXbaovTt",
         "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/solana/info/logo.png",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=GFV7t2bFf9yfivdmNPHAPXL4x8gzdkGuLvzKtXbaovTt", 1),
        ("Ethereum (ETH)", "0x8cC0E5BD371592D8D136DC95b94dBaBfb8324a19",
         "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/ethereum/info/logo.png",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=0x8cC0E5BD371592D8D136DC95b94dBaBfb8324a19", 2),
        ("USDT (TRC20)", "TND1fueyo1qFDUgWrk1GKG6P7ot1vdt3nQ",
         "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/tron/assets/TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t/logo.png",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=TND1fueyo1qFDUgWrk1GKG6P7ot1vdt3nQ", 3),
        ("USDT (ERC20)", "0x8cC0E5BD371592D8D136DC95b94dBaBfb8324a19",
         "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/ethereum/assets/0xdAC17F958D2ee523a2206206994597C13D831ec7/logo.png",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=0x8cC0E5BD371592D8D136DC95b94dBaBfb8324a19", 4),
        ("BNB (BEP20)", "0x8cC0E5BD371592D8D136DC95b94dBaBfb8324a19",
         "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/binance/info/logo.png",
         "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=0x8cC0E5BD371592D8D136DC95b94dBaBfb8324a19", 5),
    ]
    for name, address, logo, qr, order in wallets:
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO wallet_configs (display_name, address, logo_url, qr_url, sort_order, is_active) "
                "VALUES (%s, %s, %s, %s, %s, 1) ON CONFLICT (display_name) DO UPDATE SET "
                "address = EXCLUDED.address, logo_url = EXCLUDED.logo_url, "
                "qr_url = EXCLUDED.qr_url, sort_order = EXCLUDED.sort_order, is_active = 1",
                (name, address, logo, qr, order)
            )
        else:
            cur.execute(
                "INSERT INTO wallet_configs (display_name, address, logo_url, qr_url, sort_order, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1) ON CONFLICT (display_name) DO UPDATE SET "
                "address = excluded.address, logo_url = excluded.logo_url, "
                "qr_url = excluded.qr_url, sort_order = excluded.sort_order, is_active = 1",
                (name, address, logo, qr, order)
            )

    companies = [
        ("Tesla Inc", "TSLA", "Automotive - Electric Vehicles", "https://companiesmarketcap.com/img/company-logos/64/tsla.png", "Automotive"),
        ("Microsoft Corporation", "MSFT", "Technology - Software, Cloud", "https://companiesmarketcap.com/img/company-logos/64/msft.png", "Technology"),
        ("Apple Inc", "AAPL", "Technology - Smartphones, Computers", "https://companiesmarketcap.com/img/company-logos/64/aapl.png", "Technology"),
        ("Alphabet Inc", "GOOGL", "Technology - Search, Ads", "https://companiesmarketcap.com/img/company-logos/64/googl.png", "Technology"),
        ("Amazon.com Inc", "AMZN", "E-commerce - Cloud Services", "https://companiesmarketcap.com/img/company-logos/64/amzn.png", "E-commerce"),
        ("NVIDIA Corporation", "NVDA", "Technology - AI Chips", "https://companiesmarketcap.com/img/company-logos/64/nvda.png", "Technology"),
        ("Meta Platforms", "META", "Technology - Social Media", "https://companiesmarketcap.com/img/company-logos/64/meta.png", "Technology"),
        ("Berkshire Hathaway", "BRK", "Finance - Investment", "https://companiesmarketcap.com/img/company-logos/64/brk-a.png", "Finance"),
        ("JPMorgan Chase", "JPM", "Finance - Banking", "https://companiesmarketcap.com/img/company-logos/64/jpm.png", "Finance"),
        ("Visa Inc", "V", "Finance - Payments", "https://companiesmarketcap.com/img/company-logos/64/v.png", "Finance"),
        ("Netflix Inc", "NFLX", "Media - Streaming", "https://companiesmarketcap.com/img/company-logos/64/nflx.png", "Media"),
        ("Disney Company", "DIS", "Media - Entertainment", "https://companiesmarketcap.com/img/company-logos/64/dis.png", "Media"),
        ("Intel Corporation", "INTC", "Technology - Semiconductors", "https://companiesmarketcap.com/img/company-logos/64/intc.png", "Technology"),
        ("Mastercard Inc", "MA", "Finance - Payments", "https://companiesmarketcap.com/img/company-logos/64/ma.png", "Finance"),
        ("Johnson & Johnson", "JNJ", "Healthcare - Pharmaceuticals", "https://companiesmarketcap.com/img/company-logos/64/jnj.png", "Healthcare"),
        ("Coca-Cola Company", "KO", "Consumer - Beverages", "https://companiesmarketcap.com/img/company-logos/64/ko.png", "Consumer"),
        ("Pfizer Inc", "PFE", "Healthcare - Pharmaceuticals", "https://companiesmarketcap.com/img/company-logos/64/pfe.png", "Healthcare"),
        ("Nike Inc", "NKE", "Consumer - Sportswear", "https://companiesmarketcap.com/img/company-logos/64/nke.png", "Consumer"),
        ("UnitedHealth Group", "UNH", "Healthcare - Insurance", "https://companiesmarketcap.com/img/company-logos/64/unh.png", "Healthcare"),
        ("McDonald Corporation", "MCD", "Consumer - Food & Beverage", "https://companiesmarketcap.com/img/company-logos/64/mcd.png", "Consumer"),
        ("Qualcomm Inc", "QCOM", "Technology - Semiconductors", "https://companiesmarketcap.com/img/company-logos/64/qcom.png", "Technology"),
        ("Taiwan Semiconductor", "TSM", "Technology - Semiconductors", "https://companiesmarketcap.com/img/company-logos/64/tsm.png", "Technology"),
        ("Advanced Micro Devices", "AMD", "Technology - Semiconductors", "https://companiesmarketcap.com/img/company-logos/64/amd.png", "Technology"),
        ("Broadcom Inc", "AVGO", "Technology - Semiconductors", "https://companiesmarketcap.com/img/company-logos/64/avgo.png", "Technology"),
        ("AbbVie Inc", "ABBV", "Healthcare - Pharmaceuticals", "https://companiesmarketcap.com/img/company-logos/64/abbv.png", "Healthcare"),
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
        ("Tesla Inc", [("Starter", 1, 50, 10.0, 6), ("Basic", 5, 250, 12.0, 12), ("Premium", 20, 1000, 15.0, 18), ("Elite", 100, 5000, 18.0, 24)]),
        ("Microsoft Corporation", [("Starter", 1, 50, 10.0, 6), ("Basic", 5, 250, 12.0, 12), ("Premium", 20, 1000, 15.0, 18), ("Elite", 100, 5000, 18.0, 24)]),
        ("Apple Inc", [("Starter", 1, 50, 10.0, 6), ("Basic", 5, 250, 12.0, 12), ("Premium", 20, 1000, 15.0, 18), ("Elite", 100, 5000, 18.0, 24)]),
        ("Alphabet Inc", [("Starter", 1, 50, 10.0, 6), ("Basic", 5, 250, 12.0, 12), ("Premium", 20, 1000, 15.0, 18), ("Elite", 100, 5000, 18.0, 24)]),
        ("Amazon.com Inc", [("Starter", 1, 50, 10.0, 6), ("Basic", 5, 250, 12.0, 12), ("Premium", 20, 1000, 15.0, 18), ("Elite", 100, 5000, 18.0, 24)]),
        ("NVIDIA Corporation", [("Starter", 1, 50, 12.0, 6), ("Basic", 5, 250, 14.0, 12), ("Premium", 20, 1000, 17.0, 18), ("Elite", 100, 5000, 20.0, 24)]),
        ("Meta Platforms", [("Starter", 1, 50, 11.0, 6), ("Basic", 5, 250, 13.0, 12), ("Premium", 20, 1000, 16.0, 18), ("Elite", 100, 5000, 19.0, 24)]),
        ("Berkshire Hathaway", [("Starter", 1, 50, 9.0, 6), ("Basic", 5, 250, 10.0, 12), ("Premium", 20, 1000, 12.0, 18), ("Elite", 100, 5000, 14.0, 24)]),
        ("JPMorgan Chase", [("Starter", 1, 50, 10.0, 6), ("Basic", 5, 250, 11.0, 12), ("Premium", 20, 1000, 13.0, 18), ("Elite", 100, 5000, 15.0, 24)]),
        ("Visa Inc", [("Starter", 1, 50, 11.0, 6), ("Basic", 5, 250, 12.0, 12), ("Premium", 20, 1000, 14.0, 18), ("Elite", 100, 5000, 16.0, 24)]),
        ("Netflix Inc", [("Starter", 1, 50, 11.0, 6), ("Basic", 5, 250, 13.0, 12), ("Premium", 20, 1000, 15.0, 18), ("Elite", 100, 5000, 18.0, 24)]),
        ("Disney Company", [("Starter", 1, 50, 10.0, 6), ("Basic", 5, 250, 12.0, 12), ("Premium", 20, 1000, 14.0, 18), ("Elite", 100, 5000, 16.0, 24)]),
        ("Intel Corporation", [("Starter", 1, 50, 11.0, 6), ("Basic", 5, 250, 13.0, 12), ("Premium", 20, 1000, 15.0, 18), ("Elite", 100, 5000, 17.0, 24)]),
        ("Mastercard Inc", [("Starter", 1, 50, 10.0, 6), ("Basic", 5, 250, 11.0, 12), ("Premium", 20, 1000, 13.0, 18), ("Elite", 100, 5000, 15.0, 24)]),
        ("Johnson & Johnson", [("Starter", 1, 50, 10.0, 6), ("Basic", 5, 250, 11.0, 12), ("Premium", 20, 1000, 13.0, 18), ("Elite", 100, 5000, 15.0, 24)]),
        ("Coca-Cola Company", [("Starter", 1, 50, 8.0, 6), ("Basic", 5, 250, 9.0, 12), ("Premium", 20, 1000, 11.0, 18), ("Elite", 100, 5000, 13.0, 24)]),
        ("Pfizer Inc", [("Starter", 1, 50, 8.0, 6), ("Basic", 5, 250, 9.0, 12), ("Premium", 20, 1000, 11.0, 18), ("Elite", 100, 5000, 13.0, 24)]),
        ("Nike Inc", [("Starter", 1, 50, 9.0, 6), ("Basic", 5, 250, 10.0, 12), ("Premium", 20, 1000, 12.0, 18), ("Elite", 100, 5000, 14.0, 24)]),
        ("UnitedHealth Group", [("Starter", 1, 50, 10.0, 6), ("Basic", 5, 250, 11.0, 12), ("Premium", 20, 1000, 13.0, 18), ("Elite", 100, 5000, 15.0, 24)]),
        ("McDonald Corporation", [("Starter", 1, 50, 8.0, 6), ("Basic", 5, 250, 9.0, 12), ("Premium", 20, 1000, 11.0, 18), ("Elite", 100, 5000, 13.0, 24)]),
        ("Qualcomm Inc", [("Starter", 1, 50, 10.0, 6), ("Basic", 5, 250, 12.0, 12), ("Premium", 20, 1000, 14.0, 18), ("Elite", 100, 5000, 16.0, 24)]),
        ("Taiwan Semiconductor", [("Starter", 1, 50, 12.0, 6), ("Basic", 5, 250, 14.0, 12), ("Premium", 20, 1000, 16.0, 18), ("Elite", 100, 5000, 18.0, 24)]),
        ("Advanced Micro Devices", [("Starter", 1, 50, 10.0, 6), ("Basic", 5, 250, 12.0, 12), ("Premium", 20, 1000, 14.0, 18), ("Elite", 100, 5000, 16.0, 24)]),
        ("Broadcom Inc", [("Starter", 1, 50, 11.0, 6), ("Basic", 5, 250, 13.0, 12), ("Premium", 20, 1000, 15.0, 18), ("Elite", 100, 5000, 17.0, 24)]),
        ("AbbVie Inc", [("Starter", 1, 50, 8.0, 6), ("Basic", 5, 250, 9.0, 12), ("Premium", 20, 1000, 11.0, 18), ("Elite", 100, 5000, 13.0, 24)]),
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

    # The live table may predate the UNIQUE constraint declared in schema.sql
    # (CREATE TABLE IF NOT EXISTS is a no-op on an already-existing table),
    # which is what made every ON CONFLICT (display_name) upsert fail with
    # "no unique or exclusion constraint matching the ON CONFLICT specification".
    # De-duplicate any pre-existing rows first so the constraint can attach,
    # then add it.
    try:
        cur.execute("""
            DELETE FROM wallet_configs a USING wallet_configs b
            WHERE a.id > b.id AND a.display_name = b.display_name
        """)
    except Exception as e:
        print(f"[trovee] Migration warning (wallet_configs dedupe): {e}")
    try:
        cur.execute(
            "ALTER TABLE wallet_configs ADD CONSTRAINT wallet_configs_display_name_key UNIQUE (display_name)"
        )
        print("[trovee] Migration: added unique constraint on wallet_configs.display_name")
    except Exception:
        pass


if __name__ == "__main__":
    init_db()
