"""Detect Arabic vs English from short WhatsApp messages.

Prefers Lingua when available; falls back to Unicode script heuristics so
very short replies still work reliably.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

LangCode = Literal["ar", "en"]

_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_DIGITS_ONLY_RE = re.compile(r"^[\d\s\.\,\:\-\/\+٠-٩]+$")
_PAYLOAD_LIKE_RE = re.compile(
    r"^(lang_(ar|en)|menu_\d+|slot_\d+|dept_\d+|doc_\d+|date_\d{4}-\d{2}-\d{2})$",
    re.I,
)

# Button / list titles that are language selectors, not content to classify.
_EXPLICIT_AR = {"العربية", "عربي", "arabic", "lang_ar"}
_EXPLICIT_EN = {"english", "الانجليزية", "الإنجليزية", "en", "lang_en"}


@lru_cache(maxsize=1)
def _lingua_detector():
    try:
        from lingua import Language, LanguageDetectorBuilder

        return (
            LanguageDetectorBuilder.from_languages(Language.ARABIC, Language.ENGLISH)
            .with_preloaded_language_models()
            .build()
        )
    except Exception as exc:  # pragma: no cover - optional dependency path
        print(f"[language_detector] Lingua unavailable, using script heuristics: {exc}")
        return None


def is_non_linguistic(text: str | None) -> bool:
    """True when the text should not change conversation language."""
    raw = (text or "").strip()
    if not raw:
        return True
    if _PAYLOAD_LIKE_RE.match(raw):
        return True
    if _DIGITS_ONLY_RE.match(raw):
        return True
    # Pure emoji / punctuation
    if not _ARABIC_RE.search(raw) and not _LATIN_RE.search(raw):
        return True
    return False


def _script_counts(text: str) -> tuple[int, int]:
    return len(_ARABIC_RE.findall(text)), len(_LATIN_RE.findall(text))


def _detect_by_script(text: str) -> LangCode | None:
    ar_n, en_n = _script_counts(text)
    if ar_n == 0 and en_n == 0:
        return None
    if ar_n > 0 and en_n == 0:
        return "ar"
    if en_n > 0 and ar_n == 0:
        return "en"
    # Mixed script: majority wins; tie → None (keep previous)
    if ar_n >= en_n * 2:
        return "ar"
    if en_n >= ar_n * 2:
        return "en"
    return None


def _detect_by_lingua(text: str) -> LangCode | None:
    detector = _lingua_detector()
    if detector is None:
        return None
    try:
        from lingua import Language

        confidences = detector.compute_language_confidence_values(text)
        if not confidences:
            return None
        top = confidences[0]
        # Short WhatsApp replies need a lower bar than paragraphs.
        min_confidence = 0.45 if len(text.strip()) < 12 else 0.55
        if top.value < min_confidence:
            return None
        if top.language == Language.ARABIC:
            return "ar"
        if top.language == Language.ENGLISH:
            return "en"
    except Exception as exc:  # pragma: no cover
        print(f"[language_detector] Lingua detect failed: {exc}")
    return None


def detect_language(
    text: str | None,
    *,
    fallback: LangCode | None = None,
) -> LangCode | None:
    """Return ``ar`` / ``en`` for linguistic user text, else ``fallback`` / None.

    Never invents a language for empty, numeric, or payload-only messages.
    """
    raw = (text or "").strip()
    if not raw:
        return fallback

    lower = raw.lower()
    if raw in _EXPLICIT_AR or lower in _EXPLICIT_AR:
        return "ar"
    if raw in _EXPLICIT_EN or lower in _EXPLICIT_EN:
        return "en"

    if is_non_linguistic(raw):
        return fallback

    # Script heuristics are strongest on short bilingual WhatsApp traffic.
    script_hit = _detect_by_script(raw)
    if script_hit is not None:
        return script_hit

    lingua_hit = _detect_by_lingua(raw)
    if lingua_hit is not None:
        return lingua_hit

    return fallback
