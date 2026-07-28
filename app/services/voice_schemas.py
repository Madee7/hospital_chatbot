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

# Extended language codes the router may emit; folded to ar/en/mixed/unknown
# for downstream use via VoiceUnderstanding.base_language().
VoiceLanguageLiteral = Literal[
    "ar",
    "ar-EG",
    "en",
    "en-US",
    "en-GB",
    "mixed",
    "unknown",
]

# Edit/update flow: which part of an existing appointment to change.
VoiceChangeTargetLiteral = Literal["doctor", "date", "time"]

_CONF_WORDS = {
    "very high": 0.95,
    "high": 0.9,
    "medium": 0.65,
    "moderate": 0.65,
    "low": 0.35,
    "very low": 0.2,
}

_LANGUAGE_MAP = {
    "ar": "ar",
    "arabic": "ar",
    "ar-eg": "ar-EG",
    "arz": "ar-EG",
    "egyptian": "ar-EG",
    "en": "en",
    "english": "en",
    "en-us": "en-US",
    "en-gb": "en-GB",
    "mixed": "mixed",
    "unknown": "unknown",
}

_CHANGE_TARGET_MAP = {
    "doctor": "doctor",
    "physician": "doctor",
    "طبيب": "doctor",
    "دكتور": "doctor",
    "date": "date",
    "day": "date",
    "يوم": "date",
    "تاريخ": "date",
    "time": "time",
    "slot": "time",
    "وقت": "time",
    "ميعاد": "time",
}


def coerce_language(v: Any) -> str:
    """Normalize a spoken-language code; unknown values fall back to Arabic."""
    if v is None or v == "":
        return "ar"
    s = str(v).strip().lower().replace("_", "-")
    return _LANGUAGE_MAP.get(s, "ar")


def coerce_change_target(v: Any) -> str | None:
    """Map doctor/date/time synonyms (EN + AR) onto the canonical target."""
    if v is None or v == "":
        return None
    return _CHANGE_TARGET_MAP.get(str(v).strip().lower())


def coerce_confidence_value(v: Any, *, default: float | None = None) -> float | None:
    """Accept numbers or words ('high') and clamp to 0.0–1.0."""
    if v is None or v == "":
        return default
    if isinstance(v, (int, float)):
        return max(0.0, min(1.0, float(v)))
    s = str(v).strip().lower()
    if s in _CONF_WORDS:
        return _CONF_WORDS[s]
    try:
        return max(0.0, min(1.0, float(s)))
    except ValueError:
        return default


def fold_language(language: str | None) -> str:
    """Fold regional codes (ar-EG/en-US…) to ar/en/mixed/unknown."""
    s = (language or "").lower()
    if s.startswith("ar"):
        return "ar"
    if s.startswith("en"):
        return "en"
    if s == "mixed":
        return "mixed"
    return "unknown"


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
    language: VoiceLanguageLiteral = Field(default="ar")
    change_target: Optional[VoiceChangeTargetLiteral] = Field(
        default=None,
        description="For edit/update: which part to change (doctor/date/time).",
    )

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
        got = coerce_confidence_value(v, default=0.5)
        return 0.5 if got is None else got

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

    @field_validator("language", mode="before")
    @classmethod
    def _coerce_language(cls, v: Any) -> str:
        return coerce_language(v)

    @field_validator("change_target", mode="before")
    @classmethod
    def _coerce_change_target(cls, v: Any) -> str | None:
        return coerce_change_target(v)

    def base_language(self) -> str:
        """Fold regional codes (ar-EG/en-US…) to ar/en/mixed/unknown."""
        return fold_language(self.language)

    def as_intent(self) -> Intent:
        try:
            return Intent(self.intent)
        except ValueError:
            return Intent.UNKNOWN


# ---------------------------------------------------------------------------
# Router V2 — the LLM plans, the executor validates and executes
# ---------------------------------------------------------------------------
#
# V1 (VoiceUnderstanding) asks the model to *classify* into five actions, then
# Python re-decides the flow via confidence thresholds and ordered branches.
# V2 asks the model for a *plan*: what the patient wants (goal) and which step
# of the booking machine to run next (next_step), plus every slot it could
# extract. app/services/voice_executor.py owns validation: it checks each
# step's preconditions against real DB availability and degrades one rung down
# the funnel when a step can't be fulfilled — always with a message to the
# patient, never a silent fall-through.

