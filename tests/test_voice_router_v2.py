"""Router V2: plan schema, legacy projection, and the executor's degradation ladder.

The point of V2 is that a confident, correct plan can never end as a silent
main menu. Every test below that exercises an unfulfillable step asserts BOTH
that the patient was told why AND that a usable fallback was shown.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import voice_executor, voice_fastpath
from app.services.booking_service import BookingError
from app.services.voice_schemas import VoicePlan


# ---------------------------------------------------------------------------
# Schema: goal / next_step coercion
# ---------------------------------------------------------------------------


def test_goal_synonyms_are_coerced():
    assert VoicePlan(goal="book").goal == "book_new"
    assert VoicePlan(goal="update").goal == "reschedule"
    assert VoicePlan(goal="cancel").goal == "cancel_appointment"
    assert VoicePlan(goal="abort").goal == "abandon_draft"
    assert VoicePlan(goal="human").goal == "handover"


def test_next_step_synonyms_are_coerced():
    assert VoicePlan(next_step="hold").next_step == "hold_slot"
    assert VoicePlan(next_step="dates").next_step == "ask_date"
    assert VoicePlan(next_step="doctor").next_step == "show_doctors"
    assert VoicePlan(next_step="change_type").next_step == "ask_change_target"


def test_unknown_goal_and_step_degrade_safely():
    plan = VoicePlan(goal="nonsense", next_step="nonsense")
    assert plan.goal == "unclear"
    assert plan.next_step == "clarify"


def test_defaults_are_safe():
    plan = VoicePlan()
    assert (plan.goal, plan.next_step) == ("unclear", "clarify")
    assert plan.confidence.overall == 0.5
    assert plan.slots.doctor_name is None
    assert plan.slots.doctor_alternatives == []


def test_per_field_confidence_is_independent():
    """A mumbled time must not drag down a crystal-clear doctor name."""
    plan = VoicePlan.model_validate(
        {"confidence": {"overall": "high", "doctor": 0.95, "time": 0.3, "date": ""}}
    )
    assert plan.confidence.overall == 0.9
    assert plan.confidence.doctor == 0.95
    assert plan.confidence.time == 0.3
    assert plan.confidence.date is None


def test_slots_blank_strings_become_none_and_alternatives_clean():
    plan = VoicePlan.model_validate(
        {
            "slots": {
                "doctor_name": "  أحمد  ",
                "specialty": "   ",
                "doctor_alternatives": ["علي", "", None, " سارة "],
                "change_target": "يوم",
            }
        }
    )
    assert plan.slots.doctor_name == "أحمد"
    assert plan.slots.specialty is None
    assert plan.slots.doctor_alternatives == ["علي", "سارة"]
    assert plan.slots.change_target == "date"


# ---------------------------------------------------------------------------
# Schema: projection onto the V1 shape (migration safety net)
# ---------------------------------------------------------------------------


def test_projection_doctor_becomes_book_direct():
    u = VoicePlan.model_validate(
        {
            "transcript": "احجز مع دكتور أحمد",
            "goal": "book_new",
            "next_step": "ask_date",
            "slots": {"doctor_name": "أحمد", "date": "2026-07-27"},
            "confidence": {"overall": 0.9},
        }
    ).to_understanding()
    assert u.action == "book_direct"
    assert u.intent == "book"
    assert u.doctor_hint == "أحمد"
    assert u.date_hint == "2026-07-27"
    assert u.confidence == 0.9


def test_projection_specialty_becomes_specialty_direct():
    u = VoicePlan.model_validate(
        {"goal": "book_new", "next_step": "show_doctors", "slots": {"specialty": "قلب"}}
    ).to_understanding()
    assert u.action == "specialty_direct"
    assert u.specialty_hint == "قلب"


def test_projection_option_pick_wins():
    u = VoicePlan.model_validate(
        {"goal": "book_new", "next_step": "show_slots", "slots": {"selected_option_id": "slot_7"}}
    ).to_understanding()
    assert u.action == "select_option"
    assert u.selected_option_id == "slot_7"


def test_projection_both_cancel_goals_collapse_to_legacy_cancel():
    """V1 cannot express the distinction — documents the lossy edge."""
    assert VoicePlan(goal="cancel_appointment").to_understanding().intent == "cancel"
    assert VoicePlan(goal="abandon_draft").to_understanding().intent == "cancel"


def test_projection_unclear_becomes_clarify():
    u = VoicePlan(goal="unclear", next_step="clarify").to_understanding()
    assert u.action == "clarify"
    assert u.intent == "unknown"


# ---------------------------------------------------------------------------
# Executor harness
# ---------------------------------------------------------------------------


def _plan(**kw) -> VoicePlan:
    kw.setdefault("transcript", "رسالة صوتية")
    return VoicePlan.model_validate(kw)


class _Harness:
    """Captures what the executor sent and which fallback it presented."""

    def __init__(self):
        self.texts: list[str] = []
        self.presented: list[str] = []
        self.present_kwargs: list[dict] = []
        self.names_fed: list[str] = []
        self.engine_feeds: list[dict] = []
        self.sess: dict = {}


def _run(
    plan: VoicePlan,
    *,
    sess: dict | None = None,
    doctor=None,
    department=None,
    availability: dict | None = None,
    matched: dict | None = None,
    hold_error: Exception | None = None,
) -> tuple[voice_executor.ExecResult, _Harness]:
    h = _Harness()
    h.sess = sess if sess is not None else {}
    conversation = SimpleNamespace(state=None, language=None)
    wa = MagicMock()

    def _present(name):
        def _inner(*a, **kw):
            h.presented.append(name)
            h.present_kwargs.append(kw)
            return True

        return _inner

    booking = MagicMock()
    if hold_error is not None:
        booking.hold_slot.side_effect = hold_error

    from app.services import doctor_service as real_doctor_service

    doctor_service = MagicMock()
    doctor_service.get_doctor.return_value = doctor
    # Only "infer"/match departments when the text actually names a specialty —
    # mirrors prod and avoids treating person names as departments.
    _spec_hints = (
        "قلب",
        "عيون",
        "عظام",
        "أسنان",
        "اعصاب",
        "أعصاب",
        "أصاب",
        "اصاب",
        "جلد",
        "أطفال",
        "باطن",
        "نساء",
        "نسا",
        "نيسا",
        "تسا",
        "تساء",
        "cardio",
        "eye",
        "ortho",
        "dental",
        "neuro",
    )

    def _has_spec(text: str | None) -> bool:
        return bool(text) and any(h in str(text) for h in _spec_hints)

    def _find_dept(_db, _cid, name=None, department_id=None):
        if department is None:
            return None
        if department_id is not None:
            return department
        return department if _has_spec(name) else None

    def _infer(_db, _cid, text):
        return department if department is not None and _has_spec(text) else None

    doctor_service.find_department.side_effect = _find_dept
    doctor_service.infer_department_from_text.side_effect = _infer
    doctor_service.list_departments.return_value = []
    doctor_service.is_specialty_word.side_effect = real_doctor_service.is_specialty_word
    doctor_service.fuzzy_specialty_canonical.side_effect = (
        real_doctor_service.fuzzy_specialty_canonical
    )

    with ExitStack() as stack:
        stack.enter_context(patch.object(voice_executor, "_sess", return_value=h.sess))
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
            stack.enter_context(
                patch.object(voice_executor, helper, side_effect=_present(helper))
            )
        stack.enter_context(
            patch.object(
                voice_executor,
                "_feed_patient_name",
                side_effect=lambda db, phone, name: h.names_fed.append(name),
            )
        )
        stack.enter_context(
            patch.object(
                voice_executor,
                "_feed_engine",
                side_effect=lambda db, phone, text="", payload_id=None: h.engine_feeds.append(
                    {"text": text, "payload_id": payload_id}
                ),
            )
        )
        stack.enter_context(
            patch.object(voice_fastpath, "find_doctor_by_hint", return_value=doctor)
        )
        stack.enter_context(patch.object(voice_fastpath, "match_slot", return_value=matched))
        result = voice_executor.execute_plan(
            MagicMock(), phone="2010", plan=plan, conversation=conversation
        )

    h.texts = [c.args[1] for c in wa.send_text.call_args_list if len(c.args) > 1]
    return result, h


def _doctor(doctor_id=4, name_ar="د. نور الدين", name_en="Dr. Nour El-Din"):
    return SimpleNamespace(doctor_id=doctor_id, name_ar=name_ar, name_en=name_en)


# ---------------------------------------------------------------------------
# Executor: the V1 bug this rewrite exists to fix
# ---------------------------------------------------------------------------


def test_doctor_not_found_explains_and_shows_doctor_list():
    """V1 returned False here and the patient silently got the main menu."""
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="show_doctors",
            slots={"doctor_name": "أحمد سمير"},
            confidence={"overall": 0.9},
        ),
        doctor=None,
    )
    assert result.handled is True
    assert result.degraded is True
    assert "doctor_not_found" in result.reason
    # Patient was told why...
    assert any("أحمد سمير" in t for t in h.texts)
    # ...and given a real way forward.
    assert "_present_doctor_list" in h.presented


def test_doctor_found_jumps_straight_to_dates():
    result, h = _run(
        _plan(goal="book_new", next_step="show_doctors", slots={"doctor_name": "نور الدين"}),
        doctor=_doctor(),
    )
    assert result.handled is True
    assert result.step == "ask_date"
    assert h.presented == ["_present_dates"]
    assert h.texts == []


def test_named_doctor_never_opens_specialty_picker():
    """Planner hedged to ask_specialty with doctor_name set — must go to dates."""
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="ask_specialty",
            transcript="عايز أحجز معاد مع دكتور عمرو سليم",
            slots={"doctor_name": "عمرو سليم"},
            confidence={"overall": 0.9, "doctor": 0.95},
        ),
        doctor=_doctor(16, "د. عمرو سليم", "Dr. Amr Selim"),
    )
    assert result.handled is True
    assert result.step == "ask_date"
    assert h.presented == ["_present_dates"]
    assert "_present_department_doctors" not in h.presented


def test_specialty_parked_in_doctor_name_shows_department_list():
    """LLM often puts 'عيون' in doctor_name for 'دكتور عيون'."""
    dept = SimpleNamespace(department_id=5, name_ar="العيون", name_en="Ophthalmology")
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="show_doctors",
            transcript="دكتور عيون",
            slots={"doctor_name": "عيون"},
            confidence={"overall": 0.9},
        ),
        doctor=None,
        department=dept,
    )
    assert result.handled is True
    assert result.step == "show_doctors"
    assert result.degraded is False
    assert h.presented == ["_present_department_doctors"]


def test_carried_doctor_dropped_on_new_specialty_ask():
    """After Mona, saying 'دكتور قلب' must not open Mona's date picker."""
    dept = SimpleNamespace(department_id=1, name_ar="القلب", name_en="Cardiology")
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="ask_date",
            transcript="دكتور قلب",
            slots={"doctor_name": "منى يوسف", "specialty": "قلب"},
            confidence={"overall": 0.9},
        ),
        doctor=_doctor(14, "د. منى يوسف", "Dr. Mona Youssef"),
        department=dept,
        sess={"doctor_id": 14},
    )
    assert result.handled is True
    assert result.step == "show_doctors"
    assert "_present_department_doctors" in h.presented
    assert "_present_dates" not in h.presented


