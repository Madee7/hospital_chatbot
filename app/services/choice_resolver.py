"""
Map free-text / typed numbers to an interactive option id.

The LLM only picks from the offered options — it never generates the bot reply.
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from app.core.config import OPENAI_API_KEY, OPENAI_MODEL


Option = dict[str, Any]  # id, title, description?


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def resolve_choice_rules(user_text: str, options: list[Option]) -> str | None:
    """Fast local matching: index, id, title, partial title/description."""
    text = (user_text or "").strip()
    if not text or not options:
        return None

    # Pure number → 1-based index
    if re.fullmatch(r"\d{1,2}", text):
        idx = int(text) - 1
        if 0 <= idx < len(options):
            return str(options[idx]["id"])

    # Arabic-Indic digits
    arab_map = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    digit_text = text.translate(arab_map)
    if digit_text != text and re.fullmatch(r"\d{1,2}", digit_text):
        idx = int(digit_text) - 1
        if 0 <= idx < len(options):
            return str(options[idx]["id"])

    n = _norm(text)
    for opt in options:
        oid = str(opt.get("id") or "")
        title = str(opt.get("title") or "")
        desc = str(opt.get("description") or "")
        if n == _norm(oid) or n == _norm(title):
            return oid
        # "اختيار د. فلان" style
        if title and _norm(title) in n:
            return oid
        if n and n in _norm(title):
            return oid
        if desc and (n in _norm(desc) or _norm(desc) in n):
            return oid
    return None


def resolve_choice_llm(user_text: str, options: list[Option]) -> str | None:
    """Ask OpenAI which option id matches; return only that id or None."""
    if not OPENAI_API_KEY or not user_text.strip() or not options:
        return None
    catalog = [
        {
            "id": str(o.get("id")),
            "title": o.get("title"),
            "description": o.get("description") or "",
            "number": i + 1,
        }
        for i, o in enumerate(options)
    ]
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You map a patient's short WhatsApp reply to ONE option from a fixed list. "
                        "The user may type a number, Arabic/English words, a specialty, doctor name, "
                        "date, time, or paraphrase of a button. "
                        "Return JSON {\"option_id\": \"exact id from list\"} or {\"option_id\": null} "
                        "if none match. Never invent ids. Never write a chatbot reply."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"user_text": user_text, "options": catalog},
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        content = completion.choices[0].message.content or "{}"
        payload = json.loads(content)
        option_id = payload.get("option_id")
        if option_id is None:
            return None
        option_id = str(option_id).strip()
        allowed = {str(o.get("id")) for o in options}
        return option_id if option_id in allowed else None
    except Exception as exc:
        print(f"[choice_resolver] LLM failed: {exc}")
        return None


def resolve_choice(user_text: str, options: list[Option] | None) -> str | None:
    """Rules first, then LLM. Returns option id or None."""
    options = options or []
    if not options:
        return None
    hit = resolve_choice_rules(user_text, options)
    if hit:
        return hit
    return resolve_choice_llm(user_text, options)
