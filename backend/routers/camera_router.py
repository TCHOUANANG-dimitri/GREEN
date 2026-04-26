# ============================================================
# GREEN App — Rover Camera Router (Phase MVP)
#
# Two acquisition modes:
#   Mode A — IP Stream  : rover streams MJPEG over WiFi/LAN.
#   Mode B — Frame POST : browser captures a frame locally.
#
# Two AI models run on every image:
#   1. EfficientNet-B0  (best_efficientnet.pth) — plant disease
#      classification: 11 classes
#        Cassava mosaic
#        Corn brown spots | Corn healthy | Corn leaf blight
#        Corn mildew | Corn streak | Corn stripe | Corn yellowing
#        Tomato Brown Spots | Tomato blight leaf | Tomato healthy
#   2. YOLOv8 (best.pt) — pest detection: 2 classes
#        Criquet | papillon de nuit
#
# Winner logic (dual-threshold + margin arbitration):
#   1. Each model validates its score ≥ WINNER_THRESHOLD (0.50).
#   2. If both pass → compare scores:
#        margin ≥ MARGIN_THRESHOLD (0.10) → higher score wins
#        margin < MARGIN_THRESHOLD         → "uncertain" (too close)
#   3. Only one passes → that model wins.
#   4. Neither passes → "uncertain".
# ============================================================

import asyncio
import io
import json
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
from config import DEFAULT_CAMERA_IP, DEFAULT_CAMERA_PORT, GEMINI_API_KEY, GEMINI_MODEL, DISEASES_DB_PATH

# inference and yolo_inference are imported lazily inside _run_both_models()
# so that torch/ultralytics never block the server startup.

logger = logging.getLogger(__name__)

# Dedicated thread pool for AI inference.
# 2 workers = one thread per model so both run truly in parallel.
# torch/ultralytics release the GIL during C ops, so actual CPU overlap occurs.
_inference_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="inference")

router = APIRouter(prefix="/api/camera", tags=["Camera"])

# Where captured frames are saved (served as static files from frontend/)
CAPTURES_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', 'frontend', 'assets', 'captures'
)
os.makedirs(CAPTURES_DIR, exist_ok=True)

# ============================================================
# DISEASES DATABASE  (diseases.json — loaded once at startup)
# ============================================================
_DISEASE_DB_BY_ALIAS: dict[str, dict] = {}   # alias (lowercase) → entry

def _load_disease_db() -> None:
    """Load diseases.json and index entries by their aliases for fast lookup."""
    global _DISEASE_DB_BY_ALIAS
    if not os.path.exists(DISEASES_DB_PATH):
        logger.warning(f"[Camera] diseases.json not found at {DISEASES_DB_PATH}")
        return
    try:
        with open(DISEASES_DB_PATH, encoding="utf-8") as f:
            entries = json.load(f)
        for entry in entries:
            for alias in entry.get("aliases", []):
                _DISEASE_DB_BY_ALIAS[alias.lower()] = entry
            # Also index by id
            _DISEASE_DB_BY_ALIAS[entry["id"].lower()] = entry
        logger.info(f"[Camera] Disease DB loaded — {len(entries)} entries")
    except Exception as exc:
        logger.error(f"[Camera] Failed to load diseases.json: {exc}")

_load_disease_db()

# Mapping: EfficientNet class name → diseases.json alias for lookup
# (used to supplement enrichment from diseases.json if present)
_CLASS_TO_DB_ALIAS: dict[str, str] = {
    "Cassava_Mosaic":     "Cassava Mosaic",
    "Corn_Brown_Spots":   "Cercospora Leaf Spot",
    "Corn_Leaf_Blight":   "Blight",
    "Corn_Mildew":        "Mildew",
    "Corn_Streak":        "Streak",
    "Corn_Stripe":        "Stripe",
    "Corn_Yellowing":     "Yellowing",
    "Tomato_Brown_Spots": "Alternaria Blight",
    "Tomato_Blight_Leaf": "Blight",
}

