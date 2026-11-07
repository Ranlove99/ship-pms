"""证书与检验：到期状态与提醒。"""
import sqlite3

from services import audit
from services.timeutil import days_between, today_str

CATEGORY_LABEL = {"statutory": "法定", "class": "船级社", "other": "其他"}


def _state(item: dict, today: str) -> dict:
    days_left = days_between(today, item.get("expires_at") or "")
    item["days_left"] = days_left
    if days_left is None:
        item["state"] = "unknown"
        item["state_label"] = "未填到期日"
    elif days_left < 0:
        item["state"] = "expired"
        item["state_label"] = f"已过期 {abs(days_left)} 天"
    elif days_left <= int(item.get("reminder_days") or 60):
        item["state"] = "soon"
        item["state_label"] = f"{days_left} 天后到期"
    else:
        item["state"] = "valid"
        item["state_label"] = f"有效（余 {days_left} 天）"
    item["category_label"] = CATEGORY_LABEL.get(item.get("category"), "")
    return item


def list_certs(conn: sqlite3.Connection, today: str | None = None) -> list[dict]:
    today = today or today_str()
    rows = conn.execute("SELECT * FROM certificates ORDER BY expires_at IS NULL, expires_at").fetchall()
    items = [_state(dict(r), today) for r in rows]
    items.sort(key=lambda i: (i["days_left"] if i["days_left"] is not None else 99999))
    return items


def due_certs(conn: sqlite3.Connection, today: str | None = None) -> list[dict]:
    return [c for c in list_certs(conn, today) if c["state"] in ("expired", "soon")]


def create(conn: sqlite3.Connection, data: dict, user: dict | None) -> int:
    cur = conn.execute(
        "INSERT INTO certificates (name, category, cert_no, issuer, issued_at, expires_at,"
        " reminder_days, file_path, status, remarks) VALUES (?,?,?,?,?,?,?,?,'valid',?)",
        (
            (data.get("name") or "").strip(), data.get("category") or "statutory",
            data.get("cert_no") or "", data.get("issuer") or "",
            data.get("issued_at") or None, data.get("expires_at") or None,
            int(data.get("reminder_days") or 60), data.get("file_path") or "",
            data.get("remarks") or "",
        ),
    )
    cert_id = int(cur.lastrowid)
    audit.write(conn, "cert.create", user, "certificates", str(cert_id), after={"name": data.get("name")})
    return cert_id


def update(conn: sqlite3.Connection, cert_id: int, data: dict, user: dict | None) -> None:
    fields = ["name", "category", "cert_no", "issuer", "issued_at", "expires_at", "remarks", "file_path"]
    sets, params = [], []
    for field in fields:
        if field in data:
            sets.append(f"{field} = ?")
            params.append(data[field] or None)
    if "reminder_days" in data:
        sets.append("reminder_days = ?")
        params.append(int(data["reminder_days"] or 60))
    if not sets:
        return
    params.append(cert_id)
    conn.execute(f"UPDATE certificates SET {', '.join(sets)} WHERE id = ?", params)
    audit.write(conn, "cert.update", user, "certificates", str(cert_id), after=data)
