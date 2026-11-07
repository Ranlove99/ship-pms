"""备份、恢复校验与完整性检查。"""
import os
import sqlite3
from datetime import datetime

from config import Config
from services import audit, record_chain
from services.timeutil import now_iso

PREFIX = "pms-"


def backup_dir() -> str:
    path = Config.BACKUP_DIR
    os.makedirs(path, exist_ok=True)
    return path


def run_backup(conn: sqlite3.Connection, keep: int = 30, user: dict | None = None) -> dict:
    """VACUUM INTO 必须在事务之外执行，因此本函数不自带 BEGIN。"""
    target_dir = _target_dir()
    os.makedirs(target_dir, exist_ok=True)

    name = f"{PREFIX}{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    target = os.path.join(target_dir, name)
    conn.execute("VACUUM INTO ?", (target,))
    size = os.path.getsize(target)

    files = sorted(f for f in os.listdir(target_dir) if f.startswith(PREFIX) and f.endswith(".db"))
    removed = []
    while len(files) > max(1, keep):
        old = files.pop(0)
        try:
            os.remove(os.path.join(target_dir, old))
            removed.append(old)
        except OSError:
            break

    audit.write(conn, "backup.run", user, "system", name,
                after={"size": size, "dir": target_dir, "removed": removed})
    return {"file": name, "path": target, "size": size, "removed": removed, "dir": target_dir}


def _target_dir() -> str:
    """优先写入用户可见的共享目录；共享目录不存在时退回应用数据目录。"""
    share = Config.DATA_SHARE
    if os.path.isdir(share) and os.access(share, os.W_OK):
        return os.path.join(share, "backup")
    return backup_dir()


def list_backups() -> list[dict]:
    dirs = [os.path.join(Config.DATA_SHARE, "backup"), backup_dir()]
    seen, items = set(), []
    for directory in dirs:
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory), reverse=True):
            if not (name.startswith(PREFIX) and name.endswith(".db")) or name in seen:
                continue
            path = os.path.join(directory, name)
            seen.add(name)
            items.append({
                "name": name,
                "size": os.path.getsize(path),
                "at": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M"),
                "path": path,
            })
    items.sort(key=lambda i: i["at"], reverse=True)
    return items


def verify_file(path: str) -> dict:
    if not os.path.exists(path):
        return {"ok": False, "reason": "文件不存在"}
    try:
        conn = sqlite3.connect(path)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        version = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()[0]
        conn.close()
        return {"ok": integrity == "ok", "integrity": integrity, "schema_version": version}
    except sqlite3.Error as exc:
        return {"ok": False, "reason": str(exc)}


def integrity_report(conn: sqlite3.Connection) -> dict:
    records = record_chain.verify_all(conn)
    audit_res = audit.verify_chain(conn)
    db_check = conn.execute("PRAGMA integrity_check").fetchone()[0]
    return {
        "at": now_iso(),
        "database": {"ok": db_check == "ok", "detail": db_check},
        "records": records,
        "audit": audit_res,
        "ok": records["ok"] and audit_res["ok"] and db_check == "ok",
    }