# ============================================================
# DISEASE ENRICHMENT  (EfficientNet class → detailed info)
# Aligned with the 11 real classes from training:
#   Cassava mosaic | Corn × 7 | Tomato × 2 | Healthy × 2
# ============================================================
DISEASE_ENRICHMENT: dict[str, dict] = {
    # ── MANIOC ────────────────────────────────────────────────
    "Cassava_Mosaic": {
        "fr_name": "Mosaïque du manioc (CMD)",
        "characteristics": (
            "Zones chlorotiques et vertes en mosaïque sur les feuilles, réduction de la "
            "taille des feuilles et distorsion des tiges. "
            "Transmise par l'aleurode Bemisia tabaci. Peut réduire le rendement jusqu'à 80 %."
        ),
        "recommendations": [
            "Utiliser des boutures saines issues de plants certifiés exempts de virus",
            "Lutter contre les aleurodes (vecteurs) avec des insecticides systémiques",
            "Retirer et détruire tous les plants infectés du champ",
            "Adopter des variétés résistantes homologuées (ex. TMS 30572)",
        ],
    },

    # ── MAÏS ──────────────────────────────────────────────────
    "Corn_Brown_Spots": {
        "fr_name": "Taches brunes du maïs (Cercospora)",
        "characteristics": (
            "Petites taches brun-rouille à centre grisâtre sur les feuilles, "
            "entourées d'un halo jaune-vert. Progressent de bas en haut de la plante. "
            "Favorisées par une humidité élevée et des températures modérées."
        ),
        "recommendations": [
            "Traitement fongicide systémique (strobilurine + triazole en co-formulation)",
            "Améliorer la circulation d'air entre les rangs (espacement suffisant)",
            "Éviter l'irrigation par aspersion en fin d'après-midi",
            "Incorporer les résidus infectés dans le sol après récolte",
        ],
    },
    "Corn_Leaf_Blight": {
        "fr_name": "Brûlure foliaire du maïs (Helminthosporiose)",
        "characteristics": (
            "Grandes lésions elliptiques vert-grisâtre à brun pouvant atteindre 15 cm, "
            "donnant un aspect « brûlé » aux feuilles. "
            "Peut causer jusqu'à 50 % de pertes de rendement en cas d'épidémie."
        ),
        "recommendations": [
            "Appliquer des fongicides préventifs avant l'apparition des symptômes",
            "Adopter des variétés résistantes sélectionnées pour la zone",
            "Assurer une rotation des cultures avec légumineuses ou tubercules",
            "Éviter les irrigations tardives qui maintiennent l'humidité foliaire la nuit",
        ],
    },
    "Corn_Mildew": {
        "fr_name": "Mildiou du maïs",
        "characteristics": (
            "Dépôts blanchâtres à grisâtres en poudre fine sur les deux faces des feuilles. "
            "Provoque un jaunissement puis un dessèchement des tissus foliaires. "
            "Se développe par temps chaud avec de fortes variations d'humidité."
        ),
        "recommendations": [
            "Appliquer un fongicide systémique (métalaxyl, mancozèbe) dès les premiers signes",
            "Semer des variétés tolérantes disponibles localement",
            "Éviter un excès d'azote qui favorise la croissance végétative et la sensibilité",
            "Détruire les résidus de récolte infectés pour réduire l'inoculum",
        ],
    },
    "Corn_Streak": {
        "fr_name": "Stries du maïs (MSV — Maize Streak Virus)",
        "characteristics": (
            "Stries jaunes étroites parallèles aux nervures sur les feuilles jeunes, "
            "déformation et nanisme des plants sévèrement touchés. "
            "Transmis par les cicadelles (Cicadulina spp.) — vecteur principal en Afrique."
        ),
        "recommendations": [
            "Traiter les cicadelles vecteurs avec des insecticides systémiques (imidaclopride)",
            "Utiliser des variétés résistantes au MSV adaptées au Cameroun",
            "Éliminer les plants très atteints pour limiter la propagation",
            "Effectuer les semis en début de saison des pluies pour éviter les pics de vecteurs",
        ],
    },
    "Corn_Stripe": {
        "fr_name": "Rayures du maïs",
        "characteristics": (
            "Rayures longitudinales chlorotiques alternant jaune et vert sur les feuilles, "
            "souvent liées à des carences nutritionnelles (zinc, magnésium) ou à des virus. "
            "Peut aussi indiquer une phytotoxicité herbicide."
        ),
        "recommendations": [
            "Effectuer une analyse foliaire pour confirmer ou infirmer une carence minérale",
            "Apporter un engrais foliaire à base de zinc ou magnésium si carence confirmée",
            "Vérifier les herbicides utilisés — certains induisent des symptômes similaires",
            "Surveiller l'évolution : si la cause est virale, arracher les plants suspects",
        ],
    },
    "Corn_Yellowing": {
        "fr_name": "Jaunissement du maïs",
        "characteristics": (
            "Jaunissement généralisé des feuilles, débutant souvent par les feuilles âgées "
            "puis progressant vers le haut. Peut résulter d'une carence en azote, "
            "d'un excès d'eau, d'une infection virale ou d'une attaque de ravageurs racinaires."
        ),
        "recommendations": [
            "Vérifier le drainage — un sol saturé en eau provoque une carence en azote apparente",
            "Apporter un engrais azoté (urée, sulfate d'ammonium) si carence nutritionnelle",
            "Inspecter les racines pour détecter d'éventuelles larves de foreurs",
            "Consulter un agronome si le jaunissement persiste malgré les corrections",
        ],
    },

    # ── TOMATE ────────────────────────────────────────────────
    "Tomato_Brown_Spots": {
        "fr_name": "Taches brunes de la tomate (Alternariose)",
        "characteristics": (
            "Taches brunes avec anneaux concentriques (aspect « cible ») entourées d'un halo jaune, "
            "sur les feuilles âgées en bas de la plante, puis progression vers le haut. "
            "Peut défolier complètement une plante non traitée."
        ),
        "recommendations": [
            "Traitement fongicide de contact (chlorothalonil) ou systémique (mancozèbe)",
            "Éliminer et brûler les feuilles basales infectées dès détection",
            "Éviter les arrosages par-dessus le feuillage (préférer le goutte-à-goutte)",
            "Assurer une rotation triennale — ne pas replanter tomate ou solanacées avant 3 ans",
        ],
    },
    "Tomato_Blight_Leaf": {
        "fr_name": "Brûlure foliaire de la tomate (Mildiou)",
        "characteristics": (
            "Taches vert-foncé à brunes huileuses sur les feuilles, tiges et fruits, "
            "avec un duvet blanc sur la face inférieure par temps humide. "
            "Progresse très rapidement en conditions fraîches et humides — peut ravager toute une parcelle."
        ),
        "recommendations": [
            "Appliquer un fongicide systémique (métalaxyl + mancozèbe) en préventif",
            "Retirer et détruire immédiatement toute partie infectée",
            "Améliorer la ventilation entre les plants (taille, écartement)",
            "Éviter l'arrosage par aspersion et irriguer de préférence le matin",
        ],
    },

    # ── SAINES — pas d'enrichissement de maladie ─────────────
    "Corn_Healthy":   None,
    "Tomato_Healthy": None,
}

