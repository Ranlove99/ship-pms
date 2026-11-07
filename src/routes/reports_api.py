"""报表导出 API（CSV，带 BOM，Excel 直接打开）。"""
from flask import Blueprint, request

from db.connection import get_db
from middleware.auth import require
from routes._helpers import as_int
from services import export_service

bp = Blueprint("reports_api", __name__, url_prefix="/api/v1/reports")


def _days(default: int = 90) -> int:
    value = as_int(request.args.get("days"), default)
    return value if value and value > 0 else default


@bp.get("/overdue.csv")
@require("report.view")
def overdue_csv():
    rows = export_service.overdue_rows(get_db())
    headers = [
        ("asset_code", "设备编码"), ("asset_name", "设备名称"), ("title", "计划"),
        ("next_due_at", "下次到期"), ("days_left", "剩余天数"),
        ("next_due_hours", "到期小时"), ("hours_left", "剩余小时"),
        ("state", "状态"), ("regulation", "依据"),
    ]
    return export_service.csv_response(rows, headers, "overdue.csv")


@bp.get("/defects.csv")
@require("report.view")
def defects_csv():
    rows = export_service.defect_rows(get_db())
    headers = [
        ("no", "编号"), ("asset", "设备"), ("severity", "严重度"), ("status", "状态"),
        ("found_at", "发现日期"), ("description", "描述"), ("corrective", "纠正措施"),
    ]
    return export_service.csv_response(rows, headers, "defects.csv")


@bp.get("/certs.csv")
@require("report.view")
def certs_csv():
    rows = export_service.cert_rows(get_db())
    headers = [
        ("name", "证书"), ("category", "类别"), ("cert_no", "证书号"), ("issuer", "签发机构"),
        ("issued_at", "签发日"), ("expires_at", "到期日"), ("state", "状态"), ("days_left", "剩余天数"),
    ]
    return export_service.csv_response(rows, headers, "certificates.csv")


@bp.get("/workorders.csv")
@require("report.view")
def workorders_csv():
    rows = export_service.wo_rows(get_db())
    headers = [
        ("no", "工单号"), ("asset", "设备"), ("title", "内容"), ("type", "类型"),
        ("priority", "优先级"), ("status", "状态"), ("due_at", "到期"),
        ("completed_at", "完成日"), ("hours", "完成时运行小时"),
    ]
    return export_service.csv_response(rows, headers, "workorders.csv")


@bp.get("/reorder.csv")
@require("report.view")
def reorder_csv():
    rows = export_service.reorder_rows(get_db(), _days())
    headers = [
        ("code", "备件编码"), ("name", "名称"), ("spec", "规格"), ("unit", "单位"),
        ("location", "位置"), ("critical", "关键备件"), ("on_hand", "在库"),
        ("reserved", "预留"), ("available", "可用"), ("min_qty", "最低库存"),
        ("used_days", f"近{_days()}天出库"), ("suggested", "建议采购量"),
    ]
    return export_service.csv_response(rows, headers, "reorder.csv")


@bp.get("/moves.csv")
@require("report.view")
def moves_csv():
    days = _days()
    move_type = (request.args.get("type") or "").strip()
    rows = export_service.moves_rows(get_db(), days, move_type)
    headers = [
        ("at", "时间"), ("part_code", "备件编码"), ("part_name", "备件名称"),
        ("type", "动作"), ("qty", "数量"), ("unit", "单位"), ("ref_no", "单据号"),
        ("operator", "操作人"), ("note", "备注"),
    ]
    return export_service.csv_response(rows, headers, f"moves-{days}d.csv")


@bp.get("/consumption.csv")
@require("report.view")
def consumption_csv():
    rows = export_service.consumption_rows(get_db(), _days())
    headers = [
        ("code", "备件编码"), ("name", "备件名称"), ("unit", "单位"),
        ("qty", f"近{_days()}天出库"), ("times", "领用次数"),
    ]
    return export_service.csv_response(rows, headers, "consumption.csv")
