from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

DATA_DIR = Path(os.getenv("MS_FLEET_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.getenv("MS_FLEET_DB_PATH", DATA_DIR / "ms_fleet_command_center.db"))

APP_NAME = "MS Fleet AI Command Center"
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Los_Angeles")

WAHA_SERVER_URL = os.getenv("WAHA_SERVER_URL", "http://localhost:3000")
WAHA_SESSION_NAME = os.getenv("WAHA_SESSION_NAME", "default")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_ENABLED = os.getenv("OLLAMA_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
CHAT_RETENTION_DAYS = int(os.getenv("CHAT_RETENTION_DAYS", "30"))

DASHBOARD_DATA_SOURCE = os.getenv("DASHBOARD_DATA_SOURCE", "sqlite").strip().lower()
SUPABASE_ENABLED = os.getenv("SUPABASE_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_KEY = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY

READ_ONLY_WARNING = (
    "AI summary is not proof. Human verification required before closing jobs or approving payments."
)

CONFIDENCE_LABELS = ("Confirmed", "Likely", "Unconfirmed", "Conflicting")

REPAIR_CATEGORIES = [
    "Engine",
    "Transmission",
    "Electrical",
    "Starting/Charging",
    "Brakes",
    "Air System",
    "Cooling System",
    "Fuel System",
    "Suspension",
    "Steering",
    "Tires/Wheels",
    "Exhaust/DPF/DEF",
    "HVAC",
    "Diagnostics",
    "Trailer/Body",
    "Unknown",
]

EXPENSIVE_PART_KEYWORDS = {
    "turbo",
    "transmission",
    "injector",
    "dpf",
    "def pump",
    "ecm",
    "pcm",
    "radiator",
    "clutch",
    "compressor",
    "aftertreatment",
    "catalyst",
}

SAFETY_CRITICAL_KEYWORDS = {
    "brake",
    "brakes",
    "steer",
    "steering",
    "tire",
    "wheel",
    "lug",
    "hub",
    "air leak",
    "chamber",
    "slack adjuster",
    "suspension",
}
