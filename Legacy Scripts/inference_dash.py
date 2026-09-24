# from scipy import ndimage
# from skimage import measure
# from skimage.feature import peak_local_max
# from skimage.segmentation import watershed
# 
# # --- CONFIGURATION ---
# st.set_page_config(page_title="OCLAST v0.5", layout="wide")
# IMG_SIZE = 512
# NUM_CLASSES = 1
# MIN_AREA = 50 # Discard cellular debris
# MIN_DIST = 20 # Watershed peak distance
# IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
# IMAGENET_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)
# 
# # Point this to your actual Drive path when running in Colab
# WEIGHTS_PATH = '/content/UNetPlusPlus_local.weights.h5'
# 
# # --- 1. MODEL INITIALIZATION (Cached for UI Speed) ---
# @st.cache_resource
# def load_oclast_model():
#     """Builds the U-Net++ ResNet50 Architecture and loads Phase 3 weights."""
#     model = unet_models.unet_plus_2d(
#         input_size=(IMG_SIZE, IMG_SIZE, 3),
#         filter_num=[64, 128, 256, 512],
#         n_labels=NUM_CLASSES,
#         stack_num_down=4,
#         stack_num_up=4,
#         activation='ReLU',           # CRITICAL: Must be capitalized
#         output_activation='Sigmoid', # CRITICAL: Must be capitalized
#         batch_norm=True,
#         pool=False, unpool=False,
#         backbone='ResNet50',
#         weights=None,
#         deep_supervision=True
#     )
#     if os.path.exists(WEIGHTS_PATH):
#         model.load_weights(WEIGHTS_PATH)
#         return model
#     else:
#         st.error(f"Weights not found at {WEIGHTS_PATH}. Please check your Google Drive mount.")
#         return None
# 
# model = load_oclast_model()
# 
# # --- 2. PIPELINE FUNCTIONS ---
# def preprocess_v9(img_bgr):
#     """
#     Combines the offline V9 'Nuclear Pop' (CLAHE + Tophat)
#     with the online ImageNet normalization.
#     """
#     # 1. Base formatting
#     img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
#     img_rgb = cv2.resize(img_rgb, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
# 
#     # 2. V9 CLAHE + Top-Hat Logic
#     lab = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2LAB)
#     l, a, b = cv2.split(lab)
#     clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
#     l_clahe = clahe.apply(l)
#     kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
#     nuclei_map = cv2.morphologyEx(l_clahe, cv2.MORPH_TOPHAT, kernel)
#     l_final = cv2.addWeighted(l_clahe, 1.0, nuclei_map, 0.8, 0)
#     img_enhanced = cv2.cvtColor(cv2.merge((l_final, a, b)), cv2.COLOR_LAB2RGB)
# 
#     # 3. Online Normalization
#     img_norm = img_enhanced.astype(np.float32) / 255.0
#     return (img_norm - IMAGENET_MEAN) / IMAGENET_STD
# 
# def run_tiled_inference(image_path, progress_bar, status_text):
#     """Runs inference in 512x512 patches across full microscopy slide."""
#     raw_bgr = cv2.imread(image_path)
#     h, w, _ = raw_bgr.shape
# 
#     # Dynamic Padding
#     pad_h = (IMG_SIZE - h % IMG_SIZE) % IMG_SIZE
#     pad_w = (IMG_SIZE - w % IMG_SIZE) % IMG_SIZE
#     padded = cv2.copyMakeBorder(raw_bgr, 0, pad_h, 0, pad_w, cv2.BORDER_CONSTANT, value=[255,255,255])
# 
#     stitched_prob = np.zeros((padded.shape[0], padded.shape[1]), dtype=np.float32)
#     y_steps = list(range(0, padded.shape[0], IMG_SIZE))
#     x_steps = list(range(0, padded.shape[1], IMG_SIZE))
#     total_tiles = len(y_steps) * len(x_steps)
# 
#     current_tile = 0
#     for y in y_steps:
#         for x in x_steps:
#             patch = padded[y:y+IMG_SIZE, x:x+IMG_SIZE]
#             patch_norm = preprocess_v9(patch)
# 
#             # Run Model
#             preds = model.predict(np.expand_dims(patch_norm, 0), verbose=0)
#             stitched_prob[y:y+IMG_SIZE, x:x+IMG_SIZE] = preds[-1][0, :, :, 0]
# 
#             current_tile += 1
#             progress_bar.progress(current_tile / total_tiles)
# 
#     return raw_bgr, stitched_prob[:h, :w]
# 
# def extract_biology(prob_map):
#     """Morphological extraction, watershed separation, and object counts."""
#     mask = (prob_map > 0.5).astype(np.uint8)
#     mask = ndimage.binary_fill_holes(mask).astype(np.uint8)
# 
#     distance = ndimage.distance_transform_edt(mask)
#     local_maxi = peak_local_max(distance, min_distance=MIN_DIST, labels=mask)
# 
#     if len(local_maxi) > 0:
#         markers_mask = np.zeros(distance.shape, dtype=bool)
#         markers_mask[tuple(local_maxi.T)] = True
#         markers, _ = ndimage.label(markers_mask)
#         labels = watershed(-distance, markers, mask=mask)
#     else:
#         labels = measure.label(mask)
# 
#     props = [r for r in measure.regionprops(labels) if r.area > MIN_AREA]
#     centroids = [r.centroid for r in props]
#     areas = [r.area for r in props]
# 
#     return mask, len(props), centroids, areas
# 
# # --- 3. UI LAYOUT & LOGIC ---
# st.title("🔬 Project OCLAST: Osteoclast Inference Engine v0.5")
# st.markdown("Automated segmentation and counting of in vitro osteoclasts using U-Net++ (ResNet50).")
# 
# uploaded_file = st.file_uploader("Upload High-Resolution Scan (.tif, .png, .jpg)", type=["tif", "png", "jpg"])
# 
# if uploaded_file and model is not None:
#     st.markdown("---")
# 
#     # Save uploaded file to temp directory (safe for massive TIFFs)
#     with tempfile.NamedTemporaryFile(delete=False, suffix='.tif') as tmp_file:
#         tmp_file.write(uploaded_file.getbuffer())
#         tmp_path = tmp_file.name
# 
#     # UI Elements
#     col1, col2 = st.columns([1, 1])
#     progress_bar = st.progress(0)
#     status_text = st.empty()
# 
#     # Execute Inference
#     status_text.text("Initializing Tiled Inference Pipeline (Applying V9 Processing)...")
#     raw_img, prob_map = run_tiled_inference(tmp_path, progress_bar, status_text)
# 
#     status_text.text("Extracting Biological Instances (Watershed)...")
#     final_mask, cell_count, centroids, areas = extract_biology(prob_map)
# 
#     status_text.text("✅ Processing Complete!")
#     progress_bar.empty()
#     os.remove(tmp_path) # Cleanup
# 
#     # Visualization Processing
#     img_rgb = cv2.cvtColor(raw_img, cv2.COLOR_BGR2RGB)
# 
#     # Generate Overlay
#     overlay = img_rgb.copy()
#     mask_bool = final_mask > 0
#     overlay[mask_bool] = overlay[mask_bool] * 0.5 + np.array([0, 255, 0]) * 0.5 # Green overlay
# 
#     # Plotting
#     with col1:
#         st.subheader("Raw Input Image")
#         st.image(img_rgb, use_container_width=True)
#         st.subheader("AI Probability Map")
#         st.image(prob_map, cmap="magma", use_container_width=True)
# 
#     with col2:
#         st.subheader(f"Detections: {cell_count} Osteoclasts")
#         st.image(overlay, use_container_width=True)
# 
#         # Export logic
#         if areas:
#             df_export = pd.DataFrame({
#                 'Cell_ID': range(1, cell_count + 1),
#                 'Centroid_Y': [int(c[0]) for c in centroids],
#                 'Centroid_X': [int(c[1]) for c in centroids],
#                 'Area_Pixels': areas
#             })
# 
#             st.subheader("Data Export")
#             st.dataframe(df_export.head(), use_container_width=True)
# 
#             csv = df_export.to_csv(index=False).encode('utf-8')
#             st.download_button(
#                 label="📥 Download Biological Data (CSV)",
#                 data=csv,
#                 file_name=f"OCLAST_results_{uploaded_file.name}.csv",
#                 mime="text/csv",
#             )

# CELL 3: THE WEBSOCKET & HEADLESS FIX
!pip install pyngrok
import time
from pyngrok import ngrok

# 1. Nuke the port completely
!fuser -k 8501/tcp
!pkill -f streamlit
ngrok.kill()
time.sleep(2)

# 2. Ngrok Setup
NGROK_TOKEN = "30lB1JFSk51znFyUHmVJ1hnHyPv_3qr359GW7pmFAyLxggLfU"
ngrok.set_auth_token(NGROK_TOKEN)

# 3. Boot Streamlit with HEADLESS and WSS fixes
print("🚀 Booting Streamlit Server (Headless Mode)...")
run_cmd = "streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true --server.enableCORS false --server.enableXsrfProtection false &> /content/logs.txt &"
get_ipython().system_raw(run_cmd)

# Give it 5 seconds to build the network graph
time.sleep(5)

# 4. Open Tunnel
public_url = ngrok.connect(addr="8501", bind_tls=True).public_url
print("="*60)
print(f"🌟 OCLAST v0.5 IS LIVE AT: {public_url}")
print("="*60)

!cat /content/logs.txt
