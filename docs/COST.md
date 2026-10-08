# Hospital Chatbot — Model Prices & What One Dollar Buys

| | |
|:--|:--|
| **Version** | 2.1 |
| **Updated** | 2026-08-16 |
| **Scope** | Prices only: what our two models cost us, what the alternatives cost, and what one dollar provides |
| **Not here** | Server limits, capacity, voice latency, and the WhatsApp reminder wall — those live in [`DOCUMENTATION.md`](DOCUMENTATION.md) §25 |
| **Code sources of truth** | `app/services/voice_cost.py` (rate table) · `usage_logs` (what we actually spent) |
| **List prices verified** | 2026-08-16, against public pricing pages and pricing trackers |

> **How to read this document**
> Section 1 is what we measurably pay. Sections 2 and 3 put every credible alternative next to that number, priced on **our** workload — a 3.89-second voice note and a 4,049-token planning call — because a rate per minute or per million tokens tells a clinic nothing on its own.
> **Every list price below changes without notice.** Re-check the provider's page before you quote a customer.

---

## Table of contents

1. [What we pay today](#1-what-we-pay-today)
2. [Speech-to-text: the market against us](#2-speech-to-text-the-market-against-us)
3. [The planner model: the market against us](#3-the-planner-model-the-market-against-us)
4. [What one dollar provides](#4-what-one-dollar-provides)
5. [Would switching be worth it?](#5-would-switching-be-worth-it)
6. [The one bill that is not OpenAI](#6-the-one-bill-that-is-not-openai)
7. [Where the numbers live](#7-where-the-numbers-live)
8. [Document history](#8-document-history)

---

## 1. What we pay today

Two models, one per stage of a voice note:

| Stage | Model | Why this one | Rate |
|:------|:------|:-------------|-----:|
| Transcription | `whisper-1` | Chosen for Egyptian dialect — `gpt-4o-transcribe` scored worse here, per the note in `app/core/config.py` | $0.006 / audio minute |
| Planning + text understanding | `gpt-4o-mini` | Cheap, fast, reliable with structured JSON output | $0.15 / $0.075 cached / $0.60 per 1M tokens |

A typed message that resolves by tapping a button costs **nothing** — no model is called at all.

### 1.1 The measured month

![C1 — Usage / costs](images/gui/dash-usage-costs-full.png)

**Figure C1 — The whole month on one screen.** 115 voice notes (447 seconds of audio), 363 text model calls, 790 inbound WhatsApp messages, **$0.1165 total**.

| What | Measured | Per unit |
|:-----|---------:|---------:|
| Voice transcription (`voice_stt`) | $0.0449 | **$0.000390** per note |
| Voice planning (`voice_parse`) | $0.0532 | **$0.000463** per note |
| **A complete voice note** | **$0.0981** | **$0.000853** |
| Intent classification (`text_intent`, 253 calls) | $0.0124 | $0.0000490 |
| Choice mapping (`text_choice`, 110 calls) | $0.0060 | $0.0000545 |
| **The whole month** | **$0.1165** | **$0.000147** per inbound message |

Two facts worth carrying into any meeting: our average voice note is **3.89 seconds** long, and a planning call is about **4,049 tokens**, most of it the static `PLANNER_SYSTEM` prefix that OpenAI caches at half price. Every alternative in this document is priced against exactly that shape.

An earlier capture of the same screen (94 notes, 388 s) gave **$0.000854** per note against today's $0.000853. The per-note figure is stable enough to budget with.

![C2 — Recent usage logs](images/gui/dash-usage-logs-full.png)

**Figure C2 — One call per row.** Tokens, cost, latency, status. A `text_intent` call is roughly 300 tokens, $0.00005, and about a second. (An earlier capture than Figure C1; the row shape is the point.)

### 1.2 When a price changes, edit `.env`, not the code

```env
VOICE_PRICE_STT_PER_MIN=0.006
VOICE_PRICE_INPUT_PER_1M=0.15
VOICE_PRICE_CACHED_PER_1M=0.075
VOICE_PRICE_OUTPUT_PER_1M=0.60
```

An unknown model silently falls back to the `gpt-4o-mini` tier and $0.006/minute, so a swap never crashes the estimator — but it can quietly misprice it. Check `voice_cost.py` whenever `OPENAI_MODEL` or `OPENAI_STT_MODEL` changes.

---

## 2. Speech-to-text: the market against us

List prices as of **2026-08-16**. The two columns that matter are the last two: what the provider would charge for *our* 3.89-second note, and how many such notes one dollar buys.

| Provider / model | List price | Our 3.89 s note | Notes per $1 | Honest caveat |
|:-----------------|-----------:|----------------:|-------------:|:--------------|
| **`whisper-1` — what we use** | **$0.006 / min** | **$0.000389** | **~2,570** | Our accuracy baseline on Egyptian dialect |
| `gpt-4o-transcribe` | $0.006 / min | $0.000389 | ~2,570 | Same price; tested worse on our dialect |
| `gpt-4o-mini-transcribe` | $0.003 / min | $0.000195 | ~5,140 | Half price, same vendor and SDK — the easiest experiment we have not run |
| Groq `whisper-large-v3-turbo` | $0.04 / hour | $0.000111 | ~9,000 | **10-second billing minimum**; same Whisper family, OpenAI-compatible API, and `GROQ_API_KEY` already exists in config |
| Groq `whisper-large-v3` | $0.111 / hour | $0.000308 | ~3,250 | Full large-v3 quality at a fifth of our rate, same 10-second minimum |
| Groq `distil-whisper` | $0.02 / hour | $0.000056 | ~18,000 | **English only** — useless for an Arabic clinic |
| AssemblyAI Universal-2 | $0.0025 / min | $0.000162 | ~6,170 | New vendor, new SDK; verify Arabic quality |
| ElevenLabs Scribe | ~$0.22 / hour | $0.000238 | ~4,200 | Newer entrant, aggressive pricing, unverified on dialect |
| Deepgram Nova-3 multilingual | $0.0058 / min | $0.000376 | ~2,660 | Bills by the second, no rounding; strongest at streaming |
| Google Cloud dynamic batch | $0.003 / min | $0.000195 | ~5,140 | Up to 24-hour turnaround — **impossible** for a chat reply |
| Azure AI Speech standard | $1.00 / hour | $0.001083 | ~920 | 2.8× our cost |
| `gpt-realtime-whisper` | $0.017 / min | $0.001102 | ~910 | For live streaming, not for a WhatsApp voice note |
| Self-hosted Whisper on a GPU | ~$0.001–$0.0025 / min of infra | $0.000065–$0.000162 | 6,000–15,000 | Only on a real GPU host; on our CPU-only Windows box it is slower *and* worse ([`DOCUMENTATION.md`](DOCUMENTATION.md) §25.5) |

### 2.1 The trap short notes fall into

Our notes average **3.89 seconds**, and several providers bill a minimum per request. Groq's 10-second floor means a 4-second note is billed as 10 seconds — the headline "$0.04 per hour" is really **$0.000111 per note** for us, not $0.000043. It is still nine times cheaper than what we pay; it is just not the number on the pricing page. Whisper-family models on Groq also prefer clips of 30 seconds or more and pad shorter audio with silence, so measure quality on real 4-second Egyptian voice notes before believing any of this.

### 2.2 Why we have not already switched

`app/core/config.py` says it plainly: `whisper-1` is the production default because `gpt-4o-transcribe` was worse on Egyptian dialect *here*. Transcription quality is the whole product — a mis-heard doctor name becomes a wrong booking, and a wrong booking costs a clinic far more than the $0.0002 we would save on the note. Any switch needs a measured accuracy test on real Egyptian voice notes, not a price table.

---

## 3. The planner model: the market against us

Every model below is priced on the **same** call we actually make: 3,946 input tokens (of which ~3,200 hit the cached prefix) and 103 output tokens. Where a provider publishes a cached-input rate, it is used; where it does not, the full input rate is charged.

| Model | Input / cached / output per 1M | Cost per planning call | Calls per $1 | Versus us |
|:------|:-------------------------------|----------------------:|-------------:|:----------|
| DeepSeek V4-Flash | $0.14 / $0.0028 / $0.28 | $0.000142 | ~7,040 | 3.3× cheaper |
| GPT-5-nano | $0.05 / — / $0.40 | $0.000239 | ~4,180 | 2× cheaper |
| Gemini 2.0 Flash-Lite | $0.075 / — / $0.30 | $0.000327 | ~3,060 | 1.4× cheaper |
| GPT-5.6-luna | $0.20 / $0.02 / $1.20 | $0.000337 | ~2,970 | 1.4× cheaper |
| **`gpt-4o-mini` — what we use** | **$0.15 / $0.075 / $0.60** | **$0.000414 modelled, $0.000463 measured** | **~2,160** | **baseline** |
| GPT-4.1-nano | $0.10 / — / $0.40 | $0.000436 | ~2,290 | about the same |
| Gemini 2.5 Flash-Lite | $0.10 / — / $0.40 | $0.000436 | ~2,290 | about the same |
| Mistral Small 4 | $0.15 / — / $0.60 | $0.000654 | ~1,530 | 1.4× dearer |
| Claude Haiku 3 | $0.25 / — / $1.25 | $0.001115 | ~900 | 2.4× dearer |
| Claude Haiku 4.5 | $1.00 / $0.10 / $5.00 | $0.001581 | ~630 | 3.4× dearer |
| GPT-4.1-mini | $0.40 / — / $1.60 | $0.001743 | ~570 | 3.8× dearer |
| GPT-4o | $2.50 / $1.25 / $10.00 | $0.006895 | ~145 | 15× dearer |

Three things this table teaches:

- **We are already in the cheap tier.** The best possible planner swap saves about **$0.0003 per note**. At our volume that is three cents a month.
- **Caching is worth more than the vendor.** The modelled $0.000414 for `gpt-4o-mini` is below GPT-4.1-nano's $0.000436 *despite a 50 % higher input rate*, purely because the static `PLANNER_SYSTEM` prefix is cached. Keeping that prompt stable is a bigger lever than shopping for a cheaper model.
- **Structured output is the real constraint.** The planner must return a valid `VoicePlan` every time. A model that is 3× cheaper and fails JSON schema once in fifty calls is not cheaper — it is a broken booking with a discount.

Our own gap: measured cost per call ($0.000463) sits above the modelled figure ($0.000414) because not every call gets a cache hit. That difference — 12 % — is the honest error bar on this whole table.

---

## 4. What one dollar provides

Same three-column shape as the unit-cost table: metric, number, basis. Flip the unit cost and you get the capacity of **$1**.

For the PPT: standalone PDF [`pdf/COST_ONE_DOLLAR.pdf`](pdf/COST_ONE_DOLLAR.pdf), drop-in image [`images/cost-one-dollar.png`](images/cost-one-dollar.png), editable slide [`pdf/COST_ONE_DOLLAR.pptx`](pdf/COST_ONE_DOLLAR.pptx).

### 4.1 Unit cost (what we measured)

| Metric | Cost | Basis |
|:-------|-----:|:------|
| Total AI cost (30 days) | **$0.1165** | Live dashboard logs (Figure C1) |
| Per voice message | **≈ $0.0009** | Whisper + GPT-4o-mini (115 notes) |
| LLM voice planner only | **≈ $0.0005** | `gpt-4o-mini` `voice_parse` |
| Whisper STT only | **≈ $0.0004** | `whisper-1` |
| Test volume | **1,004 WhatsApp messages** | 790 inbound · 214 outbound · 0 failed |

Rounded to the same one-decimal-of-a-cent the dashboard already shows (`Avg / voice $0.0008`). Exact figures: $0.000853 per complete note, $0.000463 planner, $0.000390 STT.

### 4.2 What $1 buys

| Metric | What $1 provides | Basis |
|:-------|-----------------:|:------|
| Complete voice notes | **≈ 1,170** | $1 ÷ $0.000853 (Whisper + GPT-4o-mini) |
| Whisper STT only | **≈ 2,560 notes** | $1 ÷ $0.000390 · also **167 minutes** of audio |
| LLM voice planner only | **≈ 2,160 calls** | $1 ÷ $0.000463 (`voice_parse`) |
| Intent classifications | **≈ 20,400** | $1 ÷ $0.000049 (`text_intent`) |
| Choice mappings | **≈ 18,300** | $1 ÷ $0.000055 (`text_choice`) |
| Inbound patient messages | **≈ 6,800** | $1 ÷ $0.000147 blended AI cost |
| Expected voice compute | **≈ 6–18 s** | Typical end-to-end reply for a ~4 s note — not a volume projection |
| Button / list taps | **unlimited** | No model call — $0 |

> **One dollar of OpenAI credit buys about 1,170 complete voice notes** — transcription, planning, and a checked booking answer for every one of them. Current WhatsApp volume is a test sample, so it is not used to say how many months $1 would last.

### 4.3 Longer notes buy less

Transcription scales with duration; planning does not. So the answer moves with how much people say:

| Note length | Transcription | Planning | Total | Notes per $1 |
|:------------|--------------:|---------:|------:|-------------:|
| 5 s | $0.000500 | $0.000463 | $0.000963 | ~1,040 |
| 10 s | $0.001000 | $0.000463 | $0.001463 | ~684 |
| 15 s | $0.001500 | $0.000463 | $0.001963 | ~509 |
| 30 s | $0.003000 | $0.000463 | $0.003463 | ~289 |
| 60 s | $0.006000 | $0.000463 | $0.006463 | ~155 |

### 4.4 The same dollar on other stacks

| Stack | Per voice note | Notes per $1 |
|:------|---------------:|-------------:|
| Groq turbo STT + DeepSeek V4-Flash — cheapest credible | $0.000253 | **~3,950** |
| Groq turbo STT + `gpt-4o-mini` — one vendor change | $0.000574 | ~1,740 |
| `gpt-4o-mini-transcribe` + `gpt-4o-mini` — no new vendor | $0.000658 | ~1,520 |
| **`whisper-1` + `gpt-4o-mini` — us today** | **$0.000853** | **~1,170** |
| Azure Speech + Claude Haiku 4.5 — premium | $0.002664 | ~375 |

**The plain summary for a stakeholder:** one dollar covers roughly a thousand voice notes or six thousand patient messages. The cheapest arrangement on the market would make that four thousand notes. Either way, model inference is not what this product costs.

---

## 5. Would switching be worth it?

Monthly OpenAI spend, voice notes only, at three volumes:

| Monthly voice notes | Us today | Cheapest credible stack | Money saved |
|:--------------------|---------:|------------------------:|------------:|
| 115 (today's real volume) | $0.10 | $0.03 | **$0.07** |
| 1,000 | $0.85 | $0.25 | $0.60 |
| 5,000 | $4.27 | $1.27 | $3.00 |
| 20,000 | $17.06 | $5.06 | $12.00 |

Twelve dollars a month at twenty thousand notes. That is the entire prize for changing two vendors, writing a second transcription client, and re-testing Egyptian-dialect accuracy from scratch.

| | |
|:--|:--|
| **Recommendation** | Stay on `whisper-1` + `gpt-4o-mini`. Run **one** cheap experiment: `gpt-4o-mini-transcribe` at half the price with no new vendor, scored on real Egyptian voice notes. Adopt only if accuracy holds. |
| **Worth revisiting when** | Volume passes roughly 50,000 notes a month, or a clinic sends long notes, or Groq's Whisper proves both faster and equally accurate — speed being the more valuable of the two ([`DOCUMENTATION.md`](DOCUMENTATION.md) §25.5). |
| **Do not** | Self-host Whisper on the current CPU-only Windows server to save $12. It will be slower and less accurate. |

---

## 6. The one bill that is not OpenAI

WhatsApp free-form replies are free inside the 24-hour service window that each patient message opens. Outside it, only a **paid, pre-approved template** is delivered — which is exactly where appointment reminders fall, since they are scheduled days after the booking conversation ended.

| Line item | How it scales | Priced in our code? |
|:----------|:--------------|:--------------------|
| Free-form conversation, in window | Free at any volume | n/a |
| Template reminders, out of window | `confirmed_appointments × len(REMINDER_HOURS_BEFORE)`, at Meta's per-message utility rate for Egypt | **No — $0.00, which is an accounting gap, not a discount** |

With the default `REMINDER_HOURS_BEFORE=24,2`, every booking is **two** paid template messages. This is the only cost line that grows with clinic success rather than chat volume, and it will exceed the OpenAI bill long before OpenAI becomes interesting. Confirm the Egypt utility rate on Meta's pricing page before quoting.

The mechanics, the code path, and what it takes to fix it are in [`DOCUMENTATION.md`](DOCUMENTATION.md) §25.4.

---

## 7. Where the numbers live

Every figure in this document comes from `usage_logs` (`app/models/usage_models.py`), written by `log_usage()` on each provider call:

| Column | Meaning |
|:-------|:--------|
| `provider` | `whisper-1`, `gpt-4o-mini`, … |
| `operation` | `voice_stt`, `voice_parse`, `text_intent`, `text_choice`, `text_rewrite` |
| `tokens_or_minutes` | **Rounded audio seconds** for `voice_stt`; tokens for everything else |
| `cost_estimate` | USD from `voice_cost.py` |
| `latency_ms` | Provider round-trip time |
| `status` | `completed` or a failure state |

One naming trap: `tokens_or_minutes` stores *seconds* for transcription — the 447 in Figure C1 is 447 seconds, 7.45 minutes, not 447 minutes. A failed call still logs what was already spent: if audio transcribed and then planning failed, the STT cost is recorded anyway. **We never hide a spend that happened.**

Since Phase 2, money is **company-admin only**:

![C3 — KPIs with spend visible](images/gui/dash-kpis.png)

**Figure C3 — Spend on the KPI screen, for one role only.** `Est. cost $0.1165`, `Voice cost $0.0981`, and `Avg / voice $0.0008` appear beside the volume metrics because this session is a `company_admin` (see the badge under the email). A `clinic_admin` sees the same screen without those three tiles and without a **Usage / costs** entry in the sidebar.

Per-call detail also lands in `logs/stdout.log`, which is where a single suspicious note gets audited:

```text
stt=$0.000390 (3.89s) gpt=$0.000463 (in=3946 cached=3200 out=103) total=$0.000853
```

A short checklist to keep these numbers trustworthy: re-verify list prices before every quotation, reconcile our estimate against the OpenAI billing dashboard monthly, set a hard spend limit on the account, keep `PLANNER_SYSTEM` static so the cache discount keeps applying, and add a `whatsapp_template` operation to `usage_logs` on the day templates go live.

---

## 8. Document history

| Date | Version | Change |
|:-----|:--------|:-------|
| **2026-08-17** | **2.1** | **Added a matching three-column unit-cost table and a “what $1 buys” table (complete notes, STT, planner, intent, months at current volume)** |
| 2026-08-16 | 2.0 | Rebuilt as a price comparison: every credible STT and LLM alternative priced on our own workload, per-dollar capacity for each stack, and a switch recommendation. Server limits, capacity, voice latency, and the reminder wall moved to [`DOCUMENTATION.md`](DOCUMENTATION.md) §25 |
| 2026-08-16 | 1.1 | Refreshed the measured sample to the latest 30-day capture (115 notes, 447 s, $0.1165) and re-derived every per-unit figure |
| 2026-08-16 | 1.0 | Split out of `DOCUMENTATION.md` v5.0: rates, formulas, measured sample, $1 capacity, WhatsApp billing, server limits |

*Costs are estimates produced by this repository, not invoices. OpenAI and Meta bills are the authority. List prices for other vendors were read from public pricing pages on 2026-08-16 and will drift.*
