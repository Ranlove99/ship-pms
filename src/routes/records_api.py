"""电子记录簿 API：追加、提交、核签、更正、导出。"""
from flask import Blueprint, g, request

from db.connection import get_db, tx
from middleware.auth import require
from routes._helpers import fail, json_body, ok, tz_name
from services import record_service
from services.timeutil import to_utc_input

bp = Blueprint("records_api", __name__, url_prefix="/api/v1/recordbooks")


@bp.get("")
def list_books():
    return ok({"items": record_service.books(get_db())})


@bp.get("/<code>/entries")
def list_entries(code: str):
    conn = get_db()
    book = record_service.book_by_code(conn, code)
    if book is None:
        return fail("记录簿不存在", 404, "not_found")
    return ok({"book": book, "items": record_service.entries(conn, book["id"])})


@bp.post("/<code>/entries")
@require("record.write")
def add_entry(code: str):
    data = json_body()
    conn = get_db()
    book = record_service.book_by_code(conn, code)
    if book is None:
        return fail("记录簿不存在", 404, "not_found")
    entry_type = (data.get("entry_type") or "").strip()
    if not entry_type:
        return fail("请选择记录类型")
    particulars = data.get("particulars") or {}
    if not isinstance(particulars, dict) or not particulars:
        return fail("请填写记录内容")
    occurred = to_utc_input(data.get("occurred_local") or "", tz_name(conn))
    with tx(conn):
        result = record_service.add_entry(conn, book["id"], entry_type, occurred, particulars, g.user)
    return ok(result, 201)


@bp.post("/entries/<int:entry_id>/submit")
@require("record.write")
def submit_entry(entry_id: int):
    conn = get_db()
    with tx(conn):
        try:
            result = record_service.submit(conn, entry_id, g.user)
        except ValueError as exc:
            return fail(str(exc), 400)
    return ok(result)


@bp.post("/entries/<int:entry_id>/verify")
@require("record.verify")
def verify_entry(entry_id: int):
    conn = get_db()
    with tx(conn):
        try:
            result = record_service.verify(conn, entry_id, g.user)
        except ValueError as exc:
            return fail(str(exc), 400)
    return ok(result)


@bp.post("/entries/<int:entry_id>/amend")
@require("record.verify")
def amend_entry(entry_id: int):
    data = json_body()
    reason = (data.get("reason") or "").strip()
    if not reason:
        return fail("更正必须填写原因")
    conn = get_db()
    with tx(conn):
        try:
            result = record_service.amend(conn, entry_id, data.get("particulars") or {}, reason, g.user)
        except ValueError as exc:
            return fail(str(exc), 400)
    return ok(result, 201)


@bp.get("/<code>/integrity")
def book_integrity(code: str):
    from services import record_chain

    conn = get_db()
    book = record_service.book_by_code(conn, code)
    if book is None:
        return fail("记录簿不存在", 404, "not_found")
    return ok(record_chain.verify_book(conn, book["id"]))


@bp.get("/<code>/export")
def export_csv(code: str):
    from services.export_service import csv_response

    conn = get_db()
    book = record_service.book_by_code(conn, code)
    if book is None:
        return fail("记录簿不存在", 404, "not_found")
    rows = record_service.export_rows(conn, book["id"])
    flat = []
    for row in rows:
        item = dict(row)
        particulars = item.pop("particulars") or {}
        item["detail"] = "；".join(f"{k}: {v}" for k, v in particulars.items() if v not in (None, ""))
        flat.append(item)
    headers = [
        ("seq", "序号"), ("occurred_at_utc", "时间(UTC)"), ("entry_type", "记录类型"),
        ("detail", "内容"), ("status", "状态"), ("officer", "记录人"),
        ("master", "核签人"), ("verified_at", "核签时间"), ("hash", "哈希"),
        ("amends_seq", "更正原序号"),
    ]
    return csv_response(flat, headers, f"{code}-{request.args.get('date') or ''}.csv".replace("-.csv", ".csv"))
