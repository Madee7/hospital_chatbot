"""
Bulk test seed: many departments + doctors for WhatsApp list pagination tests.

Safe to re-run (idempotent by name_en). Does not remove the original demo doctors.

Usage:
  python -m app.scripts.seed_bulk_test
"""

from __future__ import annotations

from datetime import time

from app.db.database import SessionLocal, create_tables
from app.db.enums import Language
from app.models.core_models import Clinic, Department, Tenant
from app.models.doctor_models import Doctor, DoctorWorkingHours
from app.scripts.seed_demo import (
    PHOTO_FEMALE,
    PHOTO_MALE,
    PHOTO_SENIOR,
    _ensure_doctor_bio_en_column,
    seed as seed_base_demo,
)

# Extra specialties so the departments list exceeds WhatsApp's 10-row page.
EXTRA_DEPARTMENTS: list[dict] = [
    {"name_en": "ENT", "name_ar": "أنف وأذن وحنجرة", "description": "ENT / أنف وأذن"},
    {"name_en": "Urology", "name_ar": "مسالك بولية", "description": "Urology / المسالك"},
    {"name_en": "Psychiatry", "name_ar": "طب نفسي", "description": "Psychiatry / نفسي"},
    {"name_en": "General Surgery", "name_ar": "جراحة عامة", "description": "General Surgery"},
    {"name_en": "Endocrinology", "name_ar": "غدد صماء", "description": "Endocrinology / غدد"},
    {"name_en": "Gastroenterology", "name_ar": "جهاز هضمي", "description": "GI / هضمي"},
    {"name_en": "Pulmonology", "name_ar": "صدرية", "description": "Pulmonology / صدر"},
    {"name_en": "Rheumatology", "name_ar": "روماتيزم", "description": "Rheumatology"},
    {"name_en": "Nephrology", "name_ar": "كلى", "description": "Nephrology / كلى"},
    {"name_en": "Oncology", "name_ar": "أورام", "description": "Oncology / أورام"},
    {"name_en": "Radiology", "name_ar": "أشعة", "description": "Radiology / أشعة"},
    {"name_en": "Physiotherapy", "name_ar": "علاج طبيعي", "description": "Physiotherapy"},
    {"name_en": "Family Medicine", "name_ar": "طب أسرة", "description": "Family Medicine"},
    {"name_en": "Emergency", "name_ar": "طوارئ", "description": "Emergency / طوارئ"},
    {"name_en": "Plastic Surgery", "name_ar": "جراحة تجميل", "description": "Plastic Surgery"},
]

_EN_FIRST = [
    "Youssef", "Hassan", "Ibrahim", "Mostafa", "Khaled", "Walid", "Tarek",
    "Sherif", "Fady", "Bassem", "Hossam", "Ayman", "Magdy", "Samy", "Ramy",
    "Nader", "Ashraf", "Emad", "Hatem", "Ziad", "Omar", "Ali", "Mahmoud",
    "Sara", "Mona", "Dina", "Noha", "Heba", "Laila", "Rana", "Yara", "Farah",
    "Nour", "Hana", "Maya", "Salma", "Reem", "Jana", "Layla", "Marwa",
]
_AR_FIRST = [
    "يوسف", "حسن", "إبراهيم", "مصطفى", "خالد", "وليد", "طارق",
    "شريف", "فادي", "باسم", "حسام", "أيمن", "مجدي", "سامي", "رامي",
    "نادر", "أشرف", "عماد", "حاتم", "زياد", "عمر", "علي", "محمود",
    "سارة", "منى", "دينا", "نهى", "هبة", "ليلى", "رنا", "يارا", "فرح",
    "نور", "هنا", "مايا", "سلمى", "ريم", "جنى", "ليلى", "مروة",
]
_EN_LAST = [
    "Fouad", "Gamal", "Reda", "Sami", "Lotfy", "Helmy", "Bahnasy", "Shehata",
    "Mansour", "Soliman", "Hegazy", "Barakat", "Zaki", "Fahmy", "Nasr",
    "Habib", "Metwally", "Gaber", "Ezzat", "Shaker",
]
_AR_LAST = [
    "فؤاد", "جمال", "رضا", "سامي", "لطفي", "حلمي", "بهنسي", "شحاتة",
    "منصور", "سليمان", "حجازي", "بركات", "زكي", "فهمي", "نصر",
    "حبيب", "متولي", "جابر", "عزت", "شاكر",
]

