"""登录会话与当前用户。fnOS 网关下无需登录，本地直连时走本地账号。"""
from flask import Blueprint, g, session

from db.connection import get_db
from routes._helpers import client_ip, fail, json_body, ok
from services import audit
from services.passwords import hash_password, verify_password
from services.timeutil import now_iso

bp = Blueprint("auth_api", __name__, url_prefix="/api/v1/auth")


@bp.post("/login")
def login():
    data = json_body()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return fail("请输入账号与密码")

    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        audit.write(conn, "auth.login.fail", None, "users", username, after={"ip": client_ip()})
        return fail("账号或密码不正确", 401, "unauthorized")
    if not row["active"]:
        return fail("账号已停用", 403, "forbidden")

    session.clear()
    session["uid"] = row["id"]
    conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso(), row["id"]))
    audit.write(conn, "auth.login", {"id": row["id"], "username": row["username"]},
                "users", str(row["id"]), after={"ip": client_ip()})
    return ok({"user": {"id": row["id"], "username": row["username"],
                        "display_name": row["display_name"], "role": row["role"]}})


@bp.post("/logout")
def logout():
    user = g.get("user")
    if user:
        audit.write(get_db(), "auth.logout", user, "users", str(user["id"]))
    session.clear()
    return ok()


@bp.get("/me")
def me():
    user = g.get("user")
    if not user:
        return fail("未登录", 401, "unauthorized")
    return ok({"user": user})


@bp.post("/password")
def change_password():
    user = g.get("user")
    if not user:
        return fail("未登录", 401, "unauthorized")
    data = json_body()
    old = data.get("old_password") or ""
    new = data.get("new_password") or ""
    if len(new) < 8:
        return fail("新密码至少 8 位")
    conn = get_db()
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    if row and row["password_hash"] and not verify_password(old, row["password_hash"]):
        return fail("原密码不正确", 403, "forbidden")
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new), user["id"]))
    audit.write(conn, "auth.password", user, "users", str(user["id"]))
    return ok()
