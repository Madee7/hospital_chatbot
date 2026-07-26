"""Per-call cost estimation for the voice pipeline (Whisper STT + GPT parse).

Two billable steps per voice message:
  1. STT  — Whisper is billed per audio-minute.
  2. Parse — the chat model is billed per token (cached prefix tokens are cheaper).

Prices are USD list prices (editable below) and can be overridden via env so you
don't need a code change when OpenAI pricing shifts:
  VOICE_PRICE_INPUT_PER_1M, VOICE_PRICE_CACHED_PER_1M,
  VOICE_PRICE_OUTPUT_PER_1M, VOICE_PRICE_STT_PER_MIN
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# USD per 1,000,000 tokens for chat/parse models. Verified against public
# pricing; adjust here or via env overrides when pricing changes.
_CHAT_PRICING_PER_1M: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
    "gpt-4o": {"input": 2.50, "cached_input": 1.25, "output": 10.00},
    "gpt-4.1-mini": {"input": 0.40, "cached_input": 0.10, "output": 1.60},
    "gpt-4.1": {"input": 2.00, "cached_input": 0.50, "output": 8.00},
}

# USD per audio-minute for STT models.
_STT_PRICING_PER_MIN: dict[str, float] = {
    "whisper-1": 0.006,
    "gpt-4o-mini-transcribe": 0.003,
    "gpt-4o-transcribe": 0.006,
}

# Fallback chat rates when a model isn't in the table (assume gpt-4o-mini tier).
_DEFAULT_CHAT_RATES = {"input": 0.15, "cached_input": 0.075, "output": 0.60}
_DEFAULT_STT_PER_MIN = 0.006


def _env_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _chat_rates(model: str) -> dict[str, float]:
    rates = dict(_CHAT_PRICING_PER_1M.get(model, _DEFAULT_CHAT_RATES))
    # Env overrides (apply to whichever voice model is active).
    for key, env in (
        ("input", "VOICE_PRICE_INPUT_PER_1M"),
        ("cached_input", "VOICE_PRICE_CACHED_PER_1M"),
        ("output", "VOICE_PRICE_OUTPUT_PER_1M"),
    ):
        val = _env_float(env)
        if val is not None:
            rates[key] = val
    return rates


def _stt_rate_per_min(model: str) -> float:
    val = _env_float("VOICE_PRICE_STT_PER_MIN")
    if val is not None:
        return val
    return _STT_PRICING_PER_MIN.get(model, _DEFAULT_STT_PER_MIN)


def ogg_opus_duration_seconds(data: bytes | None) -> float | None:
    """Exact duration of an OGG/Opus stream via the last page's granule position.

    Opus granule positions are always in 48 kHz samples, regardless of the
    source rate, so duration = final_granule / 48000. Dependency-free.
    Returns None if the stream can't be parsed (caller may fall back).
    """
    if not data:
        return None
    idx = data.rfind(b"OggS")
    if idx == -1 or idx + 14 > len(data):
        return None
    granule = int.from_bytes(data[idx + 6 : idx + 14], "little", signed=True)
    if granule <= 0:
        return None
    return granule / 48000.0


def estimate_audio_seconds(
    ogg_bytes: bytes | None,
    *,
    fallback_bitrate_kbps: float | None = None,
) -> float | None:
    """Duration from OGG granule; else a rough size/bitrate estimate."""
    exact = ogg_opus_duration_seconds(ogg_bytes)
    if exact is not None:
        return exact
    if not ogg_bytes:
        return None
    kbps = fallback_bitrate_kbps or _env_float("VOICE_STT_FALLBACK_BITRATE_KBPS") or 16.0
    if kbps <= 0:
        return None
    # seconds ≈ (bytes * 8) / (kbps * 1000)
    return (len(ogg_bytes) * 8.0) / (kbps * 1000.0)


def estimate_stt_cost(model: str, audio_seconds: float | None) -> float:
    if not audio_seconds or audio_seconds <= 0:
        return 0.0
    return (audio_seconds / 60.0) * _stt_rate_per_min(model)


def estimate_gpt_cost(
    model: str,
    *,
    prompt_tokens: int,
    cached_tokens: int = 0,
    completion_tokens: int = 0,
) -> float:
    rates = _chat_rates(model)
    prompt_tokens = max(0, int(prompt_tokens or 0))
    cached_tokens = max(0, min(int(cached_tokens or 0), prompt_tokens))
    completion_tokens = max(0, int(completion_tokens or 0))
    uncached = prompt_tokens - cached_tokens
    return (
        uncached / 1_000_000 * rates["input"]
        + cached_tokens / 1_000_000 * rates["cached_input"]
        + completion_tokens / 1_000_000 * rates["output"]
    )


def estimate_voice_call_cost(
    *,
    stt_model: str,
    audio_seconds: float | None,
    chat_model: str,
    prompt_tokens: int = 0,
    cached_tokens: int = 0,
    completion_tokens: int = 0,
    stt_latency_ms: int | None = None,
    chat_latency_ms: int | None = None,
) -> dict[str, Any]:
    """Full per-voice-call cost breakdown in USD."""
    stt_usd = estimate_stt_cost(stt_model, audio_seconds)
    chat_usd = estimate_gpt_cost(
        chat_model,
        prompt_tokens=prompt_tokens,
        cached_tokens=cached_tokens,
        completion_tokens=completion_tokens,
    )
    prompt_tokens = max(0, int(prompt_tokens or 0))
    cached_tokens = max(0, min(int(cached_tokens or 0), prompt_tokens))
    return {
        "stt_model": stt_model,
        "stt_seconds": round(audio_seconds, 2) if audio_seconds else 0.0,
        "stt_usd": round(stt_usd, 6),
        "stt_latency_ms": stt_latency_ms,
        "chat_model": chat_model,
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached_tokens,
        "uncached_prompt_tokens": prompt_tokens - cached_tokens,
        "completion_tokens": max(0, int(completion_tokens or 0)),
        "chat_usd": round(chat_usd, 6),
        "chat_latency_ms": chat_latency_ms,
        "total_usd": round(stt_usd + chat_usd, 6),
    }


def usage_from_completion(completion: Any) -> dict[str, int]:
    """Pull prompt/cached/completion token counts from an OpenAI completion."""
    usage = getattr(completion, "usage", None)
    if usage is None:
        return {"prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0}
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    details = getattr(usage, "prompt_tokens_details", None)
    cached = 0
    if details is not None:
        cached = int(getattr(details, "cached_tokens", 0) or 0)
    return {
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached,
        "completion_tokens": completion_tokens,
    }


def format_cost_log(cost: dict[str, Any]) -> str:
    """Compact one-line summary for logging."""
    return (
        f"stt=${cost['stt_usd']:.6f} ({cost['stt_seconds']}s) "
        f"gpt=${cost['chat_usd']:.6f} "
        f"(in={cost['prompt_tokens']} cached={cost['cached_tokens']} "
        f"out={cost['completion_tokens']}) total=${cost['total_usd']:.6f}"
    )