# What the patient ultimately wants.
VoiceGoalLiteral = Literal[
    "book_new",
    "reschedule",
    "cancel_appointment",  # cancel a real, already-booked appointment
    "abandon_draft",  # "forget it" — drop the half-finished booking only
    "ask_doctors",
    "ask_availability",
    "ask_clinic_info",
    "confirm",
    "decline",
    "handover",
    "menu",
    "thanks",
    "unclear",
]

# Which step of the flow to run next. Mirrors the engine's booking funnel.
VoiceNextStepLiteral = Literal[
    "show_menu",
    "ask_specialty",
    "show_doctors",
    "ask_date",
    "show_slots",
    "hold_slot",
    "ask_patient_name",
    "show_summary",
    "confirm_booking",
    "pick_appointment",
    "confirm_cancel",
    "ask_change_target",
    "handover",
    "clarify",
]

VoiceDateFlexibilityLiteral = Literal["exact", "earliest", "any"]


class VoiceSlots(BaseModel):
    """Everything extractable from one utterance. All optional by design."""

    doctor_name: Optional[str] = Field(
        default=None, description="Person name only, titles stripped."
    )
    doctor_alternatives: list[str] = Field(
        default_factory=list,
        description="Further doctor candidates when several were named.",
    )
    specialty: Optional[str] = Field(default=None)
    date: Optional[str] = Field(default=None, description="YYYY-MM-DD if spoken.")
    date_flexibility: Optional[VoiceDateFlexibilityLiteral] = Field(default=None)
    time: Optional[str] = Field(
        default=None,
        description="HH:MM (24h) or morning/afternoon/evening/any.",
    )
    patient_name: Optional[str] = Field(
        default=None,
        description="The PATIENT's own name (never a doctor's).",
    )
    appointment_ref: Optional[str] = Field(
        default=None, description="Reference of an existing appointment."
    )
    change_target: Optional[VoiceChangeTargetLiteral] = Field(default=None)
    selected_option_id: Optional[str] = Field(
        default=None, description="Exact id from OPTIONS_JSON; never invented."
    )

    @field_validator(
        "doctor_name",
        "specialty",
        "date",
        "time",
        "patient_name",
        "appointment_ref",
        "selected_option_id",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, v: Any) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @field_validator("doctor_alternatives", mode="before")
    @classmethod
    def _clean_alternatives(cls, v: Any) -> list[str]:
        if not v:
            return []
        if isinstance(v, str):
            v = [v]
        return [str(x).strip() for x in v if str(x or "").strip()]

    @field_validator("change_target", mode="before")
    @classmethod
    def _coerce_target(cls, v: Any) -> str | None:
        return coerce_change_target(v)


class VoiceFieldConfidence(BaseModel):
    """Per-field confidence so one fuzzy slot can't sink a clear utterance."""

    overall: float = Field(default=0.5, ge=0.0, le=1.0)
    doctor: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    date: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    time: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @field_validator("doctor", "date", "time", mode="before")
    @classmethod
    def _coerce_optional(cls, v: Any) -> float | None:
        return coerce_confidence_value(v)

    @field_validator("overall", mode="before")
    @classmethod
    def _coerce_overall(cls, v: Any) -> float:
        got = coerce_confidence_value(v, default=0.5)
        return 0.5 if got is None else got


