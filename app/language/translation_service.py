"""Display-only translation layer.

Canonical entity values stay in the database untouched. This module only
chooses AR/EN presentation fields (or static maps) for WhatsApp replies.
Booking, search, and updates always use entity IDs / canonical records.
"""

from __future__ import annotations

from typing import Any

from app.core import i18n_bot as i18n


class TranslationService:
    """Presentation helpers — never write translated strings back to the DB."""

    def __init__(self, lang: Any):
        self.lang = i18n.normalize_lang(lang)

    @property
    def is_english(self) -> bool:
        return i18n.is_english(self.lang)

    def clinic_name(self, clinic_name: str | None = None) -> str:
        return i18n.clinic_name_for_lang(self.lang, clinic_name)

    def clinic_location(self, location: str | None = None) -> str:
        return i18n.clinic_location(self.lang, location)

    def doctor_name(self, doctor_or_dict: Any) -> str:
        """Prefer language-specific display field; never invent a DB row."""
        return i18n.doctor_display_name(doctor_or_dict, self.lang)

    def doctor_fields(self, doctor_or_dict: Any) -> dict[str, str | None]:
        return i18n.doctor_display_fields(doctor_or_dict, self.lang)

    def specialty(self, value: str | None) -> str | None:
        return i18n.localize_specialty(value, self.lang)

    def title(self, value: str | None) -> str | None:
        return i18n.localize_title(value, self.lang)

    def department_name(self, dept_or_dict: Any) -> str:
        if isinstance(dept_or_dict, dict):
            name_ar = dept_or_dict.get("name_ar")
            name_en = dept_or_dict.get("name_en")
            dept_id = dept_or_dict.get("department_id", "?")
        else:
            name_ar = getattr(dept_or_dict, "name_ar", None)
            name_en = getattr(dept_or_dict, "name_en", None)
            dept_id = getattr(dept_or_dict, "department_id", "?")
        picked = i18n.pick_bilingual_field(
            en=name_en,
            ar=name_ar,
            lang=self.lang,
            allow_cross_script=False,
            fallback=None,
        )
        if picked:
            return picked
        # Last resort so specialty lists are never blank.
        return (name_en or name_ar or f"Department {dept_id}") or ""

    def patient_display_name(self, canonical_name: str | None) -> str:
        """Patients usually have one stored name; return it unchanged.

        Do not persist any translated form — display only.
        """
        return (canonical_name or "").strip()


# Tokens that must never be rewritten by LLM translation helpers.
NEVER_TRANSLATE_TOKENS = (
    "uuid",
    "booking_id",
    "appointment_ref",
    "database_id",
    "url",
    "email",
    "phone",
    "date",
    "time",
)
