"""
Database sharding layer for Trovee.
Distributes data across multiple databases by user_id (consistent hashing).
Alternative to db_multi.py's failover approach - use this if you want
data actively spread across DBs from the start rather than sequential fill.
"""

import os
import psycopg2
import psycopg2.extras
from hashlib import md5

DATABASES = [
    os.environ.get("TROVEE_DATABASE_URL_1", ""),
    os.environ.get("TROVEE_DATABASE_URL_2", ""),
    os.environ.get("TROVEE_DATABASE_URL_3", ""),
    os.environ.get("TROVEE_DATABASE_URL_4", ""),
]

ACTIVE_DATABASES = [db for db in DATABASES if db]
SHARD_COUNT = len(ACTIVE_DATABASES)


class ShardedDatabase:
    """Routes queries to appropriate shard based on partition key (user_id)."""

    def __init__(self):
        self.connections = {}
        self._init_connections()

    def _init_connections(self):
        for idx, db_url in enumerate(ACTIVE_DATABASES):
            try:
                conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
                conn.autocommit = False
                self.connections[idx] = conn
                print(f"[trovee] Shard {idx} connected")
            except Exception as e:
                print(f"[trovee] Shard {idx} connection failed: {e}")

    def get_shard_id(self, partition_key):
        if SHARD_COUNT == 0:
            raise Exception("No database shards available")
        if SHARD_COUNT == 1:
            return 0
        hash_val = int(md5(str(partition_key).encode()).hexdigest(), 16)
        return hash_val % SHARD_COUNT

    def get_connection(self, shard_id):
        if shard_id not in self.connections:
            raise Exception(f"Shard {shard_id} not available")
        return self.connections[shard_id]

    def execute_on_shard(self, shard_id, sql, params=()):
        conn = self.get_connection(shard_id)
        cur = conn.cursor()
        pg_sql = sql.replace("?", "%s").replace("datetime('now')", "now()")
        cur.execute(pg_sql, params)
        return cur

    def execute_all_shards(self, sql, params=()):
        all_results = []
        for shard_id, conn in self.connections.items():
            try:
                cur = conn.cursor()
                pg_sql = sql.replace("?", "%s").replace("datetime('now')", "now()")
                cur.execute(pg_sql, params)
                all_results.extend(cur.fetchall())
            except Exception as e:
                print(f"[trovee] Shard {shard_id} query error: {e}")
        return all_results

    def insert_user(self, user_data):
        """Insert a new user into a deterministically-chosen shard (by email hash)."""
        shard_id = self.get_shard_id(user_data.get("email", ""))
        conn = self.connections.get(shard_id)
        if not conn:
            raise Exception(f"Shard {shard_id} unavailable")
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (username, email, phone, password_hash, password_salt,
                                country_code, currency_code, balance_usd_cents, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            RETURNING id
            """,
            (
                user_data["username"], user_data["email"], user_data["phone"],
                user_data["password_hash"], user_data["password_salt"],
                user_data.get("country_code", "US"), user_data.get("currency_code", "USD"),
                user_data.get("balance_usd_cents", 0),
            ),
        )
        new_id = cur.fetchone()
        conn.commit()
        return new_id, shard_id

    def get_user_shard(self, user_id):
        return self.get_shard_id(user_id)

    def get_user(self, user_id):
        shard_id = self.get_user_shard(user_id)
        cur = self.execute_on_shard(shard_id, "SELECT * FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()

    def update_user_balance(self, user_id, amount_cents):
        shard_id = self.get_user_shard(user_id)
        self.execute_on_shard(
            shard_id,
            "UPDATE users SET balance_usd_cents = balance_usd_cents + %s WHERE id = %s",
            (amount_cents, user_id),
        )
        self.connections[shard_id].commit()

    def get_all_users(self):
        results = self.execute_all_shards("SELECT * FROM users ORDER BY id DESC")
        return [dict(r) for r in results]

    def get_shard_info(self):
        info = {}
        for shard_id, conn in self.connections.items():
            try:
                cur = conn.cursor()
                tables = ["users", "share_purchases", "deposits", "withdrawals"]
                counts = {}
                for table in tables:
                    cur.execute(f"SELECT COUNT(*) as cnt FROM {table}")
                    result = cur.fetchone()
                    counts[table] = result["cnt"] if isinstance(result, dict) else result[0]
                cur.execute("SELECT pg_size_pretty(pg_database_size(current_database())) as size")
                size_result = cur.fetchone()
                size = size_result["size"] if isinstance(size_result, dict) else size_result[0]
                info[f"shard_{shard_id}"] = {"status": "active", "counts": counts, "database_size": size}
            except Exception as e:
                info[f"shard_{shard_id}"] = {"status": "error", "error": str(e)}
        return info

    def rebalance(self):
        """Compute (not apply) new shard assignments - useful before adding/removing shards."""
        print("[trovee] Computing rebalance plan...")
        all_users = self.get_all_users()
        reassignments = {}
        for user in all_users:
            user_id = user["id"]
            reassignments[user_id] = self.get_shard_id(user_id)
        print(f"[trovee] Rebalance plan: {len(reassignments)} users across {SHARD_COUNT} shards")
        return reassignments

    def close_all(self):
        for conn in self.connections.values():
            try:
                conn.close()
            except Exception:
                pass


def get_sharded_db():
    return ShardedDatabase()
