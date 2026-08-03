"""Router V2 executor: run the LLM's plan, check availability, degrade simply.

The planner decides WHAT to do. This module only checks whether it CAN happen
(doctor exists, day has slots, …) and either runs it or steps one rung down
with a short explanation. No V1 fastpath second-guessing.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core import i18n_bot as i18n
from app.core.config import DEFAULT_CLINIC_ID, SLOT_HOLD_MINUTES
from app.db.enums import ConversationState
from app.graph.conversation_engine import _sess
from app.models.doctor_models import Doctor
from app.services import booking_service, doctor_service, whatsapp_client as wa
from app.services.booking_service import BookingError
from app.services.conversation_service import set_conversation_state
from app.services.voice_schemas import VoicePlan

logger = logging.getLogger(__name__)

# Steps with a dedicated handler. Everything else is a single engine feed
# (transcript or option id) — no V1 voice_fastpath maze.
NATIVE_STEPS = frozenset(
    {
        "show_menu",
        "ask_specialty",
        "show_doctors",
        "ask_date",
        "show_slots",
        "hold_slot",
        "ask_patient_name",
        "confirm_booking",
        "clarify",
        "pick_appointment",
        "handover",
    }
)


# Messages sent during the current execute_plan() call. Once we have spoken to
# the patient we must never delegate to the V1 fastpath as well, or they get two
# replies for one voice note — the duplicate-menu bug this rewrite removes.
_sent_count: ContextVar[int] = ContextVar("voice_exec_sent", default=0)


def _say(phone: str, text: str) -> None:
    """Send a patient-facing message and record that we have spoken."""
    wa.send_text(phone, text)
    _sent_count.set(_sent_count.get() + 1)


@dataclass
class ExecResult:
    """Outcome of one plan execution."""

    handled: bool
    step: str = ""
    requested_step: str = ""
    reason: str = ""

    @property
    def degraded(self) -> bool:
        """True when the plan could not be run as asked.

        Keyed off `reason` rather than a step-name change: resolving a doctor can
        fail and still land on `show_doctors`, which is a degradation even though
        the step label is unchanged.
        """
        return bool(self.reason) and self.reason != "delegate"


def _delegate() -> ExecResult:
    """Not ours to run — caller should fall back to the V1 fastpath."""
    return ExecResult(handled=False, reason="delegate")


def _lang(conversation, phone: str) -> str:
    from app.graph.conversation_engine import _lang as engine_lang

    return engine_lang(conversation, _sess(phone))


def _transcript(plan: VoicePlan) -> str:
    return (plan.transcript or "").strip()


# ---------------------------------------------------------------------------
# Slot resolution — turn spoken hints into real DB entities
# ---------------------------------------------------------------------------


def _norm_simple(text: str) -> str:
    s = (text or "").strip().lower()
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي")):
        s = s.replace(src, dst)
    return s


def _looks_like_cancel_utterance(transcript: str) -> bool:
    """True for Egyptian cancel asks, including common Whisper mangling.

    Whisper/STT often turns ألغي→ألقي and معاد→معاهد/معايا/معاك.
    """
    t = _norm_simple(transcript)
    if not t:
        return False
    if "cancel" in t:
        return True
    cancel_verbs = ("الغي", "القي", "الغاء", "الغ")  # after أ/إ→ا norm
    appt_words = (
        "معاد",
        "موعد",
        "معاهد",
        "معايا",
        "معاك",
        "الحجز",
        "appointment",
    )
    has_verb = any(v in t for v in cancel_verbs)
    has_appt = any(w in t for w in appt_words)
    # "عايز ألغي" alone is enough; "ألقي معايا" needs the mangled appt word.
    return has_verb and (has_appt or "الغي" in t or "الغاء" in t)


def _looks_like_reschedule_utterance(transcript: str) -> bool:
    """True for 'أعدل الموعد' and common STT mangling ('عد الامعات')."""
    t = _norm_simple(transcript)
    if not t:
        return False
    if "reschedule" in t:
        return True
    if any(p in t for p in ("عدل الموعد", "عدل المعاد", "تغيير الموعد", "تغيير المعاد")):
        return True
    if "اعدل" in t or "عدل" in t:
        return True
    # Short "عد … معاد/امعات" mangling after booking
    if "عد" in t and any(w in t for w in ("معاد", "موعد", "امعات", "الاماعة", "معاهد")):
        return True
    return False


def _has_active_booking_draft(phone: str) -> bool:
    """True when a half-finished booking/reschedule draft is open."""
    sess = _sess(phone)
    awaiting = sess.get("awaiting")
    if awaiting in {
        "doctor",
        "date",
        "slot",
        "department",
        "patient_name",
        "confirm",
        "known_patient_confirm",
        "summary",
    }:
        return True
    return bool(
        sess.get("doctor_id")
        or sess.get("department_id")
        or sess.get("selected_date")
        or sess.get("held_slot_id")
        or sess.get("slot_id")
    )


def _reschedule_midflow(phone: str) -> bool:
    """True when an appointment is already picked and we're changing it."""
    sess = _sess(phone)
    if not sess.get("current_appt"):
        return False
    return sess.get("awaiting") in {
        "change_type",
        "date",
        "slot",
        "doctor",
        "confirm",
    }


def _is_filler_utterance(transcript: str) -> bool:
    """True for greeting/basmala-only / Whisper-hallucination speech."""
    from app.language.language_detector import is_whisper_garbage

    if is_whisper_garbage(transcript):
        return True
    t = _norm_simple(transcript)
    if not t:
        return True
    for ch in ".,!?،؛:\"'":
        t = t.replace(ch, " ")
    t = " ".join(t.split())
    exact = {
        "بسم الله الرحمن الرحيم",
        "بسم الله",
        "بسم الله الرحمن",
        "الحمد لله",
        "الله اكبر",
        "سبحان الله",
        "امين",
        "السلام عليكم",
        "وعليكم السلام",
        "السلام عليكم ورحمه الله",
        "السلام عليكم ورحمه الله وبركاته",
        "نهاية",
        "نهاية زياده",
        "نهاية زيادة",
    }
    if t in exact:
        return True
    if t.startswith("بسم الله") and len(t) < 48:
        booking_bits = (
            "احجز",
            "حجز",
            "موعد",
            "معاد",
            "دكتور",
            "الدكتور",
            "ساعه",
            "يوم",
            "بكره",
            "غدا",
        )
        if not any(b in t for b in booking_bits):
            return True
    return False


def _looks_like_patient_name_intro(transcript: str) -> bool:
    """True when the utterance is introducing a patient name ('اسمي …')."""
    t = _norm_simple(transcript)
    if not t:
        return False
    return any(
        p in t
        for p in (
            "اسمي",
            "اسم المريض",
            "انا اسمي",
            "my name is",
            "i am",
            "i'm",
        )
    )