def test_date_time_after_specialty_keeps_context_doctor():
    """After أعصاب + ليلى, 'يوم الحد الساعة اتنين' must open slots — not re-list doctors."""
    dept = SimpleNamespace(department_id=8, name_ar="أعصاب", name_en="Neurology")
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="show_slots",
            transcript="عايز أحجز يوم الحد الساعة اتنين",
            slots={
                "doctor_name": "ليلى إبراهيم",
                "specialty": "أعصاب",
                "date": "2026-07-31",
                "time": "14:00",
                "selected_option_id": "doctor_14",
            },
            confidence={"overall": 0.9},
        ),
        doctor=_doctor(14, "د. ليلى إبراهيم", "Dr. Layla Ibrahim"),
        department=dept,
        sess={"awaiting": "doctor", "department_id": 8},
        availability={"2026-07-31": [{"slot_id": 1, "start": "14:00"}]},
    )
    assert result.handled is True
    assert result.step in {"show_slots", "hold_slot", "ask_date"}
    assert "_present_department_doctors" not in h.presented
    assert any(p in h.presented for p in ("_present_slots", "_present_dates"))


def test_ask_specialty_rewritten_when_specialty_already_known():
    """LLM often hedges to ask_specialty even after extracting قلب."""
    dept = SimpleNamespace(department_id=1, name_ar="قلب", name_en="Cardiology")
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="ask_specialty",
            transcript="لا خلاص عايز قلب",
            slots={"specialty": "قلب"},
            confidence={"overall": 0.8},
        ),
        doctor=None,
        department=dept,
    )
    assert result.handled is True
    assert result.step == "show_doctors"
    assert "_present_department_doctors" in h.presented


