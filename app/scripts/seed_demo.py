"""
Seed MVP demo data: tenant, clinic, all departments, doctors, and working hours.

Fully reproducible demo dataset (9 departments, 16 doctors) with bilingual
(Arabic + English) names/bios so the whole clinic can be recreated from scripts.

Usage:
  python -m app.scripts.seed_demo
"""

from __future__ import annotations

import os
from datetime import time

from sqlalchemy import text

from app.core.security import hash_password
from app.db.database import SessionLocal, create_tables, engine
from app.db.enums import Language
from app.models.admin_models import (
    ROLE_CLINIC_ADMIN,
    ROLE_COMPANY_ADMIN,
    AdminUser,
    AdminUserClinic,
    ConfigSetting,
)
from app.models.core_models import Clinic, Department, Tenant
from app.models.doctor_models import Doctor, DoctorWorkingHours


PHOTO_MALE = (
    "https://static.vecteezy.com/system/resources/previews/026/375/416/"
    "large_2x/ai-generative-portrait-of-confident-male-doctor-in-white-coat-"
    "and-stethoscope-standing-with-arms-crossed-and-looking-at-camera-photo.jpg"
)
PHOTO_FEMALE = (
    "https://static.vecteezy.com/system/resources/previews/005/130/413/"
    "large_2x/smart-woman-doctor-is-holding-stethoscope-free-photo.jpg"
)
PHOTO_SENIOR = (
    "https://static.vecteezy.com/system/resources/previews/004/623/301/"
    "large_2x/successful-senior-doctor-in-hospital-cabinet-photo.jpg"
)


# All departments (bilingual). Keyed by name_en for doctor → department linking.
DEPARTMENTS: list[dict] = [
    {"name_en": "Cardiology", "name_ar": "قلب", "description": "Cardiology / أمراض القلب"},
    {"name_en": "Orthopedics", "name_ar": "عظام", "description": "Orthopedics / جراحة العظام"},
    {"name_en": "Dermatology", "name_ar": "جلدية", "description": "Dermatology / الأمراض الجلدية"},
    {"name_en": "Pediatrics", "name_ar": "أطفال", "description": "Pediatrics / طب الأطفال"},
    {"name_en": "Ophthalmology", "name_ar": "عيون", "description": "Ophthalmology / طب العيون"},
    {"name_en": "Dentistry", "name_ar": "أسنان", "description": "Dentistry / طب الأسنان"},
    {"name_en": "Internal Medicine", "name_ar": "باطنة", "description": "Internal Medicine / الباطنة"},
    {"name_en": "Neurology", "name_ar": "أعصاب", "description": "Neurology / المخ والأعصاب"},
    {
        "name_en": "Obstetrics & Gynecology",
        "name_ar": "نساء وتوليد",
        "description": "OB/GYN / النساء والتوليد",
    },
]