def _strip_patient_name_leadin(text: str) -> str:
    """Drop 'اسمي / my name is' prefixes so the remainder is the person name."""
    import re

    raw = (text or "").strip()
    if not raw:
        return ""
    return re.sub(
        r"^(?:انا\s+)?(?:اسمي|اسم\s+المريض|my\s+name\s+is|i(?:'?m|\s+am))\s*[:\-]?\s*",
        "",
        raw,
        flags=re.I,
    ).strip() or raw


def _coerce_plan_for_name_step(phone: str, plan: VoicePlan) -> VoicePlan:
    """While asking for the patient name, treat speech as a name edit/overwrite.

    Planner often parks a spoken name in doctor_name or ignores a correction.
    At patient_name / known_patient_confirm, prefer the spoken person name.
    """
    awaiting = _sess(phone).get("awaiting")
    if awaiting not in {"patient_name", "known_patient_confirm"}:
        return plan

    transcript = _transcript(plan)
    patient = (plan.slots.patient_name or "").strip()
    doctor = (plan.slots.doctor_name or "").strip()
    clear_doctor = False

    if not patient and doctor and not doctor_service.is_specialty_word(doctor):
        tnorm = _norm_simple(transcript)
        doctor_cue = any(
            x in tnorm
            for x in (
                "دكتور",
                "الدكتور",
                "doctor",
                "dr ",
                "dr.",
                "احجز مع",
                "مع دكتور",
                "book with",
            )
        )
        if doctor_cue:
            # Real doctor change mid name-confirm — leave for draft switch logic.
            return plan
        patient = doctor
        clear_doctor = True
        logger.info(
            "[voice][v2] name-step remap doctor_name=%r → patient_name phone=%s",
            doctor,
            phone,
        )
    if not patient and transcript and not _is_filler_utterance(transcript):
        # Don't steal a clear specialty/cancel/reschedule switch.
        if doctor_service.is_specialty_word(transcript):
            return plan
        if _looks_like_cancel_utterance(transcript) or _looks_like_reschedule_utterance(
            transcript
        ):
            return plan
        patient = _strip_patient_name_leadin(transcript)

    if not patient:
        return plan

    if doctor and (
        clear_doctor
        or doctor == patient
        or _norm_simple(doctor) in _norm_simple(patient)
        or _norm_simple(patient) in _norm_simple(doctor)
    ):
        clear_doctor = True

    slot_update = {
        "patient_name": patient,
        "selected_option_id": None,
        **({"doctor_name": None} if clear_doctor else {}),
    }
    updates: dict = {
        "next_step": "ask_patient_name",
        "slots": plan.slots.model_copy(update=slot_update),
    }
    if plan.goal in {"unclear", "ask_doctors", "reschedule"}:
        updates["goal"] = "book_new"
    logger.info(
        "[voice][v2] name-step accept patient_name=%r (awaiting=%s) phone=%s",
        patient,
        awaiting,
        phone,
    )
    return plan.model_copy(update=updates)


def _mid_draft_doctor_switch(phone: str, plan: VoicePlan) -> bool:
    """True when mid-booking the user wants another doctor/specialty (not UC-003)."""
    sess = _sess(phone)
    awaiting = sess.get("awaiting")
    if awaiting not in {
        "summary",
        "confirm",
        "known_patient_confirm",
        "patient_name",
    }:
        return False
    # A real reschedule of an existing appt uses current_appt midflow instead.
    if sess.get("current_appt") and awaiting in {"confirm", "change_type"}:
        return False

    change = (plan.slots.change_target or "").strip().lower()
    if change == "doctor":
        return True

    transcript = _transcript(plan)
    t = _norm_simple(transcript)
    if any(
        p in t
        for p in (
            "تغيير الطبيب",
            "غير الطبيب",
            "دكتور تاني",
            "طبيب اخر",
            "طبيب ثاني",
            "change doctor",
            "different doctor",
            "another doctor",
        )
    ):
        return True

    specialty = (plan.slots.specialty or "").strip()
    specialty_in_speech = bool(
        specialty and _norm_simple(specialty) and _norm_simple(specialty) in t
    )
    # Patient-name turns must not be treated as doctor switches just because
    # the planner carried doctor_name/specialty from the draft.
    if (plan.slots.patient_name or "").strip() or _looks_like_patient_name_intro(transcript):
        return specialty_in_speech

    if specialty_in_speech:
        return True

    doctor_name = (plan.slots.doctor_name or "").strip()
    if doctor_name and t:
        if any(x in t for x in ("دكتور", "الدكتور", "doctor", " dr", "د.")):
            return True
        bits = [
            b
            for b in _norm_simple(doctor_name).split()
            if len(b) >= 3 and b not in {"دكتور", "الدكتور", "doctor", "dr"}
        ]
        if bits and any(b in t for b in bits):
            return True
    return False


def _clear_draft_held_schedule(phone: str) -> None:
    """Drop held slot/date so a mid-draft doctor switch can restart cleanly."""
    sess = _sess(phone)
    for key in ("slot_id", "held_slot_id", "selected_date"):
        sess.pop(key, None)


def _mid_draft_schedule_change(phone: str, plan: VoicePlan) -> bool:
    """True when mid-booking the user wants another day/time (not UC-003)."""
    sess = _sess(phone)
    awaiting = sess.get("awaiting")
    if awaiting not in {"slot", "date"}:
        return False
    if not sess.get("doctor_id"):
        return False
    if sess.get("current_appt"):
        return False

    change = (plan.slots.change_target or "").strip().lower()
    if change in {"date", "day", "time", "slot"}:
        return True

    t = _norm_simple(_transcript(plan))
    return any(
        p in t
        for p in (
            "اغير اليوم",
            "غير اليوم",
            "تغيير اليوم",
            "عدل اليوم",
            "يوم تاني",
            "يوم اخر",
            "اغير الوقت",
            "غير الوقت",
            "تغيير الوقت",
            "عدل الوقت",
            "ساعه تانيه",
            "change day",
            "change the day",
            "different day",
            "change time",
            "different time",
        )
    )


def _looks_like_new_book_utterance(transcript: str) -> bool:
    """True for clear new-booking speech (EN/AR), incl. common Whisper mangling."""
    t = _norm_simple(transcript)
    if not t:
        return False
    book_cues = (
        "احجز",
        "حجز",
        "عايز احجز",
        "عايزه احجز",
        "عاوز احجز",
        "اعوز احجز",
        "حيكيز",  # Whisper: أحجز
        "حاجز",
        "احجزز",
        "book",
        "booking",
        "appointment",
        "i want to book",
        "make an appointment",
        "schedule",
    )
    return any(c in t for c in book_cues)


def _looks_like_edit_appointment_utterance(transcript: str) -> bool:
    """True when user wants to edit/reschedule an existing appt (اغير / اعدل).

    Must stay on the pick_appointment list — never treat as a new booking.
    """
    t = _norm_simple(transcript)
    if not t:
        return False
    if _looks_like_reschedule_utterance(transcript):
        return True
    edit_cues = (
        "اغير",
        "غير الموعد",
        "غير المعاد",
        "غير معاد",
        "تغيير الموعد",
        "تغيير المعاد",
        "change appointment",
        "change my appointment",
        "edit appointment",
        "modify appointment",
    )
    return any(c in t for c in edit_cues)