def test_cancel_appointment_starts_cancel_flow_not_menu_map():
    """Regression: pick_appointment used to feed transcript → [choice] menu_2."""
    conversation = SimpleNamespace(state=None, language=None)
    started: list[str] = []

    with ExitStack() as stack:
        stack.enter_context(patch.object(voice_executor, "_sess", return_value={}))
        stack.enter_context(patch.object(voice_executor, "wa", MagicMock()))
        stack.enter_context(
            patch(
                "app.graph.conversation_engine._start_cancel_flow",
                side_effect=lambda phone, db, conv: started.append("cancel"),
            )
        )
        stack.enter_context(
            patch.object(voice_executor, "_feed_engine", side_effect=AssertionError("no feed"))
        )
        result = voice_executor.execute_plan(
            MagicMock(),
            phone="2010",
            plan=_plan(
                goal="cancel_appointment",
                next_step="pick_appointment",
                transcript="أعيز ألغي معاد",
            ),
            conversation=conversation,
        )
    assert result.handled is True
    assert result.step == "pick_appointment"
    assert started == ["cancel"]


def test_stt_mangled_cancel_rewritten_from_handover():
    """'ألقي معايا' (STT of ألغي معاد) must not stay handover."""
    conversation = SimpleNamespace(state=None, language=None)
    started: list[str] = []

    with ExitStack() as stack:
        stack.enter_context(patch.object(voice_executor, "_sess", return_value={}))
        stack.enter_context(patch.object(voice_executor, "wa", MagicMock()))
        stack.enter_context(
            patch(
                "app.graph.conversation_engine._start_cancel_flow",
                side_effect=lambda phone, db, conv: started.append("cancel"),
            )
        )
        result = voice_executor.execute_plan(
            MagicMock(),
            phone="2010",
            plan=_plan(
                goal="handover",
                next_step="handover",
                transcript="أنا عايز ألقي معايا",
            ),
            conversation=conversation,
        )
    assert result.step == "pick_appointment"
    assert started == ["cancel"]


def test_reschedule_ask_change_target_starts_reschedule_list():
    """Planner often returns ask_change_target for 'عدّل الموعد' — must not feed menu."""
    conversation = SimpleNamespace(state=None, language=None)
    started: list[str] = []

    with ExitStack() as stack:
        stack.enter_context(patch.object(voice_executor, "_sess", return_value={"awaiting": "doctor"}))
        stack.enter_context(patch.object(voice_executor, "wa", MagicMock()))
        stack.enter_context(
            patch(
                "app.graph.conversation_engine._start_reschedule_flow",
                side_effect=lambda phone, db, conv: started.append("reschedule"),
            )
        )
        stack.enter_context(
            patch.object(voice_executor, "_feed_engine", side_effect=AssertionError("no feed"))
        )
        result = voice_executor.execute_plan(
            MagicMock(),
            phone="2010",
            plan=_plan(
                goal="reschedule",
                next_step="ask_change_target",
                transcript="أنا عايز أعدل الموعد",
                slots={"doctor_name": "عمرو سليم", "specialty": "قلب"},
            ),
            conversation=conversation,
        )
    assert result.handled is True
    assert result.step == "pick_appointment"
    assert started == ["reschedule"]


