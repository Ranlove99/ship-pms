"""库存单据 API：入库 / 出库 / 盘库。"""
from flask import Blueprint, g, request

from db.connection import get_db, tx
from middleware.auth import require
from routes._helpers import as_int, fail, json_body, ok, tz_name
from services import stock_doc_service

bp = Blueprint("stock_docs_api", __name__, url_prefix="/api/v1/stock-docs")


@bp.get("")
def list_docs():
    conn = get_db()
    items = stock_doc_service.list_docs(
        conn,
        doc_type=(request.args.get("type") or "").strip(),
        status=(request.args.get("status") or "").strip(),
        q=(request.args.get("q") or "").strip(),
        limit=as_int(request.args.get("limit"), 100) or 100,
    )
    return ok({"items": items, "total": len(items)})


@bp.post("")
@require("part.write")
def create_doc():
    data = json_body()
    conn = get_db()
    try:
        with tx(conn):
            doc_id = stock_doc_service.create_doc(
                conn, (data.get("type") or "").strip(), data, g.user, tz_name(conn))
    except ValueError as exc:
        return fail(str(exc), 400)
    return ok({"id": doc_id}, 201)


@bp.get("/<int:doc_id>")
def get_doc(doc_id: int):
    doc = stock_doc_service.get_doc(get_db(), doc_id)
    if doc is None:
        return fail("单据不存在", 404, "not_found")
    return ok({"item": doc})


@bp.patch("/<int:doc_id>")
@require("part.write")
def update_doc(doc_id: int):
    conn = get_db()
    try:
        with tx(conn):
            stock_doc_service.update_doc(conn, doc_id, json_body(), g.user)
    except ValueError as exc:
        return fail(str(exc), 400)
    return ok({"id": doc_id})


@bp.post("/<int:doc_id>/post")
@require("part.move")
def post_doc(doc_id: int):
    conn = get_db()
    try:
        with tx(conn):
            stock_doc_service.post_doc(conn, doc_id, g.user)
    except ValueError as exc:
        return fail(str(exc), 400)
    return ok({"id": doc_id})


@bp.post("/<int:doc_id>/cancel")
@require("part.move")
def cancel_doc(doc_id: int):
    conn = get_db()
    try:
        with tx(conn):
            stock_doc_service.cancel_doc(conn, doc_id, g.user)
    except ValueError as exc:
        return fail(str(exc), 400)
    return ok({"id": doc_id})


@bp.post("/stocktake-draft")
@require("part.write")
def stocktake_draft():
    data = json_body()
    raw_ids = data.get("part_ids") or []
    part_ids: list[int] = []
    for value in raw_ids:
        try:
            part_ids.append(int(value))
        except (TypeError, ValueError):
            return fail("备件选择不合法", 400)
    conn = get_db()
    try:
        with tx(conn):
            doc_id = stock_doc_service.stocktake_draft(
                conn, part_ids or None, (data.get("location") or "").strip(),
                g.user, tz_name(conn))
    except ValueError as exc:
        return fail(str(exc), 400)
    return ok({"id": doc_id}, 201)
