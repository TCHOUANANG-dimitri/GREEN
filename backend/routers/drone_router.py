# ============================================================
# GREEN App — Drone Router (Phase 4)
#
# Handles:
#   POST /api/drone/connect        → verify stream is reachable
#   POST /api/drone/capture        → grab a frame + run inference
#   POST /api/drone/upload         → analyse a user-uploaded image
#   GET  /api/drone/stream-url     → return the MJPEG stream URL
#
# The live video stream is served directly by the drone to the
# browser (img src = http://{ip}:8080/) — no proxying needed.
# The backend only fetches single frames for AI inference.
# ============================================================

import asyncio
import io
import os
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from models import User, DiseaseAnalysis
from auth import get_current_user
from config import DEFAULT_DRONE_IP, DEFAULT_DRONE_STREAM_PORT
# inference and yolo_inference imported lazily inside helpers.

logger = logging.getLogger(__name__)

# Dedicated 2-thread pool: one per model, run truly concurrently
_drone_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="drone_inf")

router = APIRouter(prefix="/api/drone", tags=["Drone"])

# Folder where captured frames are saved (relative to project root)
CAPTURES_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', 'frontend', 'assets', 'captures'
)
os.makedirs(CAPTURES_DIR, exist_ok=True)


# ============================================================
# HELPERS
# ============================================================

def _stream_url(ip: str, port: int = None) -> str:
    port = port or DEFAULT_DRONE_STREAM_PORT
    return f"http://{ip}:{port}/"


async def _check_stream(ip: str) -> bool:
    """
    Attempt a HEAD request to the drone's MJPEG endpoint.
    Returns True if the stream responds within 4 seconds.
    """
    url = _stream_url(ip)
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.head(url)
            return resp.status_code < 500
    except Exception:
        return False


async def _grab_frame(ip: str) -> bytes:
    """
    Download the first JPEG frame from an MJPEG stream.
    MJPEG boundaries look like:  --frame\r\nContent-Type: image/jpeg\r\n\r\n<data>\r\n
    We stream bytes until we have one complete JPEG (SOI…EOI markers).
    """
    url = _stream_url(ip)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            async with client.stream("GET", url) as response:
                buffer = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=16384):
                    buffer.extend(chunk)
                    # Look for complete JPEG: starts with FF D8, ends with FF D9
                    start = buffer.find(b'\xff\xd8')
                    end   = buffer.find(b'\xff\xd9', start + 2) if start != -1 else -1
                    if start != -1 and end != -1:
                        return bytes(buffer[start: end + 2])
                    # Safety: don't buffer more than 2 MB
                    if len(buffer) > 2 * 1024 * 1024:
                        break
    except Exception as exc:
        logger.error(f"Frame grab error from {ip}: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"Could not grab a frame from the drone stream at {url}. "
                   "Ensure the drone is connected and the IP is correct."
        )
    raise HTTPException(status_code=502, detail="No JPEG frame found in stream.")


