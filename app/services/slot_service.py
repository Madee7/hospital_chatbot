"""Slot generation and availability helpers (30-minute booking slots)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BOOKING_WINDOW_DAYS, MIN_LEAD_HOURS
from app.db.enums import SlotStatus
from app.models.appointment_models import AppointmentSlot
from app.models.core_models import ClinicHoliday
from app.models.doctor_models import Doctor, DoctorUnavailability, DoctorWorkingHours


def _combine(day: date, t: time) -> datetime:
    return datetime.combine(day, t)


def earliest_bookable_at(now: datetime | None = None) -> datetime:
    """BR-005: slots must start at least MIN_LEAD_HOURS from now."""
    now = now or datetime.utcnow()
    return now + timedelta(hours=MIN_LEAD_HOURS)


def _overlaps_range(
    start: datetime,
    end: datetime,
    range_start: datetime,
    range_end: datetime,
) -> bool:
    return start < range_end and end > range_start


def _overlaps_unavailability(
    start: datetime,
    end: datetime,
    blocks: list[DoctorUnavailability],
) -> bool:
    for block in blocks:
        if _overlaps_range(start, end, block.start_datetime, block.end_datetime):
            return True
    return False


def _overlaps_clinic_holidays(
    start: datetime,
    end: datetime,
    holidays: list[ClinicHoliday],
) -> bool:
    for hol in holidays:
        if _overlaps_range(start, end, hol.start_datetime, hol.end_datetime):
            return True
    return False


def list_clinic_holidays(
    db: Session,
    *,
    clinic_id: int,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
) -> list[ClinicHoliday]:
    q = db.query(ClinicHoliday).filter(
        ClinicHoliday.clinic_id == clinic_id,
        ClinicHoliday.active_flag.is_(True),
    )
    if from_dt is not None:
        q = q.filter(ClinicHoliday.end_datetime >= from_dt)
    if to_dt is not None:
        q = q.filter(ClinicHoliday.start_datetime <= to_dt)
    return q.all()


def block_available_slots_for_range(
    db: Session,
    *,
    clinic_id: int,
    start_datetime: datetime,
    end_datetime: datetime,
    updated_by: str = "clinic_holiday",
) -> int:
    """BR-012: mark AVAILABLE slots overlapping a clinic closure as BLOCKED."""
    slots = (
        db.query(AppointmentSlot)
        .filter(
            AppointmentSlot.clinic_id == clinic_id,
            AppointmentSlot.status == SlotStatus.AVAILABLE,
            AppointmentSlot.slot_start < end_datetime,
            AppointmentSlot.slot_end > start_datetime,
        )
        .all()
    )
    for slot in slots:
        slot.status = SlotStatus.BLOCKED
        slot.updated_by = updated_by
    if slots:
        db.flush()
    return len(slots)


def ensure_slots_for_doctor(
    db: Session,
    *,
    doctor: Doctor,
    days_ahead: int | None = None,
    created_by: str = "system",
) -> list[AppointmentSlot]:
    """
    Generate missing available slots from recurring working hours.

    Uses doctor.slot_minutes (expected 30 for MVP). Does not overwrite
    existing held/booked/blocked rows. Skips past/min-lead times, doctor
    unavailability, and clinic holidays (BR-005 / BR-011 / BR-012).
    """
    window = days_ahead if days_ahead is not None else BOOKING_WINDOW_DAYS
    today = date.today()
    end_day = today + timedelta(days=window)
    min_start = earliest_bookable_at()

    working_hours = (
        db.query(DoctorWorkingHours)
        .filter(
            DoctorWorkingHours.doctor_id == doctor.doctor_id,
            DoctorWorkingHours.active_flag.is_(True),
        )
        .all()
    )
    if not working_hours:
        return []

    blocks = (
        db.query(DoctorUnavailability)
        .filter(
            DoctorUnavailability.doctor_id == doctor.doctor_id,
            DoctorUnavailability.active_flag.is_(True),
            DoctorUnavailability.end_datetime >= datetime.combine(today, time.min),
            DoctorUnavailability.start_datetime <= datetime.combine(end_day, time.max),
        )
        .all()
    )
    holidays = list_clinic_holidays(
        db,
        clinic_id=doctor.clinic_id,
        from_dt=datetime.combine(today, time.min),
        to_dt=datetime.combine(end_day, time.max),
    )

    existing = (
        db.query(AppointmentSlot)
        .filter(
            AppointmentSlot.doctor_id == doctor.doctor_id,
            AppointmentSlot.slot_start >= datetime.combine(today, time.min),
            AppointmentSlot.slot_start
            <= datetime.combine(end_day, time.max),
        )
        .all()
    )
    existing_starts = {slot.slot_start for slot in existing}

    created: list[AppointmentSlot] = []
    day = today
    while day <= end_day:
        weekday = day.weekday()  # 0=Mon ... 6=Sun
        for wh in working_hours:
            if wh.weekday != weekday:
                continue
            slot_minutes = wh.slot_minutes or 30
            cursor = _combine(day, wh.start_time)
            window_end = _combine(day, wh.end_time)
            while cursor + timedelta(minutes=slot_minutes) <= window_end:
                slot_end = cursor + timedelta(minutes=slot_minutes)
                if cursor < min_start:
                    cursor = slot_end
                    continue
                if cursor in existing_starts:
                    cursor = slot_end
                    continue
                if _overlaps_unavailability(cursor, slot_end, blocks):
                    cursor = slot_end
                    continue
                if _overlaps_clinic_holidays(cursor, slot_end, holidays):
                    cursor = slot_end
                    continue

                slot = AppointmentSlot(
                    tenant_id=doctor.tenant_id,
                    doctor_id=doctor.doctor_id,
                    clinic_id=doctor.clinic_id,
                    slot_start=cursor,
                    slot_end=slot_end,
                    status=SlotStatus.AVAILABLE,
                    created_by=created_by,
                    updated_by=created_by,
                )
                db.add(slot)
                created.append(slot)
                existing_starts.add(cursor)
                cursor = slot_end
        day += timedelta(days=1)

    if created:
        db.flush()
    return created


def list_available_slots(
    db: Session,
    *,
    doctor_id: int,
    clinic_id: int,
    from_dt: datetime | None = None,
    days_ahead: int | None = None,
    limit: int = 40,
) -> list[AppointmentSlot]:
    window = days_ahead if days_ahead is not None else BOOKING_WINDOW_DAYS
    start = from_dt or earliest_bookable_at()
    if start < earliest_bookable_at():
        start = earliest_bookable_at()
    end = datetime.utcnow() + timedelta(days=window)
    return (
        db.query(AppointmentSlot)
        .filter(
            AppointmentSlot.doctor_id == doctor_id,
            AppointmentSlot.clinic_id == clinic_id,
            AppointmentSlot.status == SlotStatus.AVAILABLE,
            AppointmentSlot.slot_start >= start,
            AppointmentSlot.slot_start <= end,
        )
        .order_by(AppointmentSlot.slot_start.asc())
        .limit(limit)
        .all()
    )


def group_slots_by_date(slots: list[AppointmentSlot]) -> dict[str, list[dict]]:
    """Group slots into {YYYY-MM-DD: [{slot_id, start, end}, ...]}."""
    grouped: dict[str, list[dict]] = {}
    for slot in slots:
        key = slot.slot_start.date().isoformat()
        grouped.setdefault(key, []).append(
            {
                "slot_id": slot.slot_id,
                "slot_start": slot.slot_start.isoformat(sep=" ", timespec="minutes"),
                "slot_end": slot.slot_end.isoformat(sep=" ", timespec="minutes"),
                "status": slot.status.value if hasattr(slot.status, "value") else slot.status,
            }
        )
    return grouped


def get_slot_for_update(db: Session, slot_id: int) -> AppointmentSlot | None:
    """Lock a slot row to prevent concurrent double booking."""
    stmt = (
        select(AppointmentSlot)
        .where(AppointmentSlot.slot_id == slot_id)
        .with_for_update()
    )
    return db.execute(stmt).scalar_one_or_none()