def _sanitize_plan(db: Session, plan: VoicePlan, *, phone: str | None = None) -> VoicePlan:
    """Fix planner/STT mistakes that break booking and cancel in practice."""
    plan = _sanitize_plan_slots(db, plan)
    transcript = _transcript(plan)

    # STT often mangles "ألغي معاد" into "ألقي معايا" / "ألغي معاك".
    if _looks_like_cancel_utterance(transcript):
        has_draft = bool(phone and _has_active_booking_draft(phone))
        if has_draft:
            # Mid-booking cancel words = drop the draft, not cancel a real appt.
            if plan.goal in {"book_new", "unclear", "handover", "ask_doctors"}:
                logger.info(
                    "[voice][v2] sanitize goal %s → abandon_draft (active draft, %r)",
                    plan.goal,
                    transcript,
                )
                plan = plan.model_copy(
                    update={"goal": "abandon_draft", "next_step": "show_menu"}
                )
        elif plan.goal in {
            "abandon_draft",
            "handover",
            "ask_doctors",
            "unclear",
            "book_new",
        }:
            logger.info(
                "[voice][v2] sanitize goal %s → cancel_appointment (no draft, %r)",
                plan.goal,
                transcript,
            )
            plan = plan.model_copy(
                update={"goal": "cancel_appointment", "next_step": "pick_appointment"}
            )
        return plan

    if _looks_like_reschedule_utterance(transcript) and plan.goal in {
        "unclear",
        "handover",
        "ask_doctors",
    }:
        logger.info(
            "[voice][v2] sanitize goal %s → reschedule (transcript=%r)",
            plan.goal,
            transcript,
        )
        plan = plan.model_copy(
            update={"goal": "reschedule", "next_step": "pick_appointment"}
        )
        return plan

    # Escape cancel/reschedule appointment list when the patient starts a NEW
    # booking (specialty/doctor target). Keep list for اغير / اعدل.
    if phone and not _looks_like_edit_appointment_utterance(transcript):
        awaiting = _sess(phone).get("awaiting")
        stuck_on_list = awaiting == "pick_appointment" or plan.goal in {
            "cancel_appointment",
            "reschedule",
        }
        has_target = bool(
            (plan.slots.specialty or "").strip()
            or (plan.slots.doctor_name or "").strip()
        )
        wants_new_book = _looks_like_new_book_utterance(transcript) or has_target
        if stuck_on_list and has_target and wants_new_book:
            next_step = (
                "show_doctors"
                if (plan.slots.specialty or plan.slots.doctor_name or "").strip()
                else "ask_specialty"
            )
            logger.info(
                "[voice][v2] sanitize escape %s/%s → book_new/%s (transcript=%r)",
                plan.goal,
                awaiting,
                next_step,
                transcript,
            )
            plan = plan.model_copy(
                update={
                    "goal": "book_new",
                    "next_step": next_step,
                    "followup_goal": None,
                    "slots": plan.slots.model_copy(
                        update={"selected_option_id": None, "change_target": None}
                    ),
                }
            )
            # Leave the cancel/reschedule picker so show_doctors owns the turn.
            _sess(phone)["awaiting"] = None
            _sess(phone).pop("last_options", None)

    return plan


def _sanitize_plan_slots(db: Session, plan: VoicePlan) -> VoicePlan:
    """Fix the two LLM mistakes that break booking in practice.

    1) Specialty word parked in doctor_name ("دكتور عيون" → doctor='عيون')
    2) Previous doctor carried into a new specialty ask ("دكتور قلب" + doctor=منى)
    """
    from app.services.voice_fastpath import find_doctor_by_hint

    slots = plan.slots
    transcript = _transcript(plan)
    tnorm = _norm_simple(transcript)
    doctor_name = (slots.doctor_name or "").strip() or None
    specialty = (slots.specialty or "").strip() or None
    alternatives = list(slots.doctor_alternatives or [])

    def _as_specialty(raw: str | None) -> str | None:
        if not raw or not str(raw).strip():
            return None
        if find_doctor_by_hint(db, DEFAULT_CLINIC_ID, str(raw)):
            return None
        as_dept = doctor_service.find_department(db, DEFAULT_CLINIC_ID, name=str(raw))
        if as_dept:
            return as_dept.name_ar or as_dept.name_en or str(raw)
        if doctor_service.is_specialty_word(raw):
            return doctor_service.fuzzy_specialty_canonical(raw) or str(raw)
        return None

    # Doctor slot / alts that are really specialties (incl. Whisper near-miss).
    # Spoken specialty-as-doctor overrides a stale specialty slot (نيسا vs أعصاب).
    remapped_from_doctor = False
    if doctor_name:
        mapped = _as_specialty(doctor_name)
        if mapped:
            if specialty and specialty != mapped:
                logger.info(
                    "[voice][v2] sanitize specialty %r → %r (from doctor_name=%r)",
                    specialty,
                    mapped,
                    doctor_name,
                )
            else:
                logger.info(
                    "[voice][v2] sanitize doctor_name=%r → specialty=%r",
                    doctor_name,
                    mapped,
                )
            specialty = mapped
            doctor_name = None
            remapped_from_doctor = True
            # Planner alts (e.g. ليلى) often belong to the previous specialty.
            alternatives = []
    if not specialty:
        for alt in alternatives:
            mapped = _as_specialty(alt)
            if mapped:
                specialty = mapped
                logger.info(
                    "[voice][v2] sanitize doctor_alt=%r → specialty=%r",
                    alt,
                    specialty,
                )
                break
    # Token scan: "د. عنايزة" style misses where the whole string is too noisy.
    if not specialty and tnorm:
        for tok in tnorm.replace("،", " ").replace(",", " ").split():
            if len(tok) < 3 or tok in {"دكتور", "الدكتور", "doctor", "dr", "د"}:
                continue
            mapped = _as_specialty(tok)
            if mapped:
                specialty = mapped
                if doctor_name and _norm_simple(doctor_name) == tok:
                    doctor_name = None
                    remapped_from_doctor = True
                    alternatives = []
                logger.info(
                    "[voice][v2] sanitize transcript token=%r → specialty=%r",
                    tok,
                    specialty,
                )
                break

    inferred = doctor_service.infer_department_from_text(
        db, DEFAULT_CLINIC_ID, transcript
    )
    if inferred:
        inferred_label = inferred.name_ar or inferred.name_en
        slot_dept = (
            doctor_service.find_department(db, DEFAULT_CLINIC_ID, name=specialty)
            if specialty
            else None
        )
        # infer_* only fires when the word is in the transcript — trust speech
        # over a stale specialty the model carried from the previous turn.
        if not slot_dept or slot_dept.department_id != inferred.department_id:
            if specialty and specialty != inferred_label:
                logger.info(
                    "[voice][v2] sanitize specialty %r → %r (from transcript)",
                    specialty,
                    inferred_label,
                )
            specialty = inferred_label
            if remapped_from_doctor or slot_dept is None:
                alternatives = []

    # Drop a carried doctor only when THIS utterance names a specialty
    # ("دكتور قلب" after Mona). Date/time-only turns keep the context doctor
    # even if specialty is still sitting in the slots from earlier turns.
    specialty_spoken_now = remapped_from_doctor or inferred is not None or (
        specialty is not None and specialty != (slots.specialty or None)
    )
    if specialty_spoken_now and doctor_name and tnorm:
        bits = [
            b
            for b in _norm_simple(doctor_name).split()
            if len(b) >= 3 and b not in {"دكتور", "الدكتور", "doctor", "dr"}
        ]
        if bits and not any(b in tnorm for b in bits):
            logger.info(
                "[voice][v2] sanitize drop carried doctor=%r (specialty=%r)",
                doctor_name,
                specialty,
            )
            doctor_name = None

    if (
        doctor_name == (slots.doctor_name or None)
        and specialty == (slots.specialty or None)
        and alternatives == list(slots.doctor_alternatives or [])
    ):
        return plan

    clear_option = bool(
        specialty_spoken_now
        and not doctor_name
        and (slots.selected_option_id or "").startswith("doctor_")
    )
    return plan.model_copy(
        update={
            "slots": slots.model_copy(
                update={
                    "doctor_name": doctor_name,
                    "specialty": specialty,
                    "doctor_alternatives": alternatives,
                    **({"selected_option_id": None} if clear_option else {}),
                }
            )
        }
    )


