"""WhatsApp Cloud API webhook routes."""

from __future__ import annotations

import traceback

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import PlainTextResponse

from app.core import i18n_bot as i18n
from app.core.config import DEFAULT_CLINIC_ID, DEFAULT_TENANT_ID, VERIFY_TOKEN
from app.db.database import SessionLocal
from app.db.enums import MessageType, ReminderStatus
from app.graph import continue_after_doctor_selected, process_incoming_message
from app.graph.conversation_engine import _sess
from app.language.language_service import get_conversation_language
from app.models.reminder_models import Reminder
from app.services import flow_service
from app.services.conversation_service import (
    get_or_create_conversation,
    log_message,
    log_voice_call_cost,
    log_voice_metadata,
)

router = APIRouter(tags=["whatsapp"])


def _log(msg: str) -> None:
    """Console-safe logging (Windows cp1252 cannot encode Arabic)."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def _phone_lang(db, phone: str) -> str:
    """Best-effort conversation language for webhook fallback messages."""
    sess = _sess(phone)
    if sess.get("language"):
        return i18n.normalize_lang(sess["language"])
    try:
        conversation = get_or_create_conversation(
            db,
            tenant_id=DEFAULT_TENANT_ID,
            clinic_id=DEFAULT_CLINIC_ID,
            phone=phone,
        )
        return get_conversation_language(conversation, sess)
    except Exception:
        return "ar"

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

            lang = _phone_lang(db, phone)
            wa.send_text(phone, i18n.webhook_no_doctor_selected(lang))
            return
        continue_after_doctor_selected(db, phone=phone, doctor_id=doctor_id)
        _log(f"[webhook] flow doctor_id={doctor_id} handled")
    except Exception:
        _log("[webhook] ERROR in flow completion:")
        traceback.print_exc()
    finally:
        db.close()


def _voice_current_step(db, sess: dict, conversation) -> dict | None:
    """Compact booking-step snapshot for Whisper/GPT voice context (Task C)."""
    from app.services import doctor_service

    awaiting = sess.get("awaiting")
    raw_state = getattr(conversation, "state", None)
    conv_state = (
        raw_state.value if raw_state is not None and hasattr(raw_state, "value") else raw_state
    )
    if not awaiting and not sess.get("doctor_id") and not sess.get("department_id") and not sess.get(
        "selected_date"
    ):
        return None

    step: dict = {}
    if conv_state:
        step["conv_state"] = str(conv_state)
    if awaiting:
        step["awaiting"] = str(awaiting)

    doctor_id = sess.get("doctor_id")
    if doctor_id:
        doctor = doctor_service.get_doctor(db, int(doctor_id), clinic_id=DEFAULT_CLINIC_ID)
        if doctor:
            step["known_doctor"] = doctor.name_ar or doctor.name_en or str(doctor_id)

    selected_date = sess.get("selected_date")
    if selected_date:
        step["known_date"] = str(selected_date)

    department_id = sess.get("department_id")
    if department_id:
        dept = doctor_service.find_department(
            db, DEFAULT_CLINIC_ID, department_id=int(department_id)
        )
        if dept:
            step["known_specialty"] = dept.name_ar or dept.name_en or str(department_id)

    return step or None


def _voice_unclear_body(lang: str, awaiting: str | None) -> str:
    """Targeted follow-up when voice cannot be resolved (Task E)."""
    if awaiting == "slot":
        return i18n.webhook_voice_unclear_slot(lang)
    if awaiting == "doctor":
        return i18n.webhook_voice_unclear_doctor(lang)
    if awaiting == "date":
        return i18n.webhook_voice_unclear_date(lang)
    if awaiting == "department":
        return i18n.webhook_voice_unclear_department(lang)
    return i18n.webhook_voice_unclear(lang)


def _reshow_last_options(phone: str, body: str, options: list, *, lang: str = "ar") -> None:
    """Re-prompt with the open list/buttons alongside an unclear message."""
    from app.services import whatsapp_client as wa

    if not options:
        wa.send_text(phone, body)
        return
    if len(options) <= 3:
        buttons = [
            {"id": str(o.get("id") or ""), "title": str(o.get("title") or o.get("id") or "")[:20]}
            for o in options[:3]
        ]
        wa.send_buttons(phone, body, buttons)
    else:
        rows = [
            {
                "id": str(o.get("id") or ""),
                "title": str(o.get("title") or o.get("id") or "")[:24],
                "description": str(o.get("description") or "")[:72],
            }
            for o in options[:10]
        ]
        button_label = "Choose" if i18n.is_english(lang) else "اختر"
        wa.send_list(phone, body=body, button_label=button_label, rows=rows)
    # Keep mapping ids available for the next typed/spoken reply
    sess = _sess(phone)
    sess["last_options"] = list(options)


def _handle_voice(phone: str, media_id: str | None) -> None:
    """Audio layer: Whisper+GPT route, then GitHub booking engine."""
    from app.services import voice_fastpath, voice_service, whatsapp_client as wa

    db = SessionLocal()
    try:
        lang = _phone_lang(db, phone)
        if not media_id:
            wa.send_text(phone, i18n.webhook_voice_receive_failed(lang))
            return

        sess = _sess(phone)
        options = list(sess.get("last_options") or [])
        conversation = get_or_create_conversation(
            db,
            tenant_id=DEFAULT_TENANT_ID,
            clinic_id=DEFAULT_CLINIC_ID,
            phone=phone,
        )
        lang = get_conversation_language(conversation, sess)
        current_step = _voice_current_step(db, sess, conversation)

        # Never pin Whisper language — forcing ar/en made Egyptian dialect worse.
        # Reply language is chosen after STT from the transcript script.
        from app.language.language_service import LanguageService

        result = voice_service.route_whatsapp_voice_message(
            media_id,
            options=options,
            current_step=current_step,
            db=db,
            clinic_id=DEFAULT_CLINIC_ID,
        )
        transcript = (result.get("transcript") or result.get("text") or "").strip()
        confidence = float(result.get("confidence") or 0)
        intent = (result.get("intent") or "unknown").strip().lower()
        action = (result.get("action") or "clarify").strip().lower()
        summary = (result.get("summary_ar") or "").strip()
        option_id = result.get("selected_option_id")
        cost = result.get("cost") or None
        duration_sec = (
            int(round(cost["stt_seconds"]))
            if cost and cost.get("stt_seconds")
            else None
        )

        msg = log_message(
            db,
            conversation_id=conversation.conversation_id,
            direction="inbound",
            message_type=MessageType.VOICE,
            text=transcript or summary or f"(voice:{intent})",
            status="received",
        )
        log_voice_metadata(
            db,
            message_id=msg.message_id,
            media_url=media_id,
            transcript=transcript or None,
            stt_provider=result.get("stt_provider"),
            confidence=confidence,
            duration_sec=duration_sec,
        )
        log_voice_call_cost(
            db,
            tenant_id=DEFAULT_TENANT_ID,
            clinic_id=DEFAULT_CLINIC_ID,
            cost=cost,
            status=(
                "failed"
                if (result.get("stt_provider") or "") == "failed"
                else "completed"
            ),
        )

        # Reply language follows clear speech in the transcript (EN↔AR).
        # Garbage / unclear notes keep the previous reply language.
        lang = LanguageService(db, conversation, sess).apply_voice_language(transcript)
        plan = result.get("plan")
        plan_goal = getattr(plan, "goal", None) if plan is not None else None
        plan_step = getattr(plan, "next_step", None) if plan is not None else None
        _log(
            f"[webhook] voice reply_lang={lang} locked={sess.get('voice_lang_locked')} "
            f"locked_at={sess.get('voice_lang_locked_at')} "
            f"action={action} intent={intent} conf={confidence:.2f} "
            f"option={option_id!r} goal={plan_goal} step={plan_step} "
            f"text={transcript!r}"
        )
        db.commit()

        awaiting = sess.get("awaiting")

        # ---- V2: LLM planned the step. Executor runs it. Stop. ----
        # Do NOT fall through into the V1 fastpath maze — that second-guesses
        # the model and is what made voice feel worse.
        if plan is not None:
            from app.services import voice_executor

            voice_executor.execute_plan(
                db, phone=phone, plan=plan, conversation=conversation
            )
            return

        # ---- V1 legacy path (only when VOICE_ROUTER_V2 is off) ----
        if (
            awaiting in {"patient_name", "mrn_value", "dob_value"}
            and transcript
            and not voice_fastpath.voice_wants_flow_switch(result)
        ):
            process_incoming_message(
                db,
                phone=phone,
                text=transcript,
                payload_id=None,
                message_type="text",
            )
            return

        if voice_fastpath.try_voice_smart_route(db, phone=phone, result=result):
            return

        if action == "select_option" and option_id:
            process_incoming_message(
                db,
                phone=phone,
                text=transcript or str(option_id),
                payload_id=str(option_id),
                message_type="interactive",
            )
            return

        if transcript and action != "clarify":
            process_incoming_message(
                db,
                phone=phone,
                text=transcript,
                payload_id=None,
                message_type="text",
            )
            return

        if transcript and not awaiting:
            process_incoming_message(
                db,
                phone=phone,
                text=transcript,
                payload_id=None,
                message_type="text",
            )
            return

        _reshow_last_options(
            phone,
            _voice_unclear_body(lang, awaiting if isinstance(awaiting, str) else None),
            options,
            lang=lang,
        )
    except Exception:
        _log("[webhook] ERROR while handling voice:")
        traceback.print_exc()
        try:
            from app.services import whatsapp_client as wa

            wa.send_text(
                phone, i18n.webhook_voice_transcribe_failed(_phone_lang(db, phone))
            )
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

            wa.send_text(phone, i18n.webhook_temporary_error(_phone_lang(db, phone)))
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
