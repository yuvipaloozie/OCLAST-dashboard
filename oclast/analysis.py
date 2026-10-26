"""Image-coordinate inference and connected-component bounded object analysis."""
import hashlib
import math
from pathlib import Path
from functools import lru_cache

import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage.feature import peak_local_max
from skimage.measure import regionprops
from skimage.segmentation import watershed

from .preprocessor import preprocess_v9
from .runtime import InferenceEngine

MODEL_PATH = Path(__file__).resolve().parent.parent / 'Model Weights' / 'unetplusplus.onnx'


@lru_cache(maxsize=1)
def model():
    return InferenceEngine(MODEL_PATH)


def compute_status():
    if not model.cache_info().currsize:
        return dict(status='not_loaded',device=None)
    return model().info()


@lru_cache(maxsize=1)
def model_hash():
    h = hashlib.sha256()
    with MODEL_PATH.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def tile_positions(height, width, size=512):
    return [(y, x) for y in range(0, height, size) for x in range(0, width, size)]


def infer_image(image, progress=lambda *args: None, predictor=None):
    """Keep V9 preprocessing and final U-Net++ head; crop all padding away.

    This pass deliberately retains non-overlapping inference tiles. Objects are
    separated once after stitching, rather than counted once per inference tile.
    """
    height, width = image.shape[:2]
    probability = np.empty((height, width), dtype=np.float32)
    positions = tile_positions(height, width)
    session = None if predictor else model()
    for index, (y, x) in enumerate(positions):
        patch = image[y:y+512, x:x+512]
        h, w = patch.shape[:2]
        patch = cv2.copyMakeBorder(patch, 0, 512-h, 0, 512-w,
                                   cv2.BORDER_CONSTANT, value=(255,255,255))
        batch = preprocess_v9(patch)[None].astype(np.float32)
        if predictor:
            output = predictor(batch)
        else:
            output = session.run([session.get_outputs()[-1].name],
                                 {session.get_inputs()[0].name: batch})[0]
        output = np.asarray(output)
        if output.shape != (1,512,512,1) or not np.isfinite(output).all():
            raise ValueError(f'Unexpected model probability output: {output.shape}')
        probability[y:y+h,x:x+w] = output[0,:h,:w,0]
        progress(index+1, len(positions))
    return probability


def separate_whole_image(probability, min_area=50, min_distance=20):
    """Watershed globally connected regions using bounded temporary arrays.

    Component bounds reduce distance-transform memory for large sparse fields.
    Peak spacing, threshold and minimum area retain the existing app defaults.
    Border peaks are allowed so cells on the original image edge aren't lost.
    """
    foreground = ndi.binary_fill_holes(probability > .5)
    components, _ = ndi.label(foreground)
    sizes = np.bincount(components.ravel())
    labels = np.zeros(probability.shape, dtype=np.uint32)
    next_id = 1
    for component_id, box in enumerate(ndi.find_objects(components), start=1):
        if box is None or sizes[component_id] <= min_area:
            continue
        region = components[box] == component_id
        padded = np.pad(region, 1)
        distance = ndi.distance_transform_edt(padded)
        peaks = peak_local_max(distance, min_distance=min_distance,
                               labels=padded.astype(np.uint8), exclude_border=False)
        markers = np.zeros(padded.shape, np.int32)
        if len(peaks):
            markers[tuple(peaks.T)] = np.arange(1,len(peaks)+1)
        else:
            markers, _ = ndi.label(padded)
        local = watershed(-distance, markers, mask=padded)[1:-1,1:-1]
        target = labels[box]
        for obj in regionprops(local):
            if obj.area <= min_area:
                continue
            target[obj.slice][obj.image] = next_id
            next_id += 1
    return labels


def measurements(labels, manual_ids=()):
    manual_ids = set(manual_ids)
    rows = []
    for obj in regionprops(labels):
        perimeter = float(obj.perimeter)
        rows.append(dict(id=int(obj.label), area=float(obj.area),
                         circularity=min(1.,4*math.pi*obj.area/perimeter**2) if perimeter else 1.,
                         solidity=float(obj.solidity), eccentricity=float(obj.eccentricity),
                         x=float(obj.centroid[1]), y=float(obj.centroid[0]),
                         bbox=[int(v) for v in obj.bbox], manual=obj.label in manual_ids))
    return rows


def summary(rows):
    return dict(count=len(rows), mean_area=float(np.mean([r['area'] for r in rows])) if rows else 0.,
                mean_circularity=float(np.mean([r['circularity'] for r in rows])) if rows else 0.)
