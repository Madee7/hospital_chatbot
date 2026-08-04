"""
LangGraph conversation engine for WhatsApp booking (sections 9.1 / 9.2).

Doctor cards are sent via WhatsApp Flow ImageCarousel when enabled
(USE_DOCTOR_FLOW + WHATSAPP_FLOW_ID), otherwise sequential interactive cards.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.core import i18n_bot as i18n
from app.core.config import (
    CANCEL_CUTOFF_HOURS,
    DEFAULT_CLINIC_ID,
    DEFAULT_TENANT_ID,
    REQUIRE_DOB,
    RESCHEDULE_CUTOFF_HOURS,
    SLOT_HOLD_MINUTES,
    WHATSAPP_FLOW_CTA,
    WHATSAPP_FLOW_DRAFT,
    WHATSAPP_FLOW_ID,
)
from app.core import safety
from app.db.enums import ConversationState, HandoverPriority, MessageType, SlotStatus
from app.language.language_detector import detect_language
from app.language.language_service import LanguageService, get_conversation_language
from app.language.response_validator import ensure_response_language
from app.models.appointment_models import AppointmentSlot
from app.models.conversation_models import Conversation
from app.services import (
    booking_service,
    doctor_service,
    flow_service,
    handover_service,
    patient_service,
    whatsapp_client as wa,
)
from app.services.booking_service import BookingError
from app.services import clinic_settings_service
from app.services.conversation_service import (
    get_or_create_conversation,
    log_message,
    set_conversation_state,
)
from app.services.choice_resolver import resolve_choice
from app.services.intent_service import Intent, detect_intent


_SESSION: dict[str, dict[str, Any]] = {}
_GRAPH = None


class GraphState(TypedDict, total=False):
    phone: str
    text: str
    payload_id: str
    message_type: str
    db_session: Session
    conversation_id: int
    conversation_state: str
    language: str
    keep_language: bool
    handled: bool


def _sess(phone: str) -> dict[str, Any]:
    if phone not in _SESSION:
        _SESSION[phone] = {}
    return _SESSION[phone]


def _clear_draft(phone: str) -> None:
    """Drop booking draft keys but keep live language + voice-lang sticky flags."""
    prev = _SESSION.get(phone) or {}
    keep = {
        k: prev[k]
        for k in (
            "language",
            "voice_lang_locked",
            "voice_lang_locked_at",
            "allow_voice_lang_switch",
        )
        if prev.get(k) is not None
    }
    _SESSION.pop(phone, None)
    if keep:
        _sess(phone).update(keep)


def _sess_clear_keep_lang(sess: dict[str, Any]) -> None:
    """Clear draft keys on an existing session dict without dropping language."""
    keep = {
        k: sess[k]
        for k in (
            "language",
            "voice_lang_locked",
            "voice_lang_locked_at",
            "allow_voice_lang_switch",
        )
        if sess.get(k) is not None
    }
    sess.clear()
    sess.update(keep)


def _sess_missing(
    phone: str,
    db: Session,
    conversation: Conversation,
    *keys: str,
) -> bool:
    """If draft keys were lost (reload), recover by resetting to the main menu."""
    sess = _sess(phone)
    if all(sess.get(k) is not None for k in keys):
        return False
    lang = _lang(conversation)
    wa.send_text(phone, i18n.session_expired(lang))
    _clear_draft(phone)
    _send_main_menu(phone, db, conversation)
    return True


def _remember_options(phone: str, options: list[dict[str, Any]]) -> None:
    """Store the last list/buttons so free text / numbers can be mapped to an id."""
    _sess(phone)["last_options"] = options


def _clear_options(phone: str) -> None:
    _sess(phone).pop("last_options", None)


def _parse_hold_deadline(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", ""))
    except ValueError:
        return None


def _store_hold_deadline(sess: dict[str, Any], hold_result: dict[str, Any] | None = None) -> None:
    """Remember when the temporary slot hold expires (session-side timer)."""
    raw = None
    if hold_result:
        raw = hold_result.get("hold_expires_at")
    if not raw:
        raw = (datetime.utcnow() + timedelta(minutes=SLOT_HOLD_MINUTES)).isoformat(
            sep=" ", timespec="seconds"
        )
    sess["hold_deadline"] = str(raw)


def _hold_deadline_passed(sess: dict[str, Any]) -> bool:
    deadline = _parse_hold_deadline(sess.get("hold_deadline"))
    if deadline is None:
        return False
    return datetime.utcnow() >= deadline


def _is_hold_timeout_error(exc: BaseException | str) -> bool:
    text = str(exc).lower()
    return "hold expired" in text or "slot hold expired" in text


def _notify_booking_hold_timeout(
    phone: str,
    db: Session,
    conversation: Conversation,
    *,
    reschedule: bool = False,
) -> None:
    """Apologize for hold timeout, drop the draft, and return to the main menu."""
    lang = _lang(conversation, _sess(phone))
    msg = (
        i18n.reschedule_hold_timeout_apology(lang)
        if reschedule
        else i18n.hold_timeout_apology(lang)
    )
    # Best-effort: free the held slot if it is still ours.
    sess = _sess(phone)
    slot_id = sess.get("slot_id")
    if slot_id:
        try:
            booking_service.release_expired_holds(db, clinic_id=DEFAULT_CLINIC_ID)
            slot_row = (
                db.query(AppointmentSlot)
                .filter(AppointmentSlot.slot_id == int(slot_id))
                .one_or_none()
            )
            if slot_row and slot_row.status == SlotStatus.HELD:
                slot_row.status = SlotStatus.AVAILABLE
                slot_row.hold_expires_at = None
                slot_row.updated_by = "hold_timeout_user"
                db.commit()
        except Exception as exc:  # pragma: no cover
            print(f"[hold_timeout] release failed: {exc}")
    wa.send_text(phone, msg)
    _finish_flow_quietly(phone, db, conversation)


def _abort_if_hold_timed_out(
    phone: str,
    db: Session,
    conversation: Conversation,
    sess: dict[str, Any],
    *,
    reschedule: bool = False,
) -> bool:
    """If the booking hold window elapsed, apologize and stop. Returns True when aborted."""
    if not _hold_deadline_passed(sess):
        return False
    _notify_booking_hold_timeout(phone, db, conversation, reschedule=reschedule)
    return True


def _offer_buttons(phone: str, body: str, buttons: list[str] | list[dict[str, str]]):
    """Send reply buttons and remember them for typed number/name selection."""
    lang = _sess(phone).get("language") or "ar"
    opts = []
    for i, item in enumerate(buttons[:3]):
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("id") or f"opt{i}")
            oid = str(item.get("id") or title)
        else:
            title = str(item)
            oid = title
        opts.append(
            {
                "id": oid,
                "title": title,
                "description": i18n.option_number_description(lang, i + 1),
            }
        )
    _remember_options(phone, opts)
    return wa.send_buttons(phone, body, buttons)


def _lang(conversation: Conversation, session: dict[str, Any] | None = None) -> str:
    """Current conversation language (session mirror → DB → default ar)."""
    return get_conversation_language(conversation, session)


def _send_text(
    phone: str,
    text: str,
    lang: str | None = None,
    *,
    db: Session | None = None,
) -> None:
    """Send WhatsApp text after optional language validation (LLM-safe)."""
    body = (
        ensure_response_language(
            text,
            lang,
            db=db,
            tenant_id=DEFAULT_TENANT_ID,
            clinic_id=DEFAULT_CLINIC_ID,
        )
        if lang
        else text
    )
    wa.send_text(phone, body)


def _send_main_menu(phone: str, db: Session, conversation: Conversation) -> None:
    lang = _lang(conversation, _sess(phone))
    rows = i18n.main_menu_rows(lang)
    wa.send_text(phone, i18n.welcome(lang))
    _offer_list(
        phone,
        body=i18n.main_menu(lang),
        button_label=i18n.menu_button_label(lang),
        rows=[
            {"id": f"menu_{i}", "title": title[:24]}
            for i, title in enumerate(rows)
        ],
        section_title=i18n.menu_section_title(lang),
    )
    # After the menu, the next clear voice note may switch EN↔AR.
    # Mid-booking voice must stay sticky (see LanguageService.apply_voice_language).
    _sess(phone)["allow_voice_lang_switch"] = True
    set_conversation_state(
        db, conversation, ConversationState.MAIN_MENU, current_intent="main_menu"
    )
    log_message(
        db,
        conversation_id=conversation.conversation_id,
        direction="outbound",
        message_type=MessageType.INTERACTIVE_REPLY,
        text=i18n.main_menu(lang),
        status="sent",
    )
    db.commit()


def _finish_flow_quietly(phone: str, db: Session, conversation: Conversation) -> None:
    """End booking/reschedule/cancel without auto-sending the welcome menu."""
    _clear_draft(phone)
    set_conversation_state(
        db, conversation, ConversationState.MAIN_MENU, current_intent="idle"
    )
    db.commit()


def _offer_list(
    phone: str,
    body: str,
    button_label: str,
    rows: list[dict[str, str]],
    section_title: str = "الخيارات",
):
    """Send a list message and remember rows for typed selection."""
    opts = [
        {
            "id": row["id"],
            "title": row.get("title") or "",
            "description": row.get("description") or "",
        }
        for row in rows[:10]
    ]
    _remember_options(phone, opts)
    return wa.send_list(
        phone,
        body=body,
        button_label=button_label,
        rows=rows,
        section_title=section_title,
    )


def _resolve_free_text_choice(
    phone: str,
    text: str,
    payload_id: str,
    *,
    lang: str | None = None,
    db: Session | None = None,
) -> str:
    """
    If user typed instead of tapping a list/button, map text → option id.
    LLM only selects; bot replies stay canned in the flow below.
    """
    options = _sess(phone).get("last_options") or []
    payload = (payload_id or "").strip()
    if payload:
        # Exact remembered id (stable button ids like path_by_doctor).
        for opt in options:
            oid = str(opt.get("id") or "")
            if payload == oid:
                return oid
        # Legacy auto ids: btn_0_..., btn_1_... → map by index.
        if payload.startswith("btn_"):
            try:
                idx = int(payload.split("_", 2)[1])
                if 0 <= idx < len(options):
                    return str(options[idx].get("id") or payload)
            except (IndexError, ValueError):
                pass
        return payload
    text = (text or "").strip()
    if not text:
        return text
    if not options:
        return text
    resolved = resolve_choice(
        text,
        options,
        lang=lang,
        db=db,
        tenant_id=DEFAULT_TENANT_ID,
        clinic_id=DEFAULT_CLINIC_ID,
        allow_llm=True,
    )
    if resolved:
        try:
            print(f"[choice] mapped {text!r} -> {resolved!r}")
        except UnicodeEncodeError:
            print("[choice] mapped text -> option")
        return resolved
    return text


def _is_booking_path_choice(
    choice: str,
    text: str,
    aliases: set[str],
) -> bool:
    """Match path buttons by id, title, or legacy WhatsApp btn_* payload."""
    c = (choice or "").strip()
    t = (text or "").strip()
    if c in aliases or t in aliases:
        return True
    # Legacy payloads like btn_1_باسم الدكت
    for alias in aliases:
        if alias and (alias in c or alias in t):
            return True
    return False


def _advance_after_patient_name(
    phone: str,
    sess: dict[str, Any],
    *,
    lang: str,
) -> bool:
    """After name is accepted: ask DOB if required, else go to booking summary.

    Returns True when a prompt was already sent (caller should return).
    Returns False when awaiting=summary so the same turn can show the summary.
    """
    if REQUIRE_DOB:
        sess["awaiting"] = "dob_value"
        _clear_options(phone)
        wa.send_text(phone, i18n.ask_dob(lang))
        return True
    sess["awaiting"] = "summary"
    return False


def _arabic_weekday(dt: datetime) -> str:
    return ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"][dt.weekday()]


def _english_weekday(dt: datetime) -> str:
    return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][
        dt.weekday()
    ]


def _format_date(dt: datetime, lang: str | None = "ar") -> str:
    if i18n.is_english(lang):
        return f"{_english_weekday(dt)} {dt.day} {dt.strftime('%b')} {dt.year}"
    months = [
        "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
        "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
    ]
    return f"{_arabic_weekday(dt)} {dt.day} {months[dt.month - 1]} {dt.year}"


def _format_time(dt: datetime, lang: str | None = "ar") -> str:
    from app.core.time_format import format_time_12h

    return format_time_12h(dt, lang)


def _parse_slot_dt(value: str | datetime) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except ValueError:
        return None


def _format_time_compact(dt: datetime, lang: str | None = "ar") -> str:
    """Short 12h clock for WhatsApp list titles (keep ranges under 24 chars)."""
    hour12 = dt.hour % 12 or 12
    minute = f"{dt.minute:02d}"
    if i18n.is_english(lang):
        suffix = "AM" if dt.hour < 12 else "PM"
        return f"{hour12}:{minute} {suffix}"
    suffix = "ص" if dt.hour < 12 else "م"
    return f"{hour12}:{minute} {suffix}"


def _slot_option_row(slot: dict, lang: str | None = "ar") -> dict[str, str]:
    """One-line slot title (e.g. 10:00 AM–10:30 AM); no description to avoid double lines."""
    start = _parse_slot_dt(slot.get("slot_start"))
    end = _parse_slot_dt(slot.get("slot_end"))
    if start is None:
        raw = str(slot.get("slot_start") or "")
        title = raw.split(" ")[-1][:24] if raw else "?"
        return {"id": f"slot_{slot['slot_id']}", "title": title, "description": ""}
    start_label = _format_time_compact(start, lang)
    if end is not None:
        end_label = _format_time_compact(end, lang)
        # Prefer en-dash so start–end fits WhatsApp's 24-char title limit.
        title = f"{start_label}–{end_label}"[:24]
    else:
        title = start_label[:24]
    return {
        "id": f"slot_{slot['slot_id']}",
        "title": title,
        "description": "",
    }


def _slot_list_rows(slots: list[dict], lang: str | None = "ar") -> list[dict[str, str]]:
    return [_slot_option_row(s, lang) for s in slots]


def _filter_bookable_slots(slots: list[dict]) -> list[dict]:
    """Drop slots that violate MIN_LEAD_HOURS so users never pick an invalid time."""
    from app.services.slot_service import earliest_bookable_at

    min_start = earliest_bookable_at()
    out: list[dict] = []
    for slot in slots:
        start = _parse_slot_dt(slot.get("slot_start"))
        if start is None or start >= min_start:
            out.append(slot)
    return out


def _date_option_title(date_str: str, lang: str | None = "ar") -> str:
    """WhatsApp list title (max 24): weekday + date, localized."""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
    except ValueError:
        return date_str[:24]
    if i18n.is_english(lang):
        # e.g. "Wed 2026-07-15"
        title = f"{dt.strftime('%a')} {dt.strftime('%Y-%m-%d')}"
    else:
        # e.g. "الأربعاء 15-07-2026"
        title = f"{_arabic_weekday(dt)} {dt.strftime('%d-%m-%Y')}"
    return title[:24]


def _date_list_rows(dates: list[str], lang: str | None = "ar") -> list[dict[str, str]]:
    """Date rows: title only (no description) so WhatsApp doesn't show the date twice."""
    return [
        {
            "id": f"date_{d}",
            "title": _date_option_title(d, lang),
            "description": "",
        }
        for d in dates
    ]


