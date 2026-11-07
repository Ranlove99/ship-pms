"""时间与日期工具。船时由 vessel.timezone 决定，存储一律 UTC。"""
from datetime import datetime, timedelta, timezone

_FALLBACK_TZ = timezone(timedelta(hours=8))


def _tz(name: str):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name or "Asia/Shanghai")
    except Exception:
        return _FALLBACK_TZ


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    return iso(now_utc())


def local_now(tz_name: str) -> datetime:
    return now_utc().astimezone(_tz(tz_name))


def today_str(tz_name: str = "Asia/Shanghai") -> str:
    return local_now(tz_name).strftime("%Y-%m-%d")


def parse_date(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[: len(fmt) + 2 if "%SZ" in fmt else len(value)], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def add_days(date_str: str, days: int) -> str:
    base = parse_date(date_str)
    if base is None:
        return ""
    return (base + timedelta(days=days)).strftime("%Y-%m-%d")


def days_between(from_date: str, to_date: str) -> int | None:
    a, b = parse_date(from_date), parse_date(to_date)
    if a is None or b is None:
        return None
    return (b.date() - a.date()).days


def fmt_utc_for_display(value: str, tz_name: str) -> str:
    dt = parse_date(value)
    if dt is None:
        return value or ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_tz(tz_name)).strftime("%Y-%m-%d %H:%M")


def to_utc_input(local_value: str, tz_name: str) -> str:
    """把 datetime-local 输入（船时）转成 UTC ISO 字符串。"""
    if not local_value:
        return now_iso()
    try:
        naive = datetime.strptime(local_value.replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return now_iso()
    local = naive.replace(tzinfo=_tz(tz_name))
    return iso(local)


def from_utc_input(value: str, tz_name: str) -> str:
    """UTC ISO → datetime-local 值（船时）。"""
    dt = parse_date(value)
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_tz(tz_name)).strftime("%Y-%m-%dT%H:%M")
