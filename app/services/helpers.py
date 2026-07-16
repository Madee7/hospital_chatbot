"""Shared booking helpers."""

from __future__ import annotations

import secrets
from datetime import datetime


def generate_appointment_ref(now: datetime | None = None) -> str:
    """Generate a human-readable appointment reference, e.g. APT-20260714-A3F9."""
    ts = (now or datetime.utcnow()).strftime("%Y%m%d")
    suffix = secrets.token_hex(2).upper()
    return f"APT-{ts}-{suffix}"
