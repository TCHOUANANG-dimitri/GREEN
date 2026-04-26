# ============================================================
# GREEN App — Dashboard Router
# Endpoints:
#   GET /api/dashboard/stats          → KPI counts for the dashboard cards
#   GET /api/dashboard/disease-trends → Weekly detection data for the chart
# ============================================================

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import List

from database import get_db
from models import User, Parcel, DiseaseAnalysis, ChatSession
from auth import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


# ---- GET /api/dashboard/stats --------------------------------
@router.get("/stats", summary="Get KPI counts for the dashboard")
def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns summary counts used by the 4 KPI cards:
    - parcels        : active parcels the user has mapped
    - analyses       : total disease scans performed
    - diseases       : positive disease detections (non-healthy)
    - chat_sessions  : total GreenBot conversations
    Also returns week-over-week change for each metric.
    """
    uid = current_user.id
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    # ---- Current totals ----
    parcels       = db.query(func.count(Parcel.id)).filter(
                        Parcel.user_id == uid, Parcel.is_active == True
                    ).scalar() or 0

    analyses      = db.query(func.count(DiseaseAnalysis.id)).filter(
                        DiseaseAnalysis.user_id == uid
                    ).scalar() or 0

    diseases      = db.query(func.count(DiseaseAnalysis.id)).filter(
                        DiseaseAnalysis.user_id == uid,
                        DiseaseAnalysis.detected_disease != None,
                        DiseaseAnalysis.detected_disease != "healthy"
                    ).scalar() or 0

    pests         = db.query(func.count(DiseaseAnalysis.id)).filter(
                        DiseaseAnalysis.user_id == uid,
                        DiseaseAnalysis.pest_detected != None,
                        DiseaseAnalysis.pest_detected != "none"
                    ).scalar() or 0

    chat_sessions = db.query(func.count(ChatSession.id)).filter(
                        ChatSession.user_id == uid
                    ).scalar() or 0

    # ---- New this week (for change indicators) ----
    new_analyses_wk  = db.query(func.count(DiseaseAnalysis.id)).filter(
                           DiseaseAnalysis.user_id == uid,
                           DiseaseAnalysis.created_at >= week_ago
                       ).scalar() or 0

    new_diseases_wk  = db.query(func.count(DiseaseAnalysis.id)).filter(
                           DiseaseAnalysis.user_id == uid,
                           DiseaseAnalysis.detected_disease != None,
                           DiseaseAnalysis.detected_disease != "healthy",
                           DiseaseAnalysis.created_at >= week_ago
                       ).scalar() or 0

    new_pests_wk     = db.query(func.count(DiseaseAnalysis.id)).filter(
                           DiseaseAnalysis.user_id == uid,
                           DiseaseAnalysis.pest_detected != None,
                           DiseaseAnalysis.pest_detected != "none",
                           DiseaseAnalysis.created_at >= week_ago
                       ).scalar() or 0

    new_chats_wk     = db.query(func.count(ChatSession.id)).filter(
                           ChatSession.user_id == uid,
                           ChatSession.created_at >= week_ago
                       ).scalar() or 0

    return {
        "parcels":              parcels,
        "analyses":             analyses,
        "diseases":             diseases,
        "pests":                pests,
        "chat_sessions":        chat_sessions,
        # Week-over-week additions (used for change pills in UI)
        "new_analyses_week":    new_analyses_wk,
        "new_diseases_week":    new_diseases_wk,
        "new_pests_week":       new_pests_wk,
        "new_chats_week":       new_chats_wk,
    }


# ---- GET /api/dashboard/disease-trends -----------------------
@router.get("/disease-trends", summary="Weekly disease detection data for the chart")
def get_disease_trends(
    days: int = Query(default=30, ge=7, le=365, description="Look-back window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns weekly aggregated counts of disease detections vs healthy results
    for the last `days` days. Used to render the bar chart on the dashboard.

    Response shape:
    {
      "labels":     ["Week 1", "Week 2", ...],
      "detections": [3, 1, 5, 2],
      "healthy":    [10, 8, 14, 7]
    }
    """
    uid   = current_user.id
    since = datetime.utcnow() - timedelta(days=days)

    # Fetch all analyses in the window
    analyses = (
        db.query(DiseaseAnalysis)
          .filter(
              DiseaseAnalysis.user_id == uid,
              DiseaseAnalysis.created_at >= since
          )
          .order_by(DiseaseAnalysis.created_at.asc())
          .all()
    )

    # Build weekly buckets (ISO week number relative to `since`)
    num_weeks = max(1, days // 7)
    buckets = []
    for i in range(num_weeks):
        week_start = since + timedelta(weeks=i)
        week_end   = week_start + timedelta(weeks=1)
        detections = sum(
            1 for a in analyses
            if week_start <= a.created_at < week_end
            and a.detected_disease
            and a.detected_disease != "healthy"
        )
        healthy = sum(
            1 for a in analyses
            if week_start <= a.created_at < week_end
            and (not a.detected_disease or a.detected_disease == "healthy")
        )
        buckets.append({
            "label":      f"Week {i + 1}",
            "detections": detections,
            "healthy":    healthy,
        })

    return {
        "labels":     [b["label"]      for b in buckets],
        "detections": [b["detections"] for b in buckets],
        "healthy":    [b["healthy"]    for b in buckets],
        "period_days": days,
        "total_analyses": len(analyses),
    }


# ---- GET /api/dashboard/recent-activity ----------------------
@router.get("/recent-activity", summary="Latest 5 analyses for the activity feed")
def get_recent_activity(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns the 5 most recent analyses with their key fields.
    Used by the 'Recent Analyses' table at the bottom of the dashboard.
    """
    analyses = (
        db.query(DiseaseAnalysis)
          .filter(DiseaseAnalysis.user_id == current_user.id)
          .order_by(DiseaseAnalysis.created_at.desc())
          .limit(5)
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
            "parcel_id":        a.parcel_id,
            "latitude":         a.latitude,
            "longitude":        a.longitude,
            "created_at":       a.created_at.isoformat(),
        }
        for a in analyses
    ]
