"""12-hour clock formatting for bots, reminders, and admin UI."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable


def normalize_lang(lang: str | None) -> str:
    raw = (lang or "ar").strip().lower().replace("_", "-")
    if raw.startswith("en"):
        return "en"
    return "ar"


def is_english(lang: str | None) -> bool:
    return normalize_lang(lang) == "en"


def format_time_12h(value: time | datetime, lang: str | None = "ar") -> str:
    """e.g. 5:00 PM / 5:00 مساءً"""
    t = value.time() if isinstance(value, datetime) else value
    hour12 = t.hour % 12 or 12
    if is_english(lang):
        suffix = "AM" if t.hour < 12 else "PM"
        return f"{hour12}:{t.minute:02d} {suffix}"
    suffix = "صباحاً" if t.hour < 12 else "مساءً"
    return f"{hour12}:{t.minute:02d} {suffix}"


def _parse_dt(value: datetime | date | time | str | None) -> datetime | time | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, time):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    text = str(value).strip().replace("Z", "")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        try:
            parts = text.split(":")
            if len(parts) >= 2:
                return time(int(parts[0]), int(parts[1]))
        except ValueError:
            return None
    return None


def format_datetime_12h(value: datetime | date | time | str | None, lang: str | None = "ar") -> str:
    """Date + 12h time, or time-only / date-only when that is all we have."""
    parsed = _parse_dt(value)
    if parsed is None:
        return "" if value is None else str(value)
    if isinstance(parsed, time):
        return format_time_12h(parsed, lang)
    date_part = parsed.strftime("%Y-%m-%d")
    if parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0 and parsed.microsecond == 0:
        # Likely date-only midnight; still show clock for consistency when explicit midnight matters.
        pass
    return f"{date_part} {format_time_12h(parsed, lang)}"


def iter_clock_times(*, step_minutes: int = 15, include_end_of_day: bool = False) -> list[time]:
    """Clock options for admin selects (default every 15 minutes)."""
    step = max(1, int(step_minutes))
    out: list[time] = []
    for minutes in range(0, 24 * 60, step):
        out.append(time(minutes // 60, minutes % 60))
    if include_end_of_day and out[-1] != time(23, 59):
        out.append(time(23, 59))
    return out


def nearest_clock_time(value: time, choices: Iterable[time]) -> time:
    opts = list(choices)
    if not opts:
        return value
    target = value.hour * 60 + value.minute
    return min(opts, key=lambda t: abs((t.hour * 60 + t.minute) - target))