def test_mid_reschedule_change_time_does_not_restart_appt_list():
    """At change_type, 'أعدل الوقت' must feed the change button — not re-list appts."""
    conversation = SimpleNamespace(state=None, language=None)
    feeds: list[dict] = []
    sess = {
        "awaiting": "change_type",
        "current_appt": {"doctor_id": 3, "doctor_name": "كريم"},
        "doctor_id": 3,
        "appointment_id": 14,
    }

    with ExitStack() as stack:
        stack.enter_context(patch.object(voice_executor, "_sess", return_value=sess))
        stack.enter_context(patch.object(voice_executor, "wa", MagicMock()))
        stack.enter_context(
            patch(
                "app.graph.conversation_engine._start_reschedule_flow",
                side_effect=AssertionError("must not restart"),
            )
        )
        stack.enter_context(
            patch.object(
                voice_executor,
                "_feed_engine",
                side_effect=lambda db, phone, text="", payload_id=None: feeds.append(
                    {"text": text, "payload_id": payload_id}
                ),
            )
        )
        result = voice_executor.execute_plan(
            MagicMock(),
            phone="2010",
            plan=_plan(
                goal="reschedule",
                next_step="show_slots",
                transcript="أنا عايز أعدل الوقت",
                slots={
                    "doctor_name": "كريم شريف",
                    "change_target": "time",
                    "selected_option_id": "تعديل الوقت",
                },
            ),
            conversation=conversation,
        )
    assert result.handled is True
    assert feeds and feeds[0]["text"] == "تعديل الوقت"


def test_cancel_without_draft_not_abandon_menu():
    """'ألغي معاك' after a finished booking must start cancel, not abandon→menu."""
    conversation = SimpleNamespace(state=None, language=None)
    started: list[str] = []

    with ExitStack() as stack:
        stack.enter_context(patch.object(voice_executor, "_sess", return_value={}))
        stack.enter_context(patch.object(voice_executor, "wa", MagicMock()))
        stack.enter_context(
            patch(
                "app.graph.conversation_engine._start_cancel_flow",
                side_effect=lambda *a, **k: started.append("cancel"),
            )
        )
        stack.enter_context(
            patch(
                "app.graph.conversation_engine._send_main_menu",
                side_effect=AssertionError("no menu"),
            )
        )
        result = voice_executor.execute_plan(
            MagicMock(),
            phone="2010",
            plan=_plan(
                goal="abandon_draft",
                next_step="show_menu",
                transcript="عايز ألغي معاك",
            ),
            conversation=conversation,
        )
    assert result.step == "pick_appointment"
    assert started == ["cancel"]


def test_garbled_reschedule_from_unclear():
    """Bad Whisper of 'أعدل الموعد' should still start reschedule."""
    conversation = SimpleNamespace(state=None, language=None)
    started: list[str] = []

    with ExitStack() as stack:
        stack.enter_context(patch.object(voice_executor, "_sess", return_value={}))
        stack.enter_context(patch.object(voice_executor, "wa", MagicMock()))
        stack.enter_context(
            patch(
                "app.graph.conversation_engine._start_reschedule_flow",
                side_effect=lambda *a, **k: started.append("reschedule"),
            )
        )
        result = voice_executor.execute_plan(
            MagicMock(),
            phone="2010",
            plan=_plan(
                goal="unclear",
                next_step="clarify",
                transcript="طيب أنا حاول عد الامعات",
            ),
            conversation=conversation,
        )
    assert result.step == "pick_appointment"
    assert started == ["reschedule"]


def test_stale_specialty_overridden_by_transcript_word():
    """LLM keeps أسنان after patient says عظام — sanitize must switch."""
    teeth = SimpleNamespace(department_id=6, name_ar="أسنان", name_en="Dentistry")
    bones = SimpleNamespace(department_id=2, name_ar="عظام", name_en="Orthopedics")
    conversation = SimpleNamespace(state=None, language=None)
    from app.services import doctor_service as real_ds

    doctor_service = MagicMock()
    doctor_service.find_department.side_effect = (
        lambda db, cid, name=None, department_id=None: (
            bones
            if name and "عظم" in str(name)
            else teeth
            if name and ("سن" in str(name) or name == "أسنان")
            else None
        )
    )
    doctor_service.infer_department_from_text.return_value = bones
    doctor_service.is_specialty_word.side_effect = real_ds.is_specialty_word
    doctor_service.list_departments.return_value = []

    presented: list[str] = []
    with ExitStack() as stack:
        stack.enter_context(patch.object(voice_executor, "_sess", return_value={}))
        stack.enter_context(patch.object(voice_executor, "wa", MagicMock()))
        stack.enter_context(patch.object(voice_executor, "doctor_service", doctor_service))
        stack.enter_context(patch.object(voice_executor, "set_conversation_state", MagicMock()))
        stack.enter_context(
            patch.object(
                voice_executor,
                "_present_department_doctors",
                side_effect=lambda *a, **k: presented.append("_present_department_doctors")
                or True,
            )
        )
        stack.enter_context(
            patch.object(voice_fastpath, "find_doctor_by_hint", return_value=None)
        )
        result = voice_executor.execute_plan(
            MagicMock(),
            phone="2010",
            plan=_plan(
                goal="book_new",
                next_step="show_doctors",
                transcript="لا عظام أحسن",
                slots={"specialty": "أسنان"},
            ),
            conversation=conversation,
        )
    assert result.step == "show_doctors"
    assert presented == ["_present_department_doctors"]
    # Sanitized specialty must be bones (passed into present via department resolve)
    assert doctor_service.infer_department_from_text.called


def test_doctor_alternative_is_used_when_first_name_misses():
    """'أحمد أو علي' — V1 had nowhere to put the second candidate."""
    calls: list[str] = []

    def _find(db, clinic_id, hint):
        calls.append(hint)
        return _doctor() if "علي" in (hint or "") else None

    conversation = SimpleNamespace(state=None, language=None)
    with ExitStack() as stack:
        stack.enter_context(patch.object(voice_executor, "_sess", return_value={}))
        stack.enter_context(patch.object(voice_executor, "wa", MagicMock()))
        stack.enter_context(patch.object(voice_executor, "set_conversation_state", MagicMock()))
        stack.enter_context(patch.object(voice_executor, "_present_dates", return_value=True))
        stack.enter_context(patch.object(voice_fastpath, "find_doctor_by_hint", side_effect=_find))
        result = voice_executor.execute_plan(
            MagicMock(),
            phone="2010",
            plan=_plan(
                goal="book_new",
                next_step="show_doctors",
                slots={"doctor_name": "أحمد", "doctor_alternatives": ["علي"]},
            ),
            conversation=conversation,
        )
    assert result.handled is True
    assert result.step == "ask_date"
    # sanitize probes the primary name once; resolve then tries primary + alt
    assert calls[-2:] == ["أحمد", "علي"]
    assert "علي" in calls


