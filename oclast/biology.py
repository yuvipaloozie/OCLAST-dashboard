import numpy as np
from scipy import ndimage
from skimage import measure
from skimage.feature import peak_local_max
from skimage.segmentation import watershed
import math
from .config import MIN_AREA, MIN_DIST

def extract_biology(prob_map):
    """Watershed separation and morphometric extraction."""
    mask = (prob_map > 0.5).astype(np.uint8)
    mask = ndimage.binary_fill_holes(mask).astype(np.uint8)

    distance = ndimage.distance_transform_edt(mask)
    local_maxi = peak_local_max(distance, min_distance=MIN_DIST, labels=mask)

    if len(local_maxi) > 0:
        markers_mask = np.zeros(distance.shape, dtype=bool)
        markers_mask[tuple(local_maxi.T)] = True
        markers, _ = ndimage.label(markers_mask)
        labels = watershed(-distance, markers, mask=mask)
    else:
        labels = measure.label(mask)

    props = [r for r in measure.regionprops(labels) if r.area > MIN_AREA]
    centroids = [(int(r.centroid[0]), int(r.centroid[1])) for r in props]
    
    areas = []
    circularities = []
    solidities = []
    eccentricities = []
    
    for r in props:
        areas.append(int(r.area))
        perimeter = r.perimeter
        if perimeter > 0:
            circularity = (4 * math.pi * r.area) / (perimeter ** 2)
        else:
            circularity = 1.0 # single pixel case fallback
        circularities.append(min(circularity, 1.0)) # cap at 1.0 for biological logic
        solidities.append(r.solidity)
        eccentricities.append(r.eccentricity)

    return mask, len(props), centroids, areas, circularities, solidities, eccentricities
