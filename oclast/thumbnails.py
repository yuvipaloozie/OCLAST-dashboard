"""Small on-demand object crops; never persist another source-image copy."""
import math
import cv2
import numpy as np


def object_thumbnail(image, labels, cell, masks=True, size=160):
    y0, x0, y1, x1 = cell['bbox']
    side=max(24, math.ceil(max(x1-x0,y1-y0)*1.4))
    left=math.floor((x0+x1-side)/2)
    top=math.floor((y0+y1-side)/2)
    h,w=image.shape[:2]
    x0,y0=max(0,left),max(0,top)
    x1,y1=min(w,left+side),min(h,top+side)
    canvas=np.full((size,size,3),(56,47,48),np.uint8)
    scale=size/side
    dx0,dy0=round((x0-left)*scale),round((y0-top)*scale)
    dx1,dy1=round((x1-left)*scale),round((y1-top)*scale)
    width,height=max(1,dx1-dx0),max(1,dy1-dy0)
    patch=cv2.resize(image[y0:y1,x0:x1],(width,height),interpolation=cv2.INTER_AREA)
    if masks:
        target=np.uint8(labels[y0:y1,x0:x1]==cell['id'])
        target=cv2.resize(target,(width,height),interpolation=cv2.INTER_NEAREST)
        color=np.array((84,180,35) if cell['manual'] else (177,42,185),np.float32)
        selected=target>0
        patch[selected]=np.uint8(patch[selected]*.64+color*.36)
        boundary=target-cv2.erode(target,np.ones((3,3),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0)
        patch[boundary>0]=[245,240,250]
    canvas[dy0:dy0+height,dx0:dx0+width]=patch
    success,encoded=cv2.imencode('.jpg',canvas,[cv2.IMWRITE_JPEG_QUALITY,90])
    if not success:
        raise OSError('Could not render the object thumbnail')
    return encoded.tobytes()
