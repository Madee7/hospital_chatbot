"""Schema expansion: change_target + extended language codes, and edit-flow routing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import voice_fastpath
from app.services.voice_schemas import VoiceUnderstanding


# ---------------------------------------------------------------------------
# Schema: change_target coercion
# ---------------------------------------------------------------------------


def test_change_target_english_and_synonyms():
    assert VoiceUnderstanding(change_target="doctor").change_target == "doctor"
    assert VoiceUnderstanding(change_target="physician").change_target == "doctor"
    assert VoiceUnderstanding(change_target="day").change_target == "date"
    assert VoiceUnderstanding(change_target="slot").change_target == "time"


def test_change_target_arabic_synonyms():
    assert VoiceUnderstanding(change_target="طبيب").change_target == "doctor"
    assert VoiceUnderstanding(change_target="يوم").change_target == "date"
    assert VoiceUnderstanding(change_target="وقت").change_target == "time"


def test_change_target_unknown_and_empty_become_none():
    assert VoiceUnderstanding(change_target="").change_target is None
    assert VoiceUnderstanding(change_target=None).change_target is None
    assert VoiceUnderstanding(change_target="something").change_target is None


# ---------------------------------------------------------------------------
# Schema: extended language codes + base_language folding
# ---------------------------------------------------------------------------


def test_language_extended_codes_accepted():
    assert VoiceUnderstanding(language="ar-EG").language == "ar-EG"
    assert VoiceUnderstanding(language="en-US").language == "en-US"
    assert VoiceUnderstanding(language="en-GB").language == "en-GB"
    assert VoiceUnderstanding(language="mixed").language == "mixed"


def test_language_normalizer_maps_variants():
    assert VoiceUnderstanding(language="arabic").language == "ar"
    assert VoiceUnderstanding(language="egyptian").language == "ar-EG"
    assert VoiceUnderstanding(language="en_us").language == "en-US"
    assert VoiceUnderstanding(language="english").language == "en"
    # Unrecognized falls back to ar (Egyptian-Arabic-first chatbot)
    assert VoiceUnderstanding(language="fr").language == "ar"


def test_base_language_folds_regional_codes():
    assert VoiceUnderstanding(language="ar-EG").base_language() == "ar"
    assert VoiceUnderstanding(language="en-GB").base_language() == "en"
    assert VoiceUnderstanding(language="mixed").base_language() == "mixed"
    assert VoiceUnderstanding(language="unknown").base_language() == "unknown"


# ---------------------------------------------------------------------------
# Fastpath: reschedule change_type dispatches by change_target
# ---------------------------------------------------------------------------


def _run_change_type(result: dict) -> list[str]:
    """Drive try_voice_midflow at awaiting=change_type; capture dispatched seeds."""
    sess = {"awaiting": "change_type", "last_options": []}
    conversation = SimpleNamespace(state=None)
    dispatched: list[str] = []

    def _fake_dispatch(db, phone, *, text="", payload_id=None):
        dispatched.append(text)
        return True

    with (
        patch.object(voice_fastpath, "_sess", return_value=sess),
        patch.object(voice_fastpath, "_dispatch", side_effect=_fake_dispatch),
    ):
        voice_fastpath.try_voice_midflow(
            MagicMock(), phone="2010", result=result, conversation=conversation
        )
    return dispatched


def test_change_type_uses_change_target_doctor():
    out = _run_change_type(
        {"transcript": "غير حاجة", "change_target": "doctor", "action": "intent"}
    )
    assert out == ["تغيير الطبيب"]


def test_change_type_uses_change_target_date():
    out = _run_change_type(
        {"transcript": "غير حاجة", "change_target": "date", "action": "intent"}
    )
    assert out == ["تغيير اليوم"]


def test_change_type_uses_change_target_time():
    out = _run_change_type(
        {"transcript": "غير حاجة", "change_target": "time", "action": "intent"}
    )
    assert out == ["تغيير الوقت"]


def test_change_type_falls_back_to_transcript_keywords():
    # No change_target → keyword path still works (day/date branch)
    out = _run_change_type(
        {"transcript": "عايز اغير اليوم", "change_target": None, "action": "intent"}
    )
    assert out == ["تغيير اليوم"]


# ---------------------------------------------------------------------------
# Change the day from the time-slot step (button + voice)
# ---------------------------------------------------------------------------


def test_wants_change_day_detection():
    # Arabic phrasings
    assert voice_fastpath._wants_change_day({}, "عايز أغير اليوم")
    assert voice_fastpath._wants_change_day({}, "ممكن يوم تاني")
    # English phrasings
    assert voice_fastpath._wants_change_day({}, "I want to change the day")
    assert voice_fastpath._wants_change_day({}, "can I pick another day")
    # Explicit router change_target
    assert voice_fastpath._wants_change_day({"change_target": "date"}, "")
    # Should NOT trigger on a plain time answer
    assert not voice_fastpath._wants_change_day({}, "الساعة 2")
    assert not voice_fastpath._wants_change_day({}, "")


def _run_slot(result: dict) -> list[tuple[str, str | None]]:
    """Drive try_voice_midflow at the booking-slot step; capture dispatches."""
    from app.db.enums import ConversationState

    sess = {"awaiting": "slot", "last_options": [], "doctor_id": 1}
    conversation = SimpleNamespace(state=ConversationState.BOOKING_SLOT)
    dispatched: list[tuple[str, str | None]] = []

    def _fake_dispatch(db, phone, *, text="", payload_id=None):
        dispatched.append((text, payload_id))
        return True

    with (
        patch.object(voice_fastpath, "_sess", return_value=sess),
        patch.object(voice_fastpath, "_dispatch", side_effect=_fake_dispatch),
    ):
        voice_fastpath.try_voice_midflow(
            MagicMock(), phone="2010", result=result, conversation=conversation
        )
    return dispatched


def test_slot_step_change_day_arabic_dispatches_change_day():
    out = _run_slot(
        {"transcript": "عايز أغير اليوم", "action": "intent", "intent": "update"}
    )
    assert out == [("change_day", "change_day")]


def test_slot_step_change_day_english_dispatches_change_day():
    out = _run_slot(
        {"transcript": "change the day please", "action": "intent", "intent": "update"}
    )
    assert out == [("change_day", "change_day")]


def test_slot_step_change_target_date_dispatches_change_day():
    out = _run_slot(
        {"transcript": "غير حاجة", "change_target": "date", "action": "intent"}
    )
    assert out == [("change_day", "change_day")]
