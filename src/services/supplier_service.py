"""供应商台账：备件采购来源登记，被备件引用的供应商禁止删除。"""
import sqlite3

from services import audit
from services.timeutil import now_iso

FIELDS = ("name", "contact", "phone", "email", "address", "remarks")


def list_suppliers(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM parts p WHERE p.supplier_id = s.id) AS part_count"
        " FROM suppliers s ORDER BY s.active DESC, s.name"
    ).fetchall()
    return [dict(r) for r in rows]


def create(conn: sqlite3.Connection, data: dict, user: dict | None) -> int:
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("供应商名称必填")
    cur = conn.execute(
        "INSERT INTO suppliers (name, contact, phone, email, address, remarks, active, created_at)"
        " VALUES (?,?,?,?,?,?,1,?)",
        (name[:120], str(data.get("contact") or "")[:60], str(data.get("phone") or "")[:40],
         str(data.get("email") or "")[:80], str(data.get("address") or "")[:200],
         str(data.get("remarks") or "")[:500], now_iso()),
    )
    supplier_id = int(cur.lastrowid)
    audit.write(conn, "supplier.create", user, "suppliers", str(supplier_id), after={"name": name})
    return supplier_id


def update(conn: sqlite3.Connection, supplier_id: int, data: dict, user: dict | None) -> None:
    row = conn.execute("SELECT id FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if row is None:
        raise ValueError("供应商不存在")
    sets, params = [], []
    for field in FIELDS:
        if field in data:
            sets.append(f"{field} = ?")
            params.append(str(data[field] or "")[:500 if field in ("address", "remarks") else 120])
    if "active" in data:
        sets.append("active = ?")
        params.append(1 if data["active"] else 0)
    if not sets:
        return
    params.append(supplier_id)
    conn.execute(f"UPDATE suppliers SET {', '.join(sets)} WHERE id = ?", params)
    audit.write(conn, "supplier.update", user, "suppliers", str(supplier_id), after=data)


def delete(conn: sqlite3.Connection, supplier_id: int, user: dict | None) -> None:
    used = conn.execute(
        "SELECT COUNT(*) AS n FROM parts WHERE supplier_id = ?", (supplier_id,)
    ).fetchone()["n"]
    if used:
        raise ValueError(f"该供应商已被 {used} 个备件引用，不能删除")
    conn.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
    audit.write(conn, "supplier.delete", user, "suppliers", str(supplier_id))
