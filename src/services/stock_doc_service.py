"""库存单据：入库 / 出库 / 盘库。草稿可编辑可取消，过账后锁定并写库存流水。

过账规则：
- 入库：在库增加，流水类型 in，单价按单据行快照
- 出库：校验可用量（在库 − 预留）后扣减，关联工单时同步记录工单领料
- 盘库：过账时快照账面数，在库置为实盘数，差异行必须填写原因
已过账单据不可改不可删，纠正只能开新单据（台账只追加、可审计）。
"""
import sqlite3

from services import audit, ids, stock_service
from services.timeutil import now_iso, today_str

TYPE_LABEL = {"in": "入库", "out": "出库", "adjust": "盘库"}
STATUS_LABEL = {"draft": "草稿", "posted": "已过账", "cancelled": "已取消"}
PARTY_LABEL = {"in": "供应商", "out": "领用人 / 部门", "adjust": "盘点范围"}


def _decorate(doc: dict) -> dict:
    doc["type_label"] = TYPE_LABEL.get(doc["type"], doc["type"])
    doc["status_label"] = STATUS_LABEL.get(doc["status"], doc["status"])
    doc["party_label"] = PARTY_LABEL.get(doc["type"], "往来方")
    return doc


def list_docs(conn: sqlite3.Connection, doc_type: str = "", status: str = "",
              q: str = "", limit: int = 100) -> list[dict]:
    sql = (
        "SELECT d.*, (SELECT COUNT(*) FROM stock_doc_lines l WHERE l.doc_id = d.id) AS line_count,"
        " u.display_name AS creator_name, v.display_name AS poster_name"
        " FROM stock_docs d LEFT JOIN users u ON u.id = d.created_by"
        " LEFT JOIN users v ON v.id = d.posted_by WHERE 1=1"
    )
    params: list = []
    if doc_type in TYPE_LABEL:
        sql += " AND d.type = ?"
        params.append(doc_type)
    if status in STATUS_LABEL:
        sql += " AND d.status = ?"
        params.append(status)
    if q:
        sql += " AND (d.no LIKE ? OR d.party LIKE ? OR d.ref_no LIKE ?)"
        params += [f"%{q}%"] * 3
    sql += " ORDER BY d.id DESC LIMIT ?"
    params.append(limit)
    return [_decorate(dict(r)) for r in conn.execute(sql, params).fetchall()]


