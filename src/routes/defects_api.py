"""缺陷 API。"""
from flask import Blueprint, g, request

from db.connection import get_db, tx
from middleware.auth import require
from routes._helpers import fail, json_body, ok
from services import audit, defect_service

bp = Blueprint("defects_api", __name__, url_prefix="/api/v1/defects")


@bp.get("")
def list_defects():
    conn = get_db()
    items = defect_service.list_defects(conn, status=(request.args.get("status") or "").strip())
    return ok({"items": items, "total": len(items)})


@bp.get("/<int:defect_id>")
def get_defect(defect_id: int):
    conn = get_db()
    item = defect_service.get(conn, defect_id)
    if item is None:
        return fail("缺陷不存在", 404, "not_found")
    return ok({"item": item})


@bp.post("")
@require("defect.write")
def create_defect():
    data = json_body()
    if not (data.get("description") or "").strip():
        return fail("请填写缺陷描述")
    conn = get_db()
    with tx(conn):
        defect_id = defect_service.create(conn, data, g.user)
    return ok({"id": defect_id}, 201)


@bp.patch("/<int:defect_id>")
@require("defect.write")
def update_defect(defect_id: int):
    data = json_body()
    conn = get_db()
    with tx(conn):
        try:
            defect_service.update(conn, defect_id, data, g.user)
        except ValueError as exc:
            return fail(str(exc), 400)
    return ok({"id": defect_id})


@bp.post("/<int:defect_id>/close")
@require("defect.close")
def close_defect(defect_id: int):
    data = json_body()
    conn = get_db()
    with tx(conn):
        try:
            result = defect_service.close(conn, defect_id, data.get("corrective_action") or "", g.user)
        except ValueError as exc:
            return fail(str(exc), 400)
    return ok(result)


@bp.post("/<int:defect_id>/to-workorder")
@require("wo.write")
def defect_to_wo(defect_id: int):
    conn = get_db()
    with tx(conn):
        try:
            result = defect_service.to_workorder(conn, defect_id, g.user)
        except ValueError as exc:
            return fail(str(exc), 400)
    return ok(result, 201)