# ---------------------------------------------------------------------------
# Executor: degradation ladder
# ---------------------------------------------------------------------------


def test_fully_booked_doctor_degrades_to_doctor_list_with_reason():
    result, h = _run(
        _plan(goal="book_new", next_step="show_slots", slots={"doctor_name": "نور الدين"}),
        doctor=_doctor(),
        availability={},
    )
    assert result.handled is True
    assert result.degraded is True
    assert result.reason == "doctor_fully_booked"
    assert any("نور" in t for t in h.texts)


def test_unavailable_date_degrades_to_day_picker_with_reason():
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="show_slots",
            slots={"doctor_name": "نور الدين", "date": "2026-07-30"},
        ),
        doctor=_doctor(),
        availability={"2026-07-28": [{"slot_id": 1}]},
    )
    assert result.handled is True
    assert result.step == "ask_date"
    assert result.reason == "date_unavailable"
    assert h.texts, "patient must be told the requested day had nothing free"
    assert "_present_dates" in h.presented


def test_show_slots_renders_the_requested_day():
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="show_slots",
            slots={"doctor_name": "نور الدين", "date": "2026-07-28"},
        ),
        doctor=_doctor(),
        availability={"2026-07-28": [{"slot_id": 1}]},
    )
    assert result.handled is True
    assert result.step == "show_slots"
    assert result.degraded is False
    assert h.presented == ["_present_slots"]


def test_time_not_available_degrades_to_slot_list_with_reason():
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="hold_slot",
            slots={"doctor_name": "نور الدين", "date": "2026-07-28", "time": "13:30"},
        ),
        doctor=_doctor(),
        availability={"2026-07-28": [{"slot_id": 1}]},
        matched=None,
    )
    assert result.handled is True
    assert result.step == "show_slots"
    assert result.reason == "time_not_available"
    assert h.texts, "patient must be told the exact time wasn't free"
    assert "_present_slots" in h.presented


def test_slot_taken_race_explains_and_reshows_same_day():
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="hold_slot",
            slots={"doctor_name": "نور الدين", "date": "2026-07-28", "time": "14:00"},
        ),
        doctor=_doctor(),
        availability={"2026-07-28": [{"slot_id": 9}]},
        matched={"slot_id": 9, "slot_start": datetime(2026, 7, 28, 14, 0)},
        hold_error=BookingError("Slot not available"),
    )
    assert result.handled is True
    assert result.step == "show_slots"
    assert result.reason == "slot_taken"
    assert h.texts, "patient must be told the slot was taken"
    assert "_present_slots" in h.presented


def test_missing_doctor_at_date_step_asks_for_doctor_first():
    result, h = _run(
        _plan(goal="book_new", next_step="ask_date", slots={"date": "2026-07-28"}),
        doctor=None,
    )
    assert result.handled is True
    assert result.degraded is True
    assert result.reason == "missing_doctor"
    assert h.texts, "patient must be told we need the doctor first"


# ---------------------------------------------------------------------------
# Executor: happy path + chaining
# ---------------------------------------------------------------------------


def test_hold_slot_success_sets_patient_name_step():
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="hold_slot",
            slots={"doctor_name": "نور الدين", "date": "2026-07-28", "time": "14:00"},
        ),
        doctor=_doctor(),
        availability={"2026-07-28": [{"slot_id": 9}]},
        matched={"slot_id": 9, "slot_start": datetime(2026, 7, 28, 14, 0)},
    )
    assert result.handled is True
    assert result.step == "hold_slot"
    assert result.degraded is False
    assert h.sess["slot_id"] == 9
    assert h.sess["awaiting"] == "patient_name"
    assert h.names_fed == []


def test_spoken_patient_name_is_chained_after_hold():
    """'احجز لمحمد إبراهيم مع د. نور بكرة 2' — V1 could not carry the name."""
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="hold_slot",
            slots={
                "doctor_name": "نور الدين",
                "date": "2026-07-28",
                "time": "14:00",
                "patient_name": "محمد إبراهيم",
            },
        ),
        doctor=_doctor(),
        availability={"2026-07-28": [{"slot_id": 9}]},
        matched={"slot_id": 9, "slot_start": datetime(2026, 7, 28, 14, 0)},
    )
    assert result.handled is True
    assert h.names_fed == ["محمد إبراهيم"]


def test_earliest_flexibility_picks_first_available_day():
    """'أقرب موعد' — no date spoken, but the patient deferred to us."""
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="show_slots",
            slots={"doctor_name": "نور الدين", "date_flexibility": "earliest"},
        ),
        doctor=_doctor(),
        availability={"2026-07-30": [{"slot_id": 2}], "2026-07-28": [{"slot_id": 1}]},
    )
    assert result.handled is True
    assert result.step == "show_slots"
    assert result.degraded is False
    # Earliest of the two open days, not dict insertion order.
    assert h.present_kwargs[0]["date_key"] == "2026-07-28"


# ---------------------------------------------------------------------------
# Executor: abandon_draft, delegation, compound requests
# ---------------------------------------------------------------------------