class VoicePlan(BaseModel):
    """The router's plan for one voice note."""

    transcript: str = Field(default="")
    goal: VoiceGoalLiteral = Field(default="unclear")
    next_step: VoiceNextStepLiteral = Field(default="clarify")
    slots: VoiceSlots = Field(default_factory=VoiceSlots)
    confidence: VoiceFieldConfidence = Field(default_factory=VoiceFieldConfidence)
    followup_goal: Optional[VoiceGoalLiteral] = Field(
        default=None,
        description="Second request in a compound utterance, e.g. cancel then book.",
    )
    summary_ar: str = Field(default="")
    summary_en: str = Field(default="")
    language: VoiceLanguageLiteral = Field(default="ar")

    @field_validator("transcript", "summary_ar", "summary_en", mode="before")
    @classmethod
    def _text(cls, v: Any) -> str:
        return "" if v is None else str(v)

    @field_validator("goal", "followup_goal", mode="before")
    @classmethod
    def _coerce_goal(cls, v: Any) -> str | None:
        if v is None or v == "":
            return None
        s = str(v).strip().lower().replace("-", "_").replace(" ", "_")
        allowed = {
            "book_new",
            "reschedule",
            "cancel_appointment",
            "abandon_draft",
            "ask_doctors",
            "ask_availability",
            "ask_clinic_info",
            "confirm",
            "decline",
            "handover",
            "menu",
            "thanks",
            "unclear",
        }
        if s in allowed:
            return s
        synonyms = {
            "book": "book_new",
            "booking": "book_new",
            "new_booking": "book_new",
            "update": "reschedule",
            "edit": "reschedule",
            "change": "reschedule",
            "cancel": "cancel_appointment",
            "abort": "abandon_draft",
            "quit": "abandon_draft",
            "availability": "ask_availability",
            "info": "ask_clinic_info",
            "location": "ask_clinic_info",
            "agent": "handover",
            "human": "handover",
            "yes": "confirm",
            "no": "decline",
        }
        return synonyms.get(s, "unclear")

    @field_validator("next_step", mode="before")
    @classmethod
    def _coerce_step(cls, v: Any) -> str:
        if v is None or v == "":
            return "clarify"
        s = str(v).strip().lower().replace("-", "_").replace(" ", "_")
        allowed = {
            "show_menu",
            "ask_specialty",
            "show_doctors",
            "ask_date",
            "show_slots",
            "hold_slot",
            "ask_patient_name",
            "show_summary",
            "confirm_booking",
            "pick_appointment",
            "confirm_cancel",
            "ask_change_target",
            "handover",
            "clarify",
        }
        if s in allowed:
            return s
        synonyms = {
            "menu": "show_menu",
            "specialty": "ask_specialty",
            "doctors": "show_doctors",
            "doctor": "show_doctors",
            "date": "ask_date",
            "dates": "ask_date",
            "slots": "show_slots",
            "time": "show_slots",
            "book_slot": "hold_slot",
            "hold": "hold_slot",
            "name": "ask_patient_name",
            "summary": "show_summary",
            "confirm": "confirm_booking",
            "cancel": "confirm_cancel",
            "change_type": "ask_change_target",
        }
        return synonyms.get(s, "clarify")

    @field_validator("language", mode="before")
    @classmethod
    def _lang(cls, v: Any) -> str:
        return coerce_language(v)

    def base_language(self) -> str:
        """Fold regional codes (ar-EG/en-US…) to ar/en/mixed/unknown."""
        return fold_language(self.language)

    def summary(self) -> str:
        """Arabic summary preferred; English is the fallback for en callers."""
        return self.summary_ar or self.summary_en

    def to_understanding(self) -> VoiceUnderstanding:
        """Project the plan onto the legacy V1 shape.

        This is the migration safety net: when the executor declines a plan we
        can still hand it to the battle-tested V1 fastpath instead of dropping
        the patient's request. The projection is intentionally lossy — V1 has
        no way to express abandon_draft vs cancel_appointment, a patient name,
        an appointment ref, or a second doctor candidate.
        """
        goal = self.goal
        slots = self.slots
        intent_map: dict[str, str] = {
            "book_new": "book",
            "reschedule": "update",
            "cancel_appointment": "cancel",
            "abandon_draft": "cancel",
            "ask_doctors": "ask_doctors",
            "ask_availability": "ask_doctors",
            "confirm": "confirm",
            "decline": "update",
            "handover": "handover",
            "menu": "menu",
        }
        intent = intent_map.get(goal, "unknown")

        if slots.selected_option_id:
            action = "select_option"
        elif goal == "unclear":
            action = "clarify"
        elif slots.doctor_name and goal in {"book_new", "reschedule", "ask_availability"}:
            action = "book_direct"
        elif slots.specialty and goal in {
            "book_new",
            "reschedule",
            "ask_doctors",
            "ask_availability",
        }:
            action = "specialty_direct"
        elif intent == "unknown":
            action = "clarify"
        else:
            action = "intent"

        return VoiceUnderstanding(
            transcript=self.transcript,
            action=action,
            selected_option_id=slots.selected_option_id,
            intent=intent,
            confidence=self.confidence.overall,
            doctor_hint=slots.doctor_name,
            specialty_hint=slots.specialty,
            date_hint=slots.date,
            time_hint=slots.time,
            change_target=slots.change_target,
            summary_ar=self.summary_ar,
            language=self.language,
        )
