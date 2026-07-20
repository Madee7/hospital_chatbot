"""WhatsApp Cloud API webhook routes."""

from __future__ import annotations

import traceback

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import PlainTextResponse

from app.core.config import VERIFY_TOKEN
from app.db.database import SessionLocal
from app.db.enums import MessageType, ReminderStatus
from app.graph import continue_after_doctor_selected, process_incoming_message
from app.graph.conversation_engine import _sess
from app.models.reminder_models import Reminder
from app.services import flow_service
from app.services.conversation_service import (
    get_or_create_conversation,
    log_message,
    log_voice_metadata,
)
from app.core.config import DEFAULT_CLINIC_ID, DEFAULT_TENANT_ID

router = APIRouter(tags=["whatsapp"])


def _log(msg: str) -> None:
    """Console-safe logging (Windows cp1252 cannot encode Arabic)."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


@router.get("/webhook")
async def verify_webhook(request: Request):
    """Meta WhatsApp webhook verification handshake."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(content=challenge or "", status_code=200)
    return PlainTextResponse(content="verification failed", status_code=403)


def _extract_user_input(message: dict) -> tuple[str, str | None, str, dict | None]:
    """Return (text, payload_id, message_type, extra)."""
    msg_type = message.get("type", "text")
    if msg_type == "text":
        return message.get("text", {}).get("body", "").strip(), None, "text", None
    if msg_type == "interactive":
        interactive = message.get("interactive", {})
        itype = interactive.get("type")
        if itype == "button_reply":
            reply = interactive.get("button_reply", {})
            return reply.get("title", ""), reply.get("id"), "interactive", None
        if itype == "list_reply":
            reply = interactive.get("list_reply", {})
            return reply.get("title", ""), reply.get("id"), "interactive", None
        if itype == "nfm_reply":
            reply = interactive.get("nfm_reply", {})
            return (
                reply.get("body", "") or "flow_complete",
                reply.get("name") or "flow",
                "flow",
                {"response_json": reply.get("response_json")},
            )
    if msg_type == "audio":
        audio = message.get("audio") or {}
        return "", None, "audio", {"media_id": audio.get("id")}
    return "", None, msg_type, None


def _handle_flow_completion(phone: str, response_json: str | None) -> None:
    _log(f"[webhook] flow completion from {phone}")
    db = SessionLocal()
    try:
        doctor_id = flow_service.parse_flow_completion(response_json)
        if not doctor_id:
            from app.services import whatsapp_client as wa

            wa.send_text(phone, "لم يتم اختيار طبيب. أعد المحاولة من القائمة.")
            return
        continue_after_doctor_selected(db, phone=phone, doctor_id=doctor_id)
        _log(f"[webhook] flow doctor_id={doctor_id} handled")
    except Exception:
        _log("[webhook] ERROR in flow completion:")
        traceback.print_exc()
    finally:
        db.close()


def _handle_voice(phone: str, media_id: str | None) -> None:
    """UC-006: download + STT, confirm understanding, then enter guided flow."""
    from app.services import voice_service, whatsapp_client as wa

    db = SessionLocal()
    try:
        if not media_id:
            wa.send_text(phone, "تعذر استلام الملف الصوتي. أعد المحاولة أو اكتب طلبك.")
            return

        result = voice_service.transcribe_whatsapp_audio(media_id)
        transcript = result.get("text") or ""
        confidence = float(result.get("confidence") or 0)

        conversation = get_or_create_conversation(
            db,
            tenant_id=DEFAULT_TENANT_ID,
            clinic_id=DEFAULT_CLINIC_ID,
            phone=phone,
        )
        msg = log_message(
            db,
            conversation_id=conversation.conversation_id,
            direction="inbound",
            message_type=MessageType.VOICE,
            text=transcript or "(voice)",
            status="received",
        )
        log_voice_metadata(
            db,
            message_id=msg.message_id,
            media_url=media_id,
            transcript=transcript or None,
            stt_provider=result.get("stt_provider"),
            confidence=confidence,
        )
        db.commit()

        if not transcript or confidence < 0.5:
            wa.send_text(
                phone,
                "لم أفهم الرسالة الصوتية بوضوح. أعد التسجيل أو اكتب طلبك نصاً.",
            )
            return

        sess = _sess(phone)
        sess["awaiting"] = "voice_confirm"
        sess["voice_transcript"] = transcript
        wa.send_buttons(
            phone,
            f"فهمت طلبك كالتالي:\n«{transcript}»\nهل هذا صحيح؟ (لن أحجز قبل التأكيد النهائي لاحقاً)",
            ["نعم صحيح", "إعادة"],
        )
    except Exception:
        _log("[webhook] ERROR while handling voice:")
        traceback.print_exc()
        try:
            from app.services import whatsapp_client as wa

            wa.send_text(phone, "فشل تحويل الصوت. اكتب طلبك نصاً أو أعد التسجيل.")
        except Exception:
            traceback.print_exc()
    finally:
        db.close()


