"""Tests for per-voice-call cost estimation (app/services/voice_cost.py)."""

from __future__ import annotations

import struct

from app.services import voice_cost


def _make_ogg(granule: int) -> bytes:
    """Minimal bytes ending in an OggS page carrying `granule`."""
    header = b"OggS" + b"\x00" + b"\x00" + struct.pack("<q", granule)
    return b"junk-prefix" + header + b"trailing"


def test_ogg_opus_duration_seconds_reads_granule():
    # 48000 samples @ 48kHz == 1.0s
    assert voice_cost.ogg_opus_duration_seconds(_make_ogg(48000)) == 1.0
    assert voice_cost.ogg_opus_duration_seconds(_make_ogg(24000)) == 0.5


def test_ogg_opus_duration_seconds_bad_input():
    assert voice_cost.ogg_opus_duration_seconds(b"") is None
    assert voice_cost.ogg_opus_duration_seconds(b"no ogg here") is None
    assert voice_cost.ogg_opus_duration_seconds(_make_ogg(0)) is None


def test_estimate_audio_seconds_fallback_bitrate():
    # No OggS page -> size/bitrate estimate. 2000 bytes @ 16kbps == 1.0s
    assert voice_cost.estimate_audio_seconds(b"x" * 2000, fallback_bitrate_kbps=16) == 1.0


def test_estimate_stt_cost_whisper():
    # 60s @ $0.006/min == $0.006
    assert round(voice_cost.estimate_stt_cost("whisper-1", 60.0), 6) == 0.006
    assert voice_cost.estimate_stt_cost("whisper-1", 0) == 0.0
    assert voice_cost.estimate_stt_cost("whisper-1", None) == 0.0


def test_estimate_gpt_cost_applies_cached_discount():
    # gpt-4o-mini: input .15, cached .075, output .60 per 1M
    # 1M uncached input == $0.15
    assert round(voice_cost.estimate_gpt_cost("gpt-4o-mini", prompt_tokens=1_000_000), 6) == 0.15
    # 1M cached input == $0.075 (all prompt tokens cached)
    cached_cost = voice_cost.estimate_gpt_cost(
        "gpt-4o-mini", prompt_tokens=1_000_000, cached_tokens=1_000_000
    )
    assert round(cached_cost, 6) == 0.075
    # 1M output == $0.60
    assert round(
        voice_cost.estimate_gpt_cost("gpt-4o-mini", prompt_tokens=0, completion_tokens=1_000_000),
        6,
    ) == 0.60


def test_estimate_gpt_cost_clamps_cached_to_prompt():
    # cached can't exceed prompt tokens
    cost = voice_cost.estimate_gpt_cost(
        "gpt-4o-mini", prompt_tokens=100, cached_tokens=500
    )
    all_cached = voice_cost.estimate_gpt_cost(
        "gpt-4o-mini", prompt_tokens=100, cached_tokens=100
    )
    assert cost == all_cached


def test_estimate_voice_call_cost_breakdown():
    cost = voice_cost.estimate_voice_call_cost(
        stt_model="whisper-1",
        audio_seconds=30.0,
        chat_model="gpt-4o-mini",
        prompt_tokens=3200,
        cached_tokens=3000,
        completion_tokens=40,
    )
    assert cost["stt_seconds"] == 30.0
    assert cost["uncached_prompt_tokens"] == 200
    assert cost["cached_tokens"] == 3000
    assert cost["total_usd"] == round(cost["stt_usd"] + cost["chat_usd"], 6)
    assert cost["stt_usd"] > 0
    assert cost["chat_usd"] > 0


def test_env_override_stt_rate(monkeypatch):
    monkeypatch.setenv("VOICE_PRICE_STT_PER_MIN", "0.012")
    assert round(voice_cost.estimate_stt_cost("whisper-1", 60.0), 6) == 0.012


def test_usage_from_completion_reads_cached_tokens():
    class _Details:
        cached_tokens = 300

    class _Usage:
        prompt_tokens = 1000
        completion_tokens = 50
        prompt_tokens_details = _Details()

    class _Completion:
        usage = _Usage()

    usage = voice_cost.usage_from_completion(_Completion())
    assert usage == {
        "prompt_tokens": 1000,
        "cached_tokens": 300,
        "completion_tokens": 50,
    }


def test_usage_from_completion_no_usage():
    class _Completion:
        usage = None

    assert voice_cost.usage_from_completion(_Completion()) == {
        "prompt_tokens": 0,
        "cached_tokens": 0,
        "completion_tokens": 0,
    }


def test_log_voice_call_cost_writes_two_usage_rows():
    from unittest.mock import MagicMock

    from app.models.usage_models import UsageLog
    from app.services.conversation_service import log_voice_call_cost

    db = MagicMock()
    cost = voice_cost.estimate_voice_call_cost(
        stt_model="whisper-1",
        audio_seconds=30.0,
        chat_model="gpt-4o-mini",
        prompt_tokens=3200,
        cached_tokens=3000,
        completion_tokens=40,
        stt_latency_ms=450,
        chat_latency_ms=900,
    )

    log_voice_call_cost(db, tenant_id=1, clinic_id=2, cost=cost)

    added = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], UsageLog)]
    assert len(added) == 2
    ops = {row.operation for row in added}
    assert ops == {"voice_stt", "voice_parse"}
    for row in added:
        assert row.tenant_id == 1
        assert row.clinic_id == 2
        assert row.cost_estimate >= 0
    stt_row = next(r for r in added if r.operation == "voice_stt")
    parse_row = next(r for r in added if r.operation == "voice_parse")
    assert parse_row.tokens_or_minutes == 3240  # prompt + completion
    assert stt_row.latency_ms == 450
    assert parse_row.latency_ms == 900


def test_log_voice_call_cost_noop_when_cost_missing():
    from unittest.mock import MagicMock

    from app.services.conversation_service import log_voice_call_cost

    db = MagicMock()
    log_voice_call_cost(db, tenant_id=1, clinic_id=2, cost=None)
    db.add.assert_not_called()
