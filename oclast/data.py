import cv2
import numpy as np

def pad_image(img_bgr, img_size):
    h, w, _ = img_bgr.shape
    pad_h = (img_size - h % img_size) % img_size
    pad_w = (img_size - w % img_size) % img_size
    padded = cv2.copyMakeBorder(img_bgr, 0, pad_h, 0, pad_w, cv2.BORDER_CONSTANT, value=[255, 255, 255])
    return padded, h, w

def get_tile_coordinates(padded_shape, img_size):
    y_steps = range(0, padded_shape[0], img_size)
    x_steps = range(0, padded_shape[1], img_size)
    coords = [(y, x) for y in y_steps for x in x_steps]
    return coords
