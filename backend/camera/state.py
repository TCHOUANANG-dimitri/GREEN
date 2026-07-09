# ============================================================
# camera/state.py — Singleton d'état de la caméra connectée
#
# Conserve en mémoire la caméra active, son provider, et son
# état de connexion. Accessible depuis tous les modules backend.
# Thread-safe via asyncio.Lock.
# ============================================================

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .provider import CameraInfo, CameraProvider

logger = logging.getLogger(__name__)


class CameraState:
    """
    Singleton centralisant l'état de la caméra active.

    Attributs publics (lecture seule depuis l'extérieur) :
      connected : bool
      info      : CameraInfo | None
      provider  : CameraProvider | None
    """

    def __init__(self) -> None:
        self._lock:       asyncio.Lock          = asyncio.Lock()
        self.connected:   bool                  = False
        self.info:        Optional[CameraInfo]  = None
        self.provider:    Optional[CameraProvider] = None

    async def attach(
        self,
        provider: CameraProvider,
        info: CameraInfo,
    ) -> None:
        """Enregistre la caméra découverte comme source active."""
        async with self._lock:
            self.provider  = provider
            self.info      = info
            self.connected = True
        logger.info(
            "[CameraState] Caméra attachée : %s @ %s",
            info.device,
            info.ip,
        )

    async def detach(self) -> None:
        """Déconnecte la source active."""
        async with self._lock:
            device = self.info.device if self.info else "?"
            self.connected = False
            self.info      = None
            self.provider  = None
        logger.info("[CameraState] Caméra détachée : %s", device)

    def to_dict(self) -> dict:
        """Sérialise l'état pour les endpoints REST."""
        if not self.connected or not self.info:
            return {"connected": False, "device": None, "ip": None}
        return {
            "connected": True,
            "device":    self.info.device,
            "ip":        self.info.ip,
            "firmware":  self.info.firmware,
            "model":     self.info.model,
            "stream_url": self.info.stream_url,
        }


# Instance singleton — importée dans tout le backend
camera_state = CameraState()
