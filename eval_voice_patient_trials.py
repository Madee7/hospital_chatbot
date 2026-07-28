r"""Act as a patient: simulate voice notes as text transcripts end-to-end.

Pipeline per turn (same as production V2 voice, minus Whisper):
  transcript → GPT VoicePlan → sanitize + execute_plan → capture WA replies

Uses the real DB (seed doctors/slots). WhatsApp is mocked so nothing is sent.

Run (PowerShell, repo root):
  $env:PYTHONIOENCODING="utf-8"
  $env:VOICE_ROUTER_V2="true"
  python eval_voice_patient_trials.py

  # LLM-only planner checks (no executor / no WA side effects):
  python eval_voice_patient_trials.py --planner-only

  # Offline: inject bad LLM plans (no OpenAI) to prove sanitize/executor:
  python eval_voice_patient_trials.py --offline-sanitize
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

os.environ.setdefault("VOICE_ROUTER_V2", "true")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.config import DEFAULT_CLINIC_ID, DEFAULT_TENANT_ID  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.graph import conversation_engine  # noqa: E402
from app.graph.conversation_engine import _SESSION, _sess  # noqa: E402
from app.services import conversation_service, doctor_service, voice_executor  # noqa: E402
from app.services import whatsapp_client as wa_mod  # noqa: E402
from app.services.voice_schemas import VoicePlan  # noqa: E402
from app.services.voice_service import _plan_via_gpt_text  # noqa: E402


PHONE = "2010000VOICE_EVAL"


# ---------------------------------------------------------------------------
# Expectations
# ---------------------------------------------------------------------------


@dataclass
class Expect:
    """What a good patient experience looks like after one voice turn."""

    steps: set[str] = field(default_factory=set)  # executor result.step
    plan_steps: set[str] = field(default_factory=set)  # raw LLM next_step (optional)
    specialty_set: bool | None = None  # plan.slots.specialty after sanitize
    specialty_contains: str | None = None  # substring in plan.slots.specialty
    doctor_null: bool | None = None  # plan.slots.doctor_name is None after sanitize
    present_any: set[str] = field(default_factory=set)
    present_none: set[str] = field(default_factory=set)
    texts_any: list[str] = field(default_factory=list)  # substring must appear in some text
    texts_none: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class Turn:
    say: str  # simulated Whisper transcript
    expect: Expect
    # Optional: inject a bad plan instead of calling the LLM (offline mode)
    inject_plan: dict | None = None


@dataclass
class Journey:
    id: str
    title: str
    turns: list[Turn]
    # Seed session before turn 1 (previous booking context)
    seed_sess: dict[str, Any] = field(default_factory=dict)
    seed_doctor_id: int | None = None  # resolve known_doctor into sess


# ---------------------------------------------------------------------------
# Current-step snapshot (mirrors webhook._voice_current_step)
# ---------------------------------------------------------------------------


def _current_step(db, phone: str, conversation) -> dict | None:
    sess = _sess(phone)
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


# ---------------------------------------------------------------------------
# Journeys — hard patient trails
# ---------------------------------------------------------------------------


def _journeys() -> list[Journey]:
    return [
        # ---- The bugs that made voice feel "so bad" ----
        Journey(
            id="specialty_eyes_as_doctor",
            title="Patient says 'دكتور عيون' (specialty parked as doctor name)",
            turns=[
                Turn(
                    say="عايز دكتور عيون",
                    expect=Expect(
                        steps={"show_doctors"},
                        doctor_null=True,
                        specialty_set=True,
                        present_any={"_present_department_doctors"},
                        present_none={"_present_dates"},
                        note="Must list ophthalmology doctors, not 'doctor not found'",
                    ),
                ),
            ],
        ),
        Journey(
            id="switch_specialty_after_mona",
            title="After Mona (derm), patient switches to cardiology",
            seed_doctor_id=7,  # د. منى يوسف (Dermatology) in seed_demo
            seed_sess={"awaiting": "date", "flow": "booking"},
            turns=[
                Turn(
                    say="دكتور قلب",
                    expect=Expect(
                        steps={"show_doctors"},
                        doctor_null=True,
                        specialty_set=True,
                        present_any={"_present_department_doctors"},
                        present_none={"_present_dates"},
                        note="Must NOT open Mona's date picker",
                    ),
                ),
            ],
        ),
        Journey(
            id="switch_specialty_injected_bad_plan",
            title="Offline: LLM keeps Mona + asks ask_date for 'دكتور قلب'",
            seed_doctor_id=7,
            seed_sess={"awaiting": "date", "flow": "booking", "doctor_id": 7},
            turns=[
                Turn(
                    say="دكتور قلب",
                    inject_plan={
                        "transcript": "دكتور قلب",
                        "goal": "book_new",
                        "next_step": "ask_date",
                        "slots": {
                            "doctor_name": "منى يوسف",
                            "specialty": "قلب",
                            "selected_option_id": "doctor_7",
                        },
                        "confidence": {"overall": 0.9},
                        "language": "ar",
                    },
                    expect=Expect(
                        steps={"show_doctors"},
                        doctor_null=True,
                        present_any={"_present_department_doctors"},
                        present_none={"_present_dates"},
                        note="Sanitize must drop carried Mona + stale doctor_7 option",
                    ),
                ),
            ],
        ),
        Journey(
            id="eyes_injected_as_doctor_name",
            title="Offline: LLM puts عيون in doctor_name",
            turns=[
                Turn(
                    say="دكتور عيون",
                    inject_plan={
                        "transcript": "دكتور عيون",
                        "goal": "book_new",
                        "next_step": "show_doctors",
                        "slots": {"doctor_name": "عيون"},
                        "confidence": {"overall": 0.85},
                        "language": "ar",
                    },
                    expect=Expect(
                        steps={"show_doctors"},
                        doctor_null=True,
                        specialty_set=True,
                        present_any={"_present_department_doctors"},
                        present_none={"_present_dates"},
                    ),
                ),
            ],
        ),
        # ---- Happy / midflow hard paths ----
        Journey(
            id="specialty_heart",
            title="Cardiology specialty ask",
            turns=[
                Turn(
                    say="عايز أحجز عند دكتور قلب",
                    expect=Expect(
                        steps={"show_doctors"},
                        specialty_set=True,
                        doctor_null=True,
                        present_any={"_present_department_doctors"},
                    ),
                ),
            ],
        ),
        Journey(
            id="named_doctor_nour",
            title="Named doctor → day picker",
            turns=[
                Turn(
                    say="احجز مع دكتور نور الدين",
                    expect=Expect(
                        steps={"ask_date"},
                        present_any={"_present_dates"},
                        present_none={"_present_department_doctors"},
                    ),
                ),
            ],
        ),
        Journey(
            id="multi_switch_then_pick",
            title="Multi-turn: eyes → heart → pick أحمد سمير",
            turns=[
                Turn(
                    say="دكتور عيون",
                    expect=Expect(
                        steps={"show_doctors"},
                        present_any={"_present_department_doctors"},
                    ),
                ),
                Turn(
                    say="لا خلاص عايز قلب",
                    expect=Expect(
                        steps={"show_doctors"},
                        specialty_set=True,
                        present_any={"_present_department_doctors"},
                        present_none={"_present_dates"},
                        note="Specialty change mid-list",
                    ),
                ),
                Turn(
                    say="دكتور أحمد سمير",
                    expect=Expect(
                        steps={"ask_date"},
                        present_any={"_present_dates"},
                    ),
                ),
            ],
        ),
        Journey(
            id="whisper_garbage_then_recover",
            title="Bad Whisper then clear specialty",
            turns=[
                Turn(
                    say="أهجز أصو",
                    expect=Expect(
                        steps={"clarify", "show_menu", "ask_specialty"},
                        note="Gibberish must not invent a doctor booking",
                    ),
                ),
                Turn(
                    say="عايز دكتور أسنان",
                    expect=Expect(
                        steps={"show_doctors"},
                        specialty_set=True,
                        present_any={"_present_department_doctors"},
                    ),
                ),
            ],
        ),
        Journey(
            id="english_specialty",
            title="English specialty ask",
            turns=[
                Turn(
                    say="I need an eye doctor",
                    expect=Expect(
                        steps={"show_doctors", "ask_specialty"},
                        present_none={"_present_dates"},
                        note="English ophthalmology path — must not jump to a random doctor's dates",
                    ),
                ),
            ],
        ),
        Journey(
            id="english_named_doctor",
            title="English named doctor",
            turns=[
                Turn(
                    say="Book with doctor Dina Hassan",
                    expect=Expect(
                        steps={"ask_date", "show_slots", "hold_slot"},
                        present_none={"_present_department_doctors"},
                        note="Must land on Dina's calendar/slots, not specialty list",
                    ),
                ),
            ],
        ),
        Journey(
            id="two_doctors_or",
            title="Ambiguous 'أحمد أو علي'",
            turns=[
                Turn(
                    say="عايز أحجز مع دكتور أحمد أو دكتور علي",
                    expect=Expect(
                        steps={"show_doctors", "ask_date", "ask_specialty", "clarify"},
                        present_none={},  # dates ok if it resolved one seed doctor named أحمد
                        note="Soft: listing both is ideal; holding a slot without picking is not",
                    ),
                ),
            ],
        ),
        Journey(
            id="change_day_midflow",
            title="Change the day while picking a slot",
            seed_doctor_id=4,  # نور الدين
            seed_sess={
                "awaiting": "slot",
                "flow": "booking",
                "selected_date": "2026-07-28",
            },
            turns=[
                Turn(
                    say="عايز أغير اليوم",
                    expect=Expect(
                        steps={"ask_date"},
                        present_any={"_present_dates"},
                    ),
                ),
            ],
        ),
        Journey(
            id="abandon_draft",
            title="Abandon draft booking",
            seed_doctor_id=4,
            seed_sess={"awaiting": "confirm", "flow": "booking"},
            turns=[
                Turn(
                    say="خلاص سيبك من الحجز ده",
                    expect=Expect(
                        steps={"show_menu", "clarify"},
                        present_none={"_present_dates", "_present_slots"},
                    ),
                ),
            ],
        ),
        Journey(
            id="unknown_doctor_name",
            title="Made-up doctor name",
            turns=[
                Turn(
                    say="احجز مع دكتور زيزو الفراولة",
                    expect=Expect(
                        steps={"show_doctors", "ask_specialty", "clarify"},
                        present_none={"_present_dates"},
                        note="Explain miss; do not open random dates",
                    ),
                ),
            ],
        ),
        Journey(
            id="patient_name_not_doctor",
            title="Patient name must not become doctor",
            turns=[
                Turn(
                    say="احجز لمحمد إبراهيم مع دكتور نور الدين",
                    expect=Expect(
                        steps={"ask_date", "show_slots", "hold_slot"},
                        present_none={"_present_department_doctors"},
                        note="محمد إبراهيم is the patient, not the doctor",
                    ),
                ),
            ],
        ),
        Journey(
            id="code_switch",
            title="Code-switch English + Arabic doctor",
            turns=[
                Turn(
                    say="I want to book with دكتور نور الدين tomorrow",
                    expect=Expect(
                        steps={"ask_date", "show_slots", "hold_slot"},
                        present_none={"_present_department_doctors"},
                    ),
                ),
            ],
        ),
        Journey(
            id="teeth_then_bones",
            title="Specialty hop: teeth → bones",
            turns=[
                Turn(
                    say="دكتور أسنان",
                    expect=Expect(
                        steps={"show_doctors"},
                        present_any={"_present_department_doctors"},
                    ),
                ),
                Turn(
                    say="لا عظام أحسن",
                    expect=Expect(
                        steps={"show_doctors"},
                        specialty_contains="عظام",
                        present_any={"_present_department_doctors"},
                        present_none={"_present_dates"},
                        note="Must switch specialty to عظام, not keep أسنان",
                    ),
                ),
            ],
        ),
    ]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


PRESENT_HELPERS = (
    "_present_doctor_list",
    "_present_department_doctors",
    "_present_dates",
    "_present_slots",
)


def _reset_phone(phone: str) -> None:
    _SESSION.pop(phone, None)


def _seed_journey(db, journey: Journey, phone: str, conversation) -> None:
    sess = _sess(phone)
    sess.clear()
    sess.update(journey.seed_sess or {})
    if journey.seed_doctor_id is not None:
        sess["doctor_id"] = journey.seed_doctor_id
    if journey.seed_sess.get("awaiting") == "confirm":
        from app.db.enums import ConversationState

        conversation_service.set_conversation_state(
            db, conversation, ConversationState.CONFIRMING, current_intent="eval"
        )
    elif journey.seed_sess.get("awaiting") in {"date", "slot", "doctor"}:
        from app.db.enums import ConversationState

        state = {
            "date": ConversationState.BOOKING_DATE,
            "slot": ConversationState.BOOKING_SLOT,
            "doctor": ConversationState.BOOKING_DOCTOR,
        }[journey.seed_sess["awaiting"]]
        conversation_service.set_conversation_state(
            db, conversation, state, current_intent="eval"
        )
    db.commit()


def _check(expect: Expect, *, plan: VoicePlan, result, presented: list[str], texts: list[str]) -> list[str]:
    fails: list[str] = []
    if expect.steps and result.step not in expect.steps:
        fails.append(f"step={result.step!r} not in {sorted(expect.steps)}")
    if expect.plan_steps and plan.next_step not in expect.plan_steps:
        fails.append(f"plan.next_step={plan.next_step!r} not in {sorted(expect.plan_steps)}")
    if expect.doctor_null is True and plan.slots.doctor_name:
        fails.append(f"doctor_name should be null, got {plan.slots.doctor_name!r}")
    if expect.doctor_null is False and not plan.slots.doctor_name:
        fails.append("doctor_name should be set")
    if expect.specialty_set is True and not (plan.slots.specialty or "").strip():
        fails.append("specialty should be set")
    if expect.specialty_set is False and plan.slots.specialty:
        fails.append(f"specialty should be null, got {plan.slots.specialty!r}")
    if expect.specialty_contains and expect.specialty_contains not in (plan.slots.specialty or ""):
        fails.append(
            f"specialty should contain {expect.specialty_contains!r}, got {plan.slots.specialty!r}"
        )
    if expect.present_any and not (expect.present_any & set(presented)):
        fails.append(f"expected one of {sorted(expect.present_any)}, got {presented}")
    for banned in expect.present_none:
        if banned in presented:
            fails.append(f"must not present {banned}")
    blob = " | ".join(texts)
    for needle in expect.texts_any:
        if needle not in blob:
            fails.append(f"missing text containing {needle!r}")
    for needle in expect.texts_none:
        if needle in blob:
            fails.append(f"forbidden text {needle!r} appeared")
    return fails


def _run_turn(
    db,
    *,
    phone: str,
    conversation,
    turn: Turn,
    planner_only: bool,
    allow_llm: bool,
) -> tuple[VoicePlan, Any, list[str], list[str], dict[str, int]]:
    step_ctx = _current_step(db, phone, conversation)
    usage: dict[str, int] = {}

    if turn.inject_plan is not None:
        plan = VoicePlan.model_validate(turn.inject_plan)
    elif allow_llm:
        plan, usage = _plan_via_gpt_text(turn.say, None, current_step=step_ctx)
        # Attach transcript if model omitted it
        if not plan.transcript:
            plan = plan.model_copy(update={"transcript": turn.say})
    else:
        raise RuntimeError(f"Turn needs LLM but --offline-sanitize only: {turn.say!r}")

    if planner_only:
        # Still run sanitize so doctor_null / specialty_set checks match production
        plan = voice_executor._sanitize_plan_slots(db, plan)
        fake = SimpleNamespace(step=plan.next_step, reason="", degraded=False)
        return plan, fake, [], [], usage

    presented: list[str] = []
    texts: list[str] = []
    wa = MagicMock()
    # Engine helpers call WhatsApp for lists/cards — never hit Meta in eval.
    for name in (
        "send_text",
        "send_buttons",
        "send_list",
        "send_image",
        "send_doctor_flow",
        "send_cta_url",
    ):
        if hasattr(wa, name):
            getattr(wa, name).return_value = {"messages": [{"id": "eval"}]}

    def _track(name: str) -> Callable:
        def _inner(*a, **kw):
            presented.append(name)
            # Keep session side-effects the real helper would set, without WA.
            sess = _sess(phone)
            if name == "_present_department_doctors":
                dept_id = a[3] if len(a) > 3 else kw.get("department_id")
                sess["flow"] = sess.get("flow") or "booking"
                sess["department_id"] = dept_id
                sess["doctor_pick_mode"] = "by_specialty"
                sess["awaiting"] = "doctor"
                sess.pop("doctor_id", None)
            elif name == "_present_doctor_list":
                sess["flow"] = sess.get("flow") or "booking"
                sess["doctor_pick_mode"] = "by_name"
                sess["awaiting"] = "doctor"
            elif name == "_present_dates":
                doctor_id = a[2] if len(a) > 2 else kw.get("doctor_id")
                sess["flow"] = sess.get("flow") or "booking"
                sess["doctor_id"] = doctor_id
                sess["awaiting"] = "date"
            elif name == "_present_slots":
                sess["awaiting"] = "slot"
            return True

        return _inner

    stack_patches = [
        patch.object(voice_executor, "wa", wa),
        patch.object(conversation_engine, "wa", wa),
        patch.object(wa_mod, "send_text", wa.send_text),
        patch.object(wa_mod, "send_buttons", wa.send_buttons),
        patch.object(wa_mod, "send_list", wa.send_list),
    ]
    for h in PRESENT_HELPERS:
        stack_patches.append(patch.object(voice_executor, h, side_effect=_track(h)))

    for p in stack_patches:
        p.start()
    try:
        result = voice_executor.execute_plan(
            db, phone=phone, plan=plan, conversation=conversation
        )
        # execute_plan sanitizes a local copy; re-sanitize for assertions
        plan = voice_executor._sanitize_plan_slots(db, plan)
    finally:
        for p in reversed(stack_patches):
            p.stop()

    for call in wa.send_text.call_args_list:
        if call.args and len(call.args) > 1:
            texts.append(str(call.args[1]))
        elif call.kwargs.get("text"):
            texts.append(str(call.kwargs["text"]))

    return plan, result, presented, texts, usage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--planner-only",
        action="store_true",
        help="Call GPT planner + sanitize only (no WA / no booking side effects)",
    )
    parser.add_argument(
        "--offline-sanitize",
        action="store_true",
        help="Only journeys with inject_plan (no OpenAI calls)",
    )
    parser.add_argument("--only", type=str, default="", help="Comma-separated journey ids")
    args = parser.parse_args()

    only = {x.strip() for x in args.only.split(",") if x.strip()}
    journeys = _journeys()
    if args.offline_sanitize:
        journeys = [j for j in journeys if any(t.inject_plan for t in j.turns)]
        # Keep only inject turns
        for j in journeys:
            j.turns = [t for t in j.turns if t.inject_plan]
    if only:
        journeys = [j for j in journeys if j.id in only]

    db = SessionLocal()
    conversation = conversation_service.get_or_create_conversation(
        db,
        tenant_id=DEFAULT_TENANT_ID,
        clinic_id=DEFAULT_CLINIC_ID,
        phone=PHONE,
    )
    db.commit()

    passed = failed = skipped = 0
    total_in = total_out = 0

    print("=" * 72)
    print("PATIENT VOICE TRIALS (text = simulated Whisper transcript)")
    print(f"mode: {'offline-sanitize' if args.offline_sanitize else 'planner-only' if args.planner_only else 'full e2e'}")
    print("=" * 72)

    try:
        for journey in journeys:
            print(f"\n### {journey.id}: {journey.title}")
            _reset_phone(PHONE)
            _seed_journey(db, journey, PHONE, conversation)

            journey_ok = True
            for i, turn in enumerate(journey.turns, 1):
                if args.offline_sanitize and not turn.inject_plan:
                    skipped += 1
                    continue
                if not args.offline_sanitize and turn.inject_plan and args.planner_only:
                    # Still useful offline-style inside planner-only? skip inject
                    pass

                try:
                    plan, result, presented, texts, usage = _run_turn(
                        db,
                        phone=PHONE,
                        conversation=conversation,
                        turn=turn,
                        planner_only=args.planner_only,
                        allow_llm=not args.offline_sanitize,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"  T{i} ERROR  said={turn.say!r}")
                    print(f"         {type(exc).__name__}: {exc}")
                    journey_ok = False
                    failed += 1
                    continue

                total_in += usage.get("prompt_tokens", 0)
                total_out += usage.get("completion_tokens", 0)
                # For inject/offline, sanitize again is already done in execute
                fails = _check(
                    turn.expect,
                    plan=plan,
                    result=result,
                    presented=presented,
                    texts=texts,
                )
                mark = "OK  " if not fails else "FAIL"
                print(f"  T{i} {mark}  patient: {turn.say}")
                print(
                    f"         plan: goal={plan.goal} step={plan.next_step} "
                    f"doc={plan.slots.doctor_name!r} spec={plan.slots.specialty!r} "
                    f"lang={plan.language}"
                )
                if not args.planner_only:
                    print(
                        f"         exec: step={result.step} degraded={getattr(result, 'degraded', False)} "
                        f"reason={getattr(result, 'reason', '')!r}"
                    )
                    print(f"         ui  : {presented or ['(no list/picker)']}")
                    if texts:
                        for t in texts[:3]:
                            print(f"         msg : {t[:120]}")
                if turn.expect.note:
                    print(f"         note: {turn.expect.note}")
                if fails:
                    journey_ok = False
                    failed += 1
                    for f in fails:
                        print(f"         !! {f}")
                else:
                    passed += 1

            if journey_ok:
                print("  → journey PASS")
            else:
                print("  → journey FAIL")
    finally:
        _reset_phone(PHONE)
        db.close()

    total = passed + failed
    print("\n" + "=" * 72)
    print(f"turns: {passed} passed / {failed} failed / {total} scored" + (f" ({skipped} skipped)" if skipped else ""))
    if total_in or total_out:
        print(f"tokens: in={total_in} out={total_out}")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
