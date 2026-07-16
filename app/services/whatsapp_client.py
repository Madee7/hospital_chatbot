"""WhatsApp Cloud API outbound helpers."""

from __future__ import annotations

from typing import Any

import requests

from app.core import i18n_bot as i18n
from app.core.config import (
    PHONE_NUMBER_ID,
    WHATSAPP_API_VERSION,
    WHATSAPP_TOKEN,
)


class WhatsAppError(Exception):
    pass


def _url() -> str:
    return f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{PHONE_NUMBER_ID}/messages"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }


def _post(payload: dict[str, Any]) -> dict[str, Any]:
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        raise WhatsAppError("WHATSAPP_TOKEN / PHONE_NUMBER_ID missing")
    response = requests.post(_url(), headers=_headers(), json=payload, timeout=30)
    data = {}
    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text}
    if response.status_code >= 400:
        raise WhatsAppError(f"WhatsApp API {response.status_code}: {data}")
    return data


def send_text(to: str, text: str) -> dict[str, Any]:
    return _post(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
    )


def send_buttons(
    to: str,
    body: str,
    buttons: list[str] | list[dict[str, str]],
) -> dict[str, Any]:
    """Reply buttons (max 3, title max 20 chars).

    Each item is either a title string, or ``{"id": "...", "title": "..."}``.
    """
    action_buttons = []
    for i, item in enumerate(buttons[:3]):
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("id") or f"opt{i}")[:20]
            bid = str(item.get("id") or f"btn_{i}")[:256]
        else:
            title = str(item)[:20]
            bid = f"btn_{i}_{title[:12]}"
        action_buttons.append(
            {
                "type": "reply",
                "reply": {
                    "id": bid,
                    "title": title,
                },
            }
        )
    return _post(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {"buttons": action_buttons},
            },
        }
    )


def send_list(
    to: str,
    body: str,
    button_label: str,
    rows: list[dict[str, str]],
    section_title: str = "الخيارات",
) -> dict[str, Any]:
    """
    List message.
    rows: [{"id": "...", "title": "...", "description": "..."}]
    """
    wa_rows = []
    for row in rows[:10]:
        item = {
            "id": row["id"][:200],
            "title": row["title"][:24],
        }
        if row.get("description"):
            item["description"] = row["description"][:72]
        wa_rows.append(item)

    return _post(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body},
                "action": {
                    "button": button_label[:20],
                    "sections": [{"title": section_title[:24], "rows": wa_rows}],
                },
            },
        }
    )


def send_doctor_card(
    to: str,
    *,
    doctor_id: int,
    name: str,
    title: str | None,
    specialization: str | None,
    photo_url: str | None,
    profile: str | None = None,
    location: str | None = None,
    lang: str = "ar",
) -> dict[str, Any]:
    """
    Interactive image card with Choose button.

    Closest session-message equivalent of Botpress left/right carousel
    (official WhatsApp carousel requires approved template).
    Sending 3-5 cards in sequence lets the patient scroll between photos.
    """
    body = i18n.doctor_card_body(
        lang,
        name=name,
        title=title,
        specialization=specialization,
        profile=profile,
        location=location,
    )
    choose_title = i18n.choose_doctor_button(lang, name)
    interactive: dict[str, Any] = {
        "type": "button",
        "body": {"text": body},
        "action": {
            "buttons": [
                {
                    "type": "reply",
                    "reply": {
                        "id": f"doctor_{doctor_id}",
                        "title": choose_title,
                    },
                }
            ]
        },
    }
    if photo_url:
        interactive["header"] = {
            "type": "image",
            "image": {"link": photo_url},
        }

    return _post(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }
    )


def send_doctor_cards(
    to: str,
    doctors: list[dict[str, Any]],
    *,
    lang: str = "ar",
) -> None:
    """Send sequential doctor cards localized for the patient's language."""
    for doc in doctors[:5]:
        fields = i18n.doctor_display_fields(doc, lang)
        send_doctor_card(
            to,
            doctor_id=int(fields["doctor_id"] or doc["doctor_id"]),
            name=fields["name"] or f"Doctor {doc['doctor_id']}",
            title=fields["title"],
            specialization=fields["specialization"],
            photo_url=fields["photo_url"] or doc.get("photo_url"),
            profile=fields["bio"],
            lang=lang,
        )


def send_doctor_flow(
    to: str,
    *,
    flow_id: str,
    screen_data: dict[str, Any],
    body: str = "افتح القائمة لتمرير صور الأطباء واختيار الطبيب.",
    cta: str = "عرض الأطباء",
    flow_token: str | None = None,
    draft: bool = False,
) -> dict[str, Any]:
    """
    Open WhatsApp Flow with ImageCarousel + doctor radio options.

    Uses navigate + initial data (no encrypted data-exchange endpoint needed
    for the first screen). Flow must be published (or draft=True for testing).
    """
    from app.core.config import WHATSAPP_FLOW_CTA

    parameters: dict[str, Any] = {
        "flow_message_version": "3",
        "flow_token": flow_token or f"doctor_pick_{to}",
        "flow_id": flow_id,
        "flow_cta": (cta or WHATSAPP_FLOW_CTA)[:30],
        "flow_action": "navigate",
        "flow_action_payload": {
            "screen": "DOCTOR_PICKER",
            "data": screen_data,
        },
    }
    if draft:
        parameters["mode"] = "draft"

    return _post(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "flow",
                "body": {"text": body[:1024]},
                "action": {
                    "name": "flow",
                    "parameters": parameters,
                },
            },
        }
    )
