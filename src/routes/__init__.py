"""蓝图注册。"""

BLUEPRINT_MODULES = [
    "auth_api",
    "assets_api",
    "plans_api",
    "workorders_api",
    "defects_api",
    "parts_api",
    "stock_docs_api",
    "suppliers_api",
    "certificates_api",
    "records_api",
    "reports_api",
    "io_api",
    "system_api",
    "pages",
]


def register_blueprints(app) -> None:
    from importlib import import_module

    for name in BLUEPRINT_MODULES:
        module = import_module(f"routes.{name}")
        app.register_blueprint(module.bp)
