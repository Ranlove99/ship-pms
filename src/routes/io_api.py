"""批量导入导出 API（仅管理员可写）。"""
from flask import Blueprint, Response, g, request

from db.connection import get_db, tx
from middleware.auth import require
from routes._helpers import bool_arg, fail, ok
from services import io_service

bp = Blueprint("io_api", __name__, url_prefix="/api/v1/io")


def _csv_response(text: str, filename: str) -> Response:
    resp = Response(text, mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@bp.get("/export/<kind>.csv")
@require("report.view")
def export_csv(kind: str):
    if io_service.schema(kind) is None:
        return fail("未知的数据类型", 404, "not_found")
    rows, cols = io_service.export_rows(get_db(), kind)
    return _csv_response(io_service.to_csv(rows, cols), f"{kind}-{_stamp()}.csv")


@bp.get("/template/<kind>.csv")
@require("report.view")
def template_csv(kind: str):
    if io_service.schema(kind) is None:
        return fail("未知的数据类型", 404, "not_found")
    return _csv_response(io_service.template_csv(kind), f"{kind}-template.csv")


@bp.post("/import/<kind>")
@require("system.manage")
def import_csv(kind: str):
    spec = io_service.schema(kind)
    if spec is None:
        return fail("未知的数据类型", 404, "not_found")

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return fail("请选择 CSV 文件")
    raw = upload.read()
    if not raw:
        return fail("文件为空")

    rows, error = io_service.parse_csv(raw)
    if error:
        return fail(error)

    dry_run = bool_arg(request.args.get("dry_run"))
    create_missing = bool_arg(request.args.get("create_missing"))
    conn = get_db()

    if dry_run:
        return ok(io_service.preview(conn, kind, rows, create_missing))

    with tx(conn):
        result = io_service.apply_import(conn, kind, rows, create_missing, g.user)
    return ok(result)


def _stamp() -> str:
    from services.timeutil import local_now

    return local_now("Asia/Shanghai").strftime("%Y%m%d")
