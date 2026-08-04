"""Back / رجوع typo tolerance."""

from __future__ import annotations

from app.graph.conversation_engine import _is_explicit_back_choice


def test_back_typos():
    assert _is_explicit_back_choice("", "Back")
    assert _is_explicit_back_choice("", "back")
    assert _is_explicit_back_choice("", "baaack")
    assert _is_explicit_back_choice("", "bacck")
    assert _is_explicit_back_choice("", "رجوع")
    assert _is_explicit_back_choice("", "عودة")
    assert not _is_explicit_back_choice("", "baaack please cancel")
    assert not _is_explicit_back_choice("", "book")
