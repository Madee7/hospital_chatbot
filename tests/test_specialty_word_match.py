"""Regression: specialty aliases must match whole words, not substrings.

Bug: the dental alias 'سن' matched inside the doctor name 'حسن' (Hassan),
so 'Dr. Dina Hassan' got misrouted to the dental department.
"""

from __future__ import annotations

from app.services.doctor_service import _word_match


def test_short_alias_does_not_match_inside_name():
    # 'سن' (tooth) must NOT match inside 'حسن' (Hassan) or 'دينا حسن'
    assert not _word_match("دينا حسن", "سن")
    assert not _word_match("أنا عايز أحجز مع دكتور دينا حسن", "سن")
    # 'عين' (eye) must NOT match inside 'حسنين' / 'زين'
    assert not _word_match("محمد زين", "عين")


def test_alias_matches_as_whole_word():
    assert _word_match("عايز دكتور أسنان", "أسنان")
    assert _word_match("محتاج قلب", "قلب")
    # normalization: أ→ا, ة→ه
    assert _word_match("عيادة الاسنان", "اسنان")
    assert _word_match("dental clinic", "dental")


def test_multiword_phrase_boundary():
    assert _word_match("internal medicine department", "internal medicine")
    assert not _word_match("internalize the medicine", "internal medicine")


def test_empty_inputs():
    assert not _word_match("", "قلب")
    assert not _word_match("قلب", "")
    assert not _word_match(None, None)
