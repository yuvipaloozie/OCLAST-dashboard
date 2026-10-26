import cv2
import numpy as np
from .config import IMG_SIZE, IMAGENET_MEAN, IMAGENET_STD

def preprocess_v9(img_bgr):
    """V9 'Nuclear Pop' + Model Normalization."""
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    img_rgb = cv2.resize(img_rgb, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
    
    lab = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_clahe = clahe.apply(l)
    
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    nuclei_map = cv2.morphologyEx(l_clahe, cv2.MORPH_TOPHAT, kernel)
    
    l_final = cv2.addWeighted(l_clahe, 1.0, nuclei_map, 0.8, 0)
    img_enhanced = cv2.cvtColor(cv2.merge((l_final, a, b)), cv2.COLOR_LAB2RGB)
    
    img_norm = img_enhanced.astype(np.float32) / 255.0
    return (img_norm - IMAGENET_MEAN) / IMAGENET_STD

def preprocess_standard(img_bgr):
    """Standard RGB normalization for legacy UNet/TransUNet models.
    Note: Legacy script did not convert .tif files from BGR to RGB! 
    So we leave it as BGR to match the training distribution."""
    img_disp = cv2.resize(img_bgr, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
    img_norm = img_disp.astype(np.float32) / 255.0
    return (img_norm - IMAGENET_MEAN) / IMAGENET_STD
