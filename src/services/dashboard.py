"""总览页数据聚合。"""
import sqlite3

from db.connection import get_int_setting
from services import (cert_service, defect_service, plan_service, record_service,
                      stock_service, wo_service)
from services.timeutil import local_now, today_str


def summary(conn: sqlite3.Connection) -> dict:
    today = today_str()
    warn_days = get_int_setting(conn, "due_warn_days", 30)
    hours_warn = get_int_setting(conn, "hours_warn", 100)

    plans = plan_service.list_with_state(conn, today, warn_days, hours_warn)
    overdue = [p for p in plans if p["status"] == "overdue"]
    due_soon = [p for p in plans if p["status"] == "due"]
    open_wos = wo_service.list_orders(conn, limit=500)
    wos_pending = [w for w in open_wos if w["status"] in ("open", "in_progress")]
    wos_to_verify = [w for w in open_wos if w["status"] == "done"]

    books = record_service.books(conn)
    pending_records = sum(b["pending"] for b in books)
    certs = cert_service.list_certs(conn, today)
    cert_alerts = [c for c in certs if c["state"] in ("expired", "soon")]
    reorder = stock_service.reorder_rows(conn)
    value = stock_service.value_summary(conn)

    return {
        "today": today,
        "local_time": local_now(_tz(conn)).strftime("%Y-%m-%d %H:%M"),
        "plans_overdue": len(overdue),
        "plans_due_soon": len(due_soon),
        "plans_total": len(plans),
        "defects": defect_service.open_count(conn),
        "wos_pending": len(wos_pending),
        "wos_to_verify": len(wos_to_verify),
        "pending_records": pending_records,
        "cert_alerts": len(cert_alerts),
        "cert_expired": len([c for c in certs if c["state"] == "expired"]),
        "reorder": len(reorder),
        "parts_value": value["amount"],
        "due_items": (overdue + due_soon)[:8],
        "recent_defects": defect_service.list_defects(conn, status="open", limit=5),
        "todo_wos": wos_pending[:6],
        "cert_items": cert_alerts[:5],
        "chain_ok": all(b["chain_ok"] for b in books),
        "books": books,
    }


def critical_hours(conn: sqlite3.Connection, limit: int = 8) -> list[dict]:
    """只列实际运行过的设备（父节点分组不参与小时跟踪）。"""
    rows = conn.execute(
        "SELECT id, code, name, running_hours, running_hours_at FROM assets"
        " WHERE criticality = 'A' AND status = 'in_service' AND running_hours > 0"
        " ORDER BY running_hours DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def _tz(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT timezone FROM vessel WHERE id = 1").fetchone()
    return (row["timezone"] if row else None) or "Asia/Shanghai"