# A model must reach WINNER_THRESHOLD to be considered valid.
WINNER_THRESHOLD = 0.20


# ============================================================
# ENRICHMENT HELPER
# Merges DISEASE_ENRICHMENT (inline expert data) with diseases.json
# (scientific name, affected plants, symptoms). Falls back to Gemini
# for classes not covered by either source.
# ============================================================

def _get_disease_info(class_raw: str) -> dict:
    """
    Return enriched disease info for the given EfficientNet class name.
    Priority: DISEASE_ENRICHMENT → diseases.json → Gemini (async wrapper handled
    by caller for truly unknown classes). Returns dict with all relevant fields.
    """
    inline = DISEASE_ENRICHMENT.get(class_raw)
    if inline is None:
        # Healthy classes
        return {}
    enrich: dict = dict(inline) if inline else {}

    # Supplement with diseases.json entry if available
    alias = _CLASS_TO_DB_ALIAS.get(class_raw, "")
    db_entry = _DISEASE_DB_BY_ALIAS.get(alias.lower()) if alias else None
    if db_entry:
        enrich.setdefault("scientific_name", db_entry.get("scientificName", ""))
        enrich.setdefault("affected_plants", db_entry.get("affectedPlants", []))
        # Merge symptoms: db has a list, inline may have them embedded in characteristics
        if db_entry.get("symptoms"):
            enrich["symptoms"] = db_entry["symptoms"]
        # Merge actions from db as extra recommendations
        extra_actions = [a for a in db_entry.get("actions", [])
                         if a not in enrich.get("recommendations", [])]
        enrich["recommendations"] = enrich.get("recommendations", []) + extra_actions

    return enrich


