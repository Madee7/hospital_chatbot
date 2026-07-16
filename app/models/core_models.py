"""
Core models for the hospital chatbot application.

This module contains the foundational models for multi-tenant architecture
including tenants, clinics, and departments.
"""

from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.enums import Language, sa_enum


if TYPE_CHECKING:
    from app.models.doctor_models import Doctor
    from app.models.patient_models import Patient
    from app.models.conversation_models import Conversation
    from app.models.appointment_models import Appointment
    from app.models.appointment_models import AppointmentSlot
    from app.models.admin_models import AdminUser, ConfigSetting
    from app.models.usage_models import UsageLog


class Tenant(Base):
    """
    Tenant model representing a top-level organization.

    Each tenant represents a separate customer/organization
    using the hospital chatbot SaaS platform.
    """

    __tablename__ = "tenants"

    tenant_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    tenant_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    status: Mapped[Optional[str]] = mapped_column(
        String(50)
    )

    plan: Mapped[Optional[str]] = mapped_column(
        String(100)
    )

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

    # Relationships
    clinics: Mapped[List["Clinic"]] = relationship(
        "Clinic",
        back_populates="tenant",
        cascade="all, delete-orphan"
    )
    admin_users: Mapped[List["AdminUser"]] = relationship(
        "AdminUser",
        back_populates="tenant",
        cascade="all, delete-orphan"
    )
    doctors: Mapped[List["Doctor"]] = relationship(
        "Doctor",
        back_populates="tenant"
    )


class Clinic(Base):
    """
    Clinic model representing a medical facility.

    Each clinic belongs to a tenant and can have departments,
    doctors, patients, appointments, and WhatsApp configuration.
    """

    __tablename__ = "clinics"

    clinic_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    tenant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tenants.tenant_id"),
        nullable=False
    )

    clinic_name: Mapped[Optional[str]] = mapped_column(
        String(255)
    )

    whatsapp_number: Mapped[Optional[str]] = mapped_column(
        String(30)
    )

    timezone: Mapped[Optional[str]] = mapped_column(
        String(100)
    )

    language_default: Mapped[Optional[Language]] = mapped_column(
        sa_enum(Language, length=10)
    )

    address: Mapped[Optional[str]] = mapped_column(
        Text
    )

    status: Mapped[Optional[str]] = mapped_column(
        String(50)
    )

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
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="clinics"
    )

    departments: Mapped[List["Department"]] = relationship(
        "Department",
        back_populates="clinic",
        cascade="all, delete-orphan"
    )

    doctors: Mapped[List["Doctor"]] = relationship(
        "Doctor",
        back_populates="clinic"
    )
    conversations: Mapped[List["Conversation"]] = relationship(
        "Conversation",
        back_populates="clinic"
    )
    appointments: Mapped[List["Appointment"]] = relationship(
        "Appointment",
        back_populates="clinic"
    )
    appointment_slots: Mapped[List["AppointmentSlot"]] = relationship(
        "AppointmentSlot",
        back_populates="clinic"
    )
    config_settings: Mapped[List["ConfigSetting"]] = relationship(
        "ConfigSetting",
        back_populates="clinic",
        cascade="all, delete-orphan"
    )
    usage_logs: Mapped[List["UsageLog"]] = relationship(
        "UsageLog",
        back_populates="clinic"
    )
    patients: Mapped[List["Patient"]] = relationship(
        "Patient",
        back_populates="clinic"
    )
    holidays: Mapped[List["ClinicHoliday"]] = relationship(
        "ClinicHoliday",
        back_populates="clinic",
        cascade="all, delete-orphan",
    )


class ClinicHoliday(Base):
    """
    Clinic-wide holiday / closure (BR-012).

    Removes/blocks slots for all doctors during the range unless staff delete the holiday.
    """

    __tablename__ = "clinic_holidays"

    holiday_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clinics.clinic_id"),
        nullable=False,
    )
    start_datetime: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_datetime: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255))
    active_flag: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(255))
    updated_by: Mapped[Optional[str]] = mapped_column(String(255))

    clinic: Mapped["Clinic"] = relationship("Clinic", back_populates="holidays")


class Department(Base):
    """
    Department model representing medical specialties.

    Each department belongs to a clinic and can contain multiple doctors.
    """

    __tablename__ = "departments"

    department_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    clinic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clinics.clinic_id"),
        nullable=False
    )

    name_en: Mapped[Optional[str]] = mapped_column(
        String(150)
    )

    name_ar: Mapped[Optional[str]] = mapped_column(
        String(150)
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text
    )

    active_flag: Mapped[bool] = mapped_column(
        Boolean,
        server_default="true",
        nullable=False
    )

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
    clinic: Mapped["Clinic"] = relationship(
        "Clinic",
        back_populates="departments"
    )

    doctors: Mapped[List["Doctor"]] = relationship(
        "Doctor",
        back_populates="department"
    )
