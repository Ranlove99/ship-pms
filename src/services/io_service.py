"""CSV 批量导入导出：设备、维护计划、备件、证书。

导入策略：
- 以 code / name 作为匹配键，命中则更新，未命中可选择新增
- 只更新 CSV 中出现的列，未出现的列保持原值
- 计划导入不自动重算到期日，除非显式给出 next_due_at
- 全程可 dry-run，先给变更预览再落库
"""
import csv
import io
import sqlite3

from services import audit
from services.timeutil import now_iso, today_str

MAX_ROWS = 2000

# 类型 → (表, 匹配键, 字段定义[(列名, 中文表头, 类型)])
SCHEMAS: dict[str, dict] = {
    "assets": {
        "table": "assets",
        "key": "code",
        "label": "设备台账",
        "fields": [
            ("code", "设备编码", "str"),
            ("name", "设备名称", "str"),
            ("parent_code", "上级编码", "str"),
            ("category", "类别", "str"),
            ("criticality", "关键度", "str"),
            ("maker", "厂家", "str"),
            ("model", "型号", "str"),
            ("serial_no", "序列号", "str"),
            ("location", "位置", "str"),
            ("running_hours", "运行小时", "float"),
            ("status", "状态", "str"),
            ("notes", "备注", "str"),
        ],
        "required": {"code", "name"},
        "enums": {
            "category": {"hull", "machinery", "deck", "electrical", "safety", "navigation", "cargo", "other"},
            "criticality": {"A", "B", "C"},
            "status": {"in_service", "standby", "out_of_service", "disposed"},
        },
    },
    "plans": {
        "table": "maintenance_plans",
        "key": "code",
        "label": "维护计划",
        "fields": [
            ("code", "计划编码", "str"),
            ("asset_code", "设备编码", "str"),
            ("title", "计划名称", "str"),
            ("interval_days", "日历间隔(天)", "int"),
            ("interval_hours", "小时间隔(h)", "float"),
            ("est_hours", "预计工时", "float"),
            ("responsible_role", "责任角色", "str"),
            ("regulation_ref", "法规依据", "str"),
            ("checklist", "检查项", "list"),
            ("next_due_at", "下次到期", "date"),
            ("active", "启用", "bool"),
        ],
        "required": {"code", "title"},
        "enums": {
            "responsible_role": {"officer", "chief", "master", "crew", "admin"},
        },
    },
    "parts": {
        "table": "parts",
        "key": "code",
        "label": "备件台账",
        "fields": [
            ("code", "备件编码", "str"),
            ("name", "名称", "str"),
            ("spec", "规格", "str"),
            ("unit", "单位", "str"),
            ("maker_part_no", "厂家件号", "str"),
            ("location", "存放位置", "str"),
            ("min_qty", "最低库存", "float"),
            ("on_hand", "在库数量", "float"),
            ("unit_price", "单价", "float"),
            ("currency", "币种", "str"),
            ("critical", "关键备件", "bool"),
            ("remarks", "备注", "str"),
        ],
        "required": {"code", "name"},
        "enums": {},
    },
    "certificates": {
        "table": "certificates",
        "key": "name",
        "label": "证书台账",
        "fields": [
            ("name", "证书名称", "str"),
            ("cert_no", "证书号", "str"),
            ("category", "类别", "str"),
            ("issuer", "签发机构", "str"),
            ("issued_at", "签发日期", "date"),
            ("expires_at", "到期日期", "date"),
            ("reminder_days", "提前提醒(天)", "int"),
            ("remarks", "备注", "str"),
        ],
        "required": {"name"},
        "enums": {"category": {"statutory", "class", "other"}},
    },
}

# 导出时额外带上的只读列（不参与导入）
EXTRA_EXPORT = {
    "assets": [("id", "ID")],
    "plans": [("id", "ID"), ("last_done_at", "上次完成"), ("last_done_hours", "上次完成小时")],
    "parts": [("id", "ID"), ("available", "可用")],
    "certificates": [("id", "ID")],
}


def schema(kind: str) -> dict | None:
    return SCHEMAS.get(kind)


def headers(kind: str) -> list[str]:
    return [label for _, label, _ in SCHEMAS[kind]["fields"]]


def export_rows(conn: sqlite3.Connection, kind: str) -> tuple[list[dict], list[str]]:
    spec = SCHEMAS[kind]
    table = spec["table"]
    rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()

    asset_code = {}
    if kind == "plans":
        asset_code = {r["id"]: r["code"] for r in conn.execute("SELECT id, code FROM assets").fetchall()}

    out = []
    for row in rows:
        item = dict(row)
        record = {}
        for col, label, ftype in spec["fields"]:
            if col == "asset_code":
                value = asset_code.get(item.get("asset_id"), "")
            elif col == "checklist":
                import json

                try:
                    value = "；".join(json.loads(item.get("checklist_json") or "[]"))
                except ValueError:
                    value = ""
            elif col == "active":
                value = "是" if item.get("active") else "否"
            elif col == "critical":
                value = "是" if item.get("critical") else "否"
            else:
                value = item.get(col, "")
            record[label] = "" if value is None else value
        for col, label in EXTRA_EXPORT.get(kind, []):
            record[label] = item.get(col, "")
        out.append(record)

    extra = [label for _, label in EXTRA_EXPORT.get(kind, [])]
    return out, headers(kind) + extra


