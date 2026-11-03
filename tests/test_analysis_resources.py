"""Regression coverage for bounded separation and recoverable memory pressure."""
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage.feature import peak_local_max
from skimage.measure import regionprops
from skimage.segmentation import watershed

from oclast.analysis import infer_image, separate_whole_image


def prior_separation(probability, min_area=50, min_distance=20):
    # Frozen pre-hardening algorithm: exact IDs and geometry must remain equal.
    foreground = ndi.binary_fill_holes(probability > .5)
    components, _ = ndi.label(foreground)
    sizes = np.bincount(components.ravel())
    labels = np.zeros(probability.shape, dtype=np.uint32)
    next_id = 1
    for component_id, box in enumerate(ndi.find_objects(components), start=1):
        if box is None or sizes[component_id] <= min_area:
            continue
        padded = np.pad(components[box] == component_id, 1)
        distance = ndi.distance_transform_edt(padded)
        peaks = peak_local_max(distance, min_distance=min_distance,
                               labels=padded.astype(np.uint8), exclude_border=False)
        markers = np.zeros(padded.shape, np.int32)
        if len(peaks):
            markers[tuple(peaks.T)] = np.arange(1, len(peaks)+1)
        else:
            markers, _ = ndi.label(padded)
        local = watershed(-distance, markers, mask=padded)[1:-1,1:-1]
        target = labels[box]
        for obj in regionprops(local):
            if obj.area > min_area:
                target[obj.slice][obj.image] = next_id
                next_id += 1
    return labels


class AnalysisResourceTests(unittest.TestCase):
    def test_geometry_and_ids_equal_prior_algorithm(self):
        probability = np.zeros((1024, 1400), np.float32)
        rng = np.random.default_rng(47)
        for x, y, radius in rng.integers([0,0,2], [1400,1024,35], (150,3)):
            cv2.circle(probability, (int(x),int(y)), int(radius), 1., -1)
        probability[10:20,10:15] = 1  # exactly the rejection threshold
        probability[500:550,500:600] = 1
        probability[510:540,510:590] = 0  # holes are still filled
        np.testing.assert_array_equal(separate_whole_image(probability),
                                      prior_separation(probability))

    def test_many_rejected_components_do_not_build_full_image_bincount(self):
        probability = np.zeros((1024,1024), np.float32)
        probability[::3,::3] = 1
        with patch('oclast.analysis.np.bincount', side_effect=AssertionError('full image copy')):
            self.assertFalse(separate_whole_image(probability).any())

    def test_dense_component_rejected_before_distance_transform(self):
        probability = np.ones((1024,1024), np.float32)
        with patch('oclast.analysis.require_memory', side_effect=MemoryError('Close other apps')) as guard:
            with patch('oclast.analysis.ndi.distance_transform_edt') as edt:
                with self.assertRaisesRegex(MemoryError, 'Close other apps'):
                    separate_whole_image(probability)
                edt.assert_not_called()
                guard.assert_called_once_with(1026*1026*48, 'separate this connected region')

    def test_empty_wrong_depth_and_wrong_channel_inputs_are_recoverable(self):
        for image in (np.zeros((0,512,3),np.uint8), np.zeros((512,512),np.uint8),
                      np.zeros((512,512,4),np.uint8), np.zeros((512,512,3),np.uint16)):
            with self.subTest(shape=image.shape, dtype=image.dtype):
                with self.assertRaisesRegex(ValueError, '8-bit RGB'):
                    infer_image(image, predictor=lambda batch: self.fail('must not infer'))
