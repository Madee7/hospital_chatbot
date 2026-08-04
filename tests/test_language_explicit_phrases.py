"""Explicit language switch phrases (English please / بالعربي)."""

from __future__ import annotations

from app.language.language_service import (
    _is_explicit_arabic_phrase,
    _is_explicit_english_phrase,
)


def test_english_please_phrases():
    for text in (
        "English please",
        "english please",
        "please english",
        "speak english",
        "بالانجليزي",
    ):
        assert _is_explicit_english_phrase(text), text


def test_english_booking_sentence_not_switch():
    assert not _is_explicit_english_phrase(
        "I want to book with an English speaking doctor tomorrow"
    )


def test_arabic_please_phrases():
    assert _is_explicit_arabic_phrase("بالعربي")
    assert _is_explicit_arabic_phrase("Arabic please")
