import os
import numpy as np

IMG_SIZE = 512
NUM_CLASSES = 1

MIN_AREA = 50
MIN_DIST = 20

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)

WEIGHTS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Model Weights', 'Unetplusplus_no_Domain.weights.h5'))
BATCH_SIZE = 8  # Adjust based on GPU VRAM