def _handle_message(phone: str, text: str, payload_id: str | None, message_type: str) -> None:
    _log(
        f"[webhook] handle message phone={phone} type={message_type} "
        f"text={text!r} payload={payload_id!r}"
    )
    db = SessionLocal()
    try:
        process_incoming_message(
            db,
            phone=phone,
            text=text,
            payload_id=payload_id,
            message_type=message_type,
        )
        _log(f"[webhook] handled OK phone={phone}")
    except Exception:
        _log("[webhook] ERROR while handling message:")
        traceback.print_exc()
        try:
            from app.services import whatsapp_client as wa
            from app.services import handover_service
            from app.db.enums import HandoverPriority

            wa.send_text(phone, "حصل خطأ مؤقت. نحجز لك متابعة مع الاستقبال.")
            handover_service.create_handover(
                db,
                phone=phone,
                reason=f"System error while handling: {message_type}",
                priority=HandoverPriority.HIGH,
            )
        except Exception:
            traceback.print_exc()
    finally:
        db.close()


def _handle_status_updates(statuses: list[dict]) -> None:
    """UC-004: map WhatsApp delivery receipts to reminder/message status."""
    db = SessionLocal()
    try:
        from app.models.conversation_models import Message

        for st in statuses:
            wamid = st.get("id")
            status = (st.get("status") or "").lower()
            if not wamid or not status:
                continue
            msg = (
                db.query(Message)
                .filter(Message.whatsapp_message_id == wamid)
                .one_or_none()
            )
            if msg:
                msg.status = status
            rem = (
                db.query(Reminder)
                .filter(Reminder.whatsapp_message_id == wamid)
                .one_or_none()
            )
            if rem:
                if status == "delivered":
                    rem.status = ReminderStatus.DELIVERED
                elif status == "read":
                    rem.status = ReminderStatus.READ
                elif status == "failed":
                    rem.status = ReminderStatus.FAILED
        db.commit()
    except Exception:
        # Column may not exist yet — ignore gracefully
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


@router.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()
    try:
        value = payload["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, TypeError):
        _log("[webhook] ignored malformed payload")
        return {"status": "ignored"}

    if "messages" not in value:
        statuses = value.get("statuses") or []
        if statuses:
            background_tasks.add_task(_handle_status_updates, statuses)
        return {"status": "status_update"}

    message = value["messages"][0]
    phone = message.get("from")
    text, payload_id, message_type, extra = _extract_user_input(message)
    _log(
        f"[webhook] INCOMING phone={phone} type={message_type} "
        f"text={text!r} payload={payload_id!r}"
    )
    if not phone:
        return {"status": "no_phone"}

    if message_type == "flow":
        background_tasks.add_task(
            _handle_flow_completion,
            phone,
            (extra or {}).get("response_json"),
        )
        return {"status": "flow_queued"}

    if message_type == "audio":
        background_tasks.add_task(_handle_voice, phone, (extra or {}).get("media_id"))
        return {"status": "voice_queued"}

    background_tasks.add_task(_handle_message, phone, text, payload_id, message_type)
    return {"status": "queued"}
