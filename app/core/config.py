import os
from dotenv import load_dotenv

load_dotenv()

# WhatsApp
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v19.0")

# WhatsApp Flows doctor picker (ImageCarousel swipe + radio select)
# Set USE_DOCTOR_FLOW=true and WHATSAPP_FLOW_ID after publishing the Flow in Meta.
USE_DOCTOR_FLOW = os.getenv("USE_DOCTOR_FLOW", "false").lower() in {"1", "true", "yes"}
WHATSAPP_FLOW_ID = os.getenv("WHATSAPP_FLOW_ID", "").strip()
WHATSAPP_FLOW_CTA = os.getenv("WHATSAPP_FLOW_CTA", "عرض الأطباء")
# Use true while testing an unpublished (Draft) Flow in Meta.
WHATSAPP_FLOW_DRAFT = os.getenv("WHATSAPP_FLOW_DRAFT", "false").lower() in {"1", "true", "yes"}

# AI providers
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/hospital_chatbot",
)

# Default clinic context for MVP single-clinic demo
DEFAULT_TENANT_ID = int(os.getenv("DEFAULT_TENANT_ID", "1"))
DEFAULT_CLINIC_ID = int(os.getenv("DEFAULT_CLINIC_ID", "1"))
CLINIC_DISPLAY_NAME = os.getenv("CLINIC_DISPLAY_NAME", "مستشفى جامعة نيو جيزة")
CLINIC_LOCATION = os.getenv("CLINIC_LOCATION", "New Giza University Hospital")
CLINIC_LOCATION_AR = os.getenv(
    "CLINIC_LOCATION_AR",
    os.getenv("CLINIC_DISPLAY_NAME", "مستشفى جامعة نيو جيزة"),
)

# Ops / escalation
RECEPTIONIST_WHATSAPP = os.getenv("RECEPTIONIST_WHATSAPP", "").strip()
CANCEL_CUTOFF_HOURS = int(os.getenv("CANCEL_CUTOFF_HOURS", "2"))
RESCHEDULE_CUTOFF_HOURS = int(os.getenv("RESCHEDULE_CUTOFF_HOURS", "2"))

# Booking policy
SLOT_HOLD_MINUTES = int(os.getenv("SLOT_HOLD_MINUTES", "3"))
BOOKING_WINDOW_DAYS = int(os.getenv("BOOKING_WINDOW_DAYS", "14"))
MIN_LEAD_HOURS = int(os.getenv("MIN_LEAD_HOURS", "2"))
DUPLICATE_APPOINTMENT_DAYS = int(os.getenv("DUPLICATE_APPOINTMENT_DAYS", "7"))
ALLOW_OVERBOOKING = os.getenv("ALLOW_OVERBOOKING", "false").lower() in {"1", "true", "yes"}
REQUIRE_MRN = os.getenv("REQUIRE_MRN", "false").lower() in {"1", "true", "yes"}
REQUIRE_DOB = os.getenv("REQUIRE_DOB", "false").lower() in {"1", "true", "yes"}
REMINDER_HOURS_BEFORE = [
    int(x.strip())
    for x in os.getenv("REMINDER_HOURS_BEFORE", "24,2").split(",")
    if x.strip()
]