def _save_capture(image_bytes: bytes, user_id: int) -> str:
    """Save a captured frame to disk and return the relative path."""
    filename = f"capture_{user_id}_{uuid.uuid4().hex[:8]}.jpg"
    filepath = os.path.join(CAPTURES_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(image_bytes)
    # Return path accessible from the frontend (/assets/captures/...)
    return f"/assets/captures/{filename}"


async def _run_both_models(image_bytes: bytes) -> tuple[dict, dict]:
    """Run EfficientNet + YOLO concurrently (same pattern as camera_router)."""
    from inference import predict
    from yolo_inference import predict_yolo

    loop = asyncio.get_event_loop()
    disease_result, yolo_result = await asyncio.gather(
        loop.run_in_executor(_drone_executor, predict, image_bytes),
        loop.run_in_executor(_drone_executor, predict_yolo, image_bytes),
    )
    return disease_result, yolo_result


def _build_and_save_analysis(
    db:           Session,
    current_user: User,
    disease:      dict,
    yolo:         dict,
    image_path:   Optional[str],
    source:       str,
    parcel_id:    Optional[int],
    latitude:     Optional[float],
    longitude:    Optional[float],
) -> DiseaseAnalysis:
    """Persist disease + pest inference results as a DiseaseAnalysis row."""
    fiche = {
        "disease_id":   disease["detected_disease"],
        "disease_name": disease["disease_name"],
        "plant_type":   disease["plant_type"],
        "confidence":   round(disease["confidence"] * 100, 1),
        "severity":     disease["severity"],
        "top3":         disease["top3"],
        "pest": {
            "pest_id":    yolo.get("detected_pest"),
            "pest_name":  yolo.get("pest_name"),
            "confidence": round((yolo.get("confidence") or 0) * 100, 1),
            "severity":   yolo.get("severity"),
            "bboxes":     yolo.get("bboxes", []),
            "available":  yolo.get("available", False),
        },
        "source":       source,
        "latitude":     latitude,
        "longitude":    longitude,
        "parcel_id":    parcel_id,
        "generated_at": datetime.utcnow().isoformat(),
    }

    analysis = DiseaseAnalysis(
        user_id          = current_user.id,
        parcel_id        = parcel_id,
        source           = source,
        image_path       = image_path,
        detected_disease = disease["detected_disease"],
        disease_name     = disease["disease_name"],
        confidence       = disease["confidence"],
        severity         = disease["severity"],
        plant_type       = disease["plant_type"],
        pest_detected    = yolo.get("detected_pest"),
        pest_name        = yolo.get("pest_name"),
        pest_confidence  = yolo.get("confidence"),
        pest_severity    = yolo.get("severity"),
        latitude         = latitude,
        longitude        = longitude,
        fiche_terrain    = fiche,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


# ============================================================
# POST /api/drone/connect
# ============================================================
@router.post("/connect", summary="Verify drone stream is reachable")
async def connect_drone(
    payload:      dict,
    current_user: User = Depends(get_current_user),
):
    """
    Check that the MJPEG stream at http://{ip}:8080/ responds.
    Returns the stream URL so the frontend can set img.src directly.
    """
    ip = payload.get("ip", DEFAULT_DRONE_IP).strip()
    reachable = await _check_stream(ip)

    if not reachable:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach drone stream at {_stream_url(ip)}. "
                   "Check that the drone WiFi is connected and the IP is correct."
        )

    return {
        "success":    True,
        "ip":         ip,
        "stream_url": _stream_url(ip),
        "message":    f"Drone connected at {ip}",
    }


# ============================================================
# POST /api/drone/capture
# ============================================================
@router.post("/capture", summary="Capture a frame and run disease inference")
async def capture_and_analyze(
    payload:      dict,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """
    1. Grabs one JPEG frame from the MJPEG stream.
    2. Runs EfficientNet inference on the frame.
    3. Saves the frame to disk.
    4. Persists the DiseaseAnalysis row (with fiche terrain).
    5. Returns the full result including the fiche terrain.
    """
    ip        = payload.get("ip", DEFAULT_DRONE_IP).strip()
    parcel_id = payload.get("parcel_id")
    latitude  = payload.get("latitude")
    longitude = payload.get("longitude")

    image_bytes    = await _grab_frame(ip)
    disease, yolo  = await _run_both_models(image_bytes)
    image_path     = _save_capture(image_bytes, current_user.id)
    analysis       = _build_and_save_analysis(
        db, current_user, disease, yolo, image_path,
        source="drone", parcel_id=parcel_id,
        latitude=latitude, longitude=longitude,
    )

    return {
        "success":       True,
        "analysis_id":   analysis.id,
        "image_path":    image_path,
        "disease":       disease,
        "pest":          yolo,
        "fiche_terrain": analysis.fiche_terrain,
    }


# ============================================================
# POST /api/drone/upload
# ============================================================
@router.post("/upload", summary="Upload an image file for disease analysis")
async def upload_and_analyze(
    file:         UploadFile = File(...),
    parcel_id:    Optional[int]   = Form(None),
    latitude:     Optional[float] = Form(None),
    longitude:    Optional[float] = Form(None),
    db:           Session         = Depends(get_db),
    current_user: User            = Depends(get_current_user),
):
    """
    Upload a JPG/PNG image from disk and run disease inference.
    Same pipeline as /capture but source = "upload".
    """
    # Validate content type
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Only image files are accepted.")

    image_bytes = await file.read()
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large. Maximum 10 MB.")

    disease, yolo = await _run_both_models(image_bytes)
    image_path    = _save_capture(image_bytes, current_user.id)
    analysis      = _build_and_save_analysis(
        db, current_user, disease, yolo, image_path,
        source="upload", parcel_id=parcel_id,
        latitude=latitude, longitude=longitude,
    )

    return {
        "success":       True,
        "analysis_id":   analysis.id,
        "image_path":    image_path,
        "disease":       disease,
        "pest":          yolo,
        "fiche_terrain": analysis.fiche_terrain,
    }


# ============================================================
# GET /api/drone/stream-url
# ============================================================
@router.get("/stream-url", summary="Get the MJPEG stream URL for a given IP")
def get_stream_url(
    ip:           str  = DEFAULT_DRONE_IP,
    current_user: User = Depends(get_current_user),
):
    """Returns the stream URL so the frontend can construct the img src."""
    return {"stream_url": _stream_url(ip.strip()), "ip": ip.strip()}