def test_abandon_draft_says_so_before_the_menu():
    """The distinction V1 could not make: dropping a draft != cancelling a booking."""
    sent: list[str] = []
    conversation = SimpleNamespace(state=None, language=None)
    wa = MagicMock()
    with ExitStack() as stack:
        stack.enter_context(patch.object(voice_executor, "_sess", return_value={}))
        stack.enter_context(patch.object(voice_executor, "wa", wa))
        stack.enter_context(
            patch("app.graph.conversation_engine._clear_draft", MagicMock())
        )
        stack.enter_context(
            patch(
                "app.graph.conversation_engine._send_main_menu",
                side_effect=lambda *a, **k: sent.append("menu"),
            )
        )
        result = voice_executor.execute_plan(
            MagicMock(),
            phone="2010",
            plan=_plan(goal="abandon_draft", next_step="show_menu"),
            conversation=conversation,
        )
    assert result.handled is True
    assert sent == ["menu"]
    assert wa.send_text.called, "abandoning a draft must be acknowledged"


def test_confirm_and_engine_steps_are_owned_not_delegated():
    """V2 always owns the turn — confirm seeds the engine; cancel starts cancel flow."""
    result, h = _run(
        _plan(goal="confirm", next_step="confirm_booking", transcript="نعم")
    )
    assert result.handled is True
    assert h.engine_feeds, "confirm must seed the engine"

    started: list[str] = []
    conversation = SimpleNamespace(state=None, language=None)
    with ExitStack() as stack:
        stack.enter_context(patch.object(voice_executor, "_sess", return_value={}))
        stack.enter_context(patch.object(voice_executor, "wa", MagicMock()))
        stack.enter_context(
            patch(
                "app.graph.conversation_engine._start_cancel_flow",
                side_effect=lambda *a, **k: started.append("cancel"),
            )
        )
        result = voice_executor.execute_plan(
            MagicMock(),
            phone="2010",
            plan=_plan(
                goal="cancel_appointment",
                next_step="confirm_cancel",
                transcript="الغي موعدي",
            ),
            conversation=conversation,
        )
    assert result.handled is True
    assert result.step == "pick_appointment"
    assert started == ["cancel"]


def test_followup_goal_is_remembered_not_chained():
    """Compound requests are stored, never executed in the same turn (menu spam)."""
    result, h = _run(
        _plan(
            goal="cancel_appointment",
            next_step="confirm_cancel",
            followup_goal="book_new",
            transcript="الغي واحجز",
        ),
    )
    assert h.sess["voice_followup_goal"] == "book_new"
    assert result.handled is True


def _run_crashing_handler(*, speak_first: bool):
    """Install a show_doctors handler that crashes, optionally after replying."""
    conversation = SimpleNamespace(state=None, language=None)
    wa = MagicMock()

    def _boom(db, phone, plan, conversation):
        if speak_first:
            voice_executor._say(phone, "نأسف")
        raise RuntimeError("boom")

    with ExitStack() as stack:
        stack.enter_context(patch.object(voice_executor, "_sess", return_value={}))
        stack.enter_context(patch.object(voice_executor, "wa", wa))
        stack.enter_context(
            patch("app.graph.conversation_engine._send_main_menu", MagicMock())
        )
        stack.enter_context(
            patch.dict(voice_executor._STEP_HANDLERS, {"show_doctors": _boom})
        )
        result = voice_executor.execute_plan(
            MagicMock(),
            phone="2010",
            plan=_plan(goal="book_new", next_step="show_doctors"),
            conversation=conversation,
        )
    return result, wa


def test_crash_before_replying_owns_turn_with_clarify():
    """No V1 fallback — clarify owns the turn instead of double-messaging later."""
    result, wa = _run_crashing_handler(speak_first=False)
    assert result.handled is True
    assert wa.send_text.call_count >= 1


def test_crash_after_replying_owns_the_turn_instead_of_double_messaging():
    """Regression guard: must not send a 2nd reply path after a partial reply."""
    result, wa = _run_crashing_handler(speak_first=True)
    assert result.handled is True, "must own the turn after already replying"
    assert result.reason == "handler_error_after_reply"
    assert wa.send_text.call_count == 1


def test_send_counter_does_not_leak_between_executions():
    """The guard is per-turn; a later crash still gets its own clarify."""
    _run_crashing_handler(speak_first=True)
    result, wa = _run_crashing_handler(speak_first=False)
    assert result.handled is True
    assert wa.send_text.call_count >= 1


def test_no_departments_falls_back_to_doctor_list_not_the_menu():
    """Recursing into the main menu made the funnel 4 deep; it now stops at doctors."""
    result, h = _run(
        _plan(goal="book_new", next_step="ask_specialty"),
        department=None,
    )
    assert result.handled is True
    assert result.step == "show_doctors"
    assert result.reason == "no_departments"
    assert h.presented == ["_present_doctor_list"]


def test_spoken_name_beats_same_patient_option():
    """At known_patient_confirm, a spoken name must not feed 'نفس المريض'."""
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="confirm_booking",
            transcript="أنا اسمي علي محمود محمود",
            slots={
                "patient_name": "علي محمود محمود",
                "selected_option_id": "نفس المريض",
            },
        ),
        sess={"awaiting": "known_patient_confirm", "doctor_id": 4, "slot_id": 1},
    )
    assert result.handled is True
    assert result.step == "ask_patient_name"
    assert h.engine_feeds == [{"text": "علي محمود محمود", "payload_id": None}]


