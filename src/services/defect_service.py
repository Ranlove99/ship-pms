"""缺陷与不符合项：报告 → 纠正 → 验证关闭。"""
import sqlite3

from services import audit, ids, wo_service
from services.timeutil import now_iso

SEVERITY_LABEL = {"minor": "轻微", "major": "重要", "critical": "严重"}
STATUS_LABEL = {"open": "待处理", "in_progress": "处理中", "fixed": "已修复", "closed": "已关闭"}


def _decorate(item: dict) -> dict:
    item["severity_label"] = SEVERITY_LABEL.get(item.get("severity"), item.get("severity", ""))
    item["status_label"] = STATUS_LABEL.get(item.get("status"), item.get("status", ""))
    return item


def list_defects(conn: sqlite3.Connection, status: str = "", limit: int = 200) -> list[dict]:
    sql = (
        "SELECT d.*, a.name AS asset_name, a.code AS asset_code,"
        " u.display_name AS found_by_name, w.no AS wo_no FROM defects d"
        " LEFT JOIN assets a ON a.id = d.asset_id"
        " LEFT JOIN users u ON u.id = d.found_by"
        " LEFT JOIN work_orders w ON w.id = d.wo_id WHERE 1=1"
    )
    params: list = []
    if status == "open":
        sql += " AND d.status != 'closed'"
    elif status in STATUS_LABEL:
        sql += " AND d.status = ?"
        params.append(status)
    sql += " ORDER BY CASE d.severity WHEN 'critical' THEN 0 WHEN 'major' THEN 1 ELSE 2 END,"
    sql += " CASE d.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, d.found_at DESC LIMIT ?"
    params.append(limit)
    return [_decorate(dict(r)) for r in conn.execute(sql, params).fetchall()]


def get(conn: sqlite3.Connection, defect_id: int) -> dict | None:
    row = conn.execute(
        "SELECT d.*, a.name AS asset_name, a.code AS asset_code FROM defects d"
        " LEFT JOIN assets a ON a.id = d.asset_id WHERE d.id = ?", (defect_id,)
    ).fetchone()
    return _decorate(dict(row)) if row else None


def create(conn: sqlite3.Connection, data: dict, user: dict | None) -> int:
    no = ids.next_defect_no(conn)
    cur = conn.execute(
        "INSERT INTO defects (no, asset_id, found_at, found_by, severity, description, status, created_at)"
        " VALUES (?,?,?,?,?,?,'open',?)",
        (
            no, data.get("asset_id") or None, now_iso(), (user or {}).get("id"),
            data.get("severity") or "minor", (data.get("description") or "").strip(), now_iso(),
        ),
    )
    defect_id = int(cur.lastrowid)
    audit.write(conn, "defect.create", user, "defects", str(defect_id),
                after={"no": no, "severity": data.get("severity"), "desc": (data.get("description") or "")[:200]})
    return defect_id


def update(conn: sqlite3.Connection, defect_id: int, data: dict, user: dict | None) -> None:
    before = get(conn, defect_id)
    if before is None:
        raise ValueError("缺陷不存在")
    sets, params = [], []
    for field in ("severity", "description", "root_cause", "corrective_action", "status"):
        if field in data and data[field] is not None:
            sets.append(f"{field} = ?")
            params.append(data[field])
    if not sets:
        return
    params.append(defect_id)
    conn.execute(f"UPDATE defects SET {', '.join(sets)} WHERE id = ?", params)
    audit.write(conn, "defect.update", user, "defects", str(defect_id), before=before, after=data)


def close(conn: sqlite3.Connection, defect_id: int, corrective: str,
          user: dict | None) -> dict:
    row = conn.execute("SELECT * FROM defects WHERE id = ?", (defect_id,)).fetchone()
    if row is None:
        raise ValueError("缺陷不存在")
    if row["status"] == "closed":
        raise ValueError("缺陷已关闭")
    if not (corrective or "").strip():
        raise ValueError("关闭缺陷必须填写纠正措施")
    conn.execute(
        "UPDATE defects SET status = 'closed', corrective_action = ?, closed_at = ?, closed_by = ?"
        " WHERE id = ?",
        (corrective.strip(), now_iso(), (user or {}).get("id"), defect_id),
    )
    audit.write(conn, "defect.close", user, "defects", str(defect_id),
                before={"status": row["status"]},
                after={"status": "closed", "corrective_action": corrective[:300]})
    return {"status": "closed"}


def to_workorder(conn: sqlite3.Connection, defect_id: int, user: dict | None) -> dict:
    row = conn.execute("SELECT * FROM defects WHERE id = ?", (defect_id,)).fetchone()
    if row is None:
        raise ValueError("缺陷不存在")
    if row["wo_id"]:
        raise ValueError("该缺陷已关联工单")
    if not row["asset_id"]:
        raise ValueError("缺陷未关联设备，无法生成工单")
    wo_id = wo_service.create(conn, {
        "asset_id": row["asset_id"],
        "type": "defect",
        "priority": "high" if row["severity"] == "major" else ("critical" if row["severity"] == "critical" else "normal"),
        "title": f"缺陷修复 {row['no']}",
        "description": row["description"],
        "checklist": [],
    }, user)
    conn.execute("UPDATE defects SET wo_id = ?, status = 'in_progress' WHERE id = ?", (wo_id, defect_id))
    audit.write(conn, "defect.to_workorder", user, "defects", str(defect_id), after={"wo_id": wo_id})
    return {"wo_id": wo_id}


def open_count(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT severity, COUNT(*) AS n FROM defects WHERE status != 'closed' GROUP BY severity").fetchall()
    counts = {r["severity"]: r["n"] for r in rows}
    return {
        "total": sum(counts.values()),
        "critical": counts.get("critical", 0),
        "major": counts.get("major", 0),
        "minor": counts.get("minor", 0),
    }
