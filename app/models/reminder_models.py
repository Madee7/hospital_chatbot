"""
Reminder-related models for the hospital chatbot application.

This module contains models for scheduled reminder jobs for appointments
including status tracking and retry mechanisms.
"""

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    DateTime, ForeignKey, Integer, String, Index, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.enums import ReminderStatus, sa_enum

if TYPE_CHECKING:
    from app.models.appointment_models import Appointment


class Reminder(Base):
    """
    Reminder model representing scheduled reminder jobs for appointments.

    Tracks reminder scheduling, delivery status, and retry attempts
    for appointment notifications sent to patients.
    """
    __tablename__ = "reminders"

    reminder_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("appointments.appointment_id", ondelete="CASCADE"),
        nullable=False
    )
    reminder_type: Mapped[str] = mapped_column(String(50), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[ReminderStatus] = mapped_column(
        sa_enum(ReminderStatus),
        nullable=False,
        server_default=ReminderStatus.PENDING.value,
    )
    template_name: Mapped[Optional[str]] = mapped_column(String(100))
    retry_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    whatsapp_message_id: Mapped[Optional[str]] = mapped_column(String(255))

    # Audit fields
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships
    appointment: Mapped["Appointment"] = relationship(
        "Appointment",
        back_populates="reminders"
    )

    # Indexes
    __table_args__ = (
        Index('idx_reminder_appointment', 'appointment_id'),
        Index('idx_reminder_status', 'status'),
        Index('idx_reminder_scheduled_at', 'scheduled_at'),
        Index('idx_reminder_type', 'reminder_type'),
        Index('idx_reminder_status_scheduled', 'status', 'scheduled_at'),
    )
