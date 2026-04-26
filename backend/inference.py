# ============================================================
# GREEN App — EfficientNet Disease Inference Engine
#
# Loads the best_efficientnet.pth model once at startup and
# exposes a single `predict(image_bytes)` function used by
# the drone router and upload endpoint.
#
# Architecture: timm EfficientNet-B0 (1280-d features → 11 classes)
#
# ⚠️  CLASS ORDER — MUST MATCH TRAINING
# The list below maps output index → class label.
# If predictions look wrong, reorder this list to match the
# alphabetical order of your training dataset folders.
# ============================================================

import io
import logging
from typing import Optional

from PIL import Image

from config import MODEL_PATH

logger = logging.getLogger(__name__)

# torch and torchvision are imported lazily inside functions so that
# importing this module does not block the server startup.


# ============================================================
# CLASS NAMES  (index → label)
# 11 classes — must match the EXACT training folder order.
#
# ⚠️  ORDER WARNING
# PyTorch ImageFolder sorts folder names with Python's built-in
# sort(), which is case-sensitive (uppercase A–Z before lowercase).
# The order below assumes Linux case-sensitive alphabetical sort
# of the original training folder names:
#   "Cassava mosaic", "Corn brown spots", "Corn healthy",
#   "Corn leaf blight", "Corn mildew", "Corn streak",
#   "Corn stripe", "Corn yellowing", "Tomato Brown Spots",
#   "Tomato blight leaf", "Tomato healthy"
# If predictions look wrong, reorder this list to match your
# training folder alphabetical order exactly.
# ============================================================
CLASS_NAMES = [
    "Cassava_Mosaic",       # 0  ← "Cassava mosaic"
    "Corn_Brown_Spots",     # 1  ← "Corn brown spots"
    "Corn_Healthy",         # 2  ← "Corn healthy"
    "Corn_Leaf_Blight",     # 3  ← "Corn leaf blight"
    "Corn_Mildew",          # 4  ← "Corn mildew"
    "Corn_Streak",          # 5  ← "Corn streak"
    "Corn_Stripe",          # 6  ← "Corn stripe"
    "Corn_Yellowing",       # 7  ← "Corn yellowing"
    "Tomato_Brown_Spots",   # 8  ← "Tomato Brown Spots"
    "Tomato_Blight_Leaf",   # 9  ← "Tomato blight leaf"
    "Tomato_Healthy",       # 10 ← "Tomato healthy"
]

# "Healthy" class names — used to set detected_disease = "healthy" in the DB
HEALTHY_CLASSES = {"Corn_Healthy", "Tomato_Healthy"}

# Maps class name prefix → plant type stored in DB (English)
PLANT_TYPE_MAP = {
    "Cassava": "Cassava",
    "Corn":    "Corn",
    "Tomato":  "Tomato",
}

# Human-readable English display names for each class (API response)
CLASS_EN_NAMES: dict[str, str] = {
    "Cassava_Mosaic":     "Cassava Mosaic",
    "Corn_Brown_Spots":   "Corn Brown Spots",
    "Corn_Healthy":       "Healthy Corn",
    "Corn_Leaf_Blight":   "Corn Leaf Blight",
    "Corn_Mildew":        "Corn Mildew",
    "Corn_Streak":        "Corn Streak",
    "Corn_Stripe":        "Corn Stripe",
    "Corn_Yellowing":     "Corn Yellowing",
    "Tomato_Brown_Spots": "Tomato Brown Spots",
    "Tomato_Blight_Leaf": "Tomato Blight Leaf",
    "Tomato_Healthy":     "Healthy Tomato",
}

