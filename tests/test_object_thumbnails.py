import unittest
import cv2
import numpy as np
from oclast.analysis import measurements
from oclast.thumbnails import object_thumbnail


class ObjectThumbnailTests(unittest.TestCase):
    def test_only_target_mask_is_highlighted_and_source_is_unchanged(self):
        image=np.full((40,40,3),100,np.uint8)
        labels=np.zeros((40,40),np.uint32)
        labels[6:15,6:15]=1
        labels[6:15,16:25]=2
        cell=measurements(labels)[0]
        raw=cv2.imdecode(np.frombuffer(object_thumbnail(image,labels,cell,False),np.uint8),1)
        masked=cv2.imdecode(np.frombuffer(object_thumbnail(image,labels,cell,True),np.uint8),1)
        self.assertEqual(masked.shape,(160,160,3))
        self.assertGreater(int(masked[80,80,2])-int(masked[80,80,1]),20)
        np.testing.assert_allclose(masked[80,146],raw[80,146],atol=3)
        self.assertTrue(np.all(image==100))
        self.assertEqual(np.count_nonzero(labels==1),81)

    def test_image_edge_and_tiny_objects_render_without_wrapping(self):
        image=np.full((10,12,3),200,np.uint8)
        labels=np.zeros((10,12),np.uint32);labels[:4,:4]=1
        result=object_thumbnail(image,labels,measurements(labels)[0])
        decoded=cv2.imdecode(np.frombuffer(result,np.uint8),1)
        self.assertEqual(decoded.shape,(160,160,3))
        self.assertLess(float(decoded[0,0].mean()),70)
        self.assertGreater(float(decoded[90,90].mean()),90)

    def test_elongated_mask_fits_square_thumbnail(self):
        image=np.full((50,200,3),150,np.uint8)
        labels=np.zeros((50,200),np.uint32);labels[20:25,5:195]=1
        decoded=cv2.imdecode(np.frombuffer(object_thumbnail(image,labels,measurements(labels)[0]),np.uint8),1)
        self.assertEqual(decoded.shape,(160,160,3))
        self.assertGreater(float(decoded[80,80].mean()),90)


if __name__=='__main__':unittest.main()
