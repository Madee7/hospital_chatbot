from fastapi import FastAPI

from app.api.routes import booking_router, webhook_router
from app.db.database import create_tables

app = FastAPI(
    title="Hospital Chatbot API",
    description="Backend API for Hospital Appointment Chatbot",
    version="1.0.0",
)


@app.on_event("startup")
def on_startup() -> None:
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