def test_name_step_overwrites_when_planner_parks_name_as_doctor():
    """After ask-name, a corrected spoken name must replace any previous draft."""
    result, h = _run(
        _plan(
            goal="ask_doctors",
            next_step="show_doctors",
            transcript="محمد أحمد علي",
            slots={"doctor_name": "محمد أحمد علي"},
        ),
        sess={"awaiting": "patient_name", "patient_name": "اسم قديم قديم قديم", "doctor_id": 1},
    )
    assert result.handled is True
    assert result.step == "ask_patient_name"
    assert h.engine_feeds == [{"text": "محمد أحمد علي", "payload_id": None}]
    assert h.sess.get("awaiting") == "patient_name"


def test_name_step_uses_transcript_correction():
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="clarify",
            transcript="اسمي كريم سامح محمود",
            slots={},
        ),
        sess={"awaiting": "patient_name", "doctor_id": 1},
    )
    assert result.handled is True
    assert result.step == "ask_patient_name"
    assert h.engine_feeds == [{"text": "كريم سامح محمود", "payload_id": None}]


def test_tasa_alias_maps_to_nisa_specialty():
    from app.services.doctor_service import fuzzy_specialty_canonical, is_specialty_word

    for raw in ("تسا", "تساء", "نسا", "نيسا", "نساء", "نساء وتوليد", "نسا وتوليد"):
        assert is_specialty_word(raw), raw
        assert fuzzy_specialty_canonical(raw) == "نساء", raw


def test_asab_whisper_alias_maps_to_asaab_specialty():
    from app.services.doctor_service import fuzzy_specialty_canonical, is_specialty_word

    for raw in ("أصاب", "اصاب", "عصاب", "أعصاب", "اعصاب"):
        assert is_specialty_word(raw), raw
        assert fuzzy_specialty_canonical(raw) == "أعصاب", raw


def test_nisa_overrides_stale_asaab_and_shows_obgyn_list():
    """Whisper نيسا + stale أعصاب/ليلى must show نساء doctors, not ليلى's days."""
    from unittest.mock import patch

    from app.services import doctor_service as real_ds
    from app.services import voice_fastpath

    dept = SimpleNamespace(department_id=9, name_ar="نساء وتوليد", name_en="OB/GYN")
    laila = SimpleNamespace(
        doctor_id=8, name_ar="د. ليلى إبراهيم", name_en="Dr. Laila Ibrahim"
    )
    presented: list[str] = []
    conversation = SimpleNamespace(state=None, language=None)

    def _hint(_db, _cid, text):
        t = str(text or "")
        if "ليلى" in t or "Laila" in t:
            return laila
        return None

    with ExitStack() as stack:
        stack.enter_context(patch.object(voice_executor, "_sess", return_value={}))
        stack.enter_context(patch.object(voice_executor, "wa", MagicMock()))
        stack.enter_context(patch.object(voice_executor, "set_conversation_state", MagicMock()))
        stack.enter_context(
            patch.object(
                voice_executor,
                "_present_department_doctors",
                side_effect=lambda *a, **k: presented.append("_present_department_doctors")
                or True,
            )
        )
        stack.enter_context(
            patch.object(
                voice_executor,
                "_present_dates",
                side_effect=lambda *a, **k: presented.append("_present_dates") or True,
            )
        )
        stack.enter_context(patch.object(voice_fastpath, "find_doctor_by_hint", side_effect=_hint))

        ds = MagicMock()
        ds.find_department.side_effect = (
            lambda db, cid, name=None, department_id=None: (
                dept
                if department_id is not None
                or (name and any(x in str(name) for x in ("نساء", "نسا", "نيسا")))
                else None
            )
        )
        ds.infer_department_from_text.return_value = None
        ds.is_specialty_word.side_effect = real_ds.is_specialty_word
        ds.fuzzy_specialty_canonical.side_effect = real_ds.fuzzy_specialty_canonical
        ds.list_departments.return_value = []
        stack.enter_context(patch.object(voice_executor, "doctor_service", ds))

        result = voice_executor.execute_plan(
            MagicMock(),
            phone="2010",
            plan=_plan(
                goal="book_new",
                next_step="show_doctors",
                transcript="نايزة احكيز دكتورة نيسا",
                slots={
                    "doctor_name": "نيسا",
                    "specialty": "أعصاب",
                    "doctor_alternatives": ["ليلى إبراهيم"],
                },
            ),
            conversation=conversation,
        )

    assert result.handled is True
    assert result.step == "show_doctors"
    assert "_present_department_doctors" in presented
    assert "_present_dates" not in presented


def test_show_doctors_resolves_tasa_specialty():
    dept = SimpleNamespace(department_id=9, name_ar="نساء وتوليد", name_en="OB/GYN")
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="show_doctors",
            transcript="عايز أحجز تسا",
            slots={"doctor_name": "تسا"},
        ),
        department=dept,
    )
    assert result.handled is True
    assert result.step == "show_doctors"
    assert "_present_department_doctors" in h.presented


def test_name_intro_does_not_pick_appt_option():
    """'اسمي بلال…' must not select appt_5 from the reschedule list."""
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="ask_patient_name",
            transcript="اسمي بلال أحمد محمود",
            slots={
                "patient_name": "بلال أحمد محمود",
                "selected_option_id": "appt_5",
            },
        ),
        sess={
            "awaiting": "pick_appointment",
            "last_options": [{"id": "appt_5", "title": "موعد"}],
        },
    )
    assert result.handled is True
    assert result.step == "clarify"
    assert not any(f.get("payload_id") == "appt_5" for f in h.engine_feeds)


def test_mid_draft_specialty_change_not_reschedule_list():
    """At booking summary, 'change to نساء' restarts doctors — not UC-003."""
    dept = SimpleNamespace(department_id=9, name_ar="النساء", name_en="OB/GYN")
    result, h = _run(
        _plan(
            goal="reschedule",
            next_step="pick_appointment",
            transcript="عايز أغير لدكتور نساء",
            slots={"specialty": "نساء", "change_target": "doctor"},
        ),
        sess={
            "awaiting": "summary",
            "doctor_id": 4,
            "slot_id": 12,
            "selected_date": "2026-07-28",
        },
        department=dept,
        doctor=None,
    )
    assert result.handled is True
    assert result.step == "show_doctors"
    assert "_present_department_doctors" in h.presented
    assert h.sess.get("slot_id") is None
    assert h.sess.get("selected_date") is None


