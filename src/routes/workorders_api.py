"""工单 API。"""
from flask import Blueprint, g, request

from db.connection import get_db, tx
from middleware.auth import require
from routes._helpers import as_float, as_int, bool_arg, fail, json_body, ok
from services import audit, wo_service

bp = Blueprint("workorders_api", __name__, url_prefix="/api/v1/workorders")


@bp.get("")
def list_orders():
    conn = get_db()
    items = wo_service.list_orders(
        conn,
        status=(request.args.get("status") or "").strip(),
        asset_id=as_int(request.args.get("asset_id")),
        limit=as_int(request.args.get("limit"), 200) or 200,
    )
    return ok({"items": items, "total": len(items)})


@bp.get("/<int:wo_id>")
def get_order(wo_id: int):
    conn = get_db()
    item = wo_service.get(conn, wo_id)
    if item is None:
        return fail("工单不存在", 404, "not_found")
    return ok({"item": item})


@bp.post("")
@require("wo.write")
def create_order():
    data = json_body()
    if not data.get("asset_id"):
        return fail("请选择设备")
    conn = get_db()
    with tx(conn):
        wo_id = wo_service.create(conn, data, g.user)
    return ok({"id": wo_id}, 201)


def _act(wo_id: int, action: str, payload: dict | None = None):
    conn = get_db()
    with tx(conn):
        try:
            if action == "start":
                result = wo_service.start(conn, wo_id, g.user)
            elif action == "complete":
                result = wo_service.complete(conn, wo_id, g.user, payload or {})
            elif action == "verify":
                result = wo_service.verify(conn, wo_id, g.user, payload or {})
            else:
                result = wo_service.cancel(conn, wo_id, g.user, (payload or {}).get("reason", ""))
        except ValueError as exc:
            return fail(str(exc), 400)
    return ok(result)


@bp.post("/<int:wo_id>/start")
@require("wo.write")
def start_order(wo_id: int):
    return _act(wo_id, "start")


@bp.post("/<int:wo_id>/complete")
@require("wo.write")
def complete_order(wo_id: int):
    return _act(wo_id, "complete", json_body())


@bp.post("/<int:wo_id>/verify")
@require("wo.verify")
def verify_order(wo_id: int):
    return _act(wo_id, "verify", json_body())


@bp.post("/<int:wo_id>/cancel")
@require("wo.verify")
def cancel_order(wo_id: int):
    return _act(wo_id, "cancel", json_body())


@bp.patch("/<int:wo_id>/checklist/<int:item_id>")
@require("wo.write")
def toggle_item(wo_id: int, item_id: int):
    data = json_body()
    conn = get_db()
    with tx(conn):
        try:
            result = wo_service.toggle_check(
                conn, wo_id, item_id, bool(data.get("done")), g.user, data.get("remark") or ""
            )
        except ValueError as exc:
            return fail(str(exc), 400)
    return ok(result)


@bp.post("/<int:wo_id>/spares")
@require("part.move")
def add_spare(wo_id: int):
    data = json_body()
    part_id = as_int(data.get("part_id"))
    qty = as_float(data.get("qty"))
    if not part_id or qty is None or qty <= 0:
        return fail("请选择备件并填写数量")
    conn = get_db()
    with tx(conn):
        try:
            result = wo_service.add_spare(conn, wo_id, part_id, qty, g.user)
        except ValueError as exc:
            return fail(str(exc), 400)
    return ok(result)
