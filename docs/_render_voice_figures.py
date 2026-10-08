"""Render figures for the Split Voice System presentation PDFs."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "images" / "voice"
OUT.mkdir(parents=True, exist_ok=True)

TEAL = (15, 118, 110)
TEAL_DK = (19, 78, 74)
TEAL_LT = (204, 251, 241)
TEAL_MD = (153, 246, 228)
WHITE = (255, 255, 255)
INK = (17, 24, 39)
MUTED = (75, 85, 99)
LINE = (100, 116, 139)
BOX_BG = (248, 250, 252)
ACCENT = (14, 165, 233)
ORANGE = (234, 88, 12)
PURPLE = (124, 58, 237)
GREEN = (22, 163, 74)
RED = (220, 38, 38)
WA_GREEN = (37, 211, 102)
WA_DARK = (7, 94, 84)
BUBBLE_IN = (255, 255, 255)
BUBBLE_OUT = (220, 248, 198)


def font(size: int, bold: bool = False):
    candidates = [
        ("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        ("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        ("C:/Windows/Fonts/tahoma.ttf"),
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def rounded(draw, xy, fill, outline=TEAL, width=2, radius=12):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def center_text(draw, box, text, fnt, fill=INK):
    x0, y0, x1, y1 = box
    bbox = draw.textbbox((0, 0), text, font=fnt)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((x0 + x1 - tw) / 2, (y0 + y1 - th) / 2), text, font=fnt, fill=fill)


def multiline_center(draw, box, lines, fnt, fill=INK, gap=2):
    x0, y0, x1, y1 = box
    heights, widths = [], []
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=fnt)
        widths.append(bb[2] - bb[0])
        heights.append(bb[3] - bb[1])
    total_h = sum(heights) + gap * (len(lines) - 1)
    y = (y0 + y1 - total_h) / 2
    for i, line in enumerate(lines):
        draw.text(((x0 + x1 - widths[i]) / 2, y), line, font=fnt, fill=fill)
        y += heights[i] + gap


def arrow(draw, x1, y1, x2, y2, color=LINE, width=3):
    draw.line((x1, y1, x2, y2), fill=color, width=width)
    if abs(y2 - y1) >= abs(x2 - x1):
        direction = 1 if y2 > y1 else -1
        draw.polygon(
            [(x2, y2), (x2 - 7, y2 - 10 * direction), (x2 + 7, y2 - 10 * direction)],
            fill=color,
        )
    else:
        direction = 1 if x2 > x1 else -1
        draw.polygon(
            [(x2, y2), (x2 - 10 * direction, y2 - 7), (x2 - 10 * direction, y2 + 7)],
            fill=color,
        )


def save(img: Image.Image, name: str):
    path = OUT / name
    img.save(path, "PNG", optimize=True)
    print("OK", path.name, path.stat().st_size)


# ---------------------------------------------------------------------------
# 1. Big idea — Split
# ---------------------------------------------------------------------------
def fig_split_idea():
    w, h = 1400, 720
    img = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, 70), fill=TEAL)
    d.text((32, 18), "SPLIT VOICE SYSTEM", font=font(28, True), fill=WHITE)
    d.text((520, 28), "LLM plans  ·  Python proves", font=font(16), fill=TEAL_MD)

    # left brain
    rounded(d, (60, 120, 640, 620), (239, 246, 255), ACCENT, 3, 18)
    d.text((90, 145), "PLANNER", font=font(26, True), fill=ACCENT)
    d.text((90, 185), "GPT  ·  understands speech", font=font(16), fill=MUTED)
    for i, t in enumerate(
        [
            "Reads Whisper transcript",
            "Sees CURRENT_STEP + options",
            "Extracts slots (doctor / date / time)",
            "Picks furthest justified next_step",
            "Outputs VoicePlan JSON",
            "Does NOT touch the database",
        ]
    ):
        rounded(d, (90, 230 + i * 55, 610, 275 + i * 55), WHITE, ACCENT, 2, 10)
        d.text((110, 240 + i * 55), t, font=font(15, True), fill=INK)

    # right brain
    rounded(d, (760, 120, 1340, 620), TEAL_LT, TEAL, 3, 18)
    d.text((790, 145), "EXECUTOR", font=font(26, True), fill=TEAL)
    d.text((790, 185), "Python  ·  owns hospital truth", font=font(16), fill=MUTED)
    for i, t in enumerate(
        [
            "Validates doctors in DB",
            "Checks free slots / holds",
            "Advances booking funnel",
            "Degrades one step if blocked",
            "Sends WhatsApp reply",
            "Never re-guesses intent",
        ]
    ):
        rounded(d, (790, 230 + i * 55, 1310, 275 + i * 55), WHITE, TEAL, 2, 10)
        d.text((810, 240 + i * 55), t, font=font(15, True), fill=INK)

    # middle plus
    d.ellipse((655, 340, 745, 430), fill=TEAL)
    center_text(d, (655, 340, 745, 430), "+", font(36, True), WHITE)
    d.text((620, 640), "KEY: model is aggressive  ·  code is careful", font=font(16, True), fill=TEAL_DK)
    save(img, "v01-split-idea.png")


# ---------------------------------------------------------------------------
# 2. End-to-end pipeline
# ---------------------------------------------------------------------------
def fig_pipeline():
    w, h = 1500, 620
    img = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, 64), fill=TEAL)
    d.text((28, 16), "VOICE PIPELINE", font=font(26, True), fill=WHITE)
    d.text((320, 24), "WhatsApp audio → same booking funnel as text", font=font(15), fill=TEAL_MD)

    steps = [
        (40, "1", "Voice note", "WhatsApp OGG", WA_GREEN),
        (280, "2", "Whisper STT", "transcript", ORANGE),
        (520, "3", "GPT Planner", "VoicePlan", ACCENT),
        (760, "4", "Executor", "validate DB", TEAL),
        (1000, "5", "Funnel", "hold / ask / list", PURPLE),
        (1240, "6", "Reply", "text + buttons", GREEN),
    ]
    for x, num, title, sub, color in steps:
        rounded(d, (x, 160, x + 200, 360), BOX_BG, color, 3, 16)
        d.ellipse((x + 75, 180, x + 125, 230), fill=color)
        center_text(d, (x + 75, 180, x + 125, 230), num, font(18, True), WHITE)
        center_text(d, (x, 250, x + 200, 295), title, font(16, True), INK)
        center_text(d, (x, 295, x + 200, 330), sub, font(13), MUTED)
    for i in range(5):
        x1 = steps[i][0] + 200
        x2 = steps[i + 1][0]
        arrow(d, x1 + 4, 260, x2 - 4, 260, LINE, 3)

    d.text((40, 420), "No outbound TTS — patient hears nothing synthetic. Bot replies as WhatsApp text / lists / buttons.", font=font(15, True), fill=MUTED)
    keywords = ["STT", "Planner", "Executor", "Degrade", "Funnel", "AR + EN"]
    x = 40
    for kw in keywords:
        bb = d.textbbox((0, 0), kw, font=font(14, True))
        tw = bb[2] - bb[0] + 28
        rounded(d, (x, 480, x + tw, 530), TEAL_LT, TEAL, 2, 20)
        center_text(d, (x, 480, x + tw, 530), kw, font(14, True), TEAL_DK)
        x += tw + 14
    save(img, "v02-pipeline.png")


# ---------------------------------------------------------------------------
# 3. WhatsApp GUI journey mockup
# ---------------------------------------------------------------------------
def _phone_frame(d, x0, y0, x1, y1, title):
    rounded(d, (x0, y0, x1, y1), (236, 229, 221), (30, 30, 30), 4, 28)
    # status bar
    d.rectangle((x0 + 8, y0 + 8, x1 - 8, y0 + 58), fill=WA_DARK)
    center_text(d, (x0 + 8, y0 + 8, x1 - 8, y0 + 58), title, font(13, True), WHITE)


def _bubble(d, x0, y, x1, text, outgoing=False, lines=None):
    fill = BUBBLE_OUT if outgoing else BUBBLE_IN
    outline = (180, 210, 160) if outgoing else (220, 220, 220)
    h = 36 + (len(lines or [text]) - 1) * 18
    rounded(d, (x0, y, x1, y + h), fill, outline, 1, 12)
    fnt = font(12)
    if lines:
        yy = y + 8
        for line in lines:
            d.text((x0 + 10, yy), line, font=fnt, fill=INK)
            yy += 18
    else:
        d.text((x0 + 10, y + 10), text, font=fnt, fill=INK)
    return y + h + 10


def fig_whatsapp_gui():
    w, h = 1500, 820
    img = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, 64), fill=TEAL)
    d.text((28, 16), "PATIENT GUI — WhatsApp Journey", font=font(24, True), fill=WHITE)
    d.text((520, 24), "Voice in  ·  Guided UI out", font=font(15), fill=TEAL_MD)

    phones = [
        (40, "1 · Speak", [
            ("in", ["🎤 Voice note 0:08"]),
            ("in", ["«عايز أحجز عند دكتور", "أحمد بكرة الساعة 2»"]),
        ]),
        (400, "2 · Bot understands", [
            ("out", ["Got it — booking with", "Dr Ahmed tomorrow."]),
            ("out", ["Checking 2:00 PM…"]),
        ]),
        (760, "3 · Confirm slot", [
            ("out", ["Slot held 14:00"]),
            ("out", ["Please confirm:"]),
            ("btn", ["✅ Confirm", "❌ Change"]),
        ]),
        (1120, "4 · Done", [
            ("out", ["✅ Appointment booked"]),
            ("out", ["Ref: NGU-4821", "Tomorrow · 14:00"]),
            ("btn", ["🏠 Main menu"]),
        ]),
    ]
    for x, title, msgs in phones:
        _phone_frame(d, x, 100, x + 320, 760, title)
        y = 120
        for kind, lines in msgs:
            if kind == "btn":
                for label in lines:
                    rounded(d, (x + 40, y, x + 280, y + 36), WHITE, WA_GREEN, 2, 18)
                    center_text(d, (x + 40, y, x + 280, y + 36), label, font(12, True), WA_DARK)
                    y += 44
            elif kind == "out":
                y = _bubble(d, x + 50, y, x + 290, "", outgoing=True, lines=lines)
            else:
                y = _bubble(d, x + 30, y, x + 270, "", outgoing=False, lines=lines)
        # mic hint on first phone
        if x == 40:
            d.ellipse((x + 130, 680, x + 190, 740), fill=WA_GREEN)
            center_text(d, (x + 130, 680, x + 190, 740), "🎤", font(22), WHITE)

    save(img, "v03-whatsapp-gui.png")


# ---------------------------------------------------------------------------
# 4. VoicePlan schema visual
# ---------------------------------------------------------------------------
def fig_voiceplan():
    w, h = 1400, 700
    img = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, 64), fill=TEAL)
    d.text((28, 16), "VoicePlan — What GPT Returns", font=font(24, True), fill=WHITE)

    rounded(d, (40, 100, 1360, 640), BOX_BG, TEAL, 3, 16)
    # columns
    cols = [
        (70, "goal", "WHAT patient wants", [
            "book_new", "reschedule", "cancel_appointment",
            "ask_doctors", "handover", "confirm", "unclear",
        ], ACCENT),
        (420, "next_step", "WHERE funnel goes", [
            "ask_specialty", "show_doctors", "ask_date",
            "show_slots", "hold_slot", "confirm_booking", "clarify",
        ], TEAL),
        (770, "slots", "EXTRACTED fields", [
            "doctor_name", "specialty", "date",
            "time", "change_target", "selected_option_id",
        ], PURPLE),
        (1080, "meta", "HELPERS", [
            "confidence", "language", "summary_ar",
            "summary_en", "followup_goal", "transcript",
        ], ORANGE),
    ]
    for x, title, sub, items, color in cols:
        rounded(d, (x, 130, x + 280, 600), WHITE, color, 3, 14)
        d.rectangle((x, 130, x + 280, 210), fill=color)
        center_text(d, (x, 135, x + 280, 175), title, font(20, True), WHITE)
        center_text(d, (x, 170, x + 280, 205), sub, font(12), TEAL_MD if color != ORANGE else (255, 237, 213))
        for i, item in enumerate(items):
            d.text((x + 24, 230 + i * 48), "•  " + item, font=font(15, True), fill=INK)
    save(img, "v04-voiceplan.png")


# ---------------------------------------------------------------------------
# 5. Degradation ladder
# ---------------------------------------------------------------------------
def fig_degrade():
    w, h = 1400, 680
    img = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, 64), fill=TEAL)
    d.text((28, 16), "DEGRADATION LADDER", font=font(24, True), fill=WHITE)
    d.text((420, 24), "If a step fails → fall one rung + explain", font=font(15), fill=TEAL_MD)

    rungs = [
        (80, "hold_slot", "Doctor + date + time free", GREEN),
        (200, "show_slots", "Doctor + day, time missing / taken", TEAL),
        (320, "ask_date", "Doctor known, day missing", ACCENT),
        (440, "show_doctors", "Specialty only / many names", PURPLE),
        (560, "ask_specialty", "Want book, nothing named", ORANGE),
    ]
    for y, step, why, color in rungs:
        rounded(d, (120, y, 520, y + 90), BOX_BG, color, 3, 14)
        center_text(d, (120, y, 520, y + 90), step, font(20, True), color)
        rounded(d, (580, y, 1280, y + 90), WHITE, color, 2, 14)
        d.text((610, y + 30), why, font=font(16, True), fill=INK)
        if y < 560:
            arrow(d, 320, y + 90, 320, y + 110, RED, 3)

    d.text((120, 640), "Never silent failure · Never duplicate menus · Always tell the patient why", font=font(15, True), fill=RED)
    save(img, "v05-degrade.png")


# ---------------------------------------------------------------------------
# 6. V1 vs V2
# ---------------------------------------------------------------------------
def fig_v1_v2():
    w, h = 1400, 700
    img = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, 64), fill=TEAL)
    d.text((28, 16), "V1 vs V2 — Why We Split", font=font(24, True), fill=WHITE)

    # V1
    rounded(d, (40, 100, 660, 640), (254, 242, 242), RED, 3, 16)
    d.text((70, 120), "V1  (legacy)", font=font(22, True), fill=RED)
    for i, t in enumerate(
        [
            "Model picks ~5 actions",
            "Python re-decides with thresholds",
            "Hedges → wrong step",
            "Duplicate menus common",
            "Fastpath maze mid-flow",
            "Hard to reason about",
        ]
    ):
        rounded(d, (70, 180 + i * 70, 630, 235 + i * 70), WHITE, RED, 2, 10)
        d.text((90, 195 + i * 70), "✕  " + t, font=font(15, True), fill=INK)

    # V2
    rounded(d, (740, 100, 1360, 640), TEAL_LT, TEAL, 3, 16)
    d.text((770, 120), "V2  (production)", font=font(22, True), fill=TEAL)
    for i, t in enumerate(
        [
            "Model emits a full VoicePlan",
            "Python only validates + runs",
            "Furthest justified step",
            "One-step degrade + explain",
            "No silent fastpath fall-through",
            "Flag: VOICE_ROUTER_V2=true",
        ]
    ):
        rounded(d, (770, 180 + i * 70, 1330, 235 + i * 70), WHITE, TEAL, 2, 10)
        d.text((790, 195 + i * 70), "✓  " + t, font=font(15, True), fill=INK)
    save(img, "v06-v1-v2.png")


# ---------------------------------------------------------------------------
# 7. Module map
# ---------------------------------------------------------------------------
def fig_modules():
    w, h = 1400, 720
    img = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, 64), fill=TEAL)
    d.text((28, 16), "CODE MAP — Voice Modules", font=font(24, True), fill=WHITE)

    mods = [
        (40, 100, "webhook.py", "Detect audio · queue _handle_voice", ORANGE),
        (480, 100, "voice_service.py", "Download OGG · Whisper · GPT plan", ACCENT),
        (920, 100, "voice_prompts.py", "PLANNER_SYSTEM (cache-friendly)", PURPLE),
        (40, 280, "voice_schemas.py", "VoicePlan · VoiceSlots types", TEAL),
        (480, 280, "voice_executor.py", "execute_plan · degrade · reply", GREEN),
        (920, 280, "voice_fastpath.py", "V1 mid-flow (fallback only)", MUTED),
        (40, 460, "voice_cost.py", "STT + GPT $ logging", ORANGE),
        (480, 460, "language_service.py", "Reply language after STT", ACCENT),
        (920, 460, "conversation_engine", "Same funnel as typed chat", TEAL_DK),
    ]
    for x, y, title, sub, color in mods:
        rounded(d, (x, y, x + 400, y + 140), BOX_BG, color, 3, 14)
        d.text((x + 24, y + 28), title, font=font(18, True), fill=color)
        d.text((x + 24, y + 70), sub, font=font(14), fill=INK)
    d.text((40, 640), "Voice is an alternate INPUT into the same booking product — not a separate bot.", font=font(15, True), fill=MUTED)
    save(img, "v07-modules.png")


# ---------------------------------------------------------------------------
# 8. Admin dashboard voice KPIs mock
# ---------------------------------------------------------------------------
def fig_admin_gui():
    w, h = 1400, 720
    img = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, 64), fill=TEAL)
    d.text((28, 16), "ADMIN GUI — Voice KPIs (Streamlit)", font=font(24, True), fill=WHITE)

    # sidebar
    rounded(d, (40, 100, 280, 660), TEAL_DK, TEAL_DK, 0, 12)
    d.text((60, 130), "Dashboard", font=font(16, True), fill=WHITE)
    for i, name in enumerate(["KPIs", "Conversations", "Usage", "Doctors", "Settings"]):
        fill = TEAL if i == 0 else TEAL_DK
        rounded(d, (55, 180 + i * 55, 265, 220 + i * 55), fill, fill, 0, 8)
        d.text((75, 190 + i * 55), name, font=font(14, True), fill=WHITE)

    # KPI cards
    cards = [
        (320, "Voice notes", "1,284", TEAL),
        (580, "Voice minutes", "642", ACCENT),
        (840, "Voice cost", "$18.40", ORANGE),
        (1100, "Avg $/voice", "$0.014", PURPLE),
    ]
    for x, title, val, color in cards:
        rounded(d, (x, 120, x + 240, 260), BOX_BG, color, 3, 14)
        d.text((x + 20, 140), title, font=font(14), fill=MUTED)
        d.text((x + 20, 180), val, font=font(32, True), fill=color)

    # transcript panel
    rounded(d, (320, 300, 1340, 660), BOX_BG, TEAL, 2, 14)
    d.text((350, 320), "Recent voice transcript", font=font(16, True), fill=TEAL_DK)
    rows = [
        ("+20…1234", "عايز دكتور قلب بكرة", "book_new → show_doctors", "ar"),
        ("+20…5678", "Cancel my Friday visit", "cancel_appointment → pick", "en"),
        ("+20…9012", "أحمد الساعة اتنين", "book_new → hold_slot", "ar"),
    ]
    y = 370
    for phone, tr, plan, lang in rows:
        rounded(d, (350, y, 1310, y + 70), WHITE, LINE, 1, 10)
        d.text((370, y + 12), phone, font=font(13, True), fill=MUTED)
        d.text((540, y + 12), tr, font=font(14, True), fill=INK)
        d.text((540, y + 38), plan, font=font(13), fill=TEAL)
        rounded(d, (1220, y + 18, 1285, y + 50), TEAL_LT, TEAL, 1, 10)
        center_text(d, (1220, y + 18, 1285, y + 50), lang, font(12, True), TEAL_DK)
        y += 85
    save(img, "v08-admin-gui.png")


# ---------------------------------------------------------------------------
# 9. Example walkthrough
# ---------------------------------------------------------------------------
def fig_example():
    w, h = 1400, 700
    img = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, 64), fill=TEAL)
    d.text((28, 16), "LIVE EXAMPLE — One Voice Note", font=font(24, True), fill=WHITE)

    rounded(d, (40, 100, 1360, 200), (255, 247, 237), ORANGE, 3, 12)
    d.text((70, 120), 'Patient says:', font=font(14), fill=MUTED)
    d.text((70, 150), "«عايز أحجز عند دكتور أحمد يوم الجمعة الساعة 2»", font=font(20, True), fill=INK)

    boxes = [
        (40, 240, "STT", "Arabic transcript\n(no language pin)", ORANGE),
        (380, 240, "PLAN", "goal: book_new\nnext_step: hold_slot\nslots: Ahmed / Fri / 14:00", ACCENT),
        (720, 240, "CHECK", "Doctor OK ✓\nFriday OK ✓\n14:00 free?", TEAL),
        (1060, 240, "ACT", "hold_slot\nor show_slots\n+ WhatsApp reply", GREEN),
    ]
    for x, y, title, body, color in boxes:
        rounded(d, (x, y, x + 300, y + 280), BOX_BG, color, 3, 14)
        d.rectangle((x, y, x + 300, y + 55), fill=color)
        center_text(d, (x, y, x + 300, y + 55), title, font(18, True), WHITE)
        lines = body.split("\n")
        multiline_center(d, (x, y + 70, x + 300, y + 260), lines, font(15, True), INK, gap=8)
    for i in range(3):
        arrow(d, boxes[i][0] + 300, 380, boxes[i + 1][0], 380, LINE, 3)

    d.text((40, 560), "If 14:00 taken → degrade to show_slots and say so. Patient never gets a silent wrong confirm.", font=font(15, True), fill=MUTED)
    d.text((40, 610), "Keywords: Whisper · VoicePlan · hold_slot · degrade · Egyptian Arabic · WhatsApp buttons", font=font(15, True), fill=TEAL_DK)
    save(img, "v09-example.png")


# ---------------------------------------------------------------------------
# 10. Benefits keywords wall
# ---------------------------------------------------------------------------
def fig_benefits():
    w, h = 1400, 700
    img = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, 64), fill=TEAL)
    d.text((28, 16), "WHY IT MATTERS — Keywords", font=font(24, True), fill=WHITE)

    items = [
        (40, 110, "Separation", "LLM understands\nPython owns truth", TEAL),
        (380, 110, "Aggressive", "Furthest justified\nstep every time", ACCENT),
        (720, 110, "Safe fail", "One-rung degrade\n+ clear explanation", ORANGE),
        (1060, 110, "Dialect", "Egyptian Arabic\n+ code-switch", PURPLE),
        (40, 380, "One product", "Voice = input\nSame booking funnel", GREEN),
        (380, 380, "Observable", "Transcripts · cost\nDashboard KPIs", TEAL_DK),
        (720, 380, "Cacheable", "Static planner\nprompt → cheaper", ACCENT),
        (1060, 380, "Rollback", "VOICE_ROUTER_V2\nflag to V1", MUTED),
    ]
    for x, y, title, body, color in items:
        rounded(d, (x, y, x + 300, y + 220), BOX_BG, color, 3, 16)
        d.text((x + 24, y + 24), title, font=font(20, True), fill=color)
        lines = body.split("\n")
        yy = y + 80
        for line in lines:
            d.text((x + 24, yy), line, font=font(16), fill=INK)
            yy += 32
    save(img, "v10-benefits.png")


def main():
    fig_split_idea()
    fig_pipeline()
    fig_whatsapp_gui()
    fig_voiceplan()
    fig_degrade()
    fig_v1_v2()
    fig_modules()
    fig_admin_gui()
    fig_example()
    fig_benefits()
    print("Done ->", OUT)


if __name__ == "__main__":
    main()
