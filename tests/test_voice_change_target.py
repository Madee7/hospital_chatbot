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


# ---------------------------------------------------------------------------
# Change doctor at summary — must show doctor list, NOT cancel the draft
# ---------------------------------------------------------------------------


def test_wants_other_doctor_detection():
    assert voice_fastpath._wants_other_doctor({"change_target": "doctor"}, "")
    assert voice_fastpath._wants_other_doctor({}, "أنا عايز دكتور ثاني، مش عايز دكتور دا")
    assert voice_fastpath._wants_other_doctor({}, "عايز دكتور قلب تاني لغي الحجز")
    assert voice_fastpath._wants_other_doctor({}, "I want another doctor")
    assert not voice_fastpath._wants_other_doctor({}, "لا")
    assert not voice_fastpath._wants_other_doctor({}, "تأكيد")


def _run_summary(result: dict, *, sess: dict | None = None):
    from app.db.enums import ConversationState

    sess = sess if sess is not None else {
        "awaiting": "summary",
        "doctor_id": 13,
        "department_id": 1,
        "slot_id": 738,
        "last_options": [],
    }
    conversation = SimpleNamespace(state=ConversationState.CONFIRMING)
    restarted: list[dict] = []
    cancelled: list[str] = []

    def _fake_restart(db, *, phone, conversation, result):
        restarted.append({"phone": phone, "result": result, "sess": dict(sess)})
        return True

    def _fake_dispatch(db, phone, *, text="", payload_id=None):
        cancelled.append(text)
        return True

    with (
        patch.object(voice_fastpath, "_sess", return_value=sess),
        patch.object(voice_fastpath, "_restart_doctor_picker", side_effect=_fake_restart),
        patch.object(voice_fastpath, "_dispatch", side_effect=_fake_dispatch),
    ):
        handled = voice_fastpath.try_voice_midflow(
            MagicMock(), phone="2010", result=result, conversation=conversation
        )
    return handled, restarted, cancelled


def test_summary_change_target_doctor_shows_other_doctors_not_cancel():
    """Prod log: change='doctor' + 'مش عايز دكتور دا' was wrongly cancelled."""
    handled, restarted, cancelled = _run_summary(
        {
            "transcript": "أنا عايز دكتور ثاني، مش عايز دكتور دا",
            "action": "intent",
            "intent": "update",
            "change_target": "doctor",
            "confidence": 0.9,
        }
    )
    assert handled is True
    assert len(restarted) == 1
    assert cancelled == []


def test_summary_specialty_another_doctor_shows_doctor_list():
    """'عايز دكتور قلب تاني لغي الحجز' → cardiology doctor list, not inquiry/cancel."""
    handled, restarted, cancelled = _run_summary(
        {
            "transcript": "عايز دكتور قلب تاني لغي الحجز",
            "action": "specialty_direct",
            "intent": "ask_doctors",
            "specialty_hint": "قلب",
            "confidence": 0.7,
        }
    )
    assert handled is True
    assert len(restarted) == 1
    assert restarted[0]["result"]["specialty_hint"] == "قلب"
    assert cancelled == []


def test_summary_plain_no_still_cancels():
    handled, restarted, cancelled = _run_summary(
        {
            "transcript": "لا",
            "action": "intent",
            "intent": "cancel",
            "confidence": 0.9,
        }
    )
    assert handled is True
    assert restarted == []
    assert cancelled == ["إلغاء"]


# ---------------------------------------------------------------------------
# Specialty spoken on doctor list must NOT pick a stale doctor_* option
# ---------------------------------------------------------------------------


def test_enrich_remaps_oyoon_and_clears_hallucinated_doctor_option():
    """Prod: doctor='عيون' + option=doctor_14 → specialty, option cleared."""
    dept = SimpleNamespace(department_id=9, name_ar="عيون", name_en="Ophthalmology")
    with (
        patch.object(voice_fastpath, "find_doctor_by_hint", return_value=None),
        patch.object(voice_fastpath.doctor_service, "find_department", return_value=dept),
        patch.object(
            voice_fastpath.doctor_service,
            "infer_department_from_text",
            return_value=dept,
        ),
    ):
        out = voice_fastpath._enrich_result(
            MagicMock(),
            {
                "transcript": "طب لا، خلينا دكتور عيون",
                "action": "book_direct",
                "intent": "book",
                "doctor_hint": "عيون",
                "specialty_hint": None,
                "selected_option_id": "doctor_14",
                "change_target": "doctor",
                "confidence": 0.9,
            },
        )
    assert out["specialty_hint"] in {"عيون", "Ophthalmology"}
    assert out["doctor_hint"] is None
    assert out["action"] == "specialty_direct"
    assert out["selected_option_id"] is None