def _resolve_doctor(db: Session, plan: VoicePlan) -> tuple[Doctor | None, str | None]:
    """Resolve doctor_name (then any alternative) to a real doctor.

    Returns (doctor, unresolved_name). `unresolved_name` is set only when a name
    was actually spoken but matched nothing — that is the signal to degrade with
    an explanation rather than pretend nothing was asked for.
    """
    from app.services.voice_fastpath import find_doctor_by_hint

    candidates = [plan.slots.doctor_name, *plan.slots.doctor_alternatives]
    spoken = next((c for c in candidates if c and c.strip()), None)
    for candidate in candidates:
        if not candidate or not candidate.strip():
            continue
        if doctor_service.find_department(db, DEFAULT_CLINIC_ID, name=str(candidate)):
            continue
        doctor = find_doctor_by_hint(db, DEFAULT_CLINIC_ID, str(candidate))
        if doctor:
            return doctor, None
    return None, spoken


def _resolve_specialty(db: Session, plan: VoicePlan):
    """Resolve specialty (or fall back to scanning the transcript)."""
    spoken = (plan.slots.specialty or "").strip()
    if spoken:
        dept = doctor_service.find_department(db, DEFAULT_CLINIC_ID, name=spoken)
        if dept:
            return dept, None
    parked = (plan.slots.doctor_name or "").strip()
    if parked:
        dept = doctor_service.find_department(db, DEFAULT_CLINIC_ID, name=parked)
        if dept:
            return dept, None
    inferred = doctor_service.infer_department_from_text(
        db, DEFAULT_CLINIC_ID, _transcript(plan)
    )
    if inferred:
        return inferred, None
    return None, spoken or None


def _session_doctor_id(phone: str) -> int | None:
    raw = _sess(phone).get("doctor_id")
    return int(raw) if raw else None


def _availability(db: Session, doctor_id: int) -> dict[str, list[dict]]:
    booking_service.release_expired_holds(db, clinic_id=DEFAULT_CLINIC_ID)
    avail = booking_service.get_available_dates_and_slots(
        db, doctor_id=doctor_id, clinic_id=DEFAULT_CLINIC_ID
    )
    return avail.get("dates") or {}


def _resolve_date(
    plan: VoicePlan,
    dates: dict[str, list[dict]],
) -> str | None:
    """Pick a real available date from the plan's hint / flexibility / transcript."""
    from app.services.voice_fastpath import resolve_date_key

    if not dates:
        return None
    available = set(dates.keys())
    key = resolve_date_key(
        date_hint=plan.slots.date,
        transcript=_transcript(plan),
        available=available,
    )
    if key:
        return key
    # "أقرب موعد" / "any day" — the patient explicitly deferred to us.
    if plan.slots.date_flexibility in {"earliest", "any"}:
        return sorted(available)[0]
    return None


def _resolve_time(plan: VoicePlan) -> str | None:
    from app.services.voice_fastpath import _normalize_time_hint

    return _normalize_time_hint(plan.slots.time, transcript=_transcript(plan))


# ---------------------------------------------------------------------------
# Presentation helpers (reuse the engine's renderers so voice and taps match)
# ---------------------------------------------------------------------------


def _present_doctor_list(db: Session, phone: str, conversation) -> bool:
    """All-doctors list, tappable as doctor_<id> in BOOKING_DOCTOR."""
    from app.graph.conversation_engine import _offer_doctors_by_name_list

    sess = _sess(phone)
    sess["flow"] = sess.get("flow") or "booking"
    sess["doctor_pick_mode"] = "by_name"
    sess["awaiting"] = "doctor"
    set_conversation_state(
        db, conversation, ConversationState.BOOKING_DOCTOR, current_intent="voice_v2_doctors"
    )
    ok = _offer_doctors_by_name_list(phone, db, conversation, reset=True)
    db.commit()
    return bool(ok)


def _present_department_doctors(db: Session, phone: str, conversation, department_id: int) -> bool:
    from app.graph.conversation_engine import _show_doctor_cards

    sess = _sess(phone)
    sess["flow"] = sess.get("flow") or "booking"
    sess["department_id"] = department_id
    sess["doctor_pick_mode"] = "by_specialty"
    sess["awaiting"] = "doctor"
    set_conversation_state(
        db, conversation, ConversationState.BOOKING_DOCTOR, current_intent="voice_v2_specialty"
    )
    ok = _show_doctor_cards(phone, db, department_id)
    db.commit()
    return bool(ok)


def _present_dates(db: Session, phone: str, doctor_id: int) -> bool:
    """Day picker for a doctor (engine helper also handles the no-slots case)."""
    from app.graph.conversation_engine import continue_after_doctor_selected

    continue_after_doctor_selected(db, phone=phone, doctor_id=doctor_id)
    return True


def _present_slots(
    db: Session,
    phone: str,
    conversation,
    *,
    doctor_id: int,
    date_key: str,
    day_slots: list[dict],
) -> bool:
    from app.graph.conversation_engine import (
        _date_option_title,
        _offer_slots_list,
    )

    sess = _sess(phone)
    sess["doctor_id"] = doctor_id
    sess["selected_date"] = date_key
    sess["awaiting"] = "slot"
    set_conversation_state(
        db, conversation, ConversationState.BOOKING_SLOT, current_intent="voice_v2_slots"
    )
    lang = _lang(conversation, phone)
    _offer_slots_list(
        phone,
        day_slots,
        lang,
        body=i18n.choose_slot_on_date(lang, _date_option_title(date_key, lang)),
        reset=True,
        with_change_day=True,
    )
    db.commit()
    return True


