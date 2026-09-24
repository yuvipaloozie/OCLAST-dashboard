import cv2
import numpy as np

def pad_image(img, tile_size):
    h, w, c = img.shape
    pad_h = (tile_size - (h % tile_size)) % tile_size
    pad_w = (tile_size - (w % tile_size)) % tile_size
    padded_img = cv2.copyMakeBorder(img, 0, pad_h, 0, pad_w, cv2.BORDER_REFLECT)
    return padded_img, h, w

def get_tile_coordinates(padded_shape, tile_size):
    h, w = padded_shape[:2]
    coords = []
    for y in range(0, h, tile_size):
        for x in range(0, w, tile_size):
            coords.append((y, x))
    return coords
