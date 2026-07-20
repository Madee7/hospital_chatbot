"""
Patient-related models for the hospital chatbot application.

This module contains the Patient model for storing patient profiles
from WhatsApp interactions and optional medical record numbers.
"""

from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    DateTime, ForeignKey, Integer, String, Index, UniqueConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.core_models import Clinic, Tenant
    from app.models.appointment_models import Appointment
    from app.models.conversation_models import Conversation


class Patient(Base):
    """
    Patient model representing patient profiles in the system.

Stores patient information collected from WhatsApp interactions
including contact details and demographics.
    """
    __tablename__ = "patients"

    patient_id: Mapped[int] = mapped_column(Integer, primary_key=True)
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
    whatsapp_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    dob: Mapped[Optional[str]] = mapped_column(String(10))  # YYYY-MM-DD format
    gender: Mapped[Optional[str]] = mapped_column(String(10))
    consent_status: Mapped[Optional[str]] = mapped_column(String(50))

    # Audit fields
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
        back_populates="patients"
    )
    appointments: Mapped[List["Appointment"]] = relationship(
        "Appointment",
        back_populates="patient",
        cascade="all, delete-orphan"
    )
    conversations: Mapped[List["Conversation"]] = relationship(
        "Conversation",
        back_populates="patient",
        cascade="all, delete-orphan"
    )

    # Indexes and constraints
    __table_args__ = (
        UniqueConstraint(
            'clinic_id',
            'whatsapp_phone',
            name='uq_patient_clinic_whatsapp',
        ),
        Index('idx_patient_tenant', 'tenant_id'),
        Index('idx_patient_clinic', 'clinic_id'),
        Index('idx_patient_whatsapp_phone', 'whatsapp_phone'),
    )
