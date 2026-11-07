"""SQLite 连接、事务与迁移。单进程多线程，WAL + busy_timeout 足够。"""
import os
import sqlite3

from flask import g

from config import Config

MIGRATION_DIR = os.path.join(Config.BASE_DIR, "db", "migrations")
GENESIS = "SHIP-PMS/1.0/GENESIS"


def connect(path: str | None = None) -> sqlite3.Connection:
    db_path = path or Config.DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


class tx:
    """显式事务：异常回滚。sqlite3 在 isolation_level=None 下需手动 BEGIN。"""

    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = conn or get_db()
        self.owns = conn is None

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")
        return False


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    try:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        return {int(r["version"]) for r in rows}
    except sqlite3.OperationalError:
        return set()


def migrate(conn: sqlite3.Connection | None = None, verbose: bool = False) -> list[int]:
    """按文件名序号顺序执行未应用的迁移，返回本次应用的版本号。"""
    own = conn is None
    conn = conn or connect()
    applied: list[int] = []
    try:
        done = _applied_versions(conn)
        if not done:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
        files = sorted(f for f in os.listdir(MIGRATION_DIR) if f.endswith(".sql"))
        for name in files:
            try:
                version = int(name.split("_", 1)[0])
            except ValueError:
                continue
            if version in done:
                continue
            with open(os.path.join(MIGRATION_DIR, name), "r", encoding="utf-8") as fh:
                script = fh.read()
            conn.executescript("BEGIN;\n" + script + "\nCOMMIT;")
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations (version, applied_at) "
                "VALUES (?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                (version,),
            )
            applied.append(version)
            if verbose:
                print(f"applied migration {name}")
    finally:
        if own:
            conn.close()
    return applied


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def get_int_setting(conn: sqlite3.Connection, key: str, default: int) -> int:
    try:
        return int(get_setting(conn, key, str(default)))
    except (TypeError, ValueError):
        return default
