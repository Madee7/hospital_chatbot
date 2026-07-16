"""Patient lookup and create helpers."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.patient_models import Patient


def get_or_create_patient(
    db: Session,
    *,
    tenant_id: int,
    clinic_id: int,
    whatsapp_phone: str,
    name: str | None = None,
    mrn: str | None = None,
    dob: str | None = None,
    created_by: str = "bot",
) -> Patient:
    """Find patient by clinic + WhatsApp phone, or create a new profile."""
    patient = (
        db.query(Patient)
        .filter(
            Patient.clinic_id == clinic_id,
            Patient.whatsapp_phone == whatsapp_phone,
        )
        .one_or_none()
    )
    if patient:
        if name and not patient.name:
            patient.name = name
            patient.updated_by = created_by
        if mrn:
            patient.mrn = mrn
            patient.updated_by = created_by
        if dob:
            patient.dob = dob
            patient.updated_by = created_by
        return patient

    patient = Patient(
        tenant_id=tenant_id,
        clinic_id=clinic_id,
        whatsapp_phone=whatsapp_phone,
        name=name,
        mrn=mrn,
        dob=dob,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(patient)
    db.flush()
    return patient
