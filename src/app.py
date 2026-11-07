"""应用装配：只做注册与全局钩子，不含业务逻辑。"""
import os

from flask import Flask, g, jsonify, render_template, request

from config import Config
from db.connection import close_db, get_db, get_int_setting, migrate
from middleware.auth import check_same_origin, load_user
from middleware.prefix import PrefixMiddleware
from services import audit
from services.passwords import ROLE_LABEL
from services.timeutil import fmt_utc_for_display

GATEWAY_PREFIX = "/app/ship-pms"


def create_app() -> Flask:
    Config.ensure_dirs()
    migrate()

    app = Flask(
        __name__,
        static_folder=os.path.join(Config.BASE_DIR, "static"),
        template_folder=os.path.join(Config.BASE_DIR, "templates"),
    )
    app.secret_key = Config.secret_key()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_NAME="ship_pms",
        MAX_CONTENT_LENGTH=Config.MAX_UPLOAD_MB * 1024 * 1024,
        TEMPLATES_AUTO_RELOAD=False,
    )
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    app.wsgi_app = PrefixMiddleware(app.wsgi_app, GATEWAY_PREFIX)

    app.before_request(load_user)
    app.before_request(check_same_origin)
    app.teardown_appcontext(close_db)

    from routes import register_blueprints

    register_blueprints(app)

    _register_filters(app)
    _register_error_handlers(app)
    _register_context(app)
    return app


def _register_filters(app: Flask) -> None:
    @app.template_filter("dt")
    def _dt(value):
        return fmt_utc_for_display(value, _tz_name())

    @app.template_filter("d")
    def _d(value):
        return (value or "")[:10]

    @app.template_filter("num")
    def _num(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return value if value not in (None, "") else "—"
        return f"{number:,.0f}" if abs(number) >= 1000 else f"{number:g}"

    @app.template_filter("money")
    def _money(value):
        try:
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return "0.00"

    @app.template_global("role_label")
    def _role_label(role):
        return ROLE_LABEL.get(role, role)


def _register_context(app: Flask) -> None:
    @app.context_processor
    def _inject():
        user = g.get("user")
        ctx = {
            "current_user": user,
            "gateway_prefix": GATEWAY_PREFIX,
            "app_version": Config.VERSION,
            "vessel": None,
            "counts": {"due": 0, "defects": 0, "records": 0, "certs": 0, "docs_draft": 0},
        }
        if user:
            conn = get_db()
            ctx["vessel"] = conn.execute("SELECT * FROM vessel WHERE id = 1").fetchone()
            ctx["counts"] = _nav_counts(conn)
        return ctx


def _nav_counts(conn) -> dict:
    warn = get_int_setting(conn, "due_warn_days", 30)
    due = conn.execute(
        "SELECT COUNT(*) AS n FROM maintenance_plans WHERE active = 1"
        " AND next_due_at IS NOT NULL AND date(next_due_at) <= date('now', ?)",
        (f"+{warn} days",),
    ).fetchone()["n"]
    defects = conn.execute("SELECT COUNT(*) AS n FROM defects WHERE status != 'closed'").fetchone()["n"]
    records = conn.execute("SELECT COUNT(*) AS n FROM record_entries WHERE status = 'submitted'").fetchone()["n"]
    certs = conn.execute(
        "SELECT COUNT(*) AS n FROM certificates WHERE status != 'superseded'"
        " AND expires_at IS NOT NULL AND date(expires_at) <= date('now', '+60 days')"
    ).fetchone()["n"]
    docs = conn.execute(
        "SELECT COUNT(*) AS n FROM stock_docs WHERE status = 'draft'"
    ).fetchone()["n"]
    return {"due": due, "defects": defects, "records": records, "certs": certs, "docs_draft": docs}


def _tz_name() -> str:
    if hasattr(g, "tz_name"):
        return g.tz_name
    try:
        row = get_db().execute("SELECT timezone FROM vessel WHERE id = 1").fetchone()
        g.tz_name = (row["timezone"] if row else None) or "Asia/Shanghai"
    except Exception:
        g.tz_name = "Asia/Shanghai"
    return g.tz_name


def _register_error_handlers(app: Flask) -> None:
    def _wants_json() -> bool:
        return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"

    @app.errorhandler(400)
    def _400(err):
        if _wants_json():
            return jsonify({"code": "bad_request", "message": getattr(err, "description", "请求参数有误")}), 400
        return render_template("error.html", code=400, message=getattr(err, "description", "请求参数有误")), 400

    @app.errorhandler(403)
    def _403(err):
        if _wants_json():
            return jsonify({"code": "forbidden", "message": getattr(err, "description", "没有权限")}), 403
        return render_template("error.html", code=403, message=getattr(err, "description", "没有权限")), 403

    @app.errorhandler(404)
    def _404(err):
        if _wants_json():
            return jsonify({"code": "not_found", "message": "记录不存在"}), 404
        return render_template("error.html", code=404, message="页面或记录不存在"), 404

    @app.errorhandler(409)
    def _409(err):
        return jsonify({"code": "conflict", "message": getattr(err, "description", "操作冲突")}), 409

    @app.errorhandler(413)
    def _413(_err):
        return jsonify({"code": "too_large", "message": f"文件超过 {Config.MAX_UPLOAD_MB} MB"}), 413

    @app.errorhandler(500)
    def _500(err):
        try:
            conn = get_db()
            audit.write(conn, "error.500", g.get("user"), entity="app",
                        entity_id=request.path, after={"error": str(err)})
        except Exception:
            pass
        if _wants_json():
            return jsonify({"code": "server_error", "message": "服务内部错误，详见应用日志"}), 500
        return render_template("error.html", code=500, message="服务内部错误"), 500
