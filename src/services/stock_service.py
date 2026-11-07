"""备件库存：可用量 = 在库 - 预留；流水只追加。"""
import sqlite3
from datetime import timedelta

from services import audit
from services.timeutil import days_between, iso, now_iso, now_utc, today_str

MOVE_LABEL = {"in": "入库", "out": "出库", "adjust": "盘点", "reserve": "预留", "release": "释放预留"}


def _public(row) -> dict:
    item = dict(row)
    item["available"] = round(float(item["on_hand"]) - float(item["reserved"]), 2)
    item["below_min"] = item["available"] < float(item["min_qty"])
    return item


def list_parts(conn: sqlite3.Connection, query: str = "", only_alerts: bool = False) -> list[dict]:
    sql = "SELECT * FROM parts WHERE 1=1"
    params: list = []
    if query:
        sql += " AND (code LIKE ? OR name LIKE ? OR spec LIKE ? OR maker_part_no LIKE ?)"
        params += [f"%{query}%"] * 4
    sql += " ORDER BY critical DESC, code"
    items = [_public(r) for r in conn.execute(sql, params).fetchall()]
    if only_alerts:
        items = [i for i in items if i["below_min"]]
    return items


def get(conn: sqlite3.Connection, part_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM parts WHERE id = ?", (part_id,)).fetchone()
    return _public(row) if row else None


def create(conn: sqlite3.Connection, data: dict, user: dict | None) -> int:
    try:
        supplier_id = int(data.get("supplier_id")) if data.get("supplier_id") not in (None, "") else None
    except (TypeError, ValueError):
        supplier_id = None
    expiry = str(data.get("expiry_date") or "").strip()
    cur = conn.execute(
        "INSERT INTO parts (code, name, spec, unit, maker_part_no, location, min_qty, on_hand,"
        " reserved, unit_price, currency, critical, remarks, supplier_id, expiry_date)"
        " VALUES (?,?,?,?,?,?,?,?,0,?,?,?,?,?,?)",
        (
            (data.get("code") or "").strip(), (data.get("name") or "").strip(),
            data.get("spec") or "", data.get("unit") or "PCS", data.get("maker_part_no") or "",
            data.get("location") or "", float(data.get("min_qty") or 0),
            float(data.get("on_hand") or 0), float(data.get("unit_price") or 0),
            data.get("currency") or "CNY", 1 if data.get("critical") else 0,
            data.get("remarks") or "", supplier_id,
            expiry[:10] if len(expiry) >= 10 else "",
        ),
    )
    part_id = int(cur.lastrowid)
    if float(data.get("on_hand") or 0) > 0:
        conn.execute(
            "INSERT INTO stock_moves (part_id, type, qty, ref_no, operator, at, note)"
            " VALUES (?, 'in', ?, '初始建账', ?, ?, '初始库存')",
            (part_id, float(data["on_hand"]), (user or {}).get("id"), now_iso()),
        )
    audit.write(conn, "part.create", user, "parts", str(part_id), after={"code": data.get("code")})
    return part_id


def update(conn: sqlite3.Connection, part_id: int, data: dict, user: dict | None) -> None:
    fields = ["code", "name", "spec", "unit", "maker_part_no", "location", "remarks"]
    sets, params = [], []
    for field in fields:
        if field in data:
            sets.append(f"{field} = ?")
            params.append(data[field] or "")
    for field in ("min_qty", "unit_price"):
        if field in data:
            sets.append(f"{field} = ?")
            params.append(float(data[field] or 0))
    if "critical" in data:
        sets.append("critical = ?")
        params.append(1 if data["critical"] else 0)
    if "supplier_id" in data:
        sets.append("supplier_id = ?")
        try:
            params.append(int(data["supplier_id"]) if data["supplier_id"] not in (None, "") else None)
        except (TypeError, ValueError):
            params.append(None)
    if "expiry_date" in data:
        sets.append("expiry_date = ?")
        expiry = str(data["expiry_date"] or "").strip()
        params.append(expiry[:10] if len(expiry) >= 10 else "")
    if not sets:
        return
    params.append(part_id)
    conn.execute(f"UPDATE parts SET {', '.join(sets)} WHERE id = ?", params)
    audit.write(conn, "part.update", user, "parts", str(part_id), after=data)


def move(conn: sqlite3.Connection, part_id: int, move_type: str, qty: float,
         user: dict | None, ref_no: str = "", note: str = "",
         wo_id: int | None = None) -> dict:
    if move_type not in MOVE_LABEL:
        raise ValueError("未知的库存动作")
    part = get(conn, part_id)
    if part is None:
        raise ValueError("备件不存在")
    qty = float(qty)
    if qty < 0 and move_type != "adjust":
        raise ValueError("数量必须为正数")

    if move_type == "in":
        conn.execute("UPDATE parts SET on_hand = on_hand + ? WHERE id = ?", (qty, part_id))
    elif move_type == "out":
        if float(part["on_hand"]) - qty < 0:
            raise ValueError(f"库存不足：在库 {part['on_hand']:g} {part['unit']}，本次出库 {qty:g}")
        conn.execute("UPDATE parts SET on_hand = on_hand - ? WHERE id = ?", (qty, part_id))
    elif move_type == "adjust":
        conn.execute("UPDATE parts SET on_hand = ? WHERE id = ?", (qty, part_id))
    elif move_type == "reserve":
        if float(part["available"]) < qty:
            raise ValueError("可用量不足，无法预留")
        conn.execute("UPDATE parts SET reserved = reserved + ? WHERE id = ?", (qty, part_id))
    elif move_type == "release":
        conn.execute("UPDATE parts SET reserved = MAX(0, reserved - ?) WHERE id = ?", (qty, part_id))

    conn.execute(
        "INSERT INTO stock_moves (part_id, type, qty, wo_id, ref_no, operator, at, note)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (part_id, move_type, qty, wo_id, ref_no, (user or {}).get("id"), now_iso(), note),
    )
    audit.write(conn, "part.move", user, "parts", str(part_id),
                after={"type": move_type, "qty": qty, "ref_no": ref_no})
    return {"part_id": part_id, "type": move_type, "qty": qty}


def issue_to_workorder(conn: sqlite3.Connection, part_id: int, qty: float,
                       wo_id: int, user: dict | None) -> None:
    move(conn, part_id, "out", qty, user, ref_no=f"WO#{wo_id}", wo_id=wo_id, note="工单领用")
    conn.execute(
        "INSERT INTO wo_spares (wo_id, part_id, qty, action) VALUES (?,?,?,'issue')",
        (wo_id, part_id, qty),
    )


def moves(conn: sqlite3.Connection, part_id: int | None = None, limit: int = 100) -> list[dict]:
    sql = (
        "SELECT m.*, p.name AS part_name, p.code AS part_code, p.unit, u.display_name AS operator_name"
        " FROM stock_moves m JOIN parts p ON p.id = m.part_id"
        " LEFT JOIN users u ON u.id = m.operator WHERE 1=1"
    )
    params: list = []
    if part_id:
        sql += " AND m.part_id = ?"
        params.append(part_id)
    sql += " ORDER BY m.id DESC LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for row in rows:
        row["type_label"] = MOVE_LABEL.get(row["type"], row["type"])
    return rows


def alerts(conn: sqlite3.Connection) -> list[dict]:
    return list_parts(conn, only_alerts=True)


def _since(days: int) -> str:
    return iso(now_utc() - timedelta(days=max(int(days), 1)))


def moves_filtered(conn: sqlite3.Connection, days: int = 90, move_type: str = "",
                   part_id: int | None = None, limit: int = 500) -> list[dict]:
    """流水台账查询：按时间窗、动作类型、备件过滤，新的在前。"""
    sql = (
        "SELECT m.*, p.name AS part_name, p.code AS part_code, p.unit, u.display_name AS operator_name"
        " FROM stock_moves m JOIN parts p ON p.id = m.part_id"
        " LEFT JOIN users u ON u.id = m.operator WHERE m.at >= ?"
    )
    params: list = [_since(days)]
    if move_type in MOVE_LABEL:
        sql += " AND m.type = ?"
        params.append(move_type)
    if part_id:
        sql += " AND m.part_id = ?"
        params.append(part_id)
    sql += " ORDER BY m.id DESC LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for row in rows:
        row["type_label"] = MOVE_LABEL.get(row["type"], row["type"])
    return rows


def consumption_map(conn: sqlite3.Connection, days: int = 90) -> dict[int, float]:
    """窗口期内各备件出库量，用于补货建议。"""
    rows = conn.execute(
        "SELECT part_id, SUM(qty) AS qty FROM stock_moves WHERE type = 'out' AND at >= ?"
        " GROUP BY part_id", (_since(days),)
    ).fetchall()
    return {int(r["part_id"]): float(r["qty"]) for r in rows}


def consumption_rows(conn: sqlite3.Connection, days: int = 90, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT m.part_id, p.code, p.name, p.unit, SUM(m.qty) AS qty, COUNT(*) AS times"
        " FROM stock_moves m JOIN parts p ON p.id = m.part_id"
        " WHERE m.type = 'out' AND m.at >= ? GROUP BY m.part_id"
        " ORDER BY qty DESC, times DESC LIMIT ?", (_since(days), limit)
    ).fetchall()
    return [dict(r) for r in rows]


def reorder_rows(conn: sqlite3.Connection, days: int = 90) -> list[dict]:
    """补货建议：可用量低于最低库存的备件。
    建议采购量 = max(2×最低 − 可用, 2×窗口期出库量, 0)，关键备件优先。"""
    consumed = consumption_map(conn, days)
    out = []
    for p in list_parts(conn):
        if not p["below_min"]:
            continue
        used = consumed.get(p["id"], 0.0)
        suggested = max(round(2 * float(p["min_qty"]) - float(p["available"]), 2),
                        round(2 * used, 2), 0.0)
        out.append({
            "id": p["id"], "code": p["code"], "name": p["name"], "spec": p["spec"],
            "unit": p["unit"], "location": p["location"], "critical": bool(p["critical"]),
            "on_hand": p["on_hand"], "reserved": p["reserved"], "available": p["available"],
            "min_qty": p["min_qty"], "used_days": round(used, 2),
            "gap": round(float(p["min_qty"]) - float(p["available"]), 2),
            "suggested": suggested,
        })
    out.sort(key=lambda r: (not r["critical"], -r["gap"], r["code"]))
    return out


def value_summary(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS kinds, COALESCE(SUM(on_hand), 0) AS on_hand,"
        " COALESCE(SUM(on_hand * unit_price), 0) AS amount FROM parts"
    ).fetchone()
    return {"kinds": int(row["kinds"]), "on_hand": round(float(row["on_hand"]), 2),
            "amount": round(float(row["amount"]), 2)}


def expiring_rows(conn: sqlite3.Connection, days: int = 60,
                  tz_name: str = "Asia/Shanghai") -> list[dict]:
    """保质期预警：已设保质期且剩余天数不超过窗口（含已过期）。"""
    today = today_str(tz_name)
    rows = conn.execute(
        "SELECT id, code, name, spec, unit, location, on_hand, expiry_date FROM parts"
        " WHERE expiry_date IS NOT NULL AND expiry_date != '' ORDER BY expiry_date"
    ).fetchall()
    out = []
    for row in rows:
        left = days_between(today, row["expiry_date"])
        if left is not None and left <= days:
            item = dict(row)
            item["days_left"] = left
            out.append(item)
    return out
