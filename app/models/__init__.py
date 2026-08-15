"""
SQLAlchemy ORM models for the hospital chatbot.

Importing this package registers all models with Base.metadata
so create_all / Alembic can discover them.
"""

from app.models.core_models import Tenant, Clinic, Department, ClinicHoliday
from app.models.doctor_models import (
    Doctor,
    DoctorLocation,
    DoctorWorkingHours,
    DoctorUnavailability,
)
from app.models.patient_models import Patient
from app.models.appointment_models import (
    AppointmentSlot,
    Appointment,
    AppointmentHistory,
)
from app.models.conversation_models import Conversation, Message, VoiceMessage
from app.models.reminder_models import Reminder
from app.models.handover_models import HandoverCase
from app.models.usage_models import UsageLog
from app.models.admin_models import AdminUser, AdminUserClinic, ConfigSetting

__all__ = [
    "Tenant",
    "Clinic",
    "Department",
    "ClinicHoliday",
    "Doctor",
    "DoctorLocation",
    "DoctorWorkingHours",
    "DoctorUnavailability",
    "Patient",
    "AppointmentSlot",
    "Appointment",
    "AppointmentHistory",
    "Conversation",
    "Message",
    "VoiceMessage",
    "Reminder",
    "HandoverCase",
    "UsageLog",
    "AdminUser",
    "AdminUserClinic",
    "ConfigSetting",
]
