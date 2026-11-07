"""设备台账 API。"""
from flask import Blueprint, g, request

from db.connection import get_db, tx
from middleware.auth import require
from routes._helpers import as_float, as_int, bool_arg, fail, json_body, ok
from services import asset_service, audit

bp = Blueprint("assets_api", __name__, url_prefix="/api/v1/assets")


@bp.get("")
def list_assets():
    conn = get_db()
    if bool_arg(request.args.get("tree")):
        return ok({"items": asset_service.tree(conn)})
    items = asset_service.list_all(
        conn,
        query=(request.args.get("q") or "").strip(),
        category=(request.args.get("category") or "").strip(),
    )
    return ok({"items": items, "total": len(items)})


@bp.get("/<int:asset_id>")
def get_asset(asset_id: int):
    conn = get_db()
    item = asset_service.get(conn, asset_id)
    if item is None:
        return fail("设备不存在", 404, "not_found")
    item["history"] = asset_service.history(conn, asset_id, 30)
    return ok({"item": item})


@bp.post("")
@require("asset.write")
def create_asset():
    data = json_body()
    if not (data.get("code") or "").strip() or not (data.get("name") or "").strip():
        return fail("设备编码与名称必填")
    conn = get_db()
    with tx(conn):
        exists = conn.execute("SELECT id FROM assets WHERE code = ?", (data["code"].strip(),)).fetchone()
        if exists:
            return fail("设备编码已存在", 409, "conflict")
        asset_id = asset_service.create(conn, data)
        audit.write(conn, "asset.create", g.user, "assets", str(asset_id),
                    after={"code": data.get("code"), "name": data.get("name")})
    return ok({"id": asset_id}, 201)


@bp.patch("/<int:asset_id>")
@require("asset.write")
def update_asset(asset_id: int):
    data = json_body()
    conn = get_db()
    before = asset_service.get(conn, asset_id)
    if before is None:
        return fail("设备不存在", 404, "not_found")
    with tx(conn):
        asset_service.update(conn, asset_id, data)
        audit.write(conn, "asset.update", g.user, "assets", str(asset_id),
                    before={"name": before["name"], "criticality": before["criticality"]}, after=data)
    return ok({"id": asset_id})


@bp.post("/<int:asset_id>/hours")
@require("wo.write")
def update_hours(asset_id: int):
    data = json_body()
    hours = as_float(data.get("running_hours"))
    if hours is None or hours < 0:
        return fail("请填写有效的运行小时")
    conn = get_db()
    before = asset_service.get(conn, asset_id)
    if before is None:
        return fail("设备不存在", 404, "not_found")
    with tx(conn):
        asset_service.update_hours(conn, asset_id, hours)
        audit.write(conn, "asset.hours", g.user, "assets", str(asset_id),
                    before={"running_hours": before["running_hours"]}, after={"running_hours": hours})
    return ok({"running_hours": hours})


@bp.delete("/<int:asset_id>")
@require("asset.write")
def delete_asset(asset_id: int):
    conn = get_db()
    item = asset_service.get(conn, asset_id)
    if item is None:
        return fail("设备不存在", 404, "not_found")
    if asset_service.child_count(conn, asset_id) > 0:
        return fail("该设备下仍有子设备，不能删除", 409, "conflict")
    used = conn.execute("SELECT COUNT(*) AS n FROM work_orders WHERE asset_id = ?", (asset_id,)).fetchone()["n"]
    if used:
        return fail("该设备已有工单记录，只能停用不能删除", 409, "conflict")
    with tx(conn):
        conn.execute("DELETE FROM maintenance_plans WHERE asset_id = ?", (asset_id,))
        conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
        audit.write(conn, "asset.delete", g.user, "assets", str(asset_id), before={"code": item["code"]})
    return ok()
