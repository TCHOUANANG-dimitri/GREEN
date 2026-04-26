# ============================================================
# GREEN App — Configuration
# Centralises all environment-dependent settings.
# Values are read from a .env file (or system environment).
# ============================================================

import os
from dotenv import load_dotenv

# Load .env file from the project root (one level above /backend)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

# ---- Security -----------------------------------------------
SECRET_KEY: str = os.getenv("SECRET_KEY", "green-secret-key-change-in-production-2026")
ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

# ---- Database -----------------------------------------------
# SQLite for local development — file stored at project root
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(os.path.dirname(__file__), '..', 'green.db')
)

# ---- Gemini AI (GreenBot chatbot + camera disease research) --
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = "gemini-2.5-flash-lite"   # Free tier with separate quota

# ---- Weather API (OpenWeatherMap) --------------------------
WEATHER_API_KEY: str = os.getenv("WEATHER_API_KEY", "")
OPENWEATHER_BASE_URL: str = "https://api.openweathermap.org/data/2.5"

# ---- Camera / Rover -----------------------------------------
# Default IP for rover camera stream (MJPEG over HTTP)
DEFAULT_CAMERA_IP: str   = os.getenv("DEFAULT_CAMERA_IP",   "192.168.1.100")
DEFAULT_CAMERA_PORT: int = int(os.getenv("DEFAULT_CAMERA_PORT", "8080"))
# Keep drone aliases for backward compatibility
DEFAULT_DRONE_IP          = DEFAULT_CAMERA_IP
DEFAULT_DRONE_STREAM_PORT = DEFAULT_CAMERA_PORT

# ---- Models -------------------------------------------------
# Disease detection model (EfficientNet — cassava / maize / tomato)
MODEL_PATH: str = os.getenv(
    "MODEL_PATH",
    os.path.join(os.path.dirname(__file__), '..', 'best_efficientnet.pth')
)

# Pest detection model (legacy EfficientNet-based — superseded by YOLO model)
# ⚠️  Set PEST_MODEL_PATH in .env; leave empty to disable gracefully
PEST_MODEL_PATH: str = os.getenv(
    "PEST_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), '..', 'best_pest_model.pth')
)

# YOLO pest-detection model (best.pt — YOLOv8, detects Criquet + papillon de nuit)
YOLO_MODEL_PATH: str = os.getenv(
    "YOLO_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), '..', 'best.pt')
)

# ---- RAG ----------------------------------------------------
RAG_CHUNKS_PATH: str = os.path.join(os.path.dirname(__file__), '..', 'rag', 'chunks.json')
RAG_EMBEDDINGS_PATH: str = os.path.join(os.path.dirname(__file__), '..', 'rag', 'embeddings_f32.bin')

# ---- Disease Database ---------------------------------------
DISEASES_DB_PATH: str = os.path.join(os.path.dirname(__file__), '..', 'diseases.json')

# ---- CORS ---------------------------------------------------
# In development, allow all origins. Restrict in production.
CORS_ORIGINS: list = os.getenv("CORS_ORIGINS", "*").split(",")

# ---- App ----------------------------------------------------
APP_NAME: str = "GREEN Agricultural Intelligence Platform"
APP_VERSION: str = "1.0.0"
DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
