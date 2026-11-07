"""工单：状态机、检查项、验收与计划顺延。"""
import json
import sqlite3

from services import audit, ids, plan_service, stock_service
from services.timeutil import now_iso

STATUS_LABEL = {
    "open": "待开始",
    "in_progress": "执行中",
    "done": "待验收",
    "verified": "已验收",
    "cancelled": "已取消",
}
PRIORITY_LABEL = {"low": "低", "normal": "普通", "high": "高", "critical": "紧急"}
TYPE_LABEL = {"planned": "计划维护", "corrective": "纠正性", "defect": "缺陷修复", "inspection": "检查"}

# 允许的流转：当前 → 目标
TRANSITIONS = {
    "open": {"in_progress", "done", "cancelled"},
    "in_progress": {"done", "cancelled"},
    "done": {"verified", "in_progress"},
    "verified": set(),
    "cancelled": set(),
}


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, set())


def _decorate(item: dict) -> dict:
    item["status_label"] = STATUS_LABEL.get(item.get("status"), item.get("status", ""))
    item["priority_label"] = PRIORITY_LABEL.get(item.get("priority"), item.get("priority", ""))
    item["type_label"] = TYPE_LABEL.get(item.get("type"), item.get("type", ""))
    return item


def list_orders(conn: sqlite3.Connection, status: str = "", asset_id: int | None = None,
                limit: int = 200) -> list[dict]:
    sql = (
        "SELECT w.*, a.name AS asset_name, a.code AS asset_code, u.display_name AS completed_name"
        " FROM work_orders w JOIN assets a ON a.id = w.asset_id"
        " LEFT JOIN users u ON u.id = w.completed_by WHERE 1=1"
    )
    params: list = []
    if status in STATUS_LABEL:
        sql += " AND w.status = ?"
        params.append(status)
    if asset_id:
        sql += " AND w.asset_id = ?"
        params.append(asset_id)
    sql += " ORDER BY CASE w.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 WHEN 'done' THEN 2 ELSE 3 END,"
    sql += " CASE w.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,"
    sql += " w.due_at IS NULL, w.due_at, w.created_at DESC LIMIT ?"
    params.append(limit)
    return [_decorate(dict(r)) for r in conn.execute(sql, params).fetchall()]


def get(conn: sqlite3.Connection, wo_id: int) -> dict | None:
    row = conn.execute(
        "SELECT w.*, a.name AS asset_name, a.code AS asset_code, a.running_hours AS asset_hours"
        " FROM work_orders w JOIN assets a ON a.id = w.asset_id WHERE w.id = ?", (wo_id,)
    ).fetchone()
    if row is None:
        return None
    item = _decorate(dict(row))
    item["checklist"] = [dict(r) for r in conn.execute(
        "SELECT * FROM wo_checklist_items WHERE wo_id = ? ORDER BY seq", (wo_id,)
    ).fetchall()]
    item["spares"] = [dict(r) for r in conn.execute(
        "SELECT s.*, p.name AS part_name, p.code AS part_code, p.unit FROM wo_spares s"
        " JOIN parts p ON p.id = s.part_id WHERE s.wo_id = ? ORDER BY s.id", (wo_id,)
    ).fetchall()]
    item["defects"] = [dict(r) for r in conn.execute(
        "SELECT id, no, description, status FROM defects WHERE wo_id = ?", (wo_id,)
    ).fetchall()]
    done = sum(1 for c in item["checklist"] if c["done"])
    item["checklist_done"] = done
    item["checklist_total"] = len(item["checklist"])
    return item


