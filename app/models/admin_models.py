"""
Admin-related models for the hospital chatbot application.

This module contains models for dashboard users and configurable settings
for managing the hospital chatbot system at tenant and clinic levels.
"""

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, Index, UniqueConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.core_models import Tenant, Clinic


class AdminUser(Base):
    """
    AdminUser model representing dashboard users.

    Tracks users who can manage the hospital chatbot system,
    including their roles, access levels, and login activity.
    """
    __tablename__ = "admin_users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    active_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Audit fields
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    created_by: Mapped[Optional[str]] = mapped_column(String(255))
    updated_by: Mapped[Optional[str]] = mapped_column(String(255))

    # Relationships
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="admin_users"
    )

    # Indexes and constraints
    __table_args__ = (
        UniqueConstraint(
            'tenant_id',
            'email',
            name='uq_admin_user_tenant_email',
        ),
        Index('idx_admin_user_tenant', 'tenant_id'),
        Index('idx_admin_user_email', 'email'),
        Index('idx_admin_user_role', 'role'),
        Index('idx_admin_user_active', 'active_flag'),
    )


class ConfigSetting(Base):
    """
    ConfigSetting model for client-level configurable settings.

    Stores key-value configuration pairs for each clinic,
    allowing customization of chatbot behavior and features.
    """
    __tablename__ = "config_settings"

    setting_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tenants.tenant_id"),
        nullable=False
    )
    clinic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clinics.clinic_id", ondelete="CASCADE"),
        nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[Optional[str]] = mapped_column(Text)

    # Audit fields
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    created_by: Mapped[Optional[str]] = mapped_column(String(255))
    updated_by: Mapped[Optional[str]] = mapped_column(String(255))

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant")
    clinic: Mapped["Clinic"] = relationship(
        "Clinic",
        back_populates="config_settings"
    )

    # Indexes and constraints
    __table_args__ = (
        Index('idx_config_setting_tenant', 'tenant_id'),
        Index('idx_config_setting_clinic', 'clinic_id'),
        Index('idx_config_setting_key', 'key'),
        UniqueConstraint('clinic_id', 'key', name='uq_config_setting_clinic_key'),
    )
