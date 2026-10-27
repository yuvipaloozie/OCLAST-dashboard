# Developing OCLAST Dashboard

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
npm test
npm run build
cd ..
.venv\Scripts\python.exe -m pip install PyInstaller==6.21.0
.venv\Scripts\python.exe -m PyInstaller OCLAST.spec --noconfirm
```

The build produces **`dist/OCLAST.exe`**, with the frontend, the required U-Net++ checkpoint, and the GPU/CPU runtime inside one executable. User projects are stored outside the bundle. Executables are distributed through [GitHub Releases](https://github.com/yuvipaloozie/OCLAST-dashboard/releases), rather than committed to Git.

The regression suite covers full-image object identity, partial tiles, filtered overlays, edge objects, save/reopen, editing/undo, exports, revision conflicts, and GPU fallback. Passing these software checks does not establish biological detection accuracy.

Interface typography uses bundled [Outfit](../frontend/public/fonts/OFL-Outfit.txt) under the SIL Open Font License. See [interface conventions](../frontend/DESIGN.md) for the visual design and component references.

## Runtime overrides

Advanced overrides can be set before launching the executable or Python service:

```powershell
$env:OCLAST_DEVICE = "cpu"       # auto, cpu, cuda, or directml
$env:OCLAST_GPU_DEVICE_ID = "0"   # GPU adapter index
$env:OCLAST_PORT = "8001"        # optional if port 8000 is already occupied
```

The source implementation can also use CUDA when its ONNX provider and required libraries are installed. Install only one ONNX Runtime distribution in an environment. The default Windows requirements use DirectML, which also includes CPU execution; `requirements-cpu.txt` is available for a separate CPU-only environment.
