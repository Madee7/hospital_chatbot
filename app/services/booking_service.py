"""Transactional appointment booking (confirm flow for D1)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import (
    BOOKING_WINDOW_DAYS,
    CANCEL_CUTOFF_HOURS,
    DUPLICATE_APPOINTMENT_DAYS,
    MIN_LEAD_HOURS,
    RESCHEDULE_CUTOFF_HOURS,
    SLOT_HOLD_MINUTES,
)
from app.db.enums import AppointmentStatus, ConversationState, MessageType, SlotStatus
from app.models.appointment_models import Appointment, AppointmentHistory
from app.services.conversation_service import (
    get_or_create_conversation,
    log_message,
    set_conversation_state,
)
from app.services.doctor_service import get_doctor
from app.services.helpers import generate_appointment_ref
from app.services.patient_service import get_or_create_patient, normalize_person_name
from app.services.slot_service import (
    earliest_bookable_at,
    ensure_slots_for_doctor,
    get_slot_for_update,
    group_slots_by_date,
    list_available_slots,
)


class BookingError(Exception):
    """Raised when a booking action cannot be completed."""


_HOLD_PREFIX = "hold:"


def _hold_owner_phone(slot) -> str | None:
    marker = (getattr(slot, "updated_by", None) or "").strip()
    if marker.startswith(_HOLD_PREFIX):
        return marker[len(_HOLD_PREFIX) :] or None
    return None


def _set_hold_owner(slot, phone: str | None) -> None:
    phone = (phone or "").strip()
    slot.updated_by = f"{_HOLD_PREFIX}{phone}" if phone else f"{_HOLD_PREFIX}anonymous"


def _assert_slot_bookable_for_phone(slot, *, whatsapp_phone: str | None) -> None:
    """AVAILABLE is ok; HELD only for the same phone until expiry; BOOKED is never ok."""
    if slot.status == SlotStatus.AVAILABLE:
        return
    if slot.status == SlotStatus.HELD:
        if slot.hold_expires_at and slot.hold_expires_at < datetime.utcnow():
            raise BookingError("Slot hold expired")
        owner = _hold_owner_phone(slot)
        phone = (whatsapp_phone or "").strip()
        if owner and phone and owner != phone:
            raise BookingError("Slot is held by another patient")
        return
    raise BookingError(f"Slot is not available (status={slot.status})")


def hours_until(slot_start: datetime, *, now: datetime | None = None) -> float:
    now = now or datetime.utcnow()
    return (slot_start - now).total_seconds() / 3600


def is_within_cancel_cutoff(slot_start: datetime) -> bool:
    return hours_until(slot_start) < CANCEL_CUTOFF_HOURS


def is_within_reschedule_cutoff(slot_start: datetime) -> bool:
    return hours_until(slot_start) < RESCHEDULE_CUTOFF_HOURS


def find_duplicate_appointments(
    db: Session,
    *,
    clinic_id: int,
    whatsapp_phone: str,
    doctor_id: int,
    within_days: int | None = None,
    exclude_appointment_id: int | None = None,
) -> list[dict]:
    """BR-008: same patient + doctor confirmed appointments within the lookback/forward window."""
    from app.models.appointment_models import AppointmentSlot
    from app.models.patient_models import Patient

    period = within_days if within_days is not None else DUPLICATE_APPOINTMENT_DAYS
    now = datetime.utcnow()
    window_end = now + timedelta(days=period)

    rows = (
        db.query(Appointment, AppointmentSlot)
        .join(Patient, Patient.patient_id == Appointment.patient_id)
        .join(AppointmentSlot, AppointmentSlot.slot_id == Appointment.slot_id)
        .filter(
            Appointment.clinic_id == clinic_id,
            Appointment.doctor_id == doctor_id,
            Patient.whatsapp_phone == whatsapp_phone,
            Appointment.status == AppointmentStatus.CONFIRMED,
            AppointmentSlot.slot_start >= now,
            AppointmentSlot.slot_start <= window_end,
        )
        .order_by(AppointmentSlot.slot_start.asc())
        .all()
    )
    result: list[dict] = []
    for appt, slot in rows:
        if exclude_appointment_id and appt.appointment_id == exclude_appointment_id:
            continue
        result.append(
            {
                "appointment_id": appt.appointment_id,
                "appointment_ref": appt.appointment_ref,
                "doctor_id": appt.doctor_id,
                "slot_start": slot.slot_start,
                "slot_end": slot.slot_end,
            }
        )
    return result


def get_available_dates_and_slots(
    db: Session,
    *,
    doctor_id: int,
    clinic_id: int,
    days_ahead: int | None = None,
) -> dict:
    window = days_ahead if days_ahead is not None else BOOKING_WINDOW_DAYS
    release_expired_holds(db, clinic_id=clinic_id)
    doctor = get_doctor(db, doctor_id, clinic_id=clinic_id)
    if not doctor:
        raise BookingError("Doctor not found")

    ensure_slots_for_doctor(db, doctor=doctor, days_ahead=window)
    slots = list_available_slots(
        db,
        doctor_id=doctor_id,
        clinic_id=clinic_id,
        days_ahead=window,
    )
    db.commit()
    return {
        "doctor_id": doctor.doctor_id,
        "doctor_name_ar": doctor.name_ar,
        "doctor_name_en": doctor.name_en,
        "dates": group_slots_by_date(slots),
        "slot_count": len(slots),
    }


def _assert_slot_meets_lead_time(slot_start: datetime) -> None:
    if slot_start < earliest_bookable_at():
        raise BookingError(
            f"Appointment must be at least {MIN_LEAD_HOURS} hours from now"
        )


def confirm_booking(
    db: Session,
    *,
    tenant_id: int,
    clinic_id: int,
    whatsapp_phone: str,
    patient_name: str | None,
    doctor_id: int,
    slot_id: int,
    reason: str | None = None,
    dob: str | None = None,
    created_channel: str = "whatsapp",
    created_by: str = "bot",
) -> dict:
    """
    Confirm a booking transactionally.

    Locks the slot, creates patient/appointment records, marks slot booked,
    writes appointment_history, and logs conversation state.
    """
    doctor = get_doctor(db, doctor_id, clinic_id=clinic_id)
    if not doctor:
        raise BookingError("Doctor not found")

    slot = get_slot_for_update(db, slot_id)
    if not slot or slot.clinic_id != clinic_id or slot.doctor_id != doctor_id:
        raise BookingError("Slot not found for this doctor")

    _assert_slot_meets_lead_time(slot.slot_start)
    _assert_slot_bookable_for_phone(slot, whatsapp_phone=whatsapp_phone)

    patient = get_or_create_patient(
        db,
        tenant_id=tenant_id,
        clinic_id=clinic_id,
        whatsapp_phone=whatsapp_phone,
        name=patient_name,
        dob=dob,
        created_by=created_by,
    )

    if patient_name:
        patient.name = normalize_person_name(patient_name)
        patient.updated_by = created_by
    if dob:
        patient.dob = dob
        patient.updated_by = created_by

    appointment_ref = generate_appointment_ref()
    appointment = Appointment(
        tenant_id=tenant_id,
        clinic_id=clinic_id,
        patient_id=patient.patient_id,
        doctor_id=doctor.doctor_id,
        slot_id=slot.slot_id,
        appointment_ref=appointment_ref,
        status=AppointmentStatus.CONFIRMED,
        reason=reason,
        created_channel=created_channel,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(appointment)
    db.flush()

    slot.status = SlotStatus.BOOKED
    slot.hold_expires_at = None
    slot.updated_by = created_by

    history = AppointmentHistory(
        appointment_id=appointment.appointment_id,
        old_status=None,
        new_status=AppointmentStatus.CONFIRMED.value,
        old_slot_id=None,
        new_slot_id=slot.slot_id,
        changed_by=created_by,
        reason="Initial booking confirmation",
    )
    db.add(history)

    from app.services.reminder_service import create_booking_reminders

    reminders = create_booking_reminders(
        db,
        appointment=appointment,
        slot_start=slot.slot_start,
        created_by=created_by,
    )

    conversation = get_or_create_conversation(
        db,
        tenant_id=tenant_id,
        clinic_id=clinic_id,
        phone=whatsapp_phone,
        patient_id=patient.patient_id,
    )
    set_conversation_state(
        db,
        conversation,
        ConversationState.CLOSED,
        current_intent="book_appointment_confirmed",
    )
    log_message(
        db,
        conversation_id=conversation.conversation_id,
        direction="outbound",
        message_type=MessageType.SYSTEM,
        text=(
            f"Booking confirmed: {appointment_ref} with "
            f"{doctor.name_ar or doctor.name_en} at {slot.slot_start}"
        ),
        status="sent",
    )

    db.commit()
    db.refresh(appointment)

    return {
        "status": "confirmed",
        "appointment_id": appointment.appointment_id,
        "appointment_ref": appointment.appointment_ref,
        "patient_id": patient.patient_id,
        "doctor_id": doctor.doctor_id,
        "doctor_name_ar": doctor.name_ar,
        "doctor_name_en": doctor.name_en,
        "specialization": doctor.specialization,
        "slot_id": slot.slot_id,
        "slot_start": slot.slot_start.isoformat(sep=" ", timespec="minutes"),
        "slot_end": slot.slot_end.isoformat(sep=" ", timespec="minutes"),
        "conversation_id": conversation.conversation_id,
        "reminders_created": len(reminders),
    }


def hold_slot(
    db: Session,
    *,
    slot_id: int,
    clinic_id: int,
    held_by_phone: str | None = None,
    hold_minutes: int | None = None,
    updated_by: str = "bot",
) -> dict:
    """Temporarily hold a slot for one patient before confirmation (BR-003)."""
    minutes = SLOT_HOLD_MINUTES if hold_minutes is None else hold_minutes
    slot = get_slot_for_update(db, slot_id)
    if not slot or slot.clinic_id != clinic_id:
        raise BookingError("Slot not found")
    phone = (held_by_phone or "").strip() or None

    if slot.status == SlotStatus.HELD:
        if slot.hold_expires_at and slot.hold_expires_at < datetime.utcnow():
            slot.status = SlotStatus.AVAILABLE
            slot.hold_expires_at = None
        else:
            owner = _hold_owner_phone(slot)
            if owner and phone and owner == phone:
                # Refresh hold for the same patient
                slot.hold_expires_at = datetime.utcnow() + timedelta(minutes=minutes)
                _set_hold_owner(slot, phone)
                db.commit()
                return {
                    "slot_id": slot.slot_id,
                    "status": SlotStatus.HELD.value,
                    "hold_expires_at": slot.hold_expires_at.isoformat(
                        sep=" ", timespec="minutes"
                    ),
                    "held_by": phone,
                }
            raise BookingError("Slot is held by another patient")

    if slot.status != SlotStatus.AVAILABLE:
        raise BookingError("Slot is not available")
    _assert_slot_meets_lead_time(slot.slot_start)

    slot.status = SlotStatus.HELD
    slot.hold_expires_at = datetime.utcnow() + timedelta(minutes=minutes)
    _set_hold_owner(slot, phone)
    if not phone:
        slot.updated_by = updated_by
    db.commit()
    return {
        "slot_id": slot.slot_id,
        "status": SlotStatus.HELD.value,
        "hold_expires_at": slot.hold_expires_at.isoformat(sep=" ", timespec="minutes"),
        "held_by": phone,
    }



def list_upcoming_appointments_for_phone(
    db: Session,
    *,
    clinic_id: int,
    whatsapp_phone: str,
    limit: int = 10,
) -> list[dict]:
    """Confirmed upcoming appointments for this WhatsApp number."""
    from app.models.appointment_models import AppointmentSlot
    from app.models.patient_models import Patient
    from app.services.doctor_service import get_doctor

    now = datetime.utcnow()
    rows = (
        db.query(Appointment, AppointmentSlot)
        .join(Patient, Patient.patient_id == Appointment.patient_id)
        .join(AppointmentSlot, AppointmentSlot.slot_id == Appointment.slot_id)
        .filter(
            Appointment.clinic_id == clinic_id,
            Patient.whatsapp_phone == whatsapp_phone,
            Appointment.status == AppointmentStatus.CONFIRMED,
            AppointmentSlot.slot_start >= now,
        )
        .order_by(AppointmentSlot.slot_start.asc())
        .limit(limit)
        .all()
    )
    result: list[dict] = []
    for appt, slot in rows:
        doctor = get_doctor(db, appt.doctor_id, clinic_id=clinic_id)
        name = (doctor.name_ar or doctor.name_en) if doctor else f"Doctor {appt.doctor_id}"
        result.append(
            {
                "appointment_id": appt.appointment_id,
                "appointment_ref": appt.appointment_ref,
                "doctor_id": appt.doctor_id,
                "doctor_name": name,
                "specialization": doctor.specialization if doctor else None,
                "slot_id": slot.slot_id,
                "slot_start": slot.slot_start,
                "slot_end": slot.slot_end,
            }
        )
    return result


def get_appointment_for_clinic(
    db: Session,
    *,
    appointment_id: int,
    clinic_id: int,
) -> Appointment | None:
    return (
        db.query(Appointment)
        .filter(
            Appointment.appointment_id == appointment_id,
            Appointment.clinic_id == clinic_id,
        )
        .one_or_none()
    )


def reschedule_appointment(
    db: Session,
    *,
    clinic_id: int,
    whatsapp_phone: str,
    appointment_id: int,
    new_slot_id: int,
    updated_by: str = "bot",
) -> dict:
    """
    Move a confirmed appointment to a new slot (same clinic).

    Releases the old slot, books the new one, writes history, refreshes reminders.
    """
    from app.models.appointment_models import AppointmentSlot
    from app.models.patient_models import Patient
    from app.services.reminder_service import (
        cancel_pending_reminders,
        create_booking_reminders,
    )

    appointment = get_appointment_for_clinic(
        db, appointment_id=appointment_id, clinic_id=clinic_id
    )
    if not appointment:
        raise BookingError("Appointment not found")
    if appointment.status != AppointmentStatus.CONFIRMED:
        raise BookingError("Only confirmed appointments can be rescheduled")

    patient = (
        db.query(Patient).filter(Patient.patient_id == appointment.patient_id).one_or_none()
    )
    if not patient or patient.whatsapp_phone != whatsapp_phone:
        raise BookingError("Appointment does not belong to this phone")

    old_slot = get_slot_for_update(db, appointment.slot_id)
    new_slot = get_slot_for_update(db, new_slot_id)
    if not new_slot or new_slot.clinic_id != clinic_id:
        raise BookingError("New slot not found")
    _assert_slot_bookable_for_phone(new_slot, whatsapp_phone=whatsapp_phone)
    _assert_slot_meets_lead_time(new_slot.slot_start)

    old_slot_id = appointment.slot_id
    old_doctor_id = appointment.doctor_id
    old_status = appointment.status.value

    if old_slot and old_slot.slot_id != new_slot.slot_id:
        old_slot.status = SlotStatus.AVAILABLE
        old_slot.hold_expires_at = None
        old_slot.updated_by = updated_by

    appointment.slot_id = new_slot.slot_id
    appointment.doctor_id = new_slot.doctor_id
    appointment.status = AppointmentStatus.CONFIRMED
    appointment.updated_by = updated_by

    new_slot.status = SlotStatus.BOOKED
    new_slot.hold_expires_at = None
    new_slot.updated_by = updated_by

    change_reason = "Rescheduled via WhatsApp"
    if new_slot.doctor_id != old_doctor_id:
        change_reason = "Rescheduled via WhatsApp (doctor changed)"

    db.add(
        AppointmentHistory(
            appointment_id=appointment.appointment_id,
            old_status=old_status,
            new_status=AppointmentStatus.CONFIRMED.value,
            old_slot_id=old_slot_id,
            new_slot_id=new_slot.slot_id,
            changed_by=updated_by,
            reason=change_reason,
        )
    )

    cancel_pending_reminders(db, appointment.appointment_id)
    reminders = create_booking_reminders(
        db,
        appointment=appointment,
        slot_start=new_slot.slot_start,
        created_by=updated_by,
    )

    doctor = get_doctor(db, appointment.doctor_id, clinic_id=clinic_id)
    conversation = get_or_create_conversation(
        db,
        tenant_id=appointment.tenant_id,
        clinic_id=clinic_id,
        phone=whatsapp_phone,
        patient_id=appointment.patient_id,
    )
    set_conversation_state(
        db,
        conversation,
        ConversationState.CLOSED,
        current_intent="appointment_rescheduled",
    )
    log_message(
        db,
        conversation_id=conversation.conversation_id,
        direction="outbound",
        message_type=MessageType.SYSTEM,
        text=(
            f"Appointment {appointment.appointment_ref} rescheduled to "
            f"{new_slot.slot_start}"
        ),
        status="sent",
    )

    db.commit()
    db.refresh(appointment)

    return {
        "status": "rescheduled",
        "appointment_id": appointment.appointment_id,
        "appointment_ref": appointment.appointment_ref,
        "doctor_id": appointment.doctor_id,
        "doctor_name_ar": doctor.name_ar if doctor else None,
        "doctor_name_en": doctor.name_en if doctor else None,
        "specialization": doctor.specialization if doctor else None,
        "old_slot_id": old_slot_id,
        "slot_id": new_slot.slot_id,
        "slot_start": new_slot.slot_start.isoformat(sep=" ", timespec="minutes"),
        "slot_end": new_slot.slot_end.isoformat(sep=" ", timespec="minutes"),
        "reminders_created": len(reminders),
    }


def cancel_appointment(
    db: Session,
    *,
    clinic_id: int,
    whatsapp_phone: str,
    appointment_id: int,
    updated_by: str = "bot",
    reason: str = "Cancelled via WhatsApp",
) -> dict:
    """
    Cancel a confirmed appointment: free the slot, cancel pending reminders, write history.
    """
    from app.models.appointment_models import AppointmentSlot
    from app.models.patient_models import Patient
    from app.services.reminder_service import cancel_pending_reminders

    appointment = get_appointment_for_clinic(
        db, appointment_id=appointment_id, clinic_id=clinic_id
    )
    if not appointment:
        raise BookingError("Appointment not found")
    if appointment.status != AppointmentStatus.CONFIRMED:
        raise BookingError("Only confirmed appointments can be cancelled")

    patient = (
        db.query(Patient).filter(Patient.patient_id == appointment.patient_id).one_or_none()
    )
    if not patient or patient.whatsapp_phone != whatsapp_phone:
        raise BookingError("Appointment does not belong to this phone")

    slot = get_slot_for_update(db, appointment.slot_id)
    old_status = appointment.status.value
    slot_start = slot.slot_start if slot else None
    slot_end = slot.slot_end if slot else None

    appointment.status = AppointmentStatus.CANCELLED
    appointment.reason = reason
    appointment.updated_by = updated_by

    if slot:
        slot.status = SlotStatus.AVAILABLE
        slot.hold_expires_at = None
        slot.updated_by = updated_by

    db.add(
        AppointmentHistory(
            appointment_id=appointment.appointment_id,
            old_status=old_status,
            new_status=AppointmentStatus.CANCELLED.value,
            old_slot_id=appointment.slot_id,
            new_slot_id=None,
            changed_by=updated_by,
            reason=reason,
        )
    )

    cancelled_reminders = cancel_pending_reminders(db, appointment.appointment_id)

    doctor = get_doctor(db, appointment.doctor_id, clinic_id=clinic_id)
    conversation = get_or_create_conversation(
        db,
        tenant_id=appointment.tenant_id,
        clinic_id=clinic_id,
        phone=whatsapp_phone,
        patient_id=appointment.patient_id,
    )
    set_conversation_state(
        db,
        conversation,
        ConversationState.CLOSED,
        current_intent="appointment_cancelled",
    )
    log_message(
        db,
        conversation_id=conversation.conversation_id,
        direction="outbound",
        message_type=MessageType.SYSTEM,
        text=f"Appointment {appointment.appointment_ref} cancelled",
        status="sent",
    )

    db.commit()
    db.refresh(appointment)

    return {
        "status": "cancelled",
        "appointment_id": appointment.appointment_id,
        "appointment_ref": appointment.appointment_ref,
        "doctor_id": appointment.doctor_id,
        "doctor_name_ar": doctor.name_ar if doctor else None,
        "doctor_name_en": doctor.name_en if doctor else None,
        "specialization": doctor.specialization if doctor else None,
        "slot_id": appointment.slot_id,
        "slot_start": (
            slot_start.isoformat(sep=" ", timespec="minutes") if slot_start else None
        ),
        "slot_end": (
            slot_end.isoformat(sep=" ", timespec="minutes") if slot_end else None
        ),
        "reminders_cancelled": cancelled_reminders,
    }


def find_appointment_by_ref(
    db: Session,
    *,
    clinic_id: int,
    whatsapp_phone: str,
    appointment_ref: str,
) -> dict | None:
    """Lookup upcoming confirmed appointment by reference for this phone."""
    ref = (appointment_ref or "").strip()
    if not ref:
        return None
    upcoming = list_upcoming_appointments_for_phone(
        db, clinic_id=clinic_id, whatsapp_phone=whatsapp_phone, limit=50
    )
    for a in upcoming:
        if (a.get("appointment_ref") or "").lower() == ref.lower():
            return a
        # allow partial match on last chars (WA list titles truncate)
        if a.get("appointment_ref") and ref.lower() in a["appointment_ref"].lower():
            return a
    return None


def release_expired_holds(db: Session, *, clinic_id: int | None = None) -> int:
    """UC-001: release slots whose temporary hold has expired."""
    from app.models.appointment_models import AppointmentSlot

    now = datetime.utcnow()
    q = db.query(AppointmentSlot).filter(
        AppointmentSlot.status == SlotStatus.HELD,
        AppointmentSlot.hold_expires_at.isnot(None),
        AppointmentSlot.hold_expires_at < now,
    )
    if clinic_id is not None:
        q = q.filter(AppointmentSlot.clinic_id == clinic_id)
    slots = q.all()
    for slot in slots:
        slot.status = SlotStatus.AVAILABLE
        slot.hold_expires_at = None
        slot.updated_by = "hold_sweeper"
    if slots:
        db.commit()
    return len(slots)


def mark_no_show(
    db: Session,
    *,
    clinic_id: int,
    appointment_id: int,
    updated_by: str = "dashboard",
) -> dict:
    """BR-010: mark confirmed appointment as no-show after its start time."""
    from app.models.appointment_models import AppointmentSlot

    appointment = get_appointment_for_clinic(
        db, appointment_id=appointment_id, clinic_id=clinic_id
    )
    if not appointment:
        raise BookingError("Appointment not found")
    if appointment.status != AppointmentStatus.CONFIRMED:
        raise BookingError("Only confirmed appointments can be marked no-show")

    slot = (
        db.query(AppointmentSlot)
        .filter(AppointmentSlot.slot_id == appointment.slot_id)
        .one_or_none()
    )
    if not slot:
        raise BookingError("Slot not found")
    if slot.slot_start > datetime.utcnow():
        raise BookingError("Cannot mark no-show before appointment time")

    old_status = appointment.status.value
    appointment.status = AppointmentStatus.NO_SHOW
    appointment.updated_by = updated_by
    db.add(
        AppointmentHistory(
            appointment_id=appointment.appointment_id,
            old_status=old_status,
            new_status=AppointmentStatus.NO_SHOW.value,
            old_slot_id=appointment.slot_id,
            new_slot_id=appointment.slot_id,
            changed_by=updated_by,
            reason="Marked no-show from dashboard",
        )
    )
    from app.services.reminder_service import cancel_pending_reminders

    cancel_pending_reminders(db, appointment.appointment_id)
    db.commit()
    db.refresh(appointment)
    return {
        "status": "no_show",
        "appointment_id": appointment.appointment_id,
        "appointment_ref": appointment.appointment_ref,
    }

