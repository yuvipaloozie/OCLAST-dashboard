# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_dynamic_libs
from pathlib import Path
import sys

# Fail at build time instead of shipping an EXE containing a Git LFS pointer
# or an absent production UI. Run git lfs pull and npm run build first.
model = Path(SPECPATH) / 'Model Weights' / 'unetplusplus.onnx'
with model.open('rb') as checkpoint:
    if checkpoint.read(128).startswith(b'version https://git-lfs.github.com/spec/'):
        raise ValueError('Model weights are a Git LFS pointer. Run git lfs pull before packaging.')
if not (Path(SPECPATH) / 'frontend' / 'dist' / 'index.html').is_file():
    raise ValueError('Production UI is missing. Run npm run build in frontend before packaging.')

runtime_binaries = collect_dynamic_libs('onnxruntime')
# Conda-based Python builds keep libffi outside the normal DLL directory.
ffi = Path(sys.base_prefix) / 'Library' / 'bin' / 'ffi.dll'
if ffi.is_file():
    runtime_binaries.append((str(ffi), '.'))


a = Analysis(
    ['packaging/desktop.py'],
    pathex=[str(Path(SPECPATH))],
    binaries=runtime_binaries,
    datas=[('frontend/dist', 'frontend/dist'), ('Model Weights/unetplusplus.onnx', 'Model Weights'), ('packaging/licenses', 'licenses')],
    hiddenimports=['api'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='OCLAST',
    version='packaging/windows-version.txt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
