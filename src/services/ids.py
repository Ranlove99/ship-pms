"""单据编号：WO-YYYYMM-0001 / DEF-YYYYMM-0001，按月连续。"""
import sqlite3

from services.timeutil import local_now


def _period(tz_name: str) -> str:
    return local_now(tz_name).strftime("%Y%m")


def next_no(conn: sqlite3.Connection, table: str, column: str, prefix: str,
            tz_name: str = "Asia/Shanghai") -> str:
    """必须在写事务内调用，否则并发可能撞号（UNIQUE 约束会拦住，调用方需重试）。"""
    period = _period(tz_name)
    like = f"{prefix}-{period}-%"
    row = conn.execute(
        f"SELECT {column} AS no FROM {table} WHERE {column} LIKE ? ORDER BY {column} DESC LIMIT 1",
        (like,),
    ).fetchone()
    seq = 1
    if row and row["no"]:
        try:
            seq = int(str(row["no"]).rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            seq = 1
    return f"{prefix}-{period}-{seq:04d}"


def next_wo_no(conn: sqlite3.Connection, tz_name: str = "Asia/Shanghai") -> str:
    return next_no(conn, "work_orders", "no", "WO", tz_name)


def next_defect_no(conn: sqlite3.Connection, tz_name: str = "Asia/Shanghai") -> str:
    return next_no(conn, "defects", "no", "DEF", tz_name)


DOC_PREFIX = {"in": "RK", "out": "CK", "adjust": "PD"}


def next_doc_no(conn: sqlite3.Connection, doc_type: str, tz_name: str = "Asia/Shanghai") -> str:
    """库存单据号：RK 入库 / CK 出库 / PD 盘库，按月连续。"""
    return next_no(conn, "stock_docs", "no", DOC_PREFIX.get(doc_type, "DOC"), tz_name)
