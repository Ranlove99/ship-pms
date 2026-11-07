"""审计日志：只追加，哈希成链。所有写操作都必须经过这里。"""
import hashlib
import json
import sqlite3

from services.timeutil import now_iso

GENESIS = "SHIP-PMS/1.0/GENESIS"


def canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def last_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    return row["hash"] if row else GENESIS


def write(
    conn: sqlite3.Connection,
    action: str,
    user: dict | None = None,
    entity: str = "",
    entity_id: str = "",
    before: dict | None = None,
    after: dict | None = None,
    ip: str = "",
) -> str:
    at = now_iso()
    username = (user or {}).get("username", "") or "system"
    user_id = (user or {}).get("id")
    before_json = canonical(before) if before is not None else None
    after_json = canonical(after) if after is not None else None

    payload = {
        "at_utc": at,
        "username": username,
        "action": action,
        "entity": entity,
        "entity_id": str(entity_id),
        "before": before_json,
        "after": after_json,
    }
    prev = last_hash(conn)
    digest = sha256_hex(prev + canonical(payload))

    conn.execute(
        "INSERT INTO audit_log (at_utc, user_id, username, action, entity, entity_id,"
        " before_json, after_json, ip, hash, prev_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (at, user_id, username, action, entity, str(entity_id),
         before_json, after_json, ip, digest, prev),
    )
    return digest


def verify_chain(conn: sqlite3.Connection) -> dict:
    """重算整条审计链，返回 {ok, checked, first_bad_id}。"""
    rows = conn.execute(
        "SELECT id, at_utc, username, action, entity, entity_id, before_json, after_json, hash, prev_hash"
        " FROM audit_log ORDER BY id ASC"
    ).fetchall()
    prev = GENESIS
    checked = 0
    for row in rows:
        payload = {
            "at_utc": row["at_utc"],
            "username": row["username"],
            "action": row["action"],
            "entity": row["entity"],
            "entity_id": row["entity_id"],
            "before": row["before_json"],
            "after": row["after_json"],
        }
        expected = sha256_hex(prev + canonical(payload))
        if row["prev_hash"] != prev or row["hash"] != expected:
            return {"ok": False, "checked": checked, "first_bad_id": row["id"]}
        prev = row["hash"]
        checked += 1
    return {"ok": True, "checked": checked, "first_bad_id": None}
