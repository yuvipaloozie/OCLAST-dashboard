import cv2
import numpy as np
from .config import CLAHE_CLIP, CLAHE_GRID, TOPHAT_KERNEL_SIZE, IMAGENET_MEAN, IMAGENET_STD

def preprocess_v9(img_bgr):
    """Offline Phase 1: Nuclear Pop (CLAHE + TopHat)"""
    # 1. BGR -> LAB for CLAHE on Lightness Channel
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    
    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP, tileGridSize=CLAHE_GRID)
    cl = clahe.apply(l)
    
    limg = cv2.merge((cl, a, b))
    img_clahe = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
    
    # 2. White Top-Hat Morphological Transform (highlights cellular nuclei/features)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, TOPHAT_KERNEL_SIZE)
    tophat = cv2.morphologyEx(img_clahe, cv2.MORPH_TOPHAT, kernel)
    
    # 3. Add tophat back to highlight
    img_v9 = cv2.add(img_clahe, tophat)
    
    """Online Phase 2: PyTorch/ImageNet Standardization"""
    # Convert to RGB, normalize [0, 1]
    img_rgb = cv2.cvtColor(img_v9, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    
    # Apply standard mean and standard deviation
    img_norm = (img_rgb - IMAGENET_MEAN) / IMAGENET_STD
    
    return img_norm.astype(np.float32)
