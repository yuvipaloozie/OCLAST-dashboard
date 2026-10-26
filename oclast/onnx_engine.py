import os
import numpy as np
import onnxruntime as ort
from .config import IMG_SIZE, NUM_CLASSES

_session_instance = None

def get_model():
    global _session_instance
    if _session_instance is None:
        model_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'oclast_model.onnx'))
        print(f"Loading ONNX Runtime Session from {model_path}...")
        
        # Attempt GPU acceleration via DirectML, fallback to CPU
        _session_instance = ort.InferenceSession(model_path, providers=['DmlExecutionProvider', 'CPUExecutionProvider'])
        print("ONNX model loaded successfully.")
    return _session_instance

def predict_batch(session, patch_batch):
    # The input name is typically "input" based on our tf2onnx conversion
    input_name = session.get_inputs()[0].name
    
    # Run inference
    outputs = session.run(None, {input_name: patch_batch})
    
    # Handle Deep Supervision list output (UNet++ outputs a list of intermediate outputs)
    # The final prediction is usually the last one
    preds = outputs[-1]
    
    # Strip the channel dimension (BATCH, 512, 512, 1) -> (BATCH, 512, 512)
    return preds[:, :, :, 0]