def _doctor_label(doctor: Doctor, lang: str) -> str:
    if i18n.is_english(lang):
        return doctor.name_en or doctor.name_ar or f"Doctor {doctor.doctor_id}"
    return doctor.name_ar or doctor.name_en or f"دكتور {doctor.doctor_id}"


# ---------------------------------------------------------------------------
# Step handlers
# ---------------------------------------------------------------------------


def _step_show_menu(db: Session, phone: str, plan: VoicePlan, conversation) -> ExecResult:
    from app.graph.conversation_engine import _clear_draft, _send_main_menu

    lang = _lang(conversation, phone)
    if plan.goal == "abandon_draft":
        # Distinct from cancelling a real appointment — say so, then reset.
        _say(phone, i18n.voice_draft_abandoned(lang))
    _clear_draft(phone)
    _send_main_menu(phone, db, conversation)
    db.commit()
    return ExecResult(handled=True, step="show_menu", requested_step="show_menu")


def _step_ask_specialty(db: Session, phone: str, plan: VoicePlan, conversation) -> ExecResult:
    """No usable doctor/specialty yet → open the department list."""
    from app.graph.conversation_engine import _offer_departments_list

    departments = doctor_service.list_departments(db, DEFAULT_CLINIC_ID)
    if not departments:
        # No departments configured → the all-doctors list is the real fallback.
        # Deliberately NOT the main menu: recursing into it made the funnel four
        # levels deep and risked a partial reply followed by a duplicate one.
        ok = _present_doctor_list(db, phone, conversation)
        return ExecResult(
            handled=bool(ok),
            step="show_doctors",
            requested_step="ask_specialty",
            reason="no_departments",
        )

    sess = _sess(phone)
    sess["flow"] = sess.get("flow") or "booking"
    sess["awaiting"] = "department"
    set_conversation_state(
        db, conversation, ConversationState.BOOKING_DOCTOR, current_intent="voice_v2_departments"
    )
    _offer_departments_list(phone, db, conversation, reset=True)
    db.commit()
    return ExecResult(handled=True, step="ask_specialty", requested_step="ask_specialty")


def _looks_like_specialty_attempt(name: str | None) -> bool:
    """Single Arabic token — often a mangled specialty, not a person name."""
    import re

    raw = (name or "").strip()
    if not raw or " " in raw:
        return False
    if re.search(r"[A-Za-z]", raw):
        return False
    if not re.search(r"[\u0600-\u06FF]", raw):
        return False
    return 3 <= len(raw) <= 16


def _step_show_doctors(db: Session, phone: str, plan: VoicePlan, conversation) -> ExecResult:
    """A doctor or specialty was spoken. Resolve it, or explain the miss."""
    lang = _lang(conversation, phone)
    requested = "show_doctors"

    # Specialty first when no real person was named (e.g. "دكتور عيون" / "دكتور قلب").
    doctor, unresolved = _resolve_doctor(db, plan)
    if not doctor:
        dept, unresolved_specialty = _resolve_specialty(db, plan)
        if dept:
            _present_department_doctors(db, phone, conversation, dept.department_id)
            return ExecResult(handled=True, step="show_doctors", requested_step=requested)
        # Whisper often turns "أعصاب" into a fake Arabic doctor name. Prefer the
        # specialty picker over "doctor not found" + full clinic list.
        if unresolved and _looks_like_specialty_attempt(unresolved):
            _say(phone, i18n.voice_specialty_not_found(lang, unresolved))
            return _degraded(
                _step_ask_specialty(db, phone, plan, conversation),
                requested,
                f"specialty_not_found:{unresolved}",
            )
        if unresolved:
            _say(phone, i18n.voice_doctor_not_found(lang, unresolved))
            _present_doctor_list(db, phone, conversation)
            return ExecResult(
                handled=True,
                step="show_doctors",
                requested_step=requested,
                reason=f"doctor_not_found:{unresolved}",
            )
        if unresolved_specialty:
            _say(phone, i18n.voice_specialty_not_found(lang, unresolved_specialty))
            return _degraded(
                _step_ask_specialty(db, phone, plan, conversation),
                requested,
                f"specialty_not_found:{unresolved_specialty}",
            )
        # Already on a doctor list with open options — don't dump specialty picker
        # on garbage / unmatchable speech; ask again and keep the list.
        if _sess(phone).get("awaiting") == "doctor" and _sess(phone).get("last_options"):
            return _step_clarify(db, phone, plan, conversation)
        return _degraded(
            _step_ask_specialty(db, phone, plan, conversation),
            requested,
            "no_doctor_or_specialty",
        )

    # Real person named → their day picker.
    _present_dates(db, phone, doctor.doctor_id)
    return ExecResult(handled=True, step="ask_date", requested_step=requested)


def _step_ask_date(db: Session, phone: str, plan: VoicePlan, conversation) -> ExecResult:
    """Needs a doctor. Resolve from the plan, else from session, else degrade."""
    requested = "ask_date"
    doctor, unresolved = _resolve_doctor(db, plan)
    # If they only named a specialty, do NOT reuse the previous session doctor.
    dept, _ = _resolve_specialty(db, plan)
    if not doctor and dept and not (plan.slots.doctor_name or "").strip():
        result = _step_show_doctors(db, phone, plan, conversation)
        return _degraded(result, requested, "specialty_needs_doctor_pick")

    doctor_id = doctor.doctor_id if doctor else _session_doctor_id(phone)

    if not doctor_id:
        lang = _lang(conversation, phone)
        if unresolved:
            _say(phone, i18n.voice_doctor_not_found(lang, unresolved))
        else:
            _say(phone, i18n.voice_need_doctor_first(lang))
        result = _step_show_doctors(db, phone, plan, conversation)
        return _degraded(result, requested, "missing_doctor")

    _present_dates(db, phone, doctor_id)
    return ExecResult(handled=True, step="ask_date", requested_step=requested)


