import numpy as np

IMG_SIZE = 512
NUM_CLASSES = 1
MIN_AREA = 50 
MIN_DIST = 20 

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)

CLAHE_CLIP = 2.0
CLAHE_GRID = (8, 8)
TOPHAT_KERNEL_SIZE = (15, 15)

# Tiling & Inference configuration
BATCH_SIZE = 4
OVERLAP = 0 # No overlap needed if fully tiled on a fixed grid
