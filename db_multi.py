"""
Trovee multi-database layer with automatic failover.
Supports multiple PostgreSQL databases with capacity limits.
When the active database hits a capacity limit, it automatically
fails over to the next configured database. All previously written
data stays in place in whichever database it was written to; reads
across databases can be aggregated with get_all_data().
"""

import os
import sqlite3
import psycopg2
import psycopg2.extras

# Multi-database configuration - set these environment variables
DATABASES = {
    "primary": os.environ.get("TROVEE_DATABASE_URL_1") or os.environ.get("DATABASE_URL", ""),
    "secondary": os.environ.get("TROVEE_DATABASE_URL_2", ""),
    "tertiary": os.environ.get("TROVEE_DATABASE_URL_3", ""),
    "quaternary": os.environ.get("TROVEE_DATABASE_URL_4", ""),
}

# Database capacity limits (rows per table) before failover triggers
DB_CAPACITY_LIMITS = {
    "users": int(os.environ.get("TROVEE_DB_CAPACITY_USERS", 100000)),
    "share_purchases": int(os.environ.get("TROVEE_DB_CAPACITY_PURCHASES", 500000)),
    "chat_messages": int(os.environ.get("TROVEE_DB_CAPACITY_MESSAGES", 1000000)),
    "deposits": int(os.environ.get("TROVEE_DB_CAPACITY_DEPOSITS", 100000)),
    "withdrawals": int(os.environ.get("TROVEE_DB_CAPACITY_WITHDRAWALS", 100000)),
}

USE_POSTGRES = bool(DATABASES["primary"])
SQLITE_PATH = os.environ.get("TROVEE_DB_PATH", "/tmp/trovee.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")

ACTIVE_DATABASES = [db for db in DATABASES.values() if db]


class DatabaseRouter:
    """Routes queries to appropriate database based on capacity and load."""

    def __init__(self):
        self.connections = {}
        self.db_status = {}
        self.active_index = 0
        self._init_connections()

    def _init_connections(self):
        for idx, db_url in enumerate(ACTIVE_DATABASES):
            if not db_url:
                continue
            try:
                conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
                conn.autocommit = False
                self.connections[idx] = conn
                self.db_status[idx] = "active"
                print(f"[trovee] Database {idx} connected")
            except Exception as e:
                self.db_status[idx] = f"failed: {e}"
                print(f"[trovee] Database {idx} connection failed: {e}")

    def get_db_for_table(self, table):
        if self.active_index in self.connections:
            return self.connections[self.active_index], self.active_index
        for idx in sorted(self.connections.keys()):
            return self.connections[idx], idx
        raise Exception("No database connections available")

    def check_capacity(self, table):
        """Check if the active database is at capacity for this table; failover if so."""
        if table not in DB_CAPACITY_LIMITS:
            return False
        try:
            conn, db_idx = self.get_db_for_table(table)
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            row = cur.fetchone()
            count = row[0] if isinstance(row, (tuple, list)) else list(row.values())[0]
            limit = DB_CAPACITY_LIMITS[table]
            if count >= limit:
                print(f"[trovee] Database {db_idx} at capacity for {table}: {count}/{limit}")
                self.failover()
                return True
            return False
        except Exception as e:
            print(f"[trovee] Capacity check error: {e}")
            return False

    def failover(self):
        """Switch active database to the next available one."""
        old_index = self.active_index
        for idx in sorted(self.connections.keys()):
            if idx > self.active_index:
                self.active_index = idx
                print(f"[trovee] Failover: DB {old_index} -> DB {self.active_index}")
                return
        if self.connections:
            self.active_index = min(self.connections.keys())
            print(f"[trovee] Failover (wrap): DB {old_index} -> DB {self.active_index}")

    def execute(self, sql, params=()):
        conn, db_idx = self.get_db_for_table("users")
        cur = conn.cursor()
        pg_sql = sql.replace("?", "%s").replace("datetime('now')", "now()")
        if "INSERT" in pg_sql.upper() and "RETURNING" not in pg_sql.upper():
            pg_sql += " RETURNING id"
        cur.execute(pg_sql, params)
        return _CursorWrapper(cur, conn)

    def commit(self):
        if self.active_index in self.connections:
            self.connections[self.active_index].commit()

    def close(self):
        if self.active_index in self.connections:
            self.connections[self.active_index].close()

    def close_all(self):
        for conn in self.connections.values():
            try:
                conn.close()
            except Exception:
                pass

    def health_check(self):
        health = {}
        for idx, conn in self.connections.items():
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                health[idx] = "healthy"
            except Exception:
                health[idx] = "unhealthy"
        return health


