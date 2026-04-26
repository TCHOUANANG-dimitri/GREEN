# ============================================================
# GREEN App — YOLO Pest Detection Inference Engine
#
# Loads best.pt (YOLOv8 object-detection model) and runs
# inference on raw image bytes.  Returns the highest-confidence
# detection along with enrichment data (pest description,
# emitter-frequency recommendation).
#
# Classes detected by best.pt (2 classes):
#   0 → Criquet           (Locust / Grasshopper)
#   1 → papillon de nuit  (Moth — larva is destructive)
#
# If the model file is missing, all calls return a graceful
# null result so the rest of the API keeps working.
# ============================================================

import io
import logging
import os
from typing import Optional

from PIL import Image

from config import YOLO_MODEL_PATH

logger = logging.getLogger(__name__)


# ============================================================
# CLASS NAMES  (index → label — must match training order)
# ============================================================
YOLO_CLASS_NAMES: dict[int, str] = {
    0: "Locust",
    1: "Moth",
}

# English display names (for API response)
YOLO_DISPLAY_NAMES: dict[str, str] = {
    "Locust": "Locust / Grasshopper",
    "Moth":   "Nocturnal Moth",
}

# ============================================================
# PEST ENRICHMENT  (description + emitter-frequency data)
# ============================================================
PEST_ENRICHMENT: dict[str, dict] = {
    "Locust": {
        "display_name": "Locust / Grasshopper",
        "characteristics": (
            "Orthopteran pest insect capable of moving in devastating swarms. "
            "Devours leaves, stems and grains within hours. "
            "Particularly active during dry season and seasonal migrations."
        ),
        "emitter_frequency": "20–25 kHz",
        "emitter_message": (
            "Ultrasonic 22 kHz signal emitted by the rover — "
            "disrupts communication and gregarious behavior of locusts "
            "to repel them away from crop areas."
        ),
        "recommendations": [
            "Contact insecticide treatment (deltamethrin, malathion) if dense swarm",
            "Install insect nets on most sensitive crops",
            "Immediately report to plant protection authorities",
            "Keep ultrasonic emitter active continuously during migration season",
            "Coordinate with neighboring farms for group treatment",
        ],
    },
    "Moth": {
        "display_name": "Nocturnal Moth",
        "characteristics": (
            "Nocturnal lepidopteran whose larvae (caterpillars) cause significant damage "
            "to foliage, stems and fruits. "
            "Adults are attracted to light and lay eggs on leaves. "
            "Caterpillars can consume entire leaves within days."
        ),
        "emitter_frequency": "35–40 kHz",
        "emitter_message": (
            "Ultrasonic 38 kHz signal emitted by the rover — "
            "disrupts navigation of adult nocturnal moths "
            "and reduces their egg-laying activity on crops."
        ),
        "recommendations": [
            "Apply Bacillus thuringiensis (Bt) — caterpillar-specific biopesticide",
            "Install UV light traps near crop areas at night",
            "Natural insecticide treatment (pyrethrum, spinosad) if heavy infestation",
            "Regularly inspect leaf undersides to detect egg masses",
            "Manually remove visible egg masses (oothecae) from leaves",
        ],
    },
}

# Confidence thresholds for severity labelling
SEVERITY_THRESHOLDS = {"high": 0.80, "medium": 0.55}


# ============================================================
# MODEL SINGLETON
# ============================================================
_yolo_model = None
_yolo_available: Optional[bool] = None


def _get_severity(confidence: float) -> str:
    if confidence >= SEVERITY_THRESHOLDS["high"]:
        return "high"
    if confidence >= SEVERITY_THRESHOLDS["medium"]:
        return "medium"
    return "low"


