"""System prompts for generative AI paths.

Prefer ``app.language.multilingual_prompt.build_system_prompt`` so the reply
language follows the live conversation language.
"""

from __future__ import annotations

from app.language.multilingual_prompt import build_system_prompt

# Backward-compatible default (Arabic) for legacy imports.
SYSTEM_PROMPT = build_system_prompt("ar", purpose="patient_reply")
