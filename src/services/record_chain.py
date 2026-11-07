"""电子记录簿哈希链：条目内容入链，核签动作入审计链。

设计取舍：
- 条目 hash 只覆盖创建时的不可变业务字段，因此核签不会破坏链。
- 核签、更正、导出等动作由 audit_log 链单独留痕。
- 更正不修改原条目，而是新增条目并用 amends_entry_id 指回原条目。
"""
import sqlite3

from services.audit import canonical, sha256_hex
from services.timeutil import now_iso

GENESIS = "SHIP-PMS/1.0/BOOK/GENESIS"


def _entry_payload(row) -> dict:
    return {
        "book_id": row["book_id"],
        "seq": row["seq"],
        "occurred_at_utc": row["occurred_at_utc"],
        "entry_type": row["entry_type"],
        "particulars": row["particulars_json"],
        "amends_entry_id": row["amends_entry_id"],
        "officer_id": row["officer_id"],
    }


def last_hash(conn: sqlite3.Connection, book_id: int) -> str:
    row = conn.execute(
        "SELECT hash FROM record_entries WHERE book_id = ? ORDER BY seq DESC LIMIT 1",
        (book_id,),
    ).fetchone()
    return row["hash"] if row else GENESIS


def append_entry(
    conn: sqlite3.Connection,
    book_id: int,
    entry_type: str,
    occurred_at_utc: str,
    particulars: dict,
    officer_id: int | None,
    amends_entry_id: int | None = None,
) -> dict:
    seq_row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS nxt FROM record_entries WHERE book_id = ?",
        (book_id,),
    ).fetchone()
    seq = int(seq_row["nxt"])
    particulars_json = canonical(particulars)
    prev = last_hash(conn, book_id)
    payload = {
        "book_id": book_id,
        "seq": seq,
        "occurred_at_utc": occurred_at_utc,
        "entry_type": entry_type,
        "particulars": particulars_json,
        "amends_entry_id": amends_entry_id,
        "officer_id": officer_id,
    }
    digest = sha256_hex(prev + canonical(payload))
    cur = conn.execute(
        "INSERT INTO record_entries (book_id, seq, occurred_at_utc, entry_type, particulars_json,"
        " status, officer_id, officer_signed_at, amends_entry_id, hash, prev_hash, created_at)"
        " VALUES (?,?,?,?,?,'draft',?,NULL,?,?,?,?)",
        (book_id, seq, occurred_at_utc, entry_type, particulars_json,
         officer_id, amends_entry_id, digest, prev, now_iso()),
    )
    return {"id": cur.lastrowid, "seq": seq, "hash": digest}


def verify_book(conn: sqlite3.Connection, book_id: int) -> dict:
    rows = conn.execute(
        "SELECT * FROM record_entries WHERE book_id = ? ORDER BY seq ASC", (book_id,)
    ).fetchall()
    prev = GENESIS
    checked = 0
    for row in rows:
        expected = sha256_hex(prev + canonical(_entry_payload(row)))
        if row["prev_hash"] != prev or row["hash"] != expected:
            return {"ok": False, "checked": checked, "first_bad_seq": row["seq"]}
        prev = row["hash"]
        checked += 1
    return {"ok": True, "checked": checked, "first_bad_seq": None}


def verify_all(conn: sqlite3.Connection) -> dict:
    books = conn.execute("SELECT id, code, title FROM record_books ORDER BY code").fetchall()
    results = []
    all_ok = True
    for book in books:
        res = verify_book(conn, book["id"])
        res.update({"code": book["code"], "title": book["title"]})
        results.append(res)
        all_ok = all_ok and res["ok"]
    return {"ok": all_ok, "books": results}


# 状态机：draft → submitted → verified；verified 只能通过 amend 派生新条目
ALLOWED_TRANSITIONS = {
    "draft": {"submitted"},
    "submitted": {"verified"},
    "verified": set(),
    "amended": set(),
}


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())