def _is_available() -> bool:
    """Return True if best.pt exists and loads without error."""
    global _yolo_available, _yolo_model
    if _yolo_available is not None:
        return _yolo_available

    if not os.path.exists(YOLO_MODEL_PATH):
        logger.warning(
            f"[YoloInference] YOLO model not found at {YOLO_MODEL_PATH}. "
            "Pest detection (YOLO) will be disabled."
        )
        _yolo_available = False
        return False

    try:
        from ultralytics import YOLO  # type: ignore
        _yolo_model = YOLO(YOLO_MODEL_PATH)
        _yolo_available = True
        logger.info(
            f"[YoloInference] YOLO model loaded — "
            f"{len(_yolo_model.names)} classes: {list(_yolo_model.names.values())}"
        )
    except Exception as exc:
        logger.error(f"[YoloInference] Failed to load YOLO model: {exc}")
        _yolo_available = False

    return _yolo_available


def _null_result() -> dict:
    """Return a graceful null result when the model is unavailable."""
    return {
        "available":     False,
        "detected_pest": None,
        "pest_name":     None,
        "confidence":    None,
        "severity":      None,
        "top3":          [],
        "enrichment":    None,
        "bboxes":        [],
    }


# ============================================================
# PUBLIC PREDICT FUNCTION
# ============================================================
def predict_yolo(image_bytes: bytes) -> dict:
    """
    Run YOLO pest-detection inference on raw image bytes.

    If the model is unavailable, returns a graceful null result
    so the API can still respond without crashing.

    Returns:
        {
            "available":      bool,
            "detected_pest":  str | None,   # class name or None
            "pest_name":      str | None,   # French display name
            "confidence":     float | None, # 0.0–1.0 (best detection)
            "severity":       str | None,   # "low"|"medium"|"high"
            "top3":           list,         # [{class, confidence}, ...]
            "enrichment":     dict | None,  # PEST_ENRICHMENT entry
            "bboxes":         list,         # raw bounding boxes [{cls,conf,xyxyn}]
        }
    """
    if not _is_available():
        return _null_result()

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise ValueError(f"Cannot decode image: {exc}") from exc

    # Resize to 320 for 4x faster CPU inference, very important for i3 processors.
    results = _yolo_model(image, verbose=False, imgsz=320)

    if not results or results[0].boxes is None or len(results[0].boxes) == 0:
        # No detection at all
        return {
            "available":     True,
            "detected_pest": None,
            "pest_name":     "No pest detected",
            "confidence":    0.0,
            "severity":      "none",
            "top3":          [],
            "enrichment":    None,
            "bboxes":        [],
        }

    boxes = results[0].boxes

    # Pick the detection with the highest confidence
    best_idx   = int(boxes.conf.argmax())
    best_conf  = float(boxes.conf[best_idx])
    best_cls   = int(boxes.cls[best_idx])
    class_name = (_yolo_model.names.get(best_cls)
                  or YOLO_CLASS_NAMES.get(best_cls, f"class_{best_cls}"))

    # Build top-3 across all detections (deduplicated by class, keep highest conf)
    class_best: dict[str, float] = {}
    for i in range(len(boxes)):
        cname = _yolo_model.names.get(int(boxes.cls[i]), f"class_{int(boxes.cls[i])}")
        cconf = float(boxes.conf[i])
        if cname not in class_best or cconf > class_best[cname]:
            class_best[cname] = cconf

    top3 = sorted(class_best.items(), key=lambda x: x[1], reverse=True)[:3]
    top3_list = [
        {"class": name, "confidence": round(conf * 100, 1)}
        for name, conf in top3
    ]

    # Raw bounding boxes (normalised xyxy)
    bboxes = []
    for i in range(len(boxes)):
        bboxes.append({
            "cls":   _yolo_model.names.get(int(boxes.cls[i]), f"class_{int(boxes.cls[i])}"),
            "conf":  round(float(boxes.conf[i]), 4),
            "xyxyn": boxes.xyxyn[i].tolist() if hasattr(boxes, "xyxyn") else [],
        })

    enrichment = PEST_ENRICHMENT.get(class_name)
    pest_name  = enrichment["display_name"] if enrichment else YOLO_DISPLAY_NAMES.get(class_name, class_name)

    return {
        "available":     True,
        "detected_pest": class_name,
        "pest_name":     pest_name,
        "confidence":    round(best_conf, 4),
        "severity":      _get_severity(best_conf),
        "top3":          top3_list,
        "enrichment":    enrichment,
        "bboxes":        bboxes,
    }
