"""Doctor and department lookup for booking."""

from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from app.models.core_models import Department
from app.models.doctor_models import Doctor


def list_departments(db: Session, clinic_id: int) -> list[Department]:
    return (
        db.query(Department)
        .filter(
            Department.clinic_id == clinic_id,
            Department.active_flag.is_(True),
        )
        .order_by(Department.name_en.asc(), Department.name_ar.asc())
        .all()
    )


def find_department(
    db: Session,
    clinic_id: int,
    *,
    name: str | None = None,
    department_id: int | None = None,
) -> Department | None:
    query = db.query(Department).filter(
        Department.clinic_id == clinic_id,
        Department.active_flag.is_(True),
    )
    if department_id is not None:
        return query.filter(Department.department_id == department_id).one_or_none()

    if not name:
        return None

    cleaned = name.strip().lower()
    departments = query.all()
    # Exact match first
    for dept in departments:
        candidates = [
            (dept.name_en or "").strip().lower(),
            (dept.name_ar or "").strip().lower(),
        ]
        if cleaned in candidates:
            return dept
    # Soft match only for reasonably long queries to avoid false positives ("ا", "med")
    if len(cleaned) < 3:
        return None
    for dept in departments:
        candidates = [
            (dept.name_en or "").strip().lower(),
            (dept.name_ar or "").strip().lower(),
        ]
        for candidate in candidates:
            if candidate and (cleaned in candidate or candidate in cleaned):
                return dept
    return None


def list_doctors_by_department(
    db: Session,
    *,
    clinic_id: int,
    department_id: int,
    limit: int = 5,
) -> list[Doctor]:
    return (
        db.query(Doctor)
        .options(joinedload(Doctor.department))
        .filter(
            Doctor.clinic_id == clinic_id,
            Doctor.department_id == department_id,
            Doctor.active_flag.is_(True),
        )
        .order_by(Doctor.doctor_id.asc())
        .limit(limit)
        .all()
    )


def list_active_doctors(db: Session, clinic_id: int, limit: int = 20) -> list[Doctor]:
    return (
        db.query(Doctor)
        .options(joinedload(Doctor.department))
        .filter(
            Doctor.clinic_id == clinic_id,
            Doctor.active_flag.is_(True),
        )
        .order_by(Doctor.name_en.asc(), Doctor.name_ar.asc())
        .limit(limit)
        .all()
    )


def get_doctor(db: Session, doctor_id: int, clinic_id: int | None = None) -> Doctor | None:
    query = db.query(Doctor).options(joinedload(Doctor.department)).filter(
        Doctor.doctor_id == doctor_id,
        Doctor.active_flag.is_(True),
    )
    if clinic_id is not None:
        query = query.filter(Doctor.clinic_id == clinic_id)
    return query.one_or_none()


def doctor_card_payload(doctor: Doctor) -> dict:
    """Compact card payload for WhatsApp / API responses."""
    return {
        "doctor_id": doctor.doctor_id,
        "name_en": doctor.name_en,
        "name_ar": doctor.name_ar,
        "title": doctor.title,
        "specialization": doctor.specialization,
        "photo_url": doctor.photo_url,
        "department_id": doctor.department_id,
        "department_en": doctor.department.name_en if doctor.department else None,
        "department_ar": doctor.department.name_ar if doctor.department else None,
        "bio": doctor.bio,
        "bio_en": getattr(doctor, "bio_en", None),
    }
