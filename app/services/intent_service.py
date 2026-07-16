"""Intent detection: lightweight rules + OpenAI fallback."""

from __future__ import annotations

import json
import re
from enum import StrEnum

from openai import OpenAI

from app.core.config import OPENAI_API_KEY, OPENAI_MODEL


class Intent(StrEnum):
    BOOK = "book"
    UPDATE = "update"
    CANCEL = "cancel"
    ASK_DOCTORS = "ask_doctors"
    HANDOVER = "handover"
    MENU = "menu"
    CONFIRM = "confirm"
    UNKNOWN = "unknown"


_RULES: list[tuple[Intent, re.Pattern[str]]] = [
    (Intent.MENU, re.compile(r"^\s*(menu|القائمة|قائمة)\s*$", re.I)),
    (Intent.UPDATE, re.compile(r"(تعديل|إعادة جدولة|تاجيل|تأجيل|update|reschedule)", re.I)),
    (Intent.CANCEL, re.compile(r"(إلغاء|الغاء|cancel)", re.I)),
    (Intent.BOOK, re.compile(r"(حجز|احجز|book|appointment)", re.I)),
    (Intent.ASK_DOCTORS, re.compile(r"(طبيب|دكتور|تخصص|doctor|specialty)", re.I)),
    (Intent.HANDOVER, re.compile(r"(موظف|استقبال|بشري|handover|human|reception)", re.I)),
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


def detect_intent(text: str) -> Intent:
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
                    "content": (
                        "Classify hospital WhatsApp intents. "
                        "Return JSON {\"intent\": one of "
                        "book,update,cancel,ask_doctors,handover,menu,confirm,unknown}."
                    ),
                },
                {"role": "user", "content": text},
            ],
        )
        content = completion.choices[0].message.content or "{}"
        payload = json.loads(content)
        value = str(payload.get("intent", "unknown")).lower()
        return Intent(value) if value in Intent._value2member_map_ else Intent.UNKNOWN
    except Exception:
        return Intent.UNKNOWN
