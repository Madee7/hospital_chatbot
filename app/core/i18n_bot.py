"""Bot message locale helpers (Arabic / English)."""

from __future__ import annotations

import re
from typing import Any

from app.core.config import CLINIC_DISPLAY_NAME, CLINIC_LOCATION, CLINIC_LOCATION_AR, MIN_LEAD_HOURS
from app.db.enums import Language


def clinic_location(lang: Any, location: str | None = None) -> str:
    """Return clinic location in the patient's language (appointment ref stays untouched elsewhere)."""
    if location:
        if not is_english(lang) and location.strip() == CLINIC_LOCATION.strip():
            return CLINIC_LOCATION_AR
        return location
    return CLINIC_LOCATION if is_english(lang) else CLINIC_LOCATION_AR


def location_block(lang: Any, location: str | None = None) -> str:
    """Normalize a location string for WhatsApp confirmation / summary messages."""
    loc = (location or "").strip() or clinic_location(lang)
    first, *rest = loc.split("\n", 1)
    if not is_english(lang) and first.strip() == CLINIC_LOCATION.strip():
        first = CLINIC_LOCATION_AR
        loc = f"{first}\n{rest[0]}".strip() if rest else first
    return loc


def location_message_lines(lang: Any, location: str | None = None) -> str:
    """Render Location/المكان with optional maps URL on the next line (same message)."""
    loc = location_block(lang, location)
    label = "Location" if is_english(lang) else "المكان"
    if "\n" in loc:
        first, rest = loc.split("\n", 1)
        return f"{label}: {first}\n{rest}"
    return f"{label}: {loc}"


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


def type_menu_hint(lang: Any) -> str:
    if is_english(lang):
        return "Type MENU anytime to open the menu."
    return "اكتب MENU في أي وقت لفتح القائمة."