def _step_show_slots(db: Session, phone: str, plan: VoicePlan, conversation) -> ExecResult:
    """Needs doctor + a date that actually has openings."""
    requested = "show_slots"
    doctor, unresolved = _resolve_doctor(db, plan)
    doctor_id = doctor.doctor_id if doctor else _session_doctor_id(phone)
    lang = _lang(conversation, phone)

    if not doctor_id:
        if unresolved:
            _say(phone, i18n.voice_doctor_not_found(lang, unresolved))
        else:
            _say(phone, i18n.voice_need_doctor_first(lang))
        return _degraded(
            _step_show_doctors(db, phone, plan, conversation), requested, "missing_doctor"
        )

    resolved = doctor or doctor_service.get_doctor(db, doctor_id, clinic_id=DEFAULT_CLINIC_ID)
    doctor_name = _doctor_label(resolved, lang) if resolved else str(doctor_id)
    dates = _availability(db, doctor_id)

    if not dates:
        _say(phone, i18n.voice_doctor_fully_booked(lang, doctor_name))
        return _degraded(
            _step_show_doctors(db, phone, plan, conversation), requested, "doctor_fully_booked"
        )

    date_key = _resolve_date(plan, dates) or _sess(phone).get("selected_date")
    if not date_key or date_key not in dates:
        # Asked for a day with nothing free (or no day at all) → day picker.
        if plan.slots.date:
            from app.graph.conversation_engine import _date_option_title

            _say(
                phone,
                i18n.voice_no_slots_on_date(
                    lang, doctor_name, _date_option_title(str(plan.slots.date), lang)
                ),
            )
        _present_dates(db, phone, doctor_id)
        return ExecResult(
            handled=True,
            step="ask_date",
            requested_step=requested,
            reason="date_unavailable",
        )

    _present_slots(
        db,
        phone,
        conversation,
        doctor_id=doctor_id,
        date_key=date_key,
        day_slots=dates.get(date_key) or [],
    )
    return ExecResult(handled=True, step="show_slots", requested_step=requested)


def _step_hold_slot(db: Session, phone: str, plan: VoicePlan, conversation) -> ExecResult:
    """Needs doctor + date + an exact time that is genuinely free."""
    from app.graph.conversation_engine import _date_option_title
    from app.services.voice_fastpath import match_slot

    requested = "hold_slot"
    doctor, unresolved = _resolve_doctor(db, plan)
    doctor_id = doctor.doctor_id if doctor else _session_doctor_id(phone)
    lang = _lang(conversation, phone)

    if not doctor_id:
        if unresolved:
            _say(phone, i18n.voice_doctor_not_found(lang, unresolved))
        else:
            _say(phone, i18n.voice_need_doctor_first(lang))
        return _degraded(
            _step_show_doctors(db, phone, plan, conversation), requested, "missing_doctor"
        )

    resolved = doctor or doctor_service.get_doctor(db, doctor_id, clinic_id=DEFAULT_CLINIC_ID)
    doctor_name = _doctor_label(resolved, lang) if resolved else str(doctor_id)
    dates = _availability(db, doctor_id)
    if not dates:
        _say(phone, i18n.voice_doctor_fully_booked(lang, doctor_name))
        return _degraded(
            _step_show_doctors(db, phone, plan, conversation), requested, "doctor_fully_booked"
        )

    date_key = _resolve_date(plan, dates) or _sess(phone).get("selected_date")
    if not date_key or date_key not in dates:
        return _degraded(
            _step_show_slots(db, phone, plan, conversation), requested, "date_unavailable"
        )

    matched = match_slot(
        {date_key: dates.get(date_key) or []},
        date_hint=date_key,
        time_hint=_resolve_time(plan) or plan.slots.time,
        transcript=_transcript(plan),
    )
    date_label = _date_option_title(date_key, lang)
    if not matched:
        # Time didn't land on a free slot → show that day instead of guessing.
        _say(phone, i18n.voice_time_not_available(lang, date_label))
        _present_slots(
            db,
            phone,
            conversation,
            doctor_id=doctor_id,
            date_key=date_key,
            day_slots=dates.get(date_key) or [],
        )
        return ExecResult(
            handled=True, step="show_slots", requested_step=requested, reason="time_not_available"
        )

    slot_id = int(matched.get("slot_id") or matched.get("id") or 0)
    if not slot_id:
        return _degraded(
            _step_show_slots(db, phone, plan, conversation), requested, "slot_id_missing"
        )

    try:
        booking_service.hold_slot(
            db,
            slot_id=slot_id,
            clinic_id=DEFAULT_CLINIC_ID,
            held_by_phone=phone,
            hold_minutes=SLOT_HOLD_MINUTES,
        )
    except BookingError as exc:
        # Raced with another patient — explain, then re-show the same day.
        logger.info("[voice][v2] hold failed slot=%s: %s", slot_id, exc)
        _say(phone, i18n.voice_slot_taken(lang, doctor_name, date_label))
        fresh = _availability(db, doctor_id)
        _present_slots(
            db,
            phone,
            conversation,
            doctor_id=doctor_id,
            date_key=date_key,
            day_slots=fresh.get(date_key) or [],
        )
        return ExecResult(
            handled=True, step="show_slots", requested_step=requested, reason="slot_taken"
        )

    sess = _sess(phone)
    sess["flow"] = "booking"
    sess["doctor_id"] = doctor_id
    sess["selected_date"] = date_key
    sess["slot_id"] = slot_id
    sess["awaiting"] = "patient_name"
    sess.pop("last_options", None)
    set_conversation_state(
        db, conversation, ConversationState.PATIENT_DETAILS, current_intent="voice_v2_hold"
    )
    start = matched.get("slot_start") or matched.get("start")
    when = start.strftime("%Y-%m-%d %H:%M") if isinstance(start, datetime) else str(start)
    _say(phone, i18n.voice_slot_held(lang, doctor_name, when))
    db.commit()
    logger.info("[voice][v2] held slot=%s doctor=%s phone=%s", slot_id, doctor_id, phone)

    # V2 win: the name was already spoken ("احجز لمحمد مع د. أحمد بكرة 2") — feed
    # it straight in instead of asking for something we already have.
    if plan.slots.patient_name:
        _feed_patient_name(db, phone, plan.slots.patient_name)

    return ExecResult(handled=True, step="hold_slot", requested_step=requested)


def _feed_engine(
    db: Session,
    phone: str,
    *,
    text: str = "",
    payload_id: str | None = None,
) -> None:
    """One path into the conversation engine — no fastpath rewrite."""
    from app.graph import process_incoming_message

    process_incoming_message(
        db,
        phone=phone,
        text=text or "",
        payload_id=payload_id,
        message_type="interactive" if payload_id else "text",
        keep_language=True,
    )


def _step_ask_patient_name(db: Session, phone: str, plan: VoicePlan, conversation) -> ExecResult:
    """Feed the spoken/extracted name (overwrite any previous), or ask for it."""
    requested = "ask_patient_name"
    name = (plan.slots.patient_name or "").strip()
    if not name and _sess(phone).get("awaiting") in {
        "patient_name",
        "known_patient_confirm",
    }:
        name = _strip_patient_name_leadin(_transcript(plan))
    if name:
        # Always overwrite — user may be correcting a previous name.
        _sess(phone)["awaiting"] = "patient_name"
        _feed_engine(db, phone, text=name)
        return ExecResult(handled=True, step="ask_patient_name", requested_step=requested)

    lang = _lang(conversation, phone)
    _sess(phone)["awaiting"] = "patient_name"
    set_conversation_state(
        db, conversation, ConversationState.PATIENT_DETAILS, current_intent="voice_v2_name"
    )
    _say(phone, i18n.ask_patient_full_name(lang))
    db.commit()
    return ExecResult(handled=True, step="ask_patient_name", requested_step=requested)


