"""Bot message locale helpers (Arabic / English)."""

from __future__ import annotations

from typing import Any

from app.core.config import CLINIC_DISPLAY_NAME, CLINIC_LOCATION, CLINIC_LOCATION_AR
from app.db.enums import Language


def clinic_location(lang: Any, location: str | None = None) -> str:
    """Return clinic location in the patient's language (appointment ref stays untouched elsewhere)."""
    if location:
        if not is_english(lang) and location.strip() == CLINIC_LOCATION.strip():
            return CLINIC_LOCATION_AR
        return location
    return CLINIC_LOCATION if is_english(lang) else CLINIC_LOCATION_AR


def normalize_lang(lang: Any) -> str:
    """Return 'ar' or 'en'."""
    if lang is None:
        return "ar"
    raw = lang.value if hasattr(lang, "value") else str(lang)
    raw = raw.lower().strip()
    if raw.startswith("en"):
        return "en"
    return "ar"


def is_english(lang: Any) -> bool:
    return normalize_lang(lang) == "en"


def to_language_enum(code: str) -> Language:
    return Language.EN if normalize_lang(code) == "en" else Language.AR


def language_prompt() -> str:
    return (
        "الرجاء اختيار اللغة:\n"
        "1. العربية\n"
        "2. الانجليزية\n\n"
        "Please choose your language:\n"
        "1. Arabic\n"
        "2. English"
    )


def clinic_name_for_lang(lang: Any, clinic_name: str | None = None) -> str:
    """Return clinic name in the patient's language."""
    if clinic_name:
        return clinic_name
    return CLINIC_LOCATION if is_english(lang) else CLINIC_DISPLAY_NAME


def welcome(lang: Any, clinic_name: str | None = None) -> str:
    name = clinic_name_for_lang(lang, clinic_name)
    if is_english(lang):
        return f"Welcome to {name} 🏥"
    return f"{name} ترحب بكم 🏥"


def main_menu(lang: Any, clinic_name: str | None = None) -> str:
    name = clinic_name_for_lang(lang, clinic_name)
    if is_english(lang):
        return (
            f"Welcome to {name}. How can we help you?\n"
            "1. Book appointment\n"
            "2. Reschedule appointment\n"
            "3. Cancel appointment\n"
            "4. Ask about doctors/specialties\n"
            "5. Talk to reception"
        )
    return (
        f"أهلاً بك في {name}. كيف يمكننا مساعدتك؟\n"
        "1. حجز موعد\n"
        "2. تعديل موعد\n"
        "3. إلغاء موعد\n"
        "4. الاستفسار عن الأطباء/التخصصات\n"
        "5. التحدث مع موظف الاستقبال"
    )


def main_menu_rows(lang: Any) -> list[str]:
    if is_english(lang):
        return [
            "Book appointment",
            "Reschedule",
            "Cancel",
            "Ask about doctors",
            "Talk to reception",
        ]
    return [
        "حجز موعد",
        "تعديل موعد",
        "إلغاء موعد",
        "الاستفسار عن الأطباء",
        "التحدث مع موظف",
    ]


def menu_button_label(lang: Any) -> str:
    return "Menu" if is_english(lang) else "القائمة"


def menu_section_title(lang: Any) -> str:
    return "Options" if is_english(lang) else "الخيارات"


def booking_path_prompt(lang: Any) -> str:
    if is_english(lang):
        return "Do you prefer searching by specialty or by doctor name?"
    return "هل تفضّل البحث بالتخصص أم باسم الدكتور؟"


def booking_path_buttons(lang: Any) -> list[dict[str, str]]:
    if is_english(lang):
        return [
            {"id": "path_specialty", "title": "By specialty"},
            {"id": "path_by_doctor", "title": "By doctor name"},
        ]
    return [
        {"id": "path_specialty", "title": "بالتخصص"},
        {"id": "path_by_doctor", "title": "باسم الدكتور"},
    ]


def inquiry_prompt(lang: Any) -> str:
    if is_english(lang):
        return "For inquiry: choose a specialty, or browse doctors by name."
    return "للاستفسار: اختر التخصص، أو تصفّح الأطباء بالاسم."


def doctors_by_name_prompt(lang: Any) -> str:
    if is_english(lang):
        return "Choose a doctor (name and specialty):"
    return "اختر الطبيب (الاسم والتخصص):"


