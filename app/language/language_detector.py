"""Detect Arabic vs English from short WhatsApp messages.

Language must flip ONLY on real user-written sentences — never on
interactive payloads, list/button titles, appointment refs, or times.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

LangCode = Literal["ar", "en"]

_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_DIGITS_ONLY_RE = re.compile(r"^[\d\s\.\,\:\-\/\+٠-٩]+$")

# Structured WhatsApp interactive ids (list/button payloads).
_UI_PAYLOAD_RE = re.compile(
    r"^(lang_(ar|en)|menu_\d+|slot_\d+|dept_\d+|doc_\d+|doctor_\d+|"
    r"date_\d{4}-\d{2}-\d{2}|appt_\d+|path_specialty|path_by_doctor|"
    r"btn_\d+_.*|flow)$",
    re.I,
)

# Commands / navigation that must NOT flip conversation language.
_COMMAND_KEEP_LANG = {
    "menu",
    "منيو",
    "القائمة",
    "القائمه",
    "قائمة",
}

# Explicit language selectors only.
_EXPLICIT_AR = {"العربية", "عربي", "arabic", "lang_ar"}
_EXPLICIT_EN = {"english", "الانجليزية", "الإنجليزية", "lang_en"}

# Short UI echoes that can appear without a structured payload.
# Long menu phrases are NOT listed — typed "تعديل موعد" should still count as Arabic.
_UI_TITLE_KEEP_LANG = {
    "confirm",
    "cancel",
    "تأكيد",
    "الغاء",
    "إلغاء",
    "same patient",
    "new patient",
    "نفس المريض",
    "مريض جديد",
    "yes",
    "no",
    "نعم",
    "لا",
    "ok",
    "موافق",
    "change time",
    "change day",
    "change doctor",
    "تعديل الوقت",
    "تعديل اليوم",
    "تغيير الوقت",
    "تغيير اليوم",
    "تغيير الطبيب",
    "رجوع",
    "back",
}

# Appointment ref / code fragments: APT-..., 715-2A88, hex-ish tokens.
_APPT_REF_RE = re.compile(
    r"^(APT[-\s]?)?[0-9A-F]{2,}([-\s][0-9A-F]{2,})+$",
    re.I,
)

# Time / date echoes from WhatsApp list titles.
_TIME_ECHO_RE = re.compile(
    r"("
    r"\b\d{1,2}:\d{2}\s*(AM|PM|am|pm|ص|م|مساءً|صباحاً)?\b"
    r"|"
    r"\b\d{1,2}[-/]\d{1,2}([-/]\d{2,4})?\b"
    r"|"
    r"\b\d{4}-\d{2}-\d{2}\b"
    r")"
)

# Strip codes/times so we can judge leftover real words.
_STRIP_NOISE_RE = re.compile(
    r"("
    r"APT[-\s]?[0-9A-F\-]+"
    r"|"
    r"\b\d{1,2}:\d{2}\s*(AM|PM|ص|م)?\b"
    r"|"
    r"\b\d{1,2}[-/]\d{1,2}([-/]\d{2,4})?\b"
    r"|"
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|"
    r"\b[0-9A-F]{3,}(-[0-9A-F]{2,})+\b"
    r")",
    re.I,
)


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


def is_ui_payload(payload_id: str | None) -> bool:
    """True for structured interactive reply ids (list/button)."""
    raw = (payload_id or "").strip()
    return bool(raw and _UI_PAYLOAD_RE.match(raw))


def is_non_linguistic(text: str | None) -> bool:
    """True when the text should not change conversation language."""
    raw = (text or "").strip()
    if not raw:
        return True
    if is_ui_payload(raw):
        return True
    lower = raw.lower().strip()
    if lower in _COMMAND_KEEP_LANG or raw in _COMMAND_KEEP_LANG:
        return True
    if lower in _UI_TITLE_KEEP_LANG or raw in _UI_TITLE_KEEP_LANG:
        return True
    if _DIGITS_ONLY_RE.match(raw):
        return True
    if _APPT_REF_RE.match(raw):
        return True
    # Starts with a clock time (slot titles).
    if re.match(r"^\d{1,2}:\d{2}\b", raw):
        return True
    # Appointment list echo: "715-2A88 07-22 11:00 AM" (little/no Arabic prose).
    if _TIME_ECHO_RE.search(raw) and not _has_real_arabic_words(raw):
        # If leftover Latin is only AM/PM / tiny tokens → non-linguistic.
        if not _has_real_english_words(raw):
            return True
        # Mixed code+time with short Latin leftovers still UI-like.
        if len(_latin_letters_excluding_ampm(raw)) <= 4:
            return True
    # Pure emoji / punctuation
    if not _ARABIC_RE.search(raw) and not _LATIN_RE.search(raw):
        return True
    return False


def _has_real_arabic_words(text: str) -> bool:
    return len(_ARABIC_RE.findall(text)) >= 2


def _latin_letters_excluding_ampm(text: str) -> str:
    cleaned = re.sub(r"\b(AM|PM)\b", "", text, flags=re.I)
    return "".join(_LATIN_RE.findall(cleaned))


def _has_real_english_words(text: str) -> bool:
    """True if text has Latin words beyond codes / AM-PM / date fragments."""
    cleaned = _STRIP_NOISE_RE.sub(" ", text)
    cleaned = re.sub(r"[^A-Za-z\s]", " ", cleaned)
    words = [w for w in cleaned.split() if len(w) >= 3 and w.lower() not in {"am", "pm"}]
    return len(words) >= 1


def _script_counts(text: str) -> tuple[int, int]:
    return len(_ARABIC_RE.findall(text)), len(_LATIN_RE.findall(text))


def _detect_by_script(text: str) -> LangCode | None:
    ar_n, en_n = _script_counts(text)
    if ar_n == 0 and en_n == 0:
        return None
    if ar_n > 0 and en_n == 0:
        return "ar"
    if en_n > 0 and ar_n == 0:
        # Latin-only: require real words, not codes like "2A88" or "AM".
        if not _has_real_english_words(text):
            return None
        return "en"
    # Mixed script: strong majority only; otherwise keep previous.
    if ar_n >= en_n * 2 and ar_n >= 2:
        return "ar"
    if en_n >= ar_n * 2 and _has_real_english_words(text):
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
        # Higher bar — short UI echoes must not flip language.
        min_confidence = 0.70 if len(text.strip()) < 20 else 0.60
        if top.value < min_confidence:
            return None
        if top.language == Language.ARABIC and _has_real_arabic_words(text):
            return "ar"
        if top.language == Language.ENGLISH and _has_real_english_words(text):
            return "en"
    except Exception as exc:  # pragma: no cover
        print(f"[language_detector] Lingua detect failed: {exc}")
    return None


def is_confident_switch(text: str, detected: LangCode) -> bool:
    """Extra gate before flipping an already-set conversation language."""
    raw = (text or "").strip()
    if not raw or is_non_linguistic(raw):
        return False
    if detected == "ar":
        return _has_real_arabic_words(raw)
    if detected == "en":
        return _has_real_english_words(raw) and len(_latin_letters_excluding_ampm(raw)) >= 4
    return False


def detect_language(
    text: str | None,
    *,
    fallback: LangCode | None = None,
) -> LangCode | None:
    """Return ``ar`` / ``en`` for linguistic user text, else ``fallback`` / None.

    Never invents a language for empty, numeric, payload, or UI-echo messages.
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

    script_hit = _detect_by_script(raw)
    if script_hit is not None:
        return script_hit

    lingua_hit = _detect_by_lingua(raw)
    if lingua_hit is not None:
        return lingua_hit

    return fallback