def create(conn: sqlite3.Connection, data: dict, user: dict | None) -> int:
    plan = None
    if data.get("plan_id"):
        plan = plan_service.get(conn, int(data["plan_id"]))
    checklist = data.get("checklist")
    if checklist is None and plan:
        checklist = plan.get("checklist") or []
    title = (data.get("title") or (plan or {}).get("title") or "未命名工单").strip()

    no = ids.next_wo_no(conn)
    cur = conn.execute(
        "INSERT INTO work_orders (no, asset_id, plan_id, type, priority, status, title, description,"
        " due_at, created_by, created_at) VALUES (?,?,?,?,?,'open',?,?,?,?,?)",
        (
            no, int(data["asset_id"]), data.get("plan_id") or None,
            data.get("type") or ("planned" if plan else "corrective"),
            data.get("priority") or "normal", title, data.get("description") or "",
            data.get("due_at") or (plan or {}).get("next_due_at"),
            (user or {}).get("id"), now_iso(),
        ),
    )
    wo_id = int(cur.lastrowid)
    for seq, text in enumerate(checklist or [], start=1):
        conn.execute(
            "INSERT INTO wo_checklist_items (wo_id, seq, text) VALUES (?,?,?)",
            (wo_id, seq, str(text)),
        )
    audit.write(conn, "workorder.create", user, "work_orders", str(wo_id),
                after={"no": no, "title": title, "plan_id": data.get("plan_id")})
    return wo_id


def start(conn: sqlite3.Connection, wo_id: int, user: dict | None) -> dict:
    row = conn.execute("SELECT status FROM work_orders WHERE id = ?", (wo_id,)).fetchone()
    if row is None:
        raise ValueError("工单不存在")
    if not can_transition(row["status"], "in_progress"):
        raise ValueError(f"当前状态「{STATUS_LABEL.get(row['status'], row['status'])}」不能开始执行")
    conn.execute("UPDATE work_orders SET status = 'in_progress', started_at = ? WHERE id = ?",
                 (now_iso(), wo_id))
    audit.write(conn, "workorder.start", user, "work_orders", str(wo_id),
                before={"status": row["status"]}, after={"status": "in_progress"})
    return {"status": "in_progress"}


def complete(conn: sqlite3.Connection, wo_id: int, user: dict | None, payload: dict) -> dict:
    row = conn.execute("SELECT status FROM work_orders WHERE id = ?", (wo_id,)).fetchone()
    if row is None:
        raise ValueError("工单不存在")
    if not can_transition(row["status"], "done"):
        raise ValueError(f"当前状态「{STATUS_LABEL.get(row['status'], row['status'])}」不能提交完成")

    hours = payload.get("running_hours_at_done")
    man_hours = payload.get("man_hours")
    remarks = payload.get("remarks") or ""
    conn.execute(
        "UPDATE work_orders SET status = 'done', completed_at = ?, completed_by = ?,"
        " running_hours_at_done = ?, man_hours = ?,"
        " remarks = CASE WHEN ? = '' THEN remarks ELSE ? END WHERE id = ?",
        (now_iso(), (user or {}).get("id"),
         float(hours) if hours not in (None, "") else None,
         float(man_hours) if man_hours not in (None, "") else None,
         remarks, remarks, wo_id),
    )
    audit.write(conn, "workorder.complete", user, "work_orders", str(wo_id),
                before={"status": row["status"]},
                after={"status": "done", "running_hours": hours, "remarks": remarks[:200]})
    return {"status": "done"}


def verify(conn: sqlite3.Connection, wo_id: int, user: dict | None, payload: dict) -> dict:
    wo = get(conn, wo_id)
    if wo is None:
        raise ValueError("工单不存在")
    if not can_transition(wo["status"], "verified"):
        raise ValueError(f"当前状态「{wo['status_label']}」不能验收")

    conn.execute(
        "UPDATE work_orders SET status = 'verified', verified_by = ?, verified_at = ? WHERE id = ?",
        ((user or {}).get("id"), now_iso(), wo_id),
    )
    # 记录完成时的运行小时，作为计划顺延基准
    done_hours = wo["running_hours_at_done"]
    if done_hours is not None:
        conn.execute("UPDATE assets SET running_hours = ?, running_hours_at = ? WHERE id = ? AND running_hours < ?",
                     (done_hours, now_iso(), wo["asset_id"], done_hours))
    if wo["plan_id"]:
        plan_service.mark_done(conn, int(wo["plan_id"]),
                               (wo["completed_at"] or now_iso())[:10], done_hours)
    # 关联缺陷置为已修复，等待缺陷关闭验证
    conn.execute("UPDATE defects SET status = 'fixed' WHERE wo_id = ? AND status IN ('open','in_progress')",
                 (wo_id,))
    audit.write(conn, "workorder.verify", user, "work_orders", str(wo_id),
                before={"status": wo["status"]}, after={"status": "verified"})
    return {"status": "verified"}


