"""Doctor and department lookup for booking."""

from __future__ import annotations

import re
from sqlalchemy.orm import Session, joinedload

from app.models.core_models import Department
from app.models.doctor_models import Doctor

# Spoken aliases → match against department name_ar / name_en
_SPECIALTY_ALIASES: dict[str, tuple[str, ...]] = {
    "قلب": ("قلب", "قلبية", "القلب", "cardiology", "cardio", "cardiac"),
    "عظام": ("عظام", "orthopedics", "orthopaedics", "ortho"),
    "جلدية": ("جلدية", "جلد", "dermatology", "derma"),
    "أطفال": ("أطفال", "طفل", "pediatrics", "paediatrics", "pediatric"),
    "عيون": ("عيون", "عين", "ophthalmology", "eye"),
    "أسنان": ("أسنان", "سن", "dentistry", "dental", "dentist"),
    "باطنة": ("باطنة", "باطني", "internal medicine", "internal"),
    "أعصاب": ("أعصاب", "neurology", "neuro"),
    "نساء": ("نساء", "توليد", "نسا", "obgyn", "gynecology", "gynaecology"),
}


def specialty_alias_words() -> set[str]:
    """Flattened specialty words/aliases for voice routing (single source of truth)."""
    words: set[str] = set()
    for canonical, aliases in _SPECIALTY_ALIASES.items():
        words.add(canonical)
        words.update(aliases)
    return words


def is_specialty_word(text: str | None) -> bool:
    """True if text (after stripping دكتور/dr) matches a known specialty alias."""
    if not text or not str(text).strip():
        return False
    stripped = re.sub(
        r"^(د\.|دكتور|الدكتور|dr\.?)\s*",
        "",
        str(text).strip(),
        flags=re.I,
    ).strip()
    if not stripped:
        return False
    needle = _norm_ar(stripped)
    for word in specialty_alias_words():
        if needle == _norm_ar(word):
            return True
    return False


def _norm_ar(text: str) -> str:
    """Normalize Arabic letters for loose matching (أ/إ/آ→ا, ة→ه, ى→ي)."""
    s = (text or "").strip().lower()
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي")):
        s = s.replace(src, dst)
    return re.sub(r"\s+", " ", s)


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

    # Strip "دكتور قلب" → "قلب"
    raw = re.sub(
        r"^(د\.|دكتور|الدكتور|dr\.?)\s*",
        "",
        name.strip(),
        flags=re.I,
    ).strip()
    cleaned = _norm_ar(raw)
    if not cleaned:
        return None

    departments = query.all()

    def _dept_blob(dept: Department) -> str:
        return _norm_ar(f"{dept.name_ar or ''} {dept.name_en or ''}")

    # Exact match first
    for dept in departments:
        candidates = [
            _norm_ar(dept.name_en or ""),
            _norm_ar(dept.name_ar or ""),
        ]
        if cleaned in candidates:
            return dept

    # Alias table (قلب → Cardiology, etc.)
    for _canonical, aliases in _SPECIALTY_ALIASES.items():
        alias_norms = {_norm_ar(a) for a in aliases}
        if cleaned in alias_norms or any(a and a in cleaned for a in alias_norms):
            for dept in departments:
                blob = _dept_blob(dept)
                if any(a in blob for a in alias_norms if len(a) >= 2):
                    return dept

    # Soft containment (min 2 chars for Arabic specialty words like قلب)
    if len(cleaned) < 2:
        return None
    for dept in departments:
        blob = _dept_blob(dept)
        if blob and (cleaned in blob or blob in cleaned):
            return dept
    return None


def infer_department_from_text(
    db: Session,
    clinic_id: int,
    text: str | None,
) -> Department | None:
    """Find a department mentioned inside free text / voice transcript."""
    if not text or not text.strip():
        return None
    blob = _norm_ar(text)
    # Prefer longer department names first
    departments = sorted(
        list_departments(db, clinic_id),
        key=lambda d: max(len(d.name_ar or ""), len(d.name_en or "")),
        reverse=True,
    )
    for dept in departments:
        for label in (dept.name_ar, dept.name_en):
            n = _norm_ar(label or "")
            if len(n) >= 2 and n in blob:
                return dept
    for aliases in _SPECIALTY_ALIASES.values():
        for alias in aliases:
            n = _norm_ar(alias)
            if len(n) >= 2 and n in blob:
                found = find_department(db, clinic_id, name=alias)
                if found:
                    return found
    return None


def list_doctors_by_department(
    db: Session,
    *,
    clinic_id: int,
    department_id: int,
    limit: int = 10,
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
