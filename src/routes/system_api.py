"""系统管理：用户、设置、备份、完整性、审计、健康检查。"""
from flask import Blueprint, g, request

from config import Config
from db.connection import get_db, set_setting, tx
from middleware.auth import require
from routes._helpers import as_int, fail, json_body, ok
from services import audit, ops_service
from services.passwords import ROLE_LABEL, hash_password
from services.timeutil import now_iso

bp = Blueprint("system_api", __name__, url_prefix="/api/v1")


@bp.get("/health")
def health():
    try:
        conn = get_db()
        db_ok = conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        records = conn.execute("SELECT COUNT(*) AS n FROM record_entries").fetchone()["n"]
    except Exception:
        db_ok, records = False, 0
    return ok({
        "status": "ok" if db_ok else "degraded",
        "version": Config.VERSION,
        "db": db_ok,
        "records": records,
        "socket": Config.SOCKET_PATH,
    })


@bp.get("/users")
@require("system.manage")
def list_users():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, username, display_name, role, fnos_uid, active, created_at, last_login_at"
        " FROM users ORDER BY id"
    ).fetchall()
    items = [dict(r, role_label=ROLE_LABEL.get(r["role"], r["role"])) for r in rows]
    return ok({"items": items, "roles": ROLE_LABEL})


@bp.post("/users")
@require("user.manage")
def create_user():
    data = json_body()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or "crew").strip()
    if not username:
        return fail("请填写账号")
    if len(password) < 8:
        return fail("密码至少 8 位")
    if role not in ROLE_LABEL:
        return fail("角色不合法")
    conn = get_db()
    with tx(conn):
        if conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
            return fail("账号已存在", 409, "conflict")
        cur = conn.execute(
            "INSERT INTO users (username, display_name, role, password_hash, active, created_at)"
            " VALUES (?,?,?,?,1,?)",
            (username, (data.get("display_name") or username).strip(), role,
             hash_password(password), now_iso()),
        )
        audit.write(conn, "user.create", g.user, "users", str(cur.lastrowid),
                    after={"username": username, "role": role})
    return ok({"id": cur.lastrowid}, 201)


@bp.patch("/users/<int:user_id>")
@require("user.manage")
def update_user(user_id: int):
    data = json_body()
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return fail("用户不存在", 404, "not_found")
    with tx(conn):
        if data.get("role") and data["role"] in ROLE_LABEL:
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (data["role"], user_id))
        if "active" in data:
            conn.execute("UPDATE users SET active = ? WHERE id = ?", (1 if data["active"] else 0, user_id))
        if data.get("display_name"):
            conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (data["display_name"], user_id))
        if data.get("password"):
            if len(data["password"]) < 8:
                return fail("密码至少 8 位")
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                         (hash_password(data["password"]), user_id))
        audit.write(conn, "user.update", g.user, "users", str(user_id), after={
            k: v for k, v in data.items() if k != "password"})
    return ok({"id": user_id})


@bp.get("/settings")
@require("system.manage")
def get_settings():
    conn = get_db()
    vessel = conn.execute("SELECT * FROM vessel WHERE id = 1").fetchone()
    rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    return ok({"vessel": dict(vessel) if vessel else {}, "settings": {r["key"]: r["value"] for r in rows}})


@bp.put("/settings")
@require("system.manage")
def put_settings():
    data = json_body()
    conn = get_db()
    with tx(conn):
        vessel = data.get("vessel") or {}
        if vessel:
            conn.execute(
                "UPDATE vessel SET name = ?, imo = ?, call_sign = ?, flag = ?, port_of_registry = ?,"
                " gt = ?, ship_type = ?, class_society = ?, owner = ?, manager = ?, timezone = ?,"
                " updated_at = ? WHERE id = 1",
                (vessel.get("name") or "", vessel.get("imo") or "", vessel.get("call_sign") or "",
                 vessel.get("flag") or "", vessel.get("port_of_registry") or "",
                 float(vessel.get("gt") or 0), vessel.get("ship_type") or "散货船",
                 vessel.get("class_society") or "", vessel.get("owner") or "",
                 vessel.get("manager") or "", vessel.get("timezone") or "Asia/Shanghai", now_iso()),
            )
        for key, value in (data.get("settings") or {}).items():
            set_setting(conn, key, str(value))
        audit.write(conn, "settings.update", g.user, "settings", "1",
                    after={"vessel": vessel.get("name"), "keys": list((data.get("settings") or {}).keys())})
    return ok()


@bp.post("/backup/run")
@require("system.manage")
def run_backup():
    conn = get_db()
    from db.connection import get_int_setting

    keep = get_int_setting(conn, "backup_keep", 30)
    try:
        result = ops_service.run_backup(conn, keep, g.user)
    except Exception as exc:
        return fail(f"备份失败：{exc}", 500, "backup_failed")
    return ok(result)


@bp.get("/backup/list")
@require("system.manage")
def list_backups():
    return ok({"items": ops_service.list_backups()})


@bp.post("/integrity/verify")
def verify_integrity():
    conn = get_db()
    report = ops_service.integrity_report(conn)
    audit.write(conn, "integrity.verify", g.get("user"), "system", "all",
                after={"ok": report["ok"]})
    return ok(report)


@bp.get("/audit")
@require("report.view")
def list_audit():
    conn = get_db()
    limit = as_int(request.args.get("limit"), 100) or 100
    action = (request.args.get("action") or "").strip()
    sql = ("SELECT id, at_utc, username, action, entity, entity_id, before_json, after_json, ip"
           " FROM audit_log WHERE 1=1")
    params: list = []
    if action:
        sql += " AND action LIKE ?"
        params.append(f"{action}%")
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    items = [dict(r) for r in conn.execute(sql, params).fetchall()]
    return ok({"items": items, "total": len(items)})
