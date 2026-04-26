"""
Convert best.pt (YOLOv8 checkpoint) to ONNX at 320 x 320 resolution.

Output : best_320.onnx  (same directory as this script)

Usage:
    python convert_to_onnx.py
"""

import os
import sys
import time

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PT_PATH    = os.path.join(SCRIPT_DIR, "best.pt")
ONNX_PATH  = os.path.join(SCRIPT_DIR, "best_320.onnx")
IMG_SIZE   = 320

# ── Guard ─────────────────────────────────────────────────────────────────────
if not os.path.isfile(PT_PATH):
    print(f"[ERROR] Model not found: {PT_PATH}")
    sys.exit(1)

print("=" * 60)
print("  YOLOv8 -> ONNX conversion")
print(f"  Input  : {PT_PATH}")
print(f"  Output : {ONNX_PATH}")
print(f"  Size   : {IMG_SIZE} x {IMG_SIZE}")
print("=" * 60)

# ── Load model ────────────────────────────────────────────────────────────────
from ultralytics import YOLO

print("\n[1/3] Loading YOLOv8 checkpoint…")
t0 = time.time()
model = YOLO(PT_PATH)
print(f"      Done in {time.time()-t0:.2f}s")
print(f"      Task   : {model.task}")
print(f"      Names  : {model.names}")

# ── Export to ONNX ────────────────────────────────────────────────────────────
print(f"\n[2/3] Exporting to ONNX (imgsz={IMG_SIZE}, opset=12)…")
t1 = time.time()

exported = model.export(
    format   = "onnx",
    imgsz    = IMG_SIZE,
    opset    = 12,          # wide runtime compatibility
    simplify = True,        # onnx-simplifier removes dead nodes
    dynamic  = False,       # fixed batch=1 for edge deployment
    half     = False,       # FP32 — change to True for GPU half-precision
)
print(f"      Done in {time.time()-t1:.2f}s")

# ultralytics saves next to the .pt; rename/move to our desired path
default_out = str(exported)          # ultralytics returns the output path
if os.path.abspath(default_out) != os.path.abspath(ONNX_PATH):
    import shutil
    shutil.move(default_out, ONNX_PATH)
    print(f"      Moved  : {default_out} -> {ONNX_PATH}")

# ── Verify ────────────────────────────────────────────────────────────────────
print("\n[3/3] Verifying ONNX model…")
import onnx
onnx_model = onnx.load(ONNX_PATH)
onnx.checker.check_model(onnx_model)

size_mb = os.path.getsize(ONNX_PATH) / (1024 * 1024)

# Print input / output shapes
graph = onnx_model.graph
inputs  = [(i.name, [d.dim_value for d in i.type.tensor_type.shape.dim]) for i in graph.input]
outputs = [(o.name, [d.dim_value for d in o.type.tensor_type.shape.dim]) for o in graph.output]

print(f"      ONNX check  : PASSED [OK]")
print(f"      File size   : {size_mb:.2f} MB")
print(f"      Inputs  : {inputs}")
print(f"      Outputs : {outputs}")

# ── Quick inference smoke-test ─────────────────────────────────────────────────
print("\n[Bonus] Smoke-test with ONNXRuntime…")
import numpy as np
import onnxruntime as ort

sess  = ort.InferenceSession(ONNX_PATH, providers=["CPUExecutionProvider"])
dummy = np.zeros((1, 3, IMG_SIZE, IMG_SIZE), dtype=np.float32)
inp   = sess.get_inputs()[0].name
t2    = time.time()
out   = sess.run(None, {inp: dummy})
latency_ms = (time.time() - t2) * 1000
print(f"      Output shape : {out[0].shape}")
print(f"      Latency      : {latency_ms:.1f} ms  (CPU, dummy input)")

print("\n" + "=" * 60)
print(f"  Conversion complete -> {ONNX_PATH}")
print("=" * 60)
