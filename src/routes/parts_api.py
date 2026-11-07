"""备件与库存 API。"""
from flask import Blueprint, g, request

from db.connection import get_db, tx
from middleware.auth import require
from routes._helpers import as_float, as_int, bool_arg, fail, json_body, ok
from services import audit, stock_service

bp = Blueprint("parts_api", __name__, url_prefix="/api/v1/parts")


@bp.get("")
def list_parts():
    conn = get_db()
    items = stock_service.list_parts(
        conn,
        query=(request.args.get("q") or "").strip(),
        only_alerts=bool_arg(request.args.get("alerts")),
    )
    return ok({"items": items, "total": len(items), "alerts": len([i for i in items if i["below_min"]])})


@bp.post("")
@require("part.write")
def create_part():
    data = json_body()
    if not (data.get("code") or "").strip() or not (data.get("name") or "").strip():
        return fail("备件编码与名称必填")
    conn = get_db()
    with tx(conn):
        exists = conn.execute("SELECT id FROM parts WHERE code = ?", (data["code"].strip(),)).fetchone()
        if exists:
            return fail("备件编码已存在", 409, "conflict")
        part_id = stock_service.create(conn, data, g.user)
    return ok({"id": part_id}, 201)


@bp.patch("/<int:part_id>")
@require("part.write")
def update_part(part_id: int):
    data = json_body()
    conn = get_db()
    with tx(conn):
        stock_service.update(conn, part_id, data, g.user)
    return ok({"id": part_id})


@bp.post("/<int:part_id>/moves")
@require("part.move")
def create_move(part_id: int):
    data = json_body()
    move_type = (data.get("type") or "").strip()
    qty = as_float(data.get("qty"))
    if move_type not in {"in", "out", "adjust", "reserve", "release"}:
        return fail("库存动作不合法")
    if qty is None:
        return fail("请填写数量")
    conn = get_db()
    with tx(conn):
        try:
            result = stock_service.move(
                conn, part_id, move_type, qty, g.user,
                ref_no=data.get("ref_no") or "",
                note=data.get("note") or "",
                wo_id=as_int(data.get("wo_id")),
            )
        except ValueError as exc:
            return fail(str(exc), 400)
    return ok(result, 201)


@bp.get("/moves")
def list_moves():
    conn = get_db()
    items = stock_service.moves(conn, as_int(request.args.get("part_id")), as_int(request.args.get("limit"), 100) or 100)
    return ok({"items": items})


@bp.get("/alerts")
def list_alerts():
    conn = get_db()
    items = stock_service.alerts(conn)
    return ok({"items": items, "total": len(items)})
