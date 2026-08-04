"""Voice date/time hint normalization and three-tier slot matching."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.services.voice_fastpath import (
    _normalize_date_hint,
    _normalize_time_hint,
    match_slot,
    resolve_date_key,
)

# Fixed "today" so weekday math is deterministic (Tuesday)
_TODAY = date(2026, 7, 21)
_SAT = "2026-07-25"  # next Saturday
_WED = "2026-07-22"  # tomorrow Wednesday
_WINDOW = {
    ( _TODAY + timedelta(days=i) ).isoformat()
    for i in range(14)
}


def _day_slots(day: str, hours: list[int]) -> list[dict]:
    return [
        {
            "slot_id": 100 + h,
            "slot_start": f"{day} {h:02d}:00",
            "slot_end": f"{day} {h:02d}:30",
        }
        for h in hours
    ]


def test_normalize_date_hint_rejects_stale_gpt_year():
    assert _normalize_date_hint("2023-10-31", today=_TODAY) is None
    assert _normalize_date_hint("2026-7-25", today=_TODAY) == _SAT
    assert _normalize_date_hint("2026-07-25", today=_TODAY) == _SAT


def test_normalize_time_hint_arabic_digit_and_daytime_bias():
    assert _normalize_time_hint("٢") == "14:00"
    assert _normalize_time_hint("الساعة ٢") == "14:00"
    assert _normalize_time_hint("2") == "14:00"
    assert _normalize_time_hint("14:00") == "14:00"
    assert _normalize_time_hint("2:00 PM") == "14:00"
    assert _normalize_time_hint("9") == "09:00"  # 8–11 stay morning unless +12 fallback
    # Letter م inside مع/منى must NOT block daytime bias
    assert (
        _normalize_time_hint(
            None,
            transcript="عايز أحجز مع دكتور منى يوم السبت الساعة ٢",
        )
        == "14:00"
    )


def test_resolve_truncated_tuesday_despite_stale_gpt_date():
    """Prod log: date='2023-10-31' text='... يوم الثلاث' → must resolve, not picker."""
    key = resolve_date_key(
        date_hint="2023-10-31",
        transcript="عايز أحجز مع دكتور نور الدين يوم الثلاث",
        available=_WINDOW,
        today=_TODAY,
    )
    assert key == _TODAY.isoformat()  # Tuesday 2026-07-21


def test_a_full_match_exact_slot():
    """doctor + day + time all resolvable → match_slot returns that slot."""
    avail = {_SAT: _day_slots(_SAT, [14, 16])}
    matched = match_slot(
        avail,
        date_hint="2023-10-31",  # stale GPT date ignored
        time_hint="٢",
        transcript="عايز أحجز مع دكتور منى يوم السبت الساعة ٢",
        today=_TODAY,
    )
    assert matched is not None
    assert matched["slot_id"] == 114
    start = matched["slot_start"]
    assert "14:00" in (start if isinstance(start, str) else start.strftime("%H:%M"))


def test_b_day_only_resolves_without_time():
    """doctor + day, no time → date key for that day (caller shows slot list)."""
    key = resolve_date_key(
        date_hint=None,
        transcript="عايز أحجز مع دكتور منى يوم السبت",
        available=_WINDOW,
        today=_TODAY,
    )
    assert key == _SAT
    avail = {_SAT: _day_slots(_SAT, [10, 14]), _WED: _day_slots(_WED, [11])}
    assert match_slot(avail, date_hint=None, time_hint=None, transcript="يوم السبت") is None
    # Same-day fallback eligibility: date resolves, exact slot does not
    assert key in avail


def test_c_day_plus_unmatched_time_still_resolves_day():
    """Exact time missing → still resolve the day (same-day list, not full picker)."""
    avail = {_SAT: _day_slots(_SAT, [10, 11, 16])}  # no 14:00
    matched = match_slot(
        avail,
        date_hint=_SAT,
        time_hint="14:00",
        transcript="يوم السبت الساعة ٢",
    )
    assert matched is None
    key = resolve_date_key(
        date_hint=_SAT,
        transcript="يوم السبت الساعة ٢",
        available=set(avail.keys()),
        today=_TODAY,
    )
    assert key == _SAT
    assert key in avail


def test_d_doctor_only_no_date_key():
    """doctor only → no date_key → full date picker path."""
    key = resolve_date_key(
        date_hint=None,
        transcript="عايز أحجز مع دكتور منى",
        available=_WINDOW,
        today=_TODAY,
    )
    assert key is None


def test_tomorrow_arabic_and_english():
    for text in ("عايز أحجز بكرة", "غداً الساعة 10", "book tomorrow", "tommorow please"):
        key = resolve_date_key(
            date_hint=None,
            transcript=text,
            available=_WINDOW,
            today=_TODAY,
        )
        assert key == _WED, text


def test_day_after_tomorrow_not_confused_with_tomorrow():
    """'بعد بكرة' contains 'بكرة' — must resolve to +2, not +1."""
    after = (_TODAY + timedelta(days=2)).isoformat()  # Thursday 2026-07-23
    for text in (
        "عايز أحجز بعد بكرة",
        "بعد غد",
        "day after tomorrow",
        "after tomorrow with Dr Nour",
    ):
        key = resolve_date_key(
            date_hint=None,
            transcript=text,
            available=_WINDOW,
            today=_TODAY,
        )
        assert key == after, text


def test_bare_monday_picks_next_available_monday():
    """Bare 'الإثنين' / Monday → next Monday that has openings."""
    # Today is Tue 21 Jul; next Monday is 27 Jul. Skip a Monday with no slots.
    monday = "2026-07-27"
    other = "2026-07-25"  # Saturday
    avail = {monday, other}
    for text in ("عايز يوم الإثنين", "الاتنين", "monday please"):
        key = resolve_date_key(
            date_hint=None,
            transcript=text,
            available=avail,
            today=_TODAY,
        )
        assert key == monday, text


def test_bare_monday_skips_unavailable_to_following_week():
    """If nearest Monday has no slots, use the next Monday in the window."""
    first_mon = "2026-07-27"
    second_mon = "2026-08-03"
    avail = {second_mon, "2026-07-25"}  # first Monday missing
    key = resolve_date_key(
        date_hint=None,
        transcript="الإثنين",
        available=avail,
        today=_TODAY,
        window_days=21,
    )
    assert key == second_mon
    assert key != first_mon