def get_doc(conn: sqlite3.Connection, doc_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM stock_docs WHERE id = ?", (doc_id,)).fetchone()
    if row is None:
        return None
    lines = [dict(r) for r in conn.execute(
        "SELECT l.*, p.code AS part_code, p.name AS part_name, p.spec, p.unit,"
        " p.on_hand AS current_on_hand, p.reserved AS current_reserved"
        " FROM stock_doc_lines l JOIN parts p ON p.id = l.part_id"
        " WHERE l.doc_id = ? ORDER BY l.seq, l.id", (doc_id,)
    ).fetchall()]
    return _decorate({**dict(row), "lines": lines})


def _validate_head(conn: sqlite3.Connection, doc_type: str, data: dict):
    errors: list[str] = []
    doc_date = str(data.get("doc_date") or "").strip()
    if doc_date and (len(doc_date) != 10 or doc_date[4] != "-" or doc_date[7] != "-"):
        errors.append("业务日期格式应为 YYYY-MM-DD")
    wo_id = None
    if data.get("wo_id") not in (None, ""):
        try:
            wo_id = int(data["wo_id"])
        except (TypeError, ValueError):
            errors.append("关联工单不合法")
            wo_id = None
        else:
            wo = conn.execute("SELECT id, status FROM work_orders WHERE id = ?", (wo_id,)).fetchone()
            if wo is None:
                errors.append("关联工单不存在")
                wo_id = None
            elif wo["status"] in ("verified", "cancelled"):
                errors.append("已关闭的工单不能关联领料")
                wo_id = None
    return doc_date or today_str(), wo_id, errors


def _validate_lines(conn: sqlite3.Connection, doc_type: str, raw_lines) -> tuple[list[dict], list[str]]:
    lines: list[dict] = []
    errors: list[str] = []
    if not isinstance(raw_lines, list) or not raw_lines:
        return [], ["至少需要一行明细"]
    for index, raw in enumerate(raw_lines, start=1):
        if not isinstance(raw, dict):
            errors.append(f"第 {index} 行格式错误")
            continue
        try:
            part_id = int(raw.get("part_id"))
        except (TypeError, ValueError):
            errors.append(f"第 {index} 行未选择备件")
            continue
        part = conn.execute("SELECT id, name FROM parts WHERE id = ?", (part_id,)).fetchone()
        if part is None:
            errors.append(f"第 {index} 行备件不存在")
            continue
        try:
            qty = float(raw.get("qty"))
        except (TypeError, ValueError):
            errors.append(f"第 {index} 行「{part['name']}」数量不是数字")
            continue
        if doc_type == "adjust":
            if qty < 0:
                errors.append(f"第 {index} 行「{part['name']}」实盘数不能为负")
                continue
        elif qty <= 0:
            errors.append(f"第 {index} 行「{part['name']}」数量必须大于 0")
            continue
        try:
            price = float(raw.get("unit_price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        lines.append({"part_id": part_id, "qty": round(qty, 2),
                      "unit_price": round(max(price, 0.0), 2),
                      "note": str(raw.get("note") or "")[:200]})
    return lines, errors


def _replace_lines(conn: sqlite3.Connection, doc_id: int, lines: list[dict]) -> None:
    conn.execute("DELETE FROM stock_doc_lines WHERE doc_id = ?", (doc_id,))
    for seq, line in enumerate(lines, start=1):
        conn.execute(
            "INSERT INTO stock_doc_lines (doc_id, part_id, qty, unit_price, note, seq)"
            " VALUES (?,?,?,?,?,?)",
            (doc_id, line["part_id"], line["qty"], line["unit_price"], line["note"], seq),
        )


def create_doc(conn: sqlite3.Connection, doc_type: str, data: dict, user: dict | None,
               tz_name: str = "Asia/Shanghai") -> int:
    if doc_type not in TYPE_LABEL:
        raise ValueError("未知的单据类型")
    doc_date, wo_id, errors = _validate_head(conn, doc_type, data)
    lines, line_errors = _validate_lines(conn, doc_type, data.get("lines"))
    errors += line_errors
    if errors:
        raise ValueError("；".join(errors[:6]))
    no = ids.next_doc_no(conn, doc_type, tz_name)
    total_qty = round(sum(l["qty"] for l in lines), 2)
    total_amount = round(sum(l["qty"] * l["unit_price"] for l in lines), 2)
    cur = conn.execute(
        "INSERT INTO stock_docs (no, type, status, doc_date, party, ref_no, wo_id, note,"
        " total_qty, total_amount, created_by, created_at) VALUES (?,?,'draft',?,?,?,?,?,?,?,?,?)",
        (no, doc_type, doc_date, str(data.get("party") or "")[:120],
         str(data.get("ref_no") or "")[:120], wo_id, str(data.get("note") or "")[:500],
         total_qty, total_amount, (user or {}).get("id"), now_iso()),
    )
    doc_id = int(cur.lastrowid)
    _replace_lines(conn, doc_id, lines)
    audit.write(conn, "stockdoc.create", user, "stock_docs", str(doc_id),
                after={"no": no, "type": doc_type, "lines": len(lines)})
    return doc_id


def update_doc(conn: sqlite3.Connection, doc_id: int, data: dict, user: dict | None) -> None:
    doc = get_doc(conn, doc_id)
    if doc is None:
        raise ValueError("单据不存在")
    if doc["status"] != "draft":
        raise ValueError("只有草稿单据可以编辑")
    doc_date, wo_id, errors = _validate_head(conn, doc["type"], data)
    lines, line_errors = _validate_lines(conn, doc["type"], data.get("lines"))
    errors += line_errors
    if errors:
        raise ValueError("；".join(errors[:6]))
    total_qty = round(sum(l["qty"] for l in lines), 2)
    total_amount = round(sum(l["qty"] * l["unit_price"] for l in lines), 2)
    conn.execute(
        "UPDATE stock_docs SET doc_date = ?, party = ?, ref_no = ?, wo_id = ?, note = ?,"
        " total_qty = ?, total_amount = ? WHERE id = ?",
        (doc_date, str(data.get("party") or "")[:120], str(data.get("ref_no") or "")[:120],
         wo_id, str(data.get("note") or "")[:500], total_qty, total_amount, doc_id),
    )
    _replace_lines(conn, doc_id, lines)
    audit.write(conn, "stockdoc.update", user, "stock_docs", str(doc_id),
                after={"no": doc["no"], "lines": len(lines)})


def cancel_doc(conn: sqlite3.Connection, doc_id: int, user: dict | None) -> None:
    doc = get_doc(conn, doc_id)
    if doc is None:
        raise ValueError("单据不存在")
    if doc["status"] != "draft":
        raise ValueError("只有草稿单据可以取消")
    conn.execute("UPDATE stock_docs SET status = 'cancelled' WHERE id = ?", (doc_id,))
    audit.write(conn, "stockdoc.cancel", user, "stock_docs", str(doc_id),
                before={"status": "draft"}, after={"status": "cancelled"})


def _post_problems(doc: dict) -> list[str]:
    problems: list[str] = []
    for index, line in enumerate(doc["lines"], start=1):
        name = line.get("part_name") or f"#{line['part_id']}"
        if doc["type"] == "out":
            available = float(line["current_on_hand"]) - float(line["current_reserved"])
            if available + 1e-9 < line["qty"]:
                problems.append(
                    f"第 {index} 行「{name}」可用量不足（可用 {available:g}，申请 {line['qty']:g}）")
        elif doc["type"] == "adjust":
            variance = round(line["qty"] - float(line["current_on_hand"]), 2)
            if abs(variance) > 1e-9 and not line["note"]:
                problems.append(
                    f"第 {index} 行「{name}」盘点差异 {variance:+g}，必须填写原因")
    return problems


def post_doc(conn: sqlite3.Connection, doc_id: int, user: dict | None) -> None:
    doc = get_doc(conn, doc_id)
    if doc is None:
        raise ValueError("单据不存在")
    if doc["status"] != "draft":
        raise ValueError("只有草稿单据可以过账")
    if not doc["lines"]:
        raise ValueError("空单据不能过账")
    problems = _post_problems(doc)
    if problems:
        raise ValueError("；".join(problems[:6]))

    for line in doc["lines"]:
        part_id, qty = line["part_id"], line["qty"]
        note = line["note"] or {"in": "入库单入库", "out": "出库单出库", "adjust": "盘点"}[doc["type"]]
        if doc["type"] == "adjust":
            book = float(line["current_on_hand"])
            stock_service.move(conn, part_id, "adjust", qty, user, ref_no=doc["no"],
                               note=f"{note}：账面 {book:g} → 实盘 {qty:g}")
            conn.execute("UPDATE stock_doc_lines SET book_qty = ?, variance = ? WHERE id = ?",
                         (book, round(qty - book, 2), line["id"]))
        else:
            stock_service.move(conn, part_id, doc["type"], qty, user, ref_no=doc["no"],
                               wo_id=doc["wo_id"], note=note)
            if doc["type"] == "out" and doc["wo_id"]:
                conn.execute(
                    "INSERT INTO wo_spares (wo_id, part_id, qty, action) VALUES (?,?,?,'issue')",
                    (doc["wo_id"], part_id, qty),
                )

    conn.execute(
        "UPDATE stock_docs SET status = 'posted', posted_by = ?, posted_at = ?,"
        " total_qty = ?, total_amount = ? WHERE id = ?",
        ((user or {}).get("id"), now_iso(), doc["total_qty"], doc["total_amount"], doc_id),
    )
    audit.write(conn, "stockdoc.post", user, "stock_docs", str(doc_id),
                before={"status": "draft"}, after={"status": "posted", "no": doc["no"]})


def stocktake_draft(conn: sqlite3.Connection, part_ids: list[int] | None = None,
                    location: str = "", user: dict | None = None,
                    tz_name: str = "Asia/Shanghai") -> int:
    """生成盘点草稿：实盘数预填账面数，用户只改有差异的行。"""
    if part_ids:
        marks = ",".join("?" * len(part_ids))
        rows = conn.execute(
            f"SELECT id, on_hand, unit_price FROM parts WHERE id IN ({marks}) ORDER BY code",
            tuple(part_ids),
        ).fetchall()
        scope = f"勾选 {len(rows)} 项"
    elif location:
        rows = conn.execute(
            "SELECT id, on_hand, unit_price FROM parts WHERE location LIKE ? ORDER BY code",
            (f"%{location}%",),
        ).fetchall()
        scope = f"位置「{location}」"
    else:
        rows = conn.execute("SELECT id, on_hand, unit_price FROM parts ORDER BY code").fetchall()
        scope = "全库"
    if not rows:
        raise ValueError("没有匹配的备件，无法生成盘点单")
    lines = [{"part_id": int(r["id"]), "qty": float(r["on_hand"] or 0),
              "unit_price": float(r["unit_price"] or 0), "note": ""} for r in rows]
    return create_doc(conn, "adjust", {
        "party": scope,
        "note": "系统生成的盘点草稿：请按实际盘存修改数量，有差异的行必须填写原因。",
        "lines": lines,
    }, user, tz_name)
