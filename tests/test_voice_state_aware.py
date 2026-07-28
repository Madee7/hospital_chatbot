"""Voice state-aware routing: webhook gate, Whisper prompt, CURRENT_STEP, fallbacks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.api.routes import webhook
from app.core import i18n_bot as i18n
from app.services import voice_service


# ---------------------------------------------------------------------------
# Task E — targeted unclear templates
# ---------------------------------------------------------------------------


def test_voice_unclear_templates_by_awaiting():
    assert "وقت" in i18n.webhook_voice_unclear_slot("ar")
    assert "time" in i18n.webhook_voice_unclear_slot("en").lower()
    assert "دكتور" in i18n.webhook_voice_unclear_doctor("ar")
    assert "doctor" in i18n.webhook_voice_unclear_doctor("en").lower()
    assert "يوم" in i18n.webhook_voice_unclear_date("ar")
    assert "تخصص" in i18n.webhook_voice_unclear_department("ar")
    # Fresh conversation keeps generic copy
    assert "بوضوح" in i18n.webhook_voice_unclear("ar")


def test_voice_unclear_body_picks_awaiting_template():
    assert "وقت" in webhook._voice_unclear_body("ar", "slot")
    assert "دكتور" in webhook._voice_unclear_body("ar", "doctor")
    assert "يوم" in webhook._voice_unclear_body("ar", "date")
    assert "تخصص" in webhook._voice_unclear_body("ar", "department")
    assert "بوضوح" in webhook._voice_unclear_body("ar", None)


# ---------------------------------------------------------------------------
# Task C — CURRENT_STEP line
# ---------------------------------------------------------------------------


def test_current_step_line_for_slot_and_date():
    slot = voice_service._format_current_step_line(
        {
            "awaiting": "slot",
            "known_doctor": "د. منى محمد",
            "known_date": "2026-07-25",
        }
    )
    assert slot.startswith("CURRENT_STEP:")
    assert "time" in slot.lower()
    assert "منى" in slot or "Dr." in slot

    date_line = voice_service._format_current_step_line(
        {"awaiting": "date", "known_doctor": "د. منى محمد"}
    )
    assert "day" in date_line.lower()
    assert "منى" in date_line or "Dr." in date_line

    doctor_line = voice_service._format_current_step_line(
        {"awaiting": "doctor", "known_specialty": "قلب"}
    )
    assert "doctor" in doctor_line.lower()
    assert "قلب" in doctor_line


def test_current_step_line_absent_for_fresh_conversation():
    assert voice_service._format_current_step_line(None) == ""
    assert voice_service._format_current_step_line({}) == ""
    assert voice_service._format_current_step_line({"conv_state": "IDLE"}) == ""


# ---------------------------------------------------------------------------
# Task B — Whisper STT vocabulary prompt
# ---------------------------------------------------------------------------


def test_build_stt_context_prompt_from_doctors_and_departments():
    voice_service.clear_stt_prompt_cache()
    db = MagicMock()
    doc = SimpleNamespace(name_ar="د. منى محمد", name_en="Mona Mohamed")
    dept = SimpleNamespace(name_ar="قلب", name_en="Cardiology")
    with (
        patch("app.core.config.VOICE_STT_PROMPT", True),
        patch("app.services.doctor_service.list_active_doctors", return_value=[doc]),
        patch("app.services.doctor_service.list_departments", return_value=[dept]),
    ):
        prompt = voice_service._build_stt_context_prompt(db, clinic_id=1, now=1_000.0)
    assert "منى" in prompt or "Mona" in prompt
    assert "قلب" in prompt or "Cardiology" in prompt
    assert len(prompt) <= voice_service._STT_PROMPT_MAX_CHARS

    # Cache hit — second call must not re-query
    with (
        patch("app.core.config.VOICE_STT_PROMPT", True),
        patch("app.services.doctor_service.list_active_doctors") as list_docs,
        patch("app.services.doctor_service.list_departments") as list_depts,
    ):
        again = voice_service._build_stt_context_prompt(db, clinic_id=1, now=1_100.0)
    assert again == prompt
    list_docs.assert_not_called()
    list_depts.assert_not_called()


def test_build_stt_context_prompt_off_by_default():
    """Quality default: no Whisper prompt (matches early working path)."""
    voice_service.clear_stt_prompt_cache()
    db = MagicMock()
    with patch("app.core.config.VOICE_STT_PROMPT", False):
        assert voice_service._build_stt_context_prompt(db, clinic_id=1) == ""


def test_transcribe_ogg_passes_prompt_to_whisper():
    voice_service.clear_stt_prompt_cache()
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = SimpleNamespace(
        text="عايز دكتورة منى"
    )
    db = MagicMock()
    with (
        patch.object(voice_service, "_client", return_value=fake_client),
        patch.object(
            voice_service,
            "_build_stt_context_prompt",
            return_value="د. منى محمد، قلب",
        ),
        patch.object(voice_service, "_with_retries", side_effect=lambda _l, fn: fn()),
    ):
        text = voice_service._transcribe_ogg(b"ogg-bytes", db=db, clinic_id=1)
    assert text == "عايز دكتورة منى"
    kwargs = fake_client.audio.transcriptions.create.call_args.kwargs
    assert kwargs["prompt"] == "د. منى محمد، قلب"
    # Always auto-detect — never pin language (hurts Egyptian dialect).
    assert "language" not in kwargs


def test_transcribe_ogg_ignores_force_language():
    """force_language must not pin Whisper — live logs showed ar-force hallucinations."""
    voice_service.clear_stt_prompt_cache()
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = SimpleNamespace(
        text="عايز دكتور قلب"
    )
    with (
        patch.object(voice_service, "_client", return_value=fake_client),
        patch.object(voice_service, "_build_stt_context_prompt", return_value=""),
        patch.object(voice_service, "_with_retries", side_effect=lambda _l, fn: fn()),
    ):
        text = voice_service._transcribe_ogg(
            b"ogg-bytes", db=None, force_language="en"
        )
    assert text == "عايز دكتور قلب"
    kwargs = fake_client.audio.transcriptions.create.call_args.kwargs
    assert "language" not in kwargs


# ---------------------------------------------------------------------------
# Task D — webhook calls fastpath before unclear; clarify+hint can resolve
# ---------------------------------------------------------------------------


def _mock_conversation():
    return SimpleNamespace(conversation_id=1, state=None, language=None)


def test_webhook_clarify_with_doctor_hint_reaches_fastpath():
    """Regression: action=clarify must NOT short-circuit before smart_route."""
    result = {
        "transcript": "منى",
        "text": "منى",
        "action": "clarify",
        "intent": "book",
        "confidence": 0.55,
        "doctor_hint": "منى",
        "specialty_hint": None,
        "date_hint": None,
        "time_hint": None,
        "summary_ar": "",
        "selected_option_id": None,
        "stt_provider": "test",
    }
    db = MagicMock()
    sess = {"awaiting": "doctor", "last_options": []}

    with (
        patch.object(webhook, "SessionLocal", return_value=db),
        patch.object(webhook, "_phone_lang", return_value="ar"),
        patch.object(webhook, "_sess", return_value=sess),
        patch.object(webhook, "_voice_current_step", return_value={"awaiting": "doctor"}),
        patch.object(webhook, "get_or_create_conversation", return_value=_mock_conversation()),
        patch.object(webhook, "get_conversation_language", return_value="ar"),
        patch.object(webhook, "log_message", return_value=SimpleNamespace(message_id=9)),
        patch.object(webhook, "log_voice_metadata"),
        patch(
            "app.services.voice_service.route_whatsapp_voice_message",
            return_value=result,
        ),
        patch(
            "app.services.voice_fastpath.try_voice_smart_route",
            return_value=True,
        ) as smart,
        patch("app.services.whatsapp_client.send_text") as send_text,
    ):
        webhook._handle_voice("201000000000", "media-1")

    smart.assert_called_once()
    send_text.assert_not_called()


def test_webhook_clarify_without_match_uses_targeted_fallback():
    result = {
        "transcript": "هممم",
        "text": "هممم",
        "action": "clarify",
        "intent": "unknown",
        "confidence": 0.2,
        "doctor_hint": None,
        "specialty_hint": None,
        "date_hint": None,
        "time_hint": None,
        "summary_ar": "",
        "selected_option_id": None,
        "stt_provider": "test",
    }
    options = [
        {"id": "slot_1", "title": "02:00 PM", "description": ""},
        {"id": "slot_2", "title": "04:00 PM", "description": ""},
    ]
    db = MagicMock()
    sess = {"awaiting": "slot", "last_options": options}

    with (
        patch.object(webhook, "SessionLocal", return_value=db),
        patch.object(webhook, "_phone_lang", return_value="ar"),
        patch.object(webhook, "_sess", return_value=sess),
        patch.object(
            webhook,
            "_voice_current_step",
            return_value={"awaiting": "slot", "known_doctor": "منى"},
        ),
        patch.object(webhook, "get_or_create_conversation", return_value=_mock_conversation()),
        patch.object(webhook, "get_conversation_language", return_value="ar"),
        patch.object(webhook, "log_message", return_value=SimpleNamespace(message_id=9)),
        patch.object(webhook, "log_voice_metadata"),
        patch(
            "app.services.voice_service.route_whatsapp_voice_message",
            return_value=result,
        ),
        patch(
            "app.services.voice_fastpath.try_voice_smart_route",
            return_value=False,
        ),
        patch("app.services.whatsapp_client.send_buttons") as send_buttons,
        patch("app.services.whatsapp_client.send_text") as send_text,
    ):
        webhook._handle_voice("201000000000", "media-2")

    send_buttons.assert_called_once()
    body = send_buttons.call_args.args[1]
    assert "وقت" in body
    send_text.assert_not_called()


def test_fastpath_clarify_with_doctor_hint_still_books():
    """clarify label must not veto book_direct when intent+hint+conf pass."""
    from app.services import voice_fastpath

    db = MagicMock()
    doctor = SimpleNamespace(
        doctor_id=7,
        name_ar="د. منى محمد",
        name_en="Mona",
    )
    result = {
        "action": "clarify",
        "intent": "book",
        "confidence": 0.66,
        "doctor_hint": "منى",
        "date_hint": None,
        "time_hint": None,
        "transcript": "عايز أحجز عند منى",
    }
    with (
        patch.object(voice_fastpath, "find_doctor_by_hint", return_value=doctor),
        patch.object(
            voice_fastpath,
            "get_or_create_conversation",
            return_value=_mock_conversation(),
        ),
        patch.object(voice_fastpath, "_sess", return_value={}),
        patch.object(
            voice_fastpath.booking_service,
            "release_expired_holds",
        ),
        patch.object(
            voice_fastpath.booking_service,
            "get_available_dates_and_slots",
            return_value={"dates": {}},
        ),
        patch.object(voice_fastpath.wa, "send_text"),
        patch(
            "app.graph.conversation_engine.continue_after_doctor_selected"
        ) as cont,
    ):
        ok = voice_fastpath.try_voice_book_direct(db, phone="2010", result=result)
    assert ok is True
    cont.assert_called_once()


# ---------------------------------------------------------------------------
# Flow switch during a free-text step (name / MRN / DOB)
# ---------------------------------------------------------------------------


def test_voice_wants_flow_switch_detection():
    from app.services import voice_fastpath as vf

    # New reservation voiced during name entry → switch
    assert vf.voice_wants_flow_switch(
        {"action": "book_direct", "intent": "book", "confidence": 0.9}
    )
    assert vf.voice_wants_flow_switch(
        {"action": "specialty_direct", "intent": "book", "confidence": 0.7}
    )
    assert vf.voice_wants_flow_switch(
        {"action": "intent", "intent": "cancel", "confidence": 0.8}
    )
    # An actual name answer → NOT a switch
    assert not vf.voice_wants_flow_switch(
        {"action": "clarify", "intent": "unknown", "confidence": 0.2}
    )
    assert not vf.voice_wants_flow_switch(
        {"action": "intent", "intent": "unknown", "confidence": 0.0}
    )
    # Low-confidence intent → don't yank the patient out of name entry
    assert not vf.voice_wants_flow_switch(
        {"action": "intent", "intent": "book", "confidence": 0.4}
    )


def test_webhook_name_step_new_booking_switches_flow_not_name_capture():
    """Voicing a new reservation while awaiting name must NOT be stored as the
    name; it should fall through to the router to switch flows."""
    result = {
        "transcript": "عايز أحجز مع دكتور نور الدين يوم الثلاثاء",
        "text": "عايز أحجز مع دكتور نور الدين يوم الثلاثاء",
        "action": "book_direct",
        "intent": "book",
        "confidence": 0.9,
        "doctor_hint": "نور الدين",
        "specialty_hint": None,
        "date_hint": "2026-07-28",
        "time_hint": None,
        "summary_ar": "",
        "selected_option_id": None,
        "stt_provider": "test",
    }
    db = MagicMock()
    sess = {"awaiting": "patient_name", "last_options": []}

    with (
        patch.object(webhook, "SessionLocal", return_value=db),
        patch.object(webhook, "_phone_lang", return_value="ar"),
        patch.object(webhook, "_sess", return_value=sess),
        patch.object(webhook, "_voice_current_step", return_value={"awaiting": "patient_name"}),
        patch.object(webhook, "get_or_create_conversation", return_value=_mock_conversation()),
        patch.object(webhook, "get_conversation_language", return_value="ar"),
        patch.object(webhook, "log_message", return_value=SimpleNamespace(message_id=9)),
        patch.object(webhook, "log_voice_metadata"),
        patch.object(webhook, "process_incoming_message") as pim,
        patch(
            "app.services.voice_service.route_whatsapp_voice_message",
            return_value=result,
        ),
        patch(
            "app.services.voice_fastpath.try_voice_smart_route",
            return_value=True,
        ) as smart,
    ):
        webhook._handle_voice("201000000000", "media-3")

    # The transcript was NOT captured as the patient name...
    pim.assert_not_called()
    # ...instead the router got a chance to switch flows.
    smart.assert_called_once()


def test_webhook_name_step_plain_name_is_captured():
    """A genuine name answer at the name step is still forwarded as the name."""
    result = {
        "transcript": "أحمد محمد علي",
        "text": "أحمد محمد علي",
        "action": "clarify",
        "intent": "unknown",
        "confidence": 0.2,
        "doctor_hint": None,
        "specialty_hint": None,
        "date_hint": None,
        "time_hint": None,
        "summary_ar": "",
        "selected_option_id": None,
        "stt_provider": "test",
    }
    db = MagicMock()
    sess = {"awaiting": "patient_name", "last_options": []}

    with (
        patch.object(webhook, "SessionLocal", return_value=db),
        patch.object(webhook, "_phone_lang", return_value="ar"),
        patch.object(webhook, "_sess", return_value=sess),
        patch.object(webhook, "_voice_current_step", return_value={"awaiting": "patient_name"}),
        patch.object(webhook, "get_or_create_conversation", return_value=_mock_conversation()),
        patch.object(webhook, "get_conversation_language", return_value="ar"),
        patch.object(webhook, "log_message", return_value=SimpleNamespace(message_id=9)),
        patch.object(webhook, "log_voice_metadata"),
        patch.object(webhook, "process_incoming_message") as pim,
        patch(
            "app.services.voice_service.route_whatsapp_voice_message",
            return_value=result,
        ),
        patch(
            "app.services.voice_fastpath.try_voice_smart_route",
            return_value=True,
        ) as smart,
    ):
        webhook._handle_voice("201000000000", "media-4")

    # Captured as the name via the text engine; router not consulted.
    pim.assert_called_once()
    assert pim.call_args.kwargs.get("text") == "أحمد محمد علي"
    smart.assert_not_called()
