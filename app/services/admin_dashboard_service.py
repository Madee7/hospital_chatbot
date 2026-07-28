"""Admin dashboard data access: KPIs, clinic/dept/doctor CRUD, settings, usage."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from app.core import i18n_bot as i18n
from app.db.enums import AppointmentStatus, ConversationState, ReminderStatus
from app.models.admin_models import AdminUser, ConfigSetting
from app.models.appointment_models import Appointment, AppointmentHistory, AppointmentSlot
from app.models.conversation_models import Conversation, Message, VoiceMessage
from app.models.core_models import Clinic, Department
from app.models.doctor_models import (
    Doctor,
    DoctorLocation,
    DoctorUnavailability,
    DoctorWorkingHours,
)
from app.models.handover_models import HandoverCase
from app.models.reminder_models import Reminder
from app.models.usage_models import UsageLog
from app.services.booking_service import (
    BookingError,
    cancel_appointment,
    get_available_dates_and_slots,
    reschedule_appointment,
)


WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

WEEKDAYS_AR = [
    "الإثنين",
    "الثلاثاء",
    "الأربعاء",
    "الخميس",
    "الجمعة",
    "السبت",
    "الأحد",
]


def weekday_label(weekday: int, lang: str = "en") -> str:
    if 0 <= weekday <= 6:
        if (lang or "en").lower().startswith("ar"):
            return WEEKDAYS_AR[weekday]
        return WEEKDAYS[weekday]
    return str(weekday)


def list_clinics(db: Session) -> list[dict]:
    rows = db.query(Clinic).order_by(Clinic.clinic_id.asc()).all()
    return [
        {
            "clinic_id": c.clinic_id,
            "tenant_id": c.tenant_id,
            "clinic_name": c.clinic_name,
            "whatsapp_number": c.whatsapp_number,
            "timezone": c.timezone,
            "language_default": (
                c.language_default.value
                if c.language_default and hasattr(c.language_default, "value")
                else c.language_default
            ),
            "address": c.address,
            "status": c.status,
        }
        for c in rows
    ]


def get_clinic(db: Session, clinic_id: int) -> Clinic | None:
    return db.query(Clinic).filter(Clinic.clinic_id == clinic_id).one_or_none()


def update_clinic(db: Session, clinic_id: int, fields: dict[str, Any], updated_by: str = "dashboard") -> Clinic:
    clinic = get_clinic(db, clinic_id)
    if not clinic:
        raise ValueError("Clinic not found")
    for key, value in fields.items():
        if hasattr(clinic, key) and key not in {"clinic_id", "tenant_id"}:
            setattr(clinic, key, value)
    clinic.updated_by = updated_by
    db.commit()
    db.refresh(clinic)
    return clinic


def list_departments(db: Session, clinic_id: int) -> list[dict]:
    rows = (
        db.query(Department)
        .filter(Department.clinic_id == clinic_id)
        .order_by(Department.department_id.asc())
        .all()
    )
    return [
        {
            "department_id": d.department_id,
            "name_en": d.name_en,
            "name_ar": d.name_ar,
            "description": d.description,
            "active_flag": d.active_flag,
        }
        for d in rows
    ]


def upsert_department(
    db: Session,
    *,
    clinic_id: int,
    name_en: str,
    name_ar: str,
    description: str | None = None,
    active_flag: bool = True,
    department_id: int | None = None,
    updated_by: str = "dashboard",
) -> Department:
    if department_id:
        dept = (
            db.query(Department)
            .filter(Department.department_id == department_id, Department.clinic_id == clinic_id)
            .one_or_none()
        )
        if not dept:
            raise ValueError("Department not found")
    else:
        clinic = get_clinic(db, clinic_id)
        if not clinic:
            raise ValueError("Clinic not found")
        dept = Department(clinic_id=clinic_id, created_by=updated_by)
        db.add(dept)
    dept.name_en = name_en
    dept.name_ar = name_ar
    dept.description = description
    dept.active_flag = active_flag
    dept.updated_by = updated_by
    db.commit()
    db.refresh(dept)
    return dept


def list_doctors(db: Session, clinic_id: int) -> list[dict]:
    rows = (
        db.query(Doctor)
        .filter(Doctor.clinic_id == clinic_id)
        .order_by(Doctor.doctor_id.asc())
        .all()
    )
    return [
        {
            "doctor_id": d.doctor_id,
            "department_id": d.department_id,
            "name_en": d.name_en,
            "name_ar": d.name_ar,
            "title": d.title,
            "specialization": d.specialization,
            "bio": d.bio,
            "bio_en": getattr(d, "bio_en", None),
            "photo_url": d.photo_url,
            "active_flag": d.active_flag,
        }
        for d in rows
    ]


def upsert_doctor(
    db: Session,
    *,
    clinic_id: int,
    tenant_id: int,
    name_en: str,
    name_ar: str,
    title: str | None,
    specialization: str | None,
    bio: str | None,
    bio_en: str | None = None,
    photo_url: str | None,
    department_id: int | None,
    active_flag: bool = True,
    doctor_id: int | None = None,
    updated_by: str = "dashboard",
) -> Doctor:
    if not department_id:
        raise ValueError("Department is required. Create/select a department first.")
    dept = (
        db.query(Department)
        .filter(
            Department.department_id == department_id,
            Department.clinic_id == clinic_id,
        )
        .one_or_none()
    )
    if not dept:
        raise ValueError("Department not found for this clinic.")

    if doctor_id:
        doctor = (
            db.query(Doctor)
            .filter(Doctor.doctor_id == doctor_id, Doctor.clinic_id == clinic_id)
            .one_or_none()
        )
        if not doctor:
            raise ValueError("Doctor not found")
    else:
        doctor = Doctor(
            clinic_id=clinic_id,
            tenant_id=tenant_id,
            created_by=updated_by,
        )
        db.add(doctor)
    # Keep free-text specialization aligned with the department used in booking filters.
    synced_spec = (specialization or "").strip() or (dept.name_en or dept.name_ar)
    # Repair mixed/missing bilingual fields so WhatsApp cards stay single-language
    # even when cloud DBs (e.g. Supabase) have incomplete rows.
    normalized = i18n.normalize_doctor_bilingual_fields(
        name_en=name_en,
        name_ar=name_ar,
        bio=bio,
        bio_en=bio_en,
        title=title,
        specialization=synced_spec,
        department_en=dept.name_en,
        department_ar=dept.name_ar,
    )
    doctor.name_en = normalized["name_en"] or name_en
    doctor.name_ar = normalized["name_ar"] or name_ar
    doctor.title = title
    doctor.specialization = synced_spec
    doctor.bio = normalized["bio"]
    doctor.bio_en = normalized["bio_en"]
    doctor.photo_url = photo_url
    doctor.department_id = department_id
    doctor.active_flag = active_flag
    doctor.updated_by = updated_by
    db.commit()
    db.refresh(doctor)
    return doctor


def doctor_delete_impact(db: Session, clinic_id: int, doctor_id: int) -> dict[str, int]:
    doctor = (
        db.query(Doctor)
        .filter(Doctor.doctor_id == doctor_id, Doctor.clinic_id == clinic_id)
        .one_or_none()
    )
    if not doctor:
        raise ValueError("Doctor not found")
    appt_count = (
        db.query(func.count(Appointment.appointment_id))
        .filter(Appointment.doctor_id == doctor_id)
        .scalar()
        or 0
    )
    slot_count = (
        db.query(func.count(AppointmentSlot.slot_id))
        .filter(AppointmentSlot.doctor_id == doctor_id)
        .scalar()
        or 0
    )
    rem_count = (
        db.query(func.count(Reminder.reminder_id))
        .join(Appointment, Appointment.appointment_id == Reminder.appointment_id)
        .filter(Appointment.doctor_id == doctor_id)
        .scalar()
        or 0
    )
    return {
        "appointments": int(appt_count),
        "slots": int(slot_count),
        "reminders": int(rem_count),
    }


def deactivate_doctor(db: Session, clinic_id: int, doctor_id: int, updated_by: str = "dashboard") -> Doctor:
    doctor = (
        db.query(Doctor)
        .filter(Doctor.doctor_id == doctor_id, Doctor.clinic_id == clinic_id)
        .one_or_none()
    )
    if not doctor:
        raise ValueError("Doctor not found")
    doctor.active_flag = False
    doctor.updated_by = updated_by
    db.commit()
    db.refresh(doctor)
    return doctor


def delete_doctor(db: Session, clinic_id: int, doctor_id: int) -> dict[str, int]:
    """Permanently delete a doctor and related booking data."""
    doctor = (
        db.query(Doctor)
        .filter(Doctor.doctor_id == doctor_id, Doctor.clinic_id == clinic_id)
        .one_or_none()
    )
    if not doctor:
        raise ValueError("Doctor not found")

    impact = doctor_delete_impact(db, clinic_id, doctor_id)
    appt_ids = [
        a.appointment_id
        for a in db.query(Appointment.appointment_id).filter(Appointment.doctor_id == doctor_id).all()
    ]
    slot_ids = [
        s.slot_id
        for s in db.query(AppointmentSlot.slot_id).filter(AppointmentSlot.doctor_id == doctor_id).all()
    ]

    if appt_ids:
        db.query(Reminder).filter(Reminder.appointment_id.in_(appt_ids)).delete(synchronize_session=False)
        db.query(AppointmentHistory).filter(AppointmentHistory.appointment_id.in_(appt_ids)).delete(
            synchronize_session=False
        )
        db.query(Appointment).filter(Appointment.appointment_id.in_(appt_ids)).delete(
            synchronize_session=False
        )

    if slot_ids:
        db.query(AppointmentHistory).filter(
            or_(
                AppointmentHistory.old_slot_id.in_(slot_ids),
                AppointmentHistory.new_slot_id.in_(slot_ids),
            )
        ).delete(synchronize_session=False)
        db.query(AppointmentSlot).filter(AppointmentSlot.slot_id.in_(slot_ids)).delete(
            synchronize_session=False
        )

    db.query(DoctorWorkingHours).filter(DoctorWorkingHours.doctor_id == doctor_id).delete(
        synchronize_session=False
    )
    db.query(DoctorUnavailability).filter(DoctorUnavailability.doctor_id == doctor_id).delete(
        synchronize_session=False
    )
    db.query(DoctorLocation).filter(DoctorLocation.doctor_id == doctor_id).delete(
        synchronize_session=False
    )
    db.query(Doctor).filter(Doctor.doctor_id == doctor_id).delete(synchronize_session=False)
    db.flush()
    resequence_doctor_ids(db)
    db.commit()
    return impact


def _remap_doctor_fk(db: Session, old_id: int, new_id: int) -> None:
    """Point child rows from old_id to new_id (parent row with new_id must already exist)."""
    for model in (
        Appointment,
        AppointmentSlot,
        DoctorWorkingHours,
        DoctorUnavailability,
        DoctorLocation,
    ):
        db.query(model).filter(model.doctor_id == old_id).update(
            {model.doctor_id: new_id},
            synchronize_session=False,
        )


def resequence_doctor_ids(db: Session) -> dict[int, int]:
    """
    Close gaps in doctors.doctor_id (1..N) and rewrite FK references.
    Example after deletes: 1,2,3,4,8 -> 1,2,3,4,5
    """
    doctors = db.query(Doctor).order_by(Doctor.doctor_id.asc()).all()
    if not doctors:
        db.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('doctors', 'doctor_id'), 1, false)"
            )
        )
        return {}

    old_ids = [d.doctor_id for d in doctors]
    mapping = {old: idx for idx, old in enumerate(old_ids, start=1)}
    if all(old == new for old, new in mapping.items()):
        db.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('doctors', 'doctor_id'), "
                ":m, true)"
            ),
            {"m": len(old_ids)},
        )
        return mapping

    temp_base = 1_000_000
    # Phase 1: move every id to a free temp range (copy row → remap FKs → delete old)
    for old in old_ids:
        temp = temp_base + old
        src = db.query(Doctor).filter(Doctor.doctor_id == old).one()
        clone = Doctor(
            doctor_id=temp,
            tenant_id=src.tenant_id,
            clinic_id=src.clinic_id,
            department_id=src.department_id,
            name_en=src.name_en,
            name_ar=src.name_ar,
            title=src.title,
            specialization=src.specialization,
            bio=src.bio,
            bio_en=getattr(src, "bio_en", None),
            photo_url=src.photo_url,
            active_flag=src.active_flag,
            created_by=src.created_by,
            updated_by=src.updated_by,
        )
        db.add(clone)
        db.flush()
        _remap_doctor_fk(db, old, temp)
        db.query(Doctor).filter(Doctor.doctor_id == old).delete(synchronize_session=False)
        db.flush()

    # Phase 2: temp → sequential 1..N
    for old in old_ids:
        temp = temp_base + old
        new = mapping[old]
        src = db.query(Doctor).filter(Doctor.doctor_id == temp).one()
        clone = Doctor(
            doctor_id=new,
            tenant_id=src.tenant_id,
            clinic_id=src.clinic_id,
            department_id=src.department_id,
            name_en=src.name_en,
            name_ar=src.name_ar,
            title=src.title,
            specialization=src.specialization,
            bio=src.bio,
            bio_en=getattr(src, "bio_en", None),
            photo_url=src.photo_url,
            active_flag=src.active_flag,
            created_by=src.created_by,
            updated_by=src.updated_by,
        )
        db.add(clone)
        db.flush()
        _remap_doctor_fk(db, temp, new)
        db.query(Doctor).filter(Doctor.doctor_id == temp).delete(synchronize_session=False)
        db.flush()
        db.expire_all()

    db.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('doctors', 'doctor_id'), "
            ":m, true)"
        ),
        {"m": len(old_ids)},
    )
    db.expire_all()
    return mapping


def list_working_hours(db: Session, doctor_id: int) -> list[dict]:
    rows = (
        db.query(DoctorWorkingHours)
        .filter(DoctorWorkingHours.doctor_id == doctor_id)
        .order_by(DoctorWorkingHours.weekday.asc(), DoctorWorkingHours.start_time.asc())
        .all()
    )
    return [
        {
            "working_hours_id": w.working_hours_id,
            "weekday": w.weekday,
            "weekday_name": WEEKDAYS[w.weekday] if 0 <= w.weekday <= 6 else str(w.weekday),
            "weekday_name_ar": WEEKDAYS_AR[w.weekday] if 0 <= w.weekday <= 6 else str(w.weekday),
            "start_time": w.start_time,
            "end_time": w.end_time,
            "slot_minutes": w.slot_minutes,
            "max_bookings": w.max_bookings,
            "active_flag": w.active_flag,
        }
        for w in rows
    ]


def upsert_working_hours(
    db: Session,
    *,
    doctor_id: int,
    weekday: int,
    start_time: time,
    end_time: time,
    slot_minutes: int = 30,
    max_bookings: int = 1,
    active_flag: bool = True,
    working_hours_id: int | None = None,
) -> dict:
    """Create/update weekly hours and generate bookable slots for WhatsApp."""
    if end_time <= start_time:
        raise ValueError("end_time must be after start_time on the same day")

    wh: DoctorWorkingHours | None = None
    if working_hours_id:
        wh = (
            db.query(DoctorWorkingHours)
            .filter(DoctorWorkingHours.working_hours_id == working_hours_id)
            .one_or_none()
        )
        if not wh:
            raise ValueError("Working hours not found")
    else:
        wh = (
            db.query(DoctorWorkingHours)
            .filter(
                DoctorWorkingHours.doctor_id == doctor_id,
                DoctorWorkingHours.weekday == weekday,
            )
            .order_by(DoctorWorkingHours.working_hours_id.asc())
            .first()
        )
        if not wh:
            wh = DoctorWorkingHours(doctor_id=doctor_id)
            db.add(wh)

    wh.weekday = weekday
    wh.start_time = start_time
    wh.end_time = end_time
    wh.slot_minutes = slot_minutes
    wh.max_bookings = max_bookings
    wh.active_flag = active_flag
    db.commit()
    db.refresh(wh)

    slots_created = 0
    doctor = db.query(Doctor).filter(Doctor.doctor_id == doctor_id).one_or_none()
    if doctor and active_flag:
        from app.services.slot_service import ensure_slots_for_doctor

        created = ensure_slots_for_doctor(
            db, doctor=doctor, created_by="dashboard_working_hours"
        )
        db.commit()
        slots_created = len(created)

    return {
        "working_hours_id": wh.working_hours_id,
        "weekday": wh.weekday,
        "slots_created": slots_created,
    }


def deactivate_working_hours(db: Session, *, working_hours_id: int, doctor_id: int) -> bool:
    wh = (
        db.query(DoctorWorkingHours)
        .filter(
            DoctorWorkingHours.working_hours_id == working_hours_id,
            DoctorWorkingHours.doctor_id == doctor_id,
        )
        .one_or_none()
    )
    if not wh:
        return False
    wh.active_flag = False
    db.commit()
    return True


def list_unavailability(db: Session, doctor_id: int) -> list[dict]:
    rows = (
        db.query(DoctorUnavailability)
        .filter(DoctorUnavailability.doctor_id == doctor_id)
        .order_by(DoctorUnavailability.start_datetime.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "unavailability_id": u.unavailability_id,
            "start_datetime": u.start_datetime,
            "end_datetime": u.end_datetime,
            "reason": u.reason,
            "active_flag": u.active_flag,
        }
        for u in rows
    ]


def add_unavailability(
    db: Session,
    *,
    doctor_id: int,
    start_datetime: datetime,
    end_datetime: datetime,
    reason: str | None = None,
) -> dict:
    """Mark doctor off for a date range and block overlapping open slots."""
    if end_datetime <= start_datetime:
        raise ValueError("end_datetime must be after start_datetime")

    row = DoctorUnavailability(
        doctor_id=doctor_id,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        reason=reason,
        active_flag=True,
    )
    db.add(row)
    db.flush()

    from app.db.enums import SlotStatus

    slots = (
        db.query(AppointmentSlot)
        .filter(
            AppointmentSlot.doctor_id == doctor_id,
            AppointmentSlot.status == SlotStatus.AVAILABLE,
            AppointmentSlot.slot_start < end_datetime,
            AppointmentSlot.slot_end > start_datetime,
        )
        .all()
    )
    for slot in slots:
        slot.status = SlotStatus.BLOCKED
        slot.updated_by = "dashboard_doctor_leave"
    db.commit()
    db.refresh(row)
    return {
        "unavailability_id": row.unavailability_id,
        "slots_blocked": len(slots),
    }


def deactivate_unavailability(db: Session, *, unavailability_id: int) -> bool:
    row = (
        db.query(DoctorUnavailability)
        .filter(DoctorUnavailability.unavailability_id == unavailability_id)
        .one_or_none()
    )
    if not row:
        return False
    row.active_flag = False
    db.commit()
    return True


def get_config_map(db: Session, clinic_id: int) -> dict[str, str]:
    rows = db.query(ConfigSetting).filter(ConfigSetting.clinic_id == clinic_id).all()
    return {r.key: (r.value or "") for r in rows}


def set_config(
    db: Session,
    *,
    clinic_id: int,
    tenant_id: int,
    key: str,
    value: str,
    updated_by: str = "dashboard",
) -> None:
    row = (
        db.query(ConfigSetting)
        .filter(ConfigSetting.clinic_id == clinic_id, ConfigSetting.key == key)
        .one_or_none()
    )
    if not row:
        row = ConfigSetting(
            clinic_id=clinic_id,
            tenant_id=tenant_id,
            key=key,
            created_by=updated_by,
        )
        db.add(row)
    row.value = value
    row.updated_by = updated_by
    db.commit()


def authenticate_admin(db: Session, email: str, password: str, expected_password: str) -> dict | None:
    """Demo login: email must exist as AdminUser (or any email) + shared env password."""
    if not expected_password or password != expected_password:
        return None
    user = (
        db.query(AdminUser)
        .filter(AdminUser.email == email, AdminUser.active_flag == True)  # noqa: E712
        .one_or_none()
    )
    if user:
        user.last_login = datetime.utcnow()
        db.commit()
        return {
            "user_id": user.user_id,
            "email": user.email,
            "role": user.role,
            "tenant_id": user.tenant_id,
        }
    # Fallback demo admin when no AdminUser seed exists
    return {
        "user_id": 0,
        "email": email or "admin@demo.local",
        "role": "admin",
        "tenant_id": 1,
    }


def compute_kpis(db: Session, *, clinic_id: int, days: int = 30) -> dict[str, Any]:
    since = datetime.utcnow() - timedelta(days=days)

    total_conversations = (
        db.query(func.count(Conversation.conversation_id))
        .filter(Conversation.clinic_id == clinic_id, Conversation.created_at >= since)
        .scalar()
        or 0
    )

    booking_attempts = (
        db.query(func.count(Conversation.conversation_id))
        .filter(
            Conversation.clinic_id == clinic_id,
            Conversation.created_at >= since,
            Conversation.current_intent.isnot(None),
            Conversation.current_intent.ilike("%book%"),
        )
        .scalar()
        or 0
    )
    # Also count conversations that reached booking states historically via intent prefixes
    booking_attempts_extra = (
        db.query(func.count(Conversation.conversation_id))
        .filter(
            Conversation.clinic_id == clinic_id,
            Conversation.created_at >= since,
            Conversation.state.in_(
                [
                    ConversationState.BOOKING_DOCTOR,
                    ConversationState.BOOKING_DATE,
                    ConversationState.BOOKING_SLOT,
                    ConversationState.PATIENT_DETAILS,
                    ConversationState.CONFIRMING,
                ]
            ),
        )
        .scalar()
        or 0
    )
    booking_attempts = max(booking_attempts, booking_attempts_extra)

    confirmed = (
        db.query(func.count(Appointment.appointment_id))
        .filter(
            Appointment.clinic_id == clinic_id,
            Appointment.created_at >= since,
            Appointment.status.in_(
                [AppointmentStatus.CONFIRMED, AppointmentStatus.RESCHEDULED]
            ),
        )
        .scalar()
        or 0
    )
    cancelled = (
        db.query(func.count(Appointment.appointment_id))
        .filter(
            Appointment.clinic_id == clinic_id,
            Appointment.updated_at >= since,
            Appointment.status == AppointmentStatus.CANCELLED,
        )
        .scalar()
        or 0
    )
    no_shows = (
        db.query(func.count(Appointment.appointment_id))
        .filter(
            Appointment.clinic_id == clinic_id,
            Appointment.status == AppointmentStatus.NO_SHOW,
        )
        .scalar()
        or 0
    )
    rescheduled = (
        db.query(func.count(AppointmentHistory.history_id))
        .join(Appointment, Appointment.appointment_id == AppointmentHistory.appointment_id)
        .filter(
            Appointment.clinic_id == clinic_id,
            AppointmentHistory.created_at >= since,
            AppointmentHistory.reason.ilike("%reschedule%"),
        )
        .scalar()
        or 0
    )

    conversion = (confirmed / booking_attempts) if booking_attempts else 0.0

    failed_intents = (
        db.query(func.count(Conversation.conversation_id))
        .filter(
            Conversation.clinic_id == clinic_id,
            Conversation.created_at >= since,
            Conversation.current_intent.in_(["unknown", "failed", "fallback"]),
        )
        .scalar()
        or 0
    )

    top_doctors = (
        db.query(
            Doctor.name_ar,
            Doctor.name_en,
            func.count(Appointment.appointment_id).label("cnt"),
        )
        .join(Appointment, Appointment.doctor_id == Doctor.doctor_id)
        .filter(Appointment.clinic_id == clinic_id, Appointment.created_at >= since)
        .group_by(Doctor.doctor_id, Doctor.name_ar, Doctor.name_en)
        .order_by(func.count(Appointment.appointment_id).desc())
        .limit(5)
        .all()
    )

    top_specialties = (
        db.query(Doctor.specialization, func.count(Appointment.appointment_id))
        .join(Appointment, Appointment.doctor_id == Doctor.doctor_id)
        .filter(
            Appointment.clinic_id == clinic_id,
            Appointment.created_at >= since,
            Doctor.specialization.isnot(None),
        )
        .group_by(Doctor.specialization)
        .order_by(func.count(Appointment.appointment_id).desc())
        .limit(5)
        .all()
    )

    voice_count = (
        db.query(func.count(VoiceMessage.voice_id))
        .join(Message, Message.message_id == VoiceMessage.message_id)
        .join(Conversation, Conversation.conversation_id == Message.conversation_id)
        .filter(Conversation.clinic_id == clinic_id, VoiceMessage.created_at >= since)
        .scalar()
        or 0
    )
    voice_minutes = (
        db.query(func.coalesce(func.sum(VoiceMessage.duration_sec), 0))
        .join(Message, Message.message_id == VoiceMessage.message_id)
        .join(Conversation, Conversation.conversation_id == Message.conversation_id)
        .filter(Conversation.clinic_id == clinic_id, VoiceMessage.created_at >= since)
        .scalar()
        or 0
    )
    voice_minutes = round(float(voice_minutes) / 60.0, 2)

    rem_rows = (
        db.query(Reminder.status, func.count(Reminder.reminder_id))
        .join(Appointment, Appointment.appointment_id == Reminder.appointment_id)
        .filter(Appointment.clinic_id == clinic_id, Reminder.created_at >= since)
        .group_by(Reminder.status)
        .all()
    )
    reminder_by_status = {
        (s.value if hasattr(s, "value") else str(s)): c for s, c in rem_rows
    }

    open_handovers = (
        db.query(func.count(HandoverCase.handover_id))
        .join(Conversation, Conversation.conversation_id == HandoverCase.conversation_id)
        .filter(Conversation.clinic_id == clinic_id, HandoverCase.status == "open")
        .scalar()
        or 0
    )
    closed_handovers = (
        db.query(func.count(HandoverCase.handover_id))
        .join(Conversation, Conversation.conversation_id == HandoverCase.conversation_id)
        .filter(Conversation.clinic_id == clinic_id, HandoverCase.status == "closed")
        .scalar()
        or 0
    )

    cost_total = (
        db.query(func.coalesce(func.sum(UsageLog.cost_estimate), 0.0))
        .filter(UsageLog.clinic_id == clinic_id, UsageLog.created_at >= since)
        .scalar()
        or 0.0
    )

    voice_cost_total = (
        db.query(func.coalesce(func.sum(UsageLog.cost_estimate), 0.0))
        .filter(
            UsageLog.clinic_id == clinic_id,
            UsageLog.created_at >= since,
            UsageLog.operation.in_(["voice_stt", "voice_parse"]),
        )
        .scalar()
        or 0.0
    )
    voice_cost_avg = (
        (float(voice_cost_total) / voice_count) if voice_count else 0.0
    )

    return {
        "period_days": days,
        "total_conversations": int(total_conversations),
        "booking_attempts": int(booking_attempts),
        "confirmed_bookings": int(confirmed),
        "booking_conversion_rate": round(float(conversion), 4),
        "cancelled_appointments": int(cancelled),
        "rescheduled_appointments": int(rescheduled),
        "no_shows": int(no_shows),
        "failed_intents": int(failed_intents),
        "top_doctors": [
            {"name": (ar or en or "?"), "count": int(cnt)} for ar, en, cnt in top_doctors
        ],
        "top_specialties": [
            {"specialty": spec or "?", "count": int(cnt)} for spec, cnt in top_specialties
        ],
        "voice_usage_count": int(voice_count),
        "voice_usage_minutes": voice_minutes,
        "reminders": reminder_by_status,
        "handover_open": int(open_handovers),
        "handover_closed": int(closed_handovers),
        "estimated_cost": float(cost_total),
        "voice_estimated_cost": float(voice_cost_total),
        "voice_cost_avg": round(float(voice_cost_avg), 6),
    }


def list_usage(db: Session, clinic_id: int, limit: int = 200) -> list[dict]:
    rows = (
        db.query(UsageLog)
        .filter(UsageLog.clinic_id == clinic_id)
        .order_by(UsageLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "usage_id": u.usage_id,
            "provider": u.provider,
            "operation": u.operation,
            "tokens_or_minutes": u.tokens_or_minutes,
            "cost_estimate": u.cost_estimate,
            "latency_ms": u.latency_ms,
            "status": u.status,
            "created_at": u.created_at,
        }
        for u in rows
    ]


def usage_summary(db: Session, clinic_id: int, days: int = 30) -> list[dict]:
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(
            UsageLog.provider,
            UsageLog.operation,
            func.count(UsageLog.usage_id),
            func.coalesce(func.sum(UsageLog.tokens_or_minutes), 0),
            func.coalesce(func.sum(UsageLog.cost_estimate), 0.0),
        )
        .filter(UsageLog.clinic_id == clinic_id, UsageLog.created_at >= since)
        .group_by(UsageLog.provider, UsageLog.operation)
        .all()
    )
    return [
        {
            "provider": p,
            "operation": op,
            "events": int(c),
            "tokens_or_minutes": int(tok or 0),
            "cost_estimate": float(cost or 0),
        }
        for p, op, c, tok, cost in rows
    ]


def whatsapp_message_stats(db: Session, clinic_id: int, days: int = 30) -> dict[str, Any]:
    """Inbound/outbound WhatsApp message counts for the Usage page (BRD Usage/costs)."""
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(Message.direction, func.count(Message.message_id))
        .join(Conversation, Conversation.conversation_id == Message.conversation_id)
        .filter(Conversation.clinic_id == clinic_id, Message.created_at >= since)
        .group_by(Message.direction)
        .all()
    )
    by_dir = {(d or "").lower(): int(c or 0) for d, c in rows}
    inbound = by_dir.get("inbound", 0)
    outbound = by_dir.get("outbound", 0)
    return {
        "inbound": inbound,
        "outbound": outbound,
        "total": inbound + outbound,
        "period_days": days,
    }


def usage_failure_count(db: Session, clinic_id: int, days: int = 30) -> int:
    since = datetime.utcnow() - timedelta(days=days)
    return int(
        db.query(func.count(UsageLog.usage_id))
        .filter(
            UsageLog.clinic_id == clinic_id,
            UsageLog.created_at >= since,
            UsageLog.status == "failed",
        )
        .scalar()
        or 0
    )


def dashboard_reschedule(
    db: Session,
    *,
    clinic_id: int,
    appointment_id: int,
    new_slot_id: int,
) -> dict:
    from app.models.patient_models import Patient

    row = (
        db.query(Appointment, Patient)
        .join(Patient, Patient.patient_id == Appointment.patient_id)
        .filter(Appointment.appointment_id == appointment_id, Appointment.clinic_id == clinic_id)
        .one_or_none()
    )
    if not row:
        raise BookingError("Appointment not found")
    appt, patient = row
    return reschedule_appointment(
        db,
        clinic_id=clinic_id,
        whatsapp_phone=patient.whatsapp_phone,
        appointment_id=appointment_id,
        new_slot_id=new_slot_id,
        updated_by="dashboard",
    )


def retry_failed_reminders(db: Session, clinic_id: int, limit: int = 20) -> int:
    from app.services.reminder_service import process_due_reminders

    failed = (
        db.query(Reminder)
        .join(Appointment, Appointment.appointment_id == Reminder.appointment_id)
        .filter(
            Appointment.clinic_id == clinic_id,
            Reminder.status == ReminderStatus.FAILED,
        )
        .limit(limit)
        .all()
    )
    for rem in failed:
        rem.status = ReminderStatus.PENDING
    db.commit()
    if not failed:
        return 0
    result = process_due_reminders(db, force_all_pending=True, limit=limit)
    return int(result.get("sent") or 0)


def available_slots_for_doctor(db: Session, doctor_id: int, clinic_id: int) -> list[dict]:
    avail = get_available_dates_and_slots(db, doctor_id=doctor_id, clinic_id=clinic_id)
    slots: list[dict] = []
    for day, day_slots in (avail.get("dates") or {}).items():
        for s in day_slots:
            slots.append(
                {
                    "date": day,
                    "slot_id": s["slot_id"],
                    "slot_start": s["slot_start"],
                    "slot_end": s["slot_end"],
                }
            )
    return slots


def list_clinic_holidays(db: Session, clinic_id: int) -> list[dict]:
    from app.models.core_models import ClinicHoliday

    rows = (
        db.query(ClinicHoliday)
        .filter(ClinicHoliday.clinic_id == clinic_id)
        .order_by(ClinicHoliday.start_datetime.desc())
        .all()
    )
    return [
        {
            "holiday_id": h.holiday_id,
            "start_datetime": h.start_datetime,
            "end_datetime": h.end_datetime,
            "reason": h.reason,
            "active_flag": h.active_flag,
        }
        for h in rows
    ]


def add_clinic_holiday(
    db: Session,
    *,
    clinic_id: int,
    start_datetime: datetime,
    end_datetime: datetime,
    reason: str | None = None,
    created_by: str = "dashboard",
) -> dict:
    from app.models.core_models import ClinicHoliday
    from app.services.slot_service import block_available_slots_for_range

    if end_datetime <= start_datetime:
        raise ValueError("end_datetime must be after start_datetime")
    row = ClinicHoliday(
        clinic_id=clinic_id,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        reason=reason,
        active_flag=True,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(row)
    db.flush()
    blocked = block_available_slots_for_range(
        db,
        clinic_id=clinic_id,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        updated_by=created_by,
    )
    db.commit()
    db.refresh(row)
    return {
        "holiday_id": row.holiday_id,
        "slots_blocked": blocked,
        "reason": row.reason,
    }


def deactivate_clinic_holiday(
    db: Session, *, clinic_id: int, holiday_id: int, updated_by: str = "dashboard"
) -> bool:
    from app.models.core_models import ClinicHoliday

    row = (
        db.query(ClinicHoliday)
        .filter(
            ClinicHoliday.holiday_id == holiday_id,
            ClinicHoliday.clinic_id == clinic_id,
        )
        .one_or_none()
    )
    if not row:
        return False
    row.active_flag = False
    row.updated_by = updated_by
    db.commit()
    return True


def dashboard_mark_no_show(db: Session, *, clinic_id: int, appointment_id: int) -> dict:
    from app.services.booking_service import mark_no_show

    return mark_no_show(
        db,
        clinic_id=clinic_id,
        appointment_id=appointment_id,
        updated_by="dashboard",
    )
