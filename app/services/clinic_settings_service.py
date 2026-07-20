"""Clinic-level settings loaded from dashboard config (with env fallbacks)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.core import i18n_bot as i18n
from app.core.config import CLINIC_MAPS_URL
from app.models.admin_models import ConfigSetting

CONFIG_KEY_MAPS_URL = "clinic_maps_url"


def shorten_google_maps_url(url: str) -> str:
    """Return a shorter Google Maps link that points to the same coordinates."""
    raw = (url or "").strip()
    if not raw:
        return ""

    pin = re.search(r"3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", raw)
    if pin:
        return f"https://maps.google.com/?q={pin.group(1)},{pin.group(2)}"

    center = re.search(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", raw)
    if center:
        return f"https://maps.google.com/?q={center.group(1)},{center.group(2)}"

    if "google.com/maps" in raw and "?" in raw:
        return raw.split("?", 1)[0]
    return raw


def get_clinic_maps_url(db: Session | None, clinic_id: int) -> str:
    """Dashboard config first, then ``CLINIC_MAPS_URL`` env fallback."""
    if db is not None:
        row = (
            db.query(ConfigSetting)
            .filter(
                ConfigSetting.clinic_id == clinic_id,
                ConfigSetting.key == CONFIG_KEY_MAPS_URL,
            )
            .one_or_none()
        )
        if row and (row.value or "").strip():
            return row.value.strip()
    return (CLINIC_MAPS_URL or "").strip()


def format_clinic_location_display(
    db: Session | None,
    clinic_id: int,
    lang: Any,
) -> str:
    """Clinic name plus shortened maps URL on the next line (same WhatsApp message)."""
    label = i18n.clinic_location(lang)
    maps_url = get_clinic_maps_url(db, clinic_id)
    if not maps_url:
        return label
    short = shorten_google_maps_url(maps_url)
    if not short:
        return label
    # Same format as before: "Dar Al Shfaa\nhttps://maps.google.com/?q=..."
    return f"{label}\n{short}"
