"""Friendly weekday+time schedule <-> cron string.

Cron format: "minute hour * * dow" with day-of-week NAMES (mon..sun) — numeric
day-of-week is ambiguous (0=Mon in APScheduler's field vs 0=Sun in crontab), so
names keep the stored string unambiguous wherever it's parsed.
"""
from __future__ import annotations

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
LABELS = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu",
          "fri": "Fri", "sat": "Sat", "sun": "Sun"}


def build_cron(days: list[str], hour: int, minute: int) -> str:
    days = [d for d in WEEKDAYS if d in set(days)]  # normalize order, drop junk
    dow = ",".join(days) if days else "*"
    return f"{int(minute)} {int(hour)} * * {dow}"


def parse_cron(expr: str) -> dict:
    """Inverse for pre-filling the edit form: {days, hour, minute}."""
    parts = expr.split()
    minute, hour, dow = parts[0], parts[1], parts[4]
    days = [] if dow == "*" else [d for d in dow.split(",") if d in WEEKDAYS]
    return {"days": days, "hour": int(hour), "minute": int(minute)}


def describe(expr: str) -> str:
    p = parse_cron(expr)
    t = f"{p['hour']:02d}:{p['minute']:02d}"
    if not p["days"]:
        return f"every day at {t}"
    if p["days"] == ["mon", "tue", "wed", "thu", "fri"]:
        return f"Mon–Fri at {t}"
    return ", ".join(LABELS[d] for d in p["days"]) + f" at {t}"


if __name__ == "__main__":  # python -m geobot.cron_builder — self-check
    assert build_cron(["mon", "tue", "wed", "thu", "fri"], 9, 50) == "50 9 * * mon,tue,wed,thu,fri"
    assert build_cron([], 18, 0) == "0 18 * * *"
    assert build_cron(["fri", "mon"], 7, 5) == "5 7 * * mon,fri"  # reordered
    assert parse_cron("50 9 * * mon,tue,wed,thu,fri") == {
        "days": ["mon", "tue", "wed", "thu", "fri"], "hour": 9, "minute": 50}
    assert describe("50 9 * * mon,tue,wed,thu,fri") == "Mon–Fri at 09:50"
    assert describe("0 18 * * *") == "every day at 18:00"
    print("cron_builder ok")
