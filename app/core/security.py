"""Password hashing helpers for dashboard admin users."""

from __future__ import annotations

import bcrypt


def hash_password(plain: str) -> str:
    """Return a bcrypt hash string for storage on AdminUser.password_hash."""
    raw = (plain or "").encode("utf-8")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, password_hash: str | None) -> bool:
    """True when plain matches the stored bcrypt hash."""
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            (plain or "").encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False
