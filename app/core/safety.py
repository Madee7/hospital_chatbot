"""Safety / BR-015: block medical advice and escalate high-risk language."""

from __future__ import annotations

import re
from typing import Any

from app.core import i18n_bot as i18n

# Demo keyword set (AR + EN). Match → urgent receptionist handover, no clinical advice.
_HIGH_RISK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.I)
    for p in [
        r"\bemergency\b",
        r"\bambulance\b",
        r"\bsuicide\b",
        r"\bkill\s+myself\b",
        r"\bchest\s*pain\b",
        r"\bheart\s*attack\b",
        r"\bstroke\b",
        r"\bcannot\s+breathe\b",
        r"\bcan'?t\s+breathe\b",
        r"\bsevere\s+bleeding\b",
        r"\bunconscious\b",
        r"\boverdose\b",
        r"طوارئ",
        r"إسعاف",
        r"اسعاف",
        r"انتحار",
        r"أقتل\s*نفسي",
        r"اقتل\s*نفسي",
        r"ألم\s*صدر",
        r"الم\s*صدر",
        r"ذبحة",
        r"جلطة",
        r"سكتة",
        r"ما\s*بقدر\s*تنفس",
        r"لا\s*أستطيع\s*التنفس",
        r"نزيف\s*شديد",
        r"فقدان\s*وعي",
        r"تسمم",
        r"جرعة\s*زائدة",
    ]
]


def is_high_risk_medical(text: str | None) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    return any(p.search(raw) for p in _HIGH_RISK_PATTERNS)


def emergency_patient_message(lang: Any = "ar") -> str:
    if i18n.is_english(lang):
        return (
            "If this is a medical emergency, call local emergency services / go to the nearest ER now.\n"
            "I am an appointment assistant only and cannot give medical advice.\n"
            "Connecting you with reception for urgent help."
        )
    return (
        "إذا كانت حالتك طارئة، اتصل بالإسعاف فوراً أو توجه لأقرب طوارئ.\n"
        "أنا مساعد حجز مواعيد فقط ولا أقدم نصيحة طبية.\n"
        "جارٍ تحويلك لموظف الاستقبال للمساعدة العاجلة."
    )


def no_medical_advice_notice(lang: Any = "ar") -> str:
    if i18n.is_english(lang):
        return (
            "I can only help with appointments (book / reschedule / cancel) and clinic info. "
            "I cannot diagnose or give medical advice. For symptoms, please contact reception or emergency services."
        )
    return (
        "أستطيع المساعدة في المواعيد (حجز / تعديل / إلغاء) ومعلومات العيادة فقط. "
        "لا أشخص ولا أقدم نصيحة طبية. للأعراض تواصل مع الاستقبال أو الطوارئ."
    )
