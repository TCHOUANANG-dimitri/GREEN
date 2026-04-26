# ============================================================
# GREEN App — Disease Analysis Router
# Manages the history of disease scans (saved frames + results).
# Drone inference and upload endpoints will be added in Phase 4.
#
# Endpoints:
#   GET    /api/analysis/history         → paginated scan history
#   GET    /api/analysis/{id}            → single analysis + fiche terrain
#   DELETE /api/analysis/{id}            → remove from history
# ============================================================

import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from models import User, DiseaseAnalysis, Parcel
from auth import get_current_user
from config import DISEASES_DB_PATH

router = APIRouter(prefix="/api/analysis", tags=["Disease Analysis"])


# ---- Helper: load disease database --------------------------
def _load_diseases() -> dict:
    """
    Load the diseases.json file into a dict keyed by disease id.
    Used to enrich analysis responses with full disease details.
    """
    try:
        with open(DISEASES_DB_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {d["id"]: d for d in raw}
    except Exception:
        return {}


# ---- Helper: build fiche terrain ----------------------------
def _build_fiche_terrain(analysis: DiseaseAnalysis, diseases_db: dict) -> dict:
    """
    Generate a terrain sheet (fiche terrain) from a DiseaseAnalysis row.
    Enriches the basic detection result with full disease details from the DB.

    Returns a dict that can be displayed to the user or saved as JSON.
    """
    disease_id = analysis.detected_disease or "healthy"
    disease_info = diseases_db.get(disease_id, {})

    return {
        # ---- Identification ----
        "disease_id":       disease_id,
        "disease_name":     analysis.disease_name or disease_info.get("name", "Healthy"),
        "scientific_name":  disease_info.get("scientificName", "—"),
        "plant_type":       analysis.plant_type or "—",

        # ---- Detection result ----
        "confidence":       round((analysis.confidence or 0) * 100, 1),   # as %
        "severity":         analysis.severity or "low",
        "source":           analysis.source or "drone",

        # ---- Location ----
        "latitude":         analysis.latitude,
        "longitude":        analysis.longitude,
        "parcel_id":        analysis.parcel_id,

        # ---- Clinical data from disease DB ----
        "symptoms":         disease_info.get("symptoms", []),
        "recommendations":  disease_info.get("actions",  []),
        "affected_plants":  disease_info.get("affectedPlants", []),
        "aliases":          disease_info.get("aliases", []),

        # ---- Meta ----
        "generated_at":     analysis.created_at.isoformat(),
        "analysis_id":      analysis.id,
    }


# ---- GET /api/analysis/history -------------------------------
@router.get("/history", summary="Get paginated disease analysis history")
def get_history(
    limit:       int           = Query(default=20, ge=1, le=100),
    offset:      int           = Query(default=0,  ge=0),
    source:      Optional[str] = Query(None, description="Filter by source: camera|upload|drone"),
    result_type: Optional[str] = Query(None, description="Filter by result: disease|healthy|pest"),
    plant_type:  Optional[str] = Query(None, description="Filter by plant: Corn|Tomato|Cassava"),
    db:          Session       = Depends(get_db),
    current_user: User         = Depends(get_current_user),
):
    """
    Returns a paginated list of the user's past disease analyses,
    ordered newest first. Supports server-side filtering by source,
    result type (disease/healthy/pest), and plant type.

    Used by: dashboard recent table, History page.
    """
    q = db.query(DiseaseAnalysis).filter(DiseaseAnalysis.user_id == current_user.id)

    if source:
        q = q.filter(DiseaseAnalysis.source == source)

    if result_type == "disease":
        q = q.filter(
            DiseaseAnalysis.detected_disease != None,
            DiseaseAnalysis.detected_disease != "healthy",
        )
    elif result_type == "healthy":
        q = q.filter(DiseaseAnalysis.detected_disease == "healthy")
    elif result_type == "pest":
        q = q.filter(
            DiseaseAnalysis.pest_detected != None,
            DiseaseAnalysis.pest_detected != "none",
        )

    if plant_type:
        q = q.filter(DiseaseAnalysis.plant_type.ilike(f"%{plant_type}%"))

    total    = q.count()
    analyses = q.order_by(DiseaseAnalysis.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total":  total,
        "limit":  limit,
        "offset": offset,
        "items": [
            {
                "id":               a.id,
                "disease_name":     a.disease_name or "Healthy",
                "detected_disease": a.detected_disease,
                "plant_type":       a.plant_type,
                "severity":         a.severity,
                "confidence":       a.confidence,
                "source":           a.source,
                "parcel_id":        a.parcel_id,
                "latitude":         a.latitude,
                "longitude":        a.longitude,
                "pest_name":        a.pest_name,
                "pest_confidence":  a.pest_confidence,
                "pest_severity":    a.pest_severity,
                "created_at":       a.created_at.isoformat(),
                "has_fiche":        a.fiche_terrain is not None,
            }
            for a in analyses
        ],
    }


# ---- GET /api/analysis/{id} ----------------------------------
@router.get("/{analysis_id}", summary="Get a single analysis with full fiche terrain")
def get_analysis(
    analysis_id:  int,
    db:           Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns a single analysis enriched with the complete fiche terrain.
    If the fiche was already saved on creation (Phase 4), it is returned directly.
    Otherwise, it is generated on-the-fly from diseases.json.
    """
    analysis = (
        db.query(DiseaseAnalysis)
          .filter(
              DiseaseAnalysis.id == analysis_id,
              DiseaseAnalysis.user_id == current_user.id
          )
          .first()
    )
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found.")

    # Use saved fiche if available, otherwise build it now
    if analysis.fiche_terrain:
        fiche = analysis.fiche_terrain
    else:
        diseases_db = _load_diseases()
        fiche = _build_fiche_terrain(analysis, diseases_db)

    return {
        "id":               analysis.id,
        "disease_name":     analysis.disease_name or "Healthy",
        "detected_disease": analysis.detected_disease,
        "plant_type":       analysis.plant_type,
        "severity":         analysis.severity,
        "confidence":       analysis.confidence,
        "source":           analysis.source,
        "parcel_id":        analysis.parcel_id,
        "latitude":         analysis.latitude,
        "longitude":        analysis.longitude,
        "notes":            analysis.notes,
        "created_at":       analysis.created_at.isoformat(),
        "fiche_terrain":    fiche,
    }


# ---- DELETE /api/analysis/{id} -------------------------------
@router.delete("/{analysis_id}", summary="Delete an analysis from history")
def delete_analysis(
    analysis_id:  int,
    db:           Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Permanently removes an analysis record and its saved image (if any).
    Only the owner can delete their own analyses.
    """
    analysis = (
        db.query(DiseaseAnalysis)
          .filter(
              DiseaseAnalysis.id == analysis_id,
              DiseaseAnalysis.user_id == current_user.id
          )
          .first()
    )
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found.")

    # Remove saved image file if it exists
    if analysis.image_path and os.path.exists(analysis.image_path):
        try:
            os.remove(analysis.image_path)
        except OSError:
            pass  # Non-critical — proceed with DB deletion

    db.delete(analysis)
    db.commit()
    return {"message": "Analysis deleted.", "success": True}


# ---- GET /api/analysis/fiche/{id} ----------------------------
@router.get("/fiche/{analysis_id}", summary="Get only the fiche terrain for an analysis")
def get_fiche(
    analysis_id:  int,
    db:           Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns only the fiche terrain (terrain sheet) for a given analysis.
    Used by the History page and the post-scan modal to display the fiche.
    """
    analysis = (
        db.query(DiseaseAnalysis)
          .filter(
              DiseaseAnalysis.id == analysis_id,
              DiseaseAnalysis.user_id == current_user.id
          )
          .first()
    )
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found.")

    if analysis.fiche_terrain:
        return analysis.fiche_terrain

    diseases_db = _load_diseases()
    return _build_fiche_terrain(analysis, diseases_db)