def _step_confirm_booking(db: Session, phone: str, plan: VoicePlan, conversation) -> ExecResult:
    """Patient agreed — let the engine finalize with a confirm seed."""
    lang = _lang(conversation, phone)
    seed = "Confirm" if i18n.is_english(lang) else "تأكيد"
    _feed_engine(db, phone, text=seed)
    return ExecResult(handled=True, step="confirm_booking", requested_step="confirm_booking")


def _step_clarify(db: Session, phone: str, plan: VoicePlan, conversation) -> ExecResult:
    """Didn't catch it — nudge and keep open lists; menu only when nothing is open."""
    from app.graph.conversation_engine import _send_main_menu

    lang = _lang(conversation, phone)
    sess = _sess(phone)
    _say(phone, i18n.not_understood_menu(lang))
    # Prefer keeping the open picker (change-type / slots) over dumping the menu.
    if not sess.get("last_options"):
        _send_main_menu(phone, db, conversation)
    db.commit()
    return ExecResult(handled=True, step="clarify", requested_step="clarify")


def _reschedule_change_feed_text(plan: VoicePlan, lang: str) -> str | None:
    """Map change_target / option label to the engine's change-type button text."""
    opt = (plan.slots.selected_option_id or "").strip()
    if opt in i18n.RESCHEDULE_CHANGE_TIME | i18n.RESCHEDULE_CHANGE_DAY | i18n.RESCHEDULE_CHANGE_DOCTOR:
        # Prefer the Arabic/English labels the buttons actually send.
        preferred = {
            "time": ("تعديل الوقت", "Change time"),
            "date": ("تعديل اليوم", "Change day"),
            "doctor": ("تغيير الطبيب", "Change doctor"),
        }
        for key, (ar, en) in preferred.items():
            bucket = {
                "time": i18n.RESCHEDULE_CHANGE_TIME,
                "date": i18n.RESCHEDULE_CHANGE_DAY,
                "doctor": i18n.RESCHEDULE_CHANGE_DOCTOR,
            }[key]
            if opt in bucket:
                return en if i18n.is_english(lang) else ar
        return opt
    change = (plan.slots.change_target or "").strip().lower()
    en = i18n.is_english(lang)
    if change in {"time", "slot"}:
        return "Change time" if en else "تعديل الوقت"
    if change in {"date", "day"}:
        return "Change day" if en else "تعديل اليوم"
    if change == "doctor":
        return "Change doctor" if en else "تغيير الطبيب"
    return None


def _step_pick_appointment(
    db: Session, phone: str, plan: VoicePlan, conversation
) -> ExecResult:
    """Start cancel/reschedule list — never feed the transcript into the menu chooser."""
    from app.graph.conversation_engine import _start_cancel_flow, _start_reschedule_flow

    requested = "pick_appointment"
    if plan.goal == "reschedule":
        _start_reschedule_flow(phone, db, conversation)
        return ExecResult(handled=True, step="pick_appointment", requested_step=requested)

    # cancel_appointment (default) and any other goal that landed here
    _start_cancel_flow(phone, db, conversation)
    return ExecResult(handled=True, step="pick_appointment", requested_step=requested)


def _step_handover(db: Session, phone: str, plan: VoicePlan, conversation) -> ExecResult:
    """Reception handover via stable menu id — not free-text choice mapping."""
    _feed_engine(db, phone, text="", payload_id="menu_4")
    return ExecResult(handled=True, step="handover", requested_step="handover")


def _feed_patient_name(db: Session, phone: str, name: str) -> None:
    _feed_engine(db, phone, text=name)


def _degraded(result: ExecResult, requested_step: str, reason: str) -> ExecResult:
    """Re-tag a handler's result as a downgrade from `requested_step`."""
    if not result.handled:
        return result
    return ExecResult(
        handled=True,
        step=result.step or requested_step,
        requested_step=requested_step,
        reason=reason or result.reason,
    )


