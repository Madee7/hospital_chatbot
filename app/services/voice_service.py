"""WhatsApp voice → Whisper STT → LLM structured action (OpenAI only)."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from datetime import date, timedelta
from typing import Any, Callable, TypeVar

import openai
import requests
from openai import OpenAI
from sqlalchemy.orm import Session

from app.core.config import (
    DEFAULT_CLINIC_ID,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_STT_MODEL,
    OPENAI_VOICE_STRUCTURE_MODEL,
    VOICE_ROUTER_V2,
    WHATSAPP_API_VERSION,
    WHATSAPP_TOKEN,
)
from app.services.voice_prompts import PLANNER_SYSTEM
from app.services.voice_schemas import VoicePlan, VoiceUnderstanding
# TODO: prefer DB-driven matching via doctor_service.infer_department_from_text(clinic_id)
# once a Session/clinic_id is threaded into _sanitize (option b). For now aliases stay
# in doctor_service._SPECIALTY_ALIASES as the single source of truth.
from app.services import voice_cost
from app.services.doctor_service import is_specialty_word, specialty_alias_words

logger = logging.getLogger(__name__)

Option = dict[str, Any]
T = TypeVar("T")

# In-process Whisper vocabulary prompt cache: clinic_id → (expires_at, prompt)
_STT_PROMPT_CACHE: dict[int, tuple[float, str]] = {}
_STT_PROMPT_TTL_SEC = 600.0  # 10 minutes
_STT_PROMPT_MAX_CHARS = 500


def _calendar_context_block(today: date | None = None) -> str:
    """Precomputed TODAY / TOMORROW / DAY_AFTER for the LLM user message.

    Keeps relative Arabic (بكرة / بعد بكرة) from inventing wrong ISO dates.
    Volatile — must stay in the user message, never in PLANNER_SYSTEM.
    """
    today = today or date.today()
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)
    return (
        f"CALENDAR (use these exact ISO dates for relative words):\n"
        f"TODAY={today.isoformat()} (weekday={today.strftime('%A')})\n"
        f"TOMORROW={tomorrow.isoformat()} (weekday={tomorrow.strftime('%A')})  "
        f"← بكرة / بكره / بكرا / غداً / tomorrow\n"
        f"DAY_AFTER_TOMORROW={day_after.isoformat()} "
        f"(weekday={day_after.strftime('%A')})  "
        f"← بعد بكرة / بعد بكره / بعد غد / day after tomorrow\n"
        "If the transcript says بعد بكرة (or بعد بكره), use DAY_AFTER_TOMORROW, "
        "NOT TOMORROW. Always set slots.date / date_hint to the ISO string.\n"
    )

_SYSTEM = """You are an intelligent router for New Giza University Hospital's WhatsApp chatbot.
Patients speak Egyptian Arabic. Your job is to extract maximum information and route efficiently.

========================================================================
BOOKING FLOW OVERVIEW
========================================================================
Standard linear flow:
1. Welcome -> Book intent
2. Choose specialty OR doctor
3. Choose date
4. Choose time slot
5. Provide full name
6. Confirm booking

SMART ROUTING: When patient provides multiple pieces at once, extract ALL and skip steps.

========================================================================
ACTION TYPES (choose exactly ONE)
========================================================================

- book_direct: Patient mentions a PERSON's name as doctor.
  Examples: "احجز مع دكتور علي" / "عايز دكتور أحمد سمير بكرة" /
            "موعد مع رانيا الساعة 2" / "احجز مع د. محمد يوم الأحد الصبح".
  MUST FILL:
    - doctor_hint: PERSON NAME ONLY (strip "دكتور", "د.", titles)
    - date_hint: YYYY-MM-DD if a date is mentioned (see date rules)
    - time_hint: if a time/period is mentioned (see time rules)
    - intent: "book"
    - confidence: 0.8-1.0 if doctor name is clear
  DO NOT use if only a specialty is mentioned without a person name.

- specialty_direct: Patient mentions a specialty/department WITHOUT a person name.
  Examples: "عايز دكتور قلب" / "احجز في عظام بكرة" /
            "موعد تخصص أطفال الساعة 3" / "دكتور باطنة".
  MUST FILL:
    - specialty_hint: department/specialty name (e.g. "قلب", "عظام")
    - date_hint / time_hint if mentioned
    - doctor_hint: MUST be null
    - intent: "book"
    - confidence: 0.7-1.0 if specialty is recognized
  Specialty words: قلب، عظام، أطفال، نساء، جراحة، باطنة، أسنان، عيون.
  "دكتور [specialty]" -> specialty, NOT a doctor name.

- select_option: Patient picks from OPTIONS_JSON (by number or title).
  Examples: "رقم 1" / "1" / "واحد" / exact title / "الخيار الأول".
  MUST FILL:
    - selected_option_id: exact id from OPTIONS_JSON
    - confidence: 0.9+ if exact match
  PRIORITY: If OPTIONS_JSON is non-empty and the response matches, prefer this
  over other actions. selected_option_id MUST exist in OPTIONS_JSON. If a number
  is said, match by position (1 = first option).

