"""电子记录簿：录入、提交、核签、更正、导出。"""
import json
import sqlite3

from services import audit, record_chain
from services.timeutil import now_iso

STATUS_LABEL = {
    "draft": "草稿",
    "submitted": "待核签",
    "verified": "已核签",
    "amended": "已更正",
}

# 录入字段的中文标签（与前端 BOOK_FIELDS 对应）
FIELD_LABEL = {
    "fuel": "油品",
    "oil": "油品",
    "qty": "数量",
    "tank": "舱柜",
    "place": "地点",
    "supplier": "供应方",
    "position": "位置",
    "speed": "航速",
    "rate": "排放速率",
    "method": "方式",
    "facility": "接收设施",
    "device": "设备",
    "phenomenon": "现象",
    "action": "处置",
    "category": "类别",
    "store": "存放位置",
    "duration": "时长",
    "receipt": "接收单号",
    "cargo": "货物",
    "treated": "是否处理",
    "type": "类型",
    "content": "检修内容",
    "distance": "离岸距离",
    "remark": "说明",
}


def display_pairs(particulars: dict) -> list[dict]:
    pairs = []
    for key, value in particulars.items():
        if key.startswith("_") or value in (None, ""):
            continue
        pairs.append({"label": FIELD_LABEL.get(key, key), "value": value})
    return pairs


def books(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM record_books ORDER BY id").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["entry_types"] = json.loads(item.pop("entry_types_json", "[]"))
        except ValueError:
            item["entry_types"] = []
        stats = conn.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN status='submitted' THEN 1 ELSE 0 END) AS pending"
            " FROM record_entries WHERE book_id = ?", (row["id"],)
        ).fetchone()
        item["total"] = stats["total"] or 0
        item["pending"] = stats["pending"] or 0
        item["chain_ok"] = record_chain.verify_book(conn, row["id"])["ok"]
        result.append(item)
    return result


def book_by_code(conn: sqlite3.Connection, code: str) -> dict | None:
    row = conn.execute("SELECT * FROM record_books WHERE code = ?", (code,)).fetchone()
    if row is None:
        return None
    item = dict(row)
    try:
        item["entry_types"] = json.loads(item.pop("entry_types_json", "[]"))
    except ValueError:
        item["entry_types"] = []
    item["chain_ok"] = record_chain.verify_book(conn, row["id"])["ok"]
    stats = conn.execute(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN status='submitted' THEN 1 ELSE 0 END) AS pending"
        " FROM record_entries WHERE book_id = ?", (row["id"],)
    ).fetchone()
    item["total"] = stats["total"] or 0
    item["pending"] = stats["pending"] or 0
    return item


def entries(conn: sqlite3.Connection, book_id: int, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        "SELECT e.*, o.display_name AS officer_name, m.display_name AS master_name,"
        " a.seq AS amends_seq FROM record_entries e"
        " LEFT JOIN users o ON o.id = e.officer_id"
        " LEFT JOIN users m ON m.id = e.master_id"
        " LEFT JOIN record_entries a ON a.id = e.amends_entry_id"
        " WHERE e.book_id = ? ORDER BY e.seq DESC LIMIT ?", (book_id, limit)
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["particulars"] = json.loads(item.pop("particulars_json", "{}"))
        except ValueError:
            item["particulars"] = {}
        item["particulars_display"] = display_pairs(item["particulars"])
        item["status_label"] = STATUS_LABEL.get(item["status"], item["status"])
        result.append(item)
    return result


def get_entry(conn: sqlite3.Connection, entry_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM record_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["particulars"] = json.loads(item.pop("particulars_json", "{}"))
    item["status_label"] = STATUS_LABEL.get(item["status"], item["status"])
    return item


def add_entry(conn: sqlite3.Connection, book_id: int, entry_type: str, occurred_at_utc: str,
              particulars: dict, user: dict | None) -> dict:
    result = record_chain.append_entry(
        conn, book_id, entry_type, occurred_at_utc, particulars, (user or {}).get("id")
    )
    audit.write(conn, "record.append", user, "record_entries", str(result["id"]),
                after={"book_id": book_id, "seq": result["seq"], "type": entry_type})
    return result


def submit(conn: sqlite3.Connection, entry_id: int, user: dict | None) -> dict:
    row = conn.execute("SELECT * FROM record_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise ValueError("记录不存在")
    if not record_chain.can_transition(row["status"], "submitted"):
        raise ValueError(f"状态「{STATUS_LABEL.get(row['status'])}」不能提交")
    conn.execute(
        "UPDATE record_entries SET status = 'submitted', officer_id = COALESCE(officer_id, ?),"
        " officer_signed_at = ? WHERE id = ?",
        ((user or {}).get("id"), now_iso(), entry_id),
    )
    audit.write(conn, "record.submit", user, "record_entries", str(entry_id),
                before={"status": row["status"]}, after={"status": "submitted"})
    return {"status": "submitted"}


def verify(conn: sqlite3.Connection, entry_id: int, user: dict | None) -> dict:
    row = conn.execute("SELECT * FROM record_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise ValueError("记录不存在")
    if row["status"] == "verified":
        raise ValueError("该记录已核签，不可重复签署")
    if not record_chain.can_transition(row["status"], "verified"):
        raise ValueError(f"状态「{STATUS_LABEL.get(row['status'])}」不能核签，需先提交")
    conn.execute(
        "UPDATE record_entries SET status = 'verified', master_id = ?, master_verified_at = ? WHERE id = ?",
        ((user or {}).get("id"), now_iso(), entry_id),
    )
    audit.write(conn, "record.verify", user, "record_entries", str(entry_id),
                before={"status": row["status"]}, after={"status": "verified"})
    return {"status": "verified"}


def amend(conn: sqlite3.Connection, entry_id: int, particulars: dict, reason: str,
          user: dict | None) -> dict:
    """更正：原条目保留并标记 amended，新条目指回原条目。"""
    row = conn.execute("SELECT * FROM record_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise ValueError("记录不存在")
    if row["status"] != "verified":
        raise ValueError("仅已核签的记录需要走更正流程")

    merged = json.loads(row["particulars_json"] or "{}")
    merged.update(particulars or {})
    merged["_amendment_reason"] = reason or ""
    result = record_chain.append_entry(
        conn, row["book_id"], row["entry_type"], row["occurred_at_utc"], merged,
        (user or {}).get("id"), amends_entry_id=entry_id,
    )
    conn.execute("UPDATE record_entries SET status = 'amended' WHERE id = ?", (entry_id,))
    audit.write(conn, "record.amend", user, "record_entries", str(entry_id),
                before={"seq": row["seq"]},
                after={"new_entry": result["id"], "seq": result["seq"], "reason": reason})
    return result


def export_rows(conn: sqlite3.Connection, book_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT e.*, o.display_name AS officer_name, m.display_name AS master_name"
        " FROM record_entries e LEFT JOIN users o ON o.id = e.officer_id"
        " LEFT JOIN users m ON m.id = e.master_id WHERE e.book_id = ? ORDER BY e.seq", (book_id,)
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            particulars = json.loads(item["particulars_json"] or "{}")
        except ValueError:
            particulars = {}
        out.append({
            "seq": item["seq"],
            "occurred_at_utc": item["occurred_at_utc"],
            "entry_type": item["entry_type"],
            "particulars": particulars,
            "status": STATUS_LABEL.get(item["status"], item["status"]),
            "officer": item["officer_name"] or "",
            "master": item["master_name"] or "",
            "verified_at": item["master_verified_at"] or "",
            "hash": item["hash"],
            "amends_seq": item["amends_entry_id"],
        })
    return out