def _choice(state: GraphState, *, lang: str | None = None) -> str:
    """Prefer interactive payload id; otherwise map typed text to last options."""
    payload = (state.get("payload_id") or "").strip()
    text = (state.get("text") or "").strip()
    phone = state.get("phone") or ""
    db = state.get("db_session")
    return _resolve_free_text_choice(phone, text, payload, lang=lang, db=db)


# WhatsApp interactive lists allow at most 10 rows.
_WA_LIST_MAX_ROWS = 10


def _page_items(
    items: list[Any],
    offset: int,
    *,
    capacity: int,
) -> tuple[list[Any], bool, int]:
    """Return (page_items, has_more, next_offset) for a WhatsApp list page."""
    if offset < 0:
        offset = 0
    if capacity < 1:
        capacity = 1
    rest = items[offset:]
    if len(rest) <= capacity:
        page = list(rest)
        return page, False, offset + len(page)
    page = list(rest[: capacity - 1])
    return page, True, offset + len(page)


def _apply_list_page(
    sess: dict[str, Any],
    kind: str,
    items: list[Any],
    *,
    reset: bool = False,
    reserved_tail: int = 0,
) -> tuple[list[Any], bool, int]:
    """Track offset in session; return (page_items, has_more, page_number)."""
    off_key = f"list_{kind}_offset"
    next_key = f"list_{kind}_next_offset"
    page_key = f"list_{kind}_page"
    if reset:
        sess[off_key] = 0
        sess[page_key] = 1
        sess.pop(next_key, None)
    offset = int(sess.get(off_key) or 0)
    page_num = max(1, int(sess.get(page_key) or 1))
    capacity = _WA_LIST_MAX_ROWS - max(0, reserved_tail)
    page, has_more, next_off = _page_items(items, offset, capacity=capacity)
    if not page and offset > 0 and items:
        sess[off_key] = 0
        sess[page_key] = 1
        return _apply_list_page(
            sess, kind, items, reset=True, reserved_tail=reserved_tail
        )
    sess["list_page_kind"] = kind
    sess[page_key] = page_num
    if has_more:
        sess[next_key] = next_off
    else:
        sess.pop(next_key, None)
    return page, has_more, page_num


def _rows_with_more(
    rows: list[dict[str, str]],
    lang: str | None,
    has_more: bool,
    *,
    more_description: str | None = None,
) -> list[dict[str, str]]:
    if not has_more:
        return rows
    return list(rows) + [i18n.list_more_row(lang, description=more_description)]


