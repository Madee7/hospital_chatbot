"""App settings loaded from environment / `.env`.

Windows notes
-------------
- Save `.env` as **UTF-8 without BOM**. Notepad "UTF-8" often adds a BOM that
  corrupts the first variable *name* (e.g. VERIFY_TOKEN becomes invisible).
- Prefer leaving Arabic display fields blank in `.env` so the UTF-8 defaults
  below are used (safe even if the server editor mangles Arabic).
- This loader accepts BOM (`utf-8-sig`), strips junk around keys/values, and
  treats empty values as "use default".
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Arabic / display defaults live in this UTF-8 source file (not required in .env)
# ---------------------------------------------------------------------------
_DEFAULT_CLINIC_AR = "دار الشفاء"
_DEFAULT_CLINIC_EN = "Dar Al Shfaa"
_DEFAULT_FLOW_CTA = "عرض الأطباء"


def _load_dotenv_files() -> None:
    """Load `.env` from repo root and cwd (utf-8-sig strips Windows BOM)."""
    candidates = (
        Path(__file__).resolve().parents[2] / ".env",  # repo root
        Path.cwd() / ".env",
    )
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        load_dotenv(path, encoding="utf-8-sig", override=True)


_load_dotenv_files()


def _env(key: str, default: str | None = None) -> str | None:
    """Read env var; tolerate BOM-prefixed keys and quoted/blank values."""
    raw = os.getenv(key)
    if raw is None:
        # First line of a BOM-saved .env can land as \ufeffKEY in os.environ.
        raw = os.getenv("\ufeff" + key)
    if raw is None:
        return default
    cleaned = raw.strip().strip('"').strip("'").strip()
    # Empty / whitespace-only → fall back (so broken Arabic in .env can be cleared)
    if cleaned == "":
        return default
    return cleaned


def _env_bool(key: str, default: str = "false") -> bool:
    return (_env(key, default) or default).lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: str) -> int:
    return int(_env(key, default) or default)


def _env_float(key: str, default: str) -> float:
    return float(_env(key, default) or default)


# WhatsApp
VERIFY_TOKEN = _env("VERIFY_TOKEN")
WHATSAPP_TOKEN = _env("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = _env("PHONE_NUMBER_ID")
WHATSAPP_API_VERSION = _env("WHATSAPP_API_VERSION", "v19.0") or "v19.0"

# WhatsApp Flows doctor picker (ImageCarousel swipe + radio select)
# Set USE_DOCTOR_FLOW=true and WHATSAPP_FLOW_ID after publishing the Flow in Meta.
USE_DOCTOR_FLOW = _env_bool("USE_DOCTOR_FLOW", "false")
WHATSAPP_FLOW_ID = (_env("WHATSAPP_FLOW_ID", "") or "").strip()
WHATSAPP_FLOW_CTA = _env("WHATSAPP_FLOW_CTA", _DEFAULT_FLOW_CTA) or _DEFAULT_FLOW_CTA
# Use true while testing an unpublished (Draft) Flow in Meta.
WHATSAPP_FLOW_DRAFT = _env_bool("WHATSAPP_FLOW_DRAFT", "false")

# AI providers (OpenAI for voice — Whisper STT + GPT structure)
GROQ_API_KEY = _env("GROQ_API_KEY")
OPENAI_API_KEY = _env("OPENAI_API_KEY")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini"
# whisper-1 is the production default (gpt-4o-transcribe was worse on Egyptian dialect here).
OPENAI_STT_MODEL = _env("OPENAI_STT_MODEL", "whisper-1") or "whisper-1"
# Whisper `prompt` vocab bias — OFF by default. Turning it on can help rare
# doctor-name misses but caused hallucinations in live Egyptian notes.
VOICE_STT_PROMPT = _env_bool("VOICE_STT_PROMPT", "false")
OPENAI_VOICE_STRUCTURE_MODEL = (
    _env("OPENAI_VOICE_STRUCTURE_MODEL")
    or _env("OPENAI_MODEL", "gpt-4o-mini")
    or "gpt-4o-mini"
)
VOICE_REQUIRE_CONFIRM = _env_bool("VOICE_REQUIRE_CONFIRM", "false")
VOICE_SKIP_CONFIRM_THRESHOLD = _env_float("VOICE_SKIP_CONFIRM_THRESHOLD", "0.55")

# Voice router V2: LLM returns a flow plan (goal + next_step + slots);
# voice_executor validates availability. On by default — set false to use V1.
VOICE_ROUTER_V2 = _env_bool("VOICE_ROUTER_V2", "true")
# How long a voice-detected chat language stays locked (inactivity window).
# After this many minutes without voice, the next clear voice note may re-detect.
VOICE_LANG_SESSION_MINUTES = _env_int("VOICE_LANG_SESSION_MINUTES", "30")

# Database
DATABASE_URL = _env(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/hospital_chatbot",
) or "postgresql+psycopg://postgres:postgres@localhost:5432/hospital_chatbot"

# Default clinic context for MVP single-clinic demo
DEFAULT_TENANT_ID = _env_int("DEFAULT_TENANT_ID", "1")
DEFAULT_CLINIC_ID = _env_int("DEFAULT_CLINIC_ID", "1")
# Leave these blank in `.env` on Windows if Arabic gets corrupted — defaults apply.
CLINIC_DISPLAY_NAME = _env("CLINIC_DISPLAY_NAME", _DEFAULT_CLINIC_AR) or _DEFAULT_CLINIC_AR
CLINIC_LOCATION = _env("CLINIC_LOCATION", _DEFAULT_CLINIC_EN) or _DEFAULT_CLINIC_EN
CLINIC_LOCATION_AR = _env("CLINIC_LOCATION_AR", _DEFAULT_CLINIC_AR) or _DEFAULT_CLINIC_AR
CLINIC_MAPS_URL = (_env("CLINIC_MAPS_URL", "") or "").strip()

# Ops / escalation
RECEPTIONIST_WHATSAPP = (_env("RECEPTIONIST_WHATSAPP", "") or "").strip()
CANCEL_CUTOFF_HOURS = _env_int("CANCEL_CUTOFF_HOURS", "2")
RESCHEDULE_CUTOFF_HOURS = _env_int("RESCHEDULE_CUTOFF_HOURS", "2")

# Booking policy
SLOT_HOLD_MINUTES = _env_int("SLOT_HOLD_MINUTES", "3")
BOOKING_WINDOW_DAYS = _env_int("BOOKING_WINDOW_DAYS", "14")
MIN_LEAD_HOURS = _env_int("MIN_LEAD_HOURS", "2")
DUPLICATE_APPOINTMENT_DAYS = _env_int("DUPLICATE_APPOINTMENT_DAYS", "7")
ALLOW_OVERBOOKING = _env_bool("ALLOW_OVERBOOKING", "false")
REQUIRE_DOB = _env_bool("REQUIRE_DOB", "false")
REMINDER_HOURS_BEFORE = [
    int(x.strip())
    for x in (_env("REMINDER_HOURS_BEFORE", "24,2") or "24,2").split(",")
    if x.strip()
]
