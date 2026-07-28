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
    "أعصاب": (
        "أعصاب",
        "عصاب",
        "اعصاب",
        "أصاب",  # Whisper often writes أعصاب as أصاب
        "اصاب",
        "عنايزة",
        "اسااب",
        "neurology",
        "neuro",
        "asaab",
        "asab",
    ),
    "نساء": (
        "نساء",
        "توليد",
        "نسا",
        "نيسا",  # Whisper often writes نسا as نيسا
        "تسا",
        "تساء",
        "النسا",
        "النساء",
        "نساء وتوليد",
        "النساء والتوليد",
        "نسا وتوليد",
        "obgyn",
        "ob/gyn",
        "gynecology",
        "gynaecology",
    ),
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
    return fuzzy_specialty_canonical(text) is not None


def fuzzy_specialty_canonical(text: str | None) -> str | None:
    """Return canonical specialty for exact or near-miss aliases (عصاب→أعصاب)."""
    if not text or not str(text).strip():
        return None
    stripped = re.sub(
        r"^(د\.|دكتور|الدكتور|dr\.?)\s*",
        "",
        str(text).strip(),
        flags=re.I,
    ).strip()
    if not stripped:
        return None
    needle = _norm_ar(stripped)
    needle_al = _strip_al(needle)

    def _edit_dist(a: str, b: str) -> int:
        if a == b:
            return 0
        if abs(len(a) - len(b)) > 1:
            return 99
        if len(a) < len(b):
            a, b = b, a
        # a longer by at most 1, or same length
        if len(a) == len(b):
            return sum(x != y for x, y in zip(a, b))
        for i in range(len(a)):
            if a[:i] + a[i + 1 :] == b:
                return 1
        return 99

    # Pass 1: exact (incl. leading-alef variants) — عصاب must hit أعصاب, not عظام.
    exact_hit: str | None = None
    near_hit: str | None = None
    near_dist = 99
    for canonical, aliases in _SPECIALTY_ALIASES.items():
        for word in (canonical, *aliases):
            w = _norm_ar(word)
            w_al = _strip_al(w)
            if needle == w or needle_al == w_al or needle.lstrip("ا") == w.lstrip("ا"):
                exact_hit = canonical
                break
            d = min(_edit_dist(needle, w), _edit_dist(needle_al, w_al))
            if d <= 1 and d < near_dist:
                near_dist = d
                near_hit = canonical
        if exact_hit:
            break
    return exact_hit or near_hit


def _norm_ar(text: str) -> str:
    """Normalize Arabic letters for loose matching (أ/إ/آ→ا, ة→ه, ى→ي)."""
    s = (text or "").strip().lower()
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي")):
        s = s.replace(src, dst)
    return re.sub(r"\s+", " ", s)


def _strip_al(token: str) -> str:
    """Drop the Arabic definite article 'ال' so 'الأسنان' matches 'أسنان'."""
    if token.startswith("ال") and len(token) > 3:
        return token[2:]
    return token


def _word_match(blob: str | None, needle: str | None) -> bool:
    """Whole-word / phrase containment on normalized text.

    Respects word boundaries so a short specialty alias can't match *inside*
    an unrelated word — e.g. the alias 'سن' (tooth) must NOT match inside the
    doctor name 'حسن' (Hassan), which previously misrouted a 'Dr. Dina Hassan'
    booking to the dental department. Tolerates the Arabic definite article
    ('ال') so 'الأسنان' still matches the alias 'أسنان'.
    """
    b = _norm_ar(blob or "")
    n = _norm_ar(needle or "")
    if not b or not n:
        return False
    if f" {n} " in f" {b} ":
        return True

    b_tokens = [_strip_al(t) for t in b.split(" ") if t]
    n_tokens = [_strip_al(t) for t in n.split(" ") if t]
    if not b_tokens or not n_tokens:
        return False
    for i in range(len(b_tokens) - len(n_tokens) + 1):
        if b_tokens[i : i + len(n_tokens)] == n_tokens:
            return True
    return False


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

    # Alias table (قلب → Cardiology, etc.) — whole-word + fuzzy near-miss
    fuzzy_canonical = fuzzy_specialty_canonical(cleaned)
    if fuzzy_canonical:
        for _canonical, aliases in _SPECIALTY_ALIASES.items():
            if _canonical != fuzzy_canonical and fuzzy_canonical not in aliases:
                continue
            for dept in departments:
                blob = _dept_blob(dept)
                if any(_word_match(blob, a) for a in aliases) or _word_match(
                    blob, fuzzy_canonical
                ):
                    return dept
        # Fall through to name-based match using the canonical form
        cleaned = _norm_ar(fuzzy_canonical)

    for _canonical, aliases in _SPECIALTY_ALIASES.items():
        if any(_word_match(cleaned, a) for a in aliases):
            for dept in departments:
                blob = _dept_blob(dept)
                if any(_word_match(blob, a) for a in aliases):
                    return dept

    # Soft containment (min 2 chars for Arabic specialty words like قلب)
    if len(cleaned) < 2:
        return None
    for dept in departments:
        blob = _dept_blob(dept)
        if blob and (_word_match(blob, cleaned) or _word_match(cleaned, blob)):
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
            if _word_match(blob, label):
                return dept
    for aliases in _SPECIALTY_ALIASES.values():
        for alias in aliases:
            if _word_match(blob, alias):
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
    from app.core import i18n_bot as i18n

    dept_en = doctor.department.name_en if doctor.department else None
    dept_ar = doctor.department.name_ar if doctor.department else None
    normalized = i18n.normalize_doctor_bilingual_fields(
        doctor,
        department_en=dept_en,
        department_ar=dept_ar,
    )
    return {
        "doctor_id": doctor.doctor_id,
        "name_en": normalized["name_en"] or doctor.name_en,
        "name_ar": normalized["name_ar"] or doctor.name_ar,
        "title": doctor.title,
        "specialization": doctor.specialization,
        "photo_url": doctor.photo_url,
        "department_id": doctor.department_id,
        "department_en": dept_en,
        "department_ar": dept_ar,
        "bio": normalized["bio"],
        "bio_en": normalized["bio_en"],
    }