def _department_list_rows(departments: list, lang: str | None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for d in departments:
        title = (
            i18n.pick_bilingual_field(
                en=d.name_en,
                ar=d.name_ar,
                lang=lang,
                allow_cross_script=False,
                fallback=str(d.department_id),
            )
            or str(d.department_id)
        )[:24]
        rows.append({"id": f"dept_{d.department_id}", "title": title, "description": ""})
    return rows


def _offer_departments_list(
    phone: str,
    db: Session,
    conversation: Conversation,
    *,
    reset: bool = False,
) -> bool:
    sess = _sess(phone)
    lang = _lang(conversation, sess)
    departments = doctor_service.list_departments(db, DEFAULT_CLINIC_ID)
    if not departments:
        return False
    page, has_more, page_num = _apply_list_page(
        sess, "departments", departments, reset=reset
    )
    rows = _rows_with_more(
        _department_list_rows(page, lang),
        lang,
        has_more,
        more_description=(
            "Next specialties" if i18n.is_english(lang) else "تخصصات الصفحة التالية"
        ),
    )
    _offer_list(
        phone,
        body=i18n.paginated_list_body(
            lang,
            first_page=i18n.choose_specialty(lang),
            topic=(
                "More specialties" if i18n.is_english(lang) else "متابعة التخصصات"
            ),
            page=page_num,
            has_more=has_more,
            more_hint=i18n.specialties_list_more_hint(lang),
        ),
        button_label=i18n.specialties_label(lang),
        rows=rows,
        section_title=i18n.specialties_label(lang),
    )
    return True


def _offer_doctors_by_name_list(
    phone: str,
    db: Session,
    conversation: Conversation,
    *,
    reset: bool = False,
) -> bool:
    """Paginated doctor list (name + specialty). Last row is «More» when needed."""
    sess = _sess(phone)
    lang = _lang(conversation, sess)
    doctors = doctor_service.list_active_doctors(db, DEFAULT_CLINIC_ID, limit=200)
    if not doctors:
        _offer_buttons(
            phone,
            i18n.no_doctors_available(lang),
            i18n.no_doctors_alt_buttons(lang),
        )
        sess["awaiting"] = "no_slots_alt"
        return False

    page, has_more, page_num = _apply_list_page(
        sess, "doctors_name", doctors, reset=reset
    )
    rows: list[dict[str, str]] = []
    for doc in page:
        fields = i18n.doctor_display_fields(doc, lang)
        name = (fields.get("name") or f"Doctor {doc.doctor_id}")[:24]
        specialty = (fields.get("specialization") or "")[:72]
        rows.append(
            {
                "id": f"doctor_{doc.doctor_id}",
                "title": name,
                "description": specialty,
            }
        )
    rows = _rows_with_more(
        rows,
        lang,
        has_more,
        more_description=(
            "Next doctors" if i18n.is_english(lang) else "أطباء الصفحة التالية"
        ),
    )
    _offer_list(
        phone,
        body=i18n.paginated_list_body(
            lang,
            first_page=i18n.doctors_by_name_prompt(lang),
            topic=("More doctors" if i18n.is_english(lang) else "متابعة الأطباء"),
            page=page_num,
            has_more=has_more,
            more_hint=i18n.doctors_list_more_hint(lang),
        ),
        button_label=i18n.doctors_list_button_label(lang),
        rows=rows,
        section_title=i18n.doctors_list_button_label(lang),
    )
    return True


def _offer_slots_list(
    phone: str,
    day_slots: list[dict],
    lang: str | None,
    *,
    body: str,
    reset: bool = False,
    with_change_day: bool = False,
) -> None:
    sess = _sess(phone)
    sess["list_slots_cache"] = list(day_slots)
    sess["list_slots_with_change_day"] = bool(with_change_day)
    sess["list_slots_body"] = body
    reserved = 1 if with_change_day else 0
    page, has_more, page_num = _apply_list_page(
        sess, "slots", day_slots, reset=reset, reserved_tail=reserved
    )
    rows = [_slot_option_row(s, lang) for s in page]
    rows = _rows_with_more(
        rows,
        lang,
        has_more,
        more_description=(
            "Next times" if i18n.is_english(lang) else "مواعيد الصفحة التالية"
        ),
    )
    if with_change_day:
        rows.append(
            {
                "id": "change_day",
                "title": i18n.change_day_row_title(lang),
                "description": "",
            }
        )
    _offer_list(
        phone,
        body=i18n.paginated_list_body(
            lang,
            first_page=body,
            topic=("More times" if i18n.is_english(lang) else "متابعة المواعيد"),
            page=page_num,
            has_more=has_more,
            more_hint=i18n.times_list_more_hint(lang),
        ),
        button_label=i18n.times_button_label(lang),
        rows=rows,
        section_title=i18n.slots_section_title(lang),
    )


def _offer_dates_list(
    phone: str,
    dates: list[str],
    lang: str | None,
    *,
    body: str,
    reset: bool = False,
) -> None:
    sess = _sess(phone)
    sess["list_dates_cache"] = list(dates)
    sess["list_dates_body"] = body
    page, has_more, page_num = _apply_list_page(sess, "dates", dates, reset=reset)
    rows = _rows_with_more(
        _date_list_rows(page, lang),
        lang,
        has_more,
        more_description=(
            "Next days" if i18n.is_english(lang) else "أيام الصفحة التالية"
        ),
    )
    _offer_list(
        phone,
        body=i18n.paginated_list_body(
            lang,
            first_page=body,
            topic=("More days" if i18n.is_english(lang) else "متابعة الأيام"),
            page=page_num,
            has_more=has_more,
            more_hint=i18n.days_list_more_hint(lang),
        ),
        button_label=i18n.days_button_label(lang),
        rows=rows,
        section_title=i18n.dates_section_title(lang),
    )


def _offer_upcoming_appointments_list(
    phone: str,
    db: Session,
    conversation: Conversation,
    *,
    purpose: str,
    reset: bool = False,
) -> bool:
    """purpose: 'reschedule' | 'cancel'."""
    sess = _sess(phone)
    lang = _lang(conversation, sess)
    upcoming = booking_service.list_upcoming_appointments_for_phone(
        db, clinic_id=DEFAULT_CLINIC_ID, whatsapp_phone=phone
    )
    if not upcoming:
        return False
    sess["upcoming"] = {
        str(a["appointment_id"]): _appt_session_info(a, lang) for a in upcoming
    }
    page, has_more, page_num = _apply_list_page(
        sess, "appointments", upcoming, reset=reset
    )
    rows = _rows_with_more(
        [_appt_list_row(a, lang) for a in page],
        lang,
        has_more,
        more_description=(
            "Next appointments"
            if i18n.is_english(lang)
            else "مواعيد الصفحة التالية"
        ),
    )
    if purpose == "cancel":
        first = i18n.pick_appointment_to_cancel(lang)
        topic = "More appointments" if i18n.is_english(lang) else "متابعة المواعيد"
    else:
        first = i18n.pick_appointment_to_reschedule(lang)
        topic = "More appointments" if i18n.is_english(lang) else "متابعة المواعيد"
    _offer_list(
        phone,
        body=i18n.paginated_list_body(
            lang,
            first_page=first,
            topic=topic,
            page=page_num,
            has_more=has_more,
            more_hint=i18n.appointments_list_more_hint(lang),
        ),
        button_label=i18n.your_appointments_label(lang),
        rows=rows,
        section_title=i18n.appointments_section(lang),
    )
    return True


def _try_handle_list_more(
    phone: str,
    db: Session,
    conversation: Conversation,
    sess: dict[str, Any],
    choice: str,
    text: str,
) -> bool:
    """Advance a paginated WhatsApp list when the user picks «More»."""
    if not i18n.is_list_more_choice(choice, text):
        return False
    kind = sess.get("list_page_kind")
    if not kind:
        return False
    next_key = f"list_{kind}_next_offset"
    nxt = sess.get(next_key)
    if nxt is not None:
        sess[f"list_{kind}_offset"] = int(nxt)
        sess[f"list_{kind}_page"] = int(sess.get(f"list_{kind}_page") or 1) + 1

    lang = _lang(conversation, sess)
    if kind == "doctors_name":
        _offer_doctors_by_name_list(phone, db, conversation, reset=False)
    elif kind == "departments":
        if not _offer_departments_list(phone, db, conversation, reset=False):
            return False
    elif kind == "appointments":
        raw = conversation.state
        state_val = raw.value if hasattr(raw, "value") else raw
        purpose = "cancel" if state_val == ConversationState.CANCEL.value else "reschedule"
        if not _offer_upcoming_appointments_list(
            phone, db, conversation, purpose=purpose, reset=False
        ):
            return False
    elif kind == "dates":
        dates = list(sess.get("list_dates_cache") or [])
        if not dates and sess.get("doctor_id"):
            avail = booking_service.get_available_dates_and_slots(
                db, doctor_id=int(sess["doctor_id"]), clinic_id=DEFAULT_CLINIC_ID
            )
            dates = list(avail.get("dates", {}).keys())
        body = sess.get("list_dates_body") or i18n.choose_day(lang)
        _offer_dates_list(phone, dates, lang, body=body, reset=False)
    elif kind == "slots":
        day_slots = list(sess.get("list_slots_cache") or [])
        selected_date = sess.get("selected_date")
        if (not day_slots) and sess.get("doctor_id") and selected_date:
            avail = booking_service.get_available_dates_and_slots(
                db, doctor_id=int(sess["doctor_id"]), clinic_id=DEFAULT_CLINIC_ID
            )
            day_slots = _filter_bookable_slots(
                avail.get("dates", {}).get(str(selected_date)) or []
            )
        date_label = _date_option_title(str(selected_date or ""), lang)
        with_change_day = bool(sess.get("list_slots_with_change_day"))
        body = sess.get("list_slots_body") or i18n.choose_slot_on_date(lang, date_label)
        _offer_slots_list(
            phone,
            day_slots,
            lang,
            body=body,
            reset=False,
            with_change_day=with_change_day,
        )
    else:
        return False
    db.commit()
    return True


def _show_selected_doctor_card(
    phone: str,
    db: Session,
    doctor_id: int,
    *,
    lang: str,
) -> None:
    """Send only the chosen doctor's card before continuing booking."""
    doctor = doctor_service.get_doctor(db, doctor_id, clinic_id=DEFAULT_CLINIC_ID)
    if not doctor:
        return
    card = doctor_service.doctor_card_payload(doctor)
    # Location belongs on booking confirmation, not the doctor card.
    wa.send_doctor_cards(
        phone,
        [card],
        lang=lang,
        include_button=False,
    )


def _show_doctor_cards(phone: str, db: Session, department_id: int | None) -> bool:
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.clinic_id == DEFAULT_CLINIC_ID,
            Conversation.phone == phone,
            Conversation.state != ConversationState.CLOSED,
        )
        .order_by(Conversation.conversation_id.desc())
        .first()
    )
    lang = _lang(conversation) if conversation else "ar"

    if department_id:
        doctors = doctor_service.list_doctors_by_department(
            db,
            clinic_id=DEFAULT_CLINIC_ID,
            department_id=department_id,
            limit=5,
        )
    else:
        doctors = doctor_service.list_active_doctors(db, DEFAULT_CLINIC_ID, limit=5)
    if not doctors:
        _offer_buttons(
            phone,
            i18n.no_doctors_for_option(lang),
            i18n.no_doctors_alt_buttons(lang),
        )
        _sess(phone)["awaiting"] = "no_slots_alt"
        return False

    # Prefer WhatsApp Flow ImageCarousel when enabled; fallback to sequential cards.
    if flow_service.flow_enabled():
        screen_data = flow_service.build_doctor_picker_data(
            db,
            clinic_id=DEFAULT_CLINIC_ID,
            department_id=department_id,
            lang=lang,
        )
        if screen_data:
            try:
                wa.send_doctor_flow(
                    phone,
                    flow_id=WHATSAPP_FLOW_ID,
                    screen_data=screen_data,
                    body=i18n.doctor_flow_prompt(lang),
                    cta=WHATSAPP_FLOW_CTA,
                    draft=WHATSAPP_FLOW_DRAFT,
                )
                return True
            except Exception as exc:
                err = str(exc)
                if (not WHATSAPP_FLOW_DRAFT) and "flow_id" in err.lower():
                    print("Doctor Flow rejected; retrying with mode=draft...")
                    try:
                        wa.send_doctor_flow(
                            phone,
                            flow_id=WHATSAPP_FLOW_ID,
                            screen_data=screen_data,
                            body=i18n.doctor_flow_prompt(lang),
                            cta=WHATSAPP_FLOW_CTA,
                            draft=True,
                        )
                        return True
                    except Exception as draft_exc:
                        print(f"Doctor Flow draft retry failed, falling back to cards: {draft_exc}")
                else:
                    print(f"Doctor Flow failed, falling back to cards: {exc}")

    cards = [doctor_service.doctor_card_payload(d) for d in doctors]
    _remember_options(
        phone,
        [
            {
                "id": f"doctor_{c['doctor_id']}",
                "title": i18n.doctor_display_name(c, lang),
                "description": i18n.localize_specialty(c.get("specialization"), lang) or "",
            }
            for c in cards
        ],
    )
    wa.send_text(
        phone,
        "Available doctors — swipe cards and choose (or type number/name):"
        if i18n.is_english(lang)
        else "الأطباء المتاحون — مرّر بين الكروت واختر الطبيب (أو اكتب الرقم/الاسم):",
    )
    wa.send_doctor_cards(phone, cards, lang=lang)
    return True


def _appt_list_row(appt: dict, lang: str | None = "ar") -> dict[str, str]:
    """WhatsApp list row: doctor name on top, date/time below (no appointment ref)."""
    start: datetime = appt["slot_start"]
    doctor = i18n.doctor_display_name(appt, lang).strip() or "—"
    when = f"{_format_date(start, lang)} · {_format_time(start, lang)}"
    return {
        "id": f"appt_{appt['appointment_id']}",
        "title": doctor[:24],
        "description": when[:72],
    }


def _appt_session_info(appt: dict, lang: str | None = "ar") -> dict[str, Any]:
    """Normalize an upcoming-appointment dict for the in-memory session."""
    start = appt.get("slot_start")
    if isinstance(start, datetime):
        start_s = start.isoformat(sep=" ", timespec="minutes")
    else:
        start_s = str(start or "")
    return {
        "doctor_id": appt["doctor_id"],
        "name_ar": appt.get("name_ar"),
        "name_en": appt.get("name_en"),
        "doctor_name": i18n.doctor_display_name(appt, lang),
        "slot_start": start_s,
        "appointment_ref": appt.get("appointment_ref"),
        "specialization": appt.get("specialization"),
    }


def _resolve_upcoming_pick(
    db: Session,
    phone: str,
    sess: dict[str, Any],
    *,
    choice: str,
    text: str,
) -> tuple[int | None, dict[str, Any] | None]:
    """Resolve list/ref/name pick; rebuild session cache from DB when needed."""
    hit = booking_service.find_upcoming_appointment_choice(
        db,
        clinic_id=DEFAULT_CLINIC_ID,
        whatsapp_phone=phone,
        choice=choice,
        text=text,
        cached=sess.get("upcoming"),
    )
    if not hit:
        return None, None
    appt_id = int(hit["appointment_id"])
    info = _appt_session_info(hit, sess.get("language") or "ar")
    upcoming = dict(sess.get("upcoming") or {})
    upcoming[str(appt_id)] = info
    sess["upcoming"] = upcoming
    return appt_id, info


def _start_reschedule_flow(phone: str, db: Session, conversation: Conversation) -> None:
    lang = _lang(conversation)
    upcoming = booking_service.list_upcoming_appointments_for_phone(
        db, clinic_id=DEFAULT_CLINIC_ID, whatsapp_phone=phone
    )
    if not upcoming:
        wa.send_text(phone, i18n.no_upcoming_to_reschedule(lang))
        _finish_flow_quietly(phone, db, conversation)
        return

    set_conversation_state(
        db, conversation, ConversationState.RESCHEDULE, current_intent="reschedule"
    )
    sess = _sess(phone)
    _sess_clear_keep_lang(sess)
    sess["awaiting"] = "pick_appointment"
    if not _offer_upcoming_appointments_list(
        phone, db, conversation, purpose="reschedule", reset=True
    ):
        wa.send_text(phone, i18n.no_upcoming_to_reschedule(lang))
        _finish_flow_quietly(phone, db, conversation)
        return
    db.commit()


def _offer_reschedule_change_type(phone: str, sess: dict, lang: str | None = None) -> None:
    info = sess.get("current_appt") or {}
    start = datetime.fromisoformat(info["slot_start"])
    code = lang or "ar"
    doctor_name = i18n.doctor_display_name(info, code) or info.get("doctor_name")
    summary = i18n.current_appointment_change_prompt(
        code,
        doctor_name=doctor_name,
        date_label=_format_date(start, code),
        time_label=_format_time(start, code),
    )
    _offer_buttons(phone, summary, i18n.reschedule_change_buttons(code))