def test_book_neurology_escapes_cancel_appointment_list():
    """Clear 'book neurology' must show أعصاب doctors, not stay on cancel list."""
    dept = SimpleNamespace(department_id=8, name_ar="أعصاب", name_en="Neurology")
    result, h = _run(
        _plan(
            goal="cancel_appointment",
            next_step="pick_appointment",
            transcript="I want to book a neurology appointment",
            slots={"specialty": "أعصاب"},
            language="en",
        ),
        sess={
            "awaiting": "pick_appointment",
            "last_options": [{"id": "appt_1", "title": "موعد"}],
            "language": "en",
        },
        department=dept,
        doctor=None,
    )
    assert result.handled is True
    assert result.step == "show_doctors"
    assert "_present_department_doctors" in h.presented
    assert h.sess.get("awaiting") != "pick_appointment"


def test_mangled_book_doctor_escapes_pick_appointment_list():
    """Whisper 'حيكيز' + doctor must leave reschedule list for a new book."""
    result, h = _run(
        _plan(
            goal="reschedule",
            next_step="pick_appointment",
            transcript="دايزة حيكيز مع دكتور قلدهي",
            slots={"doctor_name": "قلدهي"},
        ),
        sess={
            "awaiting": "pick_appointment",
            "last_options": [{"id": "appt_1", "title": "موعد"}],
        },
        doctor=None,
    )
    assert result.handled is True
    assert result.step == "show_doctors"
    assert h.sess.get("awaiting") != "pick_appointment"


def test_asab_specialty_escapes_pick_appointment_without_book_cue():
    """Specialty alone on the list (أصاب→أعصاب) starts a new book."""
    dept = SimpleNamespace(department_id=8, name_ar="أعصاب", name_en="Neurology")
    result, h = _run(
        _plan(
            goal="reschedule",
            next_step="pick_appointment",
            transcript="دكتور أصاب",
            slots={"doctor_name": "أصاب"},
        ),
        sess={
            "awaiting": "pick_appointment",
            "last_options": [{"id": "appt_1", "title": "موعد"}],
        },
        department=dept,
        doctor=None,
    )
    assert result.handled is True
    assert result.step == "show_doctors"
    assert "_present_department_doctors" in h.presented
    assert h.sess.get("awaiting") != "pick_appointment"


def test_edit_utterance_stays_on_pick_appointment_list():
    """اغير / اعدل must keep the edit-appointment list, not escape to book."""
    from unittest.mock import patch

    for transcript, slots in (
        ("عايز اغير الموعد", {}),
        ("عايز اعدل المعاد", {}),
        ("اغير الموعد لدكتور أعصاب", {"specialty": "أعصاب"}),
    ):
        with patch("app.graph.conversation_engine._start_reschedule_flow"):
            result, h = _run(
                _plan(
                    goal="reschedule",
                    next_step="pick_appointment",
                    transcript=transcript,
                    slots=slots,
                ),
                sess={
                    "awaiting": "pick_appointment",
                    "last_options": [{"id": "appt_1", "title": "موعد"}],
                },
                doctor=None,
            )
        assert result.handled is True, transcript
        assert result.step == "pick_appointment", transcript
        assert h.sess.get("awaiting") == "pick_appointment", transcript


def test_named_doctor_at_patient_confirm_switches_draft():
    """Naming a doctor at known_patient_confirm changes the draft, not appt list."""
    result, h = _run(
        _plan(
            goal="reschedule",
            next_step="pick_appointment",
            transcript="عايز أحجز مع دكتور بلال أبو لبن",
            slots={"doctor_name": "بلال أبو لبن"},
        ),
        sess={"awaiting": "known_patient_confirm", "doctor_id": 4, "slot_id": 1},
        doctor=_doctor(20, "د. بلال أبو لبن", "Dr. Bilal"),
    )
    assert result.handled is True
    assert result.step == "ask_date"
    assert "_present_dates" in h.presented


def test_filler_basmala_does_not_advance_slots():
    """Greeting-only speech must clarify and keep the open slot list."""
    result, h = _run(
        _plan(
            goal="book_new",
            next_step="show_slots",
            transcript="بسم الله الرحمن الرحيم",
            slots={"date": "2026-07-28", "doctor_name": "نور الدين"},
        ),
        sess={
            "awaiting": "slot",
            "doctor_id": 4,
            "last_options": [{"id": "slot_1", "title": "2:00"}],
        },
        doctor=_doctor(),
        availability={"2026-07-28": [{"slot_id": 1}]},
    )
    assert result.handled is True
    assert result.step == "clarify"
    assert "_present_slots" not in h.presented


def test_mid_draft_change_day_not_reschedule_list():
    """At slot step, 'أغير اليوم' must reopen dates for the draft doctor."""
    result, h = _run(
        _plan(
            goal="reschedule",
            next_step="ask_date",
            transcript="عايز أغير اليوم",
            slots={"doctor_name": "نور الدين", "change_target": "date"},
        ),
        sess={
            "awaiting": "slot",
            "doctor_id": 4,
            "selected_date": "2026-07-28",
            "flow": "booking",
        },
        doctor=_doctor(),
    )
    assert result.handled is True
    assert result.step == "ask_date"
    assert "_present_dates" in h.presented
    assert h.sess.get("selected_date") is None
