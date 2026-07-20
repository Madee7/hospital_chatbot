"""Reminder job creation and delivery for confirmed/rescheduled appointments."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core import i18n_bot as i18n
from app.core.config import REMINDER_HOURS_BEFORE
from app.core.time_format import format_time_12h
from app.db.enums import AppointmentStatus, ReminderStatus
from app.models.appointment_models import Appointment, AppointmentSlot
from app.models.conversation_models import Conversation
from app.models.patient_models import Patient
from app.models.reminder_models import Reminder
from app.services import whatsapp_client as wa
from app.services.clinic_settings_service import format_clinic_location_display
from app.services.doctor_service import get_doctor


def create_booking_reminders(
    db: Session,
    *,
    appointment: Appointment,
    slot_start: datetime,
    created_by: str = "system",
) -> list[Reminder]:
    """Insert pending reminders (default 24h and 2h before appointment)."""
    created: list[Reminder] = []
    now = datetime.utcnow()
    for hours in REMINDER_HOURS_BEFORE:
        scheduled_at = slot_start - timedelta(hours=hours)
        if scheduled_at <= now:
            continue
        reminder = Reminder(
            appointment_id=appointment.appointment_id,
            reminder_type=f"{hours}h_before",
            scheduled_at=scheduled_at,
            status=ReminderStatus.PENDING,
            template_name="appointment_reminder",
            retry_count=0,
        )
        db.add(reminder)
        created.append(reminder)
    db.flush()
    return created


def cancel_pending_reminders(db: Session, appointment_id: int) -> int:
    reminders = (
        db.query(Reminder)
        .filter(
            Reminder.appointment_id == appointment_id,
            Reminder.status == ReminderStatus.PENDING,
        )
        .all()
    )
    for reminder in reminders:
        reminder.status = ReminderStatus.CANCELLED
    db.flush()
    return len(reminders)


def create_reminders_for_appointment_id(db: Session, appointment_id: int) -> list[Reminder]:
    appointment = (
        db.query(Appointment)
        .filter(Appointment.appointment_id == appointment_id)
        .one_or_none()
    )
    if not appointment:
        return []
    slot = (
        db.query(AppointmentSlot)
        .filter(AppointmentSlot.slot_id == appointment.slot_id)
        .one_or_none()
    )
    if not slot:
        return []
    return create_booking_reminders(
        db,
        appointment=appointment,
        slot_start=slot.slot_start,
    )


def _hours_label(reminder_type: str) -> str:
    if reminder_type.endswith("h_before"):
        hours = reminder_type.replace("h_before", "")
        return f"قبل الموعد بـ {hours} ساعة"
    return reminder_type


def list_due_pending_reminders(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 50,
) -> list[Reminder]:
    now = now or datetime.utcnow()
    return (
        db.query(Reminder)
        .filter(
            Reminder.status == ReminderStatus.PENDING,
            Reminder.scheduled_at <= now,
        )
        .order_by(Reminder.scheduled_at.asc())
        .limit(limit)
        .all()
    )


def process_due_reminders(
    db: Session,
    *,
    dry_run: bool = False,
    force_all_pending: bool = False,
    limit: int = 50,
) -> dict:
    """
    Send due (or all pending if force_all_pending) WhatsApp reminder texts.

    Marks reminders sent/failed. force_all_pending is for demo when scheduled_at
    is still in the future.
    """
    now = datetime.utcnow()
    if force_all_pending:
        reminders = (
            db.query(Reminder)
            .filter(Reminder.status == ReminderStatus.PENDING)
            .order_by(Reminder.scheduled_at.asc())
            .limit(limit)
            .all()
        )
    else:
        reminders = list_due_pending_reminders(db, now=now, limit=limit)

    sent = 0
    failed = 0
    skipped = 0
    details: list[dict] = []

    for reminder in reminders:
        appointment = (
            db.query(Appointment)
            .filter(Appointment.appointment_id == reminder.appointment_id)
            .one_or_none()
        )
        if not appointment or appointment.status != AppointmentStatus.CONFIRMED:
            reminder.status = ReminderStatus.CANCELLED
            skipped += 1
            details.append(
                {
                    "reminder_id": reminder.reminder_id,
                    "status": "cancelled",
                    "reason": "appointment missing or not confirmed",
                }
            )
            continue

        patient = (
            db.query(Patient)
            .filter(Patient.patient_id == appointment.patient_id)
            .one_or_none()
        )
        slot = (
            db.query(AppointmentSlot)
            .filter(AppointmentSlot.slot_id == appointment.slot_id)
            .one_or_none()
        )
        if not patient or not slot:
            reminder.status = ReminderStatus.FAILED
            reminder.retry_count = (reminder.retry_count or 0) + 1
            failed += 1
            details.append(
                {
                    "reminder_id": reminder.reminder_id,
                    "status": "failed",
                    "reason": "patient or slot missing",
                }
            )
            continue

        doctor = get_doctor(db, appointment.doctor_id, clinic_id=appointment.clinic_id)
        lang = "ar"
        prev_conv = (
            db.query(Conversation)
            .filter(
                Conversation.clinic_id == appointment.clinic_id,
                Conversation.phone == patient.whatsapp_phone,
            )
            .order_by(Conversation.conversation_id.desc())
            .first()
        )
        if prev_conv and prev_conv.language is not None:
            lang = i18n.normalize_lang(prev_conv.language)
        doctor_name = (
            i18n.doctor_display_name(doctor, lang)
            if doctor
            else f"#{appointment.doctor_id}"
        )
        body = i18n.reminder(
            lang,
            appointment_ref=appointment.appointment_ref or str(appointment.appointment_id),
            doctor_name=doctor_name,
            date_label=slot.slot_start.strftime("%Y-%m-%d"),
            time_label=format_time_12h(slot.slot_start, lang),
            hours_label=_hours_label(reminder.reminder_type),
            location=format_clinic_location_display(db, appointment.clinic_id, lang),
        )

        if dry_run:
            details.append(
                {
                    "reminder_id": reminder.reminder_id,
                    "status": "dry_run",
                    "phone": patient.whatsapp_phone,
                    "text": body,
                }
            )
            continue

        try:
            resp = wa.send_buttons(
                patient.whatsapp_phone,
                body,
                ["تعديل موعد", "إلغاء موعد", "MENU"]
                if not i18n.is_english(lang)
                else ["Reschedule", "Cancel", "MENU"],
            )
            wamid = None
            try:
                wamid = (resp.get("messages") or [{}])[0].get("id")
            except Exception:
                wamid = None
            reminder.status = ReminderStatus.SENT
            reminder.sent_at = now
            if wamid:
                reminder.whatsapp_message_id = wamid
            sent += 1
            details.append(
                {
                    "reminder_id": reminder.reminder_id,
                    "status": "sent",
                    "phone": patient.whatsapp_phone,
                    "whatsapp_message_id": wamid,
                }
            )
        except Exception as exc:  # noqa: BLE001 — worker must record failure
            reminder.status = ReminderStatus.FAILED
            reminder.retry_count = (reminder.retry_count or 0) + 1
            failed += 1
            details.append(
                {
                    "reminder_id": reminder.reminder_id,
                    "status": "failed",
                    "reason": str(exc),
                }
            )

    db.commit()
    return {
        "processed": len(reminders),
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
        "dry_run": dry_run,
        "details": details,
    }
