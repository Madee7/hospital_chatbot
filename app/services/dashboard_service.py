"""Read/query helpers for the Streamlit clinic dashboard."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.enums import AppointmentStatus
from app.models.appointment_models import Appointment, AppointmentHistory, AppointmentSlot
from app.models.conversation_models import Conversation, Message
from app.models.doctor_models import Doctor
from app.models.patient_models import Patient
from app.models.reminder_models import Reminder
from app.services.booking_service import BookingError, cancel_appointment


def list_appointments(
    db: Session,
    *,
    clinic_id: int,
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    q = (
        db.query(Appointment, AppointmentSlot, Patient, Doctor)
        .join(AppointmentSlot, AppointmentSlot.slot_id == Appointment.slot_id)
        .join(Patient, Patient.patient_id == Appointment.patient_id)
        .join(Doctor, Doctor.doctor_id == Appointment.doctor_id)
        .filter(Appointment.clinic_id == clinic_id)
        .order_by(AppointmentSlot.slot_start.desc())
    )
    if status:
        q = q.filter(Appointment.status == status)
    rows = q.limit(limit).all()
    result: list[dict] = []
    for appt, slot, patient, doctor in rows:
        result.append(
            {
                "appointment_id": appt.appointment_id,
                "appointment_ref": appt.appointment_ref,
                "status": appt.status.value if hasattr(appt.status, "value") else appt.status,
                "patient_name": patient.name,
                "phone": patient.whatsapp_phone,
                "doctor_id": appt.doctor_id,
                "doctor_name": doctor.name_ar or doctor.name_en,
                "specialization": doctor.specialization,
                "slot_id": slot.slot_id,
                "slot_start": slot.slot_start,
                "slot_end": slot.slot_end,
                "slot_status": slot.status.value if hasattr(slot.status, "value") else slot.status,
                "created_at": appt.created_at,
                "updated_at": appt.updated_at,
            }
        )
    return result


def list_appointment_history(
    db: Session,
    *,
    appointment_id: int,
) -> list[dict]:
    rows = (
        db.query(AppointmentHistory)
        .filter(AppointmentHistory.appointment_id == appointment_id)
        .order_by(AppointmentHistory.created_at.asc())
        .all()
    )
    return [
        {
            "history_id": h.history_id,
            "old_status": h.old_status,
            "new_status": h.new_status,
            "old_slot_id": h.old_slot_id,
            "new_slot_id": h.new_slot_id,
            "changed_by": h.changed_by,
            "reason": h.reason,
            "created_at": h.created_at,
        }
        for h in rows
    ]


def list_conversations(
    db: Session,
    *,
    clinic_id: int,
    limit: int = 50,
) -> list[dict]:
    rows = (
        db.query(Conversation)
        .filter(Conversation.clinic_id == clinic_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "conversation_id": c.conversation_id,
            "phone": c.phone,
            "state": c.state.value if c.state and hasattr(c.state, "value") else c.state,
            "current_intent": c.current_intent,
            "patient_id": c.patient_id,
            "updated_at": c.updated_at or c.created_at,
        }
        for c in rows
    ]


def list_messages(
    db: Session,
    *,
    conversation_id: int,
    limit: int = 200,
) -> list[dict]:
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            "message_id": m.message_id,
            "direction": m.direction,
            "message_type": (
                m.type.value if m.type and hasattr(m.type, "value") else m.type
            ),
            "text": m.text,
            "status": m.status,
            "created_at": m.created_at or m.timestamp,
        }
        for m in rows
    ]


def list_reminders(
    db: Session,
    *,
    clinic_id: int,
    limit: int = 100,
) -> list[dict]:
    rows = (
        db.query(Reminder, Appointment, AppointmentSlot, Patient)
        .join(Appointment, Appointment.appointment_id == Reminder.appointment_id)
        .join(AppointmentSlot, AppointmentSlot.slot_id == Appointment.slot_id)
        .join(Patient, Patient.patient_id == Appointment.patient_id)
        .filter(Appointment.clinic_id == clinic_id)
        .order_by(Reminder.scheduled_at.desc())
        .limit(limit)
        .all()
    )
    result: list[dict] = []
    for rem, appt, slot, patient in rows:
        result.append(
            {
                "reminder_id": rem.reminder_id,
                "appointment_ref": appt.appointment_ref,
                "phone": patient.whatsapp_phone,
                "reminder_type": rem.reminder_type,
                "scheduled_at": rem.scheduled_at,
                "sent_at": rem.sent_at,
                "status": rem.status.value if hasattr(rem.status, "value") else rem.status,
                "slot_start": slot.slot_start,
                "template_name": rem.template_name,
                "retry_count": rem.retry_count,
            }
        )
    return result


def dashboard_cancel_appointment(
    db: Session,
    *,
    clinic_id: int,
    appointment_id: int,
) -> dict:
    """Cancel from dashboard; lookup phone then reuse booking cancel."""
    row = (
        db.query(Appointment, Patient)
        .join(Patient, Patient.patient_id == Appointment.patient_id)
        .filter(
            Appointment.appointment_id == appointment_id,
            Appointment.clinic_id == clinic_id,
        )
        .one_or_none()
    )
    if not row:
        raise BookingError("Appointment not found")
    appt, patient = row
    if appt.status != AppointmentStatus.CONFIRMED:
        raise BookingError("Only confirmed appointments can be cancelled")
    return cancel_appointment(
        db,
        clinic_id=clinic_id,
        whatsapp_phone=patient.whatsapp_phone,
        appointment_id=appointment_id,
        updated_by="dashboard",
        reason="Cancelled via dashboard",
    )


def get_slot_status(db: Session, *, slot_id: int) -> str | None:
    slot = db.query(AppointmentSlot).filter(AppointmentSlot.slot_id == slot_id).one_or_none()
    if not slot:
        return None
    return slot.status.value if hasattr(slot.status, "value") else str(slot.status)


def list_doctor_schedule(
    db: Session,
    *,
    clinic_id: int,
    doctor_id: int,
    days_ahead: int = 14,
    include_past_hours: int = 0,
) -> dict:
    """
    Per-doctor inventory: free slots vs booked appointments.

    BOOKED/HELD slots never appear in free_slots — only AVAILABLE does.
    """
    from datetime import timedelta

    from app.db.enums import AppointmentStatus, SlotStatus
    from app.services.booking_service import release_expired_holds
    from app.services.doctor_service import get_doctor
    from app.services.slot_service import ensure_slots_for_doctor

    doctor = get_doctor(db, doctor_id, clinic_id=clinic_id)
    if not doctor:
        return {"doctor": None, "free_slots": [], "booked": [], "held": [], "blocked": []}

    release_expired_holds(db, clinic_id=clinic_id)
    ensure_slots_for_doctor(db, doctor=doctor, days_ahead=days_ahead, created_by="dashboard_schedule")
    db.commit()

    now = datetime.utcnow() - timedelta(hours=include_past_hours)
    end = datetime.utcnow() + timedelta(days=days_ahead)

    slots = (
        db.query(AppointmentSlot)
        .filter(
            AppointmentSlot.clinic_id == clinic_id,
            AppointmentSlot.doctor_id == doctor_id,
            AppointmentSlot.slot_start >= now,
            AppointmentSlot.slot_start <= end,
        )
        .order_by(AppointmentSlot.slot_start.asc())
        .all()
    )

    # Active appointments for this doctor in window
    appt_rows = (
        db.query(Appointment, AppointmentSlot, Patient)
        .join(AppointmentSlot, AppointmentSlot.slot_id == Appointment.slot_id)
        .join(Patient, Patient.patient_id == Appointment.patient_id)
        .filter(
            Appointment.clinic_id == clinic_id,
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_(
                [AppointmentStatus.CONFIRMED, AppointmentStatus.RESCHEDULED]
            ),
            AppointmentSlot.slot_start >= now,
            AppointmentSlot.slot_start <= end,
        )
        .order_by(AppointmentSlot.slot_start.asc())
        .all()
    )
    booked_by_slot = {slot.slot_id: (appt, patient) for appt, slot, patient in appt_rows}

    free_slots: list[dict] = []
    booked: list[dict] = []
    held: list[dict] = []
    blocked: list[dict] = []

    for slot in slots:
        status = slot.status.value if hasattr(slot.status, "value") else str(slot.status)
        base = {
            "slot_id": slot.slot_id,
            "slot_start": slot.slot_start,
            "slot_end": slot.slot_end,
            "status": status,
        }
        if slot.status == SlotStatus.AVAILABLE:
            free_slots.append(base)
        elif slot.status == SlotStatus.HELD:
            held.append({**base, "hold_expires_at": slot.hold_expires_at})
        elif slot.status == SlotStatus.BLOCKED:
            blocked.append(base)
        elif slot.status == SlotStatus.BOOKED:
            appt_patient = booked_by_slot.get(slot.slot_id)
            if appt_patient:
                appt, patient = appt_patient
                booked.append(
                    {
                        **base,
                        "appointment_id": appt.appointment_id,
                        "appointment_ref": appt.appointment_ref,
                        "patient_name": patient.name,
                        "phone": patient.whatsapp_phone,
                        "appointment_status": (
                            appt.status.value
                            if hasattr(appt.status, "value")
                            else appt.status
                        ),
                    }
                )
            else:
                booked.append({**base, "appointment_ref": None, "patient_name": None})

    # Include confirmed appts whose slot row might differ
    seen_slot_ids = {b["slot_id"] for b in booked}
    for appt, slot, patient in appt_rows:
        if slot.slot_id in seen_slot_ids:
            continue
        booked.append(
            {
                "slot_id": slot.slot_id,
                "slot_start": slot.slot_start,
                "slot_end": slot.slot_end,
                "status": "booked",
                "appointment_id": appt.appointment_id,
                "appointment_ref": appt.appointment_ref,
                "patient_name": patient.name,
                "phone": patient.whatsapp_phone,
                "appointment_status": (
                    appt.status.value if hasattr(appt.status, "value") else appt.status
                ),
            }
        )

    return {
        "doctor": {
            "doctor_id": doctor.doctor_id,
            "name_ar": doctor.name_ar,
            "name_en": doctor.name_en,
            "specialization": doctor.specialization,
        },
        "counts": {
            "free": len(free_slots),
            "booked": len(booked),
            "held": len(held),
            "blocked": len(blocked),
        },
        "free_slots": free_slots,
        "booked": booked,
        "held": held,
        "blocked": blocked,
    }


def status_counts(db: Session, *, clinic_id: int) -> dict[str, int]:
    rows = (
        db.query(Appointment.status, Appointment.appointment_id)
        .filter(Appointment.clinic_id == clinic_id)
        .all()
    )
    counts: dict[str, int] = {}
    for status, _ in rows:
        key = status.value if hasattr(status, "value") else str(status)
        counts[key] = counts.get(key, 0) + 1
    return counts
