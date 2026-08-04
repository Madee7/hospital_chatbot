"""Choice mapper must not steal book+day free text onto doctor/date rows."""

from __future__ import annotations

from app.services.choice_resolver import (
    looks_like_schedule_booking_text,
    resolve_choice,
)


_DOCTOR_OPTS = [
    {"id": "doctor_13", "title": "د. محمود سعيد", "description": "باطنة"},
    {"id": "doctor_9", "title": "د. دينا حسن", "description": "نساء"},
]


def test_looks_like_schedule_booking_text():
    assert looks_like_schedule_booking_text("احجز الدكتور ده يوم الأربعاء")
    assert looks_like_schedule_booking_text("book this doctor tomorrow at 10")
    assert not looks_like_schedule_booking_text("د. محمود سعيد")
    assert not looks_like_schedule_booking_text("1")


def test_book_wednesday_not_mapped_to_doctor():
    hit = resolve_choice(
        "احجز الدكتور ده يوم الأربعاء",
        _DOCTOR_OPTS,
        allow_llm=False,
    )
    assert hit is None


def test_exact_doctor_title_still_maps():
    hit = resolve_choice("د. محمود سعيد", _DOCTOR_OPTS, allow_llm=False)
    assert hit == "doctor_13"


def test_list_index_still_maps():
    hit = resolve_choice("1", _DOCTOR_OPTS, allow_llm=False)
    assert hit == "doctor_13"
