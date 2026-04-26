# ============================================================
# GREEN App — Parcel Router (Phase 5)
#
# Manages agricultural land parcels (parcelles).
# Each parcel stores a GeoJSON polygon (drawn with Leaflet.draw),
# crop type, area, region and optional center GPS coordinates.
#
# Endpoints:
#   GET    /api/parcels              → list all user's parcels
#   POST   /api/parcels              → create a new parcel
#   GET    /api/parcels/{id}         → get single parcel details
#   PUT    /api/parcels/{id}         → update parcel fields
#   DELETE /api/parcels/{id}         → soft-delete parcel (is_active=False)
#   GET    /api/parcels/{id}/analyses→ disease analyses linked to this parcel
# ============================================================

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db
from models import User, Parcel, DiseaseAnalysis
from auth import get_current_user

router = APIRouter(prefix="/api/parcels", tags=["Parcels"])


# ---- Request schemas ----------------------------------------

class ParcelCreate(BaseModel):
    name:        str
    crop_type:   Optional[str]  = None
    area_ha:     Optional[float]= None
    region:      Optional[str]  = None
    description: Optional[str]  = None
    geometry:    Optional[dict] = None   # GeoJSON FeatureCollection or Polygon
    latitude:    Optional[float]= None   # center lat (auto-computed if geometry given)
    longitude:   Optional[float]= None   # center lon


class ParcelUpdate(BaseModel):
    name:        Optional[str]  = None
    crop_type:   Optional[str]  = None
    area_ha:     Optional[float]= None
    region:      Optional[str]  = None
    description: Optional[str]  = None
    geometry:    Optional[dict] = None
    latitude:    Optional[float]= None
    longitude:   Optional[float]= None
    is_active:   Optional[bool] = None


# ---- Helpers -------------------------------------------------

def _parcel_dict(p: Parcel) -> dict:
    """Serialize a Parcel ORM object to a response dict."""
    return {
        "id":          p.id,
        "name":        p.name,
        "crop_type":   p.crop_type,
        "area_ha":     p.area_ha,
        "region":      p.region,
        "description": p.description,
        "geometry":    p.geometry,
        "latitude":    p.latitude,
        "longitude":   p.longitude,
        "is_active":   p.is_active,
        "created_at":  p.created_at.isoformat(),
        "updated_at":  p.updated_at.isoformat() if p.updated_at else None,
    }


def _compute_center(geometry: dict) -> tuple[Optional[float], Optional[float]]:
    """
    Compute the centroid of a GeoJSON geometry (Polygon or FeatureCollection).
    Returns (latitude, longitude) or (None, None) if geometry is invalid.
    """
    try:
        # Accept both raw Polygon and FeatureCollection
        if geometry.get("type") == "FeatureCollection":
            features = geometry.get("features", [])
            if not features:
                return None, None
            coords_list = []
            for feat in features:
                geom = feat.get("geometry", {})
                if geom.get("type") == "Polygon":
                    coords_list.extend(geom["coordinates"][0])
        elif geometry.get("type") == "Polygon":
            coords_list = geometry["coordinates"][0]
        elif geometry.get("type") == "Feature":
            geom = geometry.get("geometry", {})
            coords_list = geom.get("coordinates", [[]])[0]
        else:
            return None, None

        if not coords_list:
            return None, None

        # Simple centroid: average of all ring vertices [lon, lat]
        avg_lon = sum(c[0] for c in coords_list) / len(coords_list)
        avg_lat = sum(c[1] for c in coords_list) / len(coords_list)
        return round(avg_lat, 6), round(avg_lon, 6)
    except Exception:
        return None, None


