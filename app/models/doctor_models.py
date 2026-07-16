"""
Doctor-related models for the hospital chatbot application.

This module contains models for doctors, their locations, working hours,
unavailability periods, and appointment slots.
"""

from datetime import datetime, time
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    Index,
    func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


if TYPE_CHECKING:
    from app.models.core_models import Clinic, Department, Tenant
    from app.models.appointment_models import Appointment, AppointmentSlot


class Doctor(Base):
    """
    Doctor model representing medical practitioners in the system.

    Each doctor belongs to a clinic and department, and has associated
    locations, working hours, unavailability periods, and appointment slots.
    """

    __tablename__ = "doctors"

    doctor_id: Mapped[int] = mapped_column(
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

    department_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("departments.department_id"),
        nullable=False
    )

    name_en: Mapped[Optional[str]] = mapped_column(
        String(255)
    )

    name_ar: Mapped[Optional[str]] = mapped_column(
        String(255)
    )

    title: Mapped[Optional[str]] = mapped_column(
        String(100)
    )

    specialization: Mapped[Optional[str]] = mapped_column(
        String(255)
    )

    bio: Mapped[Optional[str]] = mapped_column(
        Text
    )

    photo_url: Mapped[Optional[str]] = mapped_column(
        String(500)
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
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="doctors"
    )

    clinic: Mapped["Clinic"] = relationship(
        "Clinic",
        back_populates="doctors"
    )

    department: Mapped["Department"] = relationship(
        "Department",
        back_populates="doctors"
    )

    doctor_locations: Mapped[List["DoctorLocation"]] = relationship(
        "DoctorLocation",
        back_populates="doctor",
        cascade="all, delete-orphan"
    )

    doctor_working_hours: Mapped[List["DoctorWorkingHours"]] = relationship(
        "DoctorWorkingHours",
        back_populates="doctor",
        cascade="all, delete-orphan"
    )

    doctor_unavailabilities: Mapped[List["DoctorUnavailability"]] = relationship(
        "DoctorUnavailability",
        back_populates="doctor",
        cascade="all, delete-orphan"
    )

    appointment_slots: Mapped[List["AppointmentSlot"]] = relationship(
        "AppointmentSlot",
        back_populates="doctor",
        cascade="all, delete-orphan"
    )

    appointments: Mapped[List["Appointment"]] = relationship(
        "Appointment",
        back_populates="doctor"
    )


    __table_args__ = (
        Index(
            "idx_doctor_tenant",
            "tenant_id"
        ),
        Index(
            "idx_doctor_clinic",
            "clinic_id"
        ),
        Index(
            "idx_doctor_department",
            "department_id"
        ),
        Index(
            "idx_doctor_active",
            "active_flag"
        ),
    )


class DoctorLocation(Base):
    """
    Doctor location model for tracking where doctors practice.

    Represents specific locations, rooms, or addresses where
    a doctor provides medical services.
    """

    __tablename__ = "doctor_locations"
    
    doctor_location_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    doctor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("doctors.doctor_id", ondelete="CASCADE"),
        nullable=False
    )

    location_name: Mapped[Optional[str]] = mapped_column(
        String(255)
    )

    room: Mapped[Optional[str]] = mapped_column(
        String(100)
    )

    address: Mapped[Optional[str]] = mapped_column(
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

    # Relationships
    doctor: Mapped["Doctor"] = relationship(
        "Doctor",
        back_populates="doctor_locations"
    )

    __table_args__ = (
        Index(
            "idx_doctor_location_doctor",
            "doctor_id"
        ),
        Index(
            "idx_doctor_location_active",
            "active_flag"
        ),
    )


class DoctorWorkingHours(Base):
    """
    Doctor working hours model for scheduling availability.

    Defines recurring weekly schedule including weekday,
    working period, appointment duration, and maximum bookings.
    """

    __tablename__ = "doctor_working_hours"


    working_hours_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    doctor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("doctors.doctor_id", ondelete="CASCADE"),
        nullable=False
    )

    weekday: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )
    # 0 = Monday ... 6 = Sunday


    start_time: Mapped[time] = mapped_column(
        Time,
        nullable=False
    )

    end_time: Mapped[time] = mapped_column(
        Time,
        nullable=False
    )

    slot_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    max_bookings: Mapped[int] = mapped_column(
        Integer,
         server_default="1",
        nullable=False
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


    # Relationships
    doctor: Mapped["Doctor"] = relationship(
        "Doctor",
        back_populates="doctor_working_hours"
    )


    __table_args__ = (
        Index(
            "idx_doctor_working_hours_doctor",
            "doctor_id"
        ),
        Index(
            "idx_doctor_working_hours_weekday",
            "weekday"
        ),
        Index(
            "idx_doctor_working_hours_active",
            "active_flag"
        ),
    )



class DoctorUnavailability(Base):
    """
    Doctor unavailability model.

    Stores periods where doctors are unavailable,
    such as vacations, holidays, sick leave, or blocked periods.
    """

    __tablename__ = "doctor_unavailability"


    unavailability_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )


    doctor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("doctors.doctor_id", ondelete="CASCADE"),
        nullable=False
    )


    start_datetime: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False
    )


    end_datetime: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False
    )


    reason: Mapped[Optional[str]] = mapped_column(
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


    # Relationships
    doctor: Mapped["Doctor"] = relationship(
        "Doctor",
        back_populates="doctor_unavailabilities"
    )


    __table_args__ = (
        Index(
            "idx_doctor_unavailability_doctor",
            "doctor_id"
        ),
        Index(
            "idx_doctor_unavailability_dates",
            "start_datetime",
            "end_datetime"
        ),
    )