def doctors_list_button_label(lang: Any) -> str:
    return "Doctors" if is_english(lang) else "الأطباء"


def language_saved(lang: Any) -> str:
    if is_english(lang):
        return "Language set to English. Continuing…"
    return "تم ضبط اللغة على العربية. جاري المتابعة…"


def confirmation(
    lang: Any,
    *,
    appointment_ref: str,
    doctor_name: str,
    specialization: str | None,
    date_label: str,
    time_label: str,
    location: str | None = None,
) -> str:
    loc = clinic_location(lang, location)
    spec_label = localize_specialty(specialization, lang)
    if is_english(lang):
        spec = f" - {spec_label}" if spec_label else ""
        return (
            "Your appointment is confirmed.\n"
            f"Ref: {appointment_ref}\n"
            f"Doctor: {doctor_name}{spec}\n"
            f"Date: {date_label}\n"
            f"Time: {time_label}\n"
            f"Location: {loc}\n"
            "You will get a reminder. Type MENU anytime to manage it."
        )
    from app.core.messages import confirmation_ar

    return confirmation_ar(
        appointment_ref=appointment_ref,
        doctor_name=doctor_name,
        specialization=spec_label,
        date_label=date_label,
        time_label=time_label,
        location=loc,
    )


def reschedule_confirmation(
    lang: Any,
    *,
    appointment_ref: str,
    doctor_name: str,
    specialization: str | None,
    date_label: str,
    time_label: str,
    location: str | None = None,
) -> str:
    loc = clinic_location(lang, location)
    spec_label = localize_specialty(specialization, lang)
    if is_english(lang):
        spec = f" - {spec_label}" if spec_label else ""
        return (
            "Your appointment was rescheduled.\n"
            f"Ref: {appointment_ref}\n"
            f"Doctor: {doctor_name}{spec}\n"
            f"New date: {date_label}\n"
            f"New time: {time_label}\n"
            f"Location: {loc}\n"
            "Reminders updated. Type MENU to manage the appointment."
        )
    from app.core.messages import reschedule_confirmation_ar

    return reschedule_confirmation_ar(
        appointment_ref=appointment_ref,
        doctor_name=doctor_name,
        specialization=spec_label,
        date_label=date_label,
        time_label=time_label,
        location=loc,
    )


def cancel_confirmation(
    lang: Any,
    *,
    appointment_ref: str,
    doctor_name: str,
    specialization: str | None,
    date_label: str,
    time_label: str,
) -> str:
    spec_label = localize_specialty(specialization, lang)
    if is_english(lang):
        spec = f" - {spec_label}" if spec_label else ""
        return (
            "Your appointment was cancelled.\n"
            f"Ref: {appointment_ref}\n"
            f"Doctor: {doctor_name}{spec}\n"
            f"Was: {date_label} at {time_label}\n"
            "The slot is free and reminders were cancelled."
        )
    from app.core.messages import cancel_confirmation_ar

    return cancel_confirmation_ar(
        appointment_ref=appointment_ref,
        doctor_name=doctor_name,
        specialization=spec_label,
        date_label=date_label,
        time_label=time_label,
    )


def reminder(
    lang: Any,
    *,
    appointment_ref: str,
    doctor_name: str,
    date_label: str,
    time_label: str,
    hours_label: str,
    location: str | None = None,
) -> str:
    loc = clinic_location(lang, location)
    if is_english(lang):
        return (
            f"Appointment reminder ({hours_label}):\n"
            f"Ref: {appointment_ref}\n"
            f"Doctor: {doctor_name}\n"
            f"Date: {date_label}\n"
            f"Time: {time_label}\n"
            f"Location: {loc}\n"
            "Use the buttons or type MENU."
        )
    from app.core.messages import reminder_ar

    return reminder_ar(
        appointment_ref=appointment_ref,
        doctor_name=doctor_name,
        date_label=date_label,
        time_label=time_label,
        hours_label=hours_label,
        location=loc,
    )


