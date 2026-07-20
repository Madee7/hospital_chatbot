"""Patient lookup and create helpers."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models.patient_models import Patient


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_person_name(name: str | None) -> str:
    """Collapse whitespace and strip; does not change letter case."""
    return _WHITESPACE_RE.sub(" ", (name or "").strip())


def name_part_count(name: str | None) -> int:
    cleaned = normalize_person_name(name)
    if not cleaned:
        return 0
    return len(cleaned.split(" "))


def is_triple_name(name: str | None) -> bool:
    """Require at least three name parts (اسم ثلاثي)."""
    return name_part_count(name) >= 3


def find_patient_by_phone(
    db: Session,
    *,
    clinic_id: int,
    whatsapp_phone: str,
) -> Patient | None:
    return (
        db.query(Patient)
        .filter(
            Patient.clinic_id == clinic_id,
            Patient.whatsapp_phone == whatsapp_phone,
        )
        .one_or_none()
    )


def get_or_create_patient(
    db: Session,
    *,
    tenant_id: int,
    clinic_id: int,
    whatsapp_phone: str,
    name: str | None = None,
    dob: str | None = None,
    created_by: str = "bot",
) -> Patient:
    """Find patient by clinic + WhatsApp phone, or create a new profile."""
    patient = find_patient_by_phone(
        db, clinic_id=clinic_id, whatsapp_phone=whatsapp_phone
    )
    if patient:
        if name and not patient.name:
            patient.name = normalize_person_name(name)
            patient.updated_by = created_by
        if dob:
            patient.dob = dob
            patient.updated_by = created_by
        return patient

    patient = Patient(
        tenant_id=tenant_id,
        clinic_id=clinic_id,
        whatsapp_phone=whatsapp_phone,
        name=normalize_person_name(name) if name else None,
        dob=dob,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(patient)
    db.flush()
    return patient
