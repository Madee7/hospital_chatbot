"""Full voice-system awareness PDF for the presenter."""
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
    p = img / name
    return p.resolve().as_uri() if p.exists() else ""


CSS = """
@page { size: A4; margin: 13mm; }
body {
  font-family: Tahoma, "Segoe UI", Arial, sans-serif;
  font-size: 10.5pt;
  color: #111827;
  line-height: 1.42;
}
h1 {
  color: #0f766e;
  font-size: 17pt;
  border-bottom: 2px solid #0f766e;
  padding-bottom: 4px;
  page-break-before: always;
}
h1.first { page-break-before: avoid; }
h2 {
  color: #134e4a;
  font-size: 12.5pt;
  margin-top: 11px;
  border-bottom: 1px solid #99f6e4;
  padding-bottom: 2px;
}
h3 { color: #115e59; font-size: 11pt; margin: 8px 0 3px; }
.cover {
  page-break-after: always;
  text-align: center;
  padding-top: 45mm;
}
.cover h1 { border: none; font-size: 26pt; page-break-before: avoid; }
.cover p { color: #475569; font-size: 12pt; }
.ok {
  background: #ecfdf5;
  border-left: 4px solid #0f766e;
  padding: 7px 10px;
  margin: 8px 0;
  color: #134e4a;
}
.say {
  background: #fff7ed;
  border-left: 4px solid #ea580c;
  padding: 7px 10px;
  margin: 8px 0;
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
th { background: #0f766e; color: white; text-align: left; padding: 5px 6px; }
td { border: 1px solid #d1d5db; padding: 5px 6px; vertical-align: top; }
tr:nth-child(even) td { background: #f8fafc; }
pre {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-left: 4px solid #0f766e;
  padding: 7px 9px;
  font-size: 8.5pt;
  white-space: pre-wrap;
  font-family: Consolas, monospace;
}
code {
  background: #f3f4f6;
  padding: 1px 3px;
  border: 1px solid #e5e7eb;
  font-family: Consolas, monospace;
  font-size: 9pt;
}
ul, ol { margin: 3px 0 3px 16px; }
li { margin: 2px 0; }
img {
  max-width: 100%;
  max-height: 85mm;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  margin: 6px 0;
}
.cap { font-size: 9pt; color: #64748b; margin-bottom: 8px; }
.toc a { color: #0f766e; text-decoration: none; }
"""