- intent: Patient expresses a general intent without enough details.
  intent values: book / update / cancel / ask_doctors / confirm / menu / handover.
  Examples: "عايز احجز" -> book; "الغي الموعد" -> cancel; "نعم تمام" -> confirm;
            "عايز اكلم حد" -> handover.
  If the patient provides a doctor/specialty WITH the intent, use book_direct or
  specialty_direct instead.

- INQUIRY / AVAILABILITY questions (asking ABOUT doctors, specialties, or open
  times rather than booking now): use intent="ask_doctors", confidence 0.6-0.9.
  Examples: "مين الأطباء المتاحين؟" / "عايز أعرف مواعيد دكتور عمر خالد" /
            "إيه المواعيد المتاحة لدكتور الأطفال؟" / "التخصصات المتاحة؟".
  - If a specialty is named -> action="specialty_direct" (specialty_hint), intent="ask_doctors".
  - If a doctor person name is named -> action="book_direct" (doctor_hint), intent="ask_doctors".
  - Otherwise -> action="intent", intent="ask_doctors".
  NEVER mark an answerable availability/info question as "clarify".

- clarify: Input is unclear, ambiguous, or unintelligible (noise, incomplete,
  cannot determine intent). Set confidence 0.0-0.4 and summary_ar explaining why.
  AVOID OVERUSE: if CURRENT_STEP context makes the intent clear, or the patient is
  clearly asking about doctors/availability, do NOT use clarify.

========================================================================
DATE PARSING RULES (always convert to concrete YYYY-MM-DD)
========================================================================
The user message gives a CALENDAR block with precomputed dates:
  TODAY=…  TOMORROW=…  DAY_AFTER_TOMORROW=…
Copy the matching ISO into date_hint. Never invent years; never leave
date_hint null when بكرة / بعد بكرة was spoken; never write the word
"tomorrow" — only YYYY-MM-DD.

Relative keywords (check "بعد بكرة" BEFORE bare "بكرة" — substring overlap):
  بعد بكرة / بعد بكره / بعد بكرا / بعد غد / day after tomorrow / after tomorrow
      -> date_hint = DAY_AFTER_TOMORROW
  بكرة / بكره / بكرا / غداً / tomorrow / bukra
      -> date_hint = TOMORROW
  النهاردة / اليوم / today -> date_hint = TODAY
  أمبارح / امس -> past (not bookable)

Weekdays alone (الأحد/الإثنين/…/السبت or Sunday/…) -> the NEXT occurrence
of that weekday from TODAY.
If weekday + calendar date together (Friday 14-8, الجمعة 14/8) -> use the
calendar date as DD-MM (14 August), NOT the nearest Friday/Saturday/etc.

Examples (when CALENDAR says TODAY=2026-08-04, TOMORROW=2026-08-05,
DAY_AFTER_TOMORROW=2026-08-06):
  "بكرة" / "بكره" -> 2026-08-05
  "بعد بكرة" / "بعد بكره" -> 2026-08-06  (NOT 2026-08-05)
  "يوم الأحد" -> next Sunday ; "friday" -> next Friday
  "Friday 14-8" / "الجمعة 14-8" -> 2026-08-14 (not nearest Friday).
OUTPUT FORMAT: always YYYY-MM-DD.

========================================================================
TIME PARSING RULES
========================================================================
Specific times:
  2 / اتنين / الساعة 2 -> "14:00" (assume PM unless context says AM)
  10 / عشرة            -> "10:00" (AM)
  2:30 / اتنين ونص     -> "14:30"
  3:15 / تلاتة وربع    -> "15:15"
  5 المساء / 5 بليل    -> "17:00"
  9 الصبح              -> "09:00"

Time periods (store the keyword; system expands to slots):
  الصبح / الصباح       -> "morning"   (~09:00-12:00)
  بعد الضهر / الظهر    -> "afternoon" (~12:00-17:00)
  المساء / بليل / الليل -> "evening"  (~17:00-20:00)
  أي وقت / أي ميعاد    -> "any"

Priority: specific time > period. "عايز موعد بكرة الصبح الساعة 10" -> time_hint="10:00".
OUTPUT: specific times as "HH:MM" (24h); periods as morning/afternoon/evening/any.

========================================================================
CONTEXT-AWARE ROUTING (CURRENT_STEP intelligence)
========================================================================
CURRENT_STEP (when provided) means the patient is mid-booking. Fields:
awaiting, known_doctor, known_specialty, known_date.

1. COMPLETE THE CURRENT STEP FIRST.
   awaiting="date" and user says "بكرة" -> date_hint=TOMORROW ISO; do NOT treat as
   unclear/new request; use select_option if a matching date_* is in OPTIONS_JSON.
2. PRESERVE KNOWN CONTEXT.
   known_doctor set and user says "الساعة 2" -> still carry doctor_hint and add
   time_hint="14:00" for full booking context.
