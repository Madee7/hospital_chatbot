"""WhatsApp voice → Whisper STT → LLM structured action (OpenAI only)."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from typing import Any, Callable, TypeVar

import openai
import requests
from openai import OpenAI

from app.core.config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_STT_MODEL,
    OPENAI_VOICE_STRUCTURE_MODEL,
    WHATSAPP_API_VERSION,
    WHATSAPP_TOKEN,
)
from app.services.voice_schemas import VoiceUnderstanding
# TODO: prefer DB-driven matching via doctor_service.infer_department_from_text(clinic_id)
# once a Session/clinic_id is threaded into _sanitize (option b). For now aliases stay
# in doctor_service._SPECIALTY_ALIASES as the single source of truth.
from app.services.doctor_service import is_specialty_word

logger = logging.getLogger(__name__)

Option = dict[str, Any]
T = TypeVar("T")

_SYSTEM = (
    "You are the router for a hospital WhatsApp chatbot "
    "(New Giza University Hospital). Patients speak Egyptian Arabic. "
    "Given a Whisper transcript AND optional current WhatsApp options (may be mid-booking), "
    "choose ONE action:\n"
    "- select_option: patient clearly picks a listed option OR says a number/title matching one "
    "→ set selected_option_id to that exact id (preferred when OPTIONS_JSON is non-empty)\n"
    "- book_direct: wants to book AND mentions a PERSON's doctor name (رانيا، أحمد سمير…) "
    "→ doctor_hint = person name only; fill date_hint as YYYY-MM-DD when possible "
    "(resolve بكرة/غداً/النهاردة/weekday to a real date if you can) and time_hint if spoken\n"
    "- specialty_direct: specialty/department WITHOUT a person name "
    "('دكتور قلب', 'عايز قلب', 'حجز عظام') → specialty_hint only; never put تخصص in doctor_hint\n"
    "- intent: book/update/cancel/ask_doctors/handover/menu/confirm when starting or escaping; "
    "confirm=تأكيد/نعم while confirming a booking\n"
    "- clarify: unclear\n"
    "If OPTIONS_JSON has date_* or slot_* rows, prefer select_option.\n"
    "Always extract doctor_hint, specialty_hint, date_hint, time_hint when mentioned. "
    "confidence MUST be a number 0-1. Never invent option ids. Keep transcript Arabic."
)

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
        "summary_ar": understanding.summary_ar,
        "language": understanding.language,
        "stt_provider": provider,
        "media_id": media_id,
        "understanding": understanding,
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


def _transcribe_ogg(ogg_bytes: bytes) -> str:
    def _do() -> str:
        client = _client()
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(ogg_bytes)
            tmp_path = tmp.name
        try:
            with open(tmp_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model=OPENAI_STT_MODEL,
                    file=audio_file,
                    language="ar",
                )
            return (transcript.text or "").strip()
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return _with_retries("openai_stt", _do)


def _understand_via_gpt_text(
    transcript: str, options: list[Option] | None
) -> VoiceUnderstanding:
    def _do() -> VoiceUnderstanding:
        client = _client()
        parse_fn = (
            getattr(client.chat.completions, "parse", None)
            or client.beta.chat.completions.parse
        )
        catalog = _options_catalog(options)
        # Calendar context in the *user* message only (system prompt unchanged).
        # Without TODAY, GPT invents stale years (prod: date_hint='2023-10-31').
        from datetime import date as _date

        today = _date.today()
        today_line = (
            f"TODAY={today.isoformat()} (weekday={today.strftime('%A')}). "
            "Resolve weekdays/relative days relative to TODAY into YYYY-MM-DD.\n"
        )
        completion = parse_fn(
            model=OPENAI_VOICE_STRUCTURE_MODEL or OPENAI_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": (
                        today_line
                        + f"OPTIONS_JSON={json.dumps(catalog, ensure_ascii=False)}\n"
                        f"TRANSCRIPT: {transcript}\n"
                        "Return structured VoiceUnderstanding."
                    ),
                },
            ],
            response_format=VoiceUnderstanding,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            return VoiceUnderstanding(
                transcript=transcript,
                action="clarify",
                intent="unknown",
                confidence=0.3,
                summary_ar="لم أفهم الطلب بوضوح",
                language="ar",
            )
        return _sanitize(
            parsed.model_copy(update={"transcript": transcript or parsed.transcript}),
            options,
        )

    return _with_retries("openai_voice_parse", _do)


def route_whatsapp_voice_message(
    media_id: str,
    options: list[Option] | None = None,
) -> dict:
    """
    Whisper (or gpt-4o-*-transcribe) → LLM Pydantic routing decision.

    Never uses Groq. On final external-call failure, returns clarify fallback
    (same shape as empty transcript) so webhook can degrade gracefully.
    """
    provider = f"openai_stt:{OPENAI_STT_MODEL}+gpt_parse"
    try:
        ogg_bytes = _download_whatsapp_audio(media_id)
        transcript = _transcribe_ogg(ogg_bytes)
        if not transcript:
            understanding = VoiceUnderstanding(
                transcript="",
                action="clarify",
                intent="unknown",
                confidence=0.0,
                summary_ar="لم يصل صوت واضح",
                language="unknown",
            )
        else:
            understanding = _understand_via_gpt_text(transcript, options)
    except VoiceProcessingError:
        logger.exception("[voice] processing failed media_id=%s", media_id)
        return _clarify_dict(
            media_id,
            summary_ar="لم أفهم الرسالة الصوتية بوضوح",
            provider="failed",
        )

    logger.info(
        "[voice] whisper+llm ok provider=%s action=%s option=%r intent=%s "
        "doctor=%r specialty=%r date=%r time=%r conf=%.2f text=%r",
        provider,
        understanding.action,
        understanding.selected_option_id,
        understanding.intent,
        understanding.doctor_hint,
        understanding.specialty_hint,
        understanding.date_hint,
        understanding.time_hint,
        understanding.confidence,
        understanding.transcript,
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
        "summary_ar": understanding.summary_ar,
        "language": understanding.language,
        "stt_provider": provider,
        "media_id": media_id,
        "understanding": understanding,
    }


def understand_whatsapp_audio(
    media_id: str,
    options: list[Option] | None = None,
) -> dict:
    """Deprecated alias for route_whatsapp_voice_message."""
    return route_whatsapp_voice_message(media_id, options=options)


def transcribe_whatsapp_audio(media_id: str) -> dict:
    """Deprecated alias — name implied STT-only; returns full routing decision."""
    return route_whatsapp_voice_message(media_id)
