"""
Seed MVP demo data: tenant, clinic, Cardiology department, doctors, working hours.

Usage:
  python -m app.scripts.seed_demo
"""

from __future__ import annotations

from datetime import time

from app.db.database import SessionLocal, create_tables
from app.db.enums import Language
from app.models.admin_models import AdminUser, ConfigSetting
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


def seed() -> None:
    create_tables()
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

        cardiology = (
            db.query(Department)
            .filter(
                Department.clinic_id == clinic.clinic_id,
                Department.name_en == "Cardiology",
            )
            .one_or_none()
        )
        if not cardiology:
            cardiology = Department(
                clinic_id=clinic.clinic_id,
                name_en="Cardiology",
                name_ar="قلب",
                description="Cardiology / أمراض القلب",
                active_flag=True,
                created_by="seed",
                updated_by="seed",
            )
            db.add(cardiology)
            db.flush()

        doctors_spec = [
            {
                "name_en": "Dr. Ahmed Samir",
                "name_ar": "د. أحمد سمير",
                "title": "Consultant",
                "specialization": "Cardiology",
                "bio": "استشاري قلب — خبرة 12 سنة",
                "photo_url": PHOTO_MALE,
                "weekdays": [0, 2, 4],  # Mon, Wed, Fri
                "start": time(9, 0),
                "end": time(13, 0),
            },
            {
                "name_en": "Dr. Rania Mamdouh",
                "name_ar": "د. رانيا ممدوح",
                "title": "Specialist",
                "specialization": "Cardiology",
                "bio": "أخصائي قلب وأوعية — خبرة 8 سنوات",
                "photo_url": PHOTO_FEMALE,
                "weekdays": [1, 3],  # Tue, Thu
                "start": time(14, 0),
                "end": time(18, 0),
            },
            {
                "name_en": "Dr. Karim Sherif",
                "name_ar": "د. كريم شريف",
                "title": "Consultant",
                "specialization": "Cardiology",
                "bio": "استشاري قسطرة قلب — خبرة 10 سنوات",
                "photo_url": PHOTO_SENIOR,
                "weekdays": [0, 1, 3],  # Mon, Tue, Thu
                "start": time(10, 0),
                "end": time(14, 0),
            },
            {
                "name_en": "Dr. Nour El-Din",
                "name_ar": "د. نور الدين",
                "title": "Specialist",
                "specialization": "Cardiology",
                "bio": "أخصائي قلب أطفال وكبار — خبرة 6 سنوات",
                "photo_url": PHOTO_MALE,
                "weekdays": [2, 5],  # Wed, Sat
                "start": time(16, 0),
                "end": time(20, 0),
            },
        ]

        for spec in doctors_spec:
            existing = (
                db.query(Doctor)
                .filter(
                    Doctor.clinic_id == clinic.clinic_id,
                    Doctor.name_en == spec["name_en"],
                )
                .one_or_none()
            )
            if existing:
                continue

            doctor = Doctor(
                tenant_id=tenant.tenant_id,
                clinic_id=clinic.clinic_id,
                department_id=cardiology.department_id,
                name_en=spec["name_en"],
                name_ar=spec["name_ar"],
                title=spec["title"],
                specialization=spec["specialization"],
                bio=spec["bio"],
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

        if not db.query(AdminUser).filter(AdminUser.email == "admin@demo.local").one_or_none():
            db.add(
                AdminUser(
                    tenant_id=tenant.tenant_id,
                    email="admin@demo.local",
                    role="admin",
                    active_flag=True,
                    created_by="seed",
                    updated_by="seed",
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
        print("Seed completed: tenant=1 clinic=1 Cardiology doctors ready.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
