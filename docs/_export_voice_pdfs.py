"""Build 2 short PDFs for the Split Voice System presentation.

1. VOICE_PPT_BRIEF.pdf   — tells the PPT maker what to put + diagrams to use
2. VOICE_EXPLAIN.pdf     — simple full explanation for the presenter
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

docs = Path(__file__).resolve().parent
img = docs / "images" / "voice"
out_dir = docs / "pdf"
html_dir = docs / "_pdf_tmp"
out_dir.mkdir(exist_ok=True)
html_dir.mkdir(exist_ok=True)

CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def uri(name: str) -> str:
    return (img / name).resolve().as_uri()


CSS = """
@page { size: A4; margin: 12mm; }
body {
  font-family: Tahoma, "Segoe UI", Arial, sans-serif;
  font-size: 10.5pt;
  color: #111827;
  line-height: 1.4;
}
h1 {
  color: #0f766e;
  font-size: 17pt;
  border-bottom: 2px solid #0f766e;
  padding-bottom: 5px;
  margin-top: 0;
}
h2 {
  color: #134e4a;
  font-size: 12.5pt;
  margin: 12px 0 5px;
  border-bottom: 1px solid #99f6e4;
  padding-bottom: 2px;
  page-break-after: avoid;
}
h3 { color: #0f766e; font-size: 11pt; margin: 8px 0 4px; }
.slide {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-left: 5px solid #0f766e;
  padding: 7px 9px;
  margin: 6px 0;
  page-break-inside: avoid;
}
.slide .n {
  display: inline-block;
  background: #0f766e;
  color: white;
  font-weight: 700;
  font-size: 9pt;
  padding: 1px 7px;
  border-radius: 999px;
  margin-right: 6px;
}
.kw {
  display: inline-block;
  background: #ccfbf1;
  color: #134e4a;
  border: 1px solid #99f6e4;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 9pt;
  font-weight: 700;
  margin: 2px;
}
table {
  border-collapse: collapse;
  width: 100%;
  margin: 6px 0;
  font-size: 9.5pt;
}
th { background: #0f766e; color: white; text-align: left; padding: 4px 6px; }
td { border: 1px solid #d1d5db; padding: 4px 6px; vertical-align: top; }
tr:nth-child(even) td { background: #f8fafc; }
ul { margin: 3px 0 3px 16px; }
li { margin: 1px 0; }
.note {
  background: #fff7ed;
  border-left: 4px solid #ea580c;
  padding: 6px 9px;
  margin: 6px 0;
}
.ok {
  background: #ecfdf5;
  border-left: 4px solid #0f766e;
  padding: 6px 9px;
  margin: 6px 0;
}
.diagram {
  page-break-inside: avoid;
  margin: 6px 0 10px 0;
  text-align: center;
}
.diagram img {
  max-width: 100%;
  max-height: 95mm;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
}
.diagram .cap {
  font-size: 9pt;
  color: #475569;
  margin-top: 3px;
  text-align: left;
}
.diagram.big img { max-height: 110mm; }
pre {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  padding: 7px 9px;
  font-size: 9pt;
  white-space: pre-wrap;
  font-family: Consolas, monospace;
}
.small { color: #64748b; font-size: 9pt; }
.file {
  background: #f1f5f9;
  padding: 1px 5px;
  border-radius: 3px;
  font-family: Consolas, monospace;
  font-size: 9pt;
}
"""


def chrome_pdf(html_path: Path, pdf_path: Path) -> None:
    if pdf_path.exists():
        try:
            pdf_path.unlink()
        except OSError:
            pass
    subprocess.run(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.resolve().as_uri(),
        ],
        check=False,
    )
    for _ in range(40):
        if pdf_path.exists() and pdf_path.stat().st_size > 500:
            break
        time.sleep(0.25)
    print("OK", pdf_path.name, pdf_path.stat().st_size if pdf_path.exists() else 0)


def brief_html() -> str:
    u = uri
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<h1>Split Voice System — PowerPoint Brief</h1>
<p><b>For:</b> the person making the PowerPoint<br>
<b>Goal:</b> make the voice section look special with clear diagrams<br>
<b>Slides:</b> 6 only · short text · big visuals</p>

<div class="ok">
<b>One sentence for the whole section:</b><br>
Patient sends a WhatsApp voice note → AI understands → system checks hospital data → bot continues booking with normal WhatsApp buttons.
</div>

<div class="note">
<b>How to use diagrams:</b> copy the image into the slide (recommended), or redraw the same shapes in PowerPoint.<br>
PNG files are in <span class="file">docs/images/voice/</span>
</div>

<h2>Slide 1 — Title</h2>
<div class="slide">
  <div><span class="n">1</span><b>Put on slide</b></div>
  <ul>
    <li><b>Title:</b> Split Voice System</li>
    <li><b>Subtitle:</b> Book by speaking on WhatsApp</li>
    <li><b>Keywords:</b>
      <span class="kw">Voice note</span>
      <span class="kw">AI plan</span>
      <span class="kw">Hospital DB check</span>
    </li>
  </ul>
  <p class="small">Optional small icon: microphone + WhatsApp. No big diagram yet.</p>
</div>

<h2>Slide 2 — Patient experience + GUI</h2>
<div class="slide">
  <div><span class="n">2</span><b>Put on slide</b></div>
  <ul>
    <li><b>Title:</b> Patient experience</li>
    <li>Patient sends a WhatsApp voice note</li>
    <li>Bot replies with normal text + buttons</li>
    <li>Same booking flow as typing · no robot voice reply</li>
  </ul>
  <p><b>Keywords:</b>
    <span class="kw">WhatsApp</span>
    <span class="kw">Voice in</span>
    <span class="kw">Buttons out</span>
  </p>
  <p><b>Diagram to use:</b> <span class="file">v03-whatsapp-gui.png</span></p>
</div>
<div class="diagram">
  <img src="{u('v03-whatsapp-gui.png')}" alt="WhatsApp GUI">
  <div class="cap">Copy this GUI journey onto Slide 2 — it makes the section look product-real, not only technical.</div>
</div>

<h2>Slide 3 — The split idea (hero diagram)</h2>
<div class="slide">
  <div><span class="n">3</span><b>Put on slide</b></div>
  <ul>
    <li><b>Title:</b> Planner + Executor</li>
    <li>Left: Planner (AI) understands speech and picks next step</li>
    <li>Right: Executor (System) checks real doctors/times in DB</li>
    <li>Bottom line: AI suggests · System confirms</li>
  </ul>
  <p><b>Keywords:</b>
    <span class="kw">Planner</span>
    <span class="kw">Executor</span>
    <span class="kw">Split</span>
  </p>
  <p><b>Diagram to use:</b> <span class="file">v01-split-idea.png</span> — make this the biggest visual in the section</p>
</div>
<div class="diagram big">
  <img src="{u('v01-split-idea.png')}" alt="Split idea">
  <div class="cap">Hero diagram for Slide 3. Keep bullets short — let this image carry the slide.</div>
</div>

<h2>Slide 4 — Main flowchart</h2>
<div class="slide">
  <div><span class="n">4</span><b>Put on slide</b></div>
  <ul>
    <li><b>Title:</b> How voice booking works</li>
    <li>Almost empty slide — big flowchart only</li>
  </ul>
  <p><b>Keywords under chart:</b>
    <span class="kw">Whisper</span>
    <span class="kw">VoicePlan</span>
    <span class="kw">Validate</span>
    <span class="kw">Book / Ask</span>
  </p>
  <p><b>Diagram to use:</b> <span class="file">v02-pipeline.png</span></p>
</div>
<div class="diagram big">
  <img src="{u('v02-pipeline.png')}" alt="Pipeline">
  <div class="cap">Main flowchart for Slide 4. If redrawing in PPT: 6 boxes — Voice note → STT → AI plan → Executor → Funnel → Reply.</div>
</div>

<h2>Slide 5 — Example + safety fallback</h2>
<div class="slide">
  <div><span class="n">5</span><b>Put on slide</b></div>
  <ul>
    <li><b>Title:</b> Example</li>
    <li>Patient: “I want Dr Ahmed on Friday at 2”</li>
    <li>AI plan: book → hold that slot</li>
    <li>System checks doctor / Friday / 2:00</li>
    <li>If free → confirm · If not → show other times</li>
  </ul>
  <p><b>Keywords:</b>
    <span class="kw">Example</span>
    <span class="kw">Hold slot</span>
    <span class="kw">Fallback</span>
  </p>
  <p><b>Main diagram:</b> <span class="file">v09-example.png</span><br>
  <b>Optional small second diagram:</b> <span class="file">v05-degrade.png</span> (fallback ladder)</p>
</div>
<div class="diagram">
  <img src="{u('v09-example.png')}" alt="Example">
  <div class="cap">Use on Slide 5 as the story diagram.</div>
</div>
<div class="diagram">
  <img src="{u('v05-degrade.png')}" alt="Degrade ladder">
  <div class="cap">Optional on Slide 5 (corner/side) or a bonus slide — shows safe fallback if the exact time is taken.</div>
</div>

<h2>Slide 6 — Why it matters</h2>
<div class="slide">
  <div><span class="n">6</span><b>Put on slide</b></div>
  <ul>
    <li><b>Title:</b> Benefits</li>
    <li>Faster booking by voice</li>
    <li>Works in Arabic + English</li>
    <li>AI does not invent appointments</li>
    <li>Hospital data is the source of truth</li>
    <li>Same product as text chat</li>
  </ul>
  <p><b>Keywords:</b>
    <span class="kw">Safe</span>
    <span class="kw">Arabic + English</span>
    <span class="kw">One product</span>
  </p>
  <p><b>Diagram to use:</b> <span class="file">v10-benefits.png</span>
  or side-by-side before/after <span class="file">v06-v1-v2.png</span></p>
</div>
<div class="diagram">
  <img src="{u('v10-benefits.png')}" alt="Benefits">
  <div class="cap">Closing visual for Slide 6.</div>
</div>

<h2>Diagram pack (quick map)</h2>
<table>
  <tr><th>Slide</th><th>PNG file</th><th>What it is</th></tr>
  <tr><td>2</td><td><span class="file">v03-whatsapp-gui.png</span></td><td>Patient WhatsApp GUI journey</td></tr>
  <tr><td>3</td><td><span class="file">v01-split-idea.png</span></td><td>Planner vs Executor (hero)</td></tr>
  <tr><td>4</td><td><span class="file">v02-pipeline.png</span></td><td>End-to-end flowchart</td></tr>
  <tr><td>5</td><td><span class="file">v09-example.png</span></td><td>Live example story</td></tr>
  <tr><td>5 optional</td><td><span class="file">v05-degrade.png</span></td><td>Fallback ladder</td></tr>
  <tr><td>6</td><td><span class="file">v10-benefits.png</span></td><td>Benefits / keywords wall</td></tr>
  <tr><td>6 alt</td><td><span class="file">v06-v1-v2.png</span></td><td>Before vs after</td></tr>
</table>

<h2>Do / Don't</h2>
<table>
  <tr><th>Do</th><th>Don't</th></tr>
  <tr><td>Make diagrams large (full-slide feel)</td><td>Tiny icons in a corner</td></tr>
  <tr><td>Keep 6 slides · short bullets</td><td>Long paragraphs or code</td></tr>
  <tr><td>Use teal/hospital colors</td><td>Look like a separate voice app</td></tr>
  <tr><td>One big visual per slide</td><td>Stack all diagrams on one slide</td></tr>
</table>

<p class="small">Presenter talk track: <b>VOICE_EXPLAIN.pdf</b> · PNG folder: <span class="file">docs/images/voice/</span></p>
</body></html>"""


def explain_html() -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<h1>Split Voice System — What to Explain</h1>
<p><b>For:</b> the presenter<br>
<b>Use with:</b> the 6 slides from <b>VOICE_PPT_BRIEF.pdf</b></p>

<div class="ok">
<b>Remember this line:</b><br>
Whisper hears the patient → AI plans the next booking step → Python checks the hospital database → WhatsApp replies with text/buttons.
</div>

<h2>Slide 1 — Open</h2>
<div class="note">
Say: “We added voice support. Patients can send a WhatsApp voice note instead of typing, and the bot continues the same booking flow.”
</div>

<h2>Slide 2 — Patient experience</h2>
<div class="note">
Say: “There is no special app. The patient uses WhatsApp voice notes. The bot does not speak back — it replies with normal text and buttons, exactly like typed chat.”
</div>
<ul>
  <li>Voice = another way to input</li>
  <li>Not a separate product</li>
  <li>No TTS / robot voice out</li>
</ul>

<h2>Slide 3 — Split idea (main point)</h2>
<div class="note">
Say: “We split the system into two parts. The AI planner understands what the patient said and how far we can jump in booking. The executor is normal code — it checks real doctors and real free times in the database. The AI never books alone.”
</div>
<table>
  <tr><th>Planner (AI)</th><th>Executor (System)</th></tr>
  <tr><td>Understands speech transcript</td><td>Checks hospital DB</td></tr>
  <tr><td>Extracts doctor / day / time</td><td>Holds slot or asks next question</td></tr>
  <tr><td>Chooses next booking step</td><td>Sends WhatsApp reply</td></tr>
  <tr><td>Can be aggressive</td><td>Must be careful / truthful</td></tr>
</table>

<h2>Slide 4 — Flowchart</h2>
<div class="note">
Say: “Voice note comes in. Whisper turns it into text. GPT makes a plan. Our system validates that plan against the database, then continues booking.”
</div>
<pre>1. WhatsApp voice note
2. Speech-to-text (Whisper)
3. AI creates a plan (goal + next step + slots)
4. System validates against hospital data
5. Reply on WhatsApp (text / buttons)</pre>

<h2>Slide 5 — Example</h2>
<div class="note">
Say: “Patient says: I want Dr Ahmed Friday at 2. AI plans to hold that slot. System checks: doctor exists, Friday is valid, is 2pm free? If yes, hold and ask confirm. If no, show other times and explain. We never invent an appointment.”
</div>
<p><b>Key word:</b> fallback — if the exact time fails, move one step back safely.</p>

<h2>Slide 6 — Close</h2>
<div class="note">
Say: “So voice makes booking easier, supports Arabic and English, and stays safe because hospital data is always the source of truth.”
</div>

<h2>If someone asks</h2>
<table>
  <tr><th>Question</th><th>Short answer</th></tr>
  <tr><td>Do you reply with voice?</td><td>No — WhatsApp text and buttons only.</td></tr>
  <tr><td>What converts speech?</td><td>Whisper speech-to-text.</td></tr>
  <tr><td>Who decides the next step?</td><td>AI suggests · system confirms with DB.</td></tr>
  <tr><td>Can AI invent a doctor/time?</td><td>No. Executor validates everything.</td></tr>
  <tr><td>Arabic support?</td><td>Yes — Egyptian Arabic and English.</td></tr>
  <tr><td>Is voice a separate bot?</td><td>No — same booking flow as typing.</td></tr>
</table>

<h2>30-second version</h2>
<div class="note">
“Patients can book by WhatsApp voice note. Speech becomes text, AI plans the booking step, and our system checks the real hospital schedule before replying with normal buttons. Safe, simple, same product as typed chat.”
</div>
</body></html>"""


def main() -> None:
    if not CHROME.exists():
        raise SystemExit(f"Chrome not found: {CHROME}")
    needed = [
        "v01-split-idea.png",
        "v02-pipeline.png",
        "v03-whatsapp-gui.png",
        "v05-degrade.png",
        "v09-example.png",
        "v10-benefits.png",
    ]
    missing = [n for n in needed if not (img / n).exists()]
    if missing:
        raise SystemExit(
            f"Missing diagrams: {missing}. Run: python docs/_render_voice_figures.py"
        )

    brief_path = html_dir / "VOICE_PPT_BRIEF.html"
    explain_path = html_dir / "VOICE_EXPLAIN.html"
    brief_path.write_text(brief_html(), encoding="utf-8")
    explain_path.write_text(explain_html(), encoding="utf-8")

    chrome_pdf(brief_path, out_dir / "VOICE_PPT_BRIEF.pdf")
    chrome_pdf(explain_path, out_dir / "VOICE_EXPLAIN.pdf")


if __name__ == "__main__":
    main()