3. DETECT CONTEXT CHANGES.
   known_doctor="Ahmed" but user says "لا عايز دكتور علي" -> doctor_hint="علي",
   action="book_direct", high confidence (clear change of mind).
4. SHORT ANSWERS IN CONTEXT.
   awaiting="confirm" + "نعم"/"موافق" -> action="intent", intent="confirm", conf≈0.95.
   awaiting="slot" + "3"/"تلاتة" -> if it matches an option id, select_option; if no
   slots shown, extract time_hint.
5. MID-FLOW STEP AWARENESS (awaiting values):
   - "department" -> choosing specialty; "قلب"/"عظام" -> specialty_hint.
   - "doctor" -> choosing doctor; "أحمد"/"رانيا" -> doctor_hint.
   - "date" -> choosing day; "بكرة"/"الأحد" -> date_hint; prefer select_option if
     date_* options exist.
   - "slot" -> choosing time; "2"/"الصبح" -> time_hint or select_option; prefer
     select_option if slot_* options exist.
   - "patient_name" -> providing full name; do NOT treat names as doctor hints;
     action="intent", intent="book".
   - "mrn_value" -> numeric is a medical record number, not an option/phone.
   - "dob_value" -> a date is date-of-birth, NOT the appointment date.
   - "confirm"/"summary" -> "نعم"/"موافق"/"تمام" -> intent="confirm";
     "لا"/"غير" -> intent="update".
   - "change_type" -> edit flow: "الدكتور" -> change doctor; "اليوم"/"التاريخ" ->
     change date; "الميعاد"/"الوقت" -> change time. Set change_target accordingly.
   - "inquiry_book_cta"/"no_slots_alt"/"pick_appointment"/"mrn_optional"/
     "dob_gate"/"post_cancel" -> treat short yes/no answers as continuing that step.

========================================================================
EDIT / UPDATE FLOW HANDLING
========================================================================
Intent recognition: "عايز اعدل"/"اغير الموعد"/"تغيير الميعاد"/"تعديل الحجز" -> intent="update".

1) WHAT to change -> set change_target:
   "اغير الدكتور" -> change_target="doctor"
   "اغير الميعاد"/"اغير الوقت" -> change_target="time"
   "اغير اليوم"/"اغير التاريخ" -> change_target="date"
   (action="intent", intent="update")
2) NEW VALUE mentioned:
   "غير الموعد لبكرة" -> date_hint=TOMORROW ISO; "بعد بكرة" -> DAY_AFTER_TOMORROW ISO
   "اغير للساعة 3" -> time_hint="15:00"
   "اغير للدكتور أحمد" -> doctor_hint="أحمد"
   If both WHAT and NEW VALUE present, use book_direct/specialty_direct and extract hints.
3) CURRENT_STEP.awaiting="change_type": map "الدكتور"/"اليوم"/"الميعاد" or a number
   in OPTIONS_JSON. Use select_option if it matches OPTIONS_JSON, else intent + change_target.

========================================================================
CONFIDENCE (rough guidance; final clamping/adjustments happen in code)
========================================================================
HIGH (0.8-1.0): clear doctor person name; exact option match; unambiguous date;
  clear intent with context; known specialty with clear date/time.
MEDIUM (0.5-0.79): doctor name slightly unclear; date needs validation; intent clear
  but missing details; partial info.
LOW (0.0-0.49): unclear audio; ambiguous words; incomplete sentences; cannot
  determine intent even with context.

========================================================================
EXTRACTION PRIORITY
========================================================================
When OPTIONS_JSON is non-empty: first check for an option match (number/title);
if matched -> select_option; else extract hints and pick action from content.
When CURRENT_STEP.awaiting is set: first try to satisfy that step.
Doctor vs specialty: known person name -> doctor_hint; known specialty -> specialty_hint;
"دكتور قلب" -> specialty; "دكتور علي" -> doctor; if still unclear, confidence < 0.6.

========================================================================
LANGUAGE DETECTION (from the transcript)
========================================================================
Always set the 'language' field from the ACTUAL words/script of THIS transcript.
Do NOT default to Arabic just because most patients speak Arabic — judge only by
what was actually said.
- Transcript written mostly in Latin/English letters -> "en" (or "en-US"/"en-GB"
  if clearly regional). Example: "I want to book with Dr. Ahmed tomorrow" -> "en".
- Transcript mostly in Arabic script -> "ar-EG" for Egyptian colloquial, or "ar" for MSA.
- Roughly balanced Arabic + English -> "mixed".
- Empty/pure noise -> "unknown"; if the transcript is clear, NEVER leave it unknown,
  even when action="clarify".
Language detection is INDEPENDENT of the hints: keep doctor_hint/specialty_hint in
the same language they were spoken (do not translate an English name into Arabic).
If THIS turn is English, language MUST be "en" even when the previous turn was Arabic.
summary_ar is always written in Arabic regardless of 'language'.

