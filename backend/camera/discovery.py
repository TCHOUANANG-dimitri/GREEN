# ============================================================
# camera/discovery.py — Découverte automatique de l'ESP32-CAM
#
# Stratégie (dans l'ordre) :
#   1. mDNS  → http://green-cam.local/status        (prioritaire)
#   2. IP fixe depuis config (DEFAULT_CAMERA_IP)     (fallback)
#
# Pourquoi mDNS en priorité ?
#   - Aucun scan réseau
#   - Fonctionne même si l'IP DHCP change
#   - Standard, supporté par ESP32 Arduino + socket Python
#
# Limitation mDNS sur Windows :
#   Le module `zeroconf` est nécessaire sur Windows/Linux.
#   Sur macOS, le socket multicast DNS du système suffit.
# ============================================================

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from config import ESP32_DEFAULT_IP as DEFAULT_CAMERA_IP, ESP32_MDNS_HOST as _MDNS_HOSTNAME_CFG
from .provider import CameraInfo
from .esp32    import ESP32CameraProvider

logger = logging.getLogger(__name__)

# Hostname mDNS déclaré par le firmware (configurable via .env)
_MDNS_HOSTNAME = _MDNS_HOSTNAME_CFG
_STATUS_TIMEOUT = 4.0


async def _probe_url(url: str) -> Optional[dict]:
    """Interroge un /status et retourne le JSON ou None."""
    try:
        async with httpx.AsyncClient(timeout=_STATUS_TIMEOUT) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return None


async def _probe_ip(ip: str) -> Optional[CameraInfo]:
    """Tente de joindre /status sur l'IP fournie."""
    status = await _probe_url(f"http://{ip}/status")
    if not status or status.get("status") != "online":
        return None
    return CameraInfo(
        device       = status.get("device", "GREEN-CAM"),
        ip           = ip,
        firmware     = status.get("firmware"),
        stream_path  = status.get("stream", "/stream"),
        capture_path = status.get("capture", "/capture"),
        status_path  = "/status",
        extra        = {"rssi": status.get("rssi"), "uptime": status.get("uptime")},
    )


async def _probe_mdns() -> Optional[CameraInfo]:
    """
    Résout green-cam.local via le système, puis interroge /status.
    Fonctionne sur macOS et Windows (avec Bonjour ou zeroconf installé).
    """
    try:
        # getaddrinfo est bloquant — on l'exécute dans un thread
        loop = asyncio.get_event_loop()
        infos = await loop.run_in_executor(
            None,
            lambda: __import__("socket").getaddrinfo(
                _MDNS_HOSTNAME, 80, type=__import__("socket").SOCK_STREAM
            ),
        )
        if not infos:
            return None
        ip = infos[0][4][0]
        logger.info("[Discovery] mDNS résolu : %s → %s", _MDNS_HOSTNAME, ip)
        return await _probe_ip(ip)
    except OSError:
        logger.debug("[Discovery] mDNS non résolu (%s)", _MDNS_HOSTNAME)
        return None


async def discover_esp32() -> Optional[tuple[ESP32CameraProvider, CameraInfo]]:
    """
    Point d'entrée principal de la découverte.

    Retourne (provider, info) si une ESP32-CAM GREEN est trouvée,
    None sinon.

    Appelé :
      - au démarrage du serveur FastAPI
      - périodiquement par le background task de healthcheck
      - sur GET /api/esp32/discover
    """
    # --- Étape 1 : mDNS ---
    logger.info("[Discovery] Tentative mDNS sur %s…", _MDNS_HOSTNAME)
    info = await _probe_mdns()

    # --- Étape 2 : IP fixe depuis config ---
    if info is None and DEFAULT_CAMERA_IP:
        logger.info("[Discovery] Fallback IP fixe : %s", DEFAULT_CAMERA_IP)
        info = await _probe_ip(DEFAULT_CAMERA_IP)

    if info is None:
        logger.info("[Discovery] Aucune ESP32-CAM trouvée.")
        return None

    provider = ESP32CameraProvider()
    logger.info(
        "[Discovery] ESP32-CAM trouvée : %s @ %s (fw %s)",
        info.device, info.ip, info.firmware,
    )
    return provider, info
