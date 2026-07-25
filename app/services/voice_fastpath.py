"""Context-aware voice routing across the full booking workflow.

Covers: menu intents, specialty/doctor jumps, date/time mid-flow,
patient details, confirm, inquiry, reschedule/cancel entry, and
spoken option selection — without wiping mid-flow sessions wrongly.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core import i18n_bot as i18n
from app.core.config import DEFAULT_CLINIC_ID, DEFAULT_TENANT_ID, SLOT_HOLD_MINUTES
from app.db.enums import ConversationState
from app.graph.conversation_engine import _sess
from app.models.doctor_models import Doctor
from app.services import booking_service, doctor_service, whatsapp_client as wa
from app.services.booking_service import BookingError
from app.services.conversation_service import (
    get_or_create_conversation,
    set_conversation_state,
)

logger = logging.getLogger(__name__)

# Free-text steps: never run specialty/book_direct diversion
_FREE_TEXT_AWAITING = {
    "patient_name",
    "mrn_value",
    "dob_value",
}

# Button/list steps: prefer select_option / spoken mapping over new booking
_OPTION_AWAITING = {
    "department",
    "doctor",
    "date",
    "slot",
    "confirm",
    "summary",
    "mrn_optional",
    "dob_gate",
    "inquiry_book_cta",
    "no_slots_alt",
    "pick_appointment",
    "change_type",
    "post_cancel",
}

# Public aliases for voice_service CURRENT_STEP templates (keep in sync)
VOICE_FREE_TEXT_AWAITING = _FREE_TEXT_AWAITING
VOICE_OPTION_AWAITING = _OPTION_AWAITING


def voice_wants_flow_switch(result: dict[str, Any]) -> bool:
    """True when a voice reply given during a free-text step (name / MRN / DOB)
    is really a *different* request — a new booking, reschedule, cancel,
    doctor/specialty jump, or staff handover — and should switch flows instead
    of being stored as the name/MRN/DOB answer.

    Plain answers (an actual name) come back as intent=unknown / action=clarify
    with no booking signal, so they are NOT treated as a switch.
    """
    action = (result.get("action") or "").strip().lower()
    intent = (result.get("intent") or "").strip().lower()
    conf = float(result.get("confidence") or 0)
    if action in {"book_direct", "specialty_direct"}:
        return True
    if intent in {"book", "update", "cancel", "ask_doctors", "handover"} and conf >= 0.6:
        return True
    return False

_WEEKDAY_AR = {
    "الاثنين": 0,
    "الاتنين": 0,
    "اتنين": 0,
    "الثلاثاء": 1,
    "التلات": 1,
    "التلاتاء": 1,
    "الثلاث": 1,  # Whisper often truncates الثلاثاء
    "الاربعاء": 2,
    "الأربعاء": 2,
    "الاربع": 2,
    "الخميس": 3,
    "الجمعة": 4,
    "الجمعه": 4,
    "السبت": 5,
    "الاحد": 6,
    "الأحد": 6,
}

# Eastern/Persian Arabic-Indic digits → ASCII (for time_hint / transcript)
_AR_DIGIT_TRANS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)

# Clinic daytime bias: bare clock hours 1–7 with no AM/PM → PM (13:00–19:00)
_DAYTIME_BARE_HOURS = range(1, 8)


def _reply_lang(phone: str) -> str:
    """Reply language for direct fastpath messages (session-mirrored)."""
    return i18n.normalize_lang(_sess(phone).get("language") or "ar")


def _norm_ar(text: str) -> str:
    s = (text or "").strip().lower()
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي")):
        s = s.replace(src, dst)
    return re.sub(r"\s+", " ", s)


_CHANGE_DAY_PHRASES = (
    # Arabic (normalized via _norm_ar: hamza/ta-marbuta/alef-maqsura folded)
    "غير اليوم",
    "غير التاريخ",
    "غير الميعاد",
    "تغيير اليوم",
    "تغيير التاريخ",
    "بدل اليوم",
    "يوم تاني",
    "يوم اخر",
    "يوم غير",
    "تاريخ تاني",
    "تاريخ اخر",
    "معاد تاني",
    "اعدل اليوم",
    "عدل اليوم",
    # English
    "change day",
    "change the day",
    "change date",
    "change the date",
    "another day",
    "other day",
    "different day",
    "another date",
    "different date",
)


def _wants_change_day(result: dict[str, Any], transcript: str) -> bool:
    """True when a voice reply at the time-slot step asks to change the day/date
    rather than pick a time (e.g. 'عايز أغير اليوم' / 'change the day')."""
    if (result.get("change_target") or "").strip().lower() == "date":
        return True
    n = _norm_ar(transcript)
    return any(p in n for p in _CHANGE_DAY_PHRASES)


def _state_value(conversation) -> str:
    raw = getattr(conversation, "state", None)
    if raw is None:
        return ""
    return raw.value if hasattr(raw, "value") else str(raw)


def _dispatch(
    db: Session,
    phone: str,
    *,
    text: str = "",
    payload_id: str | None = None,
) -> bool:
    from app.graph import process_incoming_message

    process_incoming_message(
        db,
        phone=phone,
        text=text or "",
        payload_id=payload_id,
        message_type="interactive" if payload_id else "text",
    )
    return True


def find_doctor_by_hint(db: Session, clinic_id: int, hint: str | None) -> Doctor | None:
    if not hint:
        return None
    cleaned = re.sub(r"\s+", " ", hint.strip())
    cleaned = re.sub(r"^(د\.|دكتور|الدكتور|dr\.?)\s*", "", cleaned, flags=re.I).strip()
    if len(cleaned) < 2:
        return None
    if doctor_service.find_department(db, clinic_id, name=cleaned):
        return None
    needle = _norm_ar(cleaned)
    doctors = doctor_service.list_active_doctors(db, clinic_id, limit=50)
    for doc in doctors:
        for name in ((doc.name_ar or "").strip(), (doc.name_en or "").strip()):
            if not name:
                continue
            n = _norm_ar(name)
            if needle == n or needle in n or n in needle:
                return doc
    tokens = [t for t in re.split(r"[^\w\u0600-\u06FF]+", needle) if len(t) >= 3]
    if not tokens:
        return None
    best: Doctor | None = None
    best_score = 0
    for doc in doctors:
        blob = _norm_ar(f"{doc.name_ar or ''} {doc.name_en or ''}")
        score = sum(1 for t in tokens if t in blob)
        if score > best_score:
            best_score = score
            best = doc
    return best if best_score > 0 else None


def _has_explicit_ampm(text: str) -> bool:
    """True only for real AM/PM markers — not the letter م inside مع/منى/…"""
    t = (text or "").translate(_AR_DIGIT_TRANS)
    if re.search(r"\b(am|pm)\b", t, re.I):
        return True
    if re.search(r"صباحا?ً?|مساءً?", t):
        return True
    # ص / م only when attached to a clock number: "2م" / "2 م" / "٢ ص"
    if re.search(r"\d{1,2}(?::\d{2})?\s*[صم]\b", t):
        return True
    return False


def _parse_time_to_hm(time_hint: str) -> tuple[int, int] | None:
    t = time_hint.translate(_AR_DIGIT_TRANS).strip().lower()
    t = t.replace("صباحاً", "am").replace("صباحا", "am").replace("صباح", "am")
    t = t.replace("مساءً", "pm").replace("مساء", "pm")
    t = t.replace(".", ":")
    m = re.search(r"(\d{1,2})(?::(\d{2}))?", t)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    rest = t[m.end() :]
    # am/pm or lone ص/م after the number — never the م inside مع/منى
    ampm_m = re.match(r"\s*(am|pm|[صم](?!\w))", rest, re.I)
    ampm = (ampm_m.group(1) if ampm_m else "").lower()
    if ampm in {"pm", "م"} and hour < 12:
        hour += 12
    if ampm in {"am", "ص"} and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _normalize_date_hint(
    date_hint: str | None,
    *,
    today: date | None = None,
    window_days: int = 14,
) -> str | None:
    """Strict YYYY-MM-DD inside [today, today+window]; reject stale GPT years."""
    if not date_hint:
        return None
    today = today or date.today()
    s = date_hint.strip()
    parsed: date | None = None
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            parsed = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    else:
        m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", s)
        if m:
            day_n, month_n, year_n = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if year_n < 100:
                year_n += 2000
            try:
                parsed = date(year_n, month_n, day_n)
            except ValueError:
                return None
    if parsed is None:
        return None
    if parsed < today or parsed > today + timedelta(days=window_days):
        return None
    return parsed.isoformat()


def _normalize_time_hint(
    time_hint: str | None,
    *,
    transcript: str | None = None,
) -> str | None:
    """Normalize to 24h HH:MM; bare hours 1–7 bias to PM (clinic daytime)."""
    raw = (time_hint or "").strip()
    source = raw
    if not source and transcript:
        blob = transcript.translate(_AR_DIGIT_TRANS)
        if re.search(r"(ساع[ةه]|الساع[ةه]|\d{1,2}\s*(:|am|pm)?)", blob, re.I):
            # Prefer the clock fragment around ساعة / digits, not the whole sentence
            frag = re.search(
                r"(?:ساع[ةه]\s*)?(\d{1,2}(?::\d{2})?\s*(?:am|pm|ص|م)?)",
                blob,
                re.I,
            )
            source = frag.group(0) if frag else blob
    if not source:
        return None
    source = source.translate(_AR_DIGIT_TRANS)
    hm = _parse_time_to_hm(source)
    if not hm:
        return None
    hour, minute = hm
    # If we already applied pm via ص/م on the number, hour may be >= 12
    if not _has_explicit_ampm(source) and hour in _DAYTIME_BARE_HOURS:
        hour += 12
    return f"{hour:02d}:{minute:02d}"


def resolve_date_key(
    *,
    date_hint: str | None = None,
    transcript: str | None = None,
    available: set[str] | None = None,
    today: date | None = None,
    window_days: int = 14,
) -> str | None:
    """Resolve spoken/relative date to YYYY-MM-DD, optionally constrained to available keys."""
    today = today or date.today()
    # Prefer transcript for relative/weekday words; ignore stale GPT ISO in the blob
    # so a bad year like 2023-10-31 does not pollute matching.
    blob = _norm_ar(transcript or "")
    if not blob and date_hint:
        blob = _norm_ar(date_hint)

    candidates: list[str] = []

    if any(w in blob for w in ("النهارده", "النهاردة", "اليوم", "today")):
        candidates.append(today.isoformat())
    if any(w in blob for w in ("بكره", "بكرة", "غدا", "غداً", "غداَ", "tomorrow")):
        candidates.append((today + timedelta(days=1)).isoformat())
    if any(w in blob for w in ("بعد بكره", "بعد بكرة", "بعدغد", "بعد غد")):
        candidates.append((today + timedelta(days=2)).isoformat())

    # Weekdays from speech first (more reliable than GPT calendar math)
    for name, wd in _WEEKDAY_AR.items():
        if _norm_ar(name) in blob:
            for i in range(0, window_days):
                cand = today + timedelta(days=i)
                if cand.weekday() != wd:
                    continue
                iso = cand.isoformat()
                if available is None or iso in available:
                    candidates.append(iso)
                    break

    # GPT / explicit ISO only if inside booking window (drops 2023 hallucinations)
    normalized = _normalize_date_hint(
        date_hint, today=today, window_days=window_days
    )
    if normalized:
        candidates.append(normalized)

    # Dedupe preserve order
    seen: set[str] = set()
    ordered: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            ordered.append(c)

    if available:
        for c in ordered:
            if c in available:
                return c
        return None
    return ordered[0] if ordered else None


def match_slot(
    avail_dates: dict[str, list[dict]],
    *,
    date_hint: str | None,
    time_hint: str | None,
    transcript: str | None = None,
) -> dict | None:
    """Pick a slot dict from availability using date + time hints."""
    if not avail_dates:
        return None

    date_key = resolve_date_key(
        date_hint=date_hint,
        transcript=transcript,
        available=set(avail_dates.keys()),
    )
    if not date_key:
        return None

    day_slots = avail_dates.get(date_key) or []
    if not day_slots:
        return None

    normalized_time = _normalize_time_hint(time_hint, transcript=transcript)
    if not normalized_time:
        return None
    hour, minute = (int(x) for x in normalized_time.split(":"))

    def _start_dt(slot: dict) -> datetime | None:
        start = slot.get("slot_start") or slot.get("start")
        if isinstance(start, datetime):
            return start
        if isinstance(start, str):
            try:
                return datetime.fromisoformat(start.replace("Z", ""))
            except ValueError:
                return None
        return None

    def _find(h: int, m: int) -> dict | None:
        for slot in day_slots:
            start_dt = _start_dt(slot)
            if start_dt and start_dt.hour == h and start_dt.minute == m:
                return slot
        for slot in day_slots:
            start_dt = _start_dt(slot)
            if start_dt and start_dt.hour == h:
                return slot
        return None

    found = _find(hour, minute)
    if found:
        return found
    # If still morning-ish and no am/pm in sources, try afternoon (+12)
    raw_for_ampm = f"{time_hint or ''} {transcript or ''}"
    if hour < 12 and not _has_explicit_ampm(raw_for_ampm):
        return _find(hour + 12, minute)
    return None


def _match_last_option(sess: dict, result: dict[str, Any]) -> str | None:
    """Map voice to an open WhatsApp option id when possible."""
    option_id = result.get("selected_option_id")
    last = sess.get("last_options") or []
    allowed = {str(o.get("id")) for o in last if o.get("id") is not None}
    if option_id and str(option_id) in allowed:
        return str(option_id)
    if option_id and allowed and str(option_id) not in allowed:
        # title equals option id string sometimes
        for o in last:
            if str(o.get("title") or "").strip() == str(option_id).strip():
                return str(o.get("id"))

    transcript = _norm_ar(result.get("transcript") or result.get("text") or "")
    if not transcript or not last:
        return None

    # Exact title / description
    for o in last:
        oid = str(o.get("id") or "")
        title = _norm_ar(str(o.get("title") or ""))
        desc = _norm_ar(str(o.get("description") or ""))
        if title and (transcript == title or title in transcript or transcript in title):
            return oid
        if desc and len(desc) >= 4 and desc in transcript:
            return oid

    # Numbered "الأول" / "1" / "رقم اثنين"
    num_map = {
        "1": 0,
        "اول": 0,
        "الأول": 0,
        "الاول": 0,
        "واحد": 0,
        "2": 1,
        "تاني": 1,
        "ثاني": 1,
        "اثنين": 1,
        "اتنين": 1,
        "3": 2,
        "ثالث": 2,
        "تالت": 2,
        "4": 3,
        "رابع": 3,
        "5": 4,
        "خامس": 4,
    }
    for key, idx in num_map.items():
        if _norm_ar(key) in transcript and idx < len(last):
            return str(last[idx].get("id"))
    return None


def _resolve_specialty_department(db: Session, result: dict[str, Any]):
    transcript = (result.get("transcript") or result.get("text") or "").strip()
    for candidate in (result.get("specialty_hint"), result.get("doctor_hint")):
        if not candidate:
            continue
        dept = doctor_service.find_department(
            db, DEFAULT_CLINIC_ID, name=str(candidate)
        )
        if dept:
            return dept
    return doctor_service.infer_department_from_text(db, DEFAULT_CLINIC_ID, transcript)


def _enrich_result(db: Session, result: dict[str, Any]) -> dict[str, Any]:
    """Normalize doctor_hint vs specialty_hint from typical Egyptian phrasing."""
    result = dict(result)
    doctor_hint = result.get("doctor_hint")
    if doctor_hint and not result.get("specialty_hint"):
        if not find_doctor_by_hint(db, DEFAULT_CLINIC_ID, str(doctor_hint)):
            dept = doctor_service.find_department(
                db, DEFAULT_CLINIC_ID, name=str(doctor_hint)
            ) or doctor_service.infer_department_from_text(
                db,
                DEFAULT_CLINIC_ID,
                result.get("transcript") or result.get("text"),
            )
            if dept:
                result["specialty_hint"] = dept.name_ar or dept.name_en or str(doctor_hint)
                result["doctor_hint"] = None
                result["action"] = "specialty_direct"
                result["intent"] = result.get("intent") or "book"
                logger.info(
                    f"[voice_fast] remapped doctor_hint={doctor_hint!r} "
                    f"→ specialty={result['specialty_hint']!r}"
                )

    if not result.get("specialty_hint"):
        inferred = doctor_service.infer_department_from_text(
            db,
            DEFAULT_CLINIC_ID,
            result.get("transcript") or result.get("text"),
        )
        if inferred and not find_doctor_by_hint(
            db, DEFAULT_CLINIC_ID, str(result.get("doctor_hint") or "")
        ):
            # Only auto-fill specialty_hint; don't force action yet
            result["specialty_hint"] = inferred.name_ar or inferred.name_en
            logger.info(
                f"[voice_fast] inferred specialty from transcript "
                f"→ {result['specialty_hint']!r}"
            )
    return result


# ---------------------------------------------------------------------------
# Mid-flow handlers
# ---------------------------------------------------------------------------


def try_voice_midflow(
    db: Session,
    *,
    phone: str,
    result: dict[str, Any],
    conversation,
) -> bool:
    """Handle voice while user is already inside a booking/reschedule/cancel step."""
    sess = _sess(phone)
    awaiting = sess.get("awaiting")
    conv_state = _state_value(conversation)
    transcript = (result.get("transcript") or result.get("text") or "").strip()
    intent = (result.get("intent") or "").strip().lower()
    action = (result.get("action") or "").strip().lower()
    confidence = float(result.get("confidence") or 0)

    # Explicit escape to menu (always allowed)
    if intent == "menu" and confidence >= 0.6:
        logger.info(f"[voice_fast] midflow → menu phone={phone}")
        return _dispatch(db, phone, text="القائمة")

    # A *different* request voiced during a free-text step (e.g. the patient
    # asks to book a new reservation while we're waiting for their name):
    # abandon the half-finished flow and honor the new request rather than
    # storing the whole sentence as the name/MRN/DOB.
    if awaiting in _FREE_TEXT_AWAITING and transcript and voice_wants_flow_switch(result):
        logger.info(
            "[voice_fast] midflow free-text → switch flow awaiting=%s action=%s "
            "intent=%s conf=%.2f doctor=%r specialty=%r phone=%s",
            awaiting,
            action,
            intent,
            confidence,
            result.get("doctor_hint"),
            result.get("specialty_hint"),
            phone,
        )
        from app.graph.conversation_engine import _clear_draft
        from app.services.conversation_service import set_conversation_state

        _clear_draft(phone)
        set_conversation_state(
            db,
            conversation,
            ConversationState.MAIN_MENU,
            current_intent="voice_flow_switch",
        )
        db.commit()
        if try_voice_book_direct(db, phone=phone, result=result):
            return True
        if try_voice_specialty_direct(db, phone=phone, result=result):
            return True
        if try_voice_menu_intent(db, phone=phone, result=result):
            return True
        # Couldn't start a concrete flow (e.g. named doctor not found): seed the
        # intent's flow so we don't loop on the name prompt.
        seed = {
            "book": "حجز موعد",
            "update": "تعديل موعد",
            "cancel": "إلغاء موعد",
            "ask_doctors": "الاستفسار عن الأطباء",
            "handover": "التحدث مع موظف",
        }.get(intent)
        return _dispatch(db, phone, text=seed or "القائمة")

    # Free-text capture (name / MRN / DOB) — never divert to specialty
    if awaiting in _FREE_TEXT_AWAITING and transcript:
        logger.info(f"[voice_fast] midflow free-text awaiting={awaiting} phone={phone}")
        return _dispatch(db, phone, text=transcript)

    # A clearly *different* booking voiced while reviewing the summary / confirm
    # step: the patient named a NEW doctor or specialty (e.g. "أحجز مع دكتور دينا
    # حسن يوم الاتنين"). Abandon the half-finished draft and start the new booking
    # instead of letting the confirm/cancel matcher swallow the word "أحجز".
    # Gated on a concrete doctor/specialty hint so a plain "نعم"/"احجز" can never
    # hijack a genuine confirmation.
    if (
        (
            awaiting in {"summary", "confirm"}
            or conv_state == ConversationState.CONFIRMING.value
        )
        and transcript
        and (result.get("doctor_hint") or result.get("specialty_hint"))
        and voice_wants_flow_switch(result)
    ):
        logger.info(
            "[voice_fast] midflow confirm → switch flow awaiting=%s action=%s "
            "intent=%s conf=%.2f doctor=%r specialty=%r phone=%s",
            awaiting,
            action,
            intent,
            confidence,
            result.get("doctor_hint"),
            result.get("specialty_hint"),
            phone,
        )
        from app.graph.conversation_engine import _clear_draft
        from app.services.conversation_service import set_conversation_state

        _clear_draft(phone)
        set_conversation_state(
            db,
            conversation,
            ConversationState.MAIN_MENU,
            current_intent="voice_flow_switch",
        )
        db.commit()
        if try_voice_book_direct(db, phone=phone, result=result):
            return True
        if try_voice_specialty_direct(db, phone=phone, result=result):
            return True
        # Named target couldn't be started → open the relevant flow rather than
        # silently confirming the old draft.
        seed = {"book": "حجز موعد", "cancel": "إلغاء موعد"}.get(intent, "القائمة")
        return _dispatch(db, phone, text=seed)

    # Confirm / skip gates
    if awaiting in {"summary", "confirm", "mrn_optional", "dob_gate"} or conv_state in {
        ConversationState.CONFIRMING.value,
    }:
        if intent == "confirm" or action == "select_option" or any(
            w in _norm_ar(transcript)
            for w in ("تاكيد", "تأكيد", "نعم", "ايوه", "أيوه", "yes", "confirm", "موافق")
        ):
            opt = _match_last_option(sess, result)
            if opt:
                return _dispatch(db, phone, text=transcript, payload_id=opt)
            return _dispatch(db, phone, text="تأكيد")
        if intent == "cancel" or any(
            w in _norm_ar(transcript)
            for w in ("الغاء", "إلغاء", "لا", "مش عايز", "cancel", "رجوع")
        ):
            opt = _match_last_option(sess, result)
            if opt and ("الغاء" in _norm_ar(str(opt)) or "cancel" in str(opt).lower()):
                return _dispatch(db, phone, text=transcript, payload_id=opt)
            return _dispatch(db, phone, text="إلغاء")
        opt = _match_last_option(sess, result)
        if opt:
            return _dispatch(db, phone, text=transcript, payload_id=opt)

    # Spoken option while a list/buttons are open
    opt = _match_last_option(sess, {**result, "action": action})
    if opt and (
        action == "select_option"
        or awaiting in _OPTION_AWAITING
        or conv_state
        in {
            ConversationState.BOOKING_DATE.value,
            ConversationState.BOOKING_SLOT.value,
            ConversationState.BOOKING_DOCTOR.value,
            ConversationState.RESCHEDULE.value,
            ConversationState.CANCEL.value,
        }
    ):
        logger.info(f"[voice_fast] midflow option={opt} awaiting={awaiting} phone={phone}")
        return _dispatch(db, phone, text=transcript, payload_id=opt)

    # Doctor picker step — speak a doctor name
    if awaiting == "doctor" or (
        conv_state == ConversationState.BOOKING_DOCTOR.value and sess.get("doctor_id") is None
    ):
        hint = result.get("doctor_hint") or transcript
        doctor = find_doctor_by_hint(db, DEFAULT_CLINIC_ID, str(hint) if hint else None)
        if doctor:
            from app.graph.conversation_engine import continue_after_doctor_selected

            logger.info(f"[voice_fast] midflow doctor={doctor.doctor_id} phone={phone}")
            continue_after_doctor_selected(db, phone=phone, doctor_id=doctor.doctor_id)
            return True
        # Specialty spoken while on doctor path
        dept = _resolve_specialty_department(db, result)
        if dept and intent in {"book", "ask_doctors", "unknown", ""}:
            from app.graph.conversation_engine import _show_doctor_cards

            sess["department_id"] = dept.department_id
            sess["awaiting"] = "doctor"
            wa.send_text(
                phone,
                i18n.voice_specialty_open_doctors(
                    _reply_lang(phone), dept.name_ar or dept.name_en or ""
                ),
            )
            return bool(
                _show_doctor_cards(phone, db, dept.department_id)
            )

    # Department list — speak specialty
    if awaiting == "department":
        dept = _resolve_specialty_department(db, result)
        if dept:
            return _dispatch(
                db,
                phone,
                text=dept.name_ar or dept.name_en or "",
                payload_id=f"dept_{dept.department_id}",
            )

    # Date step
    if conv_state == ConversationState.BOOKING_DATE.value or awaiting == "date":
        doctor_id = sess.get("doctor_id")
        avail_keys: set[str] = set()
        if doctor_id:
            avail = booking_service.get_available_dates_and_slots(
                db, doctor_id=int(doctor_id), clinic_id=DEFAULT_CLINIC_ID
            )
            avail_keys = set((avail.get("dates") or {}).keys())
        # Also from last_options
        for o in sess.get("last_options") or []:
            oid = str(o.get("id") or "")
            if oid.startswith("date_"):
                avail_keys.add(oid.replace("date_", "", 1))
        date_key = resolve_date_key(
            date_hint=result.get("date_hint"),
            transcript=transcript,
            available=avail_keys or None,
        )
        if date_key:
            logger.info(f"[voice_fast] midflow date={date_key} phone={phone}")
            return _dispatch(
                db, phone, text=date_key, payload_id=f"date_{date_key}"
            )

    # Slot / time step
    if conv_state == ConversationState.BOOKING_SLOT.value or awaiting == "slot":
        # "عايز أغير اليوم" / "change the day" → re-open the day picker instead
        # of trying to match a time.
        if _wants_change_day(result, transcript):
            logger.info(f"[voice_fast] midflow slot → change day phone={phone}")
            return _dispatch(db, phone, text="change_day", payload_id="change_day")
        time_hint = result.get("time_hint") or transcript
        doctor_id = sess.get("doctor_id")
        selected_date = sess.get("selected_date")
        if doctor_id and selected_date and time_hint:
            avail = booking_service.get_available_dates_and_slots(
                db, doctor_id=int(doctor_id), clinic_id=DEFAULT_CLINIC_ID
            )
            matched = match_slot(
                {selected_date: (avail.get("dates") or {}).get(selected_date) or []},
                date_hint=selected_date,
                time_hint=str(time_hint),
                transcript=transcript,
            )
            if matched:
                sid = int(matched.get("slot_id") or matched.get("id") or 0)
                if sid:
                    logger.info(f"[voice_fast] midflow slot={sid} phone={phone}")
                    return _dispatch(
                        db, phone, text=transcript, payload_id=f"slot_{sid}"
                    )
        # Try last_options titles
        opt = _match_last_option(sess, result)
        if opt and str(opt).startswith("slot_"):
            return _dispatch(db, phone, text=transcript, payload_id=opt)

    # Inquiry CTA
    if awaiting == "inquiry_book_cta":
        if intent in {"book", "confirm"} or any(
            w in _norm_ar(transcript) for w in ("حجز", "احجز", "نعم", "book")
        ):
            return _dispatch(db, phone, text="حجز معه")
        if intent == "menu":
            return _dispatch(db, phone, text="القائمة")

    # Reschedule change type
    if awaiting == "change_type":
        # Prefer the router's explicit change_target when present.
        target = (result.get("change_target") or "").strip().lower()
        if target == "doctor":
            return _dispatch(db, phone, text="تغيير الطبيب")
        if target == "date":
            return _dispatch(db, phone, text="تغيير اليوم")
        if target == "time":
            return _dispatch(db, phone, text="تغيير الوقت")
        n = _norm_ar(transcript)
        if "طبيب" in n or "doctor" in n:
            return _dispatch(db, phone, text="تغيير الطبيب")
        if "يوم" in n or "تاريخ" in n or "day" in n or "date" in n:
            return _dispatch(db, phone, text="تغيير اليوم")
        if "وقت" in n or "ميعاد" in n or "time" in n:
            return _dispatch(db, phone, text="تغيير الوقت")
        if "رجوع" in n or "قائمه" in n or "menu" in n:
            return _dispatch(db, phone, text="رجوع")

    return False


# ---------------------------------------------------------------------------
# Fresh jumps (not mid free-text)
# ---------------------------------------------------------------------------


def try_voice_book_direct(
    db: Session,
    *,
    phone: str,
    result: dict[str, Any],
) -> bool:
    """Doctor (+ optional date/time) → hold or date/slot picker. Never auto-confirms."""
    action = (result.get("action") or "").strip().lower()
    doctor_hint = result.get("doctor_hint")
    date_hint = result.get("date_hint")
    time_hint = result.get("time_hint")
    transcript = (result.get("transcript") or result.get("text") or "").strip()
    confidence = float(result.get("confidence") or 0)
    intent = (result.get("intent") or "").strip().lower()

    wants_direct = action == "book_direct" or (
        intent == "book" and bool(doctor_hint) and confidence >= 0.65
    )
    if not wants_direct or not doctor_hint:
        if action == "book_direct" or (
            intent == "book" and confidence >= 0.65 and not doctor_hint
        ):
            logger.info(
                "[voice_fast] book_direct declined: missing doctor_hint or not eligible "
                "action=%s intent=%s conf=%.2f doctor_hint=%r",
                action,
                intent,
                confidence,
                doctor_hint,
            )
        return False

    doctor = find_doctor_by_hint(db, DEFAULT_CLINIC_ID, str(doctor_hint))
    if not doctor:
        logger.info(
            "[voice_fast] book_direct declined: doctor not found hint=%r",
            doctor_hint,
        )
        return False

    conversation = get_or_create_conversation(
        db,
        tenant_id=DEFAULT_TENANT_ID,
        clinic_id=DEFAULT_CLINIC_ID,
        phone=phone,
    )
    sess = _sess(phone)
    # Preserve voice hints only
    hints = {
        k: sess.get(k)
        for k in (
            "voice_doctor_hint",
            "voice_specialty_hint",
            "voice_date_hint",
            "voice_time_hint",
            "voice_transcript",
        )
        if sess.get(k)
    }
    sess.clear()
    sess.update(hints)
    sess["flow"] = "booking"
    sess["doctor_id"] = doctor.doctor_id

    doctor_name = doctor.name_ar or doctor.name_en or str(doctor.doctor_id)
    booking_service.release_expired_holds(db, clinic_id=DEFAULT_CLINIC_ID)
    avail = booking_service.get_available_dates_and_slots(
        db, doctor_id=doctor.doctor_id, clinic_id=DEFAULT_CLINIC_ID
    )
    dates = avail.get("dates") or {}

    matched = match_slot(
        dates,
        date_hint=date_hint,
        time_hint=time_hint,
        transcript=transcript,
    )
    if matched:
        slot_id = int(matched.get("slot_id") or matched.get("id") or 0)
        if not slot_id:
            return False
        try:
            booking_service.hold_slot(
                db,
                slot_id=slot_id,
                clinic_id=DEFAULT_CLINIC_ID,
                held_by_phone=phone,
                hold_minutes=SLOT_HOLD_MINUTES,
            )
        except BookingError as exc:
            wa.send_text(
                phone,
                f"وجدت د. {doctor_name} لكن الوقت غير متاح حالياً ({exc}). اختر يوماً آخر.",
            )
            matched = None
        else:
            sess["slot_id"] = slot_id
            start = matched.get("slot_start") or matched.get("start")
            when = (
                start.strftime("%Y-%m-%d %H:%M")
                if isinstance(start, datetime)
                else str(start)
            )
            set_conversation_state(
                db,
                conversation,
                ConversationState.PATIENT_DETAILS,
                current_intent="voice_book_direct",
            )
            sess["awaiting"] = "patient_name"
            sess.pop("last_options", None)
            wa.send_text(
                phone,
                (
                    f"تمام — حجز مؤقت مع {doctor_name}\n"
                    f"الموعد: {when}\n\n"
                    "برجاء إدخال اسم المريض لإكمال التأكيد:"
                ),
            )
            db.commit()
            logger.info(
                f"[voice_fast] held slot_id={slot_id} doctor={doctor.doctor_id} phone={phone}"
            )
            return True

    # Day resolved (with or without time) but exact slot not held → that day's slots only.
    # Do NOT require `not time_hint`: a spoken time that misses a free slot must still
    # narrow to the resolved day instead of collapsing to the full date picker.
    date_key = resolve_date_key(
        date_hint=date_hint,
        transcript=transcript,
        available=set(dates.keys()) if dates else None,
    )
    if date_key and date_key in dates:
        from app.graph.conversation_engine import (
            _date_option_title,
            _lang,
            _offer_list,
            _slot_rows_with_change_day,
        )

        day_slots = dates.get(date_key) or []
        if day_slots:
            sess["selected_date"] = date_key
            set_conversation_state(
                db,
                conversation,
                ConversationState.BOOKING_SLOT,
                current_intent="voice_book_date",
            )
            lang = _lang(conversation)
            date_label = _date_option_title(date_key, lang)
            _offer_list(
                phone,
                body=i18n.choose_slot_on_date(lang, date_label),
                button_label=i18n.times_button_label(lang),
                rows=_slot_rows_with_change_day(day_slots, lang),
                section_title=i18n.slots_section_title(lang),
            )
            db.commit()
            logger.info(
                "[voice_fast] doctor=%s date=%s time_hint=%r → same-day slots",
                doctor.doctor_id,
                date_key,
                time_hint,
            )
            return True

    from app.graph.conversation_engine import continue_after_doctor_selected

    logger.info(
        "[voice_fast] doctor=%s date/time incomplete date=%r time=%r "
        "normalized_date=%r → date picker",
        doctor.doctor_id,
        date_hint,
        time_hint,
        _normalize_date_hint(date_hint),
    )
    wa.send_text(phone, i18n.voice_continue_with_doctor(_reply_lang(phone), doctor_name))
    continue_after_doctor_selected(db, phone=phone, doctor_id=doctor.doctor_id)
    return True


def try_voice_specialty_direct(
    db: Session,
    *,
    phone: str,
    result: dict[str, Any],
) -> bool:
    """Specialty (no person name) → Flow/cards for that department."""
    action = (result.get("action") or "").strip().lower()
    confidence = float(result.get("confidence") or 0)
    intent = (result.get("intent") or "").strip().lower()
    doctor_hint = result.get("doctor_hint")

    if doctor_hint and find_doctor_by_hint(db, DEFAULT_CLINIC_ID, str(doctor_hint)):
        return False

    dept = _resolve_specialty_department(db, result)
    if not dept:
        return False

    # Require clear booking/inquiry/specialty signal (avoid random mid-chat matches)
    wants = action == "specialty_direct" or (
        result.get("specialty_hint")
        and intent in {"book", "ask_doctors"}
        and confidence >= 0.55
    )
    if not wants:
        return False

    conversation = get_or_create_conversation(
        db,
        tenant_id=DEFAULT_TENANT_ID,
        clinic_id=DEFAULT_CLINIC_ID,
        phone=phone,
    )
    sess = _sess(phone)
    hints = {
        k: sess.get(k)
        for k in (
            "voice_doctor_hint",
            "voice_specialty_hint",
            "voice_date_hint",
            "voice_time_hint",
            "voice_transcript",
        )
        if sess.get(k)
    }
    sess.clear()
    sess.update(hints)
    flow = "inquiry" if intent == "ask_doctors" else "booking"
    sess["flow"] = flow
    sess["department_id"] = dept.department_id
    sess["awaiting"] = "doctor"
    sess["voice_specialty_hint"] = dept.name_ar or dept.name_en
    set_conversation_state(
        db,
        conversation,
        ConversationState.BOOKING_DOCTOR,
        current_intent="voice_specialty_direct",
    )
    db.commit()

    from app.graph.conversation_engine import _show_doctor_cards

    _lng = _reply_lang(phone)
    dept_name = (
        (dept.name_en or dept.name_ar)
        if i18n.is_english(_lng)
        else (dept.name_ar or dept.name_en)
    ) or ""
    wa.send_text(phone, i18n.voice_specialty_open_doctors(_lng, dept_name))
    ok = _show_doctor_cards(
        phone,
        db,
        dept.department_id,
    )
    logger.info(
        f"[voice_fast] specialty={dept.department_id} ({dept_name}) "
        f"flow={flow} ok={ok} phone={phone}"
    )
    return bool(ok)


def try_voice_menu_intent(
    db: Session,
    *,
    phone: str,
    result: dict[str, Any],
) -> bool:
    """Top-level intents: book / update / cancel / inquiry / handover / menu."""
    intent = (result.get("intent") or "").strip().lower()
    action = (result.get("action") or "").strip().lower()
    confidence = float(result.get("confidence") or 0)
    if confidence < 0.55 and action != "select_option":
        return False

    seeds = {
        "book": "حجز موعد",
        "update": "تعديل موعد",
        "cancel": "إلغاء موعد",
        "ask_doctors": "الاستفسار عن الأطباء",
        "handover": "التحدث مع موظف",
        "menu": "القائمة",
    }
    transcript = _norm_ar(result.get("transcript") or "")
    # Path shortcuts only when no specialty/doctor already extracted
    if intent == "book" and not result.get("specialty_hint") and not result.get("doctor_hint"):
        if any(w in transcript for w in ("كل الاطباء", "كل الأطباء", "all doctors")):
            logger.info(f"[voice_fast] menu book → all doctors phone={phone}")
            _dispatch(db, phone, text="حجز موعد")
            return _dispatch(db, phone, text="كل الأطباء")

    seed = seeds.get(intent)
    if not seed:
        return False
    # Don't steal book when specialty/doctor fastpath should run
    if intent == "book" and (
        result.get("specialty_hint") or result.get("doctor_hint")
    ):
        return False
    if intent in {"update", "cancel", "ask_doctors", "handover", "menu", "book"}:
        logger.info(f"[voice_fast] menu intent={intent} → {seed!r} phone={phone}")
        return _dispatch(db, phone, text=seed)
    return False


def try_voice_smart_route(
    db: Session,
    *,
    phone: str,
    result: dict[str, Any],
) -> bool:
    """
    Full voice router:
    1) enrich hints
    2) mid-flow continuation (don't wipe session)
    3) doctor / specialty fast jumps
    4) top-level menu intents
    """
    conversation = get_or_create_conversation(
        db,
        tenant_id=DEFAULT_TENANT_ID,
        clinic_id=DEFAULT_CLINIC_ID,
        phone=phone,
    )
    result = _enrich_result(db, result)

    sess = _sess(phone)
    for key in ("doctor_hint", "specialty_hint", "date_hint", "time_hint"):
        val = result.get(key)
        if val:
            sess[f"voice_{key}"] = val
    if result.get("transcript"):
        sess["voice_transcript"] = result["transcript"]

    awaiting = sess.get("awaiting")
    conv_state = _state_value(conversation)
    in_flow = bool(
        awaiting
        or conv_state
        in {
            ConversationState.BOOKING_DOCTOR.value,
            ConversationState.BOOKING_DATE.value,
            ConversationState.BOOKING_SLOT.value,
            ConversationState.PATIENT_DETAILS.value,
            ConversationState.CONFIRMING.value,
            ConversationState.RESCHEDULE.value,
            ConversationState.CANCEL.value,
            ConversationState.HANDOVER.value,
        }
    )

    if in_flow and try_voice_midflow(
        db, phone=phone, result=result, conversation=conversation
    ):
        return True

    # Mid free-text already returned above; for other mid-flow misses fall through
    # to option/select before wiping with a new booking jump
    if awaiting in _FREE_TEXT_AWAITING:
        return False

    if try_voice_book_direct(db, phone=phone, result=result):
        return True
    if try_voice_specialty_direct(db, phone=phone, result=result):
        return True

    # Don't restart booking from menu intents while deep in patient/confirm
    if conv_state in {
        ConversationState.PATIENT_DETAILS.value,
        ConversationState.CONFIRMING.value,
    }:
        return False

    if try_voice_menu_intent(db, phone=phone, result=result):
        return True

    action = (result.get("action") or "").strip().lower()
    intent = (result.get("intent") or "").strip().lower()
    confidence = float(result.get("confidence") or 0)
    if action == "book_direct" or (
        intent == "book" and result.get("doctor_hint") and confidence >= 0.65
    ):
        logger.info(
            "[voice_fast] smart_route declined book_direct/high-conf book "
            "(falling through to menu) phone=%s action=%s intent=%s conf=%.2f "
            "doctor=%r specialty=%r date=%r time=%r awaiting=%r state=%s",
            phone,
            action,
            intent,
            confidence,
            result.get("doctor_hint"),
            result.get("specialty_hint"),
            result.get("date_hint"),
            result.get("time_hint"),
            awaiting,
            conv_state,
        )
    return False
