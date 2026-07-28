r"""Live check of the V2 planner prompt + schema against real transcripts.

Bypasses Whisper and the executor: feeds transcripts straight to the planner LLM
and prints the plan, so we can see whether the model picks the furthest justified
step instead of hedging to clarify. Cases marked (V1-BUG) are the ones the old
classifier got wrong.

Run:  python eval_voice_planner_v2.py
"""

from __future__ import annotations

import os

os.environ.setdefault("VOICE_ROUTER_V2", "true")

from app.services.voice_service import _plan_via_gpt_text  # noqa: E402

# (label, transcript, current_step, acceptable next_step(s))
CASES: list[tuple[str, str, dict | None, str]] = [
    (
        "greeting",
        "السلام عليكم",
        None,
        "show_menu",
    ),
    (
        "doctor + day + time (V1 hedged to clarify)",
        "عايز أحجز مع دكتور نور الدين يوم الاتنين الساعة اتنين",
        None,
        "hold_slot",
    ),
    (
        "doctor + day + time + patient name (V1 could not carry the name)",
        "احجز لمحمد إبراهيم مع دكتورة دينا حسن بكرة الساعة أربعة",
        None,
        "hold_slot",
    ),
    (
        "specialty only",
        "عايز دكتور أسنان",
        None,
        "show_doctors",
    ),
    (
        "earliest available, no date named",
        "أقرب موعد متاح مع دكتور عمر خالد",
        None,
        "show_slots",
    ),
    (
        "availability question (V1-BUG: scored clarify → random menu)",
        "ايه المواعيد المتاحة لدكتور عمر خالد؟",
        None,
        "show_slots",
    ),
    (
        "new booking while typing a name (V1-BUG: taken as the name)",
        "لا لا انا عايز أحجز مع دكتور نور الدين",
        {"awaiting": "patient_name", "state": "BOOKING_NAME"},
        "ask_date",  # doctor but no day spoken → day picker is correct
    ),
    (
        "abandon draft, not cancel a booking (V1 conflated them)",
        "خلاص سيبك من الحجز ده",
        {"awaiting": "confirm", "state": "BOOKING_CONFIRM"},
        "show_menu",
    ),
    (
        "cancel a real appointment",
        "عايز ألغي معاد الكشف بكرة",
        None,
        "pick_appointment",  # which appointment isn't known yet
    ),
    (
        "change the day at the slot step",
        "عايز أغير اليوم",
        {"awaiting": "slot", "state": "BOOKING_SLOT", "known_doctor": "نور الدين"},
        "ask_date",
    ),
    (
        "English booking (must stay English)",
        "I want to book with doctor Dina Hassan on Tuesday at 3 pm",
        None,
        "hold_slot",
    ),
    (
        "English availability question",
        "what times does doctor Omar have this week?",
        None,
        "show_slots",
    ),
    (
        "compound: cancel then rebook",
        "الغي معاد بكرة واحجزلي بدالة يوم الخميس",
        None,
        "pick_appointment",  # first request runs, rebook lands in followup_goal
    ),
    (
        "two candidate doctors (V1 kept only one)",
        "عايز أحجز مع دكتور أحمد أو دكتور علي",
        None,
        "show_doctors",
    ),
    (
        # KNOWN GAP (kept failing on purpose so it stays visible): with a doctor
        # and a day but no time, the model still prefers ask_date over show_slots
        # however the rule is worded. Not language-specific — the Arabic phrasing
        # behaves identically — and it only costs one extra tap, since the day
        # picker still leads to the right slots. Language detection here is
        # correct, which is what this case primarily guards.
        "code-switched, English sentence + Arabic doctor name -> reply English",
        "I want to book with دكتور نور الدين on Tuesday",
        None,
        "show_slots",
    ),
    (
        "English, change the day at the slot step",
        "I want to change the day please",
        {"awaiting": "slot", "state": "BOOKING_SLOT", "known_doctor": "Nour"},
        "ask_date",
    ),
    (
        "genuinely unintelligible",
        # Either fallback is fine: clarify asks for a repeat, show_menu is
        # prefixed with "didn't catch that" by the engine.
        "اممم ايوه يعني",
        None,
        "clarify|show_menu",
    ),
    (
        "thanks, not a booking",
        "شكرا جزيلا",
        None,
        "show_menu",
    ),
]


def main() -> None:
    total_in = total_out = 0
    hits = 0
    for label, transcript, step, expected in CASES:
        try:
            plan, usage = _plan_via_gpt_text(transcript, None, current_step=step)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] {label}: {type(exc).__name__}: {exc}\n")
            continue

        total_in += usage.get("prompt_tokens", 0)
        total_out += usage.get("completion_tokens", 0)
        ok = plan.next_step in expected.split("|")
        hits += ok
        s = plan.slots
        print(f"{'OK ' if ok else 'DIFF'} {label}")
        print(f"     said : {transcript}")
        print(f"     goal={plan.goal} step={plan.next_step} (expected {expected})")
        print(
            f"     slots: doctor={s.doctor_name!r} alts={s.doctor_alternatives!r} "
            f"spec={s.specialty!r} date={s.date!r}/{s.date_flexibility} time={s.time!r} "
            f"patient={s.patient_name!r} change={s.change_target!r}"
        )
        print(
            f"     conf : overall={plan.confidence.overall} doctor={plan.confidence.doctor} "
            f"date={plan.confidence.date} time={plan.confidence.time}"
        )
        print(f"     lang={plan.language} followup={plan.followup_goal}\n")

    print(f"matched expectation: {hits}/{len(CASES)}")
    print(f"tokens: in={total_in} out={total_out} (~{total_in / max(len(CASES), 1):.0f} in/call)")


if __name__ == "__main__":
    main()
