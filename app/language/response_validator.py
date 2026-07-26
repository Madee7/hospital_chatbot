"""Validate that outbound LLM text matches the conversation language."""

from __future__ import annotations

import re
import time
from typing import Any, Literal

from openai import OpenAI
from sqlalchemy.orm import Session

from app.core import i18n_bot as i18n
from app.core.config import OPENAI_API_KEY, OPENAI_MODEL
from app.language.multilingual_prompt import build_system_prompt
from app.services.conversation_service import log_openai_chat_usage

LangCode = Literal["ar", "en"]

_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{3,}")

# Tokens allowed inside Arabic replies (IDs, brands, common abbreviations).
_ALLOWED_LATIN_IN_AR = {
    "menu",
    "whatsapp",
    "id",
    "ref",
    "ok",
    "am",
    "pm",
    "http",
    "https",
    "www",
}


def _latin_words(text: str) -> list[str]:
    return [w.lower() for w in _LATIN_WORD_RE.findall(text or "")]


def validate_response_language(text: str | None, lang: Any) -> bool:
    """Return True if ``text`` is acceptably monolingual for ``lang``."""
    raw = (text or "").strip()
    if not raw:
        return True

    code: LangCode = i18n.normalize_lang(lang)  # type: ignore[assignment]
    ar_chars = len(_ARABIC_RE.findall(raw))
    latin = _latin_words(raw)

    if code == "ar":
        # Arabic expected: reject if meaningful English words slip in.
        unexpected = [w for w in latin if w not in _ALLOWED_LATIN_IN_AR]
        if unexpected and ar_chars > 0:
            # Allow tiny Latin (e.g. appointment ref letters) if Arabic dominates.
            if len(unexpected) <= 1 and ar_chars >= 20:
                return True
            return False
        if unexpected and ar_chars == 0:
            return False
        return True

    # English expected: reject Arabic script.
    if ar_chars > 0:
        return False
    return True


def _rewrite_in_language(
    text: str,
    lang: LangCode,
    *,
    db: Session | None = None,
    tenant_id: int | None = None,
    clinic_id: int | None = None,
) -> str | None:
    if not OPENAI_API_KEY or not text.strip():
        return None
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        t0 = time.perf_counter()
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": build_system_prompt(lang, purpose="rewrite"),
                },
                {"role": "user", "content": text},
            ],
        )
        latency_ms = int(round((time.perf_counter() - t0) * 1000))
        log_openai_chat_usage(
            db,
            tenant_id=tenant_id,
            clinic_id=clinic_id,
            model=OPENAI_MODEL,
            operation="text_rewrite",
            completion=completion,
            latency_ms=latency_ms,
            status="completed",
        )
        rewritten = (completion.choices[0].message.content or "").strip()
        return rewritten or None
    except Exception as exc:  # pragma: no cover
        print(f"[response_validator] rewrite failed: {exc}")
        log_openai_chat_usage(
            db,
            tenant_id=tenant_id,
            clinic_id=clinic_id,
            model=OPENAI_MODEL,
            operation="text_rewrite",
            completion=None,
            status="failed",
        )
        return None


def ensure_response_language(
    text: str | None,
    lang: Any,
    *,
    max_retries: int = 1,
    db: Session | None = None,
    tenant_id: int | None = None,
    clinic_id: int | None = None,
) -> str:
    """Validate outbound text; rewrite via LLM if it mixes languages.

    Static i18n templates should already be correct; this guards LLM output.
    """
    raw = text or ""
    code: LangCode = i18n.normalize_lang(lang)  # type: ignore[assignment]
    if validate_response_language(raw, code):
        return raw

    current = raw
    for _ in range(max(1, max_retries)):
        rewritten = _rewrite_in_language(
            current,
            code,
            db=db,
            tenant_id=tenant_id,
            clinic_id=clinic_id,
        )
        if not rewritten:
            break
        if validate_response_language(rewritten, code):
            return rewritten
        current = rewritten

    # Last resort: return original rather than blocking the user.
    print(
        f"[response_validator] could not force language={code}; "
        "sending original text"
    )
    return raw
