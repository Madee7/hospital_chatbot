r"""
Eval harness for the New Giza University Hospital voice-booking router
(_SYSTEM prompt in app/services/voice_service.py).

WHAT THIS DOES
  - Defines ~35 realistic Egyptian-Arabic voice-transcript test cases,
    covering every action type, the context-aware routing rules, the
    edit/update flow, and every edge case called out in the prompt.
  - Runs each case through `call_router()`, which is wired to the REAL
    production router (`voice_service._understand_via_gpt_text`) so the
    eval reflects the actual prompt + Pydantic schema + code-side
    `_sanitize`, not a re-implementation.
  - Scores each field independently (action, intent, doctor_hint, etc.),
    prints per-case diffs, and gives you an overall + per-field accuracy
    breakdown so you know exactly WHERE the prompt is weak, not just IF.

HOW TO RUN (Windows PowerShell, from the repo root):
    $env:PYTHONIOENCODING="utf-8"
    ..\hospital-chatbot\.venv\Scripts\python.exe eval_voice_router.py

  Needs OPENAI_API_KEY in the environment / .env (the same one the app uses).
  Each case makes one structured-output call, so a full run is ~35 calls.

KNOWN EXPECTED FAILURES
  Edge Cases 7 (past date) and 9 (requested time not in options) were
  deliberately DROPPED from the live prompt (validation is handled in code,
  not by the LLM). The cases `clarify_past_date` and `time_not_in_options`
  are kept here for documentation and will likely fail — that's expected.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

# Make `app` importable when run directly from the repo root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ═══════════════════════════════════════════════════════════════════════
# TEST CASE DEFINITION
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class TestCase:
    id: str
    transcript: str                              # simulated Whisper output
    today: str = "2026-07-24"                     # Friday
    current_step: Optional[dict] = None            # CURRENT_STEP context
    options_json: Optional[list] = None             # OPTIONS_JSON context
    expected: dict = field(default_factory=dict)   # fields to check
    note: str = ""                                  # what this case probes


CASES: list[TestCase] = [

    # ---- book_direct: doctor + date + time all at once -----------------
    TestCase(
        id="book_direct_full",
        transcript="احجز مع دكتور علي بكرة الساعة 2",
        expected={
            "action": "book_direct",
            "intent": "book",
            "doctor_hint": "علي",
            "date_hint": "2026-07-25",
            "time_hint": "14:00",
            "confidence_min": 0.8,
        },
        note="Full happy path — doctor+date+time, should skip all steps.",
    ),
    TestCase(
        id="book_direct_full_name",
        transcript="عايز دكتور أحمد سمير بكرة الصبح",
        expected={
            "action": "book_direct",
            "doctor_hint_contains": "أحمد سمير",
            "date_hint": "2026-07-25",
            "time_hint": "morning",
        },
        note="Full doctor name + period, no title in transcript.",
    ),
    TestCase(
        id="book_direct_with_title",
        transcript="موعد مع د. محمد يوم الأحد الصبح",
        expected={
            "action": "book_direct",
            "doctor_hint_contains": "محمد",
            "doctor_hint_not_contains": "د.",
            "date_hint": "2026-07-26",
            "time_hint": "morning",
        },
        note="Rule 6 — title must be stripped from doctor_hint.",
    ),
    TestCase(
        id="book_direct_time_only",
        transcript="موعد مع رانيا الساعة 2",
        expected={
            "action": "book_direct",
            "doctor_hint_contains": "رانيا",
            "time_hint": "14:00",
            "date_hint": None,
        },
        note="No date mentioned — date_hint must stay null, not guessed.",
    ),

    # ---- specialty_direct -------------------------------------------------
    TestCase(
        id="specialty_direct_basic",
        transcript="عايز دكتور قلب",
        expected={
            "action": "specialty_direct",
            "specialty_hint_contains": "قلب",
            "doctor_hint": None,
        },
        note="Edge Case 1 — 'دكتور قلب' should resolve to specialty, not a person named Qalb.",
    ),
    TestCase(
        id="specialty_direct_with_date_time",
        transcript="احجز في عظام بكرة الساعة 3",
        expected={
            "action": "specialty_direct",
            "specialty_hint_contains": "عظام",
            "date_hint": "2026-07-25",
            "time_hint": "15:00",
        },
        note="Specialty + full date/time in one utterance.",
    ),
    TestCase(
        id="specialty_direct_child",
        transcript="موعد تخصص أطفال الساعة 3",
        expected={
            "action": "specialty_direct",
            "specialty_hint_contains": "أطفال",
            "time_hint": "15:00",
        },
        note="Pediatrics specialty keyword recognition.",
    ),

    # ---- select_option ------------------------------------------------
    TestCase(
        id="select_option_number",
        transcript="رقم 1",
        options_json=[
            {"id": "opt_1", "title": "دكتور أحمد - قلب"},
            {"id": "opt_2", "title": "دكتور سارة - عظام"},
        ],
        expected={
            "action": "select_option",
            "selected_option_id": "opt_1",
            "confidence_min": 0.9,
        },
        note="Numeric selection must map to first option by position.",
    ),
    TestCase(
        id="select_option_bare_number",
        transcript="واحد",
        options_json=[
            {"id": "slot_1", "title": "10:00 AM"},
            {"id": "slot_2", "title": "2:00 PM"},
        ],
        expected={"action": "select_option", "selected_option_id": "slot_1"},
        note="Spoken-word number ('واحد') should resolve the same as '1'.",
    ),
    TestCase(
        id="select_option_no_match",
        transcript="عايز حاجة تانية خالص",
        options_json=[
            {"id": "opt_1", "title": "دكتور أحمد"},
            {"id": "opt_2", "title": "دكتور سارة"},
        ],
        expected={
            "action_not": "select_option",
        },
        note="Should NOT force select_option when nothing in the utterance matches options.",
    ),

    # ---- intent (general, no specifics) --------------------------------
    TestCase(
        id="intent_book_vague",
        transcript="عايز احجز",
        expected={"action": "intent", "intent": "book"},
        note="No doctor/specialty mentioned — plain intent, not book_direct.",
    ),
    TestCase(
        id="intent_cancel",
        transcript="الغي الموعد",
        expected={"action": "intent", "intent": "cancel", "confidence_min": 0.85},
        note="Clear cancellation phrase.",
    ),
    TestCase(
        id="intent_confirm",
        transcript="نعم تمام",
        current_step={"awaiting": "confirm"},
        expected={"action": "intent", "intent": "confirm", "confidence_min": 0.9},
        note="Confirm phrase, in context of confirm step.",
    ),
    TestCase(
        id="intent_handover",
        transcript="عايز اكلم حد من الاستقبال",
        expected={"action": "intent", "intent": "handover"},
        note="Request for a human agent.",
    ),
    TestCase(
        id="intent_ask_doctors",
        transcript="مين الدكاترة المتاحين عندكم في العظام",
        expected={"action": "specialty_direct", "intent": "ask_doctors",
                  "specialty_hint_contains": "عظام"},
        note="Availability question that NAMES a specialty. Per the inquiry-routing "
             "rules, this maps to specialty_direct + intent=ask_doctors (routes to the "
             "specialty inquiry flow), not a bare 'intent'.",
    ),
    TestCase(
        id="intent_ask_doctors_generic",
        transcript="مين الدكاترة المتاحين عندكم",
        expected={"action": "intent", "intent": "ask_doctors"},
        note="Availability question with NO specialty/doctor named -> plain intent.",
    ),

    # ---- clarify ---------------------------------------------------------
    TestCase(
        id="clarify_noise",
        transcript="[صوت خلفية غير مفهوم]",
        expected={"action": "clarify", "confidence_max": 0.4},
        note="Unintelligible input.",
    ),
    TestCase(
        id="clarify_past_date",
        transcript="عايز موعد أمبارح",
        expected={"action": "clarify", "confidence_max": 0.4},
        note="Edge Case 7 (DROPPED from prompt) — past-date rejection now lives in code, "
             "so this LLM-level check is expected to fail.",
    ),

    # ---- context-aware routing -----------------------------------------
    TestCase(
        id="context_date_step_short_answer",
        transcript="بكرة",
        current_step={"awaiting": "date"},
        expected={"date_hint": "2026-07-25", "action_not": "clarify"},
        note="Rule: complete current step first, don't treat short answer as unclear.",
    ),
    TestCase(
        id="context_carry_forward_doctor",
        transcript="الساعة 2",
        current_step={"awaiting": "slot", "known_doctor": "أحمد"},
        expected={"time_hint": "14:00", "doctor_hint_contains": "أحمد"},
        note="Known doctor from context must be carried forward, not dropped.",
    ),
    TestCase(
        id="context_change_of_mind",
        transcript="لا عايز دكتور علي",
        current_step={"awaiting": "slot", "known_doctor": "أحمد"},
        expected={
            "action": "book_direct",
            "doctor_hint_contains": "علي",
            "confidence_min": 0.7,
        },
        note="Explicit change of doctor mid-flow should register as a new choice.",
    ),
    TestCase(
        id="context_patient_name_step",
        transcript="محمد إبراهيم عبد الله",
        current_step={"awaiting": "patient_name"},
        expected={"doctor_hint": None, "action": "intent", "intent": "book"},
        note="Name at patient_name step must NOT be parsed as a doctor_hint.",
    ),
    TestCase(
        id="context_phone_at_name_step",
        transcript="01234567890",
        current_step={"awaiting": "patient_name"},
        expected={"doctor_hint": None, "specialty_hint": None},
        note="Edge Case 2 — numeric string at name/MRN step must not become a hint.",
    ),

    # ---- edit / update flow ----------------------------------------------
    TestCase(
        id="edit_intent_only",
        transcript="عايز اعدل الموعد",
        expected={"action": "intent", "intent": "update"},
        note="Edit intent with no target/value yet.",
    ),
    TestCase(
        id="edit_with_new_date",
        transcript="غير الموعد لبكرة",
        expected={
            "intent": "update",
            "date_hint": "2026-07-25",
        },
        note="Edit + new value in the same utterance.",
    ),
    TestCase(
        id="edit_change_type_step",
        transcript="الدكتور",
        current_step={"awaiting": "change_type"},
        expected={"change_target": "doctor"},
        note="At change_type step, bare 'الدكتور' selects doctor as the edit target.",
    ),
    TestCase(
        id="edit_confirm_negative",
        transcript="لا",
        current_step={"awaiting": "confirm"},
        expected={"action": "intent", "intent": "update", "confidence_min": 0.85},
        note="Edge Case 4 — 'no' during confirmation means they want to change something.",
    ),

    # ---- confidence / ambiguity edge cases --------------------------------
    TestCase(
        id="ambiguous_time_pm_default",
        transcript="الساعة 9",
        expected={"time_hint": "21:00"},
        note=(
            "Flags the PM-default risk raised earlier: an elderly patient saying "
            "'الساعة 9' with no AM/PM context could mean a 9am appointment. "
            "Check confidence here — if it's >=0.8, the flow may skip confirmation "
            "on a genuinely ambiguous booking."
        ),
    ),
    TestCase(
        id="ambiguous_multiple_doctors",
        transcript="احجز مع أحمد أو علي",
        expected={
            "action": "book_direct",
            "doctor_hint_contains": "أحمد",
            "confidence_max": 0.7,
        },
        note=(
            "Edge Case 5 — structural gap: the second candidate ('علي') has no "
            "field to land in. Only the first doctor is checked here."
        ),
    ),
    TestCase(
        id="specialty_vs_doctor_ambiguous_name",
        transcript="دكتور قلب",
        expected={"action": "specialty_direct"},
        note="Same as specialty_direct_basic, isolated as a pure ambiguity probe.",
    ),

    # ---- language detection ------------------------------------------------
    TestCase(
        id="lang_egyptian_arabic",
        transcript="احجز مع دكتور علي بكرة",
        expected={"language": "ar-EG"},
        note="Colloquial Egyptian markers ('بكرة') should tag ar-EG specifically, not plain 'ar'.",
    ),
    TestCase(
        id="lang_english",
        transcript="I want to book with Dr. Ahmed tomorrow at 2pm",
        expected={"language": "en", "date_hint": "2026-07-25", "time_hint": "14:00"},
        note="Pure English transcript, date/time parsing must still work.",
    ),
    TestCase(
        id="lang_mixed",
        transcript="احجز appointment مع Dr. أحمد",
        expected={"language_in": ["mixed", "ar-EG", "ar"], "doctor_hint_contains": "أحمد"},
        note="Code-switched input — language just needs to not be 'unknown'.",
    ),

    # ---- cancellation / abort -----------------------------------------------
    TestCase(
        id="cancel_midflow",
        transcript="خلاص ماحتاجش",
        current_step={"awaiting": "slot"},
        expected={"action": "intent", "intent_in": ["cancel", "menu"], "confidence_min": 0.85},
        note="Edge Case 10 — abandon mid-booking flow.",
    ),

    # ---- unavailable slot vs available options -----------------------------
    TestCase(
        id="time_not_in_options",
        transcript="الساعة 3 ونص",
        options_json=[
            {"id": "slot_1", "title": "10:00 AM"},
            {"id": "slot_2", "title": "2:00 PM"},
            {"id": "slot_3", "title": "4:00 PM"},
        ],
        expected={"time_hint": "15:30", "action": "clarify"},
        note="Edge Case 9 (DROPPED from prompt) — slot-availability check now lives in code, "
             "so the LLM-level clarify is expected to fail.",
    ),
]


# ═══════════════════════════════════════════════════════════════════════
# SCORING
# ═══════════════════════════════════════════════════════════════════════

SIMPLE_FIELDS = [
    "action", "intent", "doctor_hint", "specialty_hint",
    "date_hint", "time_hint", "selected_option_id", "change_target", "language",
]


def score_case(tc: TestCase, actual: dict) -> tuple[bool, list[str]]:
    """Returns (passed, list_of_failure_reasons)."""
    failures: list[str] = []
    exp = tc.expected

    for f in SIMPLE_FIELDS:
        if f in exp:
            got = actual.get(f)
            want = exp[f]
            if got != want:
                failures.append(f"{f}: expected {want!r}, got {got!r}")

    if "action_not" in exp and actual.get("action") == exp["action_not"]:
        failures.append(f"action: should NOT be {exp['action_not']!r}, got it anyway")

    if "intent_in" in exp and actual.get("intent") not in exp["intent_in"]:
        failures.append(f"intent: expected one of {exp['intent_in']}, got {actual.get('intent')!r}")

    if "language_in" in exp and actual.get("language") not in exp["language_in"]:
        failures.append(f"language: expected one of {exp['language_in']}, got {actual.get('language')!r}")

    for f in ("doctor_hint", "specialty_hint"):
        key = f + "_contains"
        if key in exp:
            got = actual.get(f) or ""
            if exp[key] not in got:
                failures.append(f"{f}: expected to contain {exp[key]!r}, got {got!r}")
        key_not = f + "_not_contains"
        if key_not in exp:
            got = actual.get(f) or ""
            if exp[key_not] in got:
                failures.append(f"{f}: should NOT contain {exp[key_not]!r}, got {got!r}")

    if "confidence_min" in exp:
        got = actual.get("confidence")
        if got is None or got < exp["confidence_min"]:
            failures.append(f"confidence: expected >= {exp['confidence_min']}, got {got!r}")

    if "confidence_max" in exp:
        got = actual.get("confidence")
        if got is None or got > exp["confidence_max"]:
            failures.append(f"confidence: expected <= {exp['confidence_max']}, got {got!r}")

    return (len(failures) == 0, failures)


# ═══════════════════════════════════════════════════════════════════════
# ROUTER CALL — wired to the REAL production router.
# ═══════════════════════════════════════════════════════════════════════

def call_router(tc: TestCase) -> dict:
    """Run the transcript through the live router used in production.

    Uses `voice_service._understand_via_gpt_text`, which sends the real
    `_SYSTEM` prompt with structured output (VoiceUnderstanding) and applies
    the same `_sanitize` post-processing the webhook uses. TODAY is injected
    from the system clock inside that function, so date-relative expectations
    assume the machine date matches `TestCase.today` (see the guard in run()).
    """
    from app.services import voice_service as vs

    understanding, _usage = vs._understand_via_gpt_text(
        tc.transcript,
        tc.options_json,
        current_step=tc.current_step,
    )
    d = understanding.model_dump()
    return {
        "action": d.get("action"),
        "intent": d.get("intent"),
        "doctor_hint": d.get("doctor_hint"),
        "specialty_hint": d.get("specialty_hint"),
        "date_hint": d.get("date_hint"),
        "time_hint": d.get("time_hint"),
        "selected_option_id": d.get("selected_option_id"),
        "change_target": d.get("change_target"),
        "language": d.get("language"),
        "confidence": d.get("confidence"),
        "summary_ar": d.get("summary_ar"),
    }


# ═══════════════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════════════

def run(cases: list[TestCase] = CASES, router=call_router) -> None:
    # Date-relative cases assume the machine date == the cases' `today`.
    machine_today = date.today().isoformat()
    case_today = cases[0].today if cases else machine_today
    if machine_today != case_today:
        print(
            f"⚠️  Machine date is {machine_today} but cases assume TODAY={case_today}. "
            "Date-relative expectations (بكرة / يوم الأحد / tomorrow) may report as "
            "failures even when the router is correct.\n"
        )

    results = []
    for tc in cases:
        try:
            actual = router(tc)
            passed, failures = score_case(tc, actual)
        except NotImplementedError as e:
            print(f"⚠️  {e}\n")
            return
        except Exception as e:
            passed, failures, actual = False, [f"router raised: {e!r}"], {}
        results.append((tc, passed, failures, actual))

    # Per-case report
    n_pass = sum(1 for _, p, _, _ in results if p)
    for tc, passed, failures, actual in results:
        mark = "PASS" if passed else "FAIL"
        print(f"[{mark}] {tc.id}: {tc.transcript!r}")
        if tc.note:
            print(f"    note: {tc.note}")
        if not passed:
            for f in failures:
                print(f"    - {f}")
            print(f"    got: {json.dumps(actual, ensure_ascii=False)}")
        print()

    print("=" * 60)
    print(f"OVERALL: {n_pass}/{len(results)} passed ({n_pass/len(results):.0%})")

    # Per-field accuracy (only counted where the field was actually checked)
    field_totals: dict[str, int] = {}
    field_fails: dict[str, int] = {}
    for tc, passed, failures, actual in results:
        checked_fields = {f.split(":")[0].strip() for f in failures} | (
            set(tc.expected) & set(SIMPLE_FIELDS)
        )
        for f in checked_fields:
            field_totals[f] = field_totals.get(f, 0) + 1
    for tc, passed, failures, actual in results:
        for f in failures:
            key = f.split(":")[0].strip()
            field_fails[key] = field_fails.get(key, 0) + 1

    print("\nPer-field accuracy (fields with reported failures):")
    for f in sorted(field_totals):
        total = field_totals[f]
        fails = field_fails.get(f, 0)
        acc = (total - fails) / total if total else 0
        print(f"  {f:22s} {acc:.0%}  ({total - fails}/{total})")


if __name__ == "__main__":
    run()