# In-memory cache: class_raw → enrichment dict (persists for the server lifetime).
# Avoids re-calling Gemini on every real-time loop tick for the same class.
_gemini_cache: dict[str, dict] = {}
# Set to True after a quota error to stop hammering the API until server restarts.
_ai_quota_exceeded: bool = False


async def _gemini_research_disease(class_raw: str) -> dict:
    """
    Research an unknown disease/pest class using Google Gemini.
    Results cached in _gemini_cache — API called at most once per class per session.
    """
    global _ai_quota_exceeded

    if class_raw in _gemini_cache:
        return _gemini_cache[class_raw]

    fallback = {"fr_name": class_raw.replace("_", " "),
                "characteristics": "", "recommendations": []}

    api_key = os.environ.get("GEMINI_API_KEY", "") or GEMINI_API_KEY
    if not api_key or _ai_quota_exceeded:
        _gemini_cache[class_raw] = fallback
        return fallback

    prompt = (
        f"Tu es un expert agronome. Donne-moi des informations structurées sur cette "
        f"maladie ou ravageur de plante : '{class_raw}'.\n"
        "Réponds UNIQUEMENT avec un objet JSON valide (sans markdown, sans texte avant/après) :\n"
        '{ "fr_name": "nom français", "scientific_name": "nom scientifique", '
        '"affected_plants": ["plante1", "plante2"], '
        '"symptoms": ["symptôme1", "symptôme2", "symptôme3"], '
        '"characteristics": "description courte (2-3 phrases)", '
        '"recommendations": ["action1", "action2", "action3", "action4"] }'
    )

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config=types.GenerateContentConfig(
                system_instruction="Tu es un expert agronome. Réponds uniquement en JSON valide.",
                max_output_tokens=512,
                temperature=0.3,
            ),
        )
        raw = response.text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        _gemini_cache[class_raw] = result
        return result

    except Exception as exc:
        err_str = str(exc)
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
            _ai_quota_exceeded = True
            logger.warning("[Camera] Gemini quota exceeded — disease research disabled for this session.")
        elif "403" in err_str or "PERMISSION_DENIED" in err_str:
            _ai_quota_exceeded = True
            logger.warning("[Camera] Gemini API key invalid — disease research disabled.")
        else:
            logger.error(f"[Camera] Disease research failed for '{class_raw}': {exc}")
        _gemini_cache[class_raw] = fallback
        return fallback


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _stream_url(ip: str, port: int = None) -> str:
    port = port or DEFAULT_CAMERA_PORT
    return f"http://{ip}:{port}/"


async def _check_stream(ip: str) -> bool:
    """Try a HEAD request to the MJPEG stream. Returns True if reachable."""
    url = _stream_url(ip)
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.head(url)
            return resp.status_code < 500
    except Exception:
        return False