class _CursorWrapper:
    def __init__(self, cursor, connection):
        self.cursor = cursor
        self.connection = connection
        self.last_insert_id = None

    def fetchone(self):
        row = self.cursor.fetchone()
        if row and isinstance(row, (tuple, list)) and len(row) > 0:
            self.last_insert_id = row[0]
        return dict(row) if row else None

    def fetchall(self):
        return [dict(r) for r in self.cursor.fetchall()]

    @property
    def lastrowid(self):
        return self.last_insert_id


class MultiDatabaseConnection:
    """Main interface for multi-database (failover) operations."""

    def __init__(self):
        self.router = DatabaseRouter()

    def execute(self, sql, params=()):
        return self.router.execute(sql, params)

    def commit(self):
        return self.router.commit()

    def close(self):
        return self.router.close()

    def get_status(self):
        return {
            "active_db": self.router.active_index,
            "total_dbs": len(self.router.connections),
            "status": self.router.db_status,
            "health": self.router.health_check(),
        }

    def get_all_data(self, table, query):
        """Read from all databases to get complete data (for reporting)."""
        all_results = []
        for idx, conn in self.router.connections.items():
            try:
                cur = conn.cursor()
                cur.execute(query.replace("?", "%s"))
                results = [dict(r) for r in cur.fetchall()]
                all_results.extend(results)
            except Exception as e:
                print(f"[trovee] Error reading from DB {idx}: {e}")
        return all_results

    def sync_databases(self, table, sync_query):
        """Synchronize reference data (e.g. companies/plans) across all databases."""
        try:
            primary_data = []
            if 0 in self.router.connections:
                cur = self.router.connections[0].cursor()
                cur.execute(sync_query.replace("?", "%s"))
                primary_data = [dict(r) for r in cur.fetchall()]

            for idx in range(1, len(self.router.connections)):
                if idx not in self.router.connections:
                    continue
                conn = self.router.connections[idx]
                cur = conn.cursor()
                for row in primary_data:
                    cols = ", ".join(row.keys())
                    placeholders = ", ".join(["%s"] * len(row))
                    updates = ", ".join([f"{k}=EXCLUDED.{k}" for k in row.keys() if k != "id"])
                    try:
                        cur.execute(
                            f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
                            f"ON CONFLICT (id) DO UPDATE SET {updates}",
                            list(row.values()),
                        )
                    except Exception as e:
                        print(f"[trovee] Sync row error on DB {idx}: {e}")
                conn.commit()

            print(f"[trovee] Synced {table}: {len(primary_data)} rows")
            return True
        except Exception as e:
            print(f"[trovee] Sync error: {e}")
            return False


def get_db():
    """Get a database connection with automatic failover (if configured)."""
    if USE_POSTGRES:
        return MultiDatabaseConnection()
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize all configured databases with schema."""
    if not USE_POSTGRES:
        os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
        conn = sqlite3.connect(SQLITE_PATH)
        with open(SCHEMA_PATH, "r") as f:
            schema = f.read()
        conn.executescript(schema)
        conn.commit()
        conn.close()
        print("[trovee] SQLite database initialized")
        return

    with open(SCHEMA_PATH, "r") as f:
        schema = f.read()
    schema_pg = _schema_for_postgres(schema)

    for idx, db_url in enumerate(ACTIVE_DATABASES):
        if not db_url:
            continue
        try:
            conn = psycopg2.connect(db_url)
            conn.autocommit = True
            cur = conn.cursor()
            for stmt in schema_pg.split(";"):
                stmt = stmt.strip()
                if not stmt:
                    continue
                try:
                    cur.execute(stmt)
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        print(f"[trovee] DB {idx} init warning: {e}")
            cur.close()
            conn.close()
            print(f"[trovee] Database {idx} initialized")
        except Exception as e:
            print(f"[trovee] Database {idx} init failed: {e}")


def _schema_for_postgres(sql):
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    sql = sql.replace("datetime('now')", "now()")
    lines = sql.split("\n")
    out = []
    for line in lines:
        stripped = line.strip()
        if (
            stripped.startswith("INSERT INTO share_companies")
            or stripped.startswith("INSERT INTO share_plans")
            or stripped.startswith("INSERT OR IGNORE INTO admin_settings")
        ):
            continue
        out.append(line)
    return "\n".join(out)


if __name__ == "__main__":
    init_db()
