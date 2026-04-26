# ============================================================
# GREEN App — Disease Database Router
#
# Serves the diseases.json reference database via REST API.
# No authentication required — public agronomic reference data.
#
#   GET /api/diseases        — list all (optional ?q= search)
#   GET /api/diseases/{id}   — single disease by ID
# ============================================================

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from config import DISEASES_DB_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/diseases", tags=["Disease Database"])

# In-memory cache — loaded once on first request
_cache: list = []


def _load() -> list:
    global _cache
    if _cache:
        return _cache
    try:
        with open(DISEASES_DB_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
        logger.info(f"[DiseaseDB] Loaded {len(_cache)} entries from diseases.json")
    except FileNotFoundError:
        logger.warning(f"[DiseaseDB] diseases.json not found at {DISEASES_DB_PATH}")
        _cache = []
    except Exception as exc:
        logger.error(f"[DiseaseDB] Failed to load diseases.json: {exc}")
        _cache = []
    return _cache


@router.get("", summary="List all diseases from the reference database")
def list_diseases(
    q:     Optional[str] = Query(None, description="Search by name, alias, or plant"),
    plant: Optional[str] = Query(None, description="Filter by affected plant"),
):
    """
    Returns the full disease reference list.
    Optional full-text search via ?q= and plant filter via ?plant=
    """
    diseases = _load()

    if plant:
        plant_lower = plant.lower()
        diseases = [
            d for d in diseases
            if any(plant_lower in p.lower() for p in d.get("affectedPlants", []))
        ]

    if q:
        q_lower = q.lower()
        diseases = [
            d for d in diseases
            if q_lower in d.get("name", "").lower()
            or any(q_lower in a.lower() for a in d.get("aliases", []))
            or any(q_lower in p.lower() for p in d.get("affectedPlants", []))
            or q_lower in d.get("scientificName", "").lower()
        ]

    return diseases


@router.get("/{disease_id}", summary="Get a specific disease by ID")
def get_disease(disease_id: str):
    """Returns a single disease entry by its ID field."""
    for d in _load():
        if d["id"] == disease_id:
            return d
    raise HTTPException(status_code=404, detail=f"Disease '{disease_id}' not found.")
