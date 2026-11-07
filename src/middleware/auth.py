"""认证与鉴权：优先信任 fnOS 网关注入的用户头，回退本地会话。"""
from urllib.parse import unquote

from flask import g, jsonify, redirect, request, session, url_for

from db.connection import get_db
from services.timeutil import now_iso

PUBLIC_PATHS = {"/login", "/api/v1/health", "/favicon.ico"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _row_to_user(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "active": row["active"],
    }


def _provision_from_gateway(conn, uid: str, username: str, is_admin: bool) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE fnos_uid = ?", (uid,)).fetchone()
    if row is None and username:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is not None:
            conn.execute("UPDATE users SET fnos_uid = ? WHERE id = ?", (uid, row["id"]))
    if row is not None:
        return _row_to_user(row)

    total = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    role = "admin" if (total == 0 or is_admin) else "crew"
    display = username or f"用户{uid}"
    conn.execute(
        "INSERT INTO users (username, display_name, role, password_hash, fnos_uid, active, created_at)"
        " VALUES (?,?,?,NULL,?,1,?)",
        (username or f"fnos_{uid}", display, role, uid, now_iso()),
    )
    row = conn.execute("SELECT * FROM users WHERE fnos_uid = ?", (uid,)).fetchone()
    return _row_to_user(row) if row else None


def load_user() -> None:
    path = request.path or "/"
    if path.startswith("/static/") or path in PUBLIC_PATHS:
        g.user = None
        return

    conn = get_db()
    user = None
    uid = (request.headers.get("X-Trim-Userid") or "").strip()
    if uid:
        username = unquote(request.headers.get("X-Trim-Username") or "").strip()
        user = _provision_from_gateway(conn, uid, username, _truthy(request.headers.get("X-Trim-Isadmin")))
    elif session.get("uid"):
        row = conn.execute("SELECT * FROM users WHERE id = ? AND active = 1", (session["uid"],)).fetchone()
        user = _row_to_user(row) if row else None

    if user and not user["active"]:
        user = None
    g.user = user


def check_same_origin() -> None:
    """写操作的同源校验，配合 SameSite=Lax 会话，挡住跨站提交。"""
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    host = request.host
    source = origin or referer
    if not source:
        return
    if host and host not in source:
        from flask import abort

        abort(403, description="跨站请求被拒绝")


def require_login():
    """返回 None 表示已放行，否则返回响应。"""
    if g.get("user"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"code": "unauthorized", "message": "请先登录"}), 401
    return redirect(url_for("pages.login", next=request.full_path))


def require(action: str):
    from functools import wraps

    from services.passwords import allowed

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            guard = require_login()
            if guard is not None:
                return guard
            if not allowed(g.user, action):
                if request.path.startswith("/api/"):
                    return jsonify({"code": "forbidden", "message": "当前角色无权执行该操作"}), 403
                from flask import abort

                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
