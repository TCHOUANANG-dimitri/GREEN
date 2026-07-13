# ============================================================
# GREEN App — Router ESP32-CAM
#
# Endpoints :
#   GET  /api/esp32/status      → état de la caméra active
#   GET  /api/esp32/info        → infos hardware (MAC, RSSI…)
#   GET  /api/esp32/health      → ping léger
#   POST /api/esp32/discover    → déclenche une re-découverte
#   POST /api/esp32/connect     → connexion manuelle par IP
#   POST /api/esp32/disconnect  → déconnecte la caméra active
#   GET  /api/esp32/stream      → proxy MJPEG (le frontend appelle ceci)
#   POST /api/esp32/capture     → capture + inférence IA
# ============================================================

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth      import get_current_user, decode_access_token
from database  import get_db
from models    import User
from camera.state     import camera_state
from camera.discovery import discover_esp32
from camera.esp32     import ESP32CameraProvider
from camera.provider  import CameraInfo
from rover_common     import analyze_image_bytes   # pipeline IA existant — non modifié

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/esp32", tags=["ESP32-CAM"])


# ── Schémas ─────────────────────────────────────────────────

class ConnectPayload(BaseModel):
    ip:   str
    port: Optional[int] = 80


# ── Helpers ─────────────────────────────────────────────────

def _require_camera():
    """Lève 503 si aucune caméra n'est connectée."""
    if not camera_state.connected or not camera_state.info:
        raise HTTPException(
            status_code=503,
            detail="Aucune caméra connectée. Appelez /api/esp32/discover d'abord.",
        )
    return camera_state.info, camera_state.provider


def _user_from_query_token(token: str, db: Session) -> User:
    """
    Valide un JWT passé en query string (?token=...).

    Utilisé uniquement par /stream : cet endpoint est consommé via une
    balise <img src="..."> côté navigateur, qui ne peut pas envoyer de
    header Authorization — le token doit donc voyager dans l'URL.
    """
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré.")

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == int(user_id)).first() if user_id else None
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Utilisateur invalide.")
    return user


# ── Endpoints ────────────────────────────────────────────────

@router.get("/status", summary="État de la caméra active")
async def get_status(current_user: User = Depends(get_current_user)):
    """
    Retourne l'état de connexion et les métadonnées de la caméra active.
    Si aucune caméra n'est connectée, `connected` vaut false.
    """
    return camera_state.to_dict()


@router.get("/info", summary="Infos hardware de l'ESP32-CAM")
async def get_info(current_user: User = Depends(get_current_user)):
    """
    Interroge GET /info sur l'ESP32-CAM pour récupérer MAC, RSSI, SSID, etc.
    Nécessite une caméra connectée.
    """
    info, provider = _require_camera()
    try:
        return await provider.get_info(info)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/health", summary="Ping léger de la caméra")
async def health(current_user: User = Depends(get_current_user)):
    """
    Vérifie rapidement que la caméra répond.
    Retourne `{"alive": true}` ou `{"alive": false}`.
    """
    if not camera_state.connected or not camera_state.info or not camera_state.provider:
        return {"alive": False, "reason": "not_connected"}

    alive = await camera_state.provider.is_alive(camera_state.info)
    if not alive:
        await camera_state.detach()
    return {"alive": alive, "device": camera_state.info.device if camera_state.info else None}


@router.post("/discover", summary="Lance une découverte automatique")
async def discover(current_user: User = Depends(get_current_user)):
    """
    Tente de découvrir une ESP32-CAM GREEN sur le réseau local.
    Ordre : mDNS (green-cam.local) → IP fixe depuis config.

    Si une caméra est déjà connectée, la remplace si une nouvelle est trouvée.
    """
    result = await discover_esp32()
    if not result:
        raise HTTPException(
            status_code=404,
            detail=(
                "Aucune ESP32-CAM GREEN trouvée. "
                "Vérifiez que le firmware est flashé et que l'appareil est sur le même réseau."
            ),
        )

    provider, info = result
    await camera_state.attach(provider, info)
    return {
        "success": True,
        "device":  info.device,
        "ip":      info.ip,
        "firmware": info.firmware,
        "stream_url": "/api/esp32/stream",
        "message": f"ESP32-CAM '{info.device}' connectée à {info.ip}",
    }


