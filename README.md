# Hospital Chatbot

AI-powered WhatsApp chatbot for hospital appointment booking, rescheduling, cancellation, doctor/specialty inquiry, voice notes, and receptionist handover.

## Tech Stack

- FastAPI
- PostgreSQL
- OpenAI / Whisper
- WhatsApp Cloud API
- LangGraph
- Alembic
- Streamlit (admin dashboard)

## Features

- Book, reschedule, and cancel appointments
- Search by specialty or doctor name
- Arabic and English conversation support
- Voice-note understanding (STT + guided booking flow)
- Admin dashboard for clinic operations and KPIs, with company-admin and clinic-admin roles
- Usage / cost related logging

## Quick Start (Local)

1. Create and activate a virtual environment.
2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill required values (`DATABASE_URL`, WhatsApp, OpenAI, etc.).
4. Apply database migrations:

```powershell
.\venv\Scripts\python.exe -m alembic upgrade head
```

5. Run the API:

```powershell
.\venv\Scripts\uvicorn.exe app.main:app --reload --host 0.0.0.0 --port 8000
```

6. Optional: run the dashboard:

```powershell
.\venv\Scripts\streamlit.exe run dashboard/streamlit_app.py --server.port 8501
```

For local WhatsApp webhook testing, expose port `8000` with a tunnel (for example `cloudflared`).

## Database Migrations (Alembic)

Run from the repo root. `DATABASE_URL` comes from `.env` / `app.core.config`, not from `alembic.ini`.

```powershell
# Apply pending migrations
.\venv\Scripts\python.exe -m alembic upgrade head

# Show current DB revision
.\venv\Scripts\python.exe -m alembic current

# Create a new migration after model changes
.\venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe_change"

# One-time only for an existing full schema DB
.\venv\Scripts\python.exe -m alembic stamp head
```

## Documentation

- **Full technical & architecture guide (v5):** [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md) — product → architecture → ops → reference; figures + GUI screenshots; Phase 2 dashboard changes in §24; limitations, capacity, and the voice-latency plan in §25
- **Model prices & what $1 buys:** [`docs/COST.md`](docs/COST.md) — what our transcription and planner models cost per voice note, every credible alternative priced on the same workload, and per-dollar capacity
- **$1 table for slides:** [`docs/pdf/COST_ONE_DOLLAR.pdf`](docs/pdf/COST_ONE_DOLLAR.pdf) · drop-in image [`docs/images/cost-one-dollar.png`](docs/images/cost-one-dollar.png) · editable PPT [`docs/pdf/COST_ONE_DOLLAR.pptx`](docs/pdf/COST_ONE_DOLLAR.pptx)
- **Deploy guide (SSH, secrets, Streamlit service):** [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- PDF exports: [`docs/pdf/DOCUMENTATION.pdf`](docs/pdf/DOCUMENTATION.pdf) · [`docs/pdf/COST.pdf`](docs/pdf/COST.pdf) — regenerate with `python docs/_export_pdf.py DOCUMENTATION COST`
- **Split Voice — 4 slides for PPT designer:**
  - [`docs/pdf/VOICE_4_SLIDES.pptx`](docs/pdf/VOICE_4_SLIDES.pptx) — PowerPoint reference (Definition · Why · Architecture · Key points)
  - [`docs/pdf/VOICE_4_SLIDES.pdf`](docs/pdf/VOICE_4_SLIDES.pdf) — same 4 slides as PDF
  - Teammate brief: [`docs/pdf/VOICE_TEAMMATE_BRIEF.pdf`](docs/pdf/VOICE_TEAMMATE_BRIEF.pdf)
  - **Presenter full awareness:** [`docs/pdf/VOICE_FULL_AWARENESS.pdf`](docs/pdf/VOICE_FULL_AWARENESS.pdf) — everything about voice for your talk
  - Regenerate awareness: `python docs/_export_voice_awareness.py`

## Deploy

Push / merge to `main` → GitHub Actions SSH deploy (backend auto-restarts).  
Full details: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).
## Project Structure (High Level)

- `app/api` — HTTP routes / webhook
- `app/graph` — conversation engine
- `app/services` — booking, doctors, voice, WhatsApp, etc.
- `app/models` — database models
- `dashboard` — Streamlit admin UI
- `alembic` — DB migrations
- `docs` — project documentation
