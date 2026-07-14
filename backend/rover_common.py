# ============================================================
# GREEN App — Rover / Drone shared logic
# MJPEG stream check, frame grab, disease inference, fiche build.
# ============================================================

import asyncio
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, Tuple

import httpx
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from config import DEFAULT_DRONE_IP, DEFAULT_DRONE_STREAM_PORT, DISEASES_DB_PATH
from inference import CLASS_FR_NAMES, predict
from models import DiseaseAnalysis, User

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rover_inf")

CAPTURES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "frontend", "assets", "captures"
)
os.makedirs(CAPTURES_DIR, exist_ok=True)

# Map EfficientNet class labels → diseases.json entry ids
CLASS_TO_DISEASE_ID = {
    "Cassava_Mosaic":     "cassava-mosaic",
    "Corn_Brown_Spots":   "leaf-spot-fungi",
    "Corn_Healthy":       "healthy",
    "Corn_Leaf_Blight":   "blight-disease",
    "Corn_Mildew":        "powdery-mildew",
    "Corn_Streak":        "maize-streak",
    "Corn_Stripe":        "maize-streak-virus",
    "Corn_Yellowing":     "leaf-spot-fungi",
    "Tomato_Brown_Spots": "early-blight",
    "Tomato_Blight_Leaf": "early-blight",
    "Tomato_Healthy":     "healthy",
}

UNCERTAIN_CONFIDENCE_PCT = 70.0


def parse_ip_port(payload: dict) -> Tuple[str, int]:
    ip = (payload.get("ip") or DEFAULT_DRONE_IP).strip()
    try:
        port = int(payload.get("port") or DEFAULT_DRONE_STREAM_PORT)
    except (TypeError, ValueError):
        port = DEFAULT_DRONE_STREAM_PORT
    return ip, port


def stream_url(ip: str, port: int = None) -> str:
    port = port or DEFAULT_DRONE_STREAM_PORT
    return f"http://{ip}:{port}/"


async def check_stream(ip: str, port: int = None) -> bool:
    """Verify MJPEG endpoint responds (GET with partial read; HEAD is unreliable)."""
    url = stream_url(ip, port)
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            async with client.stream("GET", url) as response:
                if response.status_code >= 500:
                    return False
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    if chunk:
                        return True
                return response.status_code < 400
    except Exception:
        return False


async def grab_frame(ip: str, port: int = None) -> bytes:
    """Download the first complete JPEG from an MJPEG stream."""
    url = stream_url(ip, port)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            async with client.stream("GET", url) as response:
                buffer = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=16384):
                    buffer.extend(chunk)
                    start = buffer.find(b"\xff\xd8")
                    end = buffer.find(b"\xff\xd9", start + 2) if start != -1 else -1
                    if start != -1 and end != -1:
                        return bytes(buffer[start : end + 2])
                    if len(buffer) > 2 * 1024 * 1024:
                        break
    except Exception as exc:
        logger.error(f"Frame grab error from {url}: {exc}")
        raise HTTPException(
            status_code=502,
            detail=(
                f"Could not grab a frame from the stream at {url}. "
                "Ensure the drone is connected and the IP/port are correct."
            ),
        )
    raise HTTPException(status_code=502, detail="No JPEG frame found in stream.")


def save_capture(image_bytes: bytes, user_id: int) -> str:
    filename = f"capture_{user_id}_{uuid.uuid4().hex[:8]}.jpg"
    filepath = os.path.join(CAPTURES_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(image_bytes)
    return f"/assets/captures/{filename}"


async def run_disease_model(image_bytes: bytes) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, predict, image_bytes)


def load_diseases_db() -> dict:
    try:
        with open(DISEASES_DB_PATH, encoding="utf-8") as f:
            return {d["id"]: d for d in json.load(f)}
    except Exception:
        return {}


