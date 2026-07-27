import logging
import os

from fastapi import FastAPI

from app.api.routes import booking_router, webhook_router
from app.db.database import create_tables

# Surface INFO-level app logs (voice transcript + cost breakdown, routing, etc.)
# in the console. Without this, module loggers stay silent at the default
# WARNING level and the [voice]/[voice][cost] lines never print.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("app").setLevel(logging.INFO)

app = FastAPI(
    title="Hospital Chatbot API",
    description="Backend API for Hospital Appointment Chatbot",
    version="1.0.0",
)


@app.on_event("startup")
def on_startup() -> None:
    # Prefer `alembic upgrade head` on deploy. create_tables() remains as a
    # safe idempotent fallback (creates missing tables only; no migrations).
    try:
        create_tables()
    except Exception as exc:
        print(f"Warning: could not create tables on startup: {exc}")


@app.get("/")
def root():
    return {
        "message": "Hospital Chatbot API is running successfully!",
        "routes": ["/webhook", "/booking", "/docs"],
    }


app.include_router(webhook_router)
app.include_router(booking_router)