# Choice aliases (AR + EN + menu ids)
BOOK_CHOICES = {
    "حجز موعد",
    "Book appointment",
    "menu_0",
    "1",
}
RESCHEDULE_CHOICES = {
    "تعديل موعد",
    "Reschedule",
    "menu_1",
    "2",
}
CANCEL_CHOICES = {
    "إلغاء موعد",
    "Cancel",
    "menu_2",
    "3",
}
INQUIRY_CHOICES = {
    "الاستفسار عن الأطباء",
    "Ask about doctors",
    "menu_3",
    "4",
}
HANDOVER_CHOICES = {
    "التحدث مع موظف",
    "Talk to reception",
    "menu_4",
    "5",
}
PATH_SPECIALTY = {"بالتخصص", "By specialty", "path_specialty"}
PATH_BY_DOCTOR_NAME = {
    "باسم الدكتور",
    "By doctor name",
    "path_by_doctor",
    "كل الأطباء",  # legacy label
    "All doctors",  # legacy label
}
# Backward-compatible alias
PATH_ALL_DOCTORS = PATH_BY_DOCTOR_NAME
LANG_AR_CHOICES = {"العربية", "Arabic", "lang_ar", "1", "عربي"}
LANG_EN_CHOICES = {"English", "الانجليزية", "الإنجليزية", "lang_en", "2", "en"}


# Display-time localization (no extra DB rows). English codes → Arabic labels.
_TITLE_AR = {
    "consultant": "استشاري",
    "specialist": "أخصائي",
    "professor": "أستاذ",
    "resident": "مقيم",
    "gp": "طبيب عام",
    "general practitioner": "طبيب عام",
}

_SPEC_AR = {
    "cardiology": "قلب",
    "pediatrics": "أطفال",
    "paediatrics": "أطفال",
    "pediatrician": "أطفال",
    "paediatrician": "أطفال",
    "ophthalmology": "عيون",
    "dentistry": "أسنان",
    "dental": "أسنان",
    "internal medicine": "باطنة",
    "gastroenterology": "جهاز هضمي",
    "dermatology": "جلدية",
    "orthopedics": "عظام",
    "orthopaedics": "عظام",
    "neurology": "أعصاب",
    "ent": "أنف وأذن وحنجرة",
    "obgyn": "نساء وتوليد",
    "gynecology": "نساء وتوليد",
}


def localize_title(title: str | None, lang: Any) -> str | None:
    if not title:
        return title
    if is_english(lang):
        return title
    mapped = _TITLE_AR.get(title.strip().lower())
    return mapped or title


def localize_specialty(spec: str | None, lang: Any) -> str | None:
    if not spec:
        return spec
    if is_english(lang):
        return spec
    mapped = _SPEC_AR.get(spec.strip().lower())
    return mapped or spec


def doctor_display_name(doctor_or_dict: Any, lang: Any) -> str:
    if isinstance(doctor_or_dict, dict):
        name_ar = doctor_or_dict.get("name_ar")
        name_en = doctor_or_dict.get("name_en")
        doctor_id = doctor_or_dict.get("doctor_id", "?")
    else:
        name_ar = getattr(doctor_or_dict, "name_ar", None)
        name_en = getattr(doctor_or_dict, "name_en", None)
        doctor_id = getattr(doctor_or_dict, "doctor_id", "?")
    if is_english(lang):
        return (name_en or name_ar or f"Doctor {doctor_id}") or ""
    return (name_ar or name_en or f"Doctor {doctor_id}") or ""


def doctor_display_fields(doctor_or_dict: Any, lang: Any) -> dict[str, str | None]:
    """Pick AR/EN name fields + localize title/specialty without duplicating DB rows.

    Specialty on cards follows the doctor's department (booking specialty filter),
    not a stale free-text specialization that may disagree with department_id.
    """
    if isinstance(doctor_or_dict, dict):
        title = doctor_or_dict.get("title")
        spec = doctor_or_dict.get("specialization")
        dept_ar = doctor_or_dict.get("department_ar")
        dept_en = doctor_or_dict.get("department_en")
        bio = doctor_or_dict.get("bio")
        photo = doctor_or_dict.get("photo_url")
        doctor_id = doctor_or_dict.get("doctor_id")
    else:
        title = getattr(doctor_or_dict, "title", None)
        spec = getattr(doctor_or_dict, "specialization", None)
        dept = getattr(doctor_or_dict, "department", None)
        dept_ar = getattr(dept, "name_ar", None) if dept else None
        dept_en = getattr(dept, "name_en", None) if dept else None
        bio = getattr(doctor_or_dict, "bio", None)
        photo = getattr(doctor_or_dict, "photo_url", None)
        doctor_id = getattr(doctor_or_dict, "doctor_id", None)

    if is_english(lang):
        specialty_source = dept_en or spec or dept_ar
    else:
        specialty_source = dept_ar or spec or dept_en

    specialty = localize_specialty(specialty_source, lang) if specialty_source else None

    return {
        "doctor_id": doctor_id,
        "name": doctor_display_name(doctor_or_dict, lang),
        "title": localize_title(title, lang),
        "specialization": specialty,
        "bio": bio,
        "photo_url": photo,
    }


