"""到期计算：日历与运行小时双触发，取先到。"""
from services.timeutil import add_days, days_between

STATUS_ORDER = {"overdue": 0, "due": 1, "idle": 2, "ok": 3}


def compute_next(last_done_at: str | None, interval_days: int | None,
                 last_done_hours: float | None, interval_hours: float | None) -> tuple[str | None, float | None]:
    next_at = add_days(last_done_at, int(interval_days)) if (last_done_at and interval_days) else None
    next_hours = None
    if last_done_hours is not None and interval_hours:
        next_hours = round(float(last_done_hours) + float(interval_hours), 1)
    return next_at, next_hours


def plan_state(next_due_at: str | None, next_due_hours: float | None,
               today: str, current_hours: float | None,
               warn_days: int = 30, hours_warn: int = 100) -> dict:
    days_left = days_between(today, next_due_at) if next_due_at else None
    hours_left = None
    if next_due_hours is not None and current_hours is not None:
        hours_left = round(float(next_due_hours) - float(current_hours), 1)

    by_date = days_left is not None and days_left < 0
    by_hours = hours_left is not None and hours_left <= 0
    if by_date or by_hours:
        status = "overdue"
    elif (days_left is not None and days_left <= warn_days) or (hours_left is not None and hours_left <= hours_warn):
        status = "due"
    elif days_left is None and hours_left is None:
        status = "idle"
    else:
        status = "ok"

    return {
        "days_left": days_left,
        "hours_left": hours_left,
        "status": status,
        "driver": "date" if by_date else ("hours" if by_hours else ""),
    }


def sort_key(state: dict) -> tuple:
    days = state["days_left"] if state["days_left"] is not None else 99999
    hours = state["hours_left"] if state["hours_left"] is not None else 99999
    return (STATUS_ORDER.get(state["status"], 9), min(days, hours / 24 if hours < 99999 else 99999))


def label(state: dict) -> str:
    if state["status"] == "overdue":
        parts = []
        if state["days_left"] is not None and state["days_left"] < 0:
            parts.append(f"逾期 {abs(state['days_left'])} 天")
        if state["hours_left"] is not None and state["hours_left"] <= 0:
            parts.append(f"超小时 {abs(state['hours_left']):.0f} h")
        return "／".join(parts) or "逾期"
    if state["status"] == "due":
        if state["days_left"] is not None and state["days_left"] <= 30:
            return f"{state['days_left']} 天内到期"
        if state["hours_left"] is not None:
            return f"剩余 {state['hours_left']:.0f} h"
        return "临近到期"
    if state["status"] == "idle":
        return "未设周期"
    if state["days_left"] is not None:
        return f"{state['days_left']} 天后"
    if state["hours_left"] is not None:
        return f"剩余 {state['hours_left']:.0f} h"
    return "正常"