# Human-readable French display names for each class (for reference/translation)
CLASS_FR_NAMES: dict[str, str] = {
    "Cassava_Mosaic":     "Mosaïque du manioc",
    "Corn_Brown_Spots":   "Taches brunes du maïs",
    "Corn_Healthy":       "Maïs sain",
    "Corn_Leaf_Blight":   "Brûlure foliaire du maïs",
    "Corn_Mildew":        "Mildiou du maïs",
    "Corn_Streak":        "Stries du maïs",
    "Corn_Stripe":        "Rayures du maïs",
    "Corn_Yellowing":     "Jaunissement du maïs",
    "Tomato_Brown_Spots": "Taches brunes de la tomate",
    "Tomato_Blight_Leaf": "Brûlure foliaire de la tomate",
    "Tomato_Healthy":     "Tomate saine",
}

# Confidence thresholds for severity labelling
SEVERITY_THRESHOLDS = {
    "high":   0.80,   # ≥ 80 % → high risk
    "medium": 0.55,   # 55–79 % → moderate
    "low":    0.0,    # < 55 % → low / uncertain
}


# ============================================================
# IMAGE PRE-PROCESSING PIPELINE  (lazy — built on first use)
# ============================================================
_transform = None

def _get_transform():
    """Return the torchvision transform pipeline, building it on first call."""
    global _transform
    if _transform is None:
        from torchvision import transforms  # lazy import
        _transform = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std =[0.229, 0.224, 0.225],
            ),
        ])
    return _transform


# ============================================================
# MODEL LOADER  (singleton — loaded once at first call)
# ============================================================
_model = None   # type: ignore[assignment]


def _build_efficientnet(num_classes: int, state_dict_keys: list):
    """
    Reconstruct the exact EfficientNet-B0 architecture used during training
    by inspecting the saved state-dict keys.

    Three possible formats:
    ┌──────────────────────────────────────────────────────────────┐
    │ Format A — timm backbone + Sequential head (custom training) │
    │   Keys: conv_stem.*, blocks.*, classifier.1.*               │
    │   Build: timm backbone, replace classifier with             │
    │           nn.Sequential(Dropout, Linear)                    │
    ├──────────────────────────────────────────────────────────────┤
    │ Format B — standard timm (direct Linear head)               │
    │   Keys: conv_stem.*, classifier.weight                      │
    │   Build: timm.create_model(num_classes=N)                   │
    ├──────────────────────────────────────────────────────────────┤
    │ Format C — torchvision                                       │
    │   Keys: features.*, classifier.1.*                          │
    │   Build: torchvision efficientnet_b0, replace head          │
    └──────────────────────────────────────────────────────────────┘
    """
    has_conv_stem  = any("conv_stem" in k for k in state_dict_keys)
    has_features   = any("features."  in k for k in state_dict_keys)
    has_cls1       = any("classifier.1" in k for k in state_dict_keys)

    import torch  # lazy import

    # ── Format A: timm backbone + manual Sequential head ──────
    if has_conv_stem and has_cls1:
        try:
            import timm  # type: ignore
            model = timm.create_model("efficientnet_b0", pretrained=False, num_classes=num_classes)
            in_features = model.classifier.in_features
            model.classifier = torch.nn.Sequential(
                torch.nn.Dropout(p=0.2, inplace=True),
                torch.nn.Linear(in_features, num_classes),
            )
            logger.info("Model built: timm backbone + Sequential head (Format A).")
            return model
        except ImportError:
            pass

    # ── Format B: standard timm ───────────────────────────────
    if has_conv_stem and not has_cls1:
        try:
            import timm  # type: ignore
            model = timm.create_model("efficientnet_b0", pretrained=False, num_classes=num_classes)
            logger.info("Model built: standard timm efficientnet_b0 (Format B).")
            return model
        except ImportError:
            pass

    # ── Format C: torchvision (fallback) ──────────────────────
    from torchvision.models import efficientnet_b0
    model = efficientnet_b0(weights=None)
    in_features = model.classifier[1].in_features
    model.classifier[1] = torch.nn.Linear(in_features, num_classes)
    logger.info("Model built: torchvision efficientnet_b0 (Format C).")
    return model


