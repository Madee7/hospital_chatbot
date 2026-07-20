"""Human handover / receptionist escalation (UC-007)."""

from __future__ import annotations

from datetime import datetime, time

from sqlalchemy.orm import Session

from app.core import i18n_bot as i18n
from app.core.config import (
    DEFAULT_CLINIC_ID,
    DEFAULT_TENANT_ID,
    RECEPTIONIST_WHATSAPP,
)
from app.db.enums import ConversationState, HandoverPriority, MessageType
from app.models.conversation_models import Conversation, Message
from app.models.handover_models import HandoverCase
from app.services import whatsapp_client as wa
from app.services.conversation_service import (
    get_or_create_conversation,
    log_message,
    set_conversation_state,
)


def _within_business_hours(now: datetime | None = None) -> bool:
    """Simple Mon–Fri 09:00–17:00 local (server) hours for demo."""
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    return time(9, 0) <= now.time() <= time(17, 0)


def _transcript_snippet(db: Session, conversation_id: int, limit: int = 20) -> str:
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )
    lines = []
    for m in reversed(rows):
        text = (m.text or "").strip()
        if not text:
            continue
        lines.append(f"[{m.direction}] {text[:200]}")
    return "\n".join(lines) if lines else "(no messages yet)"


def create_handover(
    db: Session,
    *,
    phone: str,
    reason: str,
    priority: HandoverPriority = HandoverPriority.NORMAL,
    created_by: str = "bot",
    patient_message: str | None = None,
) -> dict:
    conversation = get_or_create_conversation(
        db,
        tenant_id=DEFAULT_TENANT_ID,
        clinic_id=DEFAULT_CLINIC_ID,
        phone=phone,
    )
    snippet = _transcript_snippet(db, conversation.conversation_id)
    full_reason = f"{reason}\n\n--- transcript ---\n{snippet}"

    case = HandoverCase(
        conversation_id=conversation.conversation_id,
        reason=full_reason,
        priority=priority,
        status="open",
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(case)
    set_conversation_state(
        db,
        conversation,
        ConversationState.HANDOVER,
        current_intent="handover",
    )
    db.flush()

    in_hours = _within_business_hours()
    if patient_message:
        patient_msg = patient_message
    else:
        lang = i18n.normalize_lang(getattr(conversation, "language", None))
        patient_msg = (
            i18n.handover_in_hours(lang)
            if in_hours
            else i18n.handover_after_hours(lang)
        )
    wa.send_text(phone, patient_msg)
    log_message(
        db,
        conversation_id=conversation.conversation_id,
        direction="outbound",
        message_type=MessageType.TEXT,
        text=patient_msg,
        status="sent",
    )

    if RECEPTIONIST_WHATSAPP:
        try:
            wa.send_text(
                RECEPTIONIST_WHATSAPP,
                f"Handover #{case.handover_id} open\n"
                f"Patient: {phone}\n"
                f"Priority: {priority.value}\n"
                f"Reason: {reason}",
            )
        except Exception:
            pass

    db.commit()
    db.refresh(case)
    return {
        "handover_id": case.handover_id,
        "status": case.status,
        "priority": case.priority.value if hasattr(case.priority, "value") else case.priority,
        "in_business_hours": in_hours,
        "conversation_id": conversation.conversation_id,
    }


def list_handovers(db: Session, *, status: str | None = "open", limit: int = 50) -> list[dict]:
    q = db.query(HandoverCase, Conversation).join(
        Conversation, Conversation.conversation_id == HandoverCase.conversation_id
    )
    if status:
        q = q.filter(HandoverCase.status == status)
    rows = q.order_by(HandoverCase.created_at.desc()).limit(limit).all()
    return [
        {
            "handover_id": h.handover_id,
            "status": h.status,
            "priority": h.priority.value if hasattr(h.priority, "value") else h.priority,
            "phone": c.phone,
            "reason": (h.reason or "")[:300],
            "assigned_to": h.assigned_to,
            "created_at": h.created_at,
        }
        for h, c in rows
    ]