========================================================================
KEY EXTRACTION CASES
========================================================================
- "دكتور قلب": if "قلب" is a known doctor person name -> doctor_hint; else specialty_hint.
- Ambiguous hour ("الساعة 2"): default PM (14:00) unless "الصبح" implies AM.
- Numeric while awaiting="patient_name"/"mrn_value": that step's value, NOT a doctor hint.
- "No" while confirming ("لا"/"غير"): intent="update".
- Multiple doctors ("أحمد أو علي"): take the FIRST -> doctor_hint="أحمد".
- Nickname/partial name ("محمد"): keep as doctor_hint; backend resolves the full name.
- Cancel mid-flow ("خلاص ماحتاجش"/"الغي الحجز"/"بطل"): intent="cancel" (or "menu").

Keep transcript in the language spoken. Never invent option ids."""

# Retry: 2 attempts, backoff 1s then 3s (Task 1)
_RETRY_BACKOFFS = (1.0, 3.0)


class VoiceProcessingError(Exception):
    """Raised when Meta download or OpenAI voice processing fails after retries."""


def _clarify_dict(
    media_id: str,
    *,
    transcript: str = "",
    summary_ar: str = "لم أفهم الطلب بوضوح",
    provider: str = "failed",
) -> dict:
    """Same shape as a successful route_whatsapp_voice_message clarify fallback."""
    understanding = VoiceUnderstanding(
        transcript=transcript,
        action="clarify",
        intent="unknown",
        confidence=0.0,
        summary_ar=summary_ar,
        language="unknown" if not transcript else "ar",
    )
    return {
        "text": understanding.transcript,
        "transcript": understanding.transcript,
        "action": understanding.action,
        "selected_option_id": understanding.selected_option_id,
        "intent": understanding.intent,
        "confidence": float(understanding.confidence),
        "doctor_hint": understanding.doctor_hint,
        "specialty_hint": understanding.specialty_hint,
        "date_hint": understanding.date_hint,
        "time_hint": understanding.time_hint,
        "change_target": understanding.change_target,
        "summary_ar": understanding.summary_ar,
        "language": understanding.language,
        "stt_provider": provider,
        "media_id": media_id,
        "cost": None,
        "understanding": understanding,
        "plan": None,
    }


def _is_non_retryable_http(exc: BaseException) -> bool:
    """Do not retry 4xx auth/client errors (except 429 rate limit)."""
    status: int | None = None
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = exc.response.status_code
    elif isinstance(exc, openai.APIStatusError):
        status = getattr(exc, "status_code", None)
    if status is None:
        return False
    if status == 429:
        return False
    return 400 <= status < 500


def _with_retries(label: str, fn: Callable[[], T]) -> T:
    """Run fn up to 2 times with 1s / 3s backoff on transient errors."""
    last_exc: BaseException | None = None
    attempts = 1 + len(_RETRY_BACKOFFS)
    for attempt in range(attempts):
        try:
            return fn()
        except VoiceProcessingError:
            raise
        except (
            requests.RequestException,
            openai.APITimeoutError,
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.APIError,
        ) as exc:
            last_exc = exc
            if _is_non_retryable_http(exc):
                logger.error("[voice] %s non-retryable error: %s", label, exc)
                raise VoiceProcessingError(f"{label} failed: {exc}") from exc
            if attempt >= len(_RETRY_BACKOFFS):
                break
            delay = _RETRY_BACKOFFS[attempt]
            logger.warning(
                "[voice] %s attempt %s/%s failed (%s); retry in %.0fs",
                label,
                attempt + 1,
                attempts,
                type(exc).__name__,
                delay,
            )
            time.sleep(delay)
        except Exception as exc:
            last_exc = exc
            logger.error("[voice] %s unexpected error: %s", label, exc)
            raise VoiceProcessingError(f"{label} failed: {exc}") from exc

    logger.error("[voice] %s failed after retries: %s", label, last_exc)
    raise VoiceProcessingError(f"{label} failed after retries: {last_exc}") from last_exc


def _client() -> OpenAI:
    # Re-read env in case module was imported before dotenv loaded
    key = (OPENAI_API_KEY or os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise VoiceProcessingError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=key)


def _download_whatsapp_audio(media_id: str) -> bytes:
    if not WHATSAPP_TOKEN:
        raise VoiceProcessingError("WHATSAPP_TOKEN is not configured")

    def _do() -> bytes:
        # Let RequestException propagate so _with_retries can back off;
        # non-transient VoiceProcessingError (e.g. missing URL) is not retried.
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        meta = requests.get(
            f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{media_id}",
            headers=headers,
            timeout=15,
        )
        meta.raise_for_status()
        download_url = (meta.json() or {}).get("url")
        if not download_url:
            raise VoiceProcessingError("Meta did not return an audio download URL")
        audio = requests.get(download_url, headers=headers, timeout=30)
        audio.raise_for_status()
        return audio.content

    return _with_retries("meta_audio_download", _do)


def _options_catalog(options: list[Option] | None) -> list[dict[str, Any]]:
    catalog = []
    for i, o in enumerate(options or []):
        catalog.append(
            {
                "id": str(o.get("id") or ""),
                "title": o.get("title") or "",
                "description": o.get("description") or "",
                "number": i + 1,
            }
        )
    return catalog


def _sanitize(understanding: VoiceUnderstanding, options: list[Option] | None) -> VoiceUnderstanding:
    allowed = {str(o.get("id")) for o in (options or []) if o.get("id") is not None}
    selected = understanding.selected_option_id
    if selected and allowed and str(selected) not in allowed:
        title_map = {
            str(o.get("title") or "").strip(): str(o.get("id"))
            for o in (options or [])
            if o.get("id") is not None
        }
        mapped = title_map.get(str(selected).strip())
        if mapped and mapped in allowed:
            understanding = understanding.model_copy(update={"selected_option_id": mapped})
        else:
            understanding = understanding.model_copy(
                update={
                    "selected_option_id": None,
                    "action": (
                        "clarify"
                        if understanding.action == "select_option"
                        else understanding.action
                    ),
                    "confidence": min(understanding.confidence, 0.45),
                }
            )
    if understanding.action == "select_option" and not understanding.selected_option_id:
        understanding = understanding.model_copy(
            update={"action": "clarify", "confidence": min(understanding.confidence, 0.45)}
        )
    # Promote to book_direct when doctor PERSON is present on a book intent
    if (
        understanding.action in {"intent", "clarify"}
        and understanding.intent == "book"
        and understanding.doctor_hint
        and understanding.confidence >= 0.7
    ):
        understanding = understanding.model_copy(update={"action": "book_direct"})
    # "دكتور قلب" often wrongly fills doctor_hint — treat as specialty
    if understanding.doctor_hint and not understanding.specialty_hint:
        dh = str(understanding.doctor_hint).strip()
        stripped = re.sub(
            r"^(د\.|دكتور|الدكتور|dr\.?)\s*",
            "",
            dh,
            flags=re.I,
        ).strip()
        if is_specialty_word(stripped) or is_specialty_word(dh):
            understanding = understanding.model_copy(
                update={
                    "specialty_hint": stripped,
                    "doctor_hint": None,
                    "action": "specialty_direct",
                    "intent": understanding.intent
                    if understanding.intent not in {"unknown", ""}
                    else "book",
                }
            )
    # Promote specialty_direct when specialty mentioned without doctor
    if (
        understanding.action in {"intent", "clarify", "book_direct", "select_option"}
        and understanding.specialty_hint
        and not understanding.doctor_hint
        and understanding.confidence >= 0.5
    ):
        understanding = understanding.model_copy(update={"action": "specialty_direct"})
    return understanding


def _build_stt_context_prompt(
    db: Session | None,
    clinic_id: int | None = None,
    *,
    now: float | None = None,
) -> str:
    """Optional Whisper vocabulary bias — OFF by default for maximum quality.

    Dumping doctor/specialty lists into ``prompt`` biased Whisper toward
    invented names and dual-script lines. The early working path used no
    prompt. Set VOICE_STT_PROMPT=true only if you need name biasing again.
    """
    from app.core.config import VOICE_STT_PROMPT

    if not VOICE_STT_PROMPT or db is None:
        return ""
    cid = int(clinic_id if clinic_id is not None else DEFAULT_CLINIC_ID)
    ts = time.time() if now is None else now
    cached = _STT_PROMPT_CACHE.get(cid)
    if cached and cached[0] > ts:
        return cached[1]

    from app.services import doctor_service

    parts: list[str] = [
        "مستشفى جامعة الجيزة الجديدة.",
        "قلب، عيون، أسنان، أعصاب، أطفال، عظام، جلدية، باطنة، نساء.",
    ]
    try:
        doctors = doctor_service.list_active_doctors(db, cid, limit=40)
        name_bits: list[str] = []
        for doc in doctors:
            ar = (doc.name_ar or "").strip()
            en = (doc.name_en or "").strip()
            if ar:
                name_bits.append(ar)
            elif en:
                name_bits.append(en)
        if name_bits:
            parts.append("، ".join(dict.fromkeys(name_bits)))
        for word in sorted(specialty_alias_words(), key=len):
            if word.isascii() or len(word) > 24:
                continue
            parts.append(word)
    except Exception:
        logger.exception("[voice] failed building STT context prompt clinic_id=%s", cid)
        return ""

    prompt = " ".join(dict.fromkeys(parts))
    if len(prompt) > _STT_PROMPT_MAX_CHARS:
        prompt = prompt[: _STT_PROMPT_MAX_CHARS].rsplit("،", 1)[0].strip()
    _STT_PROMPT_CACHE[cid] = (ts + _STT_PROMPT_TTL_SEC, prompt)
    return prompt


def clear_stt_prompt_cache() -> None:
    """Test helper — drop in-process Whisper prompt cache."""
    _STT_PROMPT_CACHE.clear()


def _format_current_step_line(current_step: dict[str, Any] | None) -> str:
    """One-line CURRENT_STEP context for the GPT routing user message."""
    if not current_step:
        return ""
    # Lazy import avoids circular load with voice_fastpath.
    from app.services.voice_fastpath import (
        VOICE_FREE_TEXT_AWAITING,
        VOICE_OPTION_AWAITING,
    )

    awaiting = str(current_step.get("awaiting") or "").strip()
    doctor = str(current_step.get("known_doctor") or "").strip()
    day = str(current_step.get("known_date") or "").strip()
    specialty = str(current_step.get("known_specialty") or "").strip()

    relevant = awaiting in VOICE_OPTION_AWAITING or awaiting in VOICE_FREE_TEXT_AWAITING
    if not relevant and not (doctor or day or specialty):
        return ""

    if awaiting == "slot":
        bits = ["patient already chose"]
        if doctor:
            bits.append(f"Dr. {doctor}")
        if day:
            bits.append(f"on {day}")
        bits.append("and is now expected to say a time for their appointment")
        detail = " ".join(bits)
    elif awaiting == "date":
        if doctor:
            detail = (
                f"patient already chose Dr. {doctor} and is now expected to say a day "
                "for their appointment"
            )
        else:
            detail = "patient is choosing an appointment day"
    elif awaiting == "doctor":
        if specialty:
            detail = (
                f"patient already chose specialty {specialty} and is now expected "
                "to say or pick a doctor name"
            )
        else:
            detail = "patient is choosing a doctor"
    elif awaiting == "department":
        detail = "patient is choosing a specialty/department"
    elif awaiting in {"patient_name"}:
        detail = "patient is expected to say their full name"
    elif awaiting in {"mrn_value"}:
        detail = "patient is expected to provide their medical record number"
    elif awaiting in {"dob_value"}:
        detail = "patient is expected to provide their date of birth"
    elif awaiting in {"confirm", "summary", "mrn_optional", "dob_gate"}:
        detail = "patient is confirming or answering a yes/no booking step"
    elif awaiting in {"inquiry_book_cta", "no_slots_alt", "pick_appointment", "change_type", "post_cancel"}:
        detail = f"patient is mid-flow (awaiting={awaiting}) and should answer that step"
    elif doctor or day or specialty:
        bits = ["patient is mid-booking"]
        if doctor:
            bits.append(f"with Dr. {doctor}")
        if specialty:
            bits.append(f"specialty {specialty}")
        if day:
            bits.append(f"date {day}")
        detail = " ".join(bits)
    else:
        return ""

    return (
        f"CURRENT_STEP: {detail}. If the transcript only contains a day/time/name/"
        "yes-no answer, treat it as continuing this booking, not a new request.\n"
    )


def _transcribe_ogg(
    ogg_bytes: bytes,
    *,
    db: Session | None = None,
    clinic_id: int | None = None,
    force_language: str | None = None,
) -> str:
    """Bare Whisper transcription — no language pin, prompt optional/off.

    Early production quality used plain whisper-1. Forcing ``language`` and
    heavy ``prompt`` vocab caused the recent hallucinations. ``force_language``
    is ignored for quality.
    """
    del force_language  # intentionally unused

    def _do() -> str:
        client = _client()
        stt_prompt = _build_stt_context_prompt(db, clinic_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(ogg_bytes)
            tmp_path = tmp.name
        try:
            with open(tmp_path, "rb") as audio_file:
                kwargs: dict[str, Any] = {
                    "model": OPENAI_STT_MODEL,
                    "file": audio_file,
                }
                if stt_prompt:
                    kwargs["prompt"] = stt_prompt
                transcript = client.audio.transcriptions.create(**kwargs)
            return (transcript.text or "").strip()
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return _with_retries("openai_stt", _do)


def _understand_via_gpt_text(
    transcript: str,
    options: list[Option] | None,
    current_step: dict[str, Any] | None = None,
) -> tuple[VoiceUnderstanding, dict[str, int]]:
    """Return (understanding, token_usage) so callers can price the call."""

    def _do() -> tuple[VoiceUnderstanding, dict[str, int]]:
        client = _client()
        parse_fn = (
            getattr(client.chat.completions, "parse", None)
            or client.beta.chat.completions.parse
        )
        catalog = _options_catalog(options)
        # Calendar context in the *user* message only (system prompt unchanged).
        # Without TODAY/TOMORROW, GPT invents stale years or wrong +1/+2 days.
        step_line = _format_current_step_line(current_step)
        completion = parse_fn(
            model=OPENAI_VOICE_STRUCTURE_MODEL or OPENAI_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": (
                        _calendar_context_block()
                        + step_line
                        + f"OPTIONS_JSON={json.dumps(catalog, ensure_ascii=False)}\n"
                        f"TRANSCRIPT: {transcript}\n"
                        "Return structured VoiceUnderstanding."
                    ),
                },
            ],
            response_format=VoiceUnderstanding,
        )
        usage = voice_cost.usage_from_completion(completion)
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            return (
                VoiceUnderstanding(
                    transcript=transcript,
                    action="clarify",
                    intent="unknown",
                    confidence=0.3,
                    summary_ar="لم أفهم الطلب بوضوح",
                    language="ar",
                ),
                usage,
            )
        understanding = _sanitize(
            parsed.model_copy(update={"transcript": transcript or parsed.transcript}),
            options,
        )
        return understanding, usage

    return _with_retries("openai_voice_parse", _do)


def _plan_via_gpt_text(
    transcript: str,
    options: list[Option] | None,
    current_step: dict[str, Any] | None = None,
) -> tuple[VoicePlan, dict[str, int]]:
    """Router V2: ask the model for a flow plan instead of a classification.

    Returns (plan, token_usage). The plan is deliberately NOT sanitized here —
    validating it against real availability is voice_executor's job, and
    rewriting it in advance is exactly the second-guessing V2 removes.
    """

    def _do() -> tuple[VoicePlan, dict[str, int]]:
        client = _client()
        parse_fn = (
            getattr(client.chat.completions, "parse", None)
            or client.beta.chat.completions.parse
        )
        catalog = _options_catalog(options)
        completion = parse_fn(
            model=OPENAI_VOICE_STRUCTURE_MODEL or OPENAI_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        _calendar_context_block()
                        + f"CURRENT_STEP={json.dumps(current_step or {}, ensure_ascii=False)}\n"
                        + f"OPTIONS_JSON={json.dumps(catalog, ensure_ascii=False)}\n"
                        + f"TRANSCRIPT: {transcript}\n"
                        + "Return the structured VoicePlan."
                    ),
                },
            ],
            response_format=VoicePlan,
        )
        usage = voice_cost.usage_from_completion(completion)
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            return (
                VoicePlan(
                    transcript=transcript,
                    goal="unclear",
                    next_step="clarify",
                    summary_ar="لم أفهم الطلب بوضوح",
                    summary_en="Could not understand the request.",
                    language="ar",
                ),
                usage,
            )
        return parsed.model_copy(update={"transcript": transcript or parsed.transcript}), usage

    plan, usage = _with_retries("openai_voice_plan", _do)
    return _align_language_to_transcript(plan, transcript), usage


def _align_language_to_transcript(plan: VoicePlan, transcript: str) -> VoicePlan:
    """Force plan.language from transcript script each turn.

    - English transcript + Arabic specialty/CURRENT_STEP → model wrongly said ar-EG
    - Arabic transcript after an English session → must flip back to ar (not stick on en)
    """
    from app.language.language_detector import detect_language
    from app.services.voice_schemas import fold_language

    detected = detect_language(transcript, fallback=None)
    if detected not in {"ar", "en"}:
        return plan
    current = fold_language(plan.language)
    if current == detected:
        return plan
    wanted = "en" if detected == "en" else "ar-EG"
    logger.info(
        "[voice] language override %s → %s (transcript script)",
        plan.language,
        wanted,
    )
    return plan.model_copy(update={"language": wanted})


def route_whatsapp_voice_message(
    media_id: str,
    options: list[Option] | None = None,
    current_step: dict[str, Any] | None = None,
    db: Session | None = None,
    clinic_id: int | None = None,
    force_stt_language: str | None = None,
) -> dict:
    """
    Whisper (or gpt-4o-*-transcribe) → LLM Pydantic routing decision.

    Never uses Groq. On final external-call failure, returns clarify fallback
    (same shape as empty transcript) so webhook can degrade gracefully.

    force_stt_language: optional "ar"/"en" to pin Whisper while voice language
    is sticky mid-booking (prevents cross-language translation).
    """
    provider = f"openai_stt:{OPENAI_STT_MODEL}+gpt_parse"
    cid = clinic_id if clinic_id is not None else DEFAULT_CLINIC_ID
    chat_model = OPENAI_VOICE_STRUCTURE_MODEL or OPENAI_MODEL
    audio_seconds: float | None = None
    usage: dict[str, int] = {"prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0}
    plan: VoicePlan | None = None
    stt_latency_ms: int | None = None
    chat_latency_ms: int | None = None
    try:
        ogg_bytes = _download_whatsapp_audio(media_id)
        audio_seconds = voice_cost.estimate_audio_seconds(ogg_bytes)
        t0 = time.perf_counter()
        transcript = _transcribe_ogg(
            ogg_bytes,
            db=db,
            clinic_id=cid,
            force_language=force_stt_language,
        )
        stt_latency_ms = int(round((time.perf_counter() - t0) * 1000))
        # Drop Whisper outros / fake greetings before the planner sees them.
        from app.language.language_detector import (
            is_whisper_garbage,
            scrub_whisper_hallucinations,
        )

        raw_transcript = transcript
        if transcript and is_whisper_garbage(transcript):
            logger.info(
                "[voice] whisper hallucination scrubbed → clarify raw=%r",
                raw_transcript,
            )
            transcript = ""
        elif transcript:
            scrubbed = scrub_whisper_hallucinations(transcript)
            if scrubbed != transcript:
                logger.info(
                    "[voice] whisper hallucination trimmed %r → %r",
                    transcript,
                    scrubbed,
                )
                transcript = scrubbed

        if not transcript:
            understanding = VoiceUnderstanding(
                transcript="",
                action="clarify",
                intent="unknown",
                confidence=0.0,
                summary_ar="لم يصل صوت واضح",
                language="unknown",
            )
        elif VOICE_ROUTER_V2:
            t1 = time.perf_counter()
            plan, usage = _plan_via_gpt_text(
                transcript, options, current_step=current_step
            )
            chat_latency_ms = int(round((time.perf_counter() - t1) * 1000))
            # Project onto V1 so the legacy fastpath stays available as a
            # fallback when the executor declines a step.
            understanding = _sanitize(plan.to_understanding(), options)
        else:
            t1 = time.perf_counter()
            understanding, usage = _understand_via_gpt_text(
                transcript, options, current_step=current_step
            )
            chat_latency_ms = int(round((time.perf_counter() - t1) * 1000))
    except VoiceProcessingError:
        logger.exception("[voice] processing failed media_id=%s", media_id)
        result = _clarify_dict(
            media_id,
            summary_ar="لم أفهم الرسالة الصوتية بوضوح",
            provider="failed",
        )
        # Still bill STT if the audio downloaded/transcribed before the failure.
        result["cost"] = voice_cost.estimate_voice_call_cost(
            stt_model=OPENAI_STT_MODEL,
            audio_seconds=audio_seconds,
            chat_model=chat_model,
            stt_latency_ms=stt_latency_ms,
            chat_latency_ms=chat_latency_ms,
            **usage,
        )
        logger.info("[voice][cost] %s", voice_cost.format_cost_log(result["cost"]))
        return result

    cost = voice_cost.estimate_voice_call_cost(
        stt_model=OPENAI_STT_MODEL,
        audio_seconds=audio_seconds,
        chat_model=chat_model,
        stt_latency_ms=stt_latency_ms,
        chat_latency_ms=chat_latency_ms,
        **usage,
    )

    logger.info(
        "[voice] whisper+llm ok provider=%s action=%s option=%r intent=%s "
        "doctor=%r specialty=%r date=%r time=%r change=%r conf=%.2f step=%r text=%r",
        provider,
        understanding.action,
        understanding.selected_option_id,
        understanding.intent,
        understanding.doctor_hint,
        understanding.specialty_hint,
        understanding.date_hint,
        understanding.time_hint,
        understanding.change_target,
        understanding.confidence,
        (current_step or {}).get("awaiting"),
        understanding.transcript,
    )
    if plan is not None:
        logger.info(
            "[voice][v2] plan goal=%s next_step=%s doctor=%r alts=%r specialty=%r "
            "date=%r(%s) time=%r patient=%r ref=%r change=%r option=%r "
            "conf=%.2f(doc=%s date=%s time=%s) followup=%s lang=%s",
            plan.goal,
            plan.next_step,
            plan.slots.doctor_name,
            plan.slots.doctor_alternatives,
            plan.slots.specialty,
            plan.slots.date,
            plan.slots.date_flexibility,
            plan.slots.time,
            plan.slots.patient_name,
            plan.slots.appointment_ref,
            plan.slots.change_target,
            plan.slots.selected_option_id,
            plan.confidence.overall,
            plan.confidence.doctor,
            plan.confidence.date,
            plan.confidence.time,
            plan.followup_goal,
            plan.language,
        )
    logger.info("[voice][cost] %s", voice_cost.format_cost_log(cost))

    return {
        "text": understanding.transcript,
        "transcript": understanding.transcript,
        "action": understanding.action,
        "selected_option_id": understanding.selected_option_id,
        "intent": understanding.intent,
        "confidence": float(understanding.confidence),
        "doctor_hint": understanding.doctor_hint,
        "specialty_hint": understanding.specialty_hint,
        "date_hint": understanding.date_hint,
        "time_hint": understanding.time_hint,
        "change_target": understanding.change_target,
        "summary_ar": understanding.summary_ar,
        "language": understanding.language,
        "stt_provider": provider,
        "media_id": media_id,
        "cost": cost,
        "understanding": understanding,
        "plan": plan,
    }


def understand_whatsapp_audio(
    media_id: str,
    options: list[Option] | None = None,
    current_step: dict[str, Any] | None = None,
    db: Session | None = None,
    clinic_id: int | None = None,
) -> dict:
    """Deprecated alias for route_whatsapp_voice_message."""
    return route_whatsapp_voice_message(
        media_id,
        options=options,
        current_step=current_step,
        db=db,
        clinic_id=clinic_id,
    )


def transcribe_whatsapp_audio(media_id: str) -> dict:
    """Deprecated alias — name implied STT-only; returns full routing decision."""
    return route_whatsapp_voice_message(media_id)
