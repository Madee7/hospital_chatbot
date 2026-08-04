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
- Admin dashboard for clinic operations and KPIs
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

Full project guide (architecture, flows, deploy, WhatsApp Flow setup):

- [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md)
- PDF export: [`docs/pdf/DOCUMENTATION.pdf`](docs/pdf/DOCUMENTATION.pdf)

## Deploy

Push / merge to `main` triggers GitHub Actions → SSH deploy
(`.github/workflows/deploy.yml`):

1. `git pull origin main` on `C:\apps\hospital-chatbot`
2. `pip install -r requirements.txt`
3. `alembic upgrade head`
4. `Restart-Service HospitalChatbotBackend`

**Secrets** (repo → Settings → Secrets → Actions):

| Secret | Required | Notes |
|--------|----------|--------|
| `WINDOWS_SSH_KEY` | yes | Private key for the server |
| `WINDOWS_SSH_HOST` | optional | Defaults to server IP in the workflow |
| `WINDOWS_SSH_USER` | optional | Defaults to `Administrator` |
| `WINDOWS_SSH_PORT` | optional | Defaults to `22` |

Manual run: Actions → **Deploy to Windows server** → **Run workflow**.

If Actions fails, update the server manually:

```powershell
cd C:\apps\hospital-chatbot
git checkout main
git pull origin main
.\venv\Scripts\pip.exe install -r requirements.txt
.\venv\Scripts\python.exe -m alembic upgrade head
Restart-Service HospitalChatbotBackend
```

## Project Structure (High Level)

- `app/api` — HTTP routes / webhook
- `app/graph` — conversation engine
- `app/services` — booking, doctors, voice, WhatsApp, etc.
- `app/models` — database models
- `dashboard` — Streamlit admin UI
- `alembic` — DB migrations
- `docs` — project documentation
