"""WhatsApp voice note → STT (UC-006)."""

from __future__ import annotations


def transcribe_whatsapp_audio(media_id: str) -> dict:
    """
    Download + transcribe a WhatsApp voice note via Groq Whisper.

    Returns dict: text, confidence (heuristic), provider.
    """
    from voice_processor import process_whatsapp_audio

    text = (process_whatsapp_audio(media_id) or "").strip()
    confidence = 0.0
    if text:
        confidence = 0.85 if len(text) >= 8 else 0.45
    return {
        "text": text,
        "confidence": confidence,
        "stt_provider": "groq_whisper",
        "media_id": media_id,
    }
