import os
import io
import cv2
import base64
import json
import numpy as np
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
import uvicorn
import onnxruntime as ort
import tifffile
from pydantic import BaseModel

uploaded_images_cache = {}

from oclast.config import IMG_SIZE
from oclast.data import pad_image, get_tile_coordinates
from oclast.preprocessor import preprocess_v9
from oclast.onnx_engine import get_model, predict_batch
from oclast.biology import extract_biology

import threading
import webbrowser
import time
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    def open_browser():
        time.sleep(1)
        webbrowser.open("http://127.0.0.1:8000")
    threading.Thread(target=open_browser, daemon=True).start()
    yield

app = FastAPI(title="OCLAST Dashboard API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

models_dict = {}

def get_model(name):
    if name not in models_dict:
        path = os.path.join(os.path.dirname(__file__), 'Model Weights', f'{name}.onnx')
        if not os.path.exists(path):
            path = os.path.join(os.path.dirname(__file__), 'Model Weights', f'{name}_quantized.onnx')
            if not os.path.exists(path):
                raise FileNotFoundError(f"Model {name} not found")
        models_dict[name] = ort.InferenceSession(path)
    return models_dict[name]

@app.post("/preview")
async def preview_endpoint(file: UploadFile = File(...)):
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if img_bgr is None:
        return {"preview": None}
        
    h, w = img_bgr.shape[:2]
    ratio = 800 / w
    new_size = (800, int(h * ratio))
    resized = cv2.resize(img_bgr, new_size)
    
    _, buffer = cv2.imencode('.jpg', resized)
    b64_img = base64.b64encode(buffer).decode('utf-8')
    return {"preview": f"data:image/jpeg;base64,{b64_img}"}

@app.post("/predict")
async def predict_endpoint(file: UploadFile = File(...), model_type: str = Form("unetplusplus")):
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    uploaded_images_cache[file.filename] = img_bgr

    base_name = os.path.splitext(file.filename)[0] if file.filename else "specimen"

    def generate():
        session = get_model(model_type)
        padded_img, h, w = pad_image(img_bgr, IMG_SIZE)
        coords = get_tile_coordinates(padded_img.shape, IMG_SIZE)
        
        total_cells = 0
        all_areas = []
        all_circs = []
        all_solids = []
        
        heatmap_data = np.zeros(padded_img.shape[:2], dtype=np.float32)

        total_coords = len(coords)
        for i, (y, x) in enumerate(coords):
            patch = padded_img[y:y+IMG_SIZE, x:x+IMG_SIZE]
            preprocessed_patch = preprocess_v9(patch)
            
            # Predict
            batch_arr = np.expand_dims(preprocessed_patch, axis=0).astype(np.float32)
            preds = predict_batch(session, batch_arr)
            
            # Handle deep supervision models (multiple outputs)
            prob_map = preds[-1] if len(preds) > 1 else preds[0]
            
            # Usually [H, W, 1] or [1, H, W, 1]
            if prob_map.ndim == 4: prob_map = prob_map[0]
            if prob_map.shape[-1] == 1: prob_map = prob_map[..., 0]
            
            mask, count, centroids, areas, circs, solids, eccs, contours = extract_biology(prob_map)
            
            total_cells += count
            all_areas.extend(areas)
            all_circs.extend(circs)
            all_solids.extend(solids)
            
            heatmap_data[y:y+IMG_SIZE, x:x+IMG_SIZE] = count
            
            patch_rgb = cv2.cvtColor(patch, cv2.COLOR_RGB2RGB if hasattr(cv2, 'COLOR_RGB2RGB') else cv2.COLOR_BGR2RGB)
            overlay = np.zeros_like(patch_rgb)
            if count > 0:
                overlay[mask > 0] = [255, 0, 255]
            blended = cv2.addWeighted(patch_rgb, 0.7, overlay, 0.5, 0)
            
            # Confidence Heatmap (Saliency)
            conf_heatmap = cv2.applyColorMap(np.uint8(255 * prob_map), cv2.COLORMAP_TURBO)
            conf_blended = cv2.addWeighted(patch_rgb, 0.4, conf_heatmap, 0.6, 0)
            
            cells = []
            for idx in range(count):
                cy, cx = centroids[idx]
                cv2.putText(blended, str(idx+1), (int(cx)-4, int(cy)+4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.putText(conf_blended, str(idx+1), (int(cx)-4, int(cy)+4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1, cv2.LINE_AA)
                cells.append({
                    "id": idx + 1,
                    "area": float(areas[idx]),
                    "circularity": float(circs[idx]),
                    "centroid": [int(cx), int(cy)],
                    "contour": contours[idx] if idx < len(contours) else [],
                    "manual": False
                })
            
            _, buffer = cv2.imencode('.jpg', cv2.cvtColor(blended, cv2.COLOR_RGB2BGR))
            b64_img = base64.b64encode(buffer).decode('utf-8')
            
            _, c_buffer = cv2.imencode('.jpg', conf_blended)
            b64_conf = base64.b64encode(c_buffer).decode('utf-8')

            _, r_buffer = cv2.imencode('.jpg', patch)
            b64_raw = base64.b64encode(r_buffer).decode('utf-8')
                
            tile_data = {
                "tile_name": f"{base_name}_tile_{i+1}",
                "y": y,
                "x": x,
                "count": count,
                "mask": f"data:image/jpeg;base64,{b64_img}",
                "raw": f"data:image/jpeg;base64,{b64_raw}",
                "confidence": f"data:image/jpeg;base64,{b64_conf}",
                "cells": cells
            }
            
            progress = (i + 1) / total_coords
            yield json.dumps({"type": "progress", "progress": progress, "tile": tile_data}) + "\n"
            
        heatmap_b64 = None
        max_count = np.max(heatmap_data)
        if max_count > 0:
            heatmap_norm_u8 = ((heatmap_data / max_count) * 255).astype(np.uint8)
            heatmap_colored = cv2.applyColorMap(heatmap_norm_u8, cv2.COLORMAP_MAGMA)
            alpha = np.expand_dims((heatmap_data / max_count).astype(np.float32), axis=-1)
            blended_heatmap = (padded_img.astype(np.float32) * (1.0 - alpha * 0.7) + heatmap_colored.astype(np.float32) * (alpha * 0.7)).astype(np.uint8)
            _, h_buffer = cv2.imencode('.jpg', blended_heatmap)
            heatmap_b64 = f"data:image/jpeg;base64,{base64.b64encode(h_buffer).decode('utf-8')}"

        avg_size = sum(all_areas) / len(all_areas) if all_areas else 0
        avg_circ = sum(all_circs) / len(all_circs) if all_circs else 0
        avg_solid = sum(all_solids) / len(all_solids) if all_solids else 0

        yield json.dumps({
            "type": "final",
            "total_cells": total_cells,
            "average_size": avg_size,
            "average_circularity": avg_circ,
            "average_solidity": avg_solid,
            "orig_width": int(w),
            "orig_height": int(h),
            "areas": all_areas,
            "circularities": all_circs,
            "heatmap": heatmap_b64
        }) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")

class SaveMaskRequest(BaseModel):
    filename: str
    orig_width: int
    orig_height: int
    tiles: list

@app.post("/save-training-mask")
async def save_training_mask_endpoint(req: SaveMaskRequest):
    base_name = os.path.splitext(req.filename)[0]
    mask_filename = f"{base_name}_mask.tif"
    
    # Generate binary mask (0 = background, 255 = osteoclast cells)
    mask = np.zeros((req.orig_height, req.orig_width), dtype=np.uint8)
    
    total_cells = 0
    manual_cells = 0
    ai_cells = 0
    
    for tile in req.tiles:
        tile_x = int(tile.get("x", 0))
        tile_y = int(tile.get("y", 0))
        for cell in tile.get("cells", []):
            contour = cell.get("contour", [])
            if len(contour) >= 3:
                pts = [[int(pt["x"]) + tile_x, int(pt["y"]) + tile_y] for pt in contour]
                pts_arr = np.array(pts, dtype=np.int32)
                cv2.fillPoly(mask, [pts_arr], 255)
                total_cells += 1
                if cell.get("manual", False):
                    manual_cells += 1
                else:
                    ai_cells += 1

    # Local training data directories
    training_dir = os.path.join(os.path.dirname(__file__), "training_data")
    masks_dir = os.path.join(training_dir, "masks")
    images_dir = os.path.join(training_dir, "images")
    os.makedirs(masks_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)
    
    # Save .tif binary mask using tifffile
    mask_path = os.path.join(masks_dir, mask_filename)
    tifffile.imwrite(mask_path, mask)
    
    # Save paired image if available
    img_saved_path = None
    if req.filename in uploaded_images_cache:
        img_bgr = uploaded_images_cache[req.filename]
        img_filename = f"{base_name}.tif"
        img_saved_path = os.path.join(images_dir, img_filename)
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        tifffile.imwrite(img_saved_path, img_rgb)
    
    # Update manifest.json
    manifest_path = os.path.join(training_dir, "manifest.json")
    manifest = []
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r") as mf:
                manifest = json.load(mf)
        except Exception:
            manifest = []
            
    record = {
        "id": f"mask_{int(time.time())}",
        "original_filename": req.filename,
        "mask_file": f"masks/{mask_filename}",
        "image_file": f"images/{base_name}.tif" if img_saved_path else None,
        "dimensions": [req.orig_width, req.orig_height],
        "total_cells": total_cells,
        "manual_cells": manual_cells,
        "ai_cells": ai_cells,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    manifest = [m for m in manifest if m.get("original_filename") != req.filename]
    manifest.insert(0, record)
    with open(manifest_path, "w") as mf:
        json.dump(manifest, mf, indent=2)

    # Lightweight base64 preview of binary mask
    preview_w = min(800, req.orig_width)
    preview_h = max(1, int(req.orig_height * (preview_w / max(1, req.orig_width))))
    resized_mask = cv2.resize(mask, (preview_w, preview_h), interpolation=cv2.INTER_NEAREST)
    _, m_buffer = cv2.imencode('.png', resized_mask)
    preview_b64 = f"data:image/png;base64,{base64.b64encode(m_buffer).decode('utf-8')}"

    return {
        "status": "success",
        "mask_filename": mask_filename,
        "mask_path": mask_path,
        "image_path": img_saved_path,
        "total_cells": total_cells,
        "manual_cells": manual_cells,
        "ai_cells": ai_cells,
        "preview": preview_b64,
        "download_url": f"http://localhost:8000/download-mask/{mask_filename}",
        "total_dataset_count": len(manifest)
    }

@app.get("/download-mask/{mask_filename}")
async def download_mask_endpoint(mask_filename: str):
    mask_path = os.path.join(os.path.dirname(__file__), "training_data", "masks", mask_filename)
    if not os.path.exists(mask_path):
        return {"error": "Mask file not found"}
    return FileResponse(
        mask_path, 
        media_type="image/tiff", 
        filename=mask_filename
    )

@app.get("/training-data/list")
async def list_training_data_endpoint():
    manifest_path = os.path.join(os.path.dirname(__file__), "training_data", "manifest.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r") as mf:
                data = json.load(mf)
                return {"items": data, "count": len(data)}
        except Exception:
            return {"items": [], "count": 0}
    return {"items": [], "count": 0}

frontend_path = os.path.join(os.path.dirname(__file__), 'frontend', 'dist')
if os.path.isdir(frontend_path):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_path, "assets")), name="assets")
    
    @app.get("/")
    @app.get("/{catchall:path}")
    async def serve_react_app(catchall: str = ""):
        return FileResponse(os.path.join(frontend_path, "index.html"))

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    uvicorn.run(app, host="127.0.0.1", port=8000)
