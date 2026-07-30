# Hospital Chatbot

AI-powered WhatsApp chatbot for hospital appointment booking.

## Tech Stack

- FastAPI
- PostgreSQL
- OpenAI
- Whisper
- WhatsApp Cloud API
- LangGraph
- Alembic (DB migrations)

## Database migrations (Alembic)

Run from the repo root with the venv active. `DATABASE_URL` comes from `app.core.config` (`.env` / environment), not from `alembic.ini`.

```powershell
# Apply pending migrations
.\venv\Scripts\python.exe -m alembic upgrade head

# Show current revision on the connected DB
.\venv\Scripts\python.exe -m alembic current

# Create a new migration after model changes
.\venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe_change"

# One-time for DBs that already have the full schema (no DDL needed):
.\venv\Scripts\python.exe -m alembic stamp head
```
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
