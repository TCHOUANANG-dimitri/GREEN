# ============================================================
# GREEN App — Pest Detection Inference Engine (Phase MVP)
#
# Second AI model dedicated to pest / ravageur identification.
# Architecture: same EfficientNet-B0 backbone as the disease model.
#
# ⚠️  SETUP REQUIRED:
#   1. Set PEST_MODEL_PATH in your .env file.
#   2. Update PEST_CLASS_NAMES below to match the exact
#      alphabetical order of your training dataset folders.
#   3. Update PEST_COUNT to the number of output classes.
#
# If the model file is not found, pest inference is DISABLED
# gracefully — the API still works, pest fields will be null.
# ============================================================

import io
import logging
import os
from typing import Optional

import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms

from config import PEST_MODEL_PATH

logger = logging.getLogger(__name__)


# ============================================================
# PEST CLASS NAMES  — ⚠️  UPDATE THESE TO MATCH YOUR MODEL
# ============================================================
# Common agricultural pests in Central/West Africa (placeholder mapping).
# Replace with the exact class names from your training dataset.
PEST_CLASS_NAMES = [
    "Aphid",                      # 0 — Puceron
    "Cassava_Mealybug",           # 1 — Cochenille du manioc
    "Fall_Armyworm",              # 2 — Légionnaire d'automne (maïs)
    "Fruit_Fly",                  # 3 — Mouche des fruits
    "Leaf_Miner",                 # 4 — Mineuse des feuilles
    "None",                       # 5 — Aucun ravageur détecté
    "Red_Spider_Mite",            # 6 — Acarien rouge
    "Stem_Borer",                 # 7 — Foreur de tige
    "Thrips",                     # 8 — Thrips
    "Whitefly",                   # 9 — Mouche blanche
]

NO_PEST_CLASS = "None"   # Class name that means "no pest detected"

PEST_PLANT_HINTS = {
    "Cassava_Mealybug":  "manioc",
    "Fall_Armyworm":     "maïs",
    "Stem_Borer":        "maïs",
}

SEVERITY_THRESHOLDS = {
    "high":   0.80,
    "medium": 0.55,
}


# ============================================================
# PRE-PROCESSING (identical to disease model)
# ============================================================
_transform = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(
        mean=[0.485, 0.456, 0.406],
        std =[0.229, 0.224, 0.225],
    ),
])


# ============================================================
# MODEL SINGLETON
# ============================================================
_pest_model: Optional[torch.nn.Module] = None
_pest_available: Optional[bool] = None   # None = not yet checked


def _build_model(num_classes: int) -> torch.nn.Module:
    try:
        import timm  # type: ignore
        model = timm.create_model("efficientnet_b0", pretrained=False, num_classes=num_classes)
        return model
    except ImportError:
        from torchvision.models import efficientnet_b0
        model = efficientnet_b0(weights=None)
        in_features = model.classifier[1].in_features
        model.classifier[1] = torch.nn.Linear(in_features, num_classes)
        return model


def _is_available() -> bool:
    """Return True if the pest model file exists and loads cleanly."""
    global _pest_available, _pest_model
    if _pest_available is not None:
        return _pest_available

    if not os.path.exists(PEST_MODEL_PATH):
        logger.warning(
            f"[PestInference] Model file not found at {PEST_MODEL_PATH}. "
            "Pest detection will be disabled. Set PEST_MODEL_PATH in .env."
        )
        _pest_available = False
        return False

    try:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = _build_model(num_classes=len(PEST_CLASS_NAMES))
        state_dict = torch.load(PEST_MODEL_PATH, map_location=device)
        if isinstance(state_dict, dict) and "state_dict" in state_dict:
            state_dict = state_dict["state_dict"]
        elif isinstance(state_dict, dict) and "model_state_dict" in state_dict:
            state_dict = state_dict["model_state_dict"]
        model.load_state_dict(state_dict, strict=True)
        model.to(device)
        model.eval()
        _pest_model = model
        _pest_available = True
        logger.info(f"[PestInference] Pest model loaded on {device} — {len(PEST_CLASS_NAMES)} classes.")
    except Exception as exc:
        logger.error(f"[PestInference] Failed to load pest model: {exc}")
        _pest_available = False

    return _pest_available


def _get_severity(confidence: float) -> str:
    if confidence >= SEVERITY_THRESHOLDS["high"]:
        return "high"
    if confidence >= SEVERITY_THRESHOLDS["medium"]:
        return "medium"
    return "low"


# ============================================================
# PUBLIC PREDICT FUNCTION
# ============================================================
def predict_pest(image_bytes: bytes) -> dict:
    """
    Run pest detection inference on raw image bytes.

    If the model is not available, returns a graceful null result
    so the API can still respond without crashing.

    Returns:
        {
            "available":      bool,   # False if model not loaded
            "detected_pest":  str,    # pest class ID or "none"
            "pest_name":      str,    # human-readable label
            "confidence":     float,
            "severity":       str,
            "top3":           list,
        }
    """
    if not _is_available():
        return {
            "available":     False,
            "detected_pest": None,
            "pest_name":     None,
            "confidence":    None,
            "severity":      None,
            "top3":          [],
        }

    model  = _pest_model
    device = next(model.parameters()).device

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise ValueError(f"Cannot decode image: {exc}") from exc

    tensor = _transform(image).unsqueeze(0).to(device)

    with torch.no_grad():
        logits = model(tensor)
        probs  = F.softmax(logits, dim=1)[0]

    confidence, class_idx = probs.max(0)
    confidence = confidence.item()
    class_idx  = class_idx.item()
    class_raw  = PEST_CLASS_NAMES[class_idx]

    no_pest    = class_raw == NO_PEST_CLASS
    pest_id    = "none" if no_pest else class_raw.lower()
    pest_name  = "No pest detected" if no_pest else class_raw.replace("_", " ")

    top3_indices = probs.topk(min(3, len(PEST_CLASS_NAMES))).indices.tolist()
    top3 = [
        {
            "class":      PEST_CLASS_NAMES[i].replace("_", " "),
            "confidence": round(probs[i].item() * 100, 1),
        }
        for i in top3_indices
    ]

    return {
        "available":     True,
        "detected_pest": pest_id,
        "pest_name":     pest_name,
        "confidence":    round(confidence, 4),
        "severity":      _get_severity(confidence) if not no_pest else "none",
        "top3":          top3,
    }
