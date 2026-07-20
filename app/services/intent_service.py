"""Intent detection: lightweight rules + OpenAI fallback."""

from __future__ import annotations

import json
import re
from enum import StrEnum

from openai import OpenAI

from app.core.config import OPENAI_API_KEY, OPENAI_MODEL
from app.language.multilingual_prompt import build_system_prompt


class Intent(StrEnum):
    BOOK = "book"
    UPDATE = "update"
    CANCEL = "cancel"
    ASK_DOCTORS = "ask_doctors"
    HANDOVER = "handover"
    MENU = "menu"
    CONFIRM = "confirm"
    THANKS = "thanks"
    UNKNOWN = "unknown"


_RULES: list[tuple[Intent, re.Pattern[str]]] = [
    (Intent.MENU, re.compile(r"^\s*(menu|منيو|القائمة|القائمه|قائمة)\s*$", re.I)),
    (
        Intent.MENU,
        re.compile(
            r"(مرحبا|أهلا|اهلا|السلام\s*عليكم|صباح الخي|مساء الخي|"
            r"\bhi\b|\bhello\b|\bhey\b|good\s*(morning|evening|afternoon)|"
            r"ابدأ|ابدا|start|help|مساعدة|كيف أقدر|ماذا يمكنك|وش تقدر)",
            re.I,
        ),
    ),
    (
        Intent.THANKS,
        re.compile(
            r"^\s*(شكرا|شكراً|merci|thanks|thank you|thx|ok|تمام|حسنا|حسناً)\s*[!.]*\s*$",
            re.I,
        ),
    ),
    (
        Intent.UPDATE,
        re.compile(
            r"(تعديل|إعادة جدولة|تاجيل|تأجيل|update|reschedule|"
            r"change.*(time|day|doctor|appointment))",
            re.I,
        ),
    ),
    (Intent.CANCEL, re.compile(r"(إلغاء|الغاء|cancel)", re.I)),
    (
        Intent.BOOK,
        re.compile(
            r"(حجز|احجز|أبغى موعد|ابي موعد|بدي موعد|أريد موعد|book|appointment)",
            re.I,
        ),
    ),
    (
        Intent.ASK_DOCTORS,
        re.compile(r"(طبيب|دكتور|تخصص|doctor|specialty|specialist)", re.I),
    ),
    (
        Intent.HANDOVER,
        re.compile(r"(موظف|استقبال|بشري|handover|human|reception|agent)", re.I),
    ),
    (Intent.CONFIRM, re.compile(r"(تأكيد|أكد|confirm|نعم.?أكد)", re.I)),
]


def detect_intent_rules(text: str) -> Intent:
    cleaned = (text or "").strip()
    if not cleaned:
        return Intent.UNKNOWN
    for intent, pattern in _RULES:
        if pattern.search(cleaned):
            return intent
    return Intent.UNKNOWN


def detect_intent(text: str, *, lang: str | None = None) -> Intent:
    """Rules first; OpenAI only when unclear and key is configured."""
    intent = detect_intent_rules(text)
    if intent != Intent.UNKNOWN:
        return intent
    if not OPENAI_API_KEY:
        return Intent.UNKNOWN
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": build_system_prompt(
                        lang or "ar", purpose="intent_classifier"
                    ),
                },
                {"role": "user", "content": text},
            ],
        )
        content = completion.choices[0].message.content or "{}"
        payload = json.loads(content)
        value = str(payload.get("intent", "unknown")).lower().strip()
        if value in Intent._value2member_map_:
            return Intent(value)
        return Intent.UNKNOWN
    except Exception:
        return Intent.UNKNOWN
