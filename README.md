# OCLAST Dashboard

**From a whole microscopy image to reviewable osteoclast masks, counts, and measurements—on your own computer.**

OCLAST Dashboard is a local Windows workspace for TRAP-stained bright-field osteoclast images. Open a full-resolution image, run the bundled U-Net++ model, inspect its masks, and export the measurements. The Windows executable includes the interface, model, and inference runtime; Python, Node.js, and a cloud account are not needed to use it.

[**Download for Windows**](https://github.com/yuvipaloozie/OCLAST-dashboard/releases/latest) · [**Paper & research code**](https://github.com/yuvipaloozie/OCLAST) · [Report an issue](https://github.com/yuvipaloozie/OCLAST-dashboard/issues)

![OCLAST Dashboard showing a whole microscopy image, instance masks, morphology distributions, and saved projects](docs/images/interface.png)

## Start analyzing

1. Download **OCLAST.exe** from the [latest release](https://github.com/yuvipaloozie/OCLAST-dashboard/releases/latest). GitHub's **Source code** downloads do not contain the executable.
2. Double-click the executable. Allow a moment for its bundled files to unpack; the interface opens in your default browser at `http://127.0.0.1:8000`.
3. Choose **Open image**, then **Analyze image**. The image and results are saved as a local project.
4. Review the masks and measurements. Download a CSV or an analysis bundle when ready.

Keep the OCLAST console window open while using the app. Close that window to stop the local service; closing the browser tab alone does not stop it. The executable is unsigned, so Windows may show an unrecognized-publisher notice.

**Supported input:** single, 8-bit RGB TIFF, PNG, or JPEG images. Grayscale, 16-bit images, alpha channels, and multipage/stack workflows require conversion to a single supported image first. The packaged release targets 64-bit Windows. Large scans need available memory and disk space.

## A workspace for reviewing images

| Feature | What you can do |
| --- | --- |
| Whole-image viewer | Fit, pan, zoom, and inspect original pixels at 1:1. Switch between the original image, object masks, and foreground probability. |
| Tile library | Browse every image region in a continuous list, toggle its mask overlay, and jump to that region in the main viewer. Empty regions and partial edge tiles remain accessible. |
| Cell inspection | Select a detection to see its area and circularity in compact metric cards. Find a cell by its global object ID. |
| Morphology distributions | Explore area and circularity with smoothed KDE curves. Focused ranges reduce empty space; **Full range** reveals the tails. The panel states how many objects fall outside the focused view. |
| Manual review | Add an object with a polygon, remove a detection, and undo the last edit. Changes update the saved labels and measurements. |
| Saved projects | Reopen images and their results without repeating inference. Collapse either side panel for more viewing space. |
| Exports | Download measurements, an analysis bundle, or lossless image/mask training pairs. |

An object spanning multiple tiles keeps one identity and is counted once. Tile counts use the object's center; neighboring thumbnails can show different parts of the same mask. Adding a polygon that overlaps an existing object is rejected to avoid duplicate counts.

The current app focuses on **image-level analysis**. It does not require experiment, drug, dose, well-size, or biological-replicate metadata. Areas are reported in pixels²; physical calibration, well-region analysis, split/merge editing, and treatment comparisons are not part of this release.

## GPU acceleration with CPU fallback

The Windows release includes **ONNX Runtime DirectML** and automatically uses a compatible GPU when available. No separate CUDA toolkit is required. If GPU initialization or execution fails, inference retries on CPU. The analysis-time card identifies GPU, CPU, or mixed execution for that saved run.

Preprocessing, object separation, and saving still run on CPU. As one local example, an **8,057 × 7,479-pixel** image completed packaged-app analysis in approximately **35 seconds** (excluding image import) on an NVIDIA RTX 3060 Ti using DirectML. This is one observed run, not a guaranteed processing time on other hardware or images.

Advanced overrides can be set before launching the executable or Python service:

```powershell
$env:OCLAST_DEVICE = "cpu"       # auto, cpu, cuda, or directml
$env:OCLAST_GPU_DEVICE_ID = "0"   # GPU adapter index
$env:OCLAST_PORT = "8001"        # optional if port 8000 is already occupied
```

The source implementation can also use CUDA when its ONNX provider and required libraries are installed. Install only one ONNX Runtime distribution in an environment. The default Windows requirements use DirectML, which also includes CPU execution; `requirements-cpu.txt` is available for a separate CPU-only environment.

## Local storage and exports

Images are processed locally. The app serves its interface on the loopback address; analysis does not send microscopy images to a hosted service. Fonts and interface assets are bundled for offline use. The GitHub icon opens the separate research repository when clicked.

| Run mode | Project location |
| --- | --- |
| Windows executable | `%LOCALAPPDATA%\OCLAST\projects\` |
| Source checkout | `data/projects/` |
| Custom location | Set `OCLAST_DATA_DIR` before starting the app |

Each project stores one lossless source PNG, compressed probability and instance-label arrays, measurements, model identity, processing settings, and review state. The original uploaded TIFF is not also retained as a second source copy. One compressed undo snapshot is kept after an edit. Back up the **entire project folder** to preserve the source and editable analysis.

Reopening restores saved results. If the service stops during processing, the project is marked interrupted and can be run again; partially completed inference is not resumed.

**Measurement CSV:** source name, global object ID, centroid coordinates, area in pixels², circularity, solidity, eccentricity, and manual-review flag.

**Analysis bundle:** project metadata, measurements, instance labels, and a foreground mask. This is an export, not a replacement for the full editable project folder.

**Training pairs:** lossless image/mask PNG pairs for all tiles, including empty regions. Partial edge tiles keep their original dimensions.

## What the masks measure

The bundled model uses V9 preprocessing and 512 × 512 prediction tiles. Foreground probabilities are thresholded at `> 0.5`, stitched to the original image dimensions, and separated with watershed. Objects larger than 50 pixels are retained. Counts, overlays, edits, and exports use the same filtered instance-label map.

Area and shape measurements describe the predicted masks. They do not establish nuclei counts, multinuclearity, fusion, or resorptive activity. Image-edge truncation, tile seams, staining differences, and merged or missed detections can affect results; inspect the overlays before using the measurements. The probability layer shows model foreground scores, not calibrated certainty that a detection is biologically correct.

For the training curriculum, evaluation, and manuscript materials, see [OCLAST](https://github.com/yuvipaloozie/OCLAST). This repository contains the local application.

## Run from source

The current Windows build was tested with Python 3.12 and Node.js 24. Retrieve the model files through Git LFS when cloning:

```powershell
git clone https://github.com/yuvipaloozie/OCLAST-dashboard.git
cd OCLAST-dashboard
git lfs pull
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
.venv\Scripts\python.exe api.py
```

For frontend development, run the backend and Vite in separate terminals:

```powershell
# Terminal 1, from the repository root
.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000

# Terminal 2
cd frontend
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`. Vite forwards API requests to the local backend. Historical scripts remain in `Legacy Scripts/`; the supported application entry point is `api.py`.

## Verify and build a Windows release

Install the development tools once with `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`. Refresh bundled dependency notices with `.venv\Scripts\python.exe packaging/collect_licenses.py` when upgrading dependencies.

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
cd frontend
npm run lint
npm run build
cd ..
.venv\Scripts\python.exe -m pip install PyInstaller==6.21.0
.venv\Scripts\python.exe -m PyInstaller OCLAST.spec --noconfirm
```

The build produces **`dist/OCLAST.exe`**, with the frontend, the required U-Net++ checkpoint, and the GPU/CPU runtime inside one executable. User projects are stored outside the bundle. Executables are distributed through [GitHub Releases](https://github.com/yuvipaloozie/OCLAST-dashboard/releases), rather than committed to Git.

The regression suite covers full-image object identity, partial tiles, filtered overlays, edge objects, save/reopen, editing/undo, exports, revision conflicts, and GPU fallback. Passing these software checks does not establish biological detection accuracy.

Interface typography uses bundled [Outfit](frontend/public/fonts/OFL-Outfit.txt) under the SIL Open Font License. See [interface conventions](frontend/DESIGN.md) for the visual design and component references.
