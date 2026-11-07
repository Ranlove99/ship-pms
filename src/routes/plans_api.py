"""维护计划与到期清单 API。"""
from flask import Blueprint, g, request

from db.connection import get_db, get_int_setting, tx
from middleware.auth import require
from routes._helpers import as_int, fail, json_body, ok, tz_name
from services import audit, plan_service, wo_service
from services.timeutil import today_str

bp = Blueprint("plans_api", __name__, url_prefix="/api/v1")


@bp.get("/plans")
def list_plans():
    conn = get_db()
    warn = get_int_setting(conn, "due_warn_days", 30)
    hours_warn = get_int_setting(conn, "hours_warn", 100)
    items = plan_service.list_with_state(conn, today_str(tz_name(conn)), warn, hours_warn)
    return ok({"items": items, "total": len(items)})


@bp.post("/plans")
@require("plan.write")
def create_plan():
    data = json_body()
    if not data.get("asset_id"):
        return fail("请选择设备")
    if not (data.get("title") or "").strip():
        return fail("请填写计划名称")
    if not data.get("interval_days") and not data.get("interval_hours"):
        return fail("日历间隔与运行小时间隔至少填一项")
    conn = get_db()
    with tx(conn):
        plan_id = plan_service.create(conn, data)
        audit.write(conn, "plan.create", g.user, "maintenance_plans", str(plan_id),
                    after={"title": data.get("title"), "asset_id": data.get("asset_id")})
    return ok({"id": plan_id}, 201)


@bp.patch("/plans/<int:plan_id>")
@require("plan.write")
def update_plan(plan_id: int):
    data = json_body()
    conn = get_db()
    before = plan_service.get(conn, plan_id)
    if before is None:
        return fail("计划不存在", 404, "not_found")
    with tx(conn):
        plan_service.update(conn, plan_id, data)
        audit.write(conn, "plan.update", g.user, "maintenance_plans", str(plan_id),
                    before={"title": before["title"], "next_due_at": before["next_due_at"]}, after=data)
    return ok({"id": plan_id})


@bp.get("/due")
def due_list():
    conn = get_db()
    days = as_int(request.args.get("days"), 30) or 30
    warn = get_int_setting(conn, "due_warn_days", 30)
    hours_warn = get_int_setting(conn, "hours_warn", 100)
    items = plan_service.due_list(conn, days, today_str(tz_name(conn)), warn, hours_warn)
    return ok({"items": items, "total": len(items), "days": days})


@bp.post("/due/generate")
@require("wo.write")
def generate_workorders():
    data = json_body()
    plan_ids = data.get("plan_ids") or []
    if not isinstance(plan_ids, list) or not plan_ids:
        return fail("请选择要派工的计划")
    conn = get_db()
    with tx(conn):
        result = wo_service.generate_from_plans(conn, [int(p) for p in plan_ids], g.user)
        audit.write(conn, "due.generate", g.user, "work_orders", "",
                    after={"created": result["created"], "skipped": len(result["skipped"])})
    return ok(result)
