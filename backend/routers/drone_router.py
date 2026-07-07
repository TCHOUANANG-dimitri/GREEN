# ============================================================
# GREEN App — Drone Router (legacy alias → same logic as camera)
# ============================================================

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from auth import get_current_user
from config import DEFAULT_DRONE_IP, DEFAULT_DRONE_STREAM_PORT
from database import get_db
from models import User
from rover_common import (
    analyze_image_bytes,
    check_stream,
    grab_frame,
    parse_ip_port,
    stream_url,
    validate_upload,
)

router = APIRouter(prefix="/api/drone", tags=["Drone"])


@router.post("/connect", summary="Verify drone stream is reachable")
async def connect_drone(
    payload: dict,
    current_user: User = Depends(get_current_user),
):
    ip, port = parse_ip_port(payload)
    reachable = await check_stream(ip, port)

    if not reachable:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Could not reach drone stream at {stream_url(ip, port)}. "
                "Check that the drone WiFi is connected and the IP/port are correct."
            ),
        )

    return {
        "success":    True,
        "ip":         ip,
        "port":       port,
        "stream_url": stream_url(ip, port),
        "message":    f"Drone connected at {ip}:{port}",
    }


@router.post("/capture", summary="Capture a frame and run disease inference")
async def capture_and_analyze(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ip, port = parse_ip_port(payload)
    parcel_id = payload.get("parcel_id")
    latitude  = payload.get("latitude")
    longitude = payload.get("longitude")

    image_bytes = await grab_frame(ip, port)
    return await analyze_image_bytes(
        image_bytes, db, current_user, source="drone",
        parcel_id=parcel_id, latitude=latitude, longitude=longitude,
    )


@router.post("/upload", summary="Upload an image file for disease analysis")
async def upload_and_analyze(
    file: UploadFile = File(...),
    parcel_id: Optional[int]   = Form(None),
    latitude:  Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    image_bytes = await validate_upload(file)
    return await analyze_image_bytes(
        image_bytes, db, current_user, source="upload",
        parcel_id=parcel_id, latitude=latitude, longitude=longitude,
    )


@router.get("/stream-url", summary="Get the MJPEG stream URL for a given IP")
def get_stream_url(
    ip: str = DEFAULT_DRONE_IP,
    port: int = DEFAULT_DRONE_STREAM_PORT,
    current_user: User = Depends(get_current_user),
):
    ip = ip.strip()
    return {"stream_url": stream_url(ip, port), "ip": ip, "port": port}
