"""Booking API routes for D1 (testable without WhatsApp/OpenAI)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import BOOKING_WINDOW_DAYS, DEFAULT_CLINIC_ID, DEFAULT_TENANT_ID
from app.db.database import get_db
from app.services import booking_service, doctor_service
from app.services.booking_service import BookingError

router = APIRouter(prefix="/booking", tags=["booking"])


class ConfirmBookingRequest(BaseModel):
    whatsapp_phone: str = Field(..., examples=["201000000001"])
    patient_name: str | None = None
    doctor_id: int
    slot_id: int
    reason: str | None = None
    mrn: str | None = None
    dob: str | None = None
    clinic_id: int = DEFAULT_CLINIC_ID
    tenant_id: int = DEFAULT_TENANT_ID


@router.get("/departments")
def api_list_departments(
    clinic_id: int = DEFAULT_CLINIC_ID,
    db: Session = Depends(get_db),
):
    departments = doctor_service.list_departments(db, clinic_id)
    return [
        {
            "department_id": d.department_id,
            "name_en": d.name_en,
            "name_ar": d.name_ar,
            "description": d.description,
        }
        for d in departments
    ]


@router.get("/doctors")
def api_list_doctors(
    department: str | None = None,
    department_id: int | None = None,
    clinic_id: int = DEFAULT_CLINIC_ID,
    limit: int = 5,
    db: Session = Depends(get_db),
):
    dept = doctor_service.find_department(
        db,
        clinic_id,
        name=department,
        department_id=department_id,
    )
    if department or department_id:
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")
        doctors = doctor_service.list_doctors_by_department(
            db,
            clinic_id=clinic_id,
            department_id=dept.department_id,
            limit=limit,
        )
    else:
        doctors = doctor_service.list_active_doctors(db, clinic_id, limit=limit)

    return [doctor_service.doctor_card_payload(d) for d in doctors]


@router.get("/doctors/{doctor_id}/slots")
def api_doctor_slots(
    doctor_id: int,
    clinic_id: int = DEFAULT_CLINIC_ID,
    days_ahead: int = BOOKING_WINDOW_DAYS,
    db: Session = Depends(get_db),
):
    try:
        return booking_service.get_available_dates_and_slots(
            db,
            doctor_id=doctor_id,
            clinic_id=clinic_id,
            days_ahead=days_ahead,
        )
    except BookingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/confirm")
def api_confirm_booking(
    body: ConfirmBookingRequest,
    db: Session = Depends(get_db),
):
    try:
        return booking_service.confirm_booking(
            db,
            tenant_id=body.tenant_id,
            clinic_id=body.clinic_id,
            whatsapp_phone=body.whatsapp_phone,
            patient_name=body.patient_name,
            doctor_id=body.doctor_id,
            slot_id=body.slot_id,
            reason=body.reason,
            mrn=body.mrn,
            dob=body.dob,
        )
    except BookingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
