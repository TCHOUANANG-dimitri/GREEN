import os
import sys
import shutil
import subprocess

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Set MODEL_PATH env var before importing config/inference
os.environ["MODEL_PATH"] = r"f:\Projects\GREEN\Models\best_efficientnet.pth"

backend_path = r"f:\Projects\GREEN\backend"
sys.path.append(backend_path)

import torch
from inference import get_model, CLASS_NAMES

def main():
    print("==================================================")
    print("STEP 1: Loading PyTorch model...")
    print("==================================================")
    # This will load the model using the backend's get_model function
    # which automatically reconstructs the architecture (Format A/B/C)
    model = get_model()
    model.eval()
    print("PyTorch model loaded successfully.\n")

    # Export to ONNX
    onnx_path = r"f:\Projects\GREEN\Models\best_efficientnet.onnx"
    print("==================================================")
    print(f"STEP 2: Exporting model to ONNX: {onnx_path}")
    print("==================================================")
    dummy_input = torch.randn(1, 3, 224, 224)
    
    # We export with dynamic batch size
    torch.onnx.export(
        model,
        dummy_input,
        onnx_path,
        export_params=True,
        opset_version=18,
        do_constant_folding=True,
        input_names=['input'],
        output_names=['output'],
        dynamic_axes={'input': {0: 'batch_size'}, 'output': {0: 'batch_size'}}
    )
    print("ONNX export complete.\n")

    # Run onnx2tf to convert ONNX to TFLite
    output_dir = r"f:\Projects\GREEN\Models\tflite_output"
    print("==================================================")
    print(f"STEP 3: Running onnx2tf. Output directory: {output_dir}")
    print("==================================================")
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    # Run onnx2tf command
    # -i: input ONNX path
    # -o: output folder path
    cmd = ["onnx2tf", "-i", onnx_path, "-o", output_dir]
    print(f"Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    print("\n--- onnx2tf stdout ---")
    print(result.stdout)
    print("--- onnx2tf stderr ---")
    print(result.stderr)
    
    if result.returncode != 0:
        print("Error: onnx2tf failed!")
        sys.exit(1)
        
    print("onnx2tf finished successfully.\n")
    
    # Find the generated .tflite files
    tflite_files = []
    for root, dirs, files in os.walk(output_dir):
        for f in files:
            if f.endswith(".tflite"):
                tflite_files.append(os.path.join(root, f))
                
    print(f"Found TFLite files: {tflite_files}")
    if not tflite_files:
        print("Error: No TFLite file found in output directory!")
        sys.exit(1)
        
    # We will use the float32 one if multiple are found, or the first one
    tflite_path = None
    for f in tflite_files:
        if "float32" in f:
            tflite_path = f
            break
    if not tflite_path:
        tflite_path = tflite_files[0]
        
    print(f"Selected TFLite model for verification: {tflite_path}\n")
    
    # Run verification/test inference on the TFLite model
    print("==================================================")
    print("STEP 4: Running verification on the TFLite model...")
    print("==================================================")
    import tensorflow as tf
    import numpy as np
    
    interpreter = tf.lite.Interpreter(model_path=tflite_path)
    interpreter.allocate_tensors()
    
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    
    print("Input details:")
    for detail in input_details:
        print(f"  Name: {detail['name']}, Shape: {detail['shape']}, Type: {detail['dtype']}")
        
    print("\nOutput details:")
    for detail in output_details:
        print(f"  Name: {detail['name']}, Shape: {detail['shape']}, Type: {detail['dtype']}")
        
    # Let's run a dummy prediction
    input_shape = input_details[0]['shape']
    # If the model has dynamic batch size, replace any negative dimension with 1
    input_shape = [dim if dim > 0 else 1 for dim in input_shape]
    print(f"\nUsing input shape for verification: {input_shape}")
    
    dummy_tensor = np.random.randn(*input_shape).astype(np.float32)
    interpreter.set_tensor(input_details[0]['index'], dummy_tensor)
    interpreter.invoke()
    
    output_data = interpreter.get_tensor(output_details[0]['index'])
    print(f"Verification output shape: {output_data.shape}")
    print("Successfully ran test inference on the TFLite model!\n")
    
    # Move/copy to Desktop
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    dest_path = os.path.join(desktop, "best_efficientnet.tflite")
    
    print("==================================================")
    print(f"STEP 5: Copying TFLite model to Desktop: {dest_path}")
    print("==================================================")
    try:
        shutil.copy2(tflite_path, dest_path)
        print("SUCCESS: File successfully copied to Desktop!")
    except Exception as e:
        print(f"Error copying file to desktop: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