_CORE_DEPTS = [
    ("Cardiology", "قلب"),
    ("Orthopedics", "عظام"),
    ("Dermatology", "جلدية"),
    ("Pediatrics", "أطفال"),
    ("Ophthalmology", "عيون"),
    ("Dentistry", "أسنان"),
    ("Internal Medicine", "باطنة"),
    ("Neurology", "أعصاب"),
    ("Obstetrics & Gynecology", "نساء وتوليد"),
]


def _all_dept_pairs() -> list[tuple[str, str]]:
    pairs = list(_CORE_DEPTS)
    for d in EXTRA_DEPARTMENTS:
        pairs.append((d["name_en"], d["name_ar"]))
    return pairs


def _build_bulk_doctors(*, per_dept: int = 3) -> list[dict]:
    photos = [PHOTO_MALE, PHOTO_FEMALE, PHOTO_SENIOR]
    titles = [
        ("Consultant", "استشاري"),
        ("Specialist", "أخصائي"),
        ("Senior Specialist", "أخصائي أول"),
    ]
    schedules = [
        ([0, 2, 4], time(9, 0), time(13, 0)),
        ([1, 3], time(14, 0), time(18, 0)),
        ([0, 1, 3], time(10, 0), time(14, 0)),
        ([2, 5], time(16, 0), time(20, 0)),
        ([6], time(9, 0), time(12, 0)),
    ]

    out: list[dict] = []
    name_i = 0
    for dept_en, dept_ar in _all_dept_pairs():
        for n in range(per_dept):
            fi = name_i % len(_EN_FIRST)
            li = (name_i + n) % len(_EN_LAST)
            en_first, ar_first = _EN_FIRST[fi], _AR_FIRST[fi]
            en_last, ar_last = _EN_LAST[li], _AR_LAST[li]
            # Unique EN key for idempotent re-runs.
            name_en = f"Dr. {en_first} {en_last} ({dept_en} {n + 1})"
            name_ar = f"د. {ar_first} {ar_last}"
            title_en, title_ar = titles[n % len(titles)]
            weekdays, start, end = schedules[n % len(schedules)]
            years = 5 + (name_i % 15)
            out.append(
                {
                    "name_en": name_en,
                    "name_ar": name_ar,
                    "title": title_en,
                    "specialization": dept_en,
                    "department": dept_en,
                    "bio": f"{title_ar} {dept_ar} — خبرة {years} سنوات",
                    "bio_en": f"{title_en} in {dept_en} — {years} years experience",
                    "photo_url": photos[name_i % len(photos)],
                    "weekdays": weekdays,
                    "start": start,
                    "end": end,
                }
            )
            name_i += 1
    return out


def _ensure_clinic(db) -> tuple[Tenant, Clinic]:
    tenant = db.query(Tenant).filter(Tenant.tenant_id == 1).one_or_none()
    if not tenant:
        seed_base_demo()
        db.expire_all()
        tenant = db.query(Tenant).filter(Tenant.tenant_id == 1).one()
    clinic = db.query(Clinic).filter(Clinic.clinic_id == 1).one_or_none()
    if not clinic:
        clinic = Clinic(
            clinic_id=1,
            tenant_id=tenant.tenant_id,
            clinic_name="دار الشفاء",
            timezone="Africa/Cairo",
            language_default=Language.AR_EG,
            address="Dar Al Shfaa",
            status="active",
            created_by="seed_bulk",
            updated_by="seed_bulk",
        )
        db.add(clinic)
        db.flush()
    return tenant, clinic