def to_csv(rows: list[dict], cols: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return "\ufeff" + buffer.getvalue()


def _norm(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _same(old, new) -> bool:
    """跨类型比较：CSV 读回来全是字符串，不能直接用类型敏感的相等判断。"""
    if isinstance(new, bool):
        if isinstance(old, str):
            return (old.strip().lower() in {"1", "是", "true", "y", "yes"}) == new
        return bool(old) == new
    if isinstance(new, (int, float)) and isinstance(old, (int, float)):
        return abs(float(old) - float(new)) < 1e-9
    if isinstance(new, list):
        if isinstance(old, list):
            return old == new
        return False
    if old is None and new in ("", None):
        return True
    return str(old if old is not None else "") == str(new if new is not None else "")


def _cast(value: str, ftype: str):
    """返回 (value, error)。"""
    text = _norm(value)
    if text == "":
        return None, None
    if ftype == "str":
        return text, None
    if ftype == "int":
        try:
            return int(float(text)), None
        except ValueError:
            return None, f"不是整数：{text}"
    if ftype == "float":
        try:
            return round(float(text), 2), None
        except ValueError:
            return None, f"不是数字：{text}"
    if ftype == "bool":
        return text.lower() in {"1", "是", "true", "y", "yes", "启用"}, None
    if ftype == "date":
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            return text[:10], None
        return None, f"日期格式应为 YYYY-MM-DD：{text}"
    if ftype == "list":
        parts = [p.strip() for p in text.replace("；", ";").replace("\n", ";").split(";")]
        return [p for p in parts if p], None
    return text, None


def parse_csv(raw: bytes) -> tuple[list[dict], str | None]:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return [], "无法识别文件编码，请用 UTF-8 保存"

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], "文件为空或没有表头"
    rows = list(reader)
    if len(rows) > MAX_ROWS:
        return [], f"单次最多导入 {MAX_ROWS} 行，当前 {len(rows)} 行"
    return rows, None


def preview(conn: sqlite3.Connection, kind: str, rows: list[dict], create_missing: bool = False) -> dict:
    spec = SCHEMAS[kind]
    label_to_field = {label: col for col, label, _ in spec["fields"]}
    type_of = {col: ftype for col, _, ftype in spec["fields"]}
    key = spec["key"]

    # 现有记录索引
    existing = {}
    for row in conn.execute(f"SELECT * FROM {spec['table']}").fetchall():
        item = dict(row)
        existing[str(item.get(key) or "")] = item

    asset_by_code = {r["code"]: r["id"]
                     for r in conn.execute("SELECT id, code FROM assets").fetchall()}

    field_label = {col: label for col, label, _ in spec["fields"]}
    results = []
    counters = {"update": 0, "create": 0, "skip": 0, "error": 0}

    for index, raw in enumerate(rows, start=2):  # 第 1 行是表头
        errors: list[str] = []
        values: dict = {}

        for header, cell in raw.items():
            if header is None:
                continue
            col = label_to_field.get(_norm(header))
            if col is None:
                continue
            if col in ("parent_code",):
                continue
            casted, err = _cast(cell, type_of[col])
            if err:
                errors.append(f"{_norm(header)}：{err}")
                continue
            if casted is not None:
                values[col] = casted

        for required in spec["required"]:
            if required not in values or values.get(required) in ("", None):
                errors.append(f"{dict((c, l) for c, l, _ in spec['fields']).get(required, required)} 不能为空")

        for col, allowed in spec["enums"].items():
            if col in values and values[col] not in allowed:
                errors.append(f"{col} 取值不合法：{values[col]}（可选 {', '.join(sorted(allowed))}）")

        # 计划的设备编码需存在
        if kind == "plans":
            asset_code = _norm(raw.get("设备编码", ""))
            if asset_code:
                if asset_code not in asset_by_code:
                    errors.append(f"设备编码不存在：{asset_code}")
                else:
                    values["asset_id"] = asset_by_code[asset_code]
            values.pop("asset_code", None)

        if kind == "assets":
            parent_code = _norm(raw.get("上级编码", ""))
            if parent_code:
                if parent_code == values.get("code"):
                    errors.append("上级编码不能与自身相同")
                elif parent_code in asset_by_code:
                    values["parent_id"] = asset_by_code[parent_code]
                elif parent_code in {_norm(r.get("设备编码", "")) for r in rows}:
                    pass  # 同批次新建的父级，先不设父子关系，导入后再调整
                else:
                    errors.append(f"上级编码不存在：{parent_code}")

        match_value = str(values.get(key) or "")
        current = existing.get(match_value) if match_value else None

        if errors:
            counters["error"] += 1
            results.append({"line": index, "key": match_value or "—", "action": "error",
                            "changes": [], "errors": errors})
            continue

        if current is None:
            if create_missing:
                counters["create"] += 1
                results.append({"line": index, "key": match_value, "action": "create",
                                "changes": [[k, "", v] for k, v in values.items()], "errors": []})
            else:
                counters["skip"] += 1
                results.append({"line": index, "key": match_value, "action": "skip",
                                "changes": [], "errors": ["未找到匹配记录（勾选「新增未匹配项」可创建）"]})
            continue

        changes = []
        for col, new_value in values.items():
            old_value = current.get(col)
            if col == "checklist":
                import json

                try:
                    old_value = json.loads(current.get("checklist_json") or "[]")
                except ValueError:
                    old_value = []
            if _same(old_value, new_value):
                continue
            label = field_label.get(col, col)
            changes.append([label, old_value, new_value])

        if changes:
            counters["update"] += 1
            results.append({"line": index, "key": match_value, "action": "update",
                            "changes": changes, "errors": []})
        else:
            counters["skip"] += 1
            results.append({"line": index, "key": match_value, "action": "unchanged",
                            "changes": [], "errors": []})

    return {"rows": results, "summary": counters}


def apply_import(conn: sqlite3.Connection, kind: str, rows: list[dict],
                 create_missing: bool, user: dict | None) -> dict:
    result = preview(conn, kind, rows, create_missing)
    spec = SCHEMAS[kind]
    key = spec["key"]
    now = now_iso()

    existing = {str(dict(r).get(key) or ""): dict(r)
                for r in conn.execute(f"SELECT * FROM {spec['table']}").fetchall()}
    asset_by_code = {r["code"]: r["id"]
                     for r in conn.execute("SELECT id, code FROM assets").fetchall()}

    label_to_col = {label: col for col, label, _ in spec["fields"]}
    written = 0
    for item in result["rows"]:
        if item["action"] not in ("update", "create"):
            continue
        changes = {label_to_col.get(label, label): new for label, _old, new in item["changes"]}
        if item["action"] == "update":
            current = existing.get(item["key"])
            if current is None:
                continue
            sets, params = [], []
            for col, value in changes.items():
                if col in ("checklist",):
                    import json

                    sets.append("checklist_json = ?")
                    params.append(json.dumps(value, ensure_ascii=False))
                else:
                    sets.append(f"{col} = ?")
                    params.append(value)
            if not sets:
                continue
            if kind in ("assets",):
                sets.append("running_hours_at = ?")
                params.append(now)
            params.append(current["id"])
            conn.execute(f"UPDATE {spec['table']} SET {', '.join(sets)} WHERE id = ?", params)
            written += 1
        else:
            cols, marks, params = [], [], []
            for col, value in changes.items():
                if col == "checklist":
                    import json

                    cols.append("checklist_json")
                    marks.append("?")
                    params.append(json.dumps(value, ensure_ascii=False))
                else:
                    cols.append(col)
                    marks.append("?")
                    params.append(value)
            if kind == "assets":
                cols += ["created_at"]
                marks += ["?"]
                params.append(now)
            elif kind == "plans":
                cols += ["created_at", "active"]
                marks += ["?", "1"]
                params.append(now)
            conn.execute(
                f"INSERT INTO {spec['table']} ({', '.join(cols)}) VALUES ({', '.join(marks)})", params
            )
            written += 1

    audit.write(conn, f"import.{kind}", user, spec["table"], "bulk",
                after={"written": written, "summary": result["summary"]})
    return {"written": written, "summary": result["summary"]}


def template_csv(kind: str) -> str:
    """空模板：只有表头 + 一行示例，避免用户删错列。"""
    cols = headers(kind)
    examples = {
        "assets": ["ME-01", "主机", "", "machinery", "A", "MAN B&W", "6S50MC-C", "", "机舱底层", "18540", "in_service", ""],
        "plans": ["ME-01-250H", "ME-01", "主机 250 小时常规检查", "", "250", "2", "officer",
                  "厂家手册 · ISM 10", "检查排温；检查油压", "2026-12-31", "是"],
        "parts": ["SP-0001", "主机燃油滤芯", "MAN 6S50MC-C 配套", "PCS", "", "A-01", "6", "8", "320", "CNY", "是", ""],
        "certificates": ["安全管理证书 SMC", "SMC-001", "statutory", "船旗国主管机关", "2024-01-01", "2029-01-01", "90", ""],
    }
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=cols)
    writer.writeheader()
    writer.writerow(dict(zip(cols, examples.get(kind, [""] * len(cols)))))
    return "\ufeff" + buffer.getvalue()
