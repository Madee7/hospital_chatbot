"""WhatsApp Flows helpers for doctor picker (ImageCarousel + radio)."""

from __future__ import annotations

import base64
import io
import json
import logging
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.core.config import DEFAULT_CLINIC_ID, USE_DOCTOR_FLOW, WHATSAPP_FLOW_ID
from app.models.doctor_models import Doctor
from app.services.doctor_service import (
    get_doctor,
    list_active_doctors,
    list_doctors_by_department,
)

logger = logging.getLogger(__name__)

# ImageCarousel max is 3 images per Meta Flows spec.
FLOW_MAX_CAROUSEL_IMAGES = 3
FLOW_MAX_DOCTORS = 5
_MAX_IMAGE_BYTES = 80_000


def _placeholder_jpeg_b64() -> str:
    try:
        from PIL import Image

        img = Image.new("RGB", (400, 300), (32, 96, 160))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=50)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        # 1x1 PNG as last resort
        return (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )


def flow_enabled() -> bool:
    return bool(USE_DOCTOR_FLOW and WHATSAPP_FLOW_ID)


def _image_to_jpeg_b64(content: bytes) -> str | None:
    """Resize/compress to stay under Flow payload limits."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(content)).convert("RGB")
        img.thumbnail((480, 480))
        buf = io.BytesIO()
        quality = 70
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        while buf.tell() > _MAX_IMAGE_BYTES and quality > 35:
            quality -= 10
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        logger.warning("Could not compress doctor image: %s", exc)
        return None


def _fetch_image_b64(url: str | None) -> str:
    if not url:
        return _placeholder_jpeg_b64()
    try:
        response = requests.get(url, timeout=12)
        response.raise_for_status()
        encoded = _image_to_jpeg_b64(response.content)
        return encoded or _placeholder_jpeg_b64()
    except Exception as exc:
        logger.warning("Doctor photo fetch failed (%s): %s", url, exc)
        return _placeholder_jpeg_b64()


def build_doctor_picker_data(
    db: Session,
    *,
    clinic_id: int = DEFAULT_CLINIC_ID,
    department_id: int | None = None,
    lang: str = "ar",
) -> dict[str, Any] | None:
    """Build Flow initial screen data (images + radio options) from DB."""
    from app.core import i18n_bot as i18n

    if department_id:
        doctors = list_doctors_by_department(
            db,
            clinic_id=clinic_id,
            department_id=department_id,
            limit=FLOW_MAX_DOCTORS,
        )
    else:
        doctors = list_active_doctors(db, clinic_id, limit=FLOW_MAX_DOCTORS)

    if not doctors:
        return None

    images: list[dict[str, str]] = []
    options: list[dict[str, str]] = []
    for doc in doctors:
        fields = i18n.doctor_display_fields(doc, lang)
        name = (fields["name"] or f"Doctor {doc.doctor_id}").strip()
        spec = (fields["specialization"] or fields["title"] or "").strip()
        options.append(
            {
                "id": str(doc.doctor_id),
                "title": name[:30],
                "description": spec[:72],
            }
        )
        if len(images) < FLOW_MAX_CAROUSEL_IMAGES:
            images.append(
                {
                    "src": _fetch_image_b64(doc.photo_url),
                    "alt-text": name[:100],
                }
            )

    # ImageCarousel requires at least 1 image; pad to 2 for nicer swipe demo.
    while len(images) < 2 and images:
        images.append(images[0])

    return {
        "heading": "Available doctors" if i18n.is_english(lang) else "الأطباء المتاحون",
        "images": images,
        "doctors": options,
    }


def parse_flow_completion(response_json: str | dict | None) -> int | None:
    """Extract doctor_id from nfm_reply response_json."""
    if response_json is None:
        return None
    try:
        payload = (
            json.loads(response_json) if isinstance(response_json, str) else response_json
        )
    except (TypeError, json.JSONDecodeError):
        return None

    raw = payload.get("doctor_id")
    if raw is None and isinstance(payload.get("response"), dict):
        raw = payload["response"].get("doctor_id")
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def doctor_exists(db: Session, doctor_id: int, clinic_id: int = DEFAULT_CLINIC_ID) -> Doctor | None:
    return get_doctor(db, doctor_id, clinic_id=clinic_id)
