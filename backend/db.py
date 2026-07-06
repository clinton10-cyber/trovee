"""
Trovee database layer — supports both SQLite and PostgreSQL.

SQLite (default, zero config):
    Works out of the box. Data is stored at TROVEE_DB_PATH or /tmp/trovee.db.

PostgreSQL (recommended for production):
    Set TROVEE_DATABASE_URL to your Postgres connection string, e.g.:
    TROVEE_DATABASE_URL=postgresql://user:password@host:5432/dbname

    Render provides this automatically when you add a PostgreSQL database
    to your service. The free tier gives you 1 GB.

    Install: pip install psycopg2-binary  (already in requirements.txt)
"""

import os
import sqlite3

DATABASE_URL = os.environ.get("TROVEE_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
USE_POSTGRES = bool(DATABASE_URL)

# SQLite fallback path
_default_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "trovee.db")
DB_PATH = os.environ.get("TROVEE_DB_PATH", _default_db)
if not USE_POSTGRES and not os.path.exists(os.path.dirname(DB_PATH)):
    DB_PATH = "/tmp/trovee.db"

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def get_db():
    """Return an open database connection (SQLite or PostgreSQL)."""
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
    """Thin wrapper that makes psycopg2 behave like sqlite3 for our usage."""

    def __init__(self, conn):
        self._conn = conn
        self._cur  = conn.cursor()

    def execute(self, sql, params=()):
        # Convert SQLite ? placeholders to Postgres %s
        pg_sql = sql.replace("?", "%s")
        # Convert SQLite datetime('now') to Postgres now()
        pg_sql = pg_sql.replace("datetime('now')", "now()")
        # Convert INSERT OR IGNORE to INSERT ... ON CONFLICT DO NOTHING
        pg_sql = pg_sql.replace("INSERT OR IGNORE INTO", "INSERT INTO").replace(
            "INSERT OR REPLACE INTO", "INSERT INTO"
        )
        if "INSERT INTO" in pg_sql and "ON CONFLICT" not in pg_sql and "IGNORE" in sql:
            pg_sql += " ON CONFLICT DO NOTHING"
        self._cur.execute(pg_sql, params)
        return self

    def fetchone(self):
        row = self._cur.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(r) for r in self._cur.fetchall()]

    @property
    def lastrowid(self):
        self._cur.execute("SELECT lastval()")
        return self._cur.fetchone()[0]

    def commit(self):
        self._conn.commit()

    def close(self):
        self._cur.close()
        self._conn.close()


def _schema_for_postgres(sql: str) -> str:
    """Convert SQLite schema to PostgreSQL-compatible DDL."""
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    sql = sql.replace("INTEGER PRIMARY KEY", "INTEGER PRIMARY KEY")
    sql = sql.replace("datetime('now')", "now()")
    sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
    # Add ON CONFLICT DO NOTHING for all seeding inserts
    lines = sql.split("\n")
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("INSERT INTO") and "ON CONFLICT" not in stripped:
            line = line.rstrip(";") + " ON CONFLICT DO NOTHING;"
        out.append(line)
    return "\n".join(out)


def init_db():
    """Create all tables if they don't exist. Safe to call on every startup."""
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
        conn.close()
        print(f"[trovee] PostgreSQL database initialized.")
    else:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.executescript(schema)
        _migrate_sqlite(conn)
        conn.commit()
        conn.close()
        print(f"[trovee] SQLite database initialized at {DB_PATH}")


def _migrate_sqlite(conn):
    """Add new columns to existing tables without losing data."""
    # Create new tables if missing
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wallet_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT NOT NULL,
            address TEXT NOT NULL,
            logo_url TEXT DEFAULT '',
            qr_url TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    migrations = [
        ("share_purchases", "plan_name",          "TEXT DEFAULT ''"),
        ("share_purchases", "return_rate_pct",     "REAL DEFAULT 0"),
        ("share_purchases", "duration_months",     "INTEGER DEFAULT 12"),
        ("share_purchases", "return_usd_cents",    "INTEGER DEFAULT 0"),
        ("share_purchases", "total_payout_cents",  "INTEGER DEFAULT 0"),
        ("share_purchases", "maturity_date",       "TEXT DEFAULT ''"),
        ("share_purchases", "paid_at",             "TEXT"),
        ("wallet_configs",    "logo_url",            "TEXT DEFAULT ''"),
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
    """Add new columns to existing Postgres tables without losing data."""
    migrations = [
        ("share_purchases", "plan_name",         "TEXT NOT NULL DEFAULT ''"),
        ("share_purchases", "return_rate_pct",   "REAL NOT NULL DEFAULT 0"),
        ("share_purchases", "duration_months",   "INTEGER NOT NULL DEFAULT 12"),
        ("share_purchases", "return_usd_cents",  "INTEGER NOT NULL DEFAULT 0"),
        ("share_purchases", "total_payout_cents","INTEGER NOT NULL DEFAULT 0"),
        ("share_purchases", "maturity_date",     "TEXT NOT NULL DEFAULT ''"),
        ("share_purchases", "paid_at",           "TEXT"),
    ]
    for table, col, col_def in migrations:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
            print(f"[trovee] Migration: added {table}.{col}")
        except Exception:
            pass  # Column already exists


if __name__ == "__main__":
    init_db()