def _seed_extra_departments(db, clinic_id: int) -> dict[str, int]:
    dept_ids: dict[str, int] = {}
    existing = (
        db.query(Department)
        .filter(Department.clinic_id == clinic_id, Department.active_flag.is_(True))
        .all()
    )
    for d in existing:
        if d.name_en:
            dept_ids[d.name_en] = d.department_id

    for spec in EXTRA_DEPARTMENTS:
        dept = (
            db.query(Department)
            .filter(
                Department.clinic_id == clinic_id,
                Department.name_en == spec["name_en"],
            )
            .one_or_none()
        )
        if not dept:
            dept = Department(
                clinic_id=clinic_id,
                name_en=spec["name_en"],
                name_ar=spec["name_ar"],
                description=spec["description"],
                active_flag=True,
                created_by="seed_bulk",
                updated_by="seed_bulk",
            )
            db.add(dept)
            db.flush()
        else:
            dept.name_ar = spec["name_ar"]
            dept.description = spec["description"]
            dept.active_flag = True
            dept.updated_by = "seed_bulk"
        dept_ids[spec["name_en"]] = dept.department_id
    return dept_ids


def _seed_bulk_doctors(
    db,
    *,
    tenant_id: int,
    clinic_id: int,
    dept_ids: dict[str, int],
    per_dept: int = 3,
) -> tuple[int, int]:
    created = 0
    skipped = 0
    for spec in _build_bulk_doctors(per_dept=per_dept):
        department_id = dept_ids.get(spec["department"])
        if not department_id:
            continue
        existing = (
            db.query(Doctor)
            .filter(
                Doctor.clinic_id == clinic_id,
                Doctor.name_en == spec["name_en"],
            )
            .one_or_none()
        )
        if existing:
            existing.active_flag = True
            existing.department_id = department_id
            existing.name_ar = spec["name_ar"]
            existing.specialization = spec["specialization"]
            existing.bio = spec["bio"]
            existing.bio_en = spec["bio_en"]
            existing.updated_by = "seed_bulk"
            skipped += 1
            continue

        doctor = Doctor(
            tenant_id=tenant_id,
            clinic_id=clinic_id,
            department_id=department_id,
            name_en=spec["name_en"],
            name_ar=spec["name_ar"],
            title=spec["title"],
            specialization=spec["specialization"],
            bio=spec["bio"],
            bio_en=spec["bio_en"],
            photo_url=spec["photo_url"],
            active_flag=True,
            created_by="seed_bulk",
            updated_by="seed_bulk",
        )
        db.add(doctor)
        db.flush()
        for weekday in spec["weekdays"]:
            db.add(
                DoctorWorkingHours(
                    doctor_id=doctor.doctor_id,
                    weekday=weekday,
                    start_time=spec["start"],
                    end_time=spec["end"],
                    slot_minutes=30,
                    max_bookings=1,
                    active_flag=True,
                )
            )
        created += 1
    return created, skipped


def seed_bulk(*, per_dept: int = 3) -> None:
    create_tables()
    _ensure_doctor_bio_en_column()
    seed_base_demo()

    db = SessionLocal()
    try:
        tenant, clinic = _ensure_clinic(db)
        dept_ids = _seed_extra_departments(db, clinic.clinic_id)
        created, skipped = _seed_bulk_doctors(
            db,
            tenant_id=tenant.tenant_id,
            clinic_id=clinic.clinic_id,
            dept_ids=dept_ids,
            per_dept=per_dept,
        )
        db.commit()

        dept_count = (
            db.query(Department)
            .filter(
                Department.clinic_id == clinic.clinic_id,
                Department.active_flag.is_(True),
            )
            .count()
        )
        doc_count = (
            db.query(Doctor)
            .filter(Doctor.clinic_id == clinic.clinic_id, Doctor.active_flag.is_(True))
            .count()
        )
        print(
            f"Bulk seed done. departments={dept_count} doctors={doc_count} "
            f"(new_doctors={created}, refreshed={skipped}, per_dept={per_dept})"
        )
        print("Ready to test «More» on specialties and doctors-by-name lists.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_bulk(per_dept=3)