_STEP_HANDLERS = {
    "show_menu": _step_show_menu,
    "ask_specialty": _step_ask_specialty,
    "show_doctors": _step_show_doctors,
    "ask_date": _step_ask_date,
    "show_slots": _step_show_slots,
    "hold_slot": _step_hold_slot,
    "ask_patient_name": _step_ask_patient_name,
    "confirm_booking": _step_confirm_booking,
    "clarify": _step_clarify,
    "pick_appointment": _step_pick_appointment,
    "handover": _step_handover,
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def execute_plan(
    db: Session,
    *,
    phone: str,
    plan: VoicePlan,
    conversation,
) -> ExecResult:
    """Run the planner's step. Always owns the turn (handled=True)."""
    plan = _sanitize_plan(db, plan, phone=phone)
    plan = _coerce_plan_for_name_step(phone, plan)
    step = plan.next_step
    transcript = _transcript(plan)

    # Basmala / greeting-only must not invent schedule progress.
    if _is_filler_utterance(transcript) and plan.goal not in {
        "cancel_appointment",
        "handover",
        "abandon_draft",
    }:
        logger.info("[voice][v2] filler utterance → clarify phone=%s %r", phone, transcript)
        return _step_clarify(db, phone, plan, conversation)

    # Goal wins over a wrong next_step: cancel must open the appointment picker.
    # Reschedule: start the list UNLESS we're already mid-change on a picked appt
    # ("أعدل الوقت" at change_type must not restart the appt list).
    # Mid-booking "change doctor" must restart the draft, not UC-003.
    if plan.goal == "cancel_appointment":
        step = "pick_appointment"
        plan = plan.model_copy(update={"next_step": "pick_appointment"})
    elif plan.goal == "reschedule":
        if _reschedule_midflow(phone):
            feed = _reschedule_change_feed_text(plan, _lang(conversation, phone))
            if feed and _sess(phone).get("awaiting") == "change_type":
                logger.info(
                    "[voice][v2] mid-reschedule change → %r phone=%s", feed, phone
                )
                _feed_engine(db, phone, text=feed)
                return ExecResult(
                    handled=True,
                    step="ask_change_target",
                    requested_step=step or "ask_change_target",
                )
            # Otherwise keep planner step (show_slots / ask_date / …) with session doctor.
        elif _mid_draft_doctor_switch(phone, plan):
            _clear_draft_held_schedule(phone)
            next_for_switch = (
                "show_doctors"
                if (plan.slots.specialty or plan.slots.doctor_name or "").strip()
                else "ask_specialty"
            )
            logger.info(
                "[voice][v2] mid-draft doctor switch → %s (not reschedule list) phone=%s",
                next_for_switch,
                phone,
            )
            step = next_for_switch
            plan = plan.model_copy(
                update={
                    "goal": "book_new",
                    "next_step": next_for_switch,
                    "slots": plan.slots.model_copy(
                        update={"selected_option_id": None, "change_target": None}
                    ),
                }
            )
        elif _mid_draft_schedule_change(phone, plan):
            next_for_sched = (
                plan.next_step
                if plan.next_step in {"ask_date", "show_slots"}
                else "ask_date"
            )
            if next_for_sched == "ask_date":
                sess = _sess(phone)
                sess.pop("selected_date", None)
                sess.pop("slot_id", None)
                sess.pop("held_slot_id", None)
            logger.info(
                "[voice][v2] mid-draft day/time change → %s (not reschedule list) phone=%s",
                next_for_sched,
                phone,
            )
            step = next_for_sched
            plan = plan.model_copy(
                update={
                    "goal": "book_new",
                    "next_step": next_for_sched,
                    "slots": plan.slots.model_copy(
                        update={"selected_option_id": None}
                    ),
                }
            )
        else:
            step = "pick_appointment"
            plan = plan.model_copy(update={"next_step": "pick_appointment"})
    elif plan.goal == "handover":
        step = "handover"
        plan = plan.model_copy(update={"next_step": "handover"})

    # Spoken patient name must win over "نفس المريض" / appt_* hallucinations.
    patient = (plan.slots.patient_name or "").strip()
    opt = (plan.slots.selected_option_id or "").strip()
    awaiting = _sess(phone).get("awaiting")
    name_intro = _looks_like_patient_name_intro(transcript)
    conflicting_opt = bool(
        opt
        and (
            opt in i18n.SAME_PATIENT_CHOICES
            or opt in i18n.NAME_CHANGED_CHOICES
            or opt.startswith("appt_")
        )
    )
    if (patient or name_intro) and conflicting_opt:
        logger.info(
            "[voice][v2] prefer patient_name over option=%r phone=%s",
            opt,
            phone,
        )
        # Name spoken while picking an existing appointment → keep list, don't guess.
        if opt.startswith("appt_") and awaiting == "pick_appointment":
            return _step_clarify(db, phone, plan, conversation)
        plan = plan.model_copy(
            update={
                "goal": "book_new" if plan.goal == "reschedule" else plan.goal,
                "next_step": "ask_patient_name",
                "slots": plan.slots.model_copy(update={"selected_option_id": None}),
            }
        )
        step = "ask_patient_name"
        opt = ""

    # Mid-draft doctor/specialty change even when the planner kept goal=book_new
    # but stuck "نفس المريض" / confirm as the option.
    if _mid_draft_doctor_switch(phone, plan) and plan.goal != "reschedule":
        _clear_draft_held_schedule(phone)
        next_for_switch = (
            "show_doctors"
            if (plan.slots.specialty or plan.slots.doctor_name or "").strip()
            else "ask_specialty"
        )
        logger.info(
            "[voice][v2] mid-draft doctor switch (goal=%s) → %s phone=%s",
            plan.goal,
            next_for_switch,
            phone,
        )
        step = next_for_switch
        plan = plan.model_copy(
            update={
                "goal": "book_new",
                "next_step": next_for_switch,
                "slots": plan.slots.model_copy(
                    update={"selected_option_id": None, "change_target": None}
                ),
            }
        )
    # Named doctor must never open the specialty picker. Planner sometimes
    # hedges to ask_specialty even with doctor_name="عمرو سليم" (esp. post_cancel).
    if step == "ask_specialty" and (plan.slots.doctor_name or "").strip():
        logger.info(
            "[voice][v2] rewrite ask_specialty → show_doctors (doctor=%r)",
            plan.slots.doctor_name,
        )
        step = "show_doctors"
        plan = plan.model_copy(update={"next_step": "show_doctors"})

    # Specialty known + no person named → show that department's doctors.
    # Skip when a doctor is already selected in-session and this turn is
    # date/slot progress (user said "Sunday at 2" after أعصاب / a doctor pick).
    session_doctor = _session_doctor_id(phone)
    specialty_only = (
        (plan.slots.specialty or "").strip()
        and not (plan.slots.doctor_name or "").strip()
    )
    advancing_schedule = step in {"ask_date", "show_slots", "hold_slot"} and (
        plan.slots.date or plan.slots.time or plan.slots.date_flexibility
    )
    if (
        step in {"ask_date", "show_slots", "hold_slot", "ask_specialty"}
        and specialty_only
        and not (session_doctor and advancing_schedule)
        and not _reschedule_midflow(phone)
    ):
        logger.info(
            "[voice][v2] rewrite %s → show_doctors (specialty-only %r)",
            step,
            plan.slots.specialty,
        )
        step = "show_doctors"
        plan = plan.model_copy(update={"next_step": "show_doctors"})

    if plan.followup_goal:
        _sess(phone)["voice_followup_goal"] = plan.followup_goal

    # Option pick from an open list — one payload to the engine, done.
    # Never for cancel/handover/abandon. Reschedule mid-change options are
    # handled above; starting-reschedule must not feed free-text options.
    opt = (plan.slots.selected_option_id or "").strip()
    schedule_spoken = bool(
        plan.slots.date or plan.slots.time or plan.slots.date_flexibility
    )
    if (
        opt
        and plan.goal
        not in {"cancel_appointment", "reschedule", "handover", "abandon_draft"}
        and not (opt.startswith("doctor_") and schedule_spoken)
        and not (
            opt.startswith("doctor_")
            and (plan.slots.specialty or "").strip()
            and not (plan.slots.doctor_name or "").strip()
        )
    ):
        logger.info("[voice][v2] option=%s phone=%s", opt, phone)
        _feed_engine(db, phone, text=transcript or opt, payload_id=opt)
        return ExecResult(handled=True, step="select_option", requested_step=step)

    handler = _STEP_HANDLERS.get(step)

    token = _sent_count.set(0)
    try:
        if handler is not None:
            result = handler(db, phone, plan, conversation)
        else:
            # Cancel / reschedule / handover / etc.: give the transcript to the
            # normal engine. Simple — no V1 voice_fastpath rewrite.
            text = _transcript(plan)
            if not text:
                result = _step_clarify(db, phone, plan, conversation)
            else:
                logger.info(
                    "[voice][v2] step=%s → engine transcript phone=%s", step, phone
                )
                _feed_engine(db, phone, text=text)
                result = ExecResult(
                    handled=True, step=step, requested_step=step, reason="engine_feed"
                )
    except Exception:
        logger.exception("[voice][v2] step=%s raised phone=%s", step, phone)
        db.rollback()
        if _sent_count.get():
            return ExecResult(
                handled=True,
                step="clarify",
                requested_step=step,
                reason="handler_error_after_reply",
            )
        # Last resort: still own the turn with a clarify, never fall to V1 maze.
        try:
            return _step_clarify(db, phone, plan, conversation)
        except Exception:
            return ExecResult(
                handled=True, step="clarify", requested_step=step, reason="handler_error"
            )
    finally:
        _sent_count.reset(token)

    if result.degraded:
        logger.info(
            "[voice][v2] step %s → %s (degraded: %s) phone=%s",
            result.requested_step,
            result.step,
            result.reason or "unspecified",
            phone,
        )
    else:
        logger.info("[voice][v2] step %s ok phone=%s", result.step or step, phone)
    return result
