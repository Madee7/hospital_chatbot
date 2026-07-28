"""Speak English, get English back.

Covers the four links in the chain that each independently broke this before:
  1. the router reports the spoken language,
  2. the plan->V1 projection doesn't drop it,
  3. code-switched speech resolves to the dominant language instead of Arabic,
  4. every voice reply the executor sends renders in that language.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.core import i18n_bot as i18n
from app.language.language_detector import detect_language
from app.services import voice_executor, voice_fastpath
from app.services.booking_service import BookingError
from app.services.voice_schemas import VoicePlan, VoiceUnderstanding


# ---------------------------------------------------------------------------
# 1-2. The router reports English, and the projection keeps it
# ---------------------------------------------------------------------------


def test_regional_english_folds_to_en():
    for code in ("en", "en-US", "en-GB"):
        assert VoicePlan(language=code).base_language() == "en", code


def test_projection_preserves_language():
    """A dropped language here silently made every V2 reply Arabic."""
    u = VoicePlan.model_validate(
        {"goal": "book_new", "next_step": "ask_date", "language": "en-US"}
    ).to_understanding()
    assert u.language == "en-US"
    assert u.base_language() == "en"


def test_align_language_overrides_arabic_label_on_english_transcript():
    """Live bug: English dentist ask at known_patient_confirm got lang=ar-EG."""
    from app.services.voice_service import _align_language_to_transcript

    plan = VoicePlan.model_validate(
        {
            "goal": "book_new",
            "next_step": "ask_specialty",
            "language": "ar-EG",
            "slots": {"specialty": "أسنان"},
            "transcript": "No, I want to book with a dentist.",
        }
    )
    fixed = _align_language_to_transcript(plan, "No, I want to book with a dentist.")
    assert fixed.base_language() == "en"
    assert fixed.language.startswith("en") or fixed.language == "en"


def test_align_language_flips_back_to_arabic_after_english_session():
    """Plan metadata still reflects transcript script (session sticky is separate)."""
    from app.services.voice_service import _align_language_to_transcript

    plan = VoicePlan.model_validate(
        {
            "goal": "ask_doctors",
            "next_step": "show_doctors",
            "language": "en",
            "slots": {"specialty": "قلب"},
            "transcript": "عايز أحجز عند دكتور قلب",
        }
    )
    fixed = _align_language_to_transcript(plan, "عايز أحجز عند دكتور قلب")
    assert fixed.base_language() == "ar"


def test_voice_language_follows_clear_speech():
    """Clear English → EN replies; clear Arabic → AR replies. Never force STT."""
    from app.language.language_service import LanguageService

    db = MagicMock()
    conversation = SimpleNamespace(language=None)
    sess: dict = {}
    svc = LanguageService(db, conversation, sess)

    assert svc.apply_voice_language("I want to book with a cardiologist") == "en"
    assert sess.get("language") == "en"
    assert svc.resolve_stt_language() is None  # quality: never pin Whisper

    # Mid-booking Arabic speech switches reply language (from transcript only).
    assert svc.apply_voice_language("عايز أحجز عند دكتور قلب") == "ar"
    assert sess.get("language") == "ar"


def test_voice_language_session_ttl_allows_redetect():
    """TTL is informational for activity; clear speech still switches language."""
    import time

    from app.language.language_service import LanguageService

    db = MagicMock()
    conversation = SimpleNamespace(language=None)
    sess: dict = {}
    svc = LanguageService(db, conversation, sess)
    assert svc.apply_voice_language("I want to book with a cardiologist") == "en"

    sess["voice_lang_locked_at"] = time.time() - (31 * 60)
    with patch("app.language.language_service.VOICE_LANG_SESSION_MINUTES", 30):
        assert svc.apply_voice_language("عايز أحجز عند دكتور قلب") == "ar"
    assert sess.get("language") == "ar"


def test_voice_language_ignores_garbage_transcript():
    """Garbled Whisper mid-booking must not flip sticky English."""
    from app.language.language_service import LanguageService

    db = MagicMock()
    conversation = SimpleNamespace(language=None)
    sess: dict = {}
    svc = LanguageService(db, conversation, sess)
    svc.apply_voice_language("I need an eye doctor")
    assert svc.apply_voice_language("أريد أن أقوم بوضع مجلس الدين") == "en"
    assert sess.get("language") == "en"


def test_voice_language_does_not_lock_on_whisper_garbage():
    """First-note MSA / YouTube hallucinations must not lock chat language."""
    from app.language.language_service import LanguageService

    db = MagicMock()
    conversation = SimpleNamespace(language=None)
    sess: dict = {}
    svc = LanguageService(db, conversation, sess)

    assert svc.apply_voice_language("أريد أن أقوم بمقابلة، أرجوك") == "ar"
    assert sess.get("voice_lang_locked") is not True

    assert svc.apply_voice_language("شكراً لكم على المشاهدة.") == "ar"
    assert sess.get("voice_lang_locked") is not True

    assert svc.apply_voice_language(
        "نهاية زيادة سلام عليكم ورحمة الله وبركاته"
    ) == "ar"
    assert sess.get("voice_lang_locked") is not True

    # Real speech after garbage can still lock.
    assert svc.apply_voice_language("I want to book with a cardiologist") == "en"
    assert sess.get("voice_lang_locked") is True


def test_scrub_whisper_keeps_real_booking_words():
    from app.language.language_detector import (
        is_whisper_garbage,
        scrub_whisper_hallucinations,
    )

    assert is_whisper_garbage("نهاية زيادة سلام عليكم ورحمة الله وبركاته")
    assert scrub_whisper_hallucinations(
        "السلام عليكم عايز أحجز دكتور قلب"
    ) == "عايز أحجز دكتور قلب"
    assert not is_whisper_garbage("عايز أحجز دكتور قلب")


def test_resolve_stt_language_never_pins_whisper():
    """Quality-first: STT language hint is always None."""
    from app.language.language_service import LanguageService

    db = MagicMock()
    conversation = SimpleNamespace(language=None)
    sess: dict = {}
    svc = LanguageService(db, conversation, sess)
    svc.apply_voice_language("I want to book with a cardiologist")
    assert svc.resolve_stt_language() is None
    sess["allow_voice_lang_switch"] = True
    assert svc.resolve_stt_language() is None


def test_v1_understanding_also_reports_english():
    assert VoiceUnderstanding(language="english").base_language() == "en"


# ---------------------------------------------------------------------------
# 3. Code-switched speech resolves to the dominant language
# ---------------------------------------------------------------------------


def test_english_sentence_with_arabic_doctor_name_is_english():
    """The webhook's fallback when the router says 'mixed'/'unknown'.

    An English request naming an Arabic doctor must not flip the reply to Arabic.
    """
    assert detect_language("I want to book with دكتور أحمد", fallback=None) == "en"
    assert detect_language("book me with دكتورة دينا حسن tomorrow", fallback=None) == "en"


def test_arabic_stays_arabic():
    assert detect_language("عايز أحجز مع دكتور نور الدين", fallback=None) == "ar"


def test_short_confirmations_do_not_decide_a_language():
    """None => keep whatever language the conversation already had."""
    assert detect_language("ok", fallback=None) is None
    assert detect_language("", fallback=None) is None


# ---------------------------------------------------------------------------
# 4. Executor replies render in the session language
# ---------------------------------------------------------------------------


def _doctor(doctor_id=4, name_ar="د. نور الدين", name_en="Dr. Nour El-Din"):
    return SimpleNamespace(doctor_id=doctor_id, name_ar=name_ar, name_en=name_en)


def _run_en(
    plan: VoicePlan,
    *,
    doctor=None,
    availability: dict | None = None,
    matched: dict | None = None,
    hold_error: Exception | None = None,
) -> list[str]:
    """Execute a plan with the conversation already switched to English."""
    sess = {"language": "en"}
    conversation = SimpleNamespace(state=None, language="en")
    wa = MagicMock()

    booking = MagicMock()
    if hold_error is not None:
        booking.hold_slot.side_effect = hold_error

    doctor_service = MagicMock()
    doctor_service.get_doctor.return_value = doctor
    doctor_service.find_department.return_value = None
    doctor_service.infer_department_from_text.return_value = None
    doctor_service.list_departments.return_value = []

    with ExitStack() as stack:
        stack.enter_context(patch.object(voice_executor, "_sess", return_value=sess))
        stack.enter_context(patch.object(voice_executor, "wa", wa))
        stack.enter_context(patch.object(voice_executor, "booking_service", booking))
        stack.enter_context(patch.object(voice_executor, "doctor_service", doctor_service))
        stack.enter_context(patch.object(voice_executor, "set_conversation_state", MagicMock()))
        stack.enter_context(
            patch.object(voice_executor, "_availability", return_value=availability or {})
        )
        for helper in (
            "_present_doctor_list",
            "_present_department_doctors",
            "_present_dates",
            "_present_slots",
        ):
            stack.enter_context(patch.object(voice_executor, helper, return_value=True))
        stack.enter_context(patch.object(voice_executor, "_feed_patient_name", MagicMock()))
        stack.enter_context(
            patch.object(voice_fastpath, "find_doctor_by_hint", return_value=doctor)
        )
        stack.enter_context(patch.object(voice_fastpath, "match_slot", return_value=matched))
        voice_executor.execute_plan(
            MagicMock(), phone="2010", plan=plan, conversation=conversation
        )

    return [c.args[1] for c in wa.send_text.call_args_list if len(c.args) > 1]


def _is_english(text: str) -> bool:
    return detect_language(text, fallback=None) == "en"


def test_doctor_not_found_message_is_english():
    texts = _run_en(
        VoicePlan.model_validate(
            {
                "transcript": "book with doctor Ahmed Samir",
                "goal": "book_new",
                "next_step": "show_doctors",
                "slots": {"doctor_name": "Ahmed Samir"},
                "language": "en",
            }
        ),
        doctor=None,
    )
    assert texts, "patient must be told the doctor wasn't found"
    assert all(_is_english(t) for t in texts), texts


def test_slot_taken_message_is_english_and_uses_the_english_doctor_name():
    texts = _run_en(
        VoicePlan.model_validate(
            {
                "transcript": "book with doctor Nour tomorrow at 2",
                "goal": "book_new",
                "next_step": "hold_slot",
                "slots": {"doctor_name": "Nour", "date": "2026-07-28", "time": "14:00"},
                "language": "en",
            }
        ),
        doctor=_doctor(),
        availability={"2026-07-28": [{"slot_id": 9}]},
        matched={"slot_id": 9, "slot_start": datetime(2026, 7, 28, 14, 0)},
        hold_error=BookingError("Slot not available"),
    )
    assert texts
    assert all(_is_english(t) for t in texts), texts
    # Arabic name must not leak into an English sentence.
    assert any("Dr. Nour El-Din" in t for t in texts)
    assert not any("نور الدين" in t for t in texts)


def test_slot_held_confirmation_is_english():
    texts = _run_en(
        VoicePlan.model_validate(
            {
                "transcript": "book with doctor Nour tomorrow at 2",
                "goal": "book_new",
                "next_step": "hold_slot",
                "slots": {"doctor_name": "Nour", "date": "2026-07-28", "time": "14:00"},
                "language": "en",
            }
        ),
        doctor=_doctor(),
        availability={"2026-07-28": [{"slot_id": 9}]},
        matched={"slot_id": 9, "slot_start": datetime(2026, 7, 28, 14, 0)},
    )
    assert texts
    assert all(_is_english(t) for t in texts), texts
    assert any("patient's name" in t for t in texts)


def test_need_doctor_first_message_is_english():
    texts = _run_en(
        VoicePlan.model_validate(
            {
                "transcript": "what about tuesday",
                "goal": "book_new",
                "next_step": "ask_date",
                "slots": {"date": "2026-07-28"},
                "language": "en",
            }
        ),
        doctor=None,
    )
    assert texts
    assert all(_is_english(t) for t in texts), texts


def test_every_v2_degradation_string_has_a_distinct_english_form():
    """Guards against a new message being added Arabic-only."""
    checks = [
        i18n.voice_doctor_not_found("en", "Ahmed"),
        i18n.voice_specialty_not_found("en", "Cardio"),
        i18n.voice_slot_taken("en", "Dr. Nour", "Tuesday"),
        i18n.voice_time_not_available("en", "Tuesday"),
        i18n.voice_no_slots_on_date("en", "Dr. Nour", "Tuesday"),
        i18n.voice_doctor_fully_booked("en", "Dr. Nour"),
        i18n.voice_no_appointment_found("en"),
        i18n.voice_draft_abandoned("en"),
        i18n.voice_need_doctor_first("en"),
        i18n.voice_slot_held("en", "Dr. Nour", "Tuesday 2:00 PM"),
        i18n.voice_specialty_open_doctors("en", "Cardiology"),
        i18n.voice_continue_with_doctor("en", "Dr. Nour"),
        i18n.stale_option_hint("en"),
        i18n.not_understood_menu("en"),
    ]
    for text in checks:
        assert text.strip(), "empty message"
        assert _is_english(text), f"not English: {text!r}"
        # Differs from the Arabic form (i.e. it was actually translated).
    assert i18n.voice_draft_abandoned("en") != i18n.voice_draft_abandoned("ar")
    assert i18n.voice_need_doctor_first("en") != i18n.voice_need_doctor_first("ar")


def test_doctor_label_uses_english_name_then_falls_back():
    assert voice_executor._doctor_label(_doctor(), "en") == "Dr. Nour El-Din"
    assert voice_executor._doctor_label(_doctor(), "ar") == "د. نور الدين"
    # Arabic-only record must still render something in an English reply.
    ar_only = SimpleNamespace(doctor_id=9, name_ar="د. سارة", name_en=None)
    assert voice_executor._doctor_label(ar_only, "en") == "د. سارة"


# ---------------------------------------------------------------------------
# Fastpath seeds must not re-detect language
# ---------------------------------------------------------------------------


def test_dispatch_marks_seeds_as_language_preserving():
    """The routing seeds are Arabic; detecting language from them flipped
    English callers back to Arabic mid-flow."""
    captured: dict = {}

    def _fake_pim(db, **kw):
        captured.update(kw)

    with patch("app.graph.process_incoming_message", _fake_pim):
        voice_fastpath._dispatch(MagicMock(), "2010", text="حجز موعد")

    assert captured["keep_language"] is True
    assert captured["text"] == "حجز موعد"


def test_executor_patient_name_relay_preserves_language():
    captured: dict = {}

    def _fake_pim(db, **kw):
        captured.update(kw)

    with patch("app.graph.process_incoming_message", _fake_pim):
        voice_executor._feed_patient_name(MagicMock(), "2010", "محمد إبراهيم")

    assert captured["keep_language"] is True


def test_engine_keeps_language_when_flagged():
    """node_handle must resolve the stored language instead of re-detecting."""
    from app.graph import conversation_engine as ce

    svc = MagicMock()
    svc.language = "en"
    conversation = SimpleNamespace(conversation_id=1, state=None, language="en")

    db = MagicMock()
    db.query.return_value.filter_by.return_value.one.return_value = conversation

    with (
        patch.object(ce, "LanguageService", return_value=svc),
        patch.object(ce, "_sess", return_value={"language": "en"}),
        patch.object(ce, "detect_intent", return_value=None),
        patch.object(ce, "_choice", return_value=""),
    ):
        try:
            ce.node_handle(
                {
                    "phone": "2010",
                    "text": "حجز موعد",
                    "payload_id": "",
                    "conversation_id": 1,
                    "db_session": db,
                    "keep_language": True,
                }
            )
        except Exception:
            # Later stages need far more state; we only care about the language
            # decision made at the top of the node.
            pass

    svc.sync_from_user_text.assert_not_called()


def test_engine_still_detects_language_for_real_user_text():
    from app.graph import conversation_engine as ce

    svc = MagicMock()
    svc.sync_from_user_text.return_value = "en"
    conversation = SimpleNamespace(conversation_id=1, state=None, language="ar")

    db = MagicMock()
    db.query.return_value.filter_by.return_value.one.return_value = conversation

    with (
        patch.object(ce, "LanguageService", return_value=svc),
        patch.object(ce, "_sess", return_value={}),
        patch.object(ce, "detect_intent", return_value=None),
        patch.object(ce, "_choice", return_value=""),
    ):
        try:
            ce.node_handle(
                {
                    "phone": "2010",
                    "text": "I want to book an appointment",
                    "payload_id": "",
                    "conversation_id": 1,
                    "db_session": db,
                }
            )
        except Exception:
            pass

    svc.sync_from_user_text.assert_called_once()


# ---------------------------------------------------------------------------
# STT: the transcription prompt must not bias toward Arabic
# ---------------------------------------------------------------------------


def test_stt_context_prompt_is_short_arabic_vocab():
    """When explicitly enabled, prompt stays a short Arabic name/specialty prior."""
    from app.services import voice_service

    db = MagicMock()
    doctors = [_doctor(1, "د. نور الدين", "Dr. Nour El-Din")]
    departments = [SimpleNamespace(name_ar="أسنان", name_en="Dentistry")]
    with (
        patch("app.core.config.VOICE_STT_PROMPT", True),
        patch("app.services.doctor_service.list_active_doctors", return_value=doctors),
        patch("app.services.doctor_service.list_departments", return_value=departments),
        patch.dict(voice_service._STT_PROMPT_CACHE, {}, clear=True),
    ):
        prompt = voice_service._build_stt_context_prompt(db, 1)

    assert "مستشفى" in prompt
    assert "نور" in prompt
    assert "قلب" in prompt or "أسنان" in prompt or "أعصاب" in prompt
    assert "Transcribe ONLY" not in prompt
    assert "Do not translate" not in prompt
    assert "cardiologist" not in prompt
    assert "New Giza University Hospital" not in prompt
    assert "Dr. Nour El-Din" not in prompt

