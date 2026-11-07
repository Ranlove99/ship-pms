"""证书与检验 API。"""
from flask import Blueprint, g

from db.connection import get_db, tx
from middleware.auth import require
from routes._helpers import as_int, fail, json_body, ok
from services import audit, cert_service

bp = Blueprint("certificates_api", __name__, url_prefix="/api/v1/certificates")


@bp.get("")
def list_certs():
    conn = get_db()
    items = cert_service.list_certs(conn)
    return ok({"items": items, "total": len(items)})


@bp.post("")
@require("cert.write")
def create_cert():
    data = json_body()
    if not (data.get("name") or "").strip():
        return fail("请填写证书名称")
    conn = get_db()
    with tx(conn):
        cert_id = cert_service.create(conn, data, g.user)
    return ok({"id": cert_id}, 201)


@bp.patch("/<int:cert_id>")
@require("cert.write")
def update_cert(cert_id: int):
    data = json_body()
    conn = get_db()
    with tx(conn):
        cert_service.update(conn, cert_id, data, g.user)
    return ok({"id": cert_id})


@bp.get("/due")
def due_certs():
    conn = get_db()
    items = cert_service.due_certs(conn)
    return ok({"items": items, "total": len(items), "days": as_int(60)})
