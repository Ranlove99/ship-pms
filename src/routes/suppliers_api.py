"""供应商台账 API。"""
from flask import Blueprint, g, request

from db.connection import get_db, tx
from middleware.auth import require
from routes._helpers import fail, json_body, ok
from services import supplier_service

bp = Blueprint("suppliers_api", __name__, url_prefix="/api/v1/suppliers")


@bp.get("")
def list_suppliers():
    items = supplier_service.list_suppliers(get_db())
    return ok({"items": items, "total": len(items)})


@bp.post("")
@require("part.write")
def create_supplier():
    conn = get_db()
    try:
        with tx(conn):
            supplier_id = supplier_service.create(conn, json_body(), g.user)
    except ValueError as exc:
        return fail(str(exc), 400)
    return ok({"id": supplier_id}, 201)


@bp.patch("/<int:supplier_id>")
@require("part.write")
def update_supplier(supplier_id: int):
    conn = get_db()
    try:
        with tx(conn):
            supplier_service.update(conn, supplier_id, json_body(), g.user)
    except ValueError as exc:
        return fail(str(exc), 400)
    return ok({"id": supplier_id})


@bp.delete("/<int:supplier_id>")
@require("part.write")
def delete_supplier(supplier_id: int):
    conn = get_db()
    try:
        with tx(conn):
            supplier_service.delete(conn, supplier_id, g.user)
    except ValueError as exc:
        return fail(str(exc), 409, "conflict")
    return ok({"id": supplier_id})
