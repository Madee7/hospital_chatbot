"""
Conversation-related models for the hospital chatbot application.

This module contains models for conversations, messages, and voice messages
to track WhatsApp interactions and conversation flow state.
"""

from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Float,
    Index,
    func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.enums import ConversationState, Language, MessageType, sa_enum


if TYPE_CHECKING:
    from app.models.core_models import Clinic, Tenant
    from app.models.patient_models import Patient
    from app.models.handover_models import HandoverCase


class Conversation(Base):
    """
    WhatsApp conversation session.

    Stores chatbot state and patient interaction context.
    Business state should always be persisted here,
    not only in temporary memory.
    """

    __tablename__ = "conversations"

    conversation_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    tenant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tenants.tenant_id"),
        nullable=False
    )

    clinic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clinics.clinic_id"),
        nullable=False
    )

    patient_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("patients.patient_id"),
        nullable=True
    )

    phone: Mapped[str] = mapped_column(
        String(20),
        nullable=False
    )

    state: Mapped[Optional[ConversationState]] = mapped_column(
        sa_enum(ConversationState),
        nullable=True
    )

    language: Mapped[Optional[Language]] = mapped_column(
        sa_enum(Language, length=10),
        nullable=True
    )

    current_intent: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True
    )

    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True
    )

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
        back_populates="conversations"
    )

    patient: Mapped[Optional["Patient"]] = relationship(
        "Patient",
        back_populates="conversations"
    )

    messages: Mapped[List["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan"
    )

    handover_cases: Mapped[List["HandoverCase"]] = relationship(
        "HandoverCase",
        back_populates="conversation",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "idx_conversation_tenant",
            "tenant_id"
        ),
        Index(
            "idx_conversation_clinic",
            "clinic_id"
        ),
        Index(
            "idx_conversation_patient",
            "patient_id"
        ),
        Index(
            "idx_conversation_phone",
            "phone"
        ),
        Index(
            "idx_conversation_state",
            "state"
        ),
        Index(
            "idx_conversation_last_message",
            "last_message_at"
        ),
        Index(
            "idx_conversation_clinic_phone",
            "clinic_id",
            "phone"
        ),
    )


class Message(Base):
    """
    WhatsApp message log.

    Stores inbound and outbound messages including
    text, voice, interactive replies, templates, etc.
    """

    __tablename__ = "messages"

    message_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    conversation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
        nullable=False
    )

    # inbound / outbound
    direction: Mapped[str] = mapped_column(
        String(20),
        nullable=False
    )

    type: Mapped[MessageType] = mapped_column(
        sa_enum(MessageType),
        nullable=False
    )

    text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    whatsapp_message_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True
    )

    # sent, delivered, read, failed
    status: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now()
    )

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
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages"
    )

    voice_message: Mapped[Optional["VoiceMessage"]] = relationship(
        "VoiceMessage",
        back_populates="message",
        uselist=False,
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "idx_message_conversation",
            "conversation_id"
        ),
        Index(
            "idx_message_direction",
            "direction"
        ),
        Index(
            "idx_message_type",
            "type"
        ),
        Index(
            "idx_message_timestamp",
            "timestamp"
        ),
        Index(
            "idx_message_whatsapp_id",
            "whatsapp_message_id"
        ),
        Index(
            "idx_message_status",
            "status"
        ),
        Index(
            "idx_message_conversation_timestamp",
            "conversation_id",
            "timestamp"
        ),
    )


class VoiceMessage(Base):
    """
    Voice message metadata and speech-to-text results.

    Stores media reference, transcript,
    STT provider information and processing status.
    """

    __tablename__ = "voice_messages"

    voice_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    message_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("messages.message_id", ondelete="CASCADE"),
        nullable=False,
        unique=True
    )

    # Media storage reference (URL/path)
    media_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True
    )

    duration_sec: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )

    transcript: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    stt_provider: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True
    )

    confidence: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )

    # pending, processing, completed, failed
    status: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True
    )

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
    message: Mapped["Message"] = relationship(
        "Message",
        back_populates="voice_message"
    )

    __table_args__ = (
        Index(
            "idx_voice_message_message",
            "message_id"
        ),
        Index(
            "idx_voice_message_status",
            "status"
        ),
        Index(
            "idx_voice_message_provider",
            "stt_provider"
        ),
    )