def doctor_card_body(
    lang: Any,
    *,
    name: str,
    title: str | None,
    specialization: str | None,
    profile: str | None = None,
    location: str | None = None,
) -> str:
    lines = [name]
    if title:
        lines.append(title)
    if specialization:
        label = "Specialty:" if is_english(lang) else "التخصص:"
        lines.append(f"{label} {specialization}")
    if profile:
        lines.append(profile)
    if location:
        label = "Location:" if is_english(lang) else "المكان:"
        lines.append(f"{label} {location}")
    return "\n".join(lines)


def choose_doctor_button(lang: Any, name: str) -> str:
    if is_english(lang):
        short = name[:14]
        return f"Select {short}"[:20]
    short = name[:12]
    return f"اختيار {short}"[:20]


def ask_patient_full_name(lang: Any) -> str:
    if is_english(lang):
        return (
            "Please enter the patient's full name (at least three names).\n"
            "Example: Ahmed Mohamed Ali"
        )
    return (
        "برجاء إدخال الاسم الثلاثي للمريض (ثلاثة أسماء على الأقل).\n"
        "مثال: أحمد محمد علي"
    )


def patient_name_too_short(lang: Any) -> str:
    if is_english(lang):
        return (
            "The name must include at least three parts (full name).\n"
            "Please enter it again. Example: Ahmed Mohamed Ali"
        )
    return (
        "الاسم يجب أن يكون ثلاثياً على الأقل.\n"
        "برجاء إعادة الإدخال. مثال: أحمد محمد علي"
    )


def known_patient_prompt(lang: Any, stored_name: str) -> str:
    if is_english(lang):
        return (
            f"This WhatsApp number is already registered as:\n"
            f"*{stored_name}*\n\n"
            "Is this the same patient, or has the patient name changed?"
        )
    return (
        f"هذا الرقم مسجّل لدينا باسم:\n"
        f"*{stored_name}*\n\n"
        "هل أنت نفس المريض، أم تغيّر اسم المريض؟"
    )


def known_patient_buttons(lang: Any) -> list[str]:
    if is_english(lang):
        return ["Same patient", "Name changed"]
    return ["نفس المريض", "تغيّر الاسم"]


SAME_PATIENT_CHOICES = {
    "نفس المريض",
    "Same patient",
    "same",
    "نعم",
    "Yes",
    "yes",
}
NAME_CHANGED_CHOICES = {
    "تغيّر الاسم",
    "تغير الاسم",
    "Name changed",
    "changed",
    "لا",
    "No",
    "no",
}


def hold_timeout_apology(lang: Any) -> str:
    if is_english(lang):
        return (
            "We're sorry — we couldn't complete your appointment booking because "
            "the time allowed to finish the process has run out. "
            "No booking was confirmed. Please try again; we'll be happy to help."
        )
    return (
        "نعتذر، لم نتمكن من إكمال حجز موعدك بسبب تجاوز الوقت المخصص لإتمام العملية. "
        "لم يتم تأكيد أي حجز. يرجى إعادة المحاولة، وسيسعدنا مساعدتك."
    )


def reschedule_hold_timeout_apology(lang: Any) -> str:
    if is_english(lang):
        return (
            "We're sorry — we couldn't complete rescheduling your appointment because "
            "the time allowed to finish the process has run out. "
            "Your previous appointment is unchanged. Please try again; we'll be happy to help."
        )
    return (
        "نعتذر، لم نتمكن من إكمال تعديل موعدك بسبب تجاوز الوقت المخصص لإتمام العملية. "
        "موعدك السابق ما زال كما هو. يرجى إعادة المحاولة، وسيسعدنا مساعدتك."
    )