def test_enrich_drops_carried_doctor_when_only_specialty_spoken():
    """Prod: 'كمان عايز أحجز أعصاب' + doctor_hint=كريم → specialty only."""
    dept = SimpleNamespace(department_id=2, name_ar="أعصاب", name_en="Neurology")
    with (
        patch.object(voice_fastpath, "find_doctor_by_hint", return_value=None),
        patch.object(voice_fastpath.doctor_service, "find_department", return_value=dept),
        patch.object(
            voice_fastpath.doctor_service,
            "infer_department_from_text",
            return_value=dept,
        ),
    ):
        out = voice_fastpath._enrich_result(
            MagicMock(),
            {
                "transcript": "كمان عايز أهجز نعرف كمان أعصاب",
                "action": "specialty_direct",
                "intent": "book",
                "doctor_hint": "كريم شريف",
                "specialty_hint": "أعصاب",
                "date_hint": "2026-07-28",
                "confidence": 0.8,
            },
        )
    assert out["doctor_hint"] is None
    assert out["specialty_hint"] in {"أعصاب", "Neurology"}
    assert out["action"] == "specialty_direct"


def test_known_patient_confirm_specialty_restarts_doctor_list():
    """Must not keep cardiologist slots when patient asks for neurology."""
    from app.db.enums import ConversationState

    sess = {
        "awaiting": "known_patient_confirm",
        "doctor_id": 3,
        "department_id": 1,
        "slot_id": 70,
        "last_options": [],
    }
    conversation = SimpleNamespace(state=ConversationState.PATIENT_DETAILS)
    restarted: list[dict] = []

    with (
        patch.object(voice_fastpath, "_sess", return_value=sess),
        patch.object(
            voice_fastpath,
            "_restart_doctor_picker",
            side_effect=lambda db, **kw: restarted.append(kw["result"]) or True,
        ),
        patch.object(
            voice_fastpath.doctor_service,
            "infer_department_from_text",
            return_value=SimpleNamespace(department_id=2, name_ar="أعصاب"),
        ),
        patch.object(voice_fastpath, "try_voice_book_direct", return_value=False),
    ):
        handled = voice_fastpath.try_voice_midflow(
            MagicMock(),
            phone="2010",
            result={
                "transcript": "كمان عايز أحجز أعصاب",
                "action": "specialty_direct",
                "intent": "book",
                "specialty_hint": "أعصاب",
                "doctor_hint": None,
                "confidence": 0.8,
            },
            conversation=conversation,
        )
    assert handled is True
    assert len(restarted) == 1
    assert restarted[0]["specialty_hint"] == "أعصاب"


def test_doctor_step_with_date_skips_day_picker():
    """'كريم يوم الثلاثة الساعة 5' must call continue_with hints, not bare continue."""
    from app.db.enums import ConversationState

    sess = {"awaiting": "doctor", "department_id": 1, "last_options": []}
    conversation = SimpleNamespace(state=ConversationState.BOOKING_DOCTOR)
    doctor = SimpleNamespace(doctor_id=3, name_ar="د. كريم", name_en="Dr K", department_id=1)
    calls: list[dict] = []

    with (
        patch.object(voice_fastpath, "_sess", return_value=sess),
        patch.object(voice_fastpath, "find_doctor_by_hint", return_value=doctor),
        patch.object(
            voice_fastpath,
            "_continue_booking_with_doctor",
            side_effect=lambda db, **kw: calls.append(kw) or True,
        ),
    ):
        handled = voice_fastpath.try_voice_midflow(
            MagicMock(),
            phone="2010",
            result={
                "transcript": "د. كريم شريف يوم الثلاثة الساعة الخامسة",
                "action": "book_direct",
                "intent": "book",
                "doctor_hint": "كريم شريف",
                "date_hint": "2026-07-28",
                "time_hint": "17:00",
                "confidence": 0.95,
            },
            conversation=conversation,
        )
    assert handled is True
    assert len(calls) == 1
    assert calls[0]["doctor"].doctor_id == 3
    assert calls[0]["result"]["date_hint"] == "2026-07-28"
    assert calls[0]["result"]["time_hint"] == "17:00"