# All doctors (bilingual). `department` links to DEPARTMENTS[*].name_en.
# Each doctor's working hours share one start/end across the listed weekdays
# (0=Mon … 6=Sun), 30-min slots.
DOCTORS: list[dict] = [
    {
        "name_en": "Dr. Ahmed Samir",
        "name_ar": "د. أحمد سمير",
        "title": "Consultant",
        "specialization": "Cardiology",
        "department": "Cardiology",
        "bio": "استشاري قلب — خبرة 12 سنة",
        "bio_en": "Cardiology consultant — 12 years experience",
        "photo_url": PHOTO_MALE,
        "weekdays": [0, 2, 4],
        "start": time(9, 0),
        "end": time(13, 0),
    },
    {
        "name_en": "Dr. Rania Mamdouh",
        "name_ar": "د. رانيا ممدوح",
        "title": "Specialist",
        "specialization": "Cardiology",
        "department": "Cardiology",
        "bio": "أخصائي قلب وأوعية — خبرة 8 سنوات",
        "bio_en": "Cardiology & vascular specialist — 8 years experience",
        "photo_url": PHOTO_FEMALE,
        "weekdays": [1, 3],
        "start": time(14, 0),
        "end": time(18, 0),
    },
    {
        "name_en": "Dr. Karim Sherif",
        "name_ar": "د. كريم شريف",
        "title": "Consultant",
        "specialization": "Cardiology",
        "department": "Cardiology",
        "bio": "استشاري قسطرة قلب — خبرة 10 سنوات",
        "bio_en": "Cardiac catheterization consultant — 10 years experience",
        "photo_url": PHOTO_SENIOR,
        "weekdays": [0, 1, 3],
        "start": time(10, 0),
        "end": time(14, 0),
    },
    {
        "name_en": "Dr. Nour El-Din",
        "name_ar": "د. نور الدين",
        "title": "Specialist",
        "specialization": "Cardiology",
        "department": "Cardiology",
        "bio": "أخصائي قلب أطفال وكبار — خبرة 6 سنوات",
        "bio_en": "Adult & pediatric cardiology specialist — 6 years experience",
        "photo_url": PHOTO_MALE,
        "weekdays": [2, 5],
        "start": time(16, 0),
        "end": time(20, 0),
    },
    {
        "name_en": "Dr. Hany Farouk",
        "name_ar": "د. هاني فاروق",
        "title": "Consultant",
        "specialization": "Orthopedics",
        "department": "Orthopedics",
        "bio": "استشاري عظام ومفاصل — خبرة 15 سنة",
        "bio_en": "Orthopedics & joints consultant — 15 years experience",
        "photo_url": PHOTO_SENIOR,
        "weekdays": [0, 2, 4],
        "start": time(9, 0),
        "end": time(13, 0),
    },
    {
        "name_en": "Dr. Sara Adel",
        "name_ar": "د. سارة عادل",
        "title": "Specialist",
        "specialization": "Orthopedics",
        "department": "Orthopedics",
        "bio": "أخصائي عظام رياضية — خبرة 7 سنوات",
        "bio_en": "Sports orthopedics specialist — 7 years experience",
        "photo_url": PHOTO_FEMALE,
        "weekdays": [1, 3, 5],
        "start": time(14, 0),
        "end": time(18, 0),
    },
    {
        "name_en": "Dr. Mona Youssef",
        "name_ar": "د. منى يوسف",
        "title": "Consultant",
        "specialization": "Dermatology",
        "department": "Dermatology",
        "bio": "استشاري جلدية وتجميل — خبرة 11 سنة",
        "bio_en": "Dermatology & aesthetics consultant — 11 years experience",
        "photo_url": PHOTO_FEMALE,
        "weekdays": [0, 2, 3],
        "start": time(10, 0),
        "end": time(14, 0),
    },
    {
        "name_en": "Dr. Tamer Nabil",
        "name_ar": "د. تامر نبيل",
        "title": "Specialist",
        "specialization": "Dermatology",
        "department": "Dermatology",
        "bio": "أخصائي جلدية وليزر — خبرة 6 سنوات",
        "bio_en": "Dermatology & laser specialist — 6 years experience",
        "photo_url": PHOTO_MALE,
        "weekdays": [1, 4],
        "start": time(16, 0),
        "end": time(20, 0),
    },
    {
        "name_en": "Dr. Dina Hassan",
        "name_ar": "د. دينا حسن",
        "title": "Consultant",
        "specialization": "Pediatrics",
        "department": "Pediatrics",
        "bio": "استشاري أطفال وحديثي الولادة — خبرة 14 سنة",
        "bio_en": "Pediatrics & neonatology consultant — 14 years experience",
        "photo_url": PHOTO_FEMALE,
        "weekdays": [0, 1, 3],
        "start": time(9, 0),
        "end": time(13, 0),
    },
    {
        "name_en": "Dr. Omar Khaled",
        "name_ar": "د. عمر خالد",
        "title": "Specialist",
        "specialization": "Pediatrics",
        "department": "Pediatrics",
        "bio": "أخصائي أطفال — خبرة 5 سنوات",
        "bio_en": "Pediatrics specialist — 5 years experience",
        "photo_url": PHOTO_MALE,
        "weekdays": [2, 4, 5],
        "start": time(15, 0),
        "end": time(19, 0),
    },
    {
        "name_en": "Dr. Yasser Magdy",
        "name_ar": "د. ياسر مجدي",
        "title": "Consultant",
        "specialization": "Ophthalmology",
        "department": "Ophthalmology",
        "bio": "استشاري عيون وجراحة الشبكية — خبرة 13 سنة",
        "bio_en": "Ophthalmology & retina consultant — 13 years experience",
        "photo_url": PHOTO_SENIOR,
        "weekdays": [0, 2, 4],
        "start": time(10, 0),
        "end": time(14, 0),
    },
    {
        "name_en": "Dr. Heba Mostafa",
        "name_ar": "د. هبة مصطفى",
        "title": "Specialist",
        "specialization": "Dentistry",
        "department": "Dentistry",
        "bio": "أخصائي أسنان وتقويم — خبرة 8 سنوات",
        "bio_en": "Dentistry & orthodontics specialist — 8 years experience",
        "photo_url": PHOTO_FEMALE,
        "weekdays": [1, 3, 5],
        "start": time(11, 0),
        "end": time(16, 0),
    },
    {
        "name_en": "Dr. Mahmoud Said",
        "name_ar": "د. محمود سعيد",
        "title": "Consultant",
        "specialization": "Internal Medicine",
        "department": "Internal Medicine",
        "bio": "استشاري باطنة عامة — خبرة 16 سنة",
        "bio_en": "Internal medicine consultant — 16 years experience",
        "photo_url": PHOTO_SENIOR,
        "weekdays": [0, 1, 2, 3],
        "start": time(9, 0),
        "end": time(12, 0),
    },
    {
        "name_en": "Dr. Laila Ibrahim",
        "name_ar": "د. ليلى إبراهيم",
        "title": "Consultant",
        "specialization": "Neurology",
        "department": "Neurology",
        "bio": "استشاري مخ وأعصاب — خبرة 12 سنة",
        "bio_en": "Neurology consultant — 12 years experience",
        "photo_url": PHOTO_FEMALE,
        "weekdays": [1, 3, 4],
        "start": time(13, 0),
        "end": time(17, 0),
    },
    {
        "name_en": "Dr. Noha Fathy",
        "name_ar": "د. نهى فتحي",
        "title": "Consultant",
        "specialization": "Obstetrics & Gynecology",
        "department": "Obstetrics & Gynecology",
        "bio": "استشاري نساء وتوليد — خبرة 10 سنوات",
        "bio_en": "OB/GYN consultant — 10 years experience",
        "photo_url": PHOTO_FEMALE,
        "weekdays": [0, 2, 5],
        "start": time(10, 0),
        "end": time(14, 0),
    },
    {
        "name_en": "Dr. Amr Selim",
        "name_ar": "د. عمرو سليم",
        "title": "Specialist",
        "specialization": "Obstetrics & Gynecology",
        "department": "Obstetrics & Gynecology",
        "bio": "أخصائي نساء وتوليد — خبرة 6 سنوات",
        "bio_en": "OB/GYN specialist — 6 years experience",
        "photo_url": PHOTO_MALE,
        "weekdays": [1, 4],
        "start": time(16, 0),
        "end": time(20, 0),
    },
]