def thanks_ack(lang: Any) -> str:
    if is_english(lang):
        return "You're welcome. Type MENU anytime if you need anything else."
    return "العفو. اكتب MENU في أي وقت إذا احتجت مساعدة."


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
    loc_lines = location_message_lines(lang, location)
    if is_english(lang):
        return (
            "Appointment confirmed.\n"
            f"Ref: {appointment_ref}\n"
            f"Doctor: {doctor_name}\n"
            f"Date: {date_label}\n"
            f"Time: {time_label}\n"
            f"{loc_lines}\n"
            "Type MENU anytime to manage it."
        )
    return (
        "تم تأكيد موعدك.\n"
        f"رقم الموعد: {appointment_ref}\n"
        f"الطبيب: {doctor_name}\n"
        f"التاريخ: {date_label}\n"
        f"الوقت: {time_label}\n"
        f"{loc_lines}\n"
        "اكتب MENU لإدارة الموعد."
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
    loc_lines = location_message_lines(lang, location)
    if is_english(lang):
        return (
            "Appointment updated.\n"
            f"Ref: {appointment_ref}\n"
            f"Doctor: {doctor_name}\n"
            f"Date: {date_label}\n"
            f"Time: {time_label}\n"
            f"{loc_lines}\n"
            "Type MENU to manage it."
        )
    return (
        "تم تعديل موعدك.\n"
        f"رقم الموعد: {appointment_ref}\n"
        f"الطبيب: {doctor_name}\n"
        f"التاريخ: {date_label}\n"
        f"الوقت: {time_label}\n"
        f"{loc_lines}\n"
        "اكتب MENU لإدارة الموعد."
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
    spec = f" - {spec_label}" if spec_label else ""
    if is_english(lang):
        return (
            "Your appointment was cancelled.\n"
            f"Ref: {appointment_ref}\n"
            f"Doctor: {doctor_name}{spec}\n"
            f"Was: {date_label} at {time_label}\n"
            "The slot is free and reminders were cancelled."
        )
    return (
        "تم إلغاء موعدك بنجاح.\n"
        f"رقم الموعد: {appointment_ref}\n"
        f"الطبيب: {doctor_name}{spec}\n"
        f"كان الموعد: {date_label} الساعة {time_label}\n"
        "تم تحرير الوقت وإلغاء التذكيرات."
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
    loc_lines = location_message_lines(lang, location)
    if is_english(lang):
        return (
            f"Appointment reminder ({hours_label}):\n"
            f"Ref: {appointment_ref}\n"
            f"Doctor: {doctor_name}\n"
            f"Date: {date_label}\n"
            f"Time: {time_label}\n"
            f"{loc_lines}\n"
            "Use the buttons or type MENU."
        )
    return (
        f"تذكير بموعدك ({hours_label}):\n"
        f"رقم الموعد: {appointment_ref}\n"
        f"الطبيب: {doctor_name}\n"
        f"التاريخ: {date_label}\n"
        f"الوقت: {time_label}\n"
        f"{loc_lines}\n"
        "اختر إجراءً من الأزرار أو اكتب MENU."
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
LANG_AR_CHOICES = {"العربية", "Arabic", "lang_ar", "1", "عربي", "arabic"}
LANG_EN_CHOICES = {
    "English",
    "الانجليزية",
    "الإنجليزية",
    "lang_en",
    "2",
    "en",
    "english",
}
CONFIRM_CHOICES = {"تأكيد", "Confirm", "نعم", "yes", "Yes"}
CANCEL_ABORT_CHOICES = {"إلغاء", "Cancel", "لا", "no", "No"}
BACK_CHOICES = {"رجوع", "Back", "لا", "إلغاء", "Cancel", "no", "No"}
INQUIRY_BOOK_CHOICES = {"حجز معه", "Book with doctor", "نعم", "Yes", "yes"}
NO_SLOTS_RETRY_CHOICES = {
    "طبيب آخر",
    "بالتخصص",
    "By specialty",
    "Another doctor",
}
NO_SLOTS_HANDOVER_CHOICES = {"موظف استقبال", "Talk to reception"}
CONFIRM_CANCEL_CHOICES = {
    "تأكيد الإلغاء",
    "Confirm cancel",
    "تأكيد",
    "نعم",
    "Confirm",
    "Yes",
    "yes",
}
RESCHEDULE_CHANGE_TIME = {
    "تغيير الوقت",
    "تعديل الوقت",
    "Change time",
}
RESCHEDULE_CHANGE_DAY = {
    "تغيير اليوم",
    "تعديل اليوم",
    "Change day",
}
RESCHEDULE_CHANGE_DOCTOR = {
    "تغيير الطبيب",
    "تعديل الطبيب",
    "Change doctor",
}
RESCHEDULE_BACK = {"رجوع", "Back"}
VOICE_CONFIRM_CHOICES = {
    "نعم صحيح",
    "نعم",
    "تأكيد",
    "Yes",
    "Confirm",
    "Yes correct",
    "yes correct",
}


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

# Arabic specialty labels → English (for English UI when DB stored Arabic text).
_SPEC_EN = {
    "قلب": "Cardiology",
    "أمراض القلب": "Cardiology",
    "اطفال": "Pediatrics",
    "أطفال": "Pediatrics",
    "طب الأطفال": "Pediatrics",
    "امراض الاطفال": "Pediatrics",
    "أمراض الأطفال": "Pediatrics",
    "عيون": "Ophthalmology",
    "أسنان": "Dentistry",
    "اسنان": "Dentistry",
    "باطنة": "Internal Medicine",
    "جهاز هضمي": "Gastroenterology",
    "جلدية": "Dermatology",
    "عظام": "Orthopedics",
    "أعصاب": "Neurology",
    "اعصاب": "Neurology",
    "أنف وأذن وحنجرة": "ENT",
    "انف واذن وحنجرة": "ENT",
    "نساء وتوليد": "Gynecology",
}

_TITLE_EN = {
    "استشاري": "Consultant",
    "أخصائي": "Specialist",
    "اخصائي": "Specialist",
    "أخصائية": "Specialist",
    "اخصائية": "Specialist",
    "أستاذ": "Professor",
    "استاذ": "Professor",
    "مقيم": "Resident",
    "طبيب عام": "General Practitioner",
}

_ARABIC_SCRIPT_RE = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
)


def has_arabic_script(text: str | None) -> bool:
    return bool(text and _ARABIC_SCRIPT_RE.search(text))


def _clean_text(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def synthesize_doctor_bio_en(
    *,
    title: str | None = None,
    specialization: str | None = None,
    department_en: str | None = None,
) -> str:
    """Build a safe English bio when ``bio_en`` is missing or mis-labeled."""
    title_en = localize_title(title, "en") or "Specialist"
    if has_arabic_script(title_en):
        title_en = "Specialist"
    spec = (
        localize_specialty(department_en, "en")
        or localize_specialty(specialization, "en")
        or "Medicine"
    )
    if has_arabic_script(spec):
        spec = "Medicine"
    return f"{title_en} in {spec}"


def synthesize_doctor_bio_ar(
    *,
    title: str | None = None,
    specialization: str | None = None,
    department_ar: str | None = None,
) -> str:
    """Build a safe Arabic bio when ``bio`` is missing or mis-labeled."""
    title_ar = localize_title(title, "ar") or "أخصائي"
    if not has_arabic_script(title_ar) and title:
        title_ar = localize_title(title, "ar") or "أخصائي"
    spec = (
        localize_specialty(department_ar, "ar")
        or localize_specialty(specialization, "ar")
        or "الطب"
    )
    return f"{title_ar} — {spec}"


def normalize_doctor_bilingual_fields(
    doctor_or_dict: Any | None = None,
    *,
    name_en: str | None = None,
    name_ar: str | None = None,
    bio: str | None = None,
    bio_en: str | None = None,
    title: str | None = None,
    specialization: str | None = None,
    department_en: str | None = None,
    department_ar: str | None = None,
) -> dict[str, str | None]:
    """Repair mixed/missing EN/AR doctor fields before display or save.

    Handles common production issues (local DB fixed, cloud DB still dirty):
    - Arabic text stored in ``bio_en`` / ``name_en``
    - English text stored in ``bio`` / ``name_ar``
    - Missing ``bio_en`` or ``bio`` → synthesize from title/specialty
    """
    if doctor_or_dict is not None and name_en is None and name_ar is None:
        if isinstance(doctor_or_dict, dict):
            name_en = doctor_or_dict.get("name_en")
            name_ar = doctor_or_dict.get("name_ar")
            bio = doctor_or_dict.get("bio") if bio is None else bio
            bio_en = doctor_or_dict.get("bio_en") if bio_en is None else bio_en
            title = doctor_or_dict.get("title") if title is None else title
            specialization = (
                doctor_or_dict.get("specialization")
                if specialization is None
                else specialization
            )
            department_en = (
                doctor_or_dict.get("department_en")
                if department_en is None
                else department_en
            )
            department_ar = (
                doctor_or_dict.get("department_ar")
                if department_ar is None
                else department_ar
            )
        else:
            name_en = getattr(doctor_or_dict, "name_en", None)
            name_ar = getattr(doctor_or_dict, "name_ar", None)
            bio = getattr(doctor_or_dict, "bio", None) if bio is None else bio
            bio_en = getattr(doctor_or_dict, "bio_en", None) if bio_en is None else bio_en
            title = getattr(doctor_or_dict, "title", None) if title is None else title
            specialization = (
                getattr(doctor_or_dict, "specialization", None)
                if specialization is None
                else specialization
            )
            dept = getattr(doctor_or_dict, "department", None)
            if department_en is None:
                department_en = getattr(dept, "name_en", None) if dept else None
            if department_ar is None:
                department_ar = getattr(dept, "name_ar", None) if dept else None

    name_en_s = _clean_text(name_en)
    name_ar_s = _clean_text(name_ar)
    bio_ar_s = _clean_text(bio)
    bio_en_s = _clean_text(bio_en)

    # Swap mis-labeled names.
    if name_en_s and has_arabic_script(name_en_s) and not name_ar_s:
        name_ar_s, name_en_s = name_en_s, None
    if name_ar_s and not has_arabic_script(name_ar_s) and not name_en_s:
        name_en_s, name_ar_s = name_ar_s, None
    if name_en_s and has_arabic_script(name_en_s):
        # Keep Arabic name if AR empty; never use Arabic as EN.
        if not name_ar_s:
            name_ar_s = name_en_s
        name_en_s = None

    # Swap mis-labeled bios.
    if bio_en_s and has_arabic_script(bio_en_s):
        if not bio_ar_s:
            bio_ar_s = bio_en_s
        bio_en_s = None
    if bio_ar_s and not has_arabic_script(bio_ar_s):
        if not bio_en_s:
            bio_en_s = bio_ar_s
        bio_ar_s = None

    if not bio_en_s:
        bio_en_s = synthesize_doctor_bio_en(
            title=title,
            specialization=specialization,
            department_en=department_en,
        )
    if not bio_ar_s:
        bio_ar_s = synthesize_doctor_bio_ar(
            title=title,
            specialization=specialization,
            department_ar=department_ar,
        )

    return {
        "name_en": name_en_s,
        "name_ar": name_ar_s,
        "bio": bio_ar_s,
        "bio_en": bio_en_s,
        "title": _clean_text(title),
        "specialization": _clean_text(specialization),
        "department_en": _clean_text(department_en),
        "department_ar": _clean_text(department_ar),
    }


def pick_bilingual_field(
    *,
    en: str | None,
    ar: str | None,
    lang: Any,
    allow_cross_script: bool = False,
    fallback: str | None = None,
) -> str | None:
    """Pick EN/AR display text for the conversation language.

    Never leak the other script unless ``allow_cross_script`` is True
    (e.g. rare name-only fallback). Bios and free-text profiles must keep
    this False so English WhatsApp cards never show Arabic blurbs.
    """
    en_s = (en or "").strip() or None
    ar_s = (ar or "").strip() or None
    # Treat mis-labeled columns (Arabic text stored in bio_en, etc.) as empty.
    if en_s and has_arabic_script(en_s):
        en_s = None
    if ar_s and not has_arabic_script(ar_s) and not allow_cross_script:
        # Latin-only text in the Arabic column is usable as English fallback,
        # but not as Arabic body copy when we want script purity for bios.
        pass
    if is_english(lang):
        if en_s:
            return en_s
        if ar_s and (allow_cross_script or not has_arabic_script(ar_s)):
            return ar_s
        return fallback
    if ar_s and has_arabic_script(ar_s):
        return ar_s
    if ar_s and allow_cross_script:
        return ar_s
    if en_s and (allow_cross_script or has_arabic_script(en_s)):
        return en_s
    return fallback


# Generic rank-only titles — redundant next to specialty/bio on doctor cards.
_GENERIC_TITLES = {
    "specialist",
    "أخصائي",
    "اخصائي",
    "أخصائية",
    "اخصائية",
}


def localize_title(title: str | None, lang: Any) -> str | None:
    if not title:
        return title
    raw = title.strip()
    if raw.lower() in _GENERIC_TITLES or raw in _GENERIC_TITLES:
        return None
    if is_english(lang):
        if has_arabic_script(raw):
            return _TITLE_EN.get(raw) or _TITLE_EN.get(raw.replace("أ", "ا"))
        return raw
    mapped = _TITLE_AR.get(raw.lower())
    return mapped or raw


def localize_specialty(spec: str | None, lang: Any) -> str | None:
    if not spec:
        return spec
    raw = spec.strip()
    if is_english(lang):
        if not has_arabic_script(raw):
            return raw
        # Exact / common Arabic specialty → English.
        mapped = _SPEC_EN.get(raw) or _SPEC_EN.get(raw.replace("أ", "ا"))
        if mapped:
            return mapped
        for ar_label, en_label in _SPEC_EN.items():
            if ar_label and ar_label in raw:
                return en_label
        return None
    mapped = _SPEC_AR.get(raw.lower())
    return mapped or raw


def doctor_display_name(doctor_or_dict: Any, lang: Any) -> str:
    if isinstance(doctor_or_dict, dict):
        name_ar = doctor_or_dict.get("name_ar")
        name_en = doctor_or_dict.get("name_en")
        doctor_id = doctor_or_dict.get("doctor_id", "?")
    else:
        name_ar = getattr(doctor_or_dict, "name_ar", None)
        name_en = getattr(doctor_or_dict, "name_en", None)
        doctor_id = getattr(doctor_or_dict, "doctor_id", "?")
    # Prefer matching language; do not show Arabic names on English UI when
    # name_en is missing (fallback id label instead of mixed-language cards).
    picked = pick_bilingual_field(
        en=name_en,
        ar=name_ar,
        lang=lang,
        allow_cross_script=False,
        fallback=None,
    )
    if picked:
        return picked
    # Last resort: other language name only if we have nothing else.
    other = (name_en or name_ar or "").strip()
    return other or f"Doctor {doctor_id}"


def doctor_display_fields(doctor_or_dict: Any, lang: Any) -> dict[str, str | None]:
    """Pick AR/EN name/bio fields + localize title/specialty without duplicating DB rows.

    Specialty on cards follows the doctor's department (booking specialty filter),
    not a stale free-text specialization that may disagree with department_id.
    Always normalizes bilingual fields so cloud DBs with missing/mis-labeled
    ``bio_en`` / ``name_en`` still render clean single-language cards.
    """
    normalized = normalize_doctor_bilingual_fields(doctor_or_dict)
    title = normalized.get("title")
    spec = normalized.get("specialization")
    dept_ar = normalized.get("department_ar")
    dept_en = normalized.get("department_en")
    bio_ar = normalized.get("bio")
    bio_en = normalized.get("bio_en")

    if isinstance(doctor_or_dict, dict):
        photo = doctor_or_dict.get("photo_url")
        doctor_id = doctor_or_dict.get("doctor_id")
    else:
        photo = getattr(doctor_or_dict, "photo_url", None)
        doctor_id = getattr(doctor_or_dict, "doctor_id", None)

    if is_english(lang):
        specialty_candidates = (dept_en, spec, dept_ar)
    else:
        specialty_candidates = (dept_ar, spec, dept_en)

    specialty = None
    for candidate in specialty_candidates:
        specialty = localize_specialty(candidate, lang) if candidate else None
        if specialty:
            break

    # Never fall back across scripts for bios (root cause of EN cards + AR text).
    bio = pick_bilingual_field(en=bio_en, ar=bio_ar, lang=lang, allow_cross_script=False)

    # Build a temporary object for name picking from normalized fields.
    name_source = {
        "name_en": normalized.get("name_en"),
        "name_ar": normalized.get("name_ar"),
        "doctor_id": doctor_id,
    }

    return {
        "doctor_id": doctor_id,
        "name": doctor_display_name(name_source, lang),
        "title": localize_title(title, lang),
        "specialization": specialty,
        "bio": bio,
        "photo_url": photo,
    }


def _text_ok_for_lang(text: str | None, lang: Any) -> bool:
    """True when text is empty or matches the conversation script."""
    if not (text or "").strip():
        return False
    if is_english(lang):
        return not has_arabic_script(text)
    # Arabic UI: allow Latin specialty/title codes; block only if we'd rather
    # have localized content — bios are filtered separately.
    return True


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
    if title and _text_ok_for_lang(title, lang):
        lines.append(title)
    if specialization and _text_ok_for_lang(specialization, lang):
        label = "Specialty:" if is_english(lang) else "التخصص:"
        lines.append(f"{label} {specialization}")
    if profile and _text_ok_for_lang(profile, lang):
        # Extra guard: never put English-only bio on Arabic cards either.
        if is_english(lang) or has_arabic_script(profile):
            lines.append(profile)
    if location and _text_ok_for_lang(location, lang):
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


# ---------------------------------------------------------------------------
# Flow prompts / labels (single source of truth for conversation_engine)
# ---------------------------------------------------------------------------


def session_expired(lang: Any) -> str:
    if is_english(lang):
        return "Your booking session expired. Starting over from the menu."
    return "انتهت جلسة الحجز. نبدأ من جديد من القائمة."


def ask_dob(lang: Any) -> str:
    if is_english(lang):
        return "Please enter date of birth (YYYY-MM-DD):"
    return "برجاء إدخال تاريخ الميلاد (YYYY-MM-DD):"


def invalid_dob(lang: Any) -> str:
    if is_english(lang):
        return "Invalid date. Use YYYY-MM-DD."
    return "صيغة غير صحيحة. استخدم YYYY-MM-DD."


def complete_profile_name(lang: Any) -> str:
    if is_english(lang):
        return (
            "Please enter your full name (at least three names) to complete your profile."
        )
    return "برجاء إدخال اسمك الثلاثي لإكمال ملفك."


def no_upcoming_to_reschedule(lang: Any) -> str:
    if is_english(lang):
        return "You have no upcoming confirmed appointments to reschedule."
    return "لا يوجد لديك مواعيد مؤكدة قادمة للتعديل."


def no_upcoming_to_cancel(lang: Any) -> str:
    if is_english(lang):
        return "You have no upcoming confirmed appointments to cancel."
    return "لا يوجد لديك مواعيد مؤكدة قادمة للإلغاء."


def pick_appointment_to_reschedule(lang: Any) -> str:
    if is_english(lang):
        return "Choose the appointment to reschedule (or type the appointment ref):"
    return "اختر الموعد الذي تريد تعديله (أو اكتب رقم الموعد):"


def pick_appointment_to_cancel(lang: Any) -> str:
    if is_english(lang):
        return "Choose the appointment to cancel, or type the appointment ref:"
    return "اختر الموعد للإلغاء، أو اكتب رقم الموعد:"


def pick_appointment_or_ref(lang: Any) -> str:
    if is_english(lang):
        return "Choose an appointment from the list, or type the appointment ref."
    return "اختر الموعد من القائمة أو اكتب رقم الموعد."


def your_appointments_label(lang: Any) -> str:
    return "Yours" if is_english(lang) else "مواعيدك"


def appointments_section(lang: Any) -> str:
    return "Appointments" if is_english(lang) else "المواعيد"


def doctor_not_found(lang: Any) -> str:
    if is_english(lang):
        return "Could not find the selected doctor."
    return "تعذر العثور على الطبيب المختار."


def inquiry_book_question(lang: Any) -> str:
    if is_english(lang):
        return "Would you like to book with this doctor?"
    return "هل تريد الحجز مع هذا الطبيب؟"


def inquiry_book_buttons(lang: Any) -> list[str]:
    if is_english(lang):
        return ["Book with doctor", "Menu"]
    return ["حجز معه", "القائمة"]


def specialty_label(lang: Any) -> str:
    return "Specialty" if is_english(lang) else "التخصص"


def no_slots_for_doctor(lang: Any) -> str:
    if is_english(lang):
        return "No available appointments for this doctor right now. Choose an option:"
    return "لا توجد مواعيد متاحة لهذا الطبيب حالياً. اختر خياراً:"


def no_slots_alt_buttons(lang: Any) -> list[str]:
    if is_english(lang):
        return ["Another doctor", "Talk to reception", "Menu"]
    return ["طبيب آخر", "موظف استقبال", "القائمة"]


def no_doctors_available(lang: Any) -> str:
    if is_english(lang):
        return "No doctors available right now."
    return "لا يوجد أطباء متاحون حالياً."


def no_doctors_for_option(lang: Any) -> str:
    if is_english(lang):
        return "No doctors available for this option right now."
    return "لا يوجد أطباء متاحون لهذا الخيار حالياً."


def no_doctors_alt_buttons(lang: Any) -> list[str]:
    if is_english(lang):
        return ["By specialty", "Talk to reception", "Menu"]
    return ["بالتخصص", "موظف استقبال", "القائمة"]


def no_departments(lang: Any) -> str:
    if is_english(lang):
        return "No specialties are available right now."
    return "لا توجد تخصصات متاحة حالياً."


def no_departments_buttons(lang: Any) -> list[str]:
    if is_english(lang):
        return ["Talk to reception", "Menu"]
    return ["موظف استقبال", "القائمة"]


def choose_specialty(lang: Any) -> str:
    return "Choose a specialty:" if is_english(lang) else "اختر التخصص:"


def specialties_label(lang: Any) -> str:
    return "Specialties" if is_english(lang) else "التخصصات"


def choose_day(lang: Any) -> str:
    return "Choose a suitable day:" if is_english(lang) else "اختر اليوم المناسب:"


def choose_new_day(lang: Any) -> str:
    if is_english(lang):
        return "Choose the new appointment day:"
    return "اختر اليوم الجديد للموعد:"


def choose_same_day_time(lang: Any, date_label: str) -> str:
    if is_english(lang):
        return f"Same day ({date_label}). Choose a new time:"
    return f"نفس اليوم ({date_label}). اختر وقتاً جديداً:"


def no_other_times_same_day(lang: Any) -> str:
    if is_english(lang):
        return (
            "No other times available on this day for this doctor. "
            "Try changing the day, or type MENU."
        )
    return (
        "لا توجد أوقات أخرى في نفس اليوم مع هذا الطبيب. "
        "جرّبي تعديل اليوم، أو اكتب MENU."
    )


def days_button_label(lang: Any) -> str:
    return "Days" if is_english(lang) else "الأيام"


def dates_section_title(lang: Any) -> str:
    return "Dates" if is_english(lang) else "التواريخ"


def times_button_label(lang: Any) -> str:
    return "Times" if is_english(lang) else "الأوقات"


def slots_section_title(lang: Any) -> str:
    return "Slots" if is_english(lang) else "المواعيد"


def change_day_row_title(lang: Any) -> str:
    """List row shown under the time slots to jump back and pick another day."""
    return "Change the day" if is_english(lang) else "تغيير اليوم"


def change_day_section_title(lang: Any) -> str:
    return "Options" if is_english(lang) else "خيارات"


def voice_specialty_open_doctors(lang: Any, dept_name: str) -> str:
    """Voice fastpath transition when jumping to a specialty's doctor list."""
    if is_english(lang):
        return f"Sure — {dept_name}. Opening the list of doctors:"
    return f"حسناً — تخصص {dept_name}. افتح قائمة الأطباء:"


def voice_continue_with_doctor(lang: Any, doctor_name: str) -> str:
    """Voice fastpath transition when continuing a booking with a chosen doctor."""
    if is_english(lang):
        return f"Sure — continuing your booking with {doctor_name}."
    return f"حسناً — متابعة الحجز مع {doctor_name}."


def no_slots_on_day(lang: Any) -> str:
    if is_english(lang):
        return "No times on that day. Please choose another day."
    return "لا توجد أوقات في هذا اليوم. اختر يوماً آخر."


def choose_slot_on_date(lang: Any, date_label: str) -> str:
    if is_english(lang):
        return f"Choose a 30-min slot on {date_label}:"
    return f"اختر موعداً لمدة 30 دقيقة بتاريخ {date_label}:"


def choose_new_time_on_date(lang: Any, date_label: str) -> str:
    if is_english(lang):
        return f"Choose the new time on {date_label}:"
    return f"اختر الوقت الجديد بتاريخ {date_label}:"


def choose_time_from_list(lang: Any) -> str:
    if is_english(lang):
        return "Please choose a time from the list."
    return "اختر الوقت من القائمة."


def voice_resend(lang: Any) -> str:
    if is_english(lang):
        return "Please resend your request as text or voice."
    return "أعد إرسال الطلب نصاً أو صوتياً."


def voice_retry_clear(lang: Any) -> str:
    if is_english(lang):
        return "OK — please type or record your request clearly."
    return "حسناً، أعد كتابة أو تسجيل طلبك بوضوح."


def booking_process_cancelled(lang: Any) -> str:
    return "Booking cancelled." if is_english(lang) else "تم إلغاء عملية الحجز."


def confirm_booking_hint(lang: Any) -> str:
    if is_english(lang):
        return "To confirm, tap Confirm or Cancel."
    return "لتأكيد الحجز اضغط تأكيد أو إلغاء."


def confirm_buttons(lang: Any) -> list[str]:
    return ["Confirm", "Cancel"] if is_english(lang) else ["تأكيد", "إلغاء"]


def keep_appointment_unchanged(lang: Any) -> str:
    if is_english(lang):
        return "Keeping your current appointment with no changes."
    return "تم الإبقاء على الموعد الحالي بدون تعديل."


def choose_new_doctor(lang: Any) -> str:
    if is_english(lang):
        return "Choose the new doctor:"
    return "اختر الطبيب الجديد:"


def no_alternative_slots(lang: Any) -> str:
    if is_english(lang):
        return "No alternative slots available. Your current appointment is unchanged."
    return "لا توجد مواعيد بديلة. بقي موعدك الحالي كما هو."


def reschedule_process_cancelled(lang: Any) -> str:
    if is_english(lang):
        return "Reschedule cancelled. Your appointment is unchanged."
    return "تم إلغاء عملية التعديل. موعدك الحالي كما هو."


def confirm_reschedule_hint(lang: Any) -> str:
    if is_english(lang):
        return "To confirm the change, tap Confirm or Cancel."
    return "لتأكيد التعديل اضغط تأكيد أو إلغاء."


def keep_appointment_no_cancel(lang: Any) -> str:
    if is_english(lang):
        return "Appointment kept — not cancelled."
    return "تم إبقاء الموعد بدون إلغاء."


def confirm_cancel_hint(lang: Any) -> str:
    if is_english(lang):
        return "Confirm cancel, or go back."
    return "أكد الإلغاء أو ارجع للقائمة."


def cancel_confirm_buttons(lang: Any) -> list[str]:
    if is_english(lang):
        return ["Confirm cancel", "Back"]
    return ["تأكيد الإلغاء", "رجوع"]


def post_cancel_buttons(lang: Any) -> list[str]:
    if is_english(lang):
        return ["Book again", "Menu"]
    return ["حجز موعد جديد", "القائمة"]


def handover_already_open(lang: Any) -> str:
    if is_english(lang):
        return "Your request is with reception. Type MENU to return to the menu."
    return "طلبك مسجّل لدى الاستقبال. اكتب MENU للعودة للقائمة."


def reschedule_change_buttons(lang: Any) -> list[str]:
    if is_english(lang):
        return ["Change time", "Change day", "Change doctor"]
    return ["تعديل الوقت", "تعديل اليوم", "تغيير الطبيب"]


def current_appointment_change_prompt(
    lang: Any,
    *,
    appointment_ref: str | None = None,
    doctor_name: str | None,
    date_label: str,
    time_label: str,
) -> str:
    _ = appointment_ref  # kept for callers; ref intentionally omitted from UI
    if is_english(lang):
        return (
            "Your current appointment:\n"
            f"- Doctor: {doctor_name or ''}\n"
            f"- Date: {date_label}\n"
            f"- Time: {time_label}\n\n"
            "What would you like to change?"
        )
    return (
        "موعدك الحالي:\n"
        f"- الطبيب: {doctor_name or ''}\n"
        f"- التاريخ: {date_label}\n"
        f"- الوقت: {time_label}\n\n"
        "ماذا تريد تغييره؟"
    )


def duplicate_appointment_note(lang: Any, *, ref: str, when: str) -> str:
    if is_english(lang):
        return (
            f"\n⚠️ You already have an appointment with this doctor soon "
            f"({ref} on {when}). Continue only if intentional.\n"
        )
    return (
        f"\n⚠️ لديك بالفعل موعد قريب مع نفس الطبيب "
        f"({ref} بتاريخ {when}). تابع فقط إذا كان مقصوداً.\n"
    )


def booking_summary(
    lang: Any,
    *,
    patient_name: str | None,
    phone: str,
    doctor_name: str | None,
    specialization: str | None,
    date_label: str,
    time_label: str,
    location: str,
    dup_note: str = "",
) -> str:
    loc_lines = location_message_lines(lang, location)
    if is_english(lang):
        return (
            "Booking summary:\n"
            f"- Name: {patient_name or ''}\n"
            f"- Phone: {phone}\n"
            f"- Doctor: {doctor_name or ''}\n"
            f"- Specialty: {specialization or ''}\n"
            f"- Date: {date_label}\n"
            f"- Time: {time_label}\n"
            f"- {loc_lines}\n"
            f"{dup_note}\n"
            "Confirm this booking?"
        )
    return (
        "ملخص الحجز:\n"
        f"- الاسم: {patient_name or ''}\n"
        f"- الهاتف: {phone}\n"
        f"- الطبيب: {doctor_name or ''}\n"
        f"- التخصص: {specialization or ''}\n"
        f"- التاريخ: {date_label}\n"
        f"- الوقت: {time_label}\n"
        f"- {loc_lines}\n"
        f"{dup_note}\n"
        "هل تريد تأكيد الحجز؟"
    )


def reschedule_summary(
    lang: Any,
    *,
    appointment_ref: str | None,
    doctor_name: str | None,
    date_label: str,
    time_label: str,
    location: str,
) -> str:
    """Pre-confirm reschedule message: new data only (no old→new compare)."""
    loc_lines = location_message_lines(lang, location)
    ref = (appointment_ref or "").strip()
    if is_english(lang):
        lines = ["Update summary:"]
        if ref:
            lines.append(f"- Ref: {ref}")
        lines.extend(
            [
                f"- Doctor: {doctor_name or ''}",
                f"- Date: {date_label}",
                f"- Time: {time_label}",
                f"- {loc_lines}",
                "",
                "Confirm this update?",
            ]
        )
        return "\n".join(lines)
    lines = ["ملخص التعديل:"]
    if ref:
        lines.append(f"- رقم الموعد: {ref}")
    lines.extend(
        [
            f"- الطبيب: {doctor_name or ''}",
            f"- التاريخ: {date_label}",
            f"- الوقت: {time_label}",
            f"- {loc_lines}",
            "",
            "هل تريد تأكيد التعديل؟",
        ]
    )
    return "\n".join(lines)


def reschedule_compare_summary(
    lang: Any,
    *,
    old_doctor: str | None = None,
    new_doctor: str | None = None,
    old_date: str = "",
    new_date: str = "",
    old_time: str = "",
    new_time: str = "",
    location: str = "",
    appointment_ref: str | None = None,
) -> str:
    """Backward-compatible alias → new-data-only summary."""
    return reschedule_summary(
        lang,
        appointment_ref=appointment_ref,
        doctor_name=new_doctor or old_doctor,
        date_label=new_date or old_date,
        time_label=new_time or old_time,
        location=location,
    )


def cancel_summary(
    lang: Any,
    *,
    appointment_ref: str,
    doctor_name: str | None,
    date_label: str,
    time_label: str,
) -> str:
    if is_english(lang):
        return (
            "Confirm cancellation:\n"
            f"- Ref: {appointment_ref}\n"
            f"- Doctor: {doctor_name or ''}\n"
            f"- Date: {date_label}\n"
            f"- Time: {time_label}\n\n"
            "Confirm cancel?"
        )
    return (
        "تأكيد إلغاء الموعد:\n"
        f"- رقم الموعد: {appointment_ref}\n"
        f"- الطبيب: {doctor_name or ''}\n"
        f"- التاريخ: {date_label}\n"
        f"- الوقت: {time_label}\n\n"
        "هل تريد تأكيد الإلغاء؟"
    )


def booking_error(lang: Any, detail: str) -> str:
    return localize_service_error(lang, detail)


def reschedule_error(lang: Any, detail: str) -> str:
    return localize_service_error(lang, detail)


def hold_error(lang: Any, detail: str) -> str:
    return localize_service_error(lang, detail)


def cancel_error(lang: Any, detail: str) -> str:
    return localize_service_error(lang, detail)


def localize_service_error(lang: Any, detail: Any) -> str:
    """Map internal English BookingError text to a single-language user message."""
    raw = str(detail or "").strip()
    en = is_english(lang)

    # Dynamic: lead-time policy
    m = re.match(
        r"Appointment must be at least\s+(\d+)\s+hours?\s+from now",
        raw,
        flags=re.IGNORECASE,
    )
    if m or raw.lower().startswith("appointment must be at least"):
        hours = m.group(1) if m else str(MIN_LEAD_HOURS)
        if en:
            return (
                f"Sorry — appointments must be at least {hours} hours from now. "
                "Please choose a later time."
            )
        return (
            f"عذراً — يجب أن يكون الموعد بعد {hours} ساعة على الأقل من الآن. "
            "برجاء اختيار وقت لاحق."
        )

    # Exact / prefix matches (internal English codes from booking_service)
    table: dict[str, tuple[str, str]] = {
        "slot hold expired": (
            "انتهت مدة حجز الوقت المؤقت. برجاء اختيار موعد من جديد.",
            "The temporary hold on this time expired. Please choose a slot again.",
        ),
        "slot is held by another patient": (
            "هذا الموعد محجوز مؤقتاً لمريض آخر. اختر وقتاً آخر.",
            "This time is temporarily held by another patient. Please choose another.",
        ),
        "slot is not available": (
            "هذا الموعد لم يعد متاحاً. اختر وقتاً آخر.",
            "This time is no longer available. Please choose another.",
        ),
        "slot not found": (
            "تعذر العثور على الموعد المختار. برجاء المحاولة من القائمة.",
            "Could not find the selected time. Please try again from the list.",
        ),
        "slot not found for this doctor": (
            "تعذر العثور على الموعد لهذا الطبيب. برجاء المحاولة مرة أخرى.",
            "Could not find that time for this doctor. Please try again.",
        ),
        "doctor not found": (
            "تعذر العثور على الطبيب المختار.",
            "Could not find the selected doctor.",
        ),
        "appointment not found": (
            "تعذر العثور على الموعد.",
            "Appointment not found.",
        ),
        "only confirmed appointments can be rescheduled": (
            "يمكن تعديل المواعيد المؤكدة فقط.",
            "Only confirmed appointments can be rescheduled.",
        ),
        "only confirmed appointments can be cancelled": (
            "يمكن إلغاء المواعيد المؤكدة فقط.",
            "Only confirmed appointments can be cancelled.",
        ),
        "appointment does not belong to this phone": (
            "هذا الموعد غير مرتبط برقمك.",
            "This appointment is not linked to your phone number.",
        ),
        "new slot not found": (
            "تعذر العثور على الموعد الجديد.",
            "The new time slot was not found.",
        ),
        "only confirmed appointments can be marked no-show": (
            "يمكن تعليم المواعيد المؤكدة فقط كعدم حضور.",
            "Only confirmed appointments can be marked no-show.",
        ),
        "cannot mark no-show before appointment time": (
            "لا يمكن تعليم عدم الحضور قبل موعد الموعد.",
            "Cannot mark no-show before the appointment time.",
        ),
    }

    low = raw.lower()
    if low.startswith("slot is not available (status="):
        ar, eng = table["slot is not available"]
        return eng if en else ar

    for key, (ar, eng) in table.items():
        if low == key or low.startswith(key):
            return eng if en else ar

    # Unknown internal error — never leak English to Arabic users.
    if en:
        return raw or "Something went wrong. Please try again or type MENU."
    return "حدث خطأ. برجاء المحاولة مرة أخرى أو اكتب MENU."


def doctor_flow_prompt(lang: Any) -> str:
    if is_english(lang):
        return "Open the screen to swipe doctor photos, then pick a doctor."
    return "افتح الشاشة لتمرير صور الأطباء يمين ويسار، ثم اختر الطبيب من القائمة."


def webhook_no_doctor_selected(lang: Any) -> str:
    if is_english(lang):
        return "No doctor was selected. Please try again from the menu."
    return "لم يتم اختيار طبيب. أعد المحاولة من القائمة."


def webhook_voice_receive_failed(lang: Any) -> str:
    if is_english(lang):
        return "Could not receive the voice note. Try again or type your request."
    return "تعذر استلام الملف الصوتي. أعد المحاولة أو اكتب طلبك."


def webhook_voice_transcribe_failed(lang: Any) -> str:
    if is_english(lang):
        return "Could not transcribe the voice note. Type your request or record again."
    return "فشل تحويل الصوت. اكتب طلبك نصاً أو أعد التسجيل."


def webhook_temporary_error(lang: Any) -> str:
    if is_english(lang):
        return "A temporary error occurred. We will have reception follow up with you."
    return "حصل خطأ مؤقت. نحجز لك متابعة مع الاستقبال."


def webhook_voice_unclear(lang: Any) -> str:
    if is_english(lang):
        return "I didn't catch the voice note clearly. Please record again or type your request."
    return "لم أفهم الرسالة الصوتية بوضوح. أعد التسجيل أو اكتب طلبك نصاً."


def not_understood_menu(lang: Any) -> str:
    """Short acknowledgment shown just before the main menu when idle input
    couldn't be understood, so the menu doesn't appear to pop up at random."""
    if is_english(lang):
        return "Sorry, I didn't quite catch that. Here's what I can help with:"
    return "معلش، مفهمتش قصدك بالظبط. دي الخدمات اللي أقدر أساعدك فيها:"


def stale_option_hint(lang: Any) -> str:
    """Nudge for a leftover button/list tap that no longer fits the current
    step — a gentle one-liner instead of re-dumping the whole menu."""
    if is_english(lang):
        return "That option isn't active anymore. Please pick from the latest message, or type MENU."
    return "هذا الاختيار لم يعد متاحاً. اختر من آخر رسالة، أو اكتب MENU."


def webhook_voice_unclear_slot(lang: Any) -> str:
    if is_english(lang):
        return (
            "I didn't catch the time you wanted — "
            "please say the hour again, or pick from the list."
        )
    return "لم أفهم الوقت المطلوب — ممكن تقول الساعة تاني، أو تختار من القائمة؟"


def webhook_voice_unclear_doctor(lang: Any) -> str:
    if is_english(lang):
        return (
            "I didn't recognize the doctor's name — "
            "try again, or choose from the list."
        )
    return "لم أتعرف على اسم الدكتور — جرب تاني أو اختر من القائمة."


def webhook_voice_unclear_date(lang: Any) -> str:
    if is_english(lang):
        return (
            "I didn't catch the day you wanted — "
            "please say the day again, or pick from the list."
        )
    return "لم أفهم اليوم المطلوب — ممكن تقول اليوم تاني، أو تختار من القائمة؟"


def webhook_voice_unclear_department(lang: Any) -> str:
    if is_english(lang):
        return (
            "I didn't catch the specialty — "
            "please say it again, or choose from the list."
        )
    return "لم أفهم التخصص المطلوب — ممكن تعيده تاني، أو تختار من القائمة؟"


def webhook_voice_confirm_prompt(lang: Any, transcript: str) -> str:
    if is_english(lang):
        return (
            f"I understood your request as:\n«{transcript}»\n"
            "Is this correct? (Final booking still needs confirmation later.)"
        )
    return (
        f"فهمت طلبك كالتالي:\n«{transcript}»\n"
        "هل هذا صحيح؟ (لن أحجز قبل التأكيد النهائي لاحقاً)"
    )


def webhook_voice_confirm_buttons(lang: Any) -> list[str]:
    if is_english(lang):
        return ["Yes correct", "Retry"]
    return ["نعم صحيح", "إعادة"]


def option_number_description(lang: Any, n: int) -> str:
    if is_english(lang):
        return f"Option {n}"
    return f"خيار رقم {n}"


def handover_in_hours(lang: Any, clinic_name: str | None = None) -> str:
    name = clinic_name_for_lang(lang, clinic_name)
    if is_english(lang):
        return (
            f"You will be connected to reception at {name}. "
            "Someone will contact you shortly. Thank you for your patience."
        )
    return (
        f"سيتم تحويلك لموظف الاستقبال في مستشفى {name}، "
        "وسيتواصل معك قريباً. شكراً لسعة صدرك."
    )


def handover_after_hours(lang: Any, clinic_name: str | None = None) -> str:
    name = clinic_name_for_lang(lang, clinic_name)
    if is_english(lang):
        return (
            f"Your request is logged with reception at {name}. "
            "We are currently outside working hours and will contact you soon. "
            "Thank you for your patience."
        )
    return (
        f"تم تسجيل طلبك لدى استقبال مستشفى {name}. "
        "نحن خارج أوقات العمل حالياً، وسنتواصل معك في أقرب وقت. "
        "شكراً لسعة صدرك."
    )
