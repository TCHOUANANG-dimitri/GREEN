# ============================================================
# camera/esp32.py — Implémentation CameraProvider pour ESP32-CAM
#
# Gère la communication avec le firmware GREEN_CAM :
#   - vérification /status
#   - grab JPEG via /capture
#   - proxy du flux MJPEG via /stream
# ============================================================

from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

import httpx

from .provider import CameraInfo, CameraProvider

logger = logging.getLogger(__name__)

# Timeouts (secondes)
_TIMEOUT_STATUS  = 4.0
_TIMEOUT_CAPTURE = 8.0
_TIMEOUT_STREAM  = 30.0


class ESP32CameraProvider(CameraProvider):
    """
    Provider pour ESP32-CAM flashé avec le firmware GREEN_CAM.

    Protocole attendu sur l'ESP32 :
      GET /status  → JSON { device, status, firmware, ip, uptime, rssi }
      GET /capture → image/jpeg
      GET /stream  → multipart/x-mixed-replace MJPEG
      GET /info    → JSON { mac, ip, rssi, ssid, free_heap, psram, … }
    """

    async def discover(self) -> Optional[CameraInfo]:
        # La découverte mDNS est déléguée à discovery.py.
        # Cette méthode ne sera jamais appelée directement — voir discover_esp32().
        return None

    async def _fetch_status(self, ip: str) -> Optional[dict]:
        """Interroge /status sur l'IP donnée."""
        url = f"http://{ip}/status"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_STATUS) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    return r.json()
        except Exception as exc:
            logger.debug("[ESP32] /status @ %s → %s", ip, exc)
        return None

    async def is_alive(self, info: CameraInfo) -> bool:
        """Ping léger via /status."""
        status = await self._fetch_status(info.ip)
        return status is not None and status.get("status") == "online"

    async def grab_frame(self, info: CameraInfo) -> bytes:
        """
        Récupère un JPEG unique via GET /capture.
        Plus fiable que parser le flux MJPEG pour un seul frame.
        """
        url = info.capture_url
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_CAPTURE) as client:
                r = await client.get(url)
                r.raise_for_status()
                data = r.content
                if not data:
                    raise ValueError("Réponse vide")
                return data
        except Exception as exc:
            logger.error("[ESP32] grab_frame @ %s → %s", url, exc)
            raise RuntimeError(f"Impossible de capturer un frame depuis {url}: {exc}") from exc

    async def stream_chunks(
        self,
        info: CameraInfo,
        chunk_size: int = 16384,
    ) -> AsyncIterator[bytes]:
        """
        Relaie les chunks bruts du flux MJPEG vers le router proxy.
        Le Content-Type multipart est conservé tel quel.
        """
        url = info.stream_url
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(
                connect=5.0,
                read=_TIMEOUT_STREAM,
                write=5.0,
                pool=5.0,
            )) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes(chunk_size):
                        yield chunk
        except Exception as exc:
            logger.error("[ESP32] stream_chunks @ %s → %s", url, exc)
            return

    async def get_info(self, info: CameraInfo) -> dict:
        """Récupère les infos étendues via GET /info."""
        url = f"http://{info.ip}/info"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_STATUS) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    return r.json()
        except Exception as exc:
            logger.debug("[ESP32] /info @ %s → %s", info.ip, exc)
        # Fallback sur les données déjà connues
        return await super().get_info(info)

    @classmethod
    async def from_ip(cls, ip: str) -> Optional["ESP32CameraProvider"]:
        """
        Crée un provider à partir d'une IP connue.
        Vérifie que l'ESP32 répond avant de retourner l'instance.
        """
        provider = cls()
        status = await provider._fetch_status(ip)
        if status and status.get("status") == "online":
            return provider
        return None