def _ensure_doctor_bio_en_column() -> None:
    """Add bio_en if missing (demo DBs created before bilingual bios)."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE doctors ADD COLUMN IF NOT EXISTS bio_en TEXT"
            )
        )


def _synthesize_bio_en(doctor: Doctor) -> str:
    from app.core.i18n_bot import has_arabic_script, localize_specialty, localize_title

    title = localize_title(doctor.title, "en") or "Specialist"
    if has_arabic_script(title):
        title = "Specialist"
    spec = localize_specialty(doctor.specialization, "en") or "Medicine"
    if has_arabic_script(spec):
        spec = "Medicine"
    return f"{title} in {spec}"


def _backfill_missing_bio_en(db, clinic_id: int) -> int:
    """Ensure every doctor has bio_en so English WhatsApp cards never fall back to Arabic."""
    updated = 0
    doctors = db.query(Doctor).filter(Doctor.clinic_id == clinic_id).all()
    for doctor in doctors:
        if (getattr(doctor, "bio_en", None) or "").strip():
            continue
        doctor.bio_en = _synthesize_bio_en(doctor)
        doctor.updated_by = "seed"
        updated += 1
    return updated


def _seed_departments(db, clinic_id: int) -> dict[str, int]:
    """Create every department (idempotent by name_en). Returns name_en → id map."""
    dept_ids: dict[str, int] = {}
    for spec in DEPARTMENTS:
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
                created_by="seed",
                updated_by="seed",
            )
            db.add(dept)
            db.flush()
        else:
            # Keep bilingual metadata fresh on re-seed.
            dept.name_ar = spec["name_ar"]
            dept.description = spec["description"]
            dept.updated_by = "seed"
        dept_ids[spec["name_en"]] = dept.department_id
    return dept_ids


def _seed_doctors(db, tenant_id: int, clinic_id: int, dept_ids: dict[str, int]) -> None:
    """Create every doctor + working hours (idempotent by name_en)."""
    for spec in DOCTORS:
        department_id = dept_ids[spec["department"]]
        existing = (
            db.query(Doctor)
            .filter(
                Doctor.clinic_id == clinic_id,
                Doctor.name_en == spec["name_en"],
            )
            .one_or_none()
        )
        if existing:
            # Refresh bilingual fields + department link on re-seed.
            existing.name_ar = spec["name_ar"]
            existing.title = spec["title"]
            existing.specialization = spec["specialization"]
            existing.department_id = department_id
            existing.bio = spec["bio"]
            existing.bio_en = spec["bio_en"]
            existing.photo_url = spec["photo_url"]
            existing.updated_by = "seed"
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
            created_by="seed",
            updated_by="seed",
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


def seed() -> None:
    create_tables()
    _ensure_doctor_bio_en_column()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.tenant_id == 1).one_or_none()
        if not tenant:
            tenant = Tenant(
                tenant_id=1,
                tenant_name="Demo Hospital Group",
                status="active",
                plan="mvp",
            )
            db.add(tenant)
            db.flush()

        clinic = db.query(Clinic).filter(Clinic.clinic_id == 1).one_or_none()
        if not clinic:
            clinic = Clinic(
                clinic_id=1,
                tenant_id=tenant.tenant_id,
                clinic_name="دار الشفاء",
                whatsapp_number=None,
                timezone="Africa/Cairo",
                language_default=Language.AR_EG,
                address="Dar Al Shfaa",
                status="active",
                created_by="seed",
                updated_by="seed",
            )
            db.add(clinic)
            db.flush()

        dept_ids = _seed_departments(db, clinic.clinic_id)
        _seed_doctors(db, tenant.tenant_id, clinic.clinic_id, dept_ids)

        bootstrap_pw = (
            os.getenv("ADMIN_DASHBOARD_PASSWORD")
            or os.getenv("ADMIN_BOOTSTRAP_PASSWORD")
            or "admin123"
        )
        pw_hash = hash_password(bootstrap_pw)

        company = (
            db.query(AdminUser)
            .filter(AdminUser.email == "admin@demo.local")
            .one_or_none()
        )
        if not company:
            company = AdminUser(
                tenant_id=tenant.tenant_id,
                email="admin@demo.local",
                role=ROLE_COMPANY_ADMIN,
                password_hash=pw_hash,
                active_flag=True,
                created_by="seed",
                updated_by="seed",
            )
            db.add(company)
            db.flush()
        else:
            company.role = ROLE_COMPANY_ADMIN
            if not company.password_hash:
                company.password_hash = pw_hash
            company.active_flag = True
            company.updated_by = "seed"

        clinic_admin = (
            db.query(AdminUser)
            .filter(AdminUser.email == "clinic@demo.local")
            .one_or_none()
        )
        if not clinic_admin:
            clinic_admin = AdminUser(
                tenant_id=tenant.tenant_id,
                email="clinic@demo.local",
                role=ROLE_CLINIC_ADMIN,
                password_hash=pw_hash,
                active_flag=True,
                created_by="seed",
                updated_by="seed",
            )
            db.add(clinic_admin)
            db.flush()
            db.add(
                AdminUserClinic(
                    user_id=clinic_admin.user_id,
                    clinic_id=clinic.clinic_id,
                )
            )
        else:
            clinic_admin.role = ROLE_CLINIC_ADMIN
            if not clinic_admin.password_hash:
                clinic_admin.password_hash = pw_hash
            clinic_admin.active_flag = True
            clinic_admin.updated_by = "seed"
            has_link = (
                db.query(AdminUserClinic)
                .filter(
                    AdminUserClinic.user_id == clinic_admin.user_id,
                    AdminUserClinic.clinic_id == clinic.clinic_id,
                )
                .one_or_none()
            )
            if not has_link:
                db.add(
                    AdminUserClinic(
                        user_id=clinic_admin.user_id,
                        clinic_id=clinic.clinic_id,
                    )
                )

        if not (
            db.query(ConfigSetting)
            .filter(
                ConfigSetting.clinic_id == clinic.clinic_id,
                ConfigSetting.key == "booking_slot_minutes",
            )
            .one_or_none()
        ):
            db.add(
                ConfigSetting(
                    tenant_id=tenant.tenant_id,
                    clinic_id=clinic.clinic_id,
                    key="booking_slot_minutes",
                    value="30",
                    created_by="seed",
                    updated_by="seed",
                )
            )

        default_maps = (
            "https://www.google.com/maps/place/30%C2%B002'49.6%22N+31%C2%B010'57.1%22E/"
            "@30.0470963,31.1847278,17z/data=!3m1!4b1!4m4!3m3!8m2!3d30.0470963!4d31.1825391?entry=ttu"
        )
        if not (
            db.query(ConfigSetting)
            .filter(
                ConfigSetting.clinic_id == clinic.clinic_id,
                ConfigSetting.key == "clinic_maps_url",
            )
            .one_or_none()
        ):
            db.add(
                ConfigSetting(
                    tenant_id=tenant.tenant_id,
                    clinic_id=clinic.clinic_id,
                    key="clinic_maps_url",
                    value=default_maps,
                    created_by="seed",
                    updated_by="seed",
                )
            )

        db.commit()
        backfilled = _backfill_missing_bio_en(db, clinic.clinic_id)
        db.commit()
        print(
            f"Seed completed: tenant=1 clinic=1 "
            f"departments={len(DEPARTMENTS)} doctors={len(DOCTORS)} ready"
            + (f" (bio_en backfilled={backfilled})." if backfilled else ".")
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
