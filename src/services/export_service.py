"""导出：CSV 与 PSC 检查包数据组装。"""
import csv
import io
import sqlite3

from services import cert_service, defect_service, plan_service, record_service, stock_service, wo_service
from services.timeutil import days_between, today_str


def csv_response(rows: list[dict], headers: list[tuple[str, str]], filename: str):
    from flask import Response

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([label for _, label in headers])
    for row in rows:
        writer.writerow([_cell(row.get(key)) for key, _ in headers])
    data = "\ufeff" + buffer.getvalue()
    resp = Response(data, mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        import json

        return json.dumps(value, ensure_ascii=False)
    return value


def psc_pack(conn: sqlite3.Connection, days: int = 90) -> dict:
    """组装 PSC / 审核自查包。所有数据来自系统记录，不做美化。"""
    today = today_str()
    vessel = conn.execute("SELECT * FROM vessel WHERE id = 1").fetchone()

    plans = plan_service.list_with_state(conn, today, 30, 100)
    overdue = [p for p in plans if p["status"] == "overdue"]
    due_soon = [p for p in plans if p["status"] == "due"]

    completed = conn.execute(
        "SELECT w.*, a.name AS asset_name, a.code AS asset_code, u.display_name AS completed_name"
        " FROM work_orders w JOIN assets a ON a.id = w.asset_id"
        " LEFT JOIN users u ON u.id = w.completed_by"
        " WHERE w.status IN ('done','verified') AND w.completed_at IS NOT NULL"
        " AND date(w.completed_at) >= date('now', ?) ORDER BY w.completed_at DESC",
        (f"-{int(days)} days",),
    ).fetchall()

    defects = [d for d in defect_service.list_defects(conn) if d["status"] != "closed"]
    certs = cert_service.list_certs(conn, today)
    books = record_service.books(conn)
    hours = conn.execute(
        "SELECT code, name, running_hours, running_hours_at FROM assets"
        " WHERE criticality IN ('A','B') AND status = 'in_service' ORDER BY criticality, code"
    ).fetchall()

    return {
        "vessel": dict(vessel) if vessel else {},
        "generated_at": today,
        "window_days": days,
        "overdue": overdue,
        "due_soon": due_soon,
        "completed": [dict(r) for r in completed],
        "defects_open": defects,
        "certificates": certs,
        "books": books,
        "hours": [dict(r) for r in hours],
        "counts": {
            "overdue": len(overdue),
            "due_soon": len(due_soon),
            "completed": len(completed),
            "defects_open": len(defects),
            "cert_expired": len([c for c in certs if c["state"] == "expired"]),
            "records_pending": sum(b["pending"] for b in books),
            "chain_ok": all(b["chain_ok"] for b in books),
        },
    }


def overdue_rows(conn: sqlite3.Connection) -> list[dict]:
    today = today_str()
    rows = plan_service.list_with_state(conn, today, 30, 100)
    out = []
    for item in rows:
        if item["status"] not in ("overdue", "due"):
            continue
        out.append({
            "asset_code": item["asset_code"],
            "asset_name": item["asset_name"],
            "title": item["title"],
            "next_due_at": item["next_due_at"] or "",
            "days_left": item["days_left"] if item["days_left"] is not None else "",
            "next_due_hours": item["next_due_hours"] if item["next_due_hours"] is not None else "",
            "hours_left": item["hours_left"] if item["hours_left"] is not None else "",
            "state": item["state_label"],
            "regulation": item["regulation_ref"],
        })
    return out


def defect_rows(conn: sqlite3.Connection) -> list[dict]:
    return [{
        "no": d["no"],
        "asset": f"{d['asset_code'] or ''} {d['asset_name'] or ''}".strip(),
        "severity": d["severity_label"],
        "status": d["status_label"],
        "found_at": d["found_at"][:10],
        "description": d["description"],
        "corrective": d.get("corrective_action") or "",
    } for d in defect_service.list_defects(conn)]


def cert_rows(conn: sqlite3.Connection) -> list[dict]:
    return [{
        "name": c["name"],
        "category": c["category_label"],
        "cert_no": c["cert_no"],
        "issuer": c["issuer"],
        "issued_at": c["issued_at"] or "",
        "expires_at": c["expires_at"] or "",
        "state": c["state_label"],
        "days_left": c["days_left"] if c["days_left"] is not None else "",
    } for c in cert_service.list_certs(conn)]


def wo_rows(conn: sqlite3.Connection, status: str = "") -> list[dict]:
    return [{
        "no": w["no"],
        "asset": f"{w['asset_code']} {w['asset_name']}",
        "title": w["title"],
        "type": w["type_label"],
        "priority": w["priority_label"],
        "status": w["status_label"],
        "due_at": w["due_at"] or "",
        "completed_at": (w["completed_at"] or "")[:10],
        "hours": w["running_hours_at_done"] if w["running_hours_at_done"] is not None else "",
    } for w in wo_service.list_orders(conn, status)]


def reorder_rows(conn: sqlite3.Connection, days: int = 90) -> list[dict]:
    return [{
        "code": r["code"], "name": r["name"], "spec": r["spec"], "unit": r["unit"],
        "location": r["location"], "critical": "是" if r["critical"] else "否",
        "on_hand": r["on_hand"], "reserved": r["reserved"], "available": r["available"],
        "min_qty": r["min_qty"], "used_days": r["used_days"], "suggested": r["suggested"],
    } for r in stock_service.reorder_rows(conn, days)]


def moves_rows(conn: sqlite3.Connection, days: int = 90, move_type: str = "") -> list[dict]:
    return [{
        "at": (m["at"] or "")[:19].replace("T", " "),
        "part_code": m["part_code"], "part_name": m["part_name"],
        "type": m["type_label"], "qty": m["qty"], "unit": m["unit"],
        "ref_no": m["ref_no"] or "", "operator": m["operator_name"] or "", "note": m["note"] or "",
    } for m in stock_service.moves_filtered(conn, days, move_type)]


def consumption_rows(conn: sqlite3.Connection, days: int = 90) -> list[dict]:
    return [{
        "code": r["code"], "name": r["name"], "unit": r["unit"],
        "qty": r["qty"], "times": r["times"],
    } for r in stock_service.consumption_rows(conn, days)]
