"""Conversation and message persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.enums import ConversationState, Language, MessageType
from app.models.conversation_models import Conversation, Message, VoiceMessage


def get_or_create_conversation(
    db: Session,
    *,
    tenant_id: int,
    clinic_id: int,
    phone: str,
    patient_id: int | None = None,
    language: Language | None = None,
) -> Conversation:
    """Reuse the latest open conversation for this phone, or start a new one."""
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.clinic_id == clinic_id,
            Conversation.phone == phone,
            Conversation.state != ConversationState.CLOSED,
        )
        .order_by(Conversation.conversation_id.desc())
        .first()
    )
    if conversation:
        if patient_id and conversation.patient_id is None:
            conversation.patient_id = patient_id
        conversation.last_message_at = datetime.utcnow()
        return conversation

    # New chats start without language; the engine detects it from the
    # first linguistic message (or asks Arabic/English if ambiguous).
    conversation = Conversation(
        tenant_id=tenant_id,
        clinic_id=clinic_id,
        patient_id=patient_id,
        phone=phone,
        state=ConversationState.NEW,
        language=language,
        last_message_at=datetime.utcnow(),
    )
    db.add(conversation)
    db.flush()
    return conversation


def set_conversation_language(
    db: Session,
    conversation: Conversation,
    language: Language,
) -> Conversation:
    conversation.language = language
    conversation.last_message_at = datetime.utcnow()
    db.flush()
    return conversation


def set_conversation_state(
    db: Session,
    conversation: Conversation,
    state: ConversationState,
    *,
    current_intent: str | None = None,
) -> Conversation:
    conversation.state = state
    if current_intent is not None:
        conversation.current_intent = current_intent
    conversation.last_message_at = datetime.utcnow()
    db.flush()
    return conversation


def log_message(
    db: Session,
    *,
    conversation_id: int,
    direction: str,
    message_type: MessageType,
    text: str | None = None,
    whatsapp_message_id: str | None = None,
    status: str | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        direction=direction,
        type=message_type,
        text=text,
        whatsapp_message_id=whatsapp_message_id,
        status=status,
        timestamp=datetime.utcnow(),
    )
    db.add(message)
    db.flush()
    return message


def log_voice_metadata(
    db: Session,
    *,
    message_id: int,
    media_url: str | None = None,
    transcript: str | None = None,
    stt_provider: str | None = None,
    confidence: float | None = None,
    duration_sec: int | None = None,
    status: str = "completed",
) -> VoiceMessage:
    voice = VoiceMessage(
        message_id=message_id,
        media_url=media_url,
        transcript=transcript,
        stt_provider=stt_provider,
        confidence=confidence,
        duration_sec=duration_sec,
        status=status,
    )
    db.add(voice)
    db.flush()
    return voice
