"""
Usage-related models for the hospital chatbot application.

This module contains models for tracking technical usage, AI provider costs,
latency, and operational metrics for monitoring and billing purposes.
"""

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    DateTime, Float, ForeignKey, Integer, String, Index, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.core_models import Clinic, Tenant


class UsageLog(Base):
    """
    UsageLog model for tracking technical usage and operational metrics.

    Records AI provider costs, latency measurements, token consumption,
    and operational status for monitoring and billing purposes.
    """
    __tablename__ = "usage_logs"

    usage_id: Mapped[int] = mapped_column(Integer, primary_key=True)
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
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    tokens_or_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    cost_estimate: Mapped[Optional[float]] = mapped_column(Float)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), nullable=False)

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

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant")
    clinic: Mapped["Clinic"] = relationship(
        "Clinic",
        back_populates="usage_logs"
    )

    # Indexes
    __table_args__ = (
        Index('idx_usage_log_tenant', 'tenant_id'),
        Index('idx_usage_log_clinic', 'clinic_id'),
        Index('idx_usage_log_provider', 'provider'),
        Index('idx_usage_log_operation', 'operation'),
        Index('idx_usage_log_status', 'status'),
        Index('idx_usage_log_created_at', 'created_at'),
        Index('idx_usage_log_clinic_created', 'clinic_id', 'created_at'),
    )
