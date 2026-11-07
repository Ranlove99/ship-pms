"""路由公共工具。"""
import sqlite3

from flask import g, jsonify, request

from db.connection import get_db


def json_body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def ok(payload=None, status: int = 200):
    body = {"ok": True}
    if payload is not None:
        body.update(payload if isinstance(payload, dict) else {"data": payload})
    return jsonify(body), status


def fail(message: str, status: int = 400, code: str = "bad_request"):
    return jsonify({"ok": False, "code": code, "message": message}), status


def as_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def bool_arg(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def tz_name(conn: sqlite3.Connection | None = None) -> str:
    if hasattr(g, "tz_name"):
        return g.tz_name
    conn = conn or get_db()
    row = conn.execute("SELECT timezone FROM vessel WHERE id = 1").fetchone()
    g.tz_name = (row["timezone"] if row else None) or "Asia/Shanghai"
    return g.tz_name


def client_ip() -> str:
    return (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
