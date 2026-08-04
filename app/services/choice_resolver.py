"""
Map free-text / typed numbers to an interactive option id.

The LLM only picks from the offered options — it never generates the bot reply.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from openai import OpenAI
from sqlalchemy.orm import Session

from app.core.config import OPENAI_API_KEY, OPENAI_MODEL
from app.language.multilingual_prompt import build_system_prompt
from app.services.conversation_service import log_openai_chat_usage


Option = dict[str, Any]  # id, title, description?

# Free-text that must NOT collapse onto an open doctor/date/slot list.
_BOOK_CUES = (
    "احجز",
    "حجز",
    "عايز احجز",
    "عاوز احجز",
    "عايزة احجز",
    "عايزه احجز",
    "book",
    "booking",
    "i want to book",
    "make an appointment",
)
_DAY_CUES = (
    "بكره",
    "بكرة",
    "بكرا",
    "غدا",
    "بعد بكره",
    "بعد بكرة",
    "بعد غد",
    "يوم ",
    "الاثنين",
    "الاتنين",
    "الثلاثاء",
    "التلات",
    "الاربعاء",
    "الاربع",
    "الخميس",
    "الجمعة",
    "الجمعه",
    "السبت",
    "الاحد",
    "tomorrow",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "after tomorrow",
    "day after tomorrow",
)
_TIME_CUES = (
    "ساع",
    "الساع",
    "الصبح",
    "المساء",
    "بليل",
    " am",
    " pm",
    "صباحا",
    "مساء",
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def looks_like_schedule_booking_text(user_text: str) -> bool:
    """True when the user is asking to book a day/time, not picking a list row."""
    n = _norm(user_text)
    if not n:
        return False
    # Fold Arabic alef variants for cue matching.
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي")):
        n = n.replace(src, dst)
    has_book = any(c in n for c in _BOOK_CUES)
    has_day = any(c in n for c in _DAY_CUES)
    has_time = any(c in n for c in _TIME_CUES) or bool(
        re.search(r"\d{1,2}\s*:\s*\d{2}", n)
    )
    return has_book and (has_day or has_time)


def _options_look_like_pickers(options: list[Option]) -> bool:
    """Doctor / date / slot lists — dangerous to fuzzy-map long booking sentences onto."""
    for opt in options:
        oid = str(opt.get("id") or "")
        if oid.startswith(("doctor_", "date_", "slot_", "dept_", "appt_")):
            return True
        if _is_time_like_title(str(opt.get("title") or "")):
            return True
        if _is_date_like_title(str(opt.get("title") or "")):
            return True
    return False


def resolve_choice_rules(user_text: str, options: list[Option]) -> str | None:
    """Fast local matching: index, id, title, partial title/description."""
    text = (user_text or "").strip()
    if not text or not options:
        return None

    # Pure number → 1-based index (only when the whole message is a number)
    if re.fullmatch(r"\d{1,2}", text):
        idx = int(text) - 1
        if 0 <= idx < len(options):
            return str(options[idx]["id"])

    # Arabic-Indic digits
    arab_map = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    digit_text = text.translate(arab_map)
    if digit_text != text and re.fullmatch(r"\d{1,2}", digit_text):
        idx = int(digit_text) - 1
        if 0 <= idx < len(options):
            return str(options[idx]["id"])

    n = _norm(text)
    time_like = any(_is_time_like_title(str(o.get("title") or "")) for o in options)
    date_like = any(
        str(o.get("id") or "").startswith("date_")
        or _is_date_like_title(str(o.get("title") or ""))
        for o in options
    )
    # Slot/day lists: exact id/title only — no substring / fuzzy contains.
    strict = time_like or date_like

    for opt in options:
        oid = str(opt.get("id") or "")
        title = str(opt.get("title") or "")
        desc = str(opt.get("description") or "")
        if n == _norm(oid) or n == _norm(title):
            return oid
        if strict:
            continue
        # "اختيار د. فلان" style (non-time lists only)
        if title and _norm(title) in n:
            return oid
        if n and n in _norm(title):
            return oid
        if desc and (n in _norm(desc) or _norm(desc) in n):
            return oid
    return None


def _is_time_like_title(title: str) -> bool:
    t = title or ""
    if re.search(r"\d{1,2}\s*:\s*\d{2}", t):
        return True
    return bool(re.search(r"\b(am|pm)\b", t, flags=re.IGNORECASE)) or (
        ("ص" in t or "م" in t) and ":" in t
    )


def _is_date_like_title(title: str) -> bool:
    t = title or ""
    return bool(re.search(r"\d{1,2}-\d{1,2}-\d{4}", t) or re.search(r"\d{4}-\d{2}-\d{2}", t))


def _extract_clock_hours(text: str) -> set[int]:
    """Hours the user mentioned as clock time (not bare list-index messages)."""
    raw = (text or "").strip()
    if not raw:
        return set()
    # Bare "3" / "٧" is list index, not a clock claim for this check.
    arab_map = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    digit_only = raw.translate(arab_map)
    if re.fullmatch(r"\d{1,2}", digit_only):
        return set()

    t = raw.translate(arab_map)
    hours: set[int] = set()
    for m in re.finditer(r"(\d{1,2})\s*:\s*\d{2}", t):
        h = int(m.group(1))
        if 1 <= h <= 12 or 0 <= h <= 23:
            hours.add(h % 12 or 12)
            hours.add(h)
    # «الساعة 7» / «الساعه 1» / «7 متاح» / «at 7»
    for m in re.finditer(
        r"(?:الساع[ةه]|الساعه|ساعة|الساعه|at\s+)?\b(\d{1,2})\b",
        t,
        flags=re.IGNORECASE,
    ):
        h = int(m.group(1))
        if 1 <= h <= 12:
            hours.add(h)
        elif 0 <= h <= 23:
            hours.add(h)
            hours.add(h % 12 or 12)
    return hours


def _option_clock_hours(title: str) -> set[int]:
    hours: set[int] = set()
    for m in re.finditer(r"(\d{1,2})\s*:\s*\d{2}", title or ""):
        h = int(m.group(1))
        hours.add(h)
        if 0 <= h <= 23:
            hours.add(h % 12 or 12)
    return hours


def _llm_pick_consistent(user_text: str, options: list[Option], option_id: str) -> bool:
    """Reject LLM picks that ignore a clearly spoken clock hour not in that option."""
    spoken = _extract_clock_hours(user_text)
    if not spoken:
        return True
    opt = next((o for o in options if str(o.get("id")) == option_id), None)
    if not opt:
        return False
    title = str(opt.get("title") or "")
    if not _is_time_like_title(title):
        return True
    opt_hours = _option_clock_hours(title)
    if not opt_hours:
        return True
    # Require overlap between spoken hour and the option's displayed hours.
    return bool(spoken & opt_hours)


def resolve_choice_llm(
    user_text: str,
    options: list[Option],
    *,
    lang: str | None = None,
    db: Session | None = None,
    tenant_id: int | None = None,
    clinic_id: int | None = None,
) -> str | None:
    """Ask OpenAI which option id matches; return only that id or None."""
    if not OPENAI_API_KEY or not user_text.strip() or not options:
        return None
    catalog = [
        {
            "id": str(o.get("id")),
            "title": o.get("title"),
            "description": o.get("description") or "",
            "number": i + 1,
        }
        for i, o in enumerate(options)
    ]
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        t0 = time.perf_counter()
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": build_system_prompt(
                        lang or "ar", purpose="choice_mapper"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "user_text": user_text,
                            "options": catalog,
                            "reminder": (
                                "Return null if the user asks about a time/day that is "
                                "not in options. Never substitute a different slot."
                            ),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        latency_ms = int(round((time.perf_counter() - t0) * 1000))
        log_openai_chat_usage(
            db,
            tenant_id=tenant_id,
            clinic_id=clinic_id,
            model=OPENAI_MODEL,
            operation="text_choice",
            completion=completion,
            latency_ms=latency_ms,
            status="completed",
        )
        content = completion.choices[0].message.content or "{}"
        payload = json.loads(content)
        option_id = payload.get("option_id")
        if option_id is None:
            return None
        option_id = str(option_id).strip()
        allowed = {str(o.get("id")) for o in options}
        if option_id not in allowed:
            return None
        if not _llm_pick_consistent(user_text, options, option_id):
            print(
                f"[choice_resolver] rejected inconsistent LLM pick "
                f"{option_id!r} for {user_text!r}"
            )
            return None
        return option_id
    except Exception as exc:
        print(f"[choice_resolver] LLM failed: {exc}")
        log_openai_chat_usage(
            db,
            tenant_id=tenant_id,
            clinic_id=clinic_id,
            model=OPENAI_MODEL,
            operation="text_choice",
            completion=None,
            status="failed",
        )
        return None


def resolve_choice(
    user_text: str,
    options: list[Option] | None,
    *,
    lang: str | None = None,
    db: Session | None = None,
    tenant_id: int | None = None,
    clinic_id: int | None = None,
    allow_llm: bool = True,
) -> str | None:
    """Rules first, then LLM (optional). Returns option id or None."""
    options = options or []
    if not options:
        return None

    # "احجز الدكتور ده يوم الأربعاء" must not become doctor_13 via fuzzy/LLM.
    skip_fuzzy = looks_like_schedule_booking_text(user_text) and _options_look_like_pickers(
        options
    )
    if skip_fuzzy:
        # Still allow a pure list index ("1") or exact option title/id.
        text = (user_text or "").strip()
        arab_map = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        digit_text = text.translate(arab_map)
        if re.fullmatch(r"\d{1,2}", digit_text):
            return resolve_choice_rules(user_text, options)
        n = _norm(text)
        for opt in options:
            oid = str(opt.get("id") or "")
            title = str(opt.get("title") or "")
            if n == _norm(oid) or n == _norm(title):
                return oid
        return None

    hit = resolve_choice_rules(user_text, options)
    if hit:
        return hit
    if not allow_llm:
        return None
    return resolve_choice_llm(
        user_text,
        options,
        lang=lang,
        db=db,
        tenant_id=tenant_id,
        clinic_id=clinic_id,
    )
