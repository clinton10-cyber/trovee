import sqlite3
import os

# In production on Render, set TROVEE_DB_PATH to the mounted disk path.
# e.g. /var/data/trovee.db  (mount your disk at /var/data on Render)
# Falls back to local instance/ folder for development.
_default_db = os.path.join(os.path.dirname(__file__), "instance", "trovee.db")
DB_PATH = os.environ.get("TROVEE_DB_PATH", _default_db)
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