def get_model():
    """Return the loaded model (lazy singleton — imports torch on first call)."""
    global _model
    if _model is None:
        import torch  # lazy import
        # Limit CPU threads to prevent CPU context-switch thrashing
        if getattr(torch, "set_num_threads", None):
            torch.set_num_threads(2)
            
        logger.info(f"Loading EfficientNet model from {MODEL_PATH}")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        state_dict = torch.load(MODEL_PATH, map_location=device)

        # Unwrap checkpoint wrappers
        if isinstance(state_dict, dict) and "state_dict" in state_dict:
            state_dict = state_dict["state_dict"]
        elif isinstance(state_dict, dict) and "model_state_dict" in state_dict:
            state_dict = state_dict["model_state_dict"]

        model = _build_efficientnet(
            num_classes=len(CLASS_NAMES),
            state_dict_keys=list(state_dict.keys()),
        )
        model.load_state_dict(state_dict, strict=True)
        model.to(device)
        model.eval()
        _model = model
        logger.info(f"Model loaded on {device} — {len(CLASS_NAMES)} classes.")

    return _model


# ============================================================
# INFERENCE FUNCTION
# ============================================================
def _get_severity(confidence: float) -> str:
    if confidence >= SEVERITY_THRESHOLDS["high"]:
        return "high"
    if confidence >= SEVERITY_THRESHOLDS["medium"]:
        return "medium"
    return "low"


def predict(image_bytes: bytes) -> dict:
    """
    Run EfficientNet inference on raw image bytes.

    Returns:
        {
            "class_raw":       str,    # e.g. "Corn_Leaf_Blight"
            "detected_disease": str,   # disease ID for the DB ("healthy" if healthy)
            "disease_name":    str,    # human-readable label
            "plant_type":      str,    # "tomate" | "maïs" | "manioc"
            "confidence":      float,  # 0.0 – 1.0
            "severity":        str,    # "low" | "medium" | "high"
            "top3":            list,   # [{class, confidence}, ...] for display
        }
    """
    model = get_model()
    device = next(model.parameters()).device

    # Decode and preprocess
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise ValueError(f"Cannot decode image: {exc}") from exc

    import torch                    # lazy — already cached by Python after first import
    import torch.nn.functional as F

    tensor = _get_transform()(image).unsqueeze(0).to(device)

    # Forward pass — inference_mode fully disables autograd (faster than no_grad)
    with torch.inference_mode():
        logits = model(tensor)                      # (1, 11)
        probs  = F.softmax(logits, dim=1)[0]        # (11,)

    # Top-1 prediction
    confidence, class_idx = probs.max(0)
    confidence = confidence.item()
    class_idx  = class_idx.item()
    class_raw  = CLASS_NAMES[class_idx]

    # Derive plant type and disease ID
    prefix     = class_raw.split("_")[0]            # "Cassava" | "Corn" | "Tomato"
    plant_type = PLANT_TYPE_MAP.get(prefix, prefix.lower())
    is_healthy = class_raw in HEALTHY_CLASSES

    # Build a human-readable disease name
    if is_healthy:
        disease_name     = CLASS_EN_NAMES.get(class_raw, "Healthy")
        detected_disease = "healthy"
    else:
        disease_name     = CLASS_EN_NAMES.get(class_raw, class_raw.replace("_", " "))
        detected_disease = class_raw  # used as disease ID in the DB

    # Top-3 for the fiche terrain display
    top3_indices = probs.topk(3).indices.tolist()
    top3 = [
        {
            "class":      CLASS_NAMES[i].replace("_", " "),
            "confidence": round(probs[i].item() * 100, 1),
        }
        for i in top3_indices
    ]

    return {
        "class_raw":        class_raw,
        "detected_disease": detected_disease,
        "disease_name":     disease_name,
        "plant_type":       plant_type,
        "confidence":       round(confidence, 4),
        "severity":         _get_severity(confidence),
        "top3":             top3,
    }
