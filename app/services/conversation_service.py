"""Conversation and message persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.enums import ConversationState, Language, MessageType
from app.models.conversation_models import Conversation, Message, VoiceMessage
from app.models.usage_models import UsageLog


def _as_latency_ms(value: object) -> int | None:
    if value is None:
        return None
    try:
        ms = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return ms if ms >= 0 else None


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
    # first linguistic message (defaults to Arabic if unclear — no picker).
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


def log_usage(
    db: Session,
    *,
    tenant_id: int,
    clinic_id: int,
    provider: str,
    operation: str,
    cost_estimate: float,
    tokens_or_minutes: int | None = None,
    latency_ms: int | None = None,
    status: str = "completed",
) -> UsageLog:
    """Record one AI-provider usage/cost row (feeds dashboard KPIs + Usage page)."""
    row = UsageLog(
        tenant_id=tenant_id,
        clinic_id=clinic_id,
        provider=provider,
        operation=operation,
        cost_estimate=cost_estimate,
        tokens_or_minutes=tokens_or_minutes,
        latency_ms=latency_ms,
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def log_voice_call_cost(
    db: Session,
    *,
    tenant_id: int,
    clinic_id: int,
    cost: dict | None,
    status: str = "completed",
) -> None:
    """Persist a voice call's cost breakdown as UsageLog rows (STT + GPT parse).

    `cost` is the dict returned by voice_service (voice_cost.estimate_voice_call_cost).
    Two rows are written so the dashboard can break cost down by provider/operation.
    """
    if not cost:
        return

    stt_seconds = float(cost.get("stt_seconds") or 0)
    log_usage(
        db,
        tenant_id=tenant_id,
        clinic_id=clinic_id,
        provider=str(cost.get("stt_model") or "openai_stt"),
        operation="voice_stt",
        cost_estimate=float(cost.get("stt_usd") or 0.0),
        tokens_or_minutes=int(round(stt_seconds)),
        latency_ms=_as_latency_ms(cost.get("stt_latency_ms")),
        status=status,
    )

    total_tokens = int(cost.get("prompt_tokens") or 0) + int(
        cost.get("completion_tokens") or 0
    )
    log_usage(
        db,
        tenant_id=tenant_id,
        clinic_id=clinic_id,
        provider=str(cost.get("chat_model") or "openai_gpt"),
        operation="voice_parse",
        cost_estimate=float(cost.get("chat_usd") or 0.0),
        tokens_or_minutes=total_tokens,
        latency_ms=_as_latency_ms(cost.get("chat_latency_ms")),
        status=status,
    )


def log_openai_chat_usage(
    db: Session | None,
    *,
    tenant_id: int | None,
    clinic_id: int | None,
    model: str,
    operation: str,
    completion: object | None = None,
    latency_ms: int | None = None,
    status: str = "completed",
) -> UsageLog | None:
    """Persist one text-LLM call (intent / choice / rewrite) into usage_logs.

    No-op when db/tenant/clinic are missing so unit tests and pure helpers stay light.
    """
    if db is None or tenant_id is None or clinic_id is None:
        return None

    from app.services import voice_cost

    usage = (
        voice_cost.usage_from_completion(completion)
        if completion is not None
        else {"prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0}
    )
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    cached_tokens = int(usage.get("cached_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    cost_usd = voice_cost.estimate_gpt_cost(
        model,
        prompt_tokens=prompt_tokens,
        cached_tokens=cached_tokens,
        completion_tokens=completion_tokens,
    )
    return log_usage(
        db,
        tenant_id=tenant_id,
        clinic_id=clinic_id,
        provider=model or "openai",
        operation=operation,
        cost_estimate=float(cost_usd),
        tokens_or_minutes=prompt_tokens + completion_tokens,
        latency_ms=_as_latency_ms(latency_ms),
        status=status,
    )
