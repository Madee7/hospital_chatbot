"""One short brief PDF for the PPT teammate — what to put on 4 voice slides."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

docs = Path(__file__).resolve().parent
out_dir = docs / "pdf"
html_dir = docs / "_pdf_tmp"
out_dir.mkdir(exist_ok=True)
html_dir.mkdir(exist_ok=True)
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
@page { size: A4; margin: 14mm; }
body { font-family: Tahoma, "Segoe UI", Arial, sans-serif; font-size: 11pt; color: #111; line-height: 1.4; }
h1 { color: #0f766e; font-size: 18pt; border-bottom: 2px solid #0f766e; padding-bottom: 4px; }
h2 { color: #134e4a; font-size: 13pt; margin: 14px 0 6px; }
.box { background: #f8fafc; border-left: 5px solid #0f766e; padding: 8px 10px; margin: 8px 0; }
.kw { display: inline-block; background: #ccfbf1; border: 1px solid #99f6e4; color: #134e4a;
      padding: 2px 8px; border-radius: 999px; font-weight: 700; font-size: 10pt; margin: 2px; }
.note { background: #fff7ed; border-left: 4px solid #ea580c; padding: 8px 10px; margin: 10px 0; }
ul { margin: 4px 0 4px 18px; }
li { margin: 3px 0; }
</style></head><body>

<h1>Split Voice — What to put in PowerPoint</h1>
<p><b>For:</b> PPT designer<br>
<b>From:</b> Voice system owner<br>
<b>Please add 4 slides</b> in the Hospital Chatbot presentation (same style as the rest of the deck).</p>

<div class="note">
Keep text short. Use <b>keywords + simple diagrams</b>. I will explain the details when presenting.
</div>

<h2>Slide 1 — Title / Keywords</h2>
<div class="box">
  <b>Title:</b> Split Voice System<br><br>
  <b>Put these 4 keyword cards:</b><br>
  <span class="kw">Voice Note</span>
  <span class="kw">STT (Whisper)</span>
  <span class="kw">AI Plan</span>
  <span class="kw">DB Check</span><br><br>
  <b>Small pills under:</b>
  <span class="kw">No TTS</span>
  <span class="kw">Same funnel</span>
  <span class="kw">AR + EN</span>
</div>

<h2>Slide 2 — Why Voice?</h2>
<div class="box">
  <b>Title:</b> Why Voice?<br><br>
  <b>Left side — PROBLEM keywords:</b>
  <ul>
    <li>Typing friction</li>
    <li>Dialect hard to type</li>
    <li>Chat drop-off</li>
    <li>Slow booking</li>
  </ul>
  <b>Right side — SOLUTION keywords:</b>
  <ul>
    <li>Speak naturally</li>
    <li>Same booking flow</li>
    <li>Faster engage</li>
    <li>No separate app</li>
  </ul>
</div>

<h2>Slide 3 — Architecture (diagram)</h2>
<div class="box">
  <b>Title:</b> Architecture<br><br>
  <b>One flowchart (big):</b><br>
  <b>Whisper → Planner → Executor → Reply</b><br><br>
  <b>Under each box (small keywords):</b>
  <ul>
    <li>Whisper = STT</li>
    <li>Planner = VoicePlan / AI</li>
    <li>Executor = DB Validate</li>
    <li>Reply = WhatsApp buttons</li>
  </ul>
  <b>Bottom line:</b> AI suggests · System confirms · DB = source of truth
</div>

<h2>Slide 4 — Key Points</h2>
<div class="box">
  <b>Title:</b> Key Points<br><br>
  <b>4 keyword cards:</b>
  <ul>
    <li><b>Input only</b> — not a new bot</li>
    <li><b>AI plans</b> — next booking step</li>
    <li><b>System proves</b> — live hospital DB</li>
    <li><b>Buttons out</b> — no robot voice</li>
  </ul>
  <b>Pills:</b>
  <span class="kw">Safe</span>
  <span class="kw">Arabic + English</span>
  <span class="kw">One product</span>
</div>

<h2>Please do / don't</h2>
<ul>
  <li><b>Do:</b> match the existing Hospital Chatbot slide style</li>
  <li><b>Do:</b> keep keywords big and clear</li>
  <li><b>Do:</b> make the architecture flowchart large on slide 3</li>
  <li><b>Don't:</b> write long definitions or paragraphs</li>
  <li><b>Don't:</b> add code, file names, or API details</li>
</ul>

<p style="color:#64748b;font-size:10pt;margin-top:16px">
One-line summary for you: Patient sends WhatsApp voice note → Whisper text → AI plans → system checks hospital DB → WhatsApp buttons reply.
</p>

</body></html>"""


def main() -> None:
    html_path = html_dir / "VOICE_TEAMMATE_BRIEF.html"
    pdf_path = out_dir / "VOICE_TEAMMATE_BRIEF.pdf"
    html_path.write_text(HTML, encoding="utf-8")
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
    print("OK", pdf_path, pdf_path.stat().st_size if pdf_path.exists() else 0)


if __name__ == "__main__":
    main()