def test_continue_booking_skips_to_slots_when_day_available():
    doctor = SimpleNamespace(doctor_id=3, name_ar="د. كريم", name_en="K", department_id=1)
    sess: dict = {"language": "ar"}
    conversation = SimpleNamespace(state=None, language="ar")
    day_slots = [{"slot_id": 70, "slot_start": "2026-07-28T17:00:00"}]
    offered: list[str] = []

    with (
        patch.object(voice_fastpath, "_sess", return_value=sess),
        patch.object(voice_fastpath, "wa", MagicMock()),
        patch.object(voice_fastpath.booking_service, "release_expired_holds"),
        patch.object(
            voice_fastpath.booking_service,
            "get_available_dates_and_slots",
            return_value={"dates": {"2026-07-28": day_slots}},
        ),
        patch.object(voice_fastpath, "match_slot", return_value=None),
        patch.object(
            voice_fastpath, "resolve_date_key", return_value="2026-07-28"
        ),
        patch(
            "app.services.conversation_service.set_conversation_state",
            MagicMock(),
        ),
        patch(
            "app.graph.conversation_engine._offer_list",
            side_effect=lambda *a, **k: offered.append("slots"),
        ),
        patch("app.graph.conversation_engine._date_option_title", return_value="Tue"),
        patch("app.graph.conversation_engine._slot_rows_with_change_day", return_value=[]),
        patch("app.graph.conversation_engine._lang", return_value="ar"),
    ):
        ok = voice_fastpath._continue_booking_with_doctor(
            MagicMock(),
            phone="2010",
            conversation=conversation,
            doctor=doctor,
            result={
                "transcript": "يوم الثلاثة الساعة الخامسة",
                "date_hint": "2026-07-28",
                "time_hint": "17:00",
            },
        )
    assert ok is True
    assert offered == ["slots"]
    assert sess["awaiting"] == "slot"
    assert sess["selected_date"] == "2026-07-28"


def test_doctor_step_specialty_wins_over_stale_option():
    """'خلينا دكتور عيون' at awaiting=doctor must open ophthalmology, not doctor_14."""
    from app.db.enums import ConversationState

    sess = {
        "awaiting": "doctor",
        "department_id": 1,  # currently showing another specialty
        "last_options": [
            {"id": "doctor_14", "title": "د. سارة"},
            {"id": "doctor_15", "title": "د. أحمد"},
        ],
    }
    conversation = SimpleNamespace(state=ConversationState.BOOKING_DOCTOR)
    dept = SimpleNamespace(department_id=9, name_ar="عيون", name_en="Ophthalmology")
    switched: list[int] = []
    dispatched: list[str] = []

    def _fake_switch(db, *, phone, sess, dept):
        switched.append(dept.department_id)
        return True

    def _fake_dispatch(db, phone, *, text="", payload_id=None):
        dispatched.append(payload_id or text)
        return True

    with (
        patch.object(voice_fastpath, "_sess", return_value=sess),
        patch.object(voice_fastpath, "find_doctor_by_hint", return_value=None),
        patch.object(
            voice_fastpath, "_resolve_specialty_department", return_value=dept
        ),
        patch.object(
            voice_fastpath.doctor_service,
            "infer_department_from_text",
            return_value=dept,
        ),
        patch.object(
            voice_fastpath, "_show_specialty_doctors_midflow", side_effect=_fake_switch
        ),
        patch.object(voice_fastpath, "_dispatch", side_effect=_fake_dispatch),
    ):
        handled = voice_fastpath.try_voice_midflow(
            MagicMock(),
            phone="2010",
            result={
                "transcript": "طب لا، خلينا دكتور عيون",
                "action": "specialty_direct",
                "intent": "book",
                "specialty_hint": "عيون",
                "doctor_hint": None,
                "selected_option_id": "doctor_14",
                "confidence": 0.9,
            },
            conversation=conversation,
        )
    assert handled is True
    assert switched == [9]
    assert dispatched == [], "must not fall through to doctor_14"