@router.post("/connect", summary="Connexion manuelle par IP")
async def connect_by_ip(
    payload: ConnectPayload,
    current_user: User = Depends(get_current_user),
):
    """
    Connexion directe à une IP connue — utile en cas d'échec mDNS.
    Vérifie que l'ESP32 répond sur /status avant d'accepter la connexion.
    """
    ip = payload.ip.strip()
    provider = await ESP32CameraProvider.from_ip(ip)
    if not provider:
        raise HTTPException(
            status_code=502,
            detail=f"Impossible de joindre l'ESP32-CAM à {ip}. "
                   "Vérifiez l'IP et que le firmware GREEN_CAM est actif.",
        )

    # Récupère les métadonnées depuis /status
    import httpx
    status_data: dict = {}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(f"http://{ip}/status")
            if r.status_code == 200:
                status_data = r.json()
    except Exception:
        pass

    info = CameraInfo(
        device      = status_data.get("device", "GREEN-CAM"),
        ip          = ip,
        firmware    = status_data.get("firmware"),
        stream_path = status_data.get("stream", "/stream"),
        capture_path= status_data.get("capture", "/capture"),
        extra       = {"rssi": status_data.get("rssi")},
    )
    await camera_state.attach(provider, info)

    return {
        "success":   True,
        "device":    info.device,
        "ip":        ip,
        "firmware":  info.firmware,
        "stream_url": "/api/esp32/stream",
        "message":   f"Connecté à {info.device} @ {ip}",
    }


@router.post("/disconnect", summary="Déconnecte la caméra active")
async def disconnect(current_user: User = Depends(get_current_user)):
    """Détache la caméra active. La découverte automatique reprend en arrière-plan."""
    if not camera_state.connected:
        return {"success": True, "message": "Aucune caméra n'était connectée."}

    device = camera_state.info.device if camera_state.info else "?"
    await camera_state.detach()
    return {"success": True, "message": f"{device} déconnectée."}


@router.get("/stream", summary="Proxy flux MJPEG vers le navigateur")
async def proxy_stream(
    token: str = Query(..., description="JWT — passé en query car <img src> ne peut pas envoyer de header Authorization"),
    db: Session = Depends(get_db),
):
    """
    Relaie le flux MJPEG de l'ESP32-CAM vers le navigateur.

    Le frontend appelle UNIQUEMENT cette URL — jamais l'IP de l'ESP32.
    Le Content-Type multipart est conservé tel quel pour que le navigateur
    l'interprète comme un flux MJPEG standard.

    Authentifié par ?token= plutôt que par header Bearer : ce endpoint est
    consommé via <img src="...">, qui ne peut pas définir de headers.
    """
    _user_from_query_token(token, db)
    info, provider = _require_camera()

    # Récupère le Content-Type depuis l'ESP32 pour le retransmettre
    content_type = "multipart/x-mixed-replace; boundary=123456789000000000000987654321"

    async def _generate():
        async for chunk in provider.stream_chunks(info):
            yield chunk

    return StreamingResponse(
        _generate(),
        media_type=content_type,
        headers={
            "Cache-Control":             "no-cache, no-store",
            "X-Accel-Buffering":         "no",          # désactive le buffering nginx
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.post("/capture", summary="Capture un frame et lance l'inférence IA")
async def capture_and_analyze(
    payload: dict = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Capte un JPEG depuis l'ESP32-CAM et le soumet au pipeline IA existant.
    Retourne la fiche terrain avec la détection de maladie.

    Payload optionnel :
      { "parcel_id": int, "latitude": float, "longitude": float }
    """
    info, provider = _require_camera()
    payload = payload or {}

    try:
        image_bytes = await provider.grab_frame(info)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Pipeline IA inchangé — rover_common.analyze_image_bytes
    return await analyze_image_bytes(
        image_bytes,
        db,
        current_user,
        source="esp32",
        parcel_id  = payload.get("parcel_id"),
        latitude   = payload.get("latitude"),
        longitude  = payload.get("longitude"),
    )
