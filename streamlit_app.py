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
    
    if st.button("Run Advanced Inference"):
        session = get_model()
        
        padded_img, h, w = pad_image(img_bgr, IMG_SIZE)
        coords = get_tile_coordinates(padded_img.shape, IMG_SIZE)
        
        # Heatmap tracking array
        heatmap_data = np.zeros(padded_img.shape[:2], dtype=np.float32)
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_cells = 0
        all_areas = []
        all_circs = []
        all_solids = []
        all_eccs = []
        
        tile_csv_data = []
        
        st.subheader("Tile Processing")
        cols = st.columns(4)
        col_idx = 0
        
        for i, (y, x) in enumerate(coords):
            patch = padded_img[y:y+IMG_SIZE, x:x+IMG_SIZE]
            preprocessed_patch = preprocess_v9(patch)
            
            batch_arr = np.expand_dims(preprocessed_patch, axis=0).astype(np.float32)
            preds = predict_batch(session, batch_arr)
            prob_map = preds[0]
            
            mask, count, centroids, areas, circs, solids, eccs = extract_biology(prob_map)
            
            total_cells += count
            all_areas.extend(areas)
            all_circs.extend(circs)
            all_solids.extend(solids)
            all_eccs.extend(eccs)
            
            tile_name = f"tile_y{y}_x{x}"
            tile_csv_data.append({"Tile_Name": tile_name, "Y": y, "X": x, "Cell_Count": count})
            
            # Fill heatmap data with count (spread across the tile region)
            heatmap_data[y:y+IMG_SIZE, x:x+IMG_SIZE] = count
            
            if count > 0:
                with cols[col_idx % 4]:
                    patch_rgb = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
                    overlay = np.zeros_like(patch_rgb)
                    overlay[mask > 0] = [255, 0, 255]
                    blended = cv2.addWeighted(patch_rgb, 0.7, overlay, 0.5, 0)
                    st.image(blended, caption=f"Cells: {count}")
                col_idx += 1
            
            progress = (i + 1) / len(coords)
            progress_bar.progress(progress)
            status_text.text(f"Processed tile {i+1}/{len(coords)}...")
            
        progress_bar.empty()
        status_text.success("Inference Complete!")
        
        # Display Heatmap
        st.divider()
        st.subheader("Global Cell Density Heatmap")
        max_count = np.max(heatmap_data)
        if max_count > 0:
            heatmap_norm = np.uint8(255 * (heatmap_data / max_count))
            heatmap_color = cv2.applyColorMap(heatmap_norm, cv2.COLORMAP_JET)
            
            # Blend with original image
            blended_heatmap = cv2.addWeighted(padded_img, 0.4, heatmap_color, 0.6, 0)
            blended_rgb = cv2.cvtColor(blended_heatmap, cv2.COLOR_BGR2RGB)
            
            st.image(blended_rgb, caption="Thermal Density Map", use_container_width=True)
        else:
            st.info("No cells detected for heatmap.")
            
        # Display Metrics
        st.divider()
        st.subheader("Global Morphometrics")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Cells Detected", total_cells)
        
        avg_area = sum(all_areas) / len(all_areas) if all_areas else 0
        col2.metric("Avg Area", f"{avg_area:.1f} px²")
        
        avg_circ = sum(all_circs) / len(all_circs) if all_circs else 0
        col3.metric("Avg Circularity", f"{avg_circ:.3f}")
        
        avg_solid = sum(all_solids) / len(all_solids) if all_solids else 0
        col4.metric("Avg Solidity", f"{avg_solid:.3f}")
        
        # CSV Export
        df_tiles = pd.DataFrame(tile_csv_data)
        csv = df_tiles.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download Tile Counts CSV",
            data=csv,
            file_name='tile_cell_counts.csv',
            mime='text/csv',
            type="primary"
        )
        
        if all_areas:
            st.divider()
            st.subheader("Morphometric Distributions")
            c1, c2 = st.columns(2)
            
            with c1:
                counts, bins = np.histogram(all_areas, bins=20)
                df_area = pd.DataFrame({
                    "Area Range (px²)": [f"{bins[i]:.0f}-{bins[i+1]:.0f}" for i in range(len(counts))],
                    "Count": counts
                }).set_index("Area Range (px²)")
                st.write("**Area Distribution**")
                st.bar_chart(df_area)
                
            with c2:
                if all_circs:
                    counts_circ, bins_circ = np.histogram(all_circs, bins=20)
                    df_circ = pd.DataFrame({
                        "Circularity Range": [f"{bins_circ[i]:.2f}-{bins_circ[i+1]:.2f}" for i in range(len(counts_circ))],
                        "Count": counts_circ
                    }).set_index("Circularity Range")
                    st.write("**Circularity Distribution**")
                    st.bar_chart(df_circ)
