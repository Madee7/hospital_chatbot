"""Render architecture flowchart PNGs for DOCUMENTATION.md / PDF export."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "images"
OUT.mkdir(exist_ok=True)

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


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
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


def rounded(draw: ImageDraw.ImageDraw, xy, fill, outline=TEAL, width=2, radius=12):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def center_text(draw, box, text, fnt, fill=INK):
    x0, y0, x1, y1 = box
    bbox = draw.textbbox((0, 0), text, font=fnt)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((x0 + x1 - tw) / 2, (y0 + y1 - th) / 2), text, font=fnt, fill=fill)


def multiline_center(draw, box, lines, fnt, fill=INK, gap=2):
    x0, y0, x1, y1 = box
    heights = []
    widths = []
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=fnt)
        widths.append(bb[2] - bb[0])
        heights.append(bb[3] - bb[1])
    total_h = sum(heights) + gap * (len(lines) - 1)
    y = (y0 + y1 - total_h) / 2
    for i, line in enumerate(lines):
        tw = widths[i]
        draw.text(((x0 + x1 - tw) / 2, y), line, font=fnt, fill=fill)
        y += heights[i] + gap


def arrow(draw, x1, y1, x2, y2, color=LINE, width=3):
    draw.line((x1, y1, x2, y2), fill=color, width=width)
    # simple arrow head toward (x2,y2)
    if abs(y2 - y1) >= abs(x2 - x1):
        # vertical
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


def caption_bar(img, title: str, subtitle: str = ""):
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, img.width, 52), fill=TEAL)
    draw.text((24, 10), title, font=font(20, True), fill=WHITE)
    if subtitle:
        draw.text((24, 32), subtitle, font=font(12), fill=TEAL_MD)


def save(img: Image.Image, name: str):
    path = OUT / name
    img.save(path, "PNG", optimize=True)
    print("OK", path, path.stat().st_size)


# ---------------------------------------------------------------------------
# Figure 1 — System context
# ---------------------------------------------------------------------------
def fig_system_context():
    w, h = 1200, 720
    img = Image.new("RGB", (w, h), WHITE)
    caption_bar(img, "Figure 1 — System context", "Patient · Meta · FastAPI · OpenAI · PostgreSQL · Admin")
    d = ImageDraw.Draw(img)
    f_title = font(14, True)
    f_sub = font(12)

    boxes = [
        (40, 120, 220, 230, TEAL_LT, ["Patient", "WhatsApp"], TEAL),
        (300, 120, 520, 230, (224, 242, 254), ["Meta", "WhatsApp Cloud API"], ACCENT),
        (600, 90, 900, 280, TEAL_LT, ["FastAPI Backend :8000", "Engine + Services"], TEAL),
        (980, 120, 1160, 230, (254, 243, 199), ["OpenAI", "Whisper + GPT"], ORANGE),
        (600, 360, 900, 470, (243, 232, 255), ["PostgreSQL", "clinic + chat data"], PURPLE),
        (300, 520, 520, 630, TEAL_LT, ["Admin", "Streamlit :8501"], TEAL),
    ]
    for x0, y0, x1, y1, fill, lines, outline in boxes:
        rounded(d, (x0, y0, x1, y1), fill, outline=outline, width=3)
        multiline_center(d, (x0, y0, x1, y1), lines, f_title if len(lines) == 2 else f_sub)

    # arrows
    arrow(d, 220, 175, 300, 175, TEAL, 3)
    arrow(d, 520, 175, 600, 175, TEAL, 3)
    arrow(d, 900, 175, 980, 175, ORANGE, 3)
    arrow(d, 750, 280, 750, 360, PURPLE, 3)
    arrow(d, 410, 520, 410, 230, TEAL, 3)
    # admin to db
    d.line((520, 575, 750, 575), fill=PURPLE, width=3)
    arrow(d, 750, 575, 750, 470, PURPLE, 3)

    d.text((40, 660), "Bidirectional WhatsApp traffic via Meta; Admin reads/writes the same DB as the bot.", font=font(13), fill=MUTED)
    save(img, "fig01-system-context.png")


# ---------------------------------------------------------------------------
# Figure 2 — Layered architecture
# ---------------------------------------------------------------------------
def fig_layers():
    w, h = 1100, 780
    img = Image.new("RGB", (w, h), WHITE)
    caption_bar(img, "Figure 2 — Layered code architecture", "Dependency flows downward only")
    d = ImageDraw.Draw(img)
    layers = [
        ("① Entry", "app/main.py — FastAPI bootstrap", TEAL),
        ("② Transport", "api/routes — webhook.py · booking.py", ACCENT),
        ("③ Orchestration", "graph/conversation_engine.py (LangGraph)", PURPLE),
        ("④ Domain services", "booking · slots · doctors · voice · WhatsApp · reminders", ORANGE),
        ("⑤ Language", "language/* — detect · prompts · validation", GREEN),
        ("⑥ Persistence", "models · db · PostgreSQL · Alembic", TEAL_DK),
        ("⑦ Cross-cutting", "core/config · i18n · safety · time_format", MUTED),
    ]
    y = 80
    for title, desc, color in layers:
        rounded(d, (80, y, 1020, y + 78), BOX_BG, outline=color, width=3, radius=14)
        d.rectangle((80, y, 96, y + 78), fill=color)
        d.text((120, y + 14), title, font=font(18, True), fill=color)
        d.text((120, y + 42), desc, font=font(14), fill=INK)
        if y < 80 + 78 * 6:
            arrow(d, 550, y + 78, 550, y + 90, LINE, 3)
        y += 90
    save(img, "fig02-layered-architecture.png")


# ---------------------------------------------------------------------------
# Figure 3 — Webhook routing
# ---------------------------------------------------------------------------
def fig_webhook():
    w, h = 1100, 700
    img = Image.new("RGB", (w, h), WHITE)
    caption_bar(img, "Figure 3 — Webhook message routing", "POST /webhook classification")
    d = ImageDraw.Draw(img)
    rounded(d, (400, 80, 700, 150), TEAL_LT, TEAL, 3)
    center_text(d, (400, 80, 700, 150), "POST /webhook", font(18, True), TEAL_DK)

    arrow(d, 550, 150, 550, 190, LINE, 3)
    rounded(d, (380, 190, 720, 260), (254, 243, 199), ORANGE, 3)
    center_text(d, (380, 190, 720, 260), "Extract phone · text · type", font(16, True))

    # diamond-ish decision via rounded box
    arrow(d, 550, 260, 550, 300, LINE, 3)
    rounded(d, (420, 300, 680, 360), WHITE, TEAL, 3)
    center_text(d, (420, 300, 680, 360), "message type?", font(16, True), TEAL)

    branches = [
        (60, 440, 280, 520, "audio", "_handle_voice", ORANGE),
        (300, 440, 520, 520, "text / interactive", "_handle_message", TEAL),
        (540, 440, 760, 520, "flow reply", "_handle_flow_completion", PURPLE),
        (780, 440, 1040, 520, "statuses", "_handle_status_updates", ACCENT),
    ]
    # fan out lines
    d.line((550, 360, 550, 400), fill=LINE, width=3)
    d.line((170, 400, 910, 400), fill=LINE, width=3)
    for x0, y0, x1, y1, label, fn, color in branches:
        cx = (x0 + x1) // 2
        d.line((cx, 400, cx, 440), fill=LINE, width=3)
        rounded(d, (x0, y0, x1, y1), TEAL_LT if color == TEAL else BOX_BG, color, 3)
        multiline_center(d, (x0, y0, x1, y1), [label, fn], font(13, True), INK)

    # bottom converge
    for x0, y0, x1, y1, *_ in branches[:3]:
        cx = (x0 + x1) // 2
        d.line((cx, 520, cx, 560), fill=LINE, width=2)
    d.line((170, 560, 650, 560), fill=LINE, width=2)
    arrow(d, 550, 560, 550, 590, LINE, 3)
    rounded(d, (320, 590, 780, 670), TEAL, TEAL_DK, 3)
    center_text(d, (320, 590, 780, 670), "Engine / voice executor → whatsapp_client reply", font(15, True), WHITE)
    save(img, "fig03-webhook-routing.png")


# ---------------------------------------------------------------------------
# Figure 4 — Booking flow
# ---------------------------------------------------------------------------
def fig_booking():
    w, h = 1000, 900
    img = Image.new("RGB", (w, h), WHITE)
    caption_bar(img, "Figure 4 — Booking flow", "Specialty or doctor path → hold → confirm")
    d = ImageDraw.Draw(img)
    steps = [
        (TEAL, "Main menu → Book"),
        (ACCENT, "Path: specialty  OR  doctor name"),
        (PURPLE, "Select doctor (cards / Flow / list)"),
        (ORANGE, "Select date"),
        (ORANGE, "Select time → hold_slot()"),
        (GREEN, "Patient details (name / optional DOB)"),
        (TEAL, "Summary → confirm_booking()"),
        (TEAL_DK, "Confirmed + reference + reminders"),
    ]
    y = 80
    for i, (color, text) in enumerate(steps):
        rounded(d, (180, y, 820, y + 70), BOX_BG, color, 3)
        d.ellipse((210, y + 18, 250, y + 58), fill=color)
        center_text(d, (210, y + 18, 250, y + 58), str(i + 1), font(16, True), WHITE)
        d.text((280, y + 22), text, font=font(16, True), fill=INK)
        if i < len(steps) - 1:
            arrow(d, 500, y + 70, 500, y + 88, LINE, 3)
        y += 95
    save(img, "fig04-booking-flow.png")


# ---------------------------------------------------------------------------
# Figure 5 — Voice pipeline
# ---------------------------------------------------------------------------
def fig_voice():
    w, h = 1200, 620
    img = Image.new("RGB", (w, h), WHITE)
    caption_bar(img, "Figure 5 — Voice pipeline", "Whisper STT → GPT plan → executor validates")
    d = ImageDraw.Draw(img)
    nodes = [
        (40, 140, 220, 260, "1. Voice note", "WhatsApp audio", TEAL),
        (260, 140, 440, 260, "2. Download", "Meta media OGG", ACCENT),
        (480, 140, 660, 260, "3. Whisper STT", "OPENAI_STT_MODEL", ORANGE),
        (700, 140, 900, 260, "4. GPT planner", "PLANNER_SYSTEM", PURPLE),
        (940, 140, 1160, 260, "5. Executor", "validate + act", GREEN),
    ]
    for i, (x0, y0, x1, y1, t, s, c) in enumerate(nodes):
        rounded(d, (x0, y0, x1, y1), BOX_BG, c, 3)
        multiline_center(d, (x0, y0, x1, y1), [t, s], font(14, True))
        if i < len(nodes) - 1:
            arrow(d, x1, (y0 + y1) // 2, nodes[i + 1][0], (y0 + y1) // 2, LINE, 3)

    # decision / fallback
    rounded(d, (700, 320, 900, 400), (254, 243, 199), ORANGE, 3)
    center_text(d, (700, 320, 900, 400), "VOICE_ROUTER_V2?", font(14, True))
    arrow(d, 800, 260, 800, 320, LINE, 3)

    rounded(d, (480, 460, 700, 560), TEAL_LT, TEAL, 3)
    multiline_center(d, (480, 460, 700, 560), ["V2 path", "VoicePlan → execute_plan"], font(13, True))
    rounded(d, (900, 460, 1120, 560), BOX_BG, MUTED, 3)
    multiline_center(d, (900, 460, 1120, 560), ["V1 fallback", "voice_fastpath → engine"], font(13, True))

    d.line((800, 400, 800, 430), fill=LINE, width=3)
    d.line((590, 430, 1010, 430), fill=LINE, width=3)
    d.line((590, 430, 590, 460), fill=LINE, width=3)
    d.line((1010, 430, 1010, 460), fill=LINE, width=3)

    d.text((40, 580), "LLM proposes furthest justified step; Python checks real availability and may fall back one step.", font=font(13), fill=MUTED)
    save(img, "fig05-voice-pipeline.png")


# ---------------------------------------------------------------------------
# Figure 6 — Hold / confirm
# ---------------------------------------------------------------------------
def fig_hold_confirm():
    w, h = 1100, 720
    img = Image.new("RGB", (w, h), WHITE)
    caption_bar(img, "Figure 6 — Slot hold & confirm", "Double-booking protection")
    d = ImageDraw.Draw(img)
    boxes = [
        (80, 100, 420, 200, "Pick time from list", "payload slot_*", TEAL),
        (80, 240, 420, 340, "hold_slot()", "SELECT FOR UPDATE → held", ORANGE),
        (80, 380, 420, 480, "Patient details", "name (+ DOB if required)", ACCENT),
        (80, 520, 420, 620, "confirm_booking()", "booked + Appointment", GREEN),
    ]
    for i, (x0, y0, x1, y1, t, s, c) in enumerate(boxes):
        rounded(d, (x0, y0, x1, y1), BOX_BG, c, 3)
        multiline_center(d, (x0, y0, x1, y1), [t, s], font(15, True))
        if i < len(boxes) - 1:
            arrow(d, 250, y1, 250, boxes[i + 1][1], LINE, 3)

    # side panel statuses
    rounded(d, (520, 120, 1020, 620), TEAL_LT, TEAL, 3)
    d.text((560, 150), "Slot status machine", font=font(18, True), fill=TEAL_DK)
    statuses = [
        ("available", "Bookable", GREEN),
        ("held", "Locked ~ SLOT_HOLD_MINUTES", ORANGE),
        ("booked", "Confirmed appointment", TEAL),
        ("blocked", "Leave / holiday", RED),
        ("expired", "Not bookable", MUTED),
    ]
    y = 210
    for name, desc, c in statuses:
        d.ellipse((560, y + 8, 580, y + 28), fill=c)
        d.text((600, y), f"{name}", font=font(16, True), fill=INK)
        d.text((600, y + 28), desc, font=font(13), fill=MUTED)
        y += 70
    d.text((560, 560), "Also: unique active appointment per slot", font=font(13), fill=MUTED)
    save(img, "fig06-hold-confirm.png")


# ---------------------------------------------------------------------------
# Figure 7 — Data model ER (simplified boxes)
# ---------------------------------------------------------------------------
def fig_er():
    w, h = 1200, 780
    img = Image.new("RGB", (w, h), WHITE)
    caption_bar(img, "Figure 7 — Core data model", "Tenant → Clinic → Doctors / Patients / Conversations")
    d = ImageDraw.Draw(img)

    def entity(x, y, title, fields, color=TEAL):
        bw, bh = 200, 110
        rounded(d, (x, y, x + bw, y + bh), WHITE, color, 2, 10)
        d.rectangle((x, y, x + bw, y + 28), fill=color)
        center_text(d, (x, y, x + bw, y + 28), title, font(13, True), WHITE)
        d.text((x + 10, y + 40), fields, font=font(11), fill=MUTED)
        return x + bw // 2, y + bh, x, y, x + bw, y + bh

    c1 = entity(500, 80, "TENANT", "id · name", TEAL_DK)
    c2 = entity(500, 230, "CLINIC", "tenant_id · name", TEAL)
    c3 = entity(80, 400, "DEPARTMENT", "clinic_id · name", ACCENT)
    c4 = entity(320, 400, "DOCTOR", "dept · hours · leave", PURPLE)
    c5 = entity(560, 400, "PATIENT", "whatsapp_phone", GREEN)
    c6 = entity(800, 400, "CONVERSATION", "state · language", ORANGE)
    c7 = entity(320, 580, "SLOT", "status · start", PURPLE)
    c8 = entity(560, 580, "APPOINTMENT", "ref · status", TEAL)
    c9 = entity(800, 580, "MESSAGE", "+ voice_message", ORANGE)

    def link(a, b):
        arrow(d, a[0], a[1], b[0], b[1] - 110 if b[1] > a[1] else b[1], LINE, 2)

    # vertical tenant-clinic
    arrow(d, 600, 190, 600, 230, LINE, 2)
    # clinic fanout
    d.line((600, 340, 600, 370), fill=LINE, width=2)
    d.line((180, 370, 900, 370), fill=LINE, width=2)
    for cx in (180, 420, 660, 900):
        d.line((cx, 370, cx, 400), fill=LINE, width=2)
    arrow(d, 420, 510, 420, 580, LINE, 2)
    arrow(d, 660, 510, 660, 580, LINE, 2)
    arrow(d, 900, 510, 900, 580, LINE, 2)
    d.line((420, 635, 660, 635), fill=LINE, width=2)  # slot-appt visual link hint
    save(img, "fig07-data-model.png")


# ---------------------------------------------------------------------------
# Figure 8 — Deploy pipeline
# ---------------------------------------------------------------------------
def fig_deploy():
    w, h = 1200, 520
    img = Image.new("RGB", (w, h), WHITE)
    caption_bar(img, "Figure 8 — Deploy pipeline", "main → GitHub Actions → Windows SSH")
    d = ImageDraw.Draw(img)
    nodes = [
        (40, 160, 200, 300, "Developer", "PR / push", TEAL),
        (240, 160, 400, 300, "main", "GitHub", ACCENT),
        (440, 160, 640, 300, "Actions", "ssh-action", PURPLE),
        (680, 160, 880, 300, "Windows", "C:\\apps\\...", ORANGE),
        (920, 120, 1160, 200, "pip + alembic", "", GREEN),
        (920, 240, 1160, 320, "Restart service", "HospitalChatbotBackend", TEAL_DK),
        (920, 360, 1160, 440, "Streamlit", "manual restart", MUTED),
    ]
    for x0, y0, x1, y1, t, s, c in nodes[:4]:
        rounded(d, (x0, y0, x1, y1), BOX_BG, c, 3)
        multiline_center(d, (x0, y0, x1, y1), [t, s] if s else [t], font(14, True))
    for i in range(3):
        arrow(d, nodes[i][2], 230, nodes[i + 1][0], 230, LINE, 3)
    arrow(d, 880, 230, 920, 230, LINE, 3)
    for x0, y0, x1, y1, t, s, c in nodes[4:]:
        rounded(d, (x0, y0, x1, y1), BOX_BG, c, 3)
        multiline_center(d, (x0, y0, x1, y1), [t, s] if s else [t], font(13, True))
    d.text((40, 470), "Secrets: WINDOWS_SSH_KEY (required). Optional host/user/port. See DEPLOYMENT.md.", font=font(13), fill=MUTED)
    save(img, "fig08-deploy-pipeline.png")


# ---------------------------------------------------------------------------
# Figure 9 — Conversation states
# ---------------------------------------------------------------------------
def fig_states():
    w, h = 1200, 700
    img = Image.new("RGB", (w, h), WHITE)
    caption_bar(img, "Figure 9 — Conversation states", "Persisted on Conversation.state")
    d = ImageDraw.Draw(img)

    def node(x, y, label, color=TEAL):
        rounded(d, (x, y, x + 170, y + 56), BOX_BG, color, 2, 10)
        center_text(d, (x, y, x + 170, y + 56), label, font(12, True))
        return x + 85, y + 56

    # row 1
    n_new = node(40, 100, "new", MUTED)
    n_lang = node(250, 100, "language_select", ACCENT)
    n_menu = node(460, 100, "main_menu", TEAL)
    arrow(d, 210, 128, 250, 128, LINE, 2)
    arrow(d, 420, 128, 460, 128, LINE, 2)

    # booking chain
    n_doc = node(40, 240, "booking_doctor", PURPLE)
    n_date = node(250, 240, "booking_date", PURPLE)
    n_slot = node(460, 240, "booking_slot", PURPLE)
    n_pat = node(670, 240, "patient_details", ORANGE)
    n_conf = node(880, 240, "confirming", ORANGE)
    n_closed = node(990, 360, "closed", TEAL_DK)
    for a, b in [(n_doc, (250, 240)), (n_date, (460, 240)), (n_slot, (670, 240)), (n_pat, (880, 240))]:
        arrow(d, a[0] + 85 if False else a[0], 268, b[0], 268, LINE, 2)
    # fix horizontal arrows properly
    d.line((210, 268, 250, 268), fill=LINE, width=2)
    d.line((420, 268, 460, 268), fill=LINE, width=2)
    d.line((630, 268, 670, 268), fill=LINE, width=2)
    d.line((840, 268, 880, 268), fill=LINE, width=2)
    arrow(d, 1050, 296, 1075, 360, LINE, 2)

    # from menu down
    arrow(d, 545, 156, 545, 220, LINE, 2)
    d.line((125, 220, 545, 220), fill=LINE, width=2)
    d.line((125, 220, 125, 240), fill=LINE, width=2)

    # side flows
    n_res = node(40, 420, "reschedule", ACCENT)
    n_can = node(250, 420, "cancel", RED)
    n_han = node(460, 420, "handover", ORANGE)
    arrow(d, 545, 156, 545, 390, LINE, 2)
    d.line((125, 390, 545, 390), fill=LINE, width=2)
    d.line((125, 390, 125, 420), fill=LINE, width=2)
    d.line((335, 390, 335, 420), fill=LINE, width=2)
    d.line((545, 390, 545, 420), fill=LINE, width=2)

    d.text((40, 520), "Global MENU clears draft → main_menu. Back moves one step (time→date→doctor→path).", font=font(13), fill=MUTED)
    d.text((40, 550), "In-memory _SESSION[phone] holds draft doctor/date/slot/awaiting (lost on process restart).", font=font(13), fill=MUTED)
    d.text((40, 600), "Also: language_select may be skipped when language already known.", font=font(13), fill=MUTED)
    save(img, "fig09-conversation-states.png")


# ---------------------------------------------------------------------------
# Figure 10 — Reminder + handover
# ---------------------------------------------------------------------------
def fig_reminders_handover():
    w, h = 1200, 560
    img = Image.new("RGB", (w, h), WHITE)
    caption_bar(img, "Figure 10 — Reminders & handover", "Parallel operational flows")
    d = ImageDraw.Draw(img)

    # left reminders
    rounded(d, (40, 90, 560, 500), TEAL_LT, TEAL, 3)
    d.text((70, 110), "Reminders", font=font(18, True), fill=TEAL_DK)
    steps = [
        "confirm_booking / reschedule",
        "create_booking_reminders (24h, 2h)",
        "reminders PENDING in DB",
        "run_reminders CLI / dashboard",
        "WhatsApp send + status updates",
    ]
    y = 160
    for i, t in enumerate(steps):
        rounded(d, (70, y, 530, y + 48), WHITE, TEAL, 2)
        d.text((90, y + 12), f"{i+1}. {t}", font=font(13, True), fill=INK)
        if i < len(steps) - 1:
            arrow(d, 300, y + 48, 300, y + 58, LINE, 2)
        y += 62

    # right handover
    rounded(d, (640, 90, 1160, 500), (255, 247, 237), ORANGE, 3)
    d.text((670, 110), "Handover", font=font(18, True), fill=ORANGE)
    triggers = [
        "Patient asks for reception",
        "Safety risk wording (safety.py)",
        "Cancel/reschedule past cutoff",
        "Unexpected webhook failure",
    ]
    y = 160
    for t in triggers:
        rounded(d, (670, y, 1130, y + 44), WHITE, ORANGE, 2)
        d.text((690, y + 10), "• " + t, font=font(13, True), fill=INK)
        y += 55
    rounded(d, (670, 400, 1130, 470), ORANGE, ORANGE, 2)
    center_text(d, (670, 400, 1130, 470), "HandoverCase → optional RECEPTIONIST_WHATSAPP", font(13, True), WHITE)
    save(img, "fig10-reminders-handover.png")


# ---------------------------------------------------------------------------
# Figure 11 — Config architecture
# ---------------------------------------------------------------------------
def fig_config():
    w, h = 1100, 520
    img = Image.new("RGB", (w, h), WHITE)
    caption_bar(img, "Figure 11 — Configuration architecture", ".env + DB settings")
    d = ImageDraw.Draw(img)
    rounded(d, (60, 120, 280, 240), BOX_BG, TEAL, 3)
    multiline_center(d, (60, 120, 280, 240), [".env file", "repo + cwd"], font(15, True))
    arrow(d, 280, 180, 340, 180, LINE, 3)
    rounded(d, (340, 120, 620, 240), TEAL_LT, TEAL, 3)
    multiline_center(d, (340, 120, 620, 240), ["app/core/config.py", "_load_dotenv_files()"], font(14, True))
    arrow(d, 620, 180, 700, 180, LINE, 3)
    rounded(d, (700, 100, 1040, 260), BOX_BG, PURPLE, 3)
    multiline_center(d, (700, 100, 1040, 260), ["Runtime constants", "WhatsApp · AI · Booking · Clinic"], font(14, True))

    rounded(d, (60, 320, 420, 460), BOX_BG, ACCENT, 3)
    multiline_center(d, (60, 320, 420, 460), ["config_settings table", "per-clinic overrides"], font(14, True))
    arrow(d, 420, 390, 520, 390, LINE, 3)
    rounded(d, (520, 320, 860, 460), BOX_BG, GREEN, 3)
    multiline_center(d, (520, 320, 860, 460), ["clinic_settings_service", "maps / location / knobs"], font(14, True))
    arrow(d, 860, 390, 920, 390, LINE, 3)
    arrow(d, 870, 260, 870, 320, LINE, 3)
    rounded(d, (920, 320, 1040, 460), TEAL, TEAL_DK, 3)
    multiline_center(d, (920, 320, 1040, 460), ["API", "+", "Services"], font(13, True), WHITE)
    save(img, "fig11-config-architecture.png")


# ---------------------------------------------------------------------------
# Figure 12 — Admin dashboard
# ---------------------------------------------------------------------------
def fig_dashboard():
    w, h = 1100, 640
    img = Image.new("RGB", (w, h), WHITE)
    caption_bar(img, "Figure 12 — Admin dashboard", "Streamlit screens → same PostgreSQL")
    d = ImageDraw.Draw(img)
    rounded(d, (400, 80, 700, 150), TEAL, TEAL_DK, 3)
    center_text(d, (400, 80, 700, 150), "Login (ADMIN_DASHBOARD_PASSWORD)", font(14, True), WHITE)

    screens = [
        "KPIs", "Clinic", "Departments", "Doctors",
        "Hours", "Schedule", "Appointments", "Conversations",
        "Reminders", "Settings", "Usage",
    ]
    positions = []
    for i, name in enumerate(screens):
        col, row = i % 4, i // 4
        x0 = 80 + col * 250
        y0 = 200 + row * 100
        x1, y1 = x0 + 220, y0 + 70
        rounded(d, (x0, y0, x1, y1), BOX_BG, TEAL, 2)
        center_text(d, (x0, y0, x1, y1), name, font(14, True))
        positions.append(((x0 + x1) // 2, y0))

    # lines from login to first row
    for cx, y0 in positions[:4]:
        d.line((550, 150, cx, 180), fill=LINE, width=1)
        d.line((cx, 180, cx, y0), fill=LINE, width=1)

    rounded(d, (300, 540, 800, 610), PURPLE, PURPLE, 3)
    center_text(d, (300, 540, 800, 610), "admin_dashboard_service → PostgreSQL", font(15, True), WHITE)
    save(img, "fig12-admin-dashboard.png")


def main():
    fig_system_context()
    fig_layers()
    fig_webhook()
    fig_booking()
    fig_voice()
    fig_hold_confirm()
    fig_er()
    fig_deploy()
    fig_states()
    fig_reminders_handover()
    fig_config()
    fig_dashboard()
    print(f"Wrote {len(list(OUT.glob('fig*.png')))} figures to {OUT}")


if __name__ == "__main__":
    main()