def _offer_reschedule_day_picker(phone: str, db: Session, sess: dict, lang: str) -> bool:
    """Same doctor, pick a new day then time. Returns False if no dates."""
    booking_service.release_expired_holds(db, clinic_id=DEFAULT_CLINIC_ID)
    avail = booking_service.get_available_dates_and_slots(
        db, doctor_id=sess["doctor_id"], clinic_id=DEFAULT_CLINIC_ID
    )
    dates = list(avail.get("dates", {}).keys())
    if not dates:
        wa.send_text(phone, i18n.no_alternative_slots(lang))
        return False
    sess["awaiting"] = "date"
    _offer_dates_list(
        phone, dates, lang, body=i18n.choose_new_day(lang), reset=True
    )
    return True


def _offer_reschedule_same_day_slots(
    phone: str, db: Session, sess: dict, lang: str
) -> bool:
    """Same doctor + same day, pick a new time only. Returns False if none."""
    info = sess.get("current_appt") or {}
    start = datetime.fromisoformat(info["slot_start"])
    selected_date = start.date().isoformat()
    sess["selected_date"] = selected_date
    booking_service.release_expired_holds(db, clinic_id=DEFAULT_CLINIC_ID)
    avail = booking_service.get_available_dates_and_slots(
        db, doctor_id=sess["doctor_id"], clinic_id=DEFAULT_CLINIC_ID
    )
    day_slots = _filter_bookable_slots(avail.get("dates", {}).get(selected_date) or [])
    if not day_slots:
        wa.send_text(phone, i18n.no_other_times_same_day(lang))
        return False
    sess["awaiting"] = "slot"
    date_label = _date_option_title(selected_date, lang)
    _offer_slots_list(
        phone,
        day_slots,
        lang,
        body=i18n.choose_same_day_time(lang, date_label),
        reset=True,
        with_change_day=False,
    )
    return True


def _start_cancel_flow(phone: str, db: Session, conversation: Conversation) -> None:
    lang = _lang(conversation)
    upcoming = booking_service.list_upcoming_appointments_for_phone(
        db, clinic_id=DEFAULT_CLINIC_ID, whatsapp_phone=phone
    )
    if not upcoming:
        wa.send_text(phone, i18n.no_upcoming_to_cancel(lang))
        _finish_flow_quietly(phone, db, conversation)
        return

    set_conversation_state(
        db, conversation, ConversationState.CANCEL, current_intent="cancel"
    )
    sess = _sess(phone)
    _sess_clear_keep_lang(sess)
    sess["awaiting"] = "pick_appointment"
    if not _offer_upcoming_appointments_list(
        phone, db, conversation, purpose="cancel", reset=True
    ):
        wa.send_text(phone, i18n.no_upcoming_to_cancel(lang))
        _finish_flow_quietly(phone, db, conversation)
        return
    db.commit()


def continue_after_doctor_selected(
    db: Session,
    *,
    phone: str,
    doctor_id: int,
) -> None:
    """Shared path after doctor chosen via Flow completion or card button."""
    conversation = get_or_create_conversation(
        db,
        tenant_id=DEFAULT_TENANT_ID,
        clinic_id=DEFAULT_CLINIC_ID,
        phone=phone,
    )
    sess = _sess(phone)
    sess["doctor_id"] = doctor_id
    lang = _lang(conversation)
    doctor = doctor_service.get_doctor(db, doctor_id, clinic_id=DEFAULT_CLINIC_ID)
    if not doctor:
        wa.send_text(phone, i18n.doctor_not_found(lang))
        return

    # Inquiry used to ask "book with this doctor?" after Select — redundant once
    # the patient already tapped a doctor card / list row. Continue into booking.
    if sess.get("flow") == "inquiry":
        sess["flow"] = "booking"

    sess["awaiting"] = None
    booking_service.release_expired_holds(db, clinic_id=DEFAULT_CLINIC_ID)
    avail = booking_service.get_available_dates_and_slots(
        db, doctor_id=doctor_id, clinic_id=DEFAULT_CLINIC_ID
    )
    dates = list(avail.get("dates", {}).keys())
    if not dates:
        _offer_buttons(
            phone,
            i18n.no_slots_for_doctor(lang),
            i18n.no_slots_alt_buttons(lang),
        )
        sess["awaiting"] = "no_slots_alt"
        db.commit()
        return

    # Reschedule with doctor change continues into RESCHEDULE date pick
    if sess.get("flow") == "reschedule_doctor":
        set_conversation_state(
            db, conversation, ConversationState.RESCHEDULE, current_intent="reschedule"
        )
        sess["awaiting"] = "date"
        _offer_dates_list(
            phone, dates, lang, body=i18n.choose_new_day(lang), reset=True
        )
        db.commit()
        return

    set_conversation_state(
        db, conversation, ConversationState.BOOKING_DATE, current_intent="booking_date"
    )
    _offer_dates_list(phone, dates, lang, body=i18n.choose_day(lang), reset=True)
    db.commit()


def _slot_rows_with_change_day(day_slots: list[dict], lang: str | None) -> list[dict[str, str]]:
    """Build first-page slot rows with change-day (for callers that still need rows)."""
    # Prefer _offer_slots_list; kept for voice paths that assemble rows themselves.
    reserved = 1
    capacity = _WA_LIST_MAX_ROWS - reserved
    page, has_more, _next = _page_items(day_slots, 0, capacity=capacity)
    rows = [_slot_option_row(s, lang) for s in page]
    rows = _rows_with_more(
        rows,
        lang,
        has_more,
        more_description=(
            "Show more times" if i18n.is_english(lang) else "عرض المزيد من المواعيد"
        ),
    )
    rows.append(
        {
            "id": "change_day",
            "title": i18n.change_day_row_title(lang),
            "description": "",
        }
    )
    return rows


def _reshow_booking_dates(phone: str, db: Session, conversation) -> bool:
    """Send the day picker again (used when the patient wants to change the day
    from the time-slot step, via a button or a voice request). Returns True when
    handled."""
    sess = _sess(phone)
    lang = _lang(conversation, sess)
    doctor_id = sess.get("doctor_id")
    if not doctor_id:
        return False
    booking_service.release_expired_holds(db, clinic_id=DEFAULT_CLINIC_ID)
    avail = booking_service.get_available_dates_and_slots(
        db, doctor_id=int(doctor_id), clinic_id=DEFAULT_CLINIC_ID
    )
    dates = list(avail.get("dates", {}).keys())
    if not dates:
        _offer_buttons(
            phone,
            i18n.no_slots_for_doctor(lang),
            i18n.no_slots_alt_buttons(lang),
        )
        sess["awaiting"] = "no_slots_alt"
        db.commit()
        return True
    set_conversation_state(
        db, conversation, ConversationState.BOOKING_DATE, current_intent="booking_date"
    )
    sess["awaiting"] = None
    _offer_dates_list(phone, dates, lang, body=i18n.choose_day(lang), reset=True)
    db.commit()
    return True


def _reshow_booking_slots(phone: str, db: Session, conversation) -> bool:
    """Re-open the time list for the currently selected doctor/day."""
    sess = _sess(phone)
    lang = _lang(conversation, sess)
    doctor_id = sess.get("doctor_id")
    selected_date = sess.get("selected_date")
    if not doctor_id or not selected_date:
        return False
    booking_service.release_expired_holds(db, clinic_id=DEFAULT_CLINIC_ID)
    avail = booking_service.get_available_dates_and_slots(
        db, doctor_id=int(doctor_id), clinic_id=DEFAULT_CLINIC_ID
    )
    day_slots = _filter_bookable_slots(
        avail.get("dates", {}).get(str(selected_date)) or []
    )
    if not day_slots:
        wa.send_text(phone, i18n.no_slots_on_day(lang))
        return False
    set_conversation_state(
        db, conversation, ConversationState.BOOKING_SLOT, current_intent="booking_slot"
    )
    date_label = _date_option_title(str(selected_date), lang)
    _offer_slots_list(
        phone,
        day_slots,
        lang,
        body=i18n.choose_slot_on_date(lang, date_label),
        reset=True,
        with_change_day=True,
    )
    sess["awaiting"] = "slot"
    db.commit()
    return True


def _collapse_letter_runs(text: str) -> str:
    """baaack → back (light typo tolerance for Back)."""
    return re.sub(r"(.)\1+", r"\1", (text or "").strip(), flags=re.IGNORECASE)


def _is_explicit_back_choice(choice: str, text: str) -> bool:
    """True only for real back/return wording, not generic 'no/cancel'."""
    back_tokens = {
        "رجوع",
        "ارجع",
        "إرجع",
        "عودة",
        "العودة",
        "back",
        "go back",
        "return",
    }
    for raw in (choice, text):
        s = (raw or "").strip()
        if not s:
            continue
        if s in {"رجوع", "ارجع", "إرجع", "عودة", "العودة", "Back", "back", "Return", "return", "go back"}:
            return True
        collapsed = _collapse_letter_runs(s).lower()
        if collapsed in back_tokens:
            return True
    return False


def _resolve_spoken_date_key(text: str, dates: list[str]) -> str | None:
    """Map بكرة / الإثنين / Wednesday onto an available YYYY-MM-DD key."""
    from app.services.voice_fastpath import resolve_date_key

    if not text or not dates:
        return None
    return resolve_date_key(
        date_hint=None,
        transcript=text,
        available=set(dates),
    )


def _handle_explicit_back(
    phone: str,
    db: Session,
    conversation: Conversation,
    *,
    conv_state: str,
    choice: str,
    text: str,
) -> bool:
    """Handle a text 'back' request by returning one sensible step."""
    if not _is_explicit_back_choice(choice, text):
        return False

    sess = _sess(phone)
    lang = _lang(conversation, sess)
    awaiting = sess.get("awaiting")

    if conv_state == ConversationState.BOOKING_DOCTOR.value:
        if awaiting == "doctor":
            if sess.get("doctor_pick_mode") == "by_specialty":
                if _offer_departments_list(phone, db, conversation, reset=True):
                    sess["awaiting"] = "department"
                    sess.pop("doctor_id", None)
                    db.commit()
                    return True
            sess.pop("department_id", None)
            sess.pop("doctor_pick_mode", None)
            _offer_buttons(phone, i18n.booking_path_prompt(lang), i18n.booking_path_buttons(lang))
            sess["awaiting"] = None
            db.commit()
            return True

        if awaiting == "department":
            sess.pop("department_id", None)
            _offer_buttons(phone, i18n.booking_path_prompt(lang), i18n.booking_path_buttons(lang))
            sess["awaiting"] = None
            db.commit()
            return True

        _clear_draft(phone)
        _send_main_menu(phone, db, conversation)
        return True

    if conv_state == ConversationState.BOOKING_DATE.value:
        sess.pop("doctor_id", None)
        if sess.get("department_id"):
            ok = _show_doctor_cards(phone, db, sess.get("department_id"))
            if ok:
                sess["awaiting"] = "doctor"
                sess["doctor_pick_mode"] = "by_specialty"
                db.commit()
                return True
        ok = _offer_doctors_by_name_list(phone, db, conversation, reset=True)
        if ok:
            sess["awaiting"] = "doctor"
            sess["doctor_pick_mode"] = "by_name"
            sess["department_id"] = None
            db.commit()
            return True
        _offer_buttons(phone, i18n.booking_path_prompt(lang), i18n.booking_path_buttons(lang))
        db.commit()
        return True

    if conv_state == ConversationState.BOOKING_SLOT.value:
        return _reshow_booking_dates(phone, db, conversation)

    if conv_state == ConversationState.PATIENT_DETAILS.value:
        return _reshow_booking_slots(phone, db, conversation)

    if conv_state == ConversationState.CONFIRMING.value:
        return _reshow_booking_slots(phone, db, conversation)

    if conv_state == ConversationState.RESCHEDULE.value:
        if awaiting == "pick_appointment":
            _clear_draft(phone)
            _send_main_menu(phone, db, conversation)
            return True
        if awaiting == "change_type":
            _start_reschedule_flow(phone, db, conversation)
            return True
        if awaiting == "date":
            _offer_reschedule_change_type(phone, sess, lang=lang)
            sess["awaiting"] = "change_type"
            db.commit()
            return True
        if awaiting == "slot":
            if sess.get("flow") == "reschedule_time":
                _offer_reschedule_change_type(phone, sess, lang=lang)
                sess["awaiting"] = "change_type"
                db.commit()
                return True
            if _offer_reschedule_day_picker(phone, db, sess, lang):
                db.commit()
                return True
        if awaiting == "confirm":
            if sess.get("flow") == "reschedule_time":
                _offer_reschedule_change_type(phone, sess, lang=lang)
                sess["awaiting"] = "change_type"
                db.commit()
                return True
            if _offer_reschedule_day_picker(phone, db, sess, lang):
                db.commit()
                return True

    if conv_state == ConversationState.CANCEL.value:
        if awaiting == "pick_appointment":
            _clear_draft(phone)
            _send_main_menu(phone, db, conversation)
            return True
        if awaiting == "confirm":
            _start_cancel_flow(phone, db, conversation)
            return True

    return False


