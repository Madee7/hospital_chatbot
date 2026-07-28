"""Conversation/session language lifecycle.

Detects language from every inbound user message, persists it on
``Conversation.language``, and mirrors it on the in-memory session.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core import i18n_bot as i18n
from app.core.config import VOICE_LANG_SESSION_MINUTES
from app.db.enums import Language
from app.language.language_detector import (
    detect_language,
    is_confident_switch,
    is_non_linguistic,
    is_ui_payload,
    is_whisper_garbage,
)
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
        set_conversation_language(self.db, self.conversation, enum_val)
        self.session["language"] = code
        self.session.pop("language_changed", None)
        # Track last confident voice/text language for TTL / activity only.
        # Never used to pin Whisper (forcing STT destroys Egyptian dialect quality).
        self.session["voice_lang_locked"] = True
        self.session["voice_lang_locked_at"] = time.time()
        self.session.pop("allow_voice_lang_switch", None)
        return code

    def _voice_lang_session_expired(self) -> bool:
        """True when the voice-language activity window has timed out."""
        locked_at = self.session.get("voice_lang_locked_at")
        if locked_at is None:
            return True
        try:
            age_sec = time.time() - float(locked_at)
        except (TypeError, ValueError):
            return True
        return age_sec >= max(1, VOICE_LANG_SESSION_MINUTES) * 60

    def resolve_stt_language(self) -> LangCode | None:
        """Always None — Whisper must auto-detect for maximum quality.

        Reply language is chosen *after* transcription from the transcript
        script (see apply_voice_language). Pinning STT language caused
        hallucinations on Egyptian dialect.
        """
        return None

    def apply_voice_language(self, transcript: str) -> LangCode:
        """Set reply language from what the user actually said (post-STT).

        Quality rule: Whisper stays auto-detect. We only read the transcript:
        - Confident English speech → English replies
        - Confident Arabic speech → Arabic replies
        - Garbage / unclear → keep previous reply language
        """
        if is_whisper_garbage(transcript):
            return self.language

        detected = detect_language(transcript, fallback=None)
        if detected not in ("ar", "en"):
            return self.language

        if not is_confident_switch(transcript, detected):
            return self.language

        # Clear speech in the other language → switch replies immediately.
        if detected != self.language or not self.session.get("voice_lang_locked"):
            return self.set_language(detected)

        self.session["voice_lang_locked_at"] = time.time()
        return self.language

    def _keep(self, previous: LangCode | None) -> LangCode:
        code = previous or "ar"
        if self.conversation.language is None:
            return self.set_language(code)  # type: ignore[arg-type]
        self.session["language"] = code
        return code  # type: ignore[return-value]

    def sync_from_user_text(
        self,
        text: str | None,
        *,
        payload_id: str | None = None,
    ) -> LangCode:
        """Detect language from the latest user message and update state.

        Language switches ONLY when the user writes real linguistic text in
        another language. Interactive payloads, list/button titles, MENU,
        appointment refs, times, and numbers keep the previous language.
        """
        previous = None
        if self.conversation.language is not None:
            previous = i18n.normalize_lang(self.conversation.language)
        elif self.session.get("language"):
            previous = i18n.normalize_lang(self.session["language"])

        explicit_ar = {"العربية", "عربي", "Arabic", "lang_ar", "arabic"}
        explicit_en = {"English", "الانجليزية", "الإنجليزية", "lang_en", "english"}
        # Bare "en" only via payload — too easy to false-positive in typed text.
        payload = (payload_id or "").strip()
        sample_text = (text or "").strip()

        if payload in explicit_ar or sample_text in explicit_ar:
            return self.set_language("ar")
        if payload == "lang_en" or sample_text in explicit_en:
            return self.set_language("en")

        # Interactive list/button choice: ignore the echoed title completely.
        if is_ui_payload(payload):
            return self._keep(previous)

        sample = sample_text or payload
        if is_non_linguistic(sample):
            return self._keep(previous)

        detected = detect_language(sample, fallback=None)
        if detected is None:
            return self._keep(previous)

        # Same language — keep flags (esp. post-menu allow_voice_lang_switch).
        if previous is not None and detected == previous:
            return self._keep(previous)

        # Already have a language → only flip on confident real prose.
        if previous is not None and detected != previous:
            if not is_confident_switch(sample, detected):
                return self._keep(previous)

        self.set_language(detected)
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