# ---- GET /api/parcels ----------------------------------------
@router.get("", summary="List all active parcels for the current user")
def list_parcels(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """
    Returns all active parcels with their geometries.
    Used by the GREEN Map to render parcel polygons on load.
    """
    parcels = (
        db.query(Parcel)
          .filter(Parcel.user_id == current_user.id, Parcel.is_active == True)
          .order_by(Parcel.created_at.desc())
          .all()
    )
    return [_parcel_dict(p) for p in parcels]


# ---- POST /api/parcels ---------------------------------------
@router.post("", summary="Create a new parcel", status_code=201)
def create_parcel(
    payload:      ParcelCreate,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """
    Create a parcel from the Leaflet.draw polygon.
    If `geometry` is provided but `latitude`/`longitude` are missing,
    the centroid is computed automatically.
    """
    lat, lon = payload.latitude, payload.longitude
    if payload.geometry and (lat is None or lon is None):
        lat, lon = _compute_center(payload.geometry)

    parcel = Parcel(
        user_id     = current_user.id,
        name        = payload.name,
        crop_type   = payload.crop_type,
        area_ha     = payload.area_ha,
        region      = payload.region,
        description = payload.description,
        geometry    = payload.geometry,
        latitude    = lat,
        longitude   = lon,
        is_active   = True,
    )
    db.add(parcel)
    db.commit()
    db.refresh(parcel)
    return _parcel_dict(parcel)


# ---- GET /api/parcels/{id} -----------------------------------
@router.get("/{parcel_id}", summary="Get a single parcel")
def get_parcel(
    parcel_id:    int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    parcel = (
        db.query(Parcel)
          .filter(Parcel.id == parcel_id, Parcel.user_id == current_user.id)
          .first()
    )
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found.")
    return _parcel_dict(parcel)


# ---- PUT /api/parcels/{id} -----------------------------------
@router.put("/{parcel_id}", summary="Update a parcel")
def update_parcel(
    parcel_id:    int,
    payload:      ParcelUpdate,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """
    Partial update — only provided fields are changed.
    If geometry changes, centroid is recomputed unless lat/lon are given.
    """
    parcel = (
        db.query(Parcel)
          .filter(Parcel.id == parcel_id, Parcel.user_id == current_user.id)
          .first()
    )
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found.")

    update_data = payload.model_dump(exclude_none=True)

    # Recompute centroid if geometry changed without explicit coords
    if "geometry" in update_data:
        if "latitude" not in update_data or "longitude" not in update_data:
            lat, lon = _compute_center(update_data["geometry"])
            if lat is not None:
                update_data["latitude"]  = lat
                update_data["longitude"] = lon

    for field, value in update_data.items():
        setattr(parcel, field, value)

    db.commit()
    db.refresh(parcel)
    return _parcel_dict(parcel)


# ---- DELETE /api/parcels/{id} --------------------------------
@router.delete("/{parcel_id}", summary="Soft-delete a parcel")
def delete_parcel(
    parcel_id:    int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """
    Marks the parcel as inactive (soft delete) so analyses
    referencing it are preserved in history.
    """
    parcel = (
        db.query(Parcel)
          .filter(Parcel.id == parcel_id, Parcel.user_id == current_user.id)
          .first()
    )
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found.")

    parcel.is_active = False
    db.commit()
    return {"success": True, "message": "Parcel deleted."}


# ---- GET /api/parcels/{id}/analyses -------------------------
@router.get("/{parcel_id}/analyses", summary="Get disease analyses linked to a parcel")
def get_parcel_analyses(
    parcel_id:    int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """
    Returns all analyses recorded on this parcel.
    Used to populate the disease overlay pins on the map.
    """
    # Verify ownership
    parcel = (
        db.query(Parcel)
          .filter(Parcel.id == parcel_id, Parcel.user_id == current_user.id)
          .first()
    )
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found.")

    analyses = (
        db.query(DiseaseAnalysis)
          .filter(DiseaseAnalysis.parcel_id == parcel_id)
          .order_by(DiseaseAnalysis.created_at.desc())
          .all()
    )
    return [
        {
            "id":               a.id,
            "disease_name":     a.disease_name or "Healthy",
            "detected_disease": a.detected_disease,
            "plant_type":       a.plant_type,
            "severity":         a.severity,
            "confidence":       a.confidence,
            "source":           a.source,
            "latitude":         a.latitude,
            "longitude":        a.longitude,
            "created_at":       a.created_at.isoformat(),
        }
        for a in analyses
    ]


# ---- GET /api/parcels/geo/analyses ---------------------------
@router.get("/geo/analyses", summary="All geolocated analyses (for map overlay)")
def get_all_geolocated_analyses(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """
    Returns all analyses that have GPS coordinates,
    regardless of parcel. Used to draw the disease-pin overlay.
    """
    analyses = (
        db.query(DiseaseAnalysis)
          .filter(
              DiseaseAnalysis.user_id   == current_user.id,
              DiseaseAnalysis.latitude  != None,
              DiseaseAnalysis.longitude != None,
          )
          .order_by(DiseaseAnalysis.created_at.desc())
          .all()
    )
    return [
        {
            "id":               a.id,
            "disease_name":     a.disease_name or "Healthy",
            "detected_disease": a.detected_disease,
            "plant_type":       a.plant_type,
            "severity":         a.severity,
            "confidence":       a.confidence,
            "latitude":         a.latitude,
            "longitude":        a.longitude,
            "parcel_id":        a.parcel_id,
            "created_at":       a.created_at.isoformat(),
        }
        for a in analyses
    ]