async def _grab_frame_from_stream(ip: str) -> bytes:
    """
    Stream bytes from the MJPEG endpoint until one complete JPEG
    (SOI 0xFF 0xD8 … EOI 0xFF 0xD9) is extracted.
    """
    url = _stream_url(ip)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            async with client.stream("GET", url) as response:
                buffer = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=16384):
                    buffer.extend(chunk)
                    start = buffer.find(b'\xff\xd8')
                    end   = buffer.find(b'\xff\xd9', start + 2) if start != -1 else -1
                    if start != -1 and end != -1:
                        return bytes(buffer[start: end + 2])
                    if len(buffer) > 3 * 1024 * 1024:
                        break
    except Exception as exc:
        logger.error(f"Frame grab error from {ip}: {exc}")
        raise HTTPException(
            status_code=502,
            detail=(
                f"Could not grab a frame from {url}. "
                "Check that the rover is connected and the IP is correct."
            )
        )
    raise HTTPException(status_code=502, detail="No JPEG frame found in camera stream.")


def _save_frame(image_bytes: bytes, user_id: int) -> str:
    """Save image bytes and return a frontend-accessible path."""
    filename = f"frame_{user_id}_{uuid.uuid4().hex[:8]}.jpg"
    filepath = os.path.join(CAPTURES_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(image_bytes)
    return f"/assets/captures/{filename}"


async def _run_both_models(image_bytes: bytes) -> tuple[dict, dict]:
    """
    Run EfficientNet disease inference AND YOLO pest inference concurrently.

    Both tasks are dispatched to _inference_executor (2 threads). torch and
    ultralytics release the GIL during their C/native forward passes, so the
    two models genuinely overlap on the CPU.  Wall-clock time ≈ max(T_eff, T_yolo)
    instead of T_eff + T_yolo — roughly 40–50 % faster on CPU.
    """
    from inference import predict             # lazy — torch loaded here
    from yolo_inference import predict_yolo  # lazy — ultralytics loaded here

    loop = asyncio.get_event_loop()
    disease_result, yolo_result = await asyncio.gather(
        loop.run_in_executor(_inference_executor, predict, image_bytes),
        loop.run_in_executor(_inference_executor, predict_yolo, image_bytes),
    )
    return disease_result, yolo_result


def _determine_winner(disease: dict, yolo: dict,
                      disease_enrich: Optional[dict] = None) -> dict:
    """
    Arbitration between EfficientNet and YOLO.
    Picks the model with the absolute highest confidence score.
    If the best confidence is truly low (< 20%), returns 'uncertain'.
    """
    d_conf     = disease.get("confidence", 0.0)   # 0–1
    y_conf     = yolo.get("confidence") or 0.0    # 0–1
    is_healthy = disease.get("detected_disease") == "healthy"
    y_has_pest = (yolo.get("detected_pest") is not None
                  and yolo.get("available", False)
                  and y_conf > 0.0)

    best_conf = max(d_conf, y_conf)

    # 1. Garbage image / too low confidence
    if best_conf < WINNER_THRESHOLD:
        return {
            "type":       "uncertain",
            "confidence": round(best_conf * 100, 1),
            "message":    "Image non reconnue ou confiance trop faible (< 20%).",
        }

    # 2. Decide winner based on highest conf
    if y_has_pest and y_conf > d_conf:
        winner_type = "pest"
    else:
        winner_type = "healthy" if is_healthy else "disease"

    # Build winner detail dict
    if winner_type == "disease":
        enrich = disease_enrich or _get_disease_info(disease.get("class_raw", ""))
        return {
            "type":            "disease",
            "confidence":      round(d_conf * 100, 1),
            "class_raw":       disease.get("class_raw", ""),
            "name":            disease.get("disease_name", ""),
            "fr_name":         enrich.get("fr_name", disease.get("disease_name", "")),
            "scientific_name": enrich.get("scientific_name", ""),
            "affected_plants": enrich.get("affected_plants", []),
            "plant_type":      disease.get("plant_type", ""),
            "severity":        disease.get("severity", "low"),
            "symptoms":        enrich.get("symptoms", []),
            "characteristics": enrich.get("characteristics", ""),
            "recommendations": enrich.get("recommendations", []),
        }

    if winner_type == "pest":
        enrich = yolo.get("enrichment") or {}
        return {
            "type":            "pest",
            "confidence":      round(y_conf * 100, 1),
            "name":            yolo.get("detected_pest", ""),
            "fr_name":         enrich.get("fr_name", yolo.get("pest_name", "")),
            "severity":        yolo.get("severity", "low"),
            "characteristics": enrich.get("characteristics", ""),
            "emitter_signal": {
                "frequency": enrich.get("emitter_frequency", ""),
                "message":   enrich.get("emitter_message", ""),
            },
            "recommendations": enrich.get("recommendations", []),
        }

    if winner_type == "healthy":
        return {
            "type":       "healthy",
            "confidence": round(d_conf * 100, 1),
            "name":       "Healthy Plant",
            "fr_name":    "Plante saine",
            "recommendations": [
                "Continue regular observation of your field",
                "Maintain good field hygiene (weeding, residue management)",
                "Ensure adequate water and nutrient supply suited to the crop",
            ],
        }

    # uncertain — confidence below 50 % on both models
    best_conf = max(d_conf, y_conf)
    return {
        "type":       "uncertain",
        "confidence": round(best_conf * 100, 1),
        "message":    "Insufficient confidence (< 70%). Please take another image.",
    }


async def _build_fiche(disease: dict, yolo: dict, source: str,
                       latitude: Optional[float], longitude: Optional[float]) -> dict:
    """Build the enriched fiche terrain from both model results."""
    # Pre-compute disease enrichment (may call Gemini for unknown classes)
    class_raw = disease.get("class_raw", "")
    disease_enrich = _get_disease_info(class_raw)
    if not disease_enrich and class_raw and "Healthy" not in class_raw:
        disease_enrich = await _gemini_research_disease(class_raw)

    winner = _determine_winner(disease, yolo, disease_enrich)

    return {
        "winner": winner,
        "disease": {
            "disease_id":   disease.get("detected_disease"),
            "disease_name": disease.get("disease_name"),
            "plant_type":   disease.get("plant_type"),
            "confidence":   round(disease.get("confidence", 0) * 100, 1),
            "severity":     disease.get("severity"),
            "top3":         disease.get("top3", []),
        },
        "pest": {
            "pest_id":    yolo.get("detected_pest"),
            "pest_name":  yolo.get("pest_name"),
            "confidence": round((yolo.get("confidence") or 0) * 100, 1),
            "severity":   yolo.get("severity"),
            "top3":       yolo.get("top3", []),
            "available":  yolo.get("available", False),
            "bboxes":     yolo.get("bboxes", []),
        },
        "source":       source,
        "latitude":     latitude,
        "longitude":    longitude,
        "generated_at": datetime.utcnow().isoformat(),
    }


async def _persist(
    db: Session,
    user: User,
    image_path: Optional[str],
    source: str,
    disease: dict,
    yolo: dict,
    parcel_id: Optional[int],
    latitude: Optional[float],
    longitude: Optional[float],
) -> DiseaseAnalysis:
    """Save both inference results + fiche terrain to the DB."""
    fiche = await _build_fiche(disease, yolo, source, latitude, longitude)

    analysis = DiseaseAnalysis(
        user_id          = user.id,
        parcel_id        = parcel_id,
        source           = source,
        image_path       = image_path,
        # Disease fields
        detected_disease = disease.get("detected_disease"),
        disease_name     = disease.get("disease_name"),
        confidence       = disease.get("confidence"),
        severity         = disease.get("severity"),
        plant_type       = disease.get("plant_type"),
        # Pest fields (YOLO)
        pest_detected    = yolo.get("detected_pest"),
        pest_name        = yolo.get("pest_name"),
        pest_confidence  = yolo.get("confidence"),
        pest_severity    = yolo.get("severity"),
        # Location
        latitude         = latitude,
        longitude        = longitude,
        # Fiche
        fiche_terrain    = fiche,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def _response(analysis: DiseaseAnalysis, disease: dict, yolo: dict) -> dict:
    """Build the standard API response for a completed analysis."""
    return {
        "success":       True,
        "analysis_id":   analysis.id,
        "image_path":    analysis.image_path,
        "disease":       disease,
        "pest":          yolo,
        "fiche_terrain": analysis.fiche_terrain,
    }


# ============================================================
# POST /api/camera/connect
# ============================================================
@router.post("/connect", summary="Verify rover camera stream is reachable")
async def connect_camera(
    payload:      dict,
    current_user: User = Depends(get_current_user),
):
    """
    Pings the MJPEG stream endpoint to check connectivity.
    Returns the stream_url to be set as <img>.src in the browser.
    """
    ip = payload.get("ip", DEFAULT_CAMERA_IP).strip()
    reachable = await _check_stream(ip)

    if not reachable:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Cannot reach camera stream at {_stream_url(ip)}. "
                "Make sure the rover is on the same network and the IP is correct."
            )
        )
    return {
        "success":    True,
        "ip":         ip,
        "stream_url": _stream_url(ip),
        "message":    f"Camera stream reachable at {ip}",
    }