def body() -> str:
    u01 = uri("v01-split-idea.png")
    u02 = uri("v02-pipeline.png")
    u05 = uri("v05-degrade.png")
    u09 = uri("v09-example.png")

    imgs = ""
    if u01:
        imgs += f'<img src="{u01}" alt="split"><div class="cap">Planner (AI) vs Executor (System)</div>'
    if u02:
        imgs += f'<img src="{u02}" alt="pipeline"><div class="cap">End-to-end voice pipeline</div>'

    return f"""
<div class="cover">
  <p style="color:#0f766e;font-weight:700;letter-spacing:.08em">HOSPITAL CHATBOT</p>
  <h1 class="first">Split Voice System</h1>
  <p style="font-size:15pt;margin-top:6px">Full Awareness Guide for Presenter</p>
  <p>Everything we built · how it works · what to say</p>
  <p style="margin-top:18px">Read this before your PowerPoint talk</p>
</div>

<h1 class="first">0. Quick map</h1>
<ol class="toc">
  <li>What we built (definition)</li>
  <li>Why we built it (problem)</li>
  <li>Architecture (Planner + Executor)</li>
  <li>Full pipeline (step by step)</li>
  <li>VoicePlan (AI output contract)</li>
  <li>Degradation / safety</li>
  <li>Languages</li>
  <li>V1 vs V2</li>
  <li>Code modules &amp; config</li>
  <li>Admin / cost / observability</li>
  <li>Example walkthrough</li>
  <li>What is NOT included</li>
  <li>Talk track + Q&amp;A</li>
</ol>

<div class="ok">
<b>Core one-liner (memorize):</b><br>
Whisper hears → GPT plans → Python proves against the hospital DB → WhatsApp replies with text/buttons.
</div>

<h1>1. What we built</h1>
<p>The <b>Split Voice System</b> lets patients send a <b>WhatsApp voice note</b> to the hospital chatbot.
The bot understands the speech and continues the <b>same booking / reschedule / cancel flow</b> used for typed messages.</p>

<p>Keywords:
<span class="kw">Split Voice</span>
<span class="kw">Router V2</span>
<span class="kw">Planner</span>
<span class="kw">Executor</span>
<span class="kw">VoicePlan</span>
<span class="kw">Whisper</span>
</p>

<ul>
  <li>Voice is an <b>alternate input</b>, not a separate product</li>
  <li>Replies are normal WhatsApp <b>text / buttons / lists</b></li>
  <li>There is <b>no outbound TTS</b> (bot does not speak back)</li>
  <li>Hospital database is always the <b>source of truth</b></li>
</ul>

<h1>2. Why we built it</h1>
<table>
  <tr><th>Problem</th><th>Solution</th></tr>
  <tr><td>Typing is slow for many patients</td><td>Speak a voice note instead</td></tr>
  <tr><td>Egyptian Arabic / mixed language hard to type</td><td>Whisper + dialect-aware planning</td></tr>
  <tr><td>Long guided chats cause drop-off</td><td>Jump as far as the words justify</td></tr>
  <tr><td>Old V1 voice routing hedged / duplicated menus</td><td>Clear Planner / Executor split (V2)</td></tr>
</table>

<div class="say">
<b>Say:</b> “We added voice to remove typing friction — without inventing a separate voice app.”
</div>

<h1>3. Architecture — the split</h1>
{imgs if imgs else ""}
<table>
  <tr><th>Layer</th><th>Owns</th><th>Does NOT own</th></tr>
  <tr>
    <td><b>Planner (GPT)</b></td>
    <td>Understand transcript, extract slots, pick furthest justified next step, emit VoicePlan</td>
    <td>Real doctors, free slots, DB writes</td>
  </tr>
  <tr>
    <td><b>Executor (Python)</b></td>
    <td>Validate vs PostgreSQL, hold slots, advance funnel, send WhatsApp reply, degrade safely</td>
    <td>Re-guessing patient intent</td>
  </tr>
</table>

<div class="ok">
<b>Design rule:</b> LLM plans the furthest justified step. Python validates availability and falls back.
</div>

<p>Production flag: <code>VOICE_ROUTER_V2=true</code> (default).</p>

<h1>4. Full pipeline (what happens for one voice note)</h1>
{"<img src='" + u02 + "' alt='pipeline'>" if u02 else ""}
<pre>1. Patient sends WhatsApp voice note (OGG audio)
2. Meta webhook → POST /webhook → message_type = audio
3. Background task: _handle_voice(phone, media_id)
4. Download audio from WhatsApp media API
5. Whisper STT → transcript (language NOT pinned — better Egyptian dialect)
6. Scrub empty / hallucination transcripts → ask clarify if needed
7. GPT planner → VoicePlan {{ goal, next_step, slots, confidence, language }}
8. Save Message + VoiceMessage + cost usage log
9. LanguageService picks sticky reply language (AR/EN)
10. voice_executor.execute_plan:
      · check doctor / date / time against DB
      · hold slot OR show list OR ask next question
      · if blocked → degrade one step + explain
11. Patient sees WhatsApp text / buttons / lists
12. Same conversation_engine booking funnel as typed chat</pre>

<p>Important: when a V2 plan is executed, we <b>do not</b> also run the old V1 fastpath — that was the duplicate-menu bug.</p>

<h1>5. VoicePlan — what the AI returns</h1>
<p>VoicePlan is the contract between AI and hospital logic.</p>
<table>
  <tr><th>Field</th><th>Meaning</th><th>Examples</th></tr>
  <tr><td><code>goal</code></td><td>What patient wants</td>
      <td>book_new, reschedule, cancel_appointment, abandon_draft, ask_doctors, handover, confirm, unclear…</td></tr>
  <tr><td><code>next_step</code></td><td>Where funnel goes</td>
      <td>ask_specialty, show_doctors, ask_date, show_slots, hold_slot, confirm_booking, pick_appointment, clarify…</td></tr>
  <tr><td><code>slots</code></td><td>Extracted entities</td>
      <td>doctor_name, specialty, date, time, change_target…</td></tr>
  <tr><td><code>confidence</code></td><td>How sure the model is</td><td>per-field scores</td></tr>
  <tr><td><code>language</code></td><td>Reply language hint</td><td>ar / en / mixed</td></tr>
</table>

<h3>Step decision cheat sheet</h3>
<pre>doctor + date + specific time  → hold_slot
doctor + day, no time          → show_slots
doctor only                    → ask_date
specialty only                 → show_doctors
want book, nothing named       → ask_specialty
cancel booked appointment      → pick_appointment
abandon mid-draft              → show_menu
handover request               → handover</pre>

<h3>Important distinction</h3>
<ul>
  <li><code>cancel_appointment</code> = cancel a <b>real booked</b> appointment</li>
  <li><code>abandon_draft</code> = stop a half-finished booking (“خلاص / مش عايز”)</li>
</ul>

<h1>6. Degradation / safety</h1>
{"<img src='" + u05 + "' alt='degrade'>" if u05 else ""}
<p>If the planner asks for something unavailable, the executor falls <b>one rung</b> and explains.</p>
<pre>hold_slot
   ↓ (time missing / taken)
show_slots
   ↓ (day missing)
ask_date
   ↓ (doctor unclear)
show_doctors / ask_specialty</pre>

<ul>
  <li>Never invent a doctor or free slot</li>
  <li>Never silent failure</li>
  <li>Never send two conflicting replies for one voice note</li>
</ul>

<div class="say">
<b>Say:</b> “AI can be aggressive. Code is careful. If 2pm is taken, we show open slots and say so.”
</div>

<h1>7. Languages</h1>
<ul>
  <li>Whisper is <b>not language-pinned</b> (better Egyptian dialect quality)</li>
  <li>Optional STT vocab prompt is <b>OFF</b> by default (<code>VOICE_STT_PROMPT=false</code>)</li>
  <li>Reply language chosen <b>after</b> STT from transcript script (Arabic vs Latin)</li>
  <li>Sticky language window: <code>VOICE_LANG_SESSION_MINUTES</code> (default 30)</li>
  <li>Supports Egyptian Arabic, English, and code-switch</li>
  <li>Bot replies in one language per message (AR or EN), not mixed</li>
</ul>

<h1>8. V1 vs V2</h1>
<table>
  <tr><th>V1 (legacy)</th><th>V2 (production)</th></tr>
  <tr><td>Model picked ~5 rough actions</td><td>Model emits full VoicePlan</td></tr>
  <tr><td>Python re-decided with thresholds</td><td>Python only validates + runs</td></tr>
  <tr><td>Hedging + duplicate menus</td><td>Furthest step + one-rung degrade</td></tr>
  <tr><td>Fastpath maze mid-flow</td><td>No silent fall-through when plan exists</td></tr>
  <tr><td>Hard to reason about</td><td>Clear Planner / Executor split</td></tr>
</table>
<p>Rollback: set <code>VOICE_ROUTER_V2=false</code>.</p>

<h1>9. Code modules &amp; config</h1>
<table>
  <tr><th>File</th><th>Role</th></tr>
  <tr><td><code>webhook.py</code></td><td>Detect audio, queue <code>_handle_voice</code></td></tr>
  <tr><td><code>voice_service.py</code></td><td>Download OGG, Whisper STT, GPT plan entry</td></tr>
  <tr><td><code>voice_prompts.py</code></td><td>Static <code>PLANNER_SYSTEM</code> (prompt-cache friendly)</td></tr>
  <tr><td><code>voice_schemas.py</code></td><td><code>VoicePlan</code> / <code>VoiceSlots</code> types</td></tr>
  <tr><td><code>voice_executor.py</code></td><td><code>execute_plan</code> — validate, degrade, reply</td></tr>
  <tr><td><code>voice_fastpath.py</code></td><td>V1 mid-flow only (fallback)</td></tr>
  <tr><td><code>voice_cost.py</code></td><td>STT + GPT cost logging</td></tr>
  <tr><td><code>language_service.py</code></td><td>Post-STT reply language</td></tr>
  <tr><td><code>conversation_engine.py</code></td><td>Shared booking state machine (text + voice)</td></tr>
</table>

<h3>Config knobs</h3>
<table>
  <tr><th>Env</th><th>Default</th><th>Meaning</th></tr>
  <tr><td><code>OPENAI_STT_MODEL</code></td><td>whisper-1</td><td>Speech-to-text</td></tr>
  <tr><td><code>OPENAI_VOICE_STRUCTURE_MODEL</code></td><td>gpt-4o-mini-ish</td><td>Planner model</td></tr>
  <tr><td><code>VOICE_ROUTER_V2</code></td><td>true</td><td>Split planner/executor path</td></tr>
  <tr><td><code>VOICE_STT_PROMPT</code></td><td>false</td><td>Extra Whisper vocab prompt</td></tr>
  <tr><td><code>VOICE_LANG_SESSION_MINUTES</code></td><td>30</td><td>Sticky reply language</td></tr>
  <tr><td><code>VOICE_REQUIRE_CONFIRM</code></td><td>false</td><td>Extra voice confirm gate</td></tr>
</table>

<h1>10. Admin / cost / observability</h1>
<ul>
  <li>Transcripts stored on <code>VoiceMessage</code></li>
  <li>Usage logs track voice STT + voice parse cost</li>
  <li>Streamlit dashboard KPIs: voice notes, minutes, cost, avg $/voice</li>
  <li>Tests: <code>test_voice_router_v2.py</code>, state-aware, language, cost, date/time hints…</li>
  <li>Eval helpers at repo root: <code>eval_voice_*.py</code></li>
</ul>

<h1>11. Example walkthrough</h1>
{"<img src='" + u09 + "' alt='example'>" if u09 else ""}
<div class="say">
<b>Demo story:</b><br>
Patient says: «عايز أحجز عند دكتور أحمد يوم الجمعة الساعة 2»<br>
→ Whisper transcript<br>
→ Plan: goal=<code>book_new</code>, next_step=<code>hold_slot</code>, slots=Ahmed / Friday / 14:00<br>
→ Executor checks DB<br>
→ If free: hold + ask confirm<br>
→ If not: degrade to <code>show_slots</code> and explain
</div>

<h1>12. What is NOT included</h1>
<ul>
  <li>No outbound text-to-speech / robot voice replies</li>
  <li>No Azure Speech / ElevenLabs</li>
  <li>No separate voice mobile app UI (WhatsApp native recorder only)</li>
  <li><code>edge-tts</code> / <code>gTTS</code> may appear in requirements but are not used by this voice path</li>
</ul>

<h1>13. Talk track for your PPT (4 slides)</h1>
<table>
  <tr><th>Your PPT slide</th><th>What you say</th></tr>
  <tr><td>Keywords / title</td>
      <td>“Patients can book by WhatsApp voice note. Voice in, buttons out.”</td></tr>
  <tr><td>Why Voice</td>
      <td>“Typing friction + dialect. Voice removes friction without a separate app.”</td></tr>
  <tr><td>Architecture</td>
      <td>“Whisper → Planner AI → Executor checks DB → WhatsApp reply. AI suggests, system confirms.”</td></tr>
  <tr><td>Key points</td>
      <td>“Input only · AI plans · system proves · no robot voice. Same product as typed chat.”</td></tr>
</table>

<h3>30-second version</h3>
<div class="say">
Patients send WhatsApp voice notes. Whisper turns speech into text. GPT makes a booking plan.
Python checks the real hospital schedule. If the time is free we hold it; if not we step back and explain.
Replies are normal WhatsApp buttons. Safe, Arabic + English, same booking product.
</div>

<h3>Q&amp;A cheat sheet</h3>
<table>
  <tr><th>Question</th><th>Answer</th></tr>
  <tr><td>Do you reply with voice?</td><td>No — WhatsApp text/buttons only.</td></tr>
  <tr><td>What converts speech?</td><td>OpenAI Whisper (<code>whisper-1</code>).</td></tr>
  <tr><td>Who decides next step?</td><td>AI Planner suggests · Executor confirms with DB.</td></tr>
  <tr><td>Can AI invent a doctor/time?</td><td>No. Executor validates everything.</td></tr>
  <tr><td>What if time is taken?</td><td>Degrade one step (e.g. show_slots) and explain.</td></tr>
  <tr><td>Arabic support?</td><td>Yes — Egyptian Arabic + English + code-switch.</td></tr>
  <tr><td>Is voice a separate bot?</td><td>No — same conversation funnel as typing.</td></tr>
  <tr><td>Can we roll back?</td><td>Yes — <code>VOICE_ROUTER_V2=false</code>.</td></tr>
  <tr><td>Where is cost tracked?</td><td>Usage logs + Streamlit voice KPIs.</td></tr>
</table>

<div class="ok">
<b>Bottom line:</b> Split Voice = understand speech aggressively, book only what the hospital DB proves is real.
</div>
"""


def main() -> None:
    if not CHROME.exists():
        raise SystemExit(f"Chrome not found: {CHROME}")
    html_path = html_dir / "VOICE_FULL_AWARENESS.html"
    pdf_path = out_dir / "VOICE_FULL_AWARENESS.pdf"
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{CSS}</style></head><body>{body()}</body></html>"
    )
    html_path.write_text(html, encoding="utf-8")
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
        if pdf_path.exists() and pdf_path.stat().st_size > 1000:
            break
        time.sleep(0.25)
    print("OK", pdf_path, pdf_path.stat().st_size if pdf_path.exists() else 0)


if __name__ == "__main__":
    main()
