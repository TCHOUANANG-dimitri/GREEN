# ============================================================
# GREEN App — FastAPI Application Entry Point
#
# Run the server:
#   cd backend
#   uvicorn main:app --reload --port 8000
#
# API docs available at: http://localhost:8000/docs
# ============================================================

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import APP_NAME, APP_VERSION, DEBUG
from database import engine, Base

# ---- Import routers -----------------------------------------
from routers import auth_router
from routers import dashboard_router   # Phase 3 — KPIs + trends
from routers import analysis_router    # Phase 3 — Analysis history + fiche terrain
from routers import drone_router       # Phase 4 legacy (kept for compat)
from routers import camera_router      # Phase MVP — Rover camera + dual inference
from routers import parcel_router      # Phase 5 — Parcel CRUD
from routers import chatbot_router     # Phase 6 — GreenBot RAG + Gemini API
from routers import weather_router     # Phase 6 — OpenWeatherMap proxy
from routers import diseases_router    # Disease reference database
from routers import esp32_router       # ESP32-CAM — proxy + découverte automatique

logger = logging.getLogger(__name__)

# ---- Create all database tables ----------------------------
Base.metadata.create_all(bind=engine)


def _warmup_models():
    """Load EfficientNet in a background thread."""
    import time
    import threading

    def load_efficientnet():
        try:
            from inference import get_model
            get_model()
            logger.info("[Warmup] EfficientNet ready.")
        except Exception as e:
            logger.error(f"[Warmup] EfficientNet FAILED to load: {e}")

    def load_rag():
        try:
            from routers.chatbot_router import _load_rag
            _load_rag()
            logger.info("[Warmup] RAG index ready.")
        except Exception as e:
            logger.error(f"[Warmup] RAG index FAILED to load: {e}")

    # Brief pause so the ASGI loop finishes binding before we hit the CPU hard
    time.sleep(1)
    logger.info("[Warmup] Loading EfficientNet in background...")

    t1 = threading.Thread(target=load_efficientnet, daemon=True)
    t1.start()
    t1.join()

    # RAG is lighter — load it after the heavy models
    load_rag()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan: runs startup logic then yields control to the server.
    Models are loaded lazily on their first request so the server
    starts accepting requests immediately without hanging the ASGI event loop.
    """
    import threading
    logger.info("[Startup] GREEN server ready — scheduling parallel AI warmup.")
    threading.Thread(target=_warmup_models, daemon=True).start()

    # ── ESP32-CAM : découverte au démarrage + healthcheck en arrière-plan ──
    from camera.discovery  import discover_esp32
    from camera.state      import camera_state
    from camera.healthcheck import camera_healthcheck_loop

    result = await discover_esp32()
    if result:
        provider, info = result
        await camera_state.attach(provider, info)
        logger.info("[Startup] ESP32-CAM découverte : %s @ %s", info.device, info.ip)
    else:
        logger.info("[Startup] Aucune ESP32-CAM trouvée au démarrage — surveillance active.")

    hc_task = asyncio.create_task(camera_healthcheck_loop())

    yield

    hc_task.cancel()
    logger.info("[Shutdown] GREEN server stopped.")


# ---- FastAPI App Instance -----------------------------------
app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Agricultural AI platform for Cameroonian agribusiness enterprises.",
    debug=DEBUG,
    lifespan=lifespan,
    docs_url="/docs" if DEBUG else None,
    redoc_url="/redoc" if DEBUG else None,
)

# ---- CORS Middleware ----------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Register API Routers -----------------------------------
app.include_router(auth_router.router)
app.include_router(dashboard_router.router)
app.include_router(analysis_router.router)
app.include_router(drone_router.router)
app.include_router(camera_router.router)
app.include_router(parcel_router.router)
app.include_router(chatbot_router.router)
app.include_router(weather_router.router)
app.include_router(diseases_router.router)
app.include_router(esp32_router.router)

# ---- Serve Frontend Static Files ----------------------------
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend')

# ---- HTML Page Routes ---------------------------------------
# Defined BEFORE the StaticFiles mount so FastAPI routes take priority.

@app.get("/", include_in_schema=False)
async def login_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/register", include_in_schema=False)
async def register_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "register.html"))


@app.get("/dashboard", include_in_schema=False)
async def dashboard_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "dashboard.html"))


@app.get("/drone", include_in_schema=False)
async def drone_page():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/camera")


@app.get("/camera", include_in_schema=False)
async def camera_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "camera.html"))


@app.get("/history", include_in_schema=False)
async def history_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "history.html"))


@app.get("/profile", include_in_schema=False)
async def profile_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "profile.html"))


@app.get("/settings", include_in_schema=False)
async def settings_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "settings.html"))


@app.get("/marketplace", include_in_schema=False)
async def marketplace_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "marketplace.html"))


@app.get("/chatbot", include_in_schema=False)
async def chatbot_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "chatbot.html"))


@app.get("/map", include_in_schema=False)
async def map_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "map.html"))


@app.get("/calendar", include_in_schema=False)
async def calendar_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "calendar.html"))


@app.get("/diseases", include_in_schema=False)
async def diseases_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "diseases.html"))


@app.get("/economics", include_in_schema=False)
async def economics_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "economics.html"))


@app.get("/benchmark", include_in_schema=False)
async def benchmark_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "benchmark.html"))


# ---- Health Check + Warmup status --------------------------
@app.get("/api/health", tags=["Health"])
async def health_check():
    """Returns server status and which models are already loaded."""
    from inference import _model as _eff_model
    from routers.chatbot_router import _chunks
    return {
        "status":            "ok",
        "app":               APP_NAME,
        "version":           APP_VERSION,
        "models": {
            "efficientnet":  "ready" if _eff_model  is not None else "lazy",
            "rag_index":     "ready" if len(_chunks) > 0             else "lazy",
        }
    }


# ---- Mount static assets ------------------------------------
app.mount(
    "/",
    StaticFiles(directory=FRONTEND_DIR, html=True),
    name="frontend"
)
