"""Pydantic schemas for WhatsApp voice → Whisper STT → LLM action."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.services.intent_service import Intent


VoiceIntentLiteral = Literal[
    "book",
    "update",
    "cancel",
    "ask_doctors",
    "handover",
    "menu",
    "confirm",
    "unknown",
]

VoiceActionLiteral = Literal[
    "select_option",
    "intent",
    "book_direct",
    "specialty_direct",
    "clarify",
]

_CONF_WORDS = {
    "very high": 0.95,
    "high": 0.9,
    "medium": 0.65,
    "moderate": 0.65,
    "low": 0.35,
    "very low": 0.2,
}


class VoiceUnderstanding(BaseModel):
    """LLM structured understanding of a Whisper transcript."""

    transcript: str = Field(default="")
    action: VoiceActionLiteral = Field(default="clarify")
    selected_option_id: Optional[str] = Field(default=None)
    intent: VoiceIntentLiteral = Field(default="unknown")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    doctor_hint: Optional[str] = Field(default=None)
    specialty_hint: Optional[str] = Field(default=None)
    date_hint: Optional[str] = Field(
        default=None,
        description="Appointment date as YYYY-MM-DD if spoken.",
    )
    time_hint: Optional[str] = Field(
        default=None,
        description="Appointment time like 16:30 or 4:30 PM if spoken.",
    )
    summary_ar: str = Field(default="")
    language: Literal["ar", "en", "mixed", "unknown"] = Field(default="ar")

    @field_validator("intent", mode="before")
    @classmethod
    def _coerce_intent(cls, v: Any) -> str:
        if v is None or v == "":
            return "unknown"
        s = str(v).strip().lower()
        allowed = {
            "book",
            "update",
            "cancel",
            "ask_doctors",
            "handover",
            "menu",
            "confirm",
            "unknown",
        }
        return s if s in allowed else "unknown"

    @field_validator("action", mode="before")
    @classmethod
    def _coerce_action(cls, v: Any) -> str:
        if v is None or v == "":
            return "clarify"
        s = str(v).strip().lower()
        if s in {"select_option", "intent", "clarify", "book_direct", "specialty_direct"}:
            return s
        if s in {"select", "option", "choose"}:
            return "select_option"
        if s in {"book_fast", "direct_book", "fast_book"}:
            return "book_direct"
        if s in {"specialty", "by_specialty", "specialty_list"}:
            return "specialty_direct"
        return "clarify"

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, v: Any) -> float:
        if v is None or v == "":
            return 0.5
        if isinstance(v, (int, float)):
            return max(0.0, min(1.0, float(v)))
        s = str(v).strip().lower()
        if s in _CONF_WORDS:
            return _CONF_WORDS[s]
        try:
            return max(0.0, min(1.0, float(s)))
        except ValueError:
            return 0.5

    @field_validator("transcript", "summary_ar", mode="before")
    @classmethod
    def _coerce_text(cls, v: Any) -> str:
        return "" if v is None else str(v)

    @field_validator(
        "doctor_hint",
        "specialty_hint",
        "date_hint",
        "time_hint",
        "selected_option_id",
        mode="before",
    )
    @classmethod
    def _coerce_optional(cls, v: Any) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    def as_intent(self) -> Intent:
        try:
            return Intent(self.intent)
        except ValueError:
            return Intent.UNKNOWN
