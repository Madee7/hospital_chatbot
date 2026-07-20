"""Arabic/English sample messages per product section 10.x."""

from __future__ import annotations

from app.core.config import CLINIC_DISPLAY_NAME, CLINIC_LOCATION_AR


def main_menu_ar(clinic_name: str | None = None) -> str:
    name = clinic_name or CLINIC_DISPLAY_NAME
    return (
        f"أهلاً بك في {name}. كيف يمكننا مساعدتك؟\n"
        "1. حجز موعد\n"
        "2. تعديل موعد\n"
        "3. إلغاء موعد\n"
        "4. الاستفسار عن الأطباء/التخصصات\n"
        "5. التحدث مع موظف الاستقبال"
    )


def welcome_ar(clinic_name: str | None = None) -> str:
    name = clinic_name or CLINIC_DISPLAY_NAME
    return f"{name} ترحب بكم 🏥"


def booking_path_prompt_ar() -> str:
    return "هل تفضّل البحث بالتخصص أم باسم الدكتور؟"


def doctor_card_body_ar(
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
        lines.append(f"التخصص: {specialization}")
    if profile:
        lines.append(profile)
    if location:
        lines.append(f"المكان: {location}")
    return "\n".join(lines)


def confirmation_ar(
    *,
    appointment_ref: str,
    doctor_name: str,
    specialization: str | None,
    date_label: str,
    time_label: str,
    location: str | None = None,
) -> str:
    spec = f" - {specialization}" if specialization else ""
    loc = location or CLINIC_LOCATION_AR
    return (
        "تم تأكيد موعدك بنجاح.\n"
        f"رقم الموعد: {appointment_ref}\n"
        f"الطبيب: {doctor_name}{spec}\n"
        f"التاريخ: {date_label}\n"
        f"الوقت: {time_label}\n"
        f"المكان: {loc}\n"
        "سيصلك تذكير قبل الموعد. اكتب MENU في أي وقت لإدارة الموعد."
    )


def reschedule_confirmation_ar(
    *,
    appointment_ref: str,
    doctor_name: str,
    specialization: str | None,
    date_label: str,
    time_label: str,
    location: str | None = None,
) -> str:
    spec = f" - {specialization}" if specialization else ""
    loc = location or CLINIC_LOCATION_AR
    return (
        "تم تعديل موعدك بنجاح.\n"
        f"رقم الموعد: {appointment_ref}\n"
        f"الطبيب: {doctor_name}{spec}\n"
        f"التاريخ الجديد: {date_label}\n"
        f"الوقت الجديد: {time_label}\n"
        f"المكان: {loc}\n"
        "تم تحديث التذكيرات. اكتب MENU لإدارة الموعد."
    )


def cancel_confirmation_ar(
    *,
    appointment_ref: str,
    doctor_name: str,
    specialization: str | None,
    date_label: str,
    time_label: str,
) -> str:
    spec = f" - {specialization}" if specialization else ""
    return (
        "تم إلغاء موعدك بنجاح.\n"
        f"رقم الموعد: {appointment_ref}\n"
        f"الطبيب: {doctor_name}{spec}\n"
        f"كان الموعد: {date_label} الساعة {time_label}\n"
        "تم تحرير الوقت وإلغاء التذكيرات."
    )


def reminder_ar(
    *,
    appointment_ref: str,
    doctor_name: str,
    date_label: str,
    time_label: str,
    hours_label: str,
    location: str | None = None,
) -> str:
    loc = location or CLINIC_LOCATION_AR
    return (
        f"تذكير بموعدك ({hours_label}):\n"
        f"رقم الموعد: {appointment_ref}\n"
        f"الطبيب: {doctor_name}\n"
        f"التاريخ: {date_label}\n"
        f"الوقت: {time_label}\n"
        f"المكان: {loc}\n"
        "اختر إجراءً من الأزرار أو اكتب MENU."
    )


MAIN_MENU_BUTTONS = [
    "حجز موعد",
    "تعديل موعد",
    "إلغاء موعد",
]

# Extra options beyond 3 WhatsApp reply buttons → list rows
MAIN_MENU_LIST_ROWS = [
    "حجز موعد",
    "تعديل موعد",
    "إلغاء موعد",
    "الاستفسار عن الأطباء",
    "التحدث مع موظف",
]

BOOKING_PATH_BUTTONS = ["بالتخصص", "باسم الدكتور"]
