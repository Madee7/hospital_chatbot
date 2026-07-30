"""Pydantic schemas for the Booking API routes."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.config import DEFAULT_CLINIC_ID, DEFAULT_TENANT_ID


class ConfirmBookingRequest(BaseModel):
    whatsapp_phone: str = Field(..., examples=["201000000001"])
    patient_name: str | None = None
    doctor_id: int
    slot_id: int
    reason: str | None = None
    dob: str | None = None
    clinic_id: int = DEFAULT_CLINIC_ID
    tenant_id: int = DEFAULT_TENANT_ID


class DepartmentResponse(BaseModel):
    department_id: int
    name_en: str | None = None
    name_ar: str | None = None
    description: str | None = None


class DoctorCardResponse(BaseModel):
    doctor_id: int
    name_en: str | None = None
    name_ar: str | None = None
    title: str | None = None
    specialization: str | None = None
    photo_url: str | None = None
    department_id: int
    department_en: str | None = None
    department_ar: str | None = None
    bio: str | None = None
    bio_en: str | None = None


class SlotItemResponse(BaseModel):
    slot_id: int
    slot_start: str
    slot_end: str
    status: str


class DoctorSlotsResponse(BaseModel):
    doctor_id: int
    doctor_name_ar: str | None = None
    doctor_name_en: str | None = None
    dates: dict[str, list[SlotItemResponse]]
    slot_count: int


class ConfirmBookingResponse(BaseModel):
    status: str
    appointment_id: int
    appointment_ref: str
    patient_id: int
    doctor_id: int
    doctor_name_ar: str | None = None
    doctor_name_en: str | None = None
    specialization: str | None = None
    slot_id: int
    slot_start: str
    slot_end: str
    conversation_id: int
    reminders_created: int
