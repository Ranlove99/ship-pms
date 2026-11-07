"""页面渲染路由（服务端渲染，写操作走 JSON API）。"""
from flask import Blueprint, g, redirect, render_template, request, url_for

from config import Config
from db.connection import get_db, get_int_setting
from middleware.auth import require_login
from routes._helpers import as_int, tz_name
from services import (asset_service, cert_service, dashboard, defect_service,
                      export_service, ops_service, plan_service, record_service,
                      stock_doc_service, stock_service, supplier_service, wo_service)
from services.timeutil import today_str

bp = Blueprint("pages", __name__)


def _guard():
    return require_login()


def _render(template: str, **context):
    return render_template(template, **context)


@bp.get("/login")
def login():
    if g.get("user"):
        return redirect(url_for("pages.dashboard"))
    return render_template("login.html", next=request.args.get("next") or "")


@bp.get("/")
def index():
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    data = dashboard.summary(conn)
    return _render("dashboard.html", data=data, hours=dashboard.critical_hours(conn), page="dashboard")


@bp.get("/due")
def due():
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    days = as_int(request.args.get("days"), 30) or 30
    warn = get_int_setting(conn, "due_warn_days", 30)
    hours_warn = get_int_setting(conn, "hours_warn", 100)
    items = plan_service.due_list(conn, days, today_str(tz_name(conn)), warn, hours_warn)
    return _render("due.html", items=items, days=days, page="due")


@bp.get("/workorders")
def workorders():
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    status = (request.args.get("status") or "").strip()
    items = wo_service.list_orders(conn, status=status)
    assets = asset_service.list_all(conn)
    return _render("workorders.html", items=items, status=status, assets=assets, page="workorders")


@bp.get("/workorders/<int:wo_id>")
def workorder_detail(wo_id: int):
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    item = wo_service.get(conn, wo_id)
    if item is None:
        return render_template("error.html", code=404, message="工单不存在"), 404
    return _render("workorder_detail.html", item=item, parts=stock_service.list_parts(conn),
                   page="workorders")


@bp.get("/plans")
def plans():
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    warn = get_int_setting(conn, "due_warn_days", 30)
    hours_warn = get_int_setting(conn, "hours_warn", 100)
    items = plan_service.list_with_state(conn, today_str(tz_name(conn)), warn, hours_warn, active_only=False)
    return _render("plans.html", items=items, assets=asset_service.list_all(conn), page="plans")


@bp.get("/defects")
def defects():
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    status = (request.args.get("status") or "").strip()
    items = defect_service.list_defects(conn, status=status)
    return _render("defects.html", items=items, status=status,
                   assets=asset_service.list_all(conn), page="defects")


@bp.get("/assets")
def assets():
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    return _render("assets.html", tree=asset_service.tree(conn),
                   stats=asset_service.stats(conn), page="assets")


@bp.get("/assets/<int:asset_id>")
def asset_detail(asset_id: int):
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    item = asset_service.get(conn, asset_id)
    if item is None:
        return render_template("error.html", code=404, message="设备不存在"), 404
    plans_raw = conn.execute(
        "SELECT * FROM maintenance_plans WHERE asset_id = ? ORDER BY id", (asset_id,)
    ).fetchall()
    children = conn.execute(
        "SELECT * FROM assets WHERE parent_id = ? ORDER BY code", (asset_id,)
    ).fetchall()
    return _render("asset_detail.html", item=item,
                   history=asset_service.history(conn, asset_id),
                   plans=[dict(r) for r in plans_raw],
                   children=[dict(r) for r in children],
                   stats=asset_service.stats(conn), page="assets")


@bp.get("/parts")
def parts():
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    tz = tz_name(conn)
    items = stock_service.list_parts(conn, query=(request.args.get("q") or "").strip())
    return _render("parts.html", items=items, moves=stock_service.moves(conn, limit=40),
                   alert_count=len([i for i in items if i["below_min"]]),
                   reorder=stock_service.reorder_rows(conn),
                   consumption=stock_service.consumption_rows(conn, limit=10),
                   value=stock_service.value_summary(conn),
                   expiring=stock_service.expiring_rows(conn, tz_name=tz),
                   suppliers=supplier_service.list_suppliers(conn), page="parts")


@bp.get("/stock-docs")
def stock_docs():
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    doc_type = (request.args.get("type") or "").strip()
    status = (request.args.get("status") or "").strip()
    q = (request.args.get("q") or "").strip()
    items = stock_doc_service.list_docs(conn, doc_type=doc_type, status=status, q=q, limit=200)
    open_wos = [{"id": w["id"], "no": w["no"], "title": w["title"],
                 "asset_name": w["asset_name"]}
                for w in wo_service.list_orders(conn, limit=100)
                if w["status"] in ("open", "in_progress", "done")]
    return _render("stock_docs.html", items=items, doc_type=doc_type, status=status,
                   q=q, parts=stock_service.list_parts(conn), open_wos=open_wos,
                   page="stock_docs")


@bp.get("/stock-docs/<int:doc_id>")
def stock_doc_detail(doc_id: int):
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    doc = stock_doc_service.get_doc(conn, doc_id)
    if doc is None:
        return render_template("error.html", code=404, message="单据不存在"), 404
    open_wos = [{"id": w["id"], "no": w["no"], "title": w["title"],
                 "asset_name": w["asset_name"]}
                for w in wo_service.list_orders(conn, limit=100)
                if w["status"] in ("open", "in_progress", "done")]
    return _render("stock_doc_detail.html", doc=doc, parts=stock_service.list_parts(conn),
                   open_wos=open_wos, page="stock_docs")


@bp.get("/certificates")
def certificates():
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    items = cert_service.list_certs(conn, today_str(tz_name(conn)))
    return _render("certificates.html", items=items, page="certificates")


@bp.get("/records")
@bp.get("/records/<code>")
def records(code: str = ""):
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    books = record_service.books(conn)
    if not code and books:
        code = books[0]["code"]
    book = record_service.book_by_code(conn, code) if code else None
    entries = record_service.entries(conn, book["id"]) if book else []
    return _render("records.html", books=books, book=book, entries=entries, page="records")


@bp.get("/reports")
def reports():
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    today = today_str(tz_name(conn))
    plans = plan_service.list_with_state(conn, today, 30, 100)
    orders = wo_service.list_orders(conn, limit=500)
    stats = {
        "plans_total": len(plans),
        "overdue": len([p for p in plans if p["status"] == "overdue"]),
        "due": len([p for p in plans if p["status"] == "due"]),
        "wos": len(orders),
        "wos_open": len([w for w in orders if w["status"] in ("open", "in_progress")]),
        "wos_verify": len([w for w in orders if w["status"] == "done"]),
        "defects": defect_service.open_count(conn),
        "certs": cert_service.list_certs(conn, today),
    }
    return _render("reports.html", stats=stats, page="reports")


@bp.get("/settings")
def settings():
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    vessel = conn.execute("SELECT * FROM vessel WHERE id = 1").fetchone()
    users = conn.execute(
        "SELECT id, username, display_name, role, active, last_login_at FROM users ORDER BY id"
    ).fetchall()
    rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    return _render("settings.html", vessel=dict(vessel) if vessel else {},
                   users=[dict(u) for u in users],
                   suppliers=supplier_service.list_suppliers(conn),
                   settings={r["key"]: r["value"] for r in rows},
                   backups=ops_service.list_backups()[:8],
                   socket_path=Config.SOCKET_PATH,
                   page="settings")


@bp.get("/print/psc-pack")
def psc_pack():
    guard = _guard()
    if guard:
        return guard
    conn = get_db()
    days = as_int(request.args.get("days"), 90) or 90
    data = export_service.psc_pack(conn, days)
    return _render("print/psc_pack.html", data=data, page="reports")
