"""维护计划：双触发到期计算与完成顺延。"""
import json
import sqlite3

from services import due_calc
from services.timeutil import now_iso, today_str


def _checklist(raw: str | None) -> list[str]:
    try:
        items = json.loads(raw or "[]")
    except ValueError:
        return []
    return [str(x) for x in items if str(x).strip()]


def list_with_state(conn: sqlite3.Connection, today: str | None = None,
                    warn_days: int = 30, hours_warn: int = 100,
                    active_only: bool = True) -> list[dict]:
    today = today or today_str()
    sql = (
        "SELECT p.*, a.name AS asset_name, a.code AS asset_code, a.criticality,"
        " a.running_hours AS asset_hours FROM maintenance_plans p"
        " JOIN assets a ON a.id = p.asset_id"
    )
    if active_only:
        sql += " WHERE p.active = 1"
    sql += " ORDER BY p.next_due_at IS NULL, p.next_due_at"
    rows = conn.execute(sql).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        state = due_calc.plan_state(
            item["next_due_at"], item["next_due_hours"], today,
            item["asset_hours"], warn_days, hours_warn,
        )
        item.update(state)
        item["state_label"] = due_calc.label(state)
        item["checklist"] = _checklist(item.pop("checklist_json", "[]"))
        result.append(item)
    result.sort(key=due_calc.sort_key)
    return result


def due_list(conn: sqlite3.Connection, days: int = 30, today: str | None = None,
             warn_days: int = 30, hours_warn: int = 100) -> list[dict]:
    items = list_with_state(conn, today, warn_days, hours_warn)
    out = []
    for item in items:
        if item["status"] == "overdue":
            out.append(item)
        elif item["status"] == "due":
            out.append(item)
        elif item["days_left"] is not None and item["days_left"] <= days:
            out.append(item)
        elif item["hours_left"] is not None and item["hours_left"] <= hours_warn * 3:
            out.append(item)
    return out


def get(conn: sqlite3.Connection, plan_id: int) -> dict | None:
    row = conn.execute(
        "SELECT p.*, a.name AS asset_name, a.code AS asset_code FROM maintenance_plans p"
        " JOIN assets a ON a.id = p.asset_id WHERE p.id = ?", (plan_id,)
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["checklist"] = _checklist(item.pop("checklist_json", "[]"))
    return item


def create(conn: sqlite3.Connection, data: dict) -> int:
    interval_days = data.get("interval_days")
    interval_hours = data.get("interval_hours")
    next_at, next_hours = due_calc.compute_next(
        data.get("last_done_at") or None,
        int(interval_days) if interval_days else None,
        data.get("last_done_hours"),
        float(interval_hours) if interval_hours else None,
    )
    if data.get("next_due_at"):
        next_at = data["next_due_at"]
    cur = conn.execute(
        "INSERT INTO maintenance_plans (asset_id, code, title, interval_days, interval_hours,"
        " last_done_at, last_done_hours, next_due_at, next_due_hours, checklist_json,"
        " required_spares_json, est_hours, responsible_role, regulation_ref, active, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
        (
            data["asset_id"],
            (data.get("code") or "").strip(),
            (data.get("title") or "").strip(),
            int(interval_days) if interval_days else None,
            float(interval_hours) if interval_hours else None,
            data.get("last_done_at") or None,
            float(data["last_done_hours"]) if data.get("last_done_hours") not in (None, "") else None,
            next_at,
            next_hours,
            json.dumps(data.get("checklist") or [], ensure_ascii=False),
            json.dumps(data.get("required_spares") or [], ensure_ascii=False),
            float(data.get("est_hours") or 0),
            data.get("responsible_role") or "officer",
            data.get("regulation_ref") or "",
            now_iso(),
        ),
    )
    return int(cur.lastrowid)


def update(conn: sqlite3.Connection, plan_id: int, data: dict) -> None:
    current = get(conn, plan_id)
    if current is None:
        return
    interval_days = data.get("interval_days", current["interval_days"])
    interval_hours = data.get("interval_hours", current["interval_hours"])
    last_done_at = data.get("last_done_at", current["last_done_at"])
    last_done_hours = data.get("last_done_hours", current["last_done_hours"])
    next_at, next_hours = due_calc.compute_next(
        last_done_at, int(interval_days) if interval_days else None,
        last_done_hours, float(interval_hours) if interval_hours else None,
    )
    if data.get("next_due_at"):
        next_at = data["next_due_at"]
    checklist = data.get("checklist", current["checklist"])

    conn.execute(
        "UPDATE maintenance_plans SET title = ?, interval_days = ?, interval_hours = ?,"
        " last_done_at = ?, last_done_hours = ?, next_due_at = ?, next_due_hours = ?,"
        " checklist_json = ?, required_spares_json = ?, est_hours = ?, responsible_role = ?,"
        " regulation_ref = ?, active = ? WHERE id = ?",
        (
            data.get("title", current["title"]),
            int(interval_days) if interval_days else None,
            float(interval_hours) if interval_hours else None,
            last_done_at or None,
            float(last_done_hours) if last_done_hours not in (None, "") else None,
            next_at,
            next_hours,
            json.dumps(checklist, ensure_ascii=False),
            json.dumps(data.get("required_spares", json.loads(current["required_spares_json"] or "[]")),
                       ensure_ascii=False),
            float(data.get("est_hours", current["est_hours"]) or 0),
            data.get("responsible_role", current["responsible_role"]),
            data.get("regulation_ref", current["regulation_ref"]),
            1 if data.get("active", current["active"]) else 0,
            plan_id,
        ),
    )


def mark_done(conn: sqlite3.Connection, plan_id: int, done_at: str, done_hours: float | None) -> None:
    """工单验收后顺延计划。基准取实际完成时点与运行小时。"""
    plan = get(conn, plan_id)
    if plan is None:
        return
    next_at, next_hours = due_calc.compute_next(
        done_at[:10], plan["interval_days"], done_hours, plan["interval_hours"]
    )
    conn.execute(
        "UPDATE maintenance_plans SET last_done_at = ?, last_done_hours = ?,"
        " next_due_at = ?, next_due_hours = ? WHERE id = ?",
        (done_at[:10], done_hours, next_at, next_hours, plan_id),
    )
