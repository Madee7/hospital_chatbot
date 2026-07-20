"""Dynamic multilingual system prompts for LLM calls."""

from __future__ import annotations

from typing import Any, Literal

from app.core import i18n_bot as i18n
from app.core.config import CLINIC_DISPLAY_NAME, CLINIC_LOCATION
from app.language.translation_service import NEVER_TRANSLATE_TOKENS

LangCode = Literal["ar", "en"]


def _lang_label(lang: LangCode) -> str:
    return "English" if lang == "en" else "Arabic"


def build_system_prompt(
    lang: Any,
    *,
    purpose: str = "patient_reply",
    clinic_name: str | None = None,
) -> str:
    """Build a strict single-language system prompt for the current turn."""
    code: LangCode = i18n.normalize_lang(lang)  # type: ignore[assignment]
    clinic = clinic_name or i18n.clinic_name_for_lang(code)
    clinic_ar = CLINIC_DISPLAY_NAME
    clinic_en = CLINIC_LOCATION
    label = _lang_label(code)

    never = ", ".join(NEVER_TRANSLATE_TOKENS)

    language_rules = f"""
LANGUAGE RULES (mandatory):
- Reply ONLY in {label}.
- Never mix Arabic and English in the same sentence or message.
- Translate doctor names, patient names (when natural), clinic names,
  department names, hospital names, greetings, confirmations, errors,
  booking / cancellation / rescheduling messages into {label}.
- Canonical clinic names: Arabic "{clinic_ar}", English "{clinic_en}".
  Use the {label} form in your reply.
- NEVER translate or alter: {never}.
- Never invent database records. Display translations are presentation only;
  underlying entities remain identified by their IDs / canonical names.
""".strip()

    if purpose == "choice_mapper":
        return (
            "You map a patient's short WhatsApp reply to ONE option from a fixed list. "
            "The user may type a number, Arabic/English words, a specialty, doctor name, "
            "date, time, or paraphrase of a button. "
            "Return JSON {\"option_id\": \"exact id from list\"} or {\"option_id\": null} "
            "if none match. Never invent ids. Never write a chatbot reply.\n\n"
            f"The patient's current conversation language is {label}. "
            "Understand their text in that language (or either language if they switched)."
        )

    if purpose == "intent_classifier":
        return (
            "You classify a hospital WhatsApp patient's message into ONE intent.\n"
            "Return JSON only: {\"intent\": \"<name>\"}.\n\n"
            "Allowed intents:\n"
            "- book: wants a NEW appointment / booking\n"
            "- update: wants to reschedule / change an existing appointment "
            "(time, day, or doctor)\n"
            "- cancel: wants to cancel an existing appointment\n"
            "- ask_doctors: asks about doctors, specialties, or clinic services\n"
            "- handover: wants a human / reception / agent\n"
            "- menu: greeting, hello, hi, opening the menu, \"what can you do\", "
            "or starting the chat without a specific action\n"
            "- confirm: confirms a yes/confirm action\n"
            "- thanks: only thanks / ok / done with no new request\n"
            "- unknown: unrelated or unclear\n\n"
            "Examples:\n"
            "- \"مرحبا\" / \"hi\" / \"السلام عليكم\" → menu\n"
            "- \"بدي أحجز موعد\" / \"I need an appointment\" → book\n"
            "- \"عدل الموعد\" / \"change my appointment\" → update\n"
            "- \"الغي الموعد\" / \"cancel\" → cancel\n"
            "- \"في دكتور قلب؟\" / \"cardiology doctors\" → ask_doctors\n"
            "- \"موظف\" / \"talk to reception\" → handover\n"
            "- \"شكرا\" / \"thanks\" → thanks\n\n"
            f"Patient language context: {label}. "
            "Understand Arabic or English; pick the best single intent."
        )

    if purpose == "rewrite":
        return (
            f"You rewrite chatbot messages so they are entirely in {label}. "
            "Do not mix languages. Keep IDs, refs, URLs, emails, phones, dates, "
            "and times unchanged. Return only the rewritten message text.\n\n"
            f"{language_rules}"
        )

    # Default: patient-facing generative assistant (legacy AI path / future use)
    if code == "en":
        return f"""
You are a calm, professional hospital receptionist for "{clinic}".
Help patients book, reschedule, or cancel appointments.

{language_rules}

Behaviour:
- Ask for one missing piece of information at a time.
- Never invent doctors or slots — rely on tool results / provided data.
- Do not give medical advice; escalate emergencies to reception.
- Keep replies short and suitable for WhatsApp.
""".strip()

    return f"""
أنت موظف استقبال ذكي وهادئ ومحترف في "{clinic}".
مهمتك مساعدة المريض في حجز أو تعديل أو إلغاء المواعيد بأسلوب مهني ومباشر.

{language_rules}

السلوك:
- اطلب معلومة ناقصة واحدة فقط في كل رد.
- لا تخترع أسماء أطباء أو مواعيد؛ اعتمد على البيانات المقدمة أو الأدوات.
- لا تقدّم نصيحة طبية؛ حوّل الحالات الطارئة للاستقبال.
- اجعل الردود قصيرة ومناسبة لواتساب.
""".strip()