def node_persist_inbound(state: GraphState) -> GraphState:
    db: Session = state["db_session"]
    phone = state["phone"]
    text = state.get("text") or ""
    conversation = get_or_create_conversation(
        db,
        tenant_id=DEFAULT_TENANT_ID,
        clinic_id=DEFAULT_CLINIC_ID,
        phone=phone,
    )
    log_message(
        db,
        conversation_id=conversation.conversation_id,
        direction="inbound",
        message_type=(
            MessageType.VOICE if state.get("message_type") == "audio" else MessageType.TEXT
        ),
        text=text or state.get("payload_id"),
        status="received",
    )
    db.commit()
    raw_state = conversation.state
    return {
        **state,
        "conversation_id": conversation.conversation_id,
        "conversation_state": (
            raw_state.value if hasattr(raw_state, "value") else (raw_state or ConversationState.NEW.value)
        ),
    }


def node_handle(state: GraphState) -> GraphState:
    db: Session = state["db_session"]
    phone = state["phone"]
    text = (state.get("text") or "").strip()
    payload_id = (state.get("payload_id") or "").strip()
    sess = _sess(phone)
    conversation = (
        db.query(Conversation)
        .filter_by(conversation_id=state["conversation_id"])
        .one()
    )
    conv_state = state.get("conversation_state") or ConversationState.NEW.value

    # ---- Per-message language detection (before any LLM / reply work) ----
    lang_svc = LanguageService(db, conversation, sess)
    if state.get("keep_language"):
        # Synthesized routing seed from the voice fastpath: the caller's language
        # was already decided from the audio, which is more reliable than
        # detecting it from our own Arabic seed text.
        lang = lang_svc.language
    else:
        lang = lang_svc.sync_from_user_text(text, payload_id=payload_id)
    db.commit()

    choice = _choice(state, lang=lang)
    intent = detect_intent(
        text or choice,
        lang=lang,
        db=db,
        tenant_id=DEFAULT_TENANT_ID,
        clinic_id=DEFAULT_CLINIC_ID,
    )
    state = {**state, "language": lang}

    # ---- BR-015: high-risk medical language → urgent handover (no advice) ----
    if safety.is_high_risk_medical(text) or safety.is_high_risk_medical(choice):
        handover_service.create_handover(
            db,
            phone=phone,
            reason=f"High-risk medical language: {(text or choice)[:300]}",
            priority=HandoverPriority.URGENT,
            patient_message=safety.emergency_patient_message(lang),
        )
        _clear_draft(phone)
        return {**state, "handled": True}

    # ---- Language bootstrap (auto-detect; no language-select screen) ----
    in_lang_select = conv_state == ConversationState.LANGUAGE_SELECT.value
    # Digits "1"/"2" only mean language while on a leftover language-select screen.
    lang_ar_labels = set(i18n.LANG_AR_CHOICES)
    lang_en_labels = set(i18n.LANG_EN_CHOICES)
    if not in_lang_select:
        lang_ar_labels.discard("1")
        lang_en_labels.discard("2")
    from app.language.language_service import (
        _is_explicit_arabic_phrase,
        _is_explicit_english_phrase,
    )

    explicit_ar = (
        choice in lang_ar_labels
        or text in lang_ar_labels
        or _is_explicit_arabic_phrase(text)
    )
    explicit_en = (
        choice in lang_en_labels
        or text in lang_en_labels
        or _is_explicit_english_phrase(text)
    )

    # Mid-flow explicit switch (e.g. "English please") even when language is set.
    if conversation.language is not None and not in_lang_select:
        if explicit_en:
            lang = lang_svc.set_language("en")
            db.commit()
        elif explicit_ar:
            lang = lang_svc.set_language("ar")
            db.commit()

    if conversation.language is None or in_lang_select:
        sample = text or choice or payload_id
        detected = detect_language(sample, fallback=None)
        if explicit_ar:
            lang = lang_svc.set_language("ar")
        elif explicit_en:
            lang = lang_svc.set_language("en")
        elif detected is not None:
            lang = lang_svc.set_language(detected)
        elif conversation.language is None:
            # MENU / منيو / numbers / empty → default Arabic (never ask again).
            lang = lang_svc.set_language("ar")
        else:
            lang = _lang(conversation, sess)
        db.commit()

        # Escape leftover language_select state from older sessions.
        if in_lang_select:
            _send_main_menu(phone, db, conversation)
            return {**state, "language": lang, "handled": True}

    # Mid-conversation switch: language already updated on Conversation;
    # continue the current flow in the new language (no extra confirmation).
    lang = _lang(conversation, sess)
    state = {**state, "language": lang}

    # Global MENU — explicit command only (not greetings mid-flow).
    menu_tokens = {"MENU", "منيو", "القائمة", "القائمه", "قائمة"}
    explicit_menu = (
        choice.strip().upper() == "MENU"
        or text.strip().upper() == "MENU"
        or choice.strip() in menu_tokens
        or text.strip() in menu_tokens
    )
    if explicit_menu:
        _clear_draft(phone)
        _send_main_menu(phone, db, conversation)
        return {**state, "handled": True}

    if _handle_explicit_back(
        phone,
        db,
        conversation,
        conv_state=conv_state,
        choice=choice,
        text=text,
    ):
        return {**state, "handled": True}

    if _try_handle_list_more(phone, db, conversation, sess, choice, text):
        return {**state, "handled": True}

    # UC-002 rebook CTA after cancel (state may already be MAIN_MENU)
    if sess.get("awaiting") == "post_cancel":
        rebook = {
            "حجز موعد جديد",
            "Book again",
            "Book appointment",
            "حجز",
            "Book",
        } | i18n.BOOK_CHOICES
        if choice in rebook or text in rebook:
            _sess_clear_keep_lang(sess)
            sess["flow"] = "booking"
            set_conversation_state(
                db,
                conversation,
                ConversationState.BOOKING_DOCTOR,
                current_intent="booking_started",
            )
            _offer_buttons(phone, i18n.booking_path_prompt(lang), i18n.booking_path_buttons(lang))
            db.commit()
            return {**state, "handled": True}
        _clear_draft(phone)
        _finish_flow_quietly(phone, db, conversation)
        return {**state, "handled": True}

    # UC-006 voice transcript confirmation
    if sess.get("awaiting") == "voice_confirm":
        if choice in i18n.VOICE_CONFIRM_CHOICES or text in i18n.VOICE_CONFIRM_CHOICES:
            transcript = sess.pop("voice_transcript", "") or ""
            sess["awaiting"] = None
            if transcript:
                process_incoming_message(
                    db,
                    phone=phone,
                    text=transcript,
                    payload_id=None,
                    message_type="text",
                )
                return {**state, "handled": True}
            wa.send_text(phone, i18n.voice_resend(lang))
            return {**state, "handled": True}
        _clear_draft(phone)
        wa.send_text(phone, i18n.voice_retry_clear(lang))
        _finish_flow_quietly(phone, db, conversation)
        return {**state, "handled": True}

    # ---- New / closed / greetings ----
    if conv_state in {
        ConversationState.NEW.value,
        ConversationState.CLOSED.value,
        ConversationState.MAIN_MENU.value,
    }:
        update_hit = (
            intent == Intent.UPDATE
            or choice in i18n.RESCHEDULE_CHOICES
            or text in i18n.RESCHEDULE_CHOICES
        )
        if update_hit:
            _start_reschedule_flow(phone, db, conversation)
            return {**state, "handled": True}

        cancel_hit = (
            intent == Intent.CANCEL
            or choice in i18n.CANCEL_CHOICES
            or text in i18n.CANCEL_CHOICES
        )
        if cancel_hit:
            _start_cancel_flow(phone, db, conversation)
            return {**state, "handled": True}

        book_hit = (
            intent == Intent.BOOK
            or choice in i18n.BOOK_CHOICES
            or text in i18n.BOOK_CHOICES
        )
        if book_hit:
            set_conversation_state(
                db,
                conversation,
                ConversationState.BOOKING_DOCTOR,
                current_intent="booking_started",
            )
            sess = _sess(phone)
            _sess_clear_keep_lang(sess)
            sess["flow"] = "booking"
            _offer_buttons(phone, i18n.booking_path_prompt(lang), i18n.booking_path_buttons(lang))
            db.commit()
            return {**state, "handled": True}

        inquiry_hit = (
            intent == Intent.ASK_DOCTORS
            or choice in i18n.INQUIRY_CHOICES
            or text in i18n.INQUIRY_CHOICES
        )
        if inquiry_hit:
            set_conversation_state(
                db,
                conversation,
                ConversationState.BOOKING_DOCTOR,
                current_intent="inquiry",
            )
            sess = _sess(phone)
            _sess_clear_keep_lang(sess)
            sess["flow"] = "inquiry"
            _offer_buttons(
                phone,
                i18n.inquiry_prompt(lang),
                i18n.booking_path_buttons(lang),
            )
            db.commit()
            return {**state, "handled": True}

        handover_hit = (
            intent == Intent.HANDOVER
            or choice in i18n.HANDOVER_CHOICES
            or text in i18n.HANDOVER_CHOICES
        )
        if handover_hit:
            handover_service.create_handover(
                db,
                phone=phone,
                reason="Patient requested receptionist",
                priority=HandoverPriority.NORMAL,
            )
            return {**state, "handled": True}

        if intent == Intent.THANKS:
            wa.send_text(phone, i18n.thanks_ack(lang))
            return {**state, "handled": True}

        # Greeting / explicit menu intent while idle → open the menu as a
        # welcome (no apology; greetings are classified as Intent.MENU).
        if intent == Intent.MENU:
            _send_main_menu(phone, db, conversation)
            return {**state, "handled": True}

        # A leftover interactive tap (an old date/slot/doctor button the patient
        # taps after the flow already moved on, or after returning to the menu):
        # don't re-dump the whole menu — that reads as the menu "popping up
        # twice" / the bot glitching. A short nudge is enough.
        if payload_id:
            wa.send_text(phone, i18n.stale_option_hint(lang))
            return {**state, "handled": True}

        # Any other unrecognized free-text while idle → acknowledge we didn't
        # understand BEFORE showing the menu, so it doesn't feel like the menu
        # popped up at random (common after an unclear voice note).
        if (text or choice).strip():
            wa.send_text(phone, i18n.not_understood_menu(lang))
            _send_main_menu(phone, db, conversation)
        return {**state, "handled": True}

    # ---- Booking: choose path / specialty / doctor ----
    if conv_state == ConversationState.BOOKING_DOCTOR.value:
        if sess.get("awaiting") == "inquiry_book_cta":
            if (
                choice in i18n.INQUIRY_BOOK_CHOICES
                or text in i18n.INQUIRY_BOOK_CHOICES
            ):
                doctor_id = int(sess.get("doctor_id") or 0)
                sess["flow"] = "booking"
                sess["awaiting"] = None
                if doctor_id:
                    continue_after_doctor_selected(db, phone=phone, doctor_id=doctor_id)
                return {**state, "handled": True}
            _clear_draft(phone)
            _finish_flow_quietly(phone, db, conversation)
            return {**state, "handled": True}

        if sess.get("awaiting") == "no_slots_alt":
            if (
                choice in i18n.NO_SLOTS_RETRY_CHOICES
                or text in i18n.NO_SLOTS_RETRY_CHOICES
            ):
                sess.pop("doctor_id", None)
                sess["awaiting"] = None
                _offer_buttons(
                    phone,
                    i18n.booking_path_prompt(_lang(conversation)),
                    i18n.booking_path_buttons(_lang(conversation)),
                )
                db.commit()
                return {**state, "handled": True}
            if (
                choice in i18n.NO_SLOTS_HANDOVER_CHOICES
                or text in i18n.NO_SLOTS_HANDOVER_CHOICES
            ):
                handover_service.create_handover(
                    db, phone=phone, reason="No slots/doctors available", priority=HandoverPriority.NORMAL
                )
                _clear_draft(phone)
                return {**state, "handled": True}
            _clear_draft(phone)
            _finish_flow_quietly(phone, db, conversation)
            return {**state, "handled": True}

    if conv_state == ConversationState.BOOKING_DOCTOR.value and not sess.get("doctor_id"):
        if _is_booking_path_choice(choice, text, i18n.PATH_SPECIALTY):
            lang = _lang(conversation)
            if not _offer_departments_list(phone, db, conversation, reset=True):
                _offer_buttons(
                    phone,
                    i18n.no_departments(lang),
                    i18n.no_departments_buttons(lang),
                )
                sess["awaiting"] = "no_slots_alt"
                db.commit()
                return {**state, "handled": True}
            sess["awaiting"] = "department"
            db.commit()
            return {**state, "handled": True}

        department_id = None
        if choice.startswith("dept_"):
            department_id = int(choice.replace("dept_", ""))
        elif sess.get("awaiting") == "department":
            dept = doctor_service.find_department(db, DEFAULT_CLINIC_ID, name=text)
            department_id = dept.department_id if dept else None

        if _is_booking_path_choice(choice, text, i18n.PATH_BY_DOCTOR_NAME):
            # By doctor name → list names + specialties (not all cards at once)
            ok = _offer_doctors_by_name_list(phone, db, conversation, reset=True)
            if ok:
                sess["awaiting"] = "doctor"
                sess["doctor_pick_mode"] = "by_name"
                sess["department_id"] = None
            db.commit()
            return {**state, "handled": True}

        if department_id is not None or (
            sess.get("awaiting") == "department" and department_id
        ):
            ok = _show_doctor_cards(phone, db, department_id)
            if ok:
                sess["awaiting"] = "doctor"
                sess["doctor_pick_mode"] = "by_specialty"
                sess["department_id"] = department_id
            db.commit()
            return {**state, "handled": True}

        from app.services.choice_resolver import looks_like_schedule_booking_text
        from app.services.voice_fastpath import find_doctor_by_hint

        doctor_id = None
        schedule_text = looks_like_schedule_booking_text(text)
        if choice.startswith("doctor_"):
            doctor_id = int(choice.replace("doctor_", ""))
        elif sess.get("awaiting") == "doctor":
            for doc in doctor_service.list_active_doctors(db, DEFAULT_CLINIC_ID, limit=50):
                name_ar = (doc.name_ar or "").strip()
                name_en = (doc.name_en or "").strip()
                if (name_ar and name_ar in text) or (
                    name_en and name_en.lower() in text.lower()
                ):
                    doctor_id = doc.doctor_id
                    break
            if doctor_id is None and schedule_text:
                hinted = find_doctor_by_hint(db, DEFAULT_CLINIC_ID, text)
                if hinted:
                    doctor_id = hinted.doctor_id
                else:
                    # "احجز الدكتور ده يوم …" with a single open doctor card.
                    tnorm = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
                    if any(p in tnorm for p in ("الدكتور ده", "الدكتور دا", "this doctor")):
                        doc_opts = [
                            o
                            for o in (sess.get("last_options") or [])
                            if str(o.get("id") or "").startswith("doctor_")
                        ]
                        if len(doc_opts) == 1:
                            doctor_id = int(str(doc_opts[0]["id"]).replace("doctor_", ""))

        if doctor_id:
            lang = _lang(conversation, sess)
            # Name-list path: show only the selected doctor's card, then continue.
            if sess.get("doctor_pick_mode") == "by_name":
                _show_selected_doctor_card(phone, db, doctor_id, lang=lang)
            sess.pop("doctor_pick_mode", None)
            sess.pop("doctor_name_list_offset", None)
            sess.pop("doctor_name_list_next_offset", None)
            continue_after_doctor_selected(db, phone=phone, doctor_id=doctor_id)
            # Booking sentence with a day → jump to that day's slots when possible.
            if schedule_text:
                avail = booking_service.get_available_dates_and_slots(
                    db, doctor_id=doctor_id, clinic_id=DEFAULT_CLINIC_ID
                )
                dates = list(avail.get("dates", {}).keys())
                selected_date = _resolve_spoken_date_key(text, dates)
                if selected_date and selected_date in dates:
                    day_slots = _filter_bookable_slots(
                        avail.get("dates", {}).get(selected_date) or []
                    )
                    if day_slots:
                        sess["selected_date"] = selected_date
                        set_conversation_state(
                            db,
                            conversation,
                            ConversationState.BOOKING_SLOT,
                            current_intent="booking_slot",
                        )
                        date_label = _date_option_title(selected_date, lang)
                        _offer_slots_list(
                            phone,
                            day_slots,
                            lang,
                            body=i18n.choose_slot_on_date(lang, date_label),
                            reset=True,
                        )
                        db.commit()
            return {**state, "handled": True}

        # Already waiting for a doctor pick — don't re-ask specialty vs name.
        if sess.get("awaiting") == "doctor":
            if sess.get("doctor_pick_mode") == "by_name":
                _offer_doctors_by_name_list(phone, db, conversation)
            else:
                _show_doctor_cards(phone, db, sess.get("department_id"))
            db.commit()
            return {**state, "handled": True}

        _offer_buttons(phone, i18n.booking_path_prompt(_lang(conversation)), i18n.booking_path_buttons(_lang(conversation)))
        db.commit()
        return {**state, "handled": True}

    # ---- Date ----
    if conv_state == ConversationState.BOOKING_DATE.value:
        if _sess_missing(phone, db, conversation, "doctor_id"):
            return {**state, "handled": True}
        lang = _lang(conversation, sess)
        avail = booking_service.get_available_dates_and_slots(
            db, doctor_id=sess["doctor_id"], clinic_id=DEFAULT_CLINIC_ID
        )
        dates = list(avail.get("dates", {}).keys())
        if choice.startswith("date_"):
            selected_date = choice.replace("date_", "")
        elif text in dates:
            selected_date = text
        else:
            selected_date = _resolve_spoken_date_key(text, dates)

        if not selected_date or selected_date not in dates:
            wa.send_text(phone, i18n.choose_day_from_list(lang))
            if dates:
                _offer_dates_list(
                    phone, dates, lang, body=i18n.choose_day(lang), reset=True
                )
            db.commit()
            return {**state, "handled": True}

        sess["selected_date"] = selected_date
        day_slots = _filter_bookable_slots(
            avail.get("dates", {}).get(selected_date) or []
        )
        if not day_slots:
            wa.send_text(phone, i18n.no_slots_on_day(lang))
            if dates:
                _offer_dates_list(
                    phone, dates, lang, body=i18n.choose_day(lang), reset=True
                )
            db.commit()
            return {**state, "handled": True}
        set_conversation_state(
            db, conversation, ConversationState.BOOKING_SLOT, current_intent="booking_slot"
        )
        date_label = _date_option_title(selected_date, lang)
        _offer_slots_list(
            phone,
            day_slots,
            lang,
            body=i18n.choose_slot_on_date(lang, date_label),
            reset=True,
            with_change_day=True,
        )
        db.commit()
        return {**state, "handled": True}

    # ---- Slot hold ----
    if conv_state == ConversationState.BOOKING_SLOT.value:
        if _sess_missing(phone, db, conversation, "doctor_id"):
            return {**state, "handled": True}
        lang = _lang(conversation, sess)
        # "Change the day" from the time list → re-open the day picker.
        if choice == "change_day" or text == "change_day":
            _reshow_booking_dates(phone, db, conversation)
            return {**state, "handled": True}
        if not choice.startswith("slot_"):
            wa.send_text(phone, i18n.choose_time_from_list(lang))
            _reshow_booking_slots(phone, db, conversation)
            return {**state, "handled": True}
        slot_id = int(choice.replace("slot_", ""))
        try:
            hold_result = booking_service.hold_slot(
                db,
                slot_id=slot_id,
                clinic_id=DEFAULT_CLINIC_ID,
                held_by_phone=phone,
                hold_minutes=SLOT_HOLD_MINUTES,
            )
        except BookingError as exc:
            wa.send_text(phone, i18n.hold_error(lang, str(exc)))
            _reshow_booking_slots(phone, db, conversation)
            return {**state, "handled": True}
        sess["slot_id"] = slot_id
        _store_hold_deadline(sess, hold_result)
        set_conversation_state(
            db, conversation, ConversationState.PATIENT_DETAILS, current_intent="patient_details"
        )
        _clear_options(phone)
        lang = _lang(conversation, sess)
        existing = patient_service.find_patient_by_phone(
            db, clinic_id=DEFAULT_CLINIC_ID, whatsapp_phone=phone
        )
        if existing and (existing.name or "").strip():
            sess["known_patient_name"] = patient_service.normalize_person_name(existing.name)
            sess["awaiting"] = "known_patient_confirm"
            _offer_buttons(
                phone,
                i18n.known_patient_prompt(lang, sess["known_patient_name"]),
                i18n.known_patient_buttons(lang),
            )
        else:
            sess["awaiting"] = "patient_name"
            wa.send_text(phone, i18n.ask_patient_full_name(lang))
        db.commit()
        return {**state, "handled": True}

    # ---- Patient details ----
    if conv_state == ConversationState.PATIENT_DETAILS.value:
        if _abort_if_hold_timed_out(phone, db, conversation, sess):
            return {**state, "handled": True}
        lang = _lang(conversation, sess)

        if sess.get("awaiting") == "known_patient_confirm":
            if choice in i18n.SAME_PATIENT_CHOICES or text in i18n.SAME_PATIENT_CHOICES:
                stored = patient_service.normalize_person_name(
                    sess.get("known_patient_name") or ""
                )
                if patient_service.is_valid_person_name(stored):
                    sess["patient_name"] = stored
                    if _advance_after_patient_name(phone, sess, lang=lang):
                        db.commit()
                        return {**state, "handled": True}
                    # awaiting=summary → fall through below
                else:
                    sess["awaiting"] = "patient_name"
                    _clear_options(phone)
                    wa.send_text(phone, i18n.complete_profile_name(lang))
                    db.commit()
                    return {**state, "handled": True}
            elif choice in i18n.NAME_CHANGED_CHOICES or text in i18n.NAME_CHANGED_CHOICES:
                sess["awaiting"] = "patient_name"
                _clear_options(phone)
                wa.send_text(phone, i18n.ask_patient_full_name(lang))
                db.commit()
                return {**state, "handled": True}
            else:
                # Voice: "أنا اسمي علي محمود…" — accept a spoken triple name
                # instead of only the Same patient / Name changed buttons.
                cleaned = patient_service.normalize_person_name(text)
                if patient_service.is_valid_person_name(cleaned):
                    sess["patient_name"] = cleaned
                    _clear_options(phone)
                    if _advance_after_patient_name(phone, sess, lang=lang):
                        db.commit()
                        return {**state, "handled": True}
                    # awaiting=summary → fall through below
                else:
                    _offer_buttons(
                        phone,
                        i18n.known_patient_prompt(
                            lang, sess.get("known_patient_name") or ""
                        ),
                        i18n.known_patient_buttons(lang),
                    )
                    return {**state, "handled": True}

        if sess.get("awaiting") == "patient_name":
            cleaned = patient_service.normalize_person_name(text)
            if not patient_service.is_valid_person_name(cleaned):
                wa.send_text(phone, i18n.patient_name_too_short(lang))
                return {**state, "handled": True}
            # Overwrite any previous draft name (voice correction).
            sess["patient_name"] = cleaned
            if _advance_after_patient_name(phone, sess, lang=lang):
                db.commit()
                return {**state, "handled": True}
            # fall through to summary

        if sess.get("awaiting") == "dob_gate":
            if REQUIRE_DOB:
                sess["awaiting"] = "dob_value"
                _clear_options(phone)
                wa.send_text(phone, i18n.ask_dob(lang))
                db.commit()
                return {**state, "handled": True}
            sess["awaiting"] = "summary"

        if sess.get("awaiting") == "dob_value":
            raw = text.strip()
            try:
                datetime.strptime(raw, "%Y-%m-%d")
            except ValueError:
                wa.send_text(phone, i18n.invalid_dob(lang))
                return {**state, "handled": True}
            sess["dob"] = raw
            sess["awaiting"] = "summary"

        if sess.get("awaiting") == "summary":
            if _sess_missing(phone, db, conversation, "doctor_id", "slot_id"):
                return {**state, "handled": True}
            doctor = doctor_service.get_doctor(
                db, sess["doctor_id"], clinic_id=DEFAULT_CLINIC_ID
            )
            slot_row = (
                db.query(AppointmentSlot)
                .filter(AppointmentSlot.slot_id == sess["slot_id"])
                .one()
            )
            fields = i18n.doctor_display_fields(doctor, lang)
            loc = clinic_settings_service.format_clinic_location_display(
                db, DEFAULT_CLINIC_ID, lang
            )
            dups = booking_service.find_duplicate_appointments(
                db,
                clinic_id=DEFAULT_CLINIC_ID,
                whatsapp_phone=phone,
                doctor_id=sess["doctor_id"],
            )
            dup_note = ""
            if dups and not sess.get("duplicate_ack"):
                ref = dups[0].get("appointment_ref") or ""
                when = _format_date(dups[0]["slot_start"], lang)
                dup_note = i18n.duplicate_appointment_note(lang, ref=ref, when=when)
                sess["duplicate_ack"] = True
            summary = i18n.booking_summary(
                lang,
                patient_name=sess.get("patient_name"),
                phone=phone,
                doctor_name=fields["name"],
                specialization=fields["specialization"],
                date_label=_format_date(slot_row.slot_start, lang),
                time_label=_format_time(slot_row.slot_start, lang),
                location=loc,
                dup_note=dup_note,
            )
            set_conversation_state(
                db, conversation, ConversationState.CONFIRMING, current_intent="confirming"
            )
            _offer_buttons(phone, summary, i18n.confirm_buttons(lang))
            db.commit()
            return {**state, "handled": True}

    # ---- Confirm ----
    if conv_state == ConversationState.CONFIRMING.value:
        if _abort_if_hold_timed_out(phone, db, conversation, sess):
            return {**state, "handled": True}
        lang = _lang(conversation)
        if choice in i18n.CANCEL_ABORT_CHOICES or text in i18n.CANCEL_ABORT_CHOICES:
            slot_row = (
                db.query(AppointmentSlot)
                .filter(AppointmentSlot.slot_id == sess.get("slot_id"))
                .one_or_none()
            )
            if slot_row and slot_row.status == SlotStatus.HELD:
                slot_row.status = SlotStatus.AVAILABLE
                slot_row.hold_expires_at = None
                slot_row.updated_by = "user_abort_hold"
                db.commit()
            _clear_draft(phone)
            wa.send_text(phone, i18n.booking_process_cancelled(lang))
            _finish_flow_quietly(phone, db, conversation)
            return {**state, "handled": True}

        if choice in i18n.CONFIRM_CHOICES or text in i18n.CONFIRM_CHOICES:
            if _sess_missing(phone, db, conversation, "doctor_id", "slot_id"):
                return {**state, "handled": True}
            try:
                result = booking_service.confirm_booking(
                    db,
                    tenant_id=DEFAULT_TENANT_ID,
                    clinic_id=DEFAULT_CLINIC_ID,
                    whatsapp_phone=phone,
                    patient_name=sess.get("patient_name"),
                    doctor_id=sess["doctor_id"],
                    slot_id=sess["slot_id"],
                    dob=sess.get("dob"),
                )
            except BookingError as exc:
                if _is_hold_timeout_error(exc):
                    _notify_booking_hold_timeout(phone, db, conversation)
                else:
                    wa.send_text(phone, i18n.booking_error(lang, str(exc)))
                    _finish_flow_quietly(phone, db, conversation)
                return {**state, "handled": True}

            start = datetime.fromisoformat(result["slot_start"])
            doctor_name = (
                result.get("doctor_name_en") or result.get("doctor_name_ar")
                if i18n.is_english(lang)
                else result.get("doctor_name_ar") or result.get("doctor_name_en")
            )
            msg = i18n.confirmation(
                lang,
                appointment_ref=result["appointment_ref"],
                doctor_name=doctor_name,
                specialization=result.get("specialization"),
                date_label=_format_date(start, lang),
                time_label=_format_time(start, lang),
                location=clinic_settings_service.format_clinic_location_display(
                    db, DEFAULT_CLINIC_ID, lang
                ),
            )
            wa.send_text(phone, msg)
            log_message(
                db,
                conversation_id=conversation.conversation_id,
                direction="outbound",
                message_type=MessageType.TEXT,
                text=msg,
                status="sent",
            )
            db.commit()
            _finish_flow_quietly(phone, db, conversation)
            return {**state, "handled": True}

        _offer_buttons(
            phone, i18n.confirm_booking_hint(lang), i18n.confirm_buttons(lang)
        )
        return {**state, "handled": True}

    # ---- Reschedule (UC-003) ----
    if conv_state == ConversationState.RESCHEDULE.value:
        awaiting = sess.get("awaiting")
        lang = _lang(conversation)

        # After uvicorn reload the in-memory draft is empty while DB state stays
        # RESCHEDULE — recover instead of re-sending the pick list.
        if not awaiting:
            if (choice or "").startswith("appt_") or (
                text and sess.get("upcoming")
            ):
                awaiting = "pick_appointment"
                sess["awaiting"] = "pick_appointment"
            elif sess.get("appointment_id") and sess.get("current_appt"):
                awaiting = "change_type"
                sess["awaiting"] = "change_type"

        if awaiting == "pick_appointment":
            appt_id, info = _resolve_upcoming_pick(
                db, phone, sess, choice=choice, text=text
            )
            if not info or appt_id is None:
                # Don't restart the whole flow (feels like a duplicate list).
                wa.send_text(phone, i18n.pick_appointment_or_ref(lang))
                # Re-offer the same list once so the user can tap again.
                upcoming_rows = booking_service.list_upcoming_appointments_for_phone(
                    db, clinic_id=DEFAULT_CLINIC_ID, whatsapp_phone=phone
                )
                if upcoming_rows:
                    _offer_upcoming_appointments_list(
                        phone, db, conversation, purpose="reschedule", reset=False
                    )
                db.commit()
                return {**state, "handled": True}

            start = datetime.fromisoformat(info["slot_start"])
            if booking_service.is_within_reschedule_cutoff(start):
                handover_service.create_handover(
                    db,
                    phone=phone,
                    reason=(
                        f"Reschedule cutoff passed ({RESCHEDULE_CUTOFF_HOURS}h) for "
                        f"{info.get('appointment_ref')}"
                    ),
                    priority=HandoverPriority.HIGH,
                )
                _clear_draft(phone)
                return {**state, "handled": True}

            sess["appointment_id"] = appt_id
            sess["doctor_id"] = int(info["doctor_id"])
            sess["current_appt"] = info
            sess["awaiting"] = "change_type"
            _offer_reschedule_change_type(phone, sess, lang=lang)
            db.commit()
            return {**state, "handled": True}

        if awaiting == "change_type":
            if (
                choice in i18n.RESCHEDULE_BACK
                or text in i18n.RESCHEDULE_BACK
                or text in {"لا", "No", "no"}
            ):
                _clear_draft(phone)
                wa.send_text(phone, i18n.keep_appointment_unchanged(lang))
                _finish_flow_quietly(phone, db, conversation)
                return {**state, "handled": True}

            # 1) Change doctor → doctor + day + time
            if (
                choice in i18n.RESCHEDULE_CHANGE_DOCTOR
                or text in i18n.RESCHEDULE_CHANGE_DOCTOR
            ):
                sess["flow"] = "reschedule_doctor"
                sess.pop("doctor_id", None)
                sess["awaiting"] = None
                set_conversation_state(
                    db,
                    conversation,
                    ConversationState.BOOKING_DOCTOR,
                    current_intent="reschedule_doctor",
                )
                _offer_buttons(
                    phone,
                    i18n.choose_new_doctor(lang),
                    i18n.booking_path_buttons(lang),
                )
                db.commit()
                return {**state, "handled": True}

            # 2) Change day → same doctor, new day + time
            if (
                choice in i18n.RESCHEDULE_CHANGE_DAY
                or text in i18n.RESCHEDULE_CHANGE_DAY
            ):
                sess["flow"] = "reschedule_day"
                if not _offer_reschedule_day_picker(phone, db, sess, lang):
                    _finish_flow_quietly(phone, db, conversation)
                    return {**state, "handled": True}
                db.commit()
                return {**state, "handled": True}

            # 3) Change time → same doctor + same day, new time only
            if (
                choice in i18n.RESCHEDULE_CHANGE_TIME
                or text in i18n.RESCHEDULE_CHANGE_TIME
            ):
                sess["flow"] = "reschedule_time"
                if not _offer_reschedule_same_day_slots(phone, db, sess, lang):
                    if not _offer_reschedule_day_picker(phone, db, sess, lang):
                        _finish_flow_quietly(phone, db, conversation)
                        return {**state, "handled": True}
                    sess["flow"] = "reschedule_day"
                db.commit()
                return {**state, "handled": True}

            _offer_reschedule_change_type(phone, sess, lang=lang)
            db.commit()
            return {**state, "handled": True}

        if awaiting == "date":
            avail = booking_service.get_available_dates_and_slots(
                db, doctor_id=sess["doctor_id"], clinic_id=DEFAULT_CLINIC_ID
            )
            dates = list(avail.get("dates", {}).keys())
            if choice.startswith("date_"):
                selected_date = choice.replace("date_", "")
            elif text in dates:
                selected_date = text
            else:
                selected_date = _resolve_spoken_date_key(text, dates)

            if not selected_date or selected_date not in dates:
                wa.send_text(phone, i18n.choose_day_from_list(lang))
                if dates:
                    _offer_dates_list(
                        phone, dates, lang, body=i18n.choose_new_day(lang), reset=True
                    )
                db.commit()
                return {**state, "handled": True}

            sess["selected_date"] = selected_date
            day_slots = _filter_bookable_slots(
                avail.get("dates", {}).get(selected_date) or []
            )
            if not day_slots:
                wa.send_text(phone, i18n.no_slots_on_day(lang))
                if dates:
                    _offer_dates_list(
                        phone, dates, lang, body=i18n.choose_new_day(lang), reset=True
                    )
                db.commit()
                return {**state, "handled": True}
            sess["awaiting"] = "slot"
            date_label = _date_option_title(selected_date, lang)
            _offer_slots_list(
                phone,
                day_slots,
                lang,
                body=i18n.choose_new_time_on_date(lang, date_label),
                reset=True,
                with_change_day=False,
            )
            db.commit()
            return {**state, "handled": True}

        if awaiting == "slot":
            if not choice.startswith("slot_"):
                wa.send_text(phone, i18n.choose_time_from_list(lang))
                selected_date = sess.get("selected_date")
                if sess.get("doctor_id") and selected_date:
                    avail = booking_service.get_available_dates_and_slots(
                        db, doctor_id=sess["doctor_id"], clinic_id=DEFAULT_CLINIC_ID
                    )
                    day_slots = _filter_bookable_slots(
                        avail.get("dates", {}).get(str(selected_date)) or []
                    )
                    if day_slots:
                        date_label = _date_option_title(str(selected_date), lang)
                        body = sess.get("list_slots_body") or i18n.choose_new_time_on_date(
                            lang, date_label
                        )
                        _offer_slots_list(
                            phone,
                            day_slots,
                            lang,
                            body=body,
                            reset=True,
                            with_change_day=bool(sess.get("list_slots_with_change_day")),
                        )
                db.commit()
                return {**state, "handled": True}
            slot_id = int(choice.replace("slot_", ""))
            try:
                hold_result = booking_service.hold_slot(
                    db,
                    slot_id=slot_id,
                    clinic_id=DEFAULT_CLINIC_ID,
                    held_by_phone=phone,
                    hold_minutes=SLOT_HOLD_MINUTES,
                )
            except BookingError as exc:
                wa.send_text(phone, i18n.hold_error(lang, str(exc)))
                selected_date = sess.get("selected_date")
                if sess.get("doctor_id") and selected_date:
                    avail = booking_service.get_available_dates_and_slots(
                        db, doctor_id=sess["doctor_id"], clinic_id=DEFAULT_CLINIC_ID
                    )
                    day_slots = _filter_bookable_slots(
                        avail.get("dates", {}).get(str(selected_date)) or []
                    )
                    if day_slots:
                        date_label = _date_option_title(str(selected_date), lang)
                        body = sess.get("list_slots_body") or i18n.choose_new_time_on_date(
                            lang, date_label
                        )
                        _offer_slots_list(
                            phone,
                            day_slots,
                            lang,
                            body=body,
                            reset=True,
                            with_change_day=bool(sess.get("list_slots_with_change_day")),
                        )
                db.commit()
                return {**state, "handled": True}
            sess["slot_id"] = slot_id
            _store_hold_deadline(sess, hold_result)
            sess["awaiting"] = "confirm"
            doctor = doctor_service.get_doctor(
                db, sess["doctor_id"], clinic_id=DEFAULT_CLINIC_ID
            )
            slot_row = (
                db.query(AppointmentSlot)
                .filter(AppointmentSlot.slot_id == slot_id)
                .one()
            )
            old = sess.get("current_appt") or {}
            fields = i18n.doctor_display_fields(doctor, lang) if doctor else {"name": ""}
            loc = clinic_settings_service.format_clinic_location_display(
                db, DEFAULT_CLINIC_ID, lang
            )
            summary = i18n.reschedule_summary(
                lang,
                appointment_ref=old.get("appointment_ref"),
                doctor_name=fields.get("name") or old.get("doctor_name"),
                date_label=_format_date(slot_row.slot_start, lang),
                time_label=_format_time(slot_row.slot_start, lang),
                location=loc,
            )
            _offer_buttons(phone, summary, i18n.confirm_buttons(lang))
            db.commit()
            return {**state, "handled": True}

        if awaiting == "confirm":
            if _abort_if_hold_timed_out(phone, db, conversation, sess, reschedule=True):
                return {**state, "handled": True}
            if choice in i18n.CANCEL_ABORT_CHOICES or text in i18n.CANCEL_ABORT_CHOICES:
                slot_row = (
                    db.query(AppointmentSlot)
                    .filter(AppointmentSlot.slot_id == sess.get("slot_id"))
                    .one_or_none()
                )
                if slot_row and slot_row.status == SlotStatus.HELD:
                    slot_row.status = SlotStatus.AVAILABLE
                    slot_row.hold_expires_at = None
                    db.commit()
                _clear_draft(phone)
                wa.send_text(phone, i18n.reschedule_process_cancelled(lang))
                _finish_flow_quietly(phone, db, conversation)
                return {**state, "handled": True}

            if choice in i18n.CONFIRM_CHOICES or text in i18n.CONFIRM_CHOICES:
                try:
                    result = booking_service.reschedule_appointment(
                        db,
                        clinic_id=DEFAULT_CLINIC_ID,
                        whatsapp_phone=phone,
                        appointment_id=sess["appointment_id"],
                        new_slot_id=sess["slot_id"],
                    )
                except BookingError as exc:
                    if _is_hold_timeout_error(exc):
                        _notify_booking_hold_timeout(
                            phone, db, conversation, reschedule=True
                        )
                    else:
                        wa.send_text(phone, i18n.reschedule_error(lang, str(exc)))
                        _finish_flow_quietly(phone, db, conversation)
                    return {**state, "handled": True}

                start = datetime.fromisoformat(result["slot_start"])
                doctor_name = (
                    result.get("doctor_name_en") or result.get("doctor_name_ar")
                    if i18n.is_english(lang)
                    else result.get("doctor_name_ar") or result.get("doctor_name_en")
                )
                msg = i18n.reschedule_confirmation(
                    lang,
                    appointment_ref=result["appointment_ref"],
                    doctor_name=doctor_name,
                    specialization=result.get("specialization"),
                    date_label=_format_date(start, lang),
                    time_label=_format_time(start, lang),
                    location=clinic_settings_service.format_clinic_location_display(
                        db, DEFAULT_CLINIC_ID, lang
                    ),
                )
                wa.send_text(phone, msg)
                _finish_flow_quietly(phone, db, conversation)
                return {**state, "handled": True}

            _offer_buttons(
                phone, i18n.confirm_reschedule_hint(lang), i18n.confirm_buttons(lang)
            )
            return {**state, "handled": True}

        # Draft lost and nothing to recover — start clean once.
        _start_reschedule_flow(phone, db, conversation)
        return {**state, "handled": True}

    # ---- Cancel (UC-002) ----
    if conv_state == ConversationState.CANCEL.value:
        awaiting = sess.get("awaiting")
        lang = _lang(conversation)

        if awaiting == "pick_appointment":
            appt_id, info = _resolve_upcoming_pick(
                db, phone, sess, choice=choice, text=text
            )
            if not info or appt_id is None:
                wa.send_text(phone, i18n.pick_appointment_or_ref(lang))
                upcoming_rows = booking_service.list_upcoming_appointments_for_phone(
                    db, clinic_id=DEFAULT_CLINIC_ID, whatsapp_phone=phone
                )
                if upcoming_rows:
                    _offer_upcoming_appointments_list(
                        phone, db, conversation, purpose="cancel", reset=False
                    )
                db.commit()
                return {**state, "handled": True}

            start = datetime.fromisoformat(info["slot_start"])
            hours_left = (start - datetime.utcnow()).total_seconds() / 3600
            if hours_left < CANCEL_CUTOFF_HOURS:
                handover_service.create_handover(
                    db,
                    phone=phone,
                    reason=(
                        f"Cancel cutoff passed ({CANCEL_CUTOFF_HOURS}h) for "
                        f"{info.get('appointment_ref')}"
                    ),
                    priority=HandoverPriority.HIGH,
                )
                _clear_draft(phone)
                return {**state, "handled": True}

            sess["appointment_id"] = appt_id
            sess["current_appt"] = info
            sess["awaiting"] = "confirm"
            summary = i18n.cancel_summary(
                lang,
                appointment_ref=str(info.get("appointment_ref") or appt_id),
                doctor_name=info.get("doctor_name"),
                date_label=_format_date(start, lang),
                time_label=_format_time(start, lang),
            )
            _offer_buttons(phone, summary, i18n.cancel_confirm_buttons(lang))
            db.commit()
            return {**state, "handled": True}

        if awaiting == "confirm":
            if choice in i18n.BACK_CHOICES or text in i18n.BACK_CHOICES:
                _clear_draft(phone)
                wa.send_text(phone, i18n.keep_appointment_no_cancel(lang))
                _finish_flow_quietly(phone, db, conversation)
                return {**state, "handled": True}

            if (
                choice in i18n.CONFIRM_CANCEL_CHOICES
                or text in i18n.CONFIRM_CANCEL_CHOICES
            ):
                try:
                    result = booking_service.cancel_appointment(
                        db,
                        clinic_id=DEFAULT_CLINIC_ID,
                        whatsapp_phone=phone,
                        appointment_id=sess["appointment_id"],
                        reason="Cancelled via WhatsApp by patient",
                    )
                except BookingError as exc:
                    wa.send_text(phone, i18n.cancel_error(lang, str(exc)))
                    _finish_flow_quietly(phone, db, conversation)
                    return {**state, "handled": True}

                start = (
                    datetime.fromisoformat(result["slot_start"])
                    if result.get("slot_start")
                    else None
                )
                doctor_name = (
                    result.get("doctor_name_en") or result.get("doctor_name_ar") or ""
                    if i18n.is_english(lang)
                    else result.get("doctor_name_ar") or result.get("doctor_name_en") or ""
                )
                msg = i18n.cancel_confirmation(
                    lang,
                    appointment_ref=result["appointment_ref"],
                    doctor_name=doctor_name,
                    specialization=result.get("specialization"),
                    date_label=_format_date(start, lang) if start else "-",
                    time_label=_format_time(start, lang) if start else "-",
                )
                _offer_buttons(phone, msg, i18n.post_cancel_buttons(lang))
                _sess_clear_keep_lang(sess)
                sess["awaiting"] = "post_cancel"
                set_conversation_state(
                    db, conversation, ConversationState.MAIN_MENU, current_intent="cancelled"
                )
                db.commit()
                return {**state, "handled": True}

            _offer_buttons(
                phone, i18n.confirm_cancel_hint(lang), i18n.cancel_confirm_buttons(lang)
            )
            return {**state, "handled": True}

        _start_cancel_flow(phone, db, conversation)
        return {**state, "handled": True}

    if conv_state == ConversationState.HANDOVER.value:
        wa.send_text(phone, i18n.handover_already_open(_lang(conversation)))
        return {**state, "handled": True}
    # Unknown mid-flow state: nudge without dumping the full welcome menu.
    wa.send_text(phone, i18n.type_menu_hint(_lang(conversation)))
    _finish_flow_quietly(phone, db, conversation)
    return {**state, "handled": True}


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("persist_inbound", node_persist_inbound)
    graph.add_node("handle", node_handle)
    graph.set_entry_point("persist_inbound")
    graph.add_edge("persist_inbound", "handle")
    graph.add_edge("handle", END)
    return graph.compile()


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


def process_incoming_message(
    db: Session,
    *,
    phone: str,
    text: str,
    payload_id: str | None = None,
    message_type: str = "text",
    keep_language: bool = False,
) -> None:
    """Run one inbound turn through the graph.

    keep_language: the text is bot-synthesized (a voice fastpath routing seed
    like "حجز موعد"), not the patient's own words, so language must NOT be
    re-detected from it — that flipped English callers back to Arabic.
    """
    get_graph().invoke(
        {
            "phone": phone,
            "text": text,
            "payload_id": payload_id or "",
            "message_type": message_type,
            "db_session": db,
            "handled": False,
            "keep_language": keep_language,
        }
    )
