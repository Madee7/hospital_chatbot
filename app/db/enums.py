"""
Enums for the hospital chatbot application.

This module defines all the enumeration types used throughout the application
for consistent data representation and validation.
"""

from enum import StrEnum, unique
from typing import Type

from sqlalchemy import Enum as SAEnum


def sa_enum(enum_cls: Type[StrEnum], *, length: int = 50) -> SAEnum:
    """Store StrEnum values as VARCHAR (not PostgreSQL native ENUM)."""
    return SAEnum(
        enum_cls,
        values_callable=lambda members: [member.value for member in members],
        native_enum=False,
        length=length,
        validate_strings=True,
    )


@unique
class AppointmentStatus(StrEnum):
    """Status values for appointment records."""
    DRAFT = "draft"
    HELD = "held"
    CONFIRMED = "confirmed"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"
    PENDING_HANDOVER = "pending_handover"

@unique
class SlotStatus(StrEnum):
    """Status values for appointment time slots."""
    AVAILABLE = "available"
    HELD = "held"
    BOOKED = "booked"
    BLOCKED = "blocked"
    EXPIRED = "expired"

@unique
class ReminderStatus(StrEnum):
    """Status values for appointment reminders."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    CANCELLED = "cancelled"

@unique
class ConversationState(StrEnum):
    """State values for chatbot conversation flow."""
    NEW = "new"
    LANGUAGE_SELECT = "language_select"
    MAIN_MENU = "main_menu"
    BOOKING_DOCTOR = "booking_doctor"
    BOOKING_DATE = "booking_date"
    BOOKING_SLOT = "booking_slot"
    PATIENT_DETAILS = "patient_details"
    CONFIRMING = "confirming"
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"
    HANDOVER = "handover"
    CLOSED = "closed"

@unique
class MessageType(StrEnum):
    """Type values for chat messages."""
    TEXT = "text"
    IMAGE = "image"
    VOICE = "voice"
    INTERACTIVE_REPLY = "interactive_reply"
    TEMPLATE = "template"
    FLOW = "flow"
    SYSTEM = "system"

@unique
class HandoverPriority(StrEnum):
    """Priority levels for human handover requests."""
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

@unique
class Language(StrEnum):
    """Supported language codes."""
    AR = "ar"
    AR_EG = "ar-EG"
    EN = "en"