def build_winner(disease: dict, diseases_db: dict) -> dict:
    """Build the fiche.winner object expected by camera.html."""
    class_raw = disease.get("class_raw") or ""
    detected = disease.get("detected_disease") or "healthy"
    confidence_pct = round((disease.get("confidence") or 0) * 100, 1)

    # low_confidence = True quand sous le seuil ; le nom est quand même retourné.
    low_confidence = confidence_pct < UNCERTAIN_CONFIDENCE_PCT

    disease_id = CLASS_TO_DISEASE_ID.get(class_raw, detected.lower().replace("_", "-"))
    info = diseases_db.get(disease_id, {})
    fr_name = CLASS_FR_NAMES.get(class_raw) or info.get("name") or disease.get("disease_name")

    if detected == "healthy":
        return {
            "type":            "healthy",
            "name":            disease.get("disease_name"),
            "fr_name":         fr_name,
            "plant_type":      disease.get("plant_type"),
            "confidence":      confidence_pct,
            "severity":        disease.get("severity") or "none",
            "recommendations": info.get("actions", []),
            "low_confidence":  low_confidence,
        }

    return {
        "type":            "disease",
        "name":            disease.get("disease_name"),
        "fr_name":         fr_name,
        "scientific_name": info.get("scientificName"),
        "plant_type":      disease.get("plant_type"),
        "confidence":      confidence_pct,
        "severity":        disease.get("severity"),
        "symptoms":        info.get("symptoms", []),
        "recommendations": info.get("actions", []),
        "affected_plants": info.get("affectedPlants", []),
        "characteristics": info.get("description", ""),
        "low_confidence":  low_confidence,
    }


def build_fiche(
    disease: dict,
    source: str,
    parcel_id: Optional[int],
    latitude: Optional[float],
    longitude: Optional[float],
) -> dict:
    diseases_db = load_diseases_db()
    winner = build_winner(disease, diseases_db)
    disease_id = CLASS_TO_DISEASE_ID.get(
        disease.get("class_raw", ""),
        (disease.get("detected_disease") or "healthy").lower().replace("_", "-"),
    )
    info = diseases_db.get(disease_id, {})

    return {
        "winner":         winner,
        "disease_id":     disease.get("detected_disease"),
        "disease_name":   disease.get("disease_name"),
        "scientific_name": info.get("scientificName"),
        "plant_type":     disease.get("plant_type"),
        "confidence":     round((disease.get("confidence") or 0) * 100, 1),
        "severity":       disease.get("severity"),
        "top3":           disease.get("top3", []),
        "symptoms":       info.get("symptoms", []),
        "recommendations": info.get("actions", []),
        "affected_plants": info.get("affectedPlants", []),
        "source":         source,
        "latitude":       latitude,
        "longitude":      longitude,
        "parcel_id":      parcel_id,
        "generated_at":   datetime.utcnow().isoformat(),
    }


def save_analysis(
    db: Session,
    current_user: User,
    disease: dict,
    image_path: Optional[str],
    source: str,
    parcel_id: Optional[int],
    latitude: Optional[float],
    longitude: Optional[float],
) -> DiseaseAnalysis:
    fiche = build_fiche(disease, source, parcel_id, latitude, longitude)

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
        latitude         = latitude,
        longitude        = longitude,
        fiche_terrain    = fiche,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


async def analyze_image_bytes(
    image_bytes: bytes,
    db: Session,
    current_user: User,
    source: str,
    parcel_id: Optional[int] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    save_image: bool = True,
) -> dict:
    disease = await run_disease_model(image_bytes)
    image_path = save_capture(image_bytes, current_user.id) if save_image else None
    analysis = save_analysis(
        db, current_user, disease, image_path, source,
        parcel_id, latitude, longitude,
    )
    return {
        "success":       True,
        "analysis_id":   analysis.id,
        "image_path":    image_path,
        "disease":       disease,
        "fiche_terrain": analysis.fiche_terrain,
    }


async def validate_upload(file: UploadFile) -> bytes:
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Only image files are accepted.")
    image_bytes = await file.read()
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large. Maximum 10 MB.")
    return image_bytes
