import os
import streamlit as st
import cv2
import numpy as np
import pandas as pd
import onnxruntime as ort

from oclast.config import IMG_SIZE, BATCH_SIZE
from oclast.data import pad_image, get_tile_coordinates
from oclast.preprocessor import preprocess_v9
from oclast.onnx_engine import get_model, predict_batch
from oclast.biology import extract_biology

st.set_page_config(page_title="OCLAST Dashboard", layout="wide")

st.title("OCLAST Microscopy Analysis (Advanced Prototype)")
st.markdown("Upload a cellular microscopy image to extract advanced morphometrics and density heatmaps.")

uploaded_file = st.file_uploader("Choose an image...", type=["tif", "png", "jpg", "jpeg"])

if uploaded_file is not None:
    file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
    img_bgr = cv2.imdecode(file_bytes, 1)
    
    st.image(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB), caption="Uploaded Image", use_container_width=True)
    
    if st.button("Run Full FOV Extraction"):
        with st.spinner("Processing image through UNet++ Inference Engine..."):
            padded_img, h, w = pad_image(img_bgr, IMG_SIZE)
            coords = get_tile_coordinates(padded_img.shape, IMG_SIZE)
            
            session = get_model()
            
            total_cells = 0
            all_areas = []
            all_circs = []
            
            tiles = []
            raw_tiles = []
            
            # Heatmap accumulator
            heatmap_data = np.zeros(padded_img.shape[:2], dtype=np.float32)
            
            base_name = os.path.splitext(uploaded_file.name)[0] if uploaded_file.name else "specimen"

            for i, (y, x) in enumerate(coords):
                patch = padded_img[y:y+IMG_SIZE, x:x+IMG_SIZE]
                preprocessed_patch = preprocess_v9(patch)
                
                batch_arr = np.expand_dims(preprocessed_patch, axis=0).astype(np.float32)
                preds = predict_batch(session, batch_arr)
                
                prob_map = preds[0] if preds.ndim == 3 else preds
                mask, count, centroids, areas, circs, solids, eccs, *rest = extract_biology(prob_map)
                
                total_cells += count
                all_areas.extend(areas)
                all_circs.extend(circs)
                
                heatmap_data[y:y+IMG_SIZE, x:x+IMG_SIZE] = count
                
                patch_rgb = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
                overlay = np.zeros_like(patch_rgb)
                if count > 0:
                    overlay[mask > 0] = [255, 0, 255]
                blended = cv2.addWeighted(patch_rgb, 0.7, overlay, 0.5, 0)
                
                tiles.append(blended)
                raw_tiles.append(patch_rgb)
            
            st.success("Inference Complete!")
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Osteoclasts", total_cells)
            col2.metric("Average Size (px²)", f"{np.mean(all_areas):.1f}" if all_areas else "0")
            col3.metric("Average Circularity", f"{np.mean(all_circs):.2f}" if all_circs else "0")
            
            # Heatmap Visualization
            st.subheader("Global Density Heatmap")
            max_count = np.max(heatmap_data)
            if max_count > 0:
                heatmap_norm_u8 = ((heatmap_data / max_count) * 255).astype(np.uint8)
                heatmap_colored = cv2.applyColorMap(heatmap_norm_u8, cv2.COLORMAP_MAGMA)
                alpha = np.expand_dims((heatmap_data / max_count).astype(np.float32), axis=-1)
                blended_heatmap = (padded_img.astype(np.float32) * (1.0 - alpha * 0.7) + heatmap_colored.astype(np.float32) * (alpha * 0.7)).astype(np.uint8)
                st.image(cv2.cvtColor(blended_heatmap, cv2.COLOR_BGR2RGB), caption="Cell Density Heatmap Overlay", use_container_width=True)
            
            # Interactive Tile Explorer
            st.subheader("Interactive Extraction Library")
            selected_tile_idx = st.selectbox(
                "Select Tile to Inspect",
                range(len(tiles)),
                format_func=lambda idx: f"{base_name}_tile_{idx+1} (Pos: {coords[idx]})"
            )
            
            t_col1, t_col2 = st.columns(2)
            with t_col1:
                st.image(raw_tiles[selected_tile_idx], caption="Raw Patch", use_container_width=True)
            with t_col2:
                st.image(tiles[selected_tile_idx], caption="Predicted Biology Overlay", use_container_width=True)
            
            # Export CSV
            if total_cells > 0:
                csv_data = pd.DataFrame({
                    "Area_px2": all_areas,
                    "Circularity": all_circs
                }).to_csv(index=False).encode('utf-8')
                
                st.download_button(
                    "Download Clinical Morphometric Metrics (CSV)",
                    data=csv_data,
                    file_name="chana_morphometrics.csv",
                    mime="text/csv",
                )
