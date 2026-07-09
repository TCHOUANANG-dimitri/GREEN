# ============================================================
# camera/healthcheck.py — Background task de surveillance caméra
#
# Tourne en arrière-plan dès le démarrage du serveur FastAPI.
# Toutes les N secondes :
#   - Si caméra connectée  → vérifie qu'elle répond encore
#   - Si caméra absente    → tente de la redécouvrir
# ============================================================

from __future__ import annotations

import asyncio
import logging

from .discovery import discover_esp32
from .state     import camera_state

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_S    = 15   # intervalle de vérification (secondes)
_REDISCOVER_INTERVAL = 3    # nombre de ticks avant re-tentative de découverte


async def camera_healthcheck_loop() -> None:
    """
    Coroutine infinie lancée au démarrage de l'app via asyncio.create_task().
    Ne jamais appeler directement depuis un endpoint.
    """
    logger.info("[Healthcheck] Démarrage boucle surveillance caméra (intervalle %ds)", _CHECK_INTERVAL_S)

    miss_count = 0   # compteur de ticks sans caméra → déclenche une re-découverte

    while True:
        await asyncio.sleep(_CHECK_INTERVAL_S)

        if camera_state.connected and camera_state.provider and camera_state.info:
            # ── Caméra connue : vérifie qu'elle répond ──────────────
            alive = await camera_state.provider.is_alive(camera_state.info)
            if alive:
                miss_count = 0
                logger.debug(
                    "[Healthcheck] %s @ %s OK",
                    camera_state.info.device,
                    camera_state.info.ip,
                )
            else:
                miss_count += 1
                logger.warning(
                    "[Healthcheck] %s @ %s ne répond plus (miss %d)",
                    camera_state.info.device,
                    camera_state.info.ip,
                    miss_count,
                )
                # Après 2 échecs consécutifs → déconnexion
                if miss_count >= 2:
                    logger.warning("[Healthcheck] Détachement de la caméra.")
                    await camera_state.detach()
                    miss_count = 0

        else:
            # ── Pas de caméra : tente la découverte périodiquement ──
            miss_count += 1
            if miss_count >= _REDISCOVER_INTERVAL:
                miss_count = 0
                logger.info("[Healthcheck] Tentative de re-découverte…")
                result = await discover_esp32()
                if result:
                    provider, info = result
                    await camera_state.attach(provider, info)
                    logger.info(
                        "[Healthcheck] Caméra reconnectée : %s @ %s",
                        info.device, info.ip,
                    )
