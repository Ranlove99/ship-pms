"""初始化种子数据：散货船模板。可重复调用，已存在数据则跳过。"""
import json
import os
import sys

from db.connection import connect, get_setting, migrate, set_setting
from db.seed.assets_bulk import ASSETS, INITIAL_HOURS
from db.seed.plans_bulk import PLANS
from db.seed.reference import CERTIFICATES, PARTS, RECORD_BOOKS, SUPPLIERS
from services.timeutil import add_days, now_iso, today_str


def is_seeded(conn) -> bool:
    return get_setting(conn, "seeded", "0") == "1"


def apply(conn, vessel: dict | None = None, admin_password: str | None = None,
          admin_username: str = "admin") -> dict:
    if is_seeded(conn):
        return {"seeded": False, "reason": "already"}

    today = today_str()
    now = now_iso()

    if vessel:
        conn.execute(
            "UPDATE vessel SET name = COALESCE(NULLIF(?,''), name), imo = ?, call_sign = ?,"
            " flag = ?, gt = ?, ship_type = ?, class_society = ?, owner = ?, manager = ?,"
            " timezone = ?, updated_at = ? WHERE id = 1",
            (
                vessel.get("name", ""), vessel.get("imo", ""), vessel.get("call_sign", ""),
                vessel.get("flag", ""), float(vessel.get("gt") or 0),
                vessel.get("ship_type") or "散货船", vessel.get("class_society", ""),
                vessel.get("owner", ""), vessel.get("manager", ""),
                vessel.get("timezone") or "Asia/Shanghai", now,
            ),
        )

    if admin_password:
        from services.passwords import hash_password

        exists = conn.execute("SELECT id FROM users WHERE username = ?", (admin_username,)).fetchone()
        if exists is None:
            conn.execute(
                "INSERT INTO users (username, display_name, role, password_hash, active, created_at)"
                " VALUES (?,?,?,?,1,?)",
                (admin_username, "系统管理员", "admin", hash_password(admin_password), now),
            )

    code_to_id: dict[str, int] = {}
    for code, parent_code, name, category, criticality, maker, model, location in ASSETS:
        parent_id = code_to_id.get(parent_code) if parent_code else None
        cur = conn.execute(
            "INSERT INTO assets (parent_id, code, name, category, criticality, maker, model,"
            " location, running_hours, running_hours_at, status, notes, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,'in_service','',?)",
            (parent_id, code, name, category, criticality, maker, model, location,
             float(INITIAL_HOURS.get(code, 0)), now if code in INITIAL_HOURS else None, now),
        )
        code_to_id[code] = int(cur.lastrowid)

    hours_by_code = {}
    for code, asset_id in code_to_id.items():
        row = conn.execute("SELECT running_hours FROM assets WHERE id = ?", (asset_id,)).fetchone()
        hours_by_code[code] = float(row["running_hours"] or 0)

    plan_count = 0
    for asset_code, code, title, interval_days, interval_hours, checklist, est_hours, regulation in PLANS:
        asset_id = code_to_id.get(asset_code)
        if asset_id is None:
            continue
        next_at = add_days(today, int(interval_days)) if interval_days else None
        next_hours = round(hours_by_code.get(asset_code, 0) + float(interval_hours), 1) if interval_hours else None
        conn.execute(
            "INSERT INTO maintenance_plans (asset_id, code, title, interval_days, interval_hours,"
            " last_done_at, last_done_hours, next_due_at, next_due_hours, checklist_json,"
            " required_spares_json, est_hours, responsible_role, regulation_ref, active, created_at)"
            " VALUES (?,?,?,?,?,NULL,NULL,?,?,?,'[]',?,'officer',?,1,?)",
            (asset_id, code, title,
             int(interval_days) if interval_days else None,
             float(interval_hours) if interval_hours else None,
             next_at, next_hours,
             json.dumps(checklist, ensure_ascii=False), float(est_hours), regulation, now),
        )
        plan_count += 1

    for name, category, cert_no, issuer, offset, valid, reminder, remark in CERTIFICATES:
        conn.execute(
            "INSERT INTO certificates (name, category, cert_no, issuer, issued_at, expires_at,"
            " reminder_days, status, remarks) VALUES (?,?,?,?,?,?,?,'valid',?)",
            (name, category, cert_no, issuer, add_days(today, offset),
             add_days(today, offset + valid), reminder, remark),
        )

    for code, title, regulation, entry_types in RECORD_BOOKS:
        conn.execute(
            "INSERT INTO record_books (code, title, regulation_ref, entry_types_json) VALUES (?,?,?,?)",
            (code, title, regulation, json.dumps(entry_types, ensure_ascii=False)),
        )

    supplier_ids: list[int] = []
    for name, contact, phone, email, address, remarks in SUPPLIERS:
        cur = conn.execute(
            "INSERT INTO suppliers (name, contact, phone, email, address, remarks, active, created_at)"
            " VALUES (?,?,?,?,?,?,1,?)",
            (name, contact, phone, email, address, remarks, now),
        )
        supplier_ids.append(int(cur.lastrowid))

    for code, name, spec, unit, mpn, location, min_qty, on_hand, price, critical, sup_idx, exp_days in PARTS:
        conn.execute(
            "INSERT INTO parts (code, name, spec, unit, maker_part_no, location, min_qty,"
            " on_hand, reserved, unit_price, currency, critical, remarks, supplier_id, expiry_date)"
            " VALUES (?,?,?,?,?,?,?,?,0,?,'CNY',?, '', ?, ?)",
            (code, name, spec, unit, mpn, location, float(min_qty), float(on_hand),
             float(price), 1 if critical else 0,
             supplier_ids[sup_idx] if sup_idx is not None else None,
             add_days(today, exp_days) if exp_days else None),
        )
        if on_hand:
            conn.execute(
                "INSERT INTO stock_moves (part_id, type, qty, ref_no, at, note)"
                " SELECT id, 'in', ?, '初始建账', ?, '模板初始库存' FROM parts WHERE code = ?",
                (float(on_hand), now, code),
            )

    set_setting(conn, "seeded", "1")
    set_setting(conn, "seeded_at", now)
    return {"seeded": True, "assets": len(code_to_id), "plans": plan_count,
            "certs": len(CERTIFICATES), "books": len(RECORD_BOOKS), "parts": len(PARTS),
            "suppliers": len(SUPPLIERS)}


def main(argv: list[str]) -> int:
    args = dict(item.split("=", 1) for item in argv if "=" in item)
    conn = connect()
    migrate(conn)
    vessel = {
        "name": args.get("vessel_name", ""),
        "imo": args.get("imo", ""),
        "call_sign": args.get("call_sign", ""),
        "flag": args.get("flag", ""),
        "gt": args.get("gt", 0),
        "class_society": args.get("class_society", ""),
        "timezone": args.get("timezone", "Asia/Shanghai"),
    }
    result = apply(conn, vessel, args.get("admin_password"), args.get("admin_username", "admin"))
    print(json.dumps(result, ensure_ascii=False))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
