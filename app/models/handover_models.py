"""
Handover-related models for the hospital chatbot application.

This module contains models for human escalation tickets when the chatbot
needs to transfer conversations to staff members for manual handling.
"""

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    DateTime, ForeignKey, Integer, String, Text, Index, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.enums import HandoverPriority, sa_enum

if TYPE_CHECKING:
    from app.models.conversation_models import Conversation


class HandoverCase(Base):
    """
    HandoverCase model representing human escalation tickets.

    Tracks cases where the chatbot needs to transfer conversations
    to human staff members, including priority levels, assignment,
    and resolution status.
    """
    __tablename__ = "handover_cases"

    handover_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("conversations.conversation_id"),
        nullable=False
    )
    reason: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[HandoverPriority] = mapped_column(
        sa_enum(HandoverPriority, length=20),
        nullable=False,
        server_default=HandoverPriority.NORMAL.value,
    )
    assigned_to: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")

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
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="handover_cases"
    )

    # Indexes
    __table_args__ = (
        Index('idx_handover_conversation', 'conversation_id'),
        Index('idx_handover_status', 'status'),
        Index('idx_handover_priority', 'priority'),
        Index('idx_handover_created_at', 'created_at'),
        Index('idx_handover_status_priority', 'status', 'priority'),
        Index('idx_handover_assigned_to', 'assigned_to'),
    )
