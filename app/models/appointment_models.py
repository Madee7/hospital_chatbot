"""
Appointment-related models for the hospital chatbot application.

This module contains models for appointment slots, appointments, and
appointment history for tracking booking changes and audit trails.
"""

from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Index,
    UniqueConstraint,
    text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.enums import AppointmentStatus, SlotStatus, sa_enum


if TYPE_CHECKING:
    from app.models.core_models import Clinic, Tenant
    from app.models.doctor_models import Doctor
    from app.models.patient_models import Patient
    from app.models.reminder_models import Reminder


class AppointmentSlot(Base):
    __tablename__ = "appointment_slots"

    slot_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    tenant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tenants.tenant_id"),
        nullable=False
    )

    doctor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("doctors.doctor_id"),
        nullable=False
    )

    clinic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clinics.clinic_id"),
        nullable=False
    )

    slot_start: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False
    )

    slot_end: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False
    )

    status: Mapped[SlotStatus] = mapped_column(
        sa_enum(SlotStatus),
        server_default=SlotStatus.AVAILABLE.value,
        nullable=False
    )

    hold_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )

    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now()
    )

    created_by: Mapped[Optional[str]] = mapped_column(String(255))
    updated_by: Mapped[Optional[str]] = mapped_column(String(255))

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant")

    doctor: Mapped["Doctor"] = relationship(
        "Doctor",
        back_populates="appointment_slots"
    )

    clinic: Mapped["Clinic"] = relationship(
        "Clinic",
        back_populates="appointment_slots"
    )

    appointments: Mapped[List["Appointment"]] = relationship(
        "Appointment",
        back_populates="appointment_slot"
    )

    old_slot_histories: Mapped[List["AppointmentHistory"]] = relationship(
        "AppointmentHistory",
        foreign_keys="AppointmentHistory.old_slot_id",
        back_populates="old_slot"
    )

    new_slot_histories: Mapped[List["AppointmentHistory"]] = relationship(
        "AppointmentHistory",
        foreign_keys="AppointmentHistory.new_slot_id",
        back_populates="new_slot"
    )

    __table_args__ = (
        UniqueConstraint(
            "doctor_id",
            "slot_start",
            name="uq_appointment_slot_doctor_start",
        ),
        Index("idx_appointment_slot_tenant", "tenant_id"),
        Index("idx_appointment_slot_doctor", "doctor_id"),
        Index("idx_appointment_slot_clinic", "clinic_id"),
        Index("idx_appointment_slot_status", "status"),
    )


class Appointment(Base):
    __tablename__ = "appointments"

    appointment_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    tenant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tenants.tenant_id"),
        nullable=False
    )

    clinic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clinics.clinic_id"),
        nullable=False
    )

    patient_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("patients.patient_id"),
        nullable=False
    )

    doctor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("doctors.doctor_id"),
        nullable=False
    )

    slot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("appointment_slots.slot_id"),
        nullable=False
    )

    appointment_ref: Mapped[Optional[str]] = mapped_column(
        String(100)
    )

    status: Mapped[AppointmentStatus] = mapped_column(
        sa_enum(AppointmentStatus),
        server_default=AppointmentStatus.DRAFT.value,
        nullable=False
    )

    reason: Mapped[Optional[str]] = mapped_column(
        Text
    )

    created_channel: Mapped[Optional[str]] = mapped_column(
        String(50)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )

    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now()
    )

    created_by: Mapped[Optional[str]] = mapped_column(String(255))
    updated_by: Mapped[Optional[str]] = mapped_column(String(255))

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant")

    clinic: Mapped["Clinic"] = relationship(
        "Clinic",
        back_populates="appointments"
    )

    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="appointments"
    )

    doctor: Mapped["Doctor"] = relationship(
        "Doctor",
        back_populates="appointments"
    )

    appointment_slot: Mapped["AppointmentSlot"] = relationship(
        "AppointmentSlot",
        back_populates="appointments"
    )

    appointment_histories: Mapped[List["AppointmentHistory"]] = relationship(
        "AppointmentHistory",
        back_populates="appointment",
        cascade="all, delete-orphan"
    )

    reminders: Mapped[List["Reminder"]] = relationship(
        "Reminder",
        back_populates="appointment",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        # One active booking per slot; cancelled/completed/no_show/rescheduled may reuse freed slots
        Index(
            "uq_appointment_active_slot",
            "slot_id",
            unique=True,
            postgresql_where=text(
                "status NOT IN ('cancelled', 'completed', 'no_show', 'rescheduled')"
            ),
        ),
        Index("idx_appointment_tenant", "tenant_id"),
        Index("idx_appointment_clinic", "clinic_id"),
        Index("idx_appointment_patient", "patient_id"),
        Index("idx_appointment_doctor", "doctor_id"),
        Index("idx_appointment_status", "status"),
        Index("idx_appointment_slot", "slot_id"),
    )


class AppointmentHistory(Base):
    __tablename__ = "appointment_history"

    history_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    appointment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("appointments.appointment_id"),
        nullable=False
    )

    old_status: Mapped[Optional[str]] = mapped_column(
        String(50)
    )

    new_status: Mapped[Optional[str]] = mapped_column(
        String(50)
    )

    old_slot_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("appointment_slots.slot_id")
    )

    new_slot_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("appointment_slots.slot_id")
    )

    changed_by: Mapped[Optional[str]] = mapped_column(
        String(255)
    )

    reason: Mapped[Optional[str]] = mapped_column(
        Text
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )

    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now()
    )

    # Relationships
    appointment: Mapped["Appointment"] = relationship(
        "Appointment",
        back_populates="appointment_histories"
    )

    old_slot: Mapped[Optional["AppointmentSlot"]] = relationship(
        "AppointmentSlot",
        foreign_keys=[old_slot_id],
        back_populates="old_slot_histories"
    )

    new_slot: Mapped[Optional["AppointmentSlot"]] = relationship(
        "AppointmentSlot",
        foreign_keys=[new_slot_id],
        back_populates="new_slot_histories"
    )

    __table_args__ = (
        Index(
            "idx_appointment_history_appointment",
            "appointment_id"
        ),
    )
