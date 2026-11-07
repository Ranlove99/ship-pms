"""设备台账查询与维护。"""
import sqlite3

from services.timeutil import now_iso

CATEGORY_LABEL = {
    "hull": "船体结构",
    "machinery": "轮机",
    "deck": "甲板机械",
    "electrical": "电气",
    "safety": "安全与消防",
    "navigation": "导航通信",
    "cargo": "货物系统",
    "other": "其他",
}
CRITICALITY_LABEL = {"A": "A 级 · 关键", "B": "B 级 · 重要", "C": "C 级 · 一般"}
STATUS_LABEL = {
    "in_service": "在用",
    "standby": "备用",
    "out_of_service": "停用",
    "disposed": "已处置",
}


def _public(row) -> dict:
    item = dict(row)
    item["category_label"] = CATEGORY_LABEL.get(item.get("category"), item.get("category", ""))
    item["criticality_label"] = CRITICALITY_LABEL.get(item.get("criticality"), "")
    item["status_label"] = STATUS_LABEL.get(item.get("status"), item.get("status", ""))
    return item


def list_all(conn: sqlite3.Connection, query: str = "", category: str = "") -> list[dict]:
    sql = "SELECT * FROM assets WHERE 1=1"
    params: list = []
    if query:
        sql += " AND (code LIKE ? OR name LIKE ? OR maker LIKE ? OR model LIKE ? OR serial_no LIKE ?)"
        like = f"%{query}%"
        params += [like] * 5
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY code"
    return [_public(r) for r in conn.execute(sql, params).fetchall()]


ROOT_ORDER = {"hull": 0, "machinery": 1, "deck": 2, "electrical": 3,
              "safety": 4, "navigation": 5, "cargo": 6, "other": 7}


def tree(conn: sqlite3.Connection) -> list[dict]:
    rows = list_all(conn)
    index = {r["id"]: dict(r, children=[]) for r in rows}
    roots = []
    for item in index.values():
        parent = index.get(item.get("parent_id"))
        if parent:
            parent["children"].append(item)
        else:
            roots.append(item)
    roots.sort(key=lambda r: (ROOT_ORDER.get(r.get("category"), 9), r["code"]))
    return roots


def get(conn: sqlite3.Connection, asset_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if row is None:
        return None
    item = _public(row)
    item["path"] = _path(conn, row["id"])
    return item


def _path(conn: sqlite3.Connection, asset_id: int | None) -> list[dict]:
    chain: list[dict] = []
    current = asset_id
    guard = 0
    while current and guard < 12:
        row = conn.execute("SELECT id, name, code, parent_id FROM assets WHERE id = ?", (current,)).fetchone()
        if row is None:
            break
        chain.append({"id": row["id"], "name": row["name"], "code": row["code"]})
        current = row["parent_id"]
        guard += 1
    return list(reversed(chain))


def create(conn: sqlite3.Connection, data: dict) -> int:
    cur = conn.execute(
        "INSERT INTO assets (parent_id, code, name, category, criticality, maker, model, serial_no,"
        " location, install_date, running_hours, running_hours_at, status, notes, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            data.get("parent_id") or None,
            (data.get("code") or "").strip(),
            (data.get("name") or "").strip(),
            data.get("category") or "machinery",
            data.get("criticality") or "B",
            data.get("maker") or "",
            data.get("model") or "",
            data.get("serial_no") or "",
            data.get("location") or "",
            data.get("install_date") or "",
            float(data.get("running_hours") or 0),
            now_iso(),
            data.get("status") or "in_service",
            data.get("notes") or "",
            now_iso(),
        ),
    )
    return int(cur.lastrowid)


def update(conn: sqlite3.Connection, asset_id: int, data: dict) -> None:
    fields = ["parent_id", "code", "name", "category", "criticality", "maker", "model",
              "serial_no", "location", "install_date", "status", "notes"]
    sets, params = [], []
    for field in fields:
        if field in data:
            value = data[field]
            if field == "parent_id":
                value = value or None
            sets.append(f"{field} = ?")
            params.append(value)
    if "running_hours" in data:
        sets.append("running_hours = ?")
        params.append(float(data["running_hours"] or 0))
        sets.append("running_hours_at = ?")
        params.append(now_iso())
    if not sets:
        return
    params.append(asset_id)
    conn.execute(f"UPDATE assets SET {', '.join(sets)} WHERE id = ?", params)


def update_hours(conn: sqlite3.Connection, asset_id: int, hours: float) -> None:
    conn.execute(
        "UPDATE assets SET running_hours = ?, running_hours_at = ? WHERE id = ?",
        (float(hours), now_iso(), asset_id),
    )


def child_count(conn: sqlite3.Connection, asset_id: int) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM assets WHERE parent_id = ?", (asset_id,)).fetchone()["n"]


def stats(conn: sqlite3.Connection) -> dict:
    flat = list_all(conn)
    total = len(flat)
    # 分组节点（有子设备）不计入设备统计，避免父节点污染覆盖率与关键设备数
    parent_ids = {a["parent_id"] for a in flat if a.get("parent_id")}
    leaves = [a for a in flat if a["id"] not in parent_ids]
    planned_ids = {
        row["asset_id"]
        for row in conn.execute("SELECT DISTINCT asset_id FROM maintenance_plans WHERE active = 1").fetchall()
    }
    critical = len([a for a in leaves if a["criticality"] == "A"])
    covered = len([a for a in leaves if a["id"] in planned_ids])
    roots = len([a for a in flat if not a.get("parent_id")])

    counter: dict[str, int] = {}
    for item in leaves:
        counter[item["category"]] = counter.get(item["category"], 0) + 1
    by_category = [
        {"label": CATEGORY_LABEL.get(key, key), "count": value}
        for key, value in sorted(counter.items(), key=lambda kv: -kv[1])
    ]
    top_hours = sorted(
        [a for a in leaves if a["running_hours"]], key=lambda a: -a["running_hours"]
    )[:6]
    return {
        "total": total,
        "leaves": len(leaves),
        "roots": roots,
        "critical": critical,
        "with_plans": covered,
        "coverage": round(covered / len(leaves) * 100) if leaves else 0,
        "by_category": by_category,
        "top_hours": [{"id": a["id"], "code": a["code"], "name": a["name"],
                       "running_hours": a["running_hours"]} for a in top_hours],
        "all_assets": [{"id": a["id"], "code": a["code"], "name": a["name"]} for a in flat],
    }


def history(conn: sqlite3.Connection, asset_id: int, limit: int = 60) -> list[dict]:
    wos = conn.execute(
        "SELECT id, no, title, status, type, completed_at, created_at FROM work_orders"
        " WHERE asset_id = ? ORDER BY COALESCE(completed_at, created_at) DESC LIMIT ?",
        (asset_id, limit),
    ).fetchall()
    events = [
        {
            "kind": "workorder",
            "ref": row["no"],
            "id": row["id"],
            "title": row["title"],
            "status": row["status"],
            "at": row["completed_at"] or row["created_at"],
        }
        for row in wos
    ]
    defects = conn.execute(
        "SELECT id, no, description, status, found_at FROM defects WHERE asset_id = ?"
        " ORDER BY found_at DESC LIMIT ?",
        (asset_id, limit),
    ).fetchall()
    events += [
        {
            "kind": "defect",
            "ref": row["no"],
            "id": row["id"],
            "title": row["description"],
            "status": row["status"],
            "at": row["found_at"],
        }
        for row in defects
    ]
    events.sort(key=lambda e: e["at"] or "", reverse=True)
    return events[:limit]
