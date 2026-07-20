"""Conversation/session language lifecycle.

Detects language from every inbound user message, persists it on
``Conversation.language``, and mirrors it on the in-memory session.
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core import i18n_bot as i18n
from app.db.enums import Language
from app.language.language_detector import detect_language, is_non_linguistic
from app.models.conversation_models import Conversation
from app.services.conversation_service import set_conversation_language

LangCode = Literal["ar", "en"]


def get_conversation_language(
    conversation: Conversation | None,
    session: dict[str, Any] | None = None,
) -> LangCode:
    """Resolve current language: session → conversation → Arabic default."""
    if session:
        sess_lang = session.get("language")
        if sess_lang:
            return i18n.normalize_lang(sess_lang)  # type: ignore[return-value]
    if conversation is not None and conversation.language is not None:
        return i18n.normalize_lang(conversation.language)  # type: ignore[return-value]
    return "ar"


def _to_enum(code: LangCode) -> Language:
    return Language.EN if code == "en" else Language.AR


class LanguageService:
    """Owns language detection + persistence for one conversation turn."""

    def __init__(self, db: Session, conversation: Conversation, session: dict[str, Any]):
        self.db = db
        self.conversation = conversation
        self.session = session

    @property
    def language(self) -> LangCode:
        return get_conversation_language(self.conversation, self.session)

    def set_language(self, code: LangCode, *, announce: bool = False) -> LangCode:
        """Force-set language (e.g. explicit button) and sync session."""
        enum_val = _to_enum(code)
        prev = get_conversation_language(self.conversation, self.session)
        set_conversation_language(self.db, self.conversation, enum_val)
        self.session["language"] = code
        if announce and prev != code:
            self.session["language_changed"] = True
        else:
            self.session.pop("language_changed", None)
        return code

    def sync_from_user_text(
        self,
        text: str | None,
        *,
        payload_id: str | None = None,
    ) -> LangCode:
        """Detect language from the latest user message and update state.

        - Payload / numeric / empty messages keep the previous language.
        - Linguistic text updates ``conversation.language`` immediately when
          the detected language differs from the stored one.
        """
        previous = None
        if self.conversation.language is not None:
            previous = i18n.normalize_lang(self.conversation.language)
        elif self.session.get("language"):
            previous = i18n.normalize_lang(self.session["language"])

        # Explicit language labels/payloads (never bare "1"/"2" — those are menus).
        explicit_ar = {"العربية", "عربي", "Arabic", "lang_ar", "arabic"}
        explicit_en = {"English", "الانجليزية", "الإنجليزية", "lang_en", "en", "english"}
        payload = (payload_id or "").strip()
        sample_text = (text or "").strip()
        if payload in explicit_ar or sample_text in explicit_ar:
            return self.set_language("ar")
        if payload in explicit_en or sample_text in explicit_en:
            return self.set_language("en")

        sample = sample_text or payload
        if is_non_linguistic(sample):
            code = previous or "ar"
            self.session["language"] = code
            return code  # type: ignore[return-value]

        detected = detect_language(sample, fallback=None)
        if detected is None:
            code = previous or "ar"
            self.session["language"] = code
            return code  # type: ignore[return-value]

        changed = previous is not None and previous != detected
        self.set_language(detected, announce=changed)
        return detected


def sync_conversation_language(
    db: Session,
    conversation: Conversation,
    session: dict[str, Any],
    text: str | None,
    *,
    payload_id: str | None = None,
) -> LangCode:
    """Module-level helper used by the conversation engine."""
    return LanguageService(db, conversation, session).sync_from_user_text(
        text, payload_id=payload_id
    )