def cancel(conn: sqlite3.Connection, wo_id: int, user: dict | None, reason: str = "") -> dict:
    row = conn.execute("SELECT status FROM work_orders WHERE id = ?", (wo_id,)).fetchone()
    if row is None:
        raise ValueError("工单不存在")
    if not can_transition(row["status"], "cancelled"):
        raise ValueError(f"当前状态「{STATUS_LABEL.get(row['status'], row['status'])}」不能取消")
    conn.execute("UPDATE work_orders SET status = 'cancelled', remarks = ? WHERE id = ?",
                 (f"取消原因：{reason}" if reason else "", wo_id))
    audit.write(conn, "workorder.cancel", user, "work_orders", str(wo_id),
                before={"status": row["status"]}, after={"status": "cancelled", "reason": reason})
    return {"status": "cancelled"}


def toggle_check(conn: sqlite3.Connection, wo_id: int, item_id: int, done: bool,
                 user: dict | None, remark: str = "") -> dict:
    row = conn.execute(
        "SELECT i.*, w.status FROM wo_checklist_items i JOIN work_orders w ON w.id = i.wo_id"
        " WHERE i.id = ? AND i.wo_id = ?", (item_id, wo_id)
    ).fetchone()
    if row is None:
        raise ValueError("检查项不存在")
    if row["status"] in ("verified", "cancelled"):
        raise ValueError("已验收或已取消的工单不可修改检查项")
    conn.execute(
        "UPDATE wo_checklist_items SET done = ?, done_at = ?, done_by = ?,"
        " remark = CASE WHEN ? = '' THEN remark ELSE ? END WHERE id = ?",
        (1 if done else 0, now_iso() if done else None, (user or {}).get("id"),
         remark, remark, item_id),
    )
    audit.write(conn, "workorder.check", user, "wo_checklist_items", str(item_id),
                before={"done": row["done"]}, after={"done": bool(done)})
    return {"done": bool(done)}


def add_spare(conn: sqlite3.Connection, wo_id: int, part_id: int, qty: float,
              user: dict | None) -> dict:
    wo = conn.execute("SELECT status FROM work_orders WHERE id = ?", (wo_id,)).fetchone()
    if wo is None:
        raise ValueError("工单不存在")
    if wo["status"] in ("verified", "cancelled"):
        raise ValueError("已关闭的工单不能领料")
    stock_service.issue_to_workorder(conn, part_id, qty, wo_id, user)
    return {"part_id": part_id, "qty": qty}


def generate_from_plans(conn: sqlite3.Connection, plan_ids: list[int],
                        user: dict | None) -> dict:
    """批量生成工单，幂等：同一计划已有未关闭工单则跳过。"""
    created, skipped = [], []
    for pid in plan_ids:
        plan = plan_service.get(conn, int(pid))
        if plan is None:
            skipped.append({"plan_id": pid, "reason": "计划不存在"})
            continue
        exists = conn.execute(
            "SELECT id FROM work_orders WHERE plan_id = ? AND status IN ('open','in_progress','done') LIMIT 1",
            (int(pid),),
        ).fetchone()
        if exists:
            skipped.append({"plan_id": pid, "reason": "已有未关闭工单", "wo_id": exists["id"]})
            continue
        wo_id = create(conn, {
            "asset_id": plan["asset_id"],
            "plan_id": plan["id"],
            "type": "planned",
            "title": plan["title"],
            "due_at": plan["next_due_at"],
        }, user)
        created.append(wo_id)
    return {"created": created, "skipped": skipped}