# ============================================================
# POST /api/camera/capture
# ============================================================
@router.post("/capture", summary="Grab a frame from the IP stream and run inference")
async def capture_from_stream(
    payload:      dict,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """
    Mode A — IP Stream capture:
    Fetches one JPEG frame from the rover's MJPEG stream,
    runs both AI models, saves result and returns enriched fiche terrain.
    """
    ip        = payload.get("ip", DEFAULT_CAMERA_IP).strip()
    parcel_id = payload.get("parcel_id")
    latitude  = payload.get("latitude")
    longitude = payload.get("longitude")

    image_bytes        = await _grab_frame_from_stream(ip)
    disease, yolo      = await _run_both_models(image_bytes)
    image_path         = _save_frame(image_bytes, current_user.id)
    analysis           = await _persist(db, current_user, image_path, "camera",
                                        disease, yolo, parcel_id, latitude, longitude)
    return _response(analysis, disease, yolo)


# ============================================================
# POST /api/camera/analyze-frame
# ============================================================
@router.post("/analyze-frame", summary="Receive a browser-captured frame and run inference")
async def analyze_browser_frame(
    file:         UploadFile        = File(...),
    parcel_id:    Optional[int]     = Form(None),
    latitude:     Optional[float]   = Form(None),
    longitude:    Optional[float]   = Form(None),
    db:           Session           = Depends(get_db),
    current_user: User              = Depends(get_current_user),
):
    """
    Mode B — Browser / local webcam:
    Receives a JPEG blob captured by the browser via getUserMedia() + canvas.
    Runs both AI models and returns the combined enriched analysis.
    """
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Only image files are accepted.")

    image_bytes = await file.read()
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large. Maximum 10 MB.")

    disease, yolo = await _run_both_models(image_bytes)
    image_path    = _save_frame(image_bytes, current_user.id)
    analysis      = await _persist(db, current_user, image_path, "camera",
                                   disease, yolo, parcel_id, latitude, longitude)
    return _response(analysis, disease, yolo)


# ============================================================
# POST /api/camera/upload
# ============================================================
@router.post("/upload", summary="Upload a static image file for analysis")
async def upload_image(
    file:         UploadFile        = File(...),
    parcel_id:    Optional[int]     = Form(None),
    latitude:     Optional[float]   = Form(None),
    longitude:    Optional[float]   = Form(None),
    db:           Session           = Depends(get_db),
    current_user: User              = Depends(get_current_user),
):
    """Upload a JPG/PNG image from disk. Same inference pipeline, source = 'upload'."""
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Only image files are accepted.")

    image_bytes = await file.read()
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large. Maximum 10 MB.")

    disease, yolo = await _run_both_models(image_bytes)
    image_path    = _save_frame(image_bytes, current_user.id)
    analysis      = await _persist(db, current_user, image_path, "upload",
                                   disease, yolo, parcel_id, latitude, longitude)
    return _response(analysis, disease, yolo)


# ============================================================
# GET /api/camera/stream-url
# ============================================================
@router.get("/stream-url", summary="Build the MJPEG stream URL for a given IP")
def get_stream_url(
    ip:           str  = DEFAULT_CAMERA_IP,
    current_user: User = Depends(get_current_user),
):
    return {"stream_url": _stream_url(ip.strip()), "ip": ip.strip()}
