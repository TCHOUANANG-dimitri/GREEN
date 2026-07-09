# ============================================================
# camera/provider.py — Interface abstraite CameraProvider
#
# Toute source vidéo (ESP32-CAM, caméra IP, RTSP, WebRTC…)
# doit implémenter ce protocol.
# Le reste du code (router, proxy) ne dépend que de cette
# interface — jamais d'une implémentation concrète.
# ============================================================

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional


@dataclass
class CameraInfo:
    """Informations sur la source vidéo connectée."""
    device:    str             = "unknown"
    ip:        Optional[str]   = None
    firmware:  Optional[str]   = None
    model:     Optional[str]   = None
    stream_path: str           = "/stream"
    capture_path: str          = "/capture"
    status_path:  str          = "/status"
    extra:     dict            = field(default_factory=dict)

    @property
    def stream_url(self) -> Optional[str]:
        if not self.ip:
            return None
        return f"http://{self.ip}{self.stream_path}"

    @property
    def capture_url(self) -> Optional[str]:
        if not self.ip:
            return None
        return f"http://{self.ip}{self.capture_path}"

    @property
    def status_url(self) -> Optional[str]:
        if not self.ip:
            return None
        return f"http://{self.ip}{self.status_path}"


class CameraProvider(abc.ABC):
    """
    Interface abstraite pour toute source vidéo.

    Implémenter cette classe pour supporter un nouveau type de caméra
    sans modifier le router ni le frontend.
    """

    @abc.abstractmethod
    async def discover(self) -> Optional[CameraInfo]:
        """
        Tente de découvrir/atteindre la source vidéo.
        Retourne CameraInfo si trouvée, None sinon.
        """

    @abc.abstractmethod
    async def is_alive(self, info: CameraInfo) -> bool:
        """Vérifie si la source est toujours joignable."""

    @abc.abstractmethod
    async def grab_frame(self, info: CameraInfo) -> bytes:
        """Capture et retourne un JPEG brut."""

    @abc.abstractmethod
    async def stream_chunks(
        self,
        info: CameraInfo,
        chunk_size: int = 16384,
    ) -> AsyncIterator[bytes]:
        """
        Générateur asynchrone de chunks bruts du flux MJPEG.
        Le router proxy les retransmet directement au navigateur.
        """
        # Annotation mypy : yields bytes
        yield b""  # type: ignore[misc]

    async def get_info(self, info: CameraInfo) -> dict:
        """
        Retourne des métadonnées étendues.
        Optionnel — les sous-classes peuvent surcharger.
        """
        return {
            "device":   info.device,
            "ip":       info.ip,
            "firmware": info.firmware,
            "model":    info.model,
        }
