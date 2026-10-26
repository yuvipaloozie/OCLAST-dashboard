"""Regression tests for whole-image identity, persistence, and exported geometry."""
import io
import os
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from oclast.analysis import infer_image, separate_whole_image
from oclast.projects import Projects


class AnalysisTests(unittest.TestCase):
    def test_one_object_across_inference_seam_has_one_identity(self):
        probability=np.zeros((512,1024),np.float32)
        cv2.circle(probability,(512,256),30,1.,-1)
        pieces=iter([probability[:,:512],probability[:,512:]])
        result=infer_image(np.full((512,1024,3),255,np.uint8),predictor=lambda batch:next(pieces)[None,...,None])
        labels=separate_whole_image(result)
        self.assertEqual(int(labels.max()),1)
        self.assertEqual(labels[256,500],labels[256,520])

    def test_partial_tiles_crop_to_original_dimensions(self):
        result=infer_image(np.zeros((533,777,3),np.uint8),predictor=lambda batch:np.full((1,512,512,1),.8,np.float32))
        self.assertEqual(result.shape,(533,777))
        np.testing.assert_allclose(result,.8)

    def test_rejected_small_foreground_is_not_in_counted_overlay(self):
        probability=np.zeros((100,100),np.float32)
        probability[20:24,20:24]=1
        self.assertFalse(separate_whole_image(probability).any())

    def test_original_image_edge_object_is_retained(self):
        probability=np.zeros((100,100),np.float32)
        cv2.circle(probability,(0,50),15,1.,-1)
        self.assertEqual(int(separate_whole_image(probability).max()),1)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Projects(self.temp.name)
        self.image=np.full((100,120,3),210,np.uint8)
        self.meta=self.store.create(self.image,'field.tif','original-hash')
        self.id=self.meta['id']
        p=np.zeros((100,120),np.float32);p[20:35,20:35]=1
        self.store.save_analysis(self.id,p,separate_whole_image(p),'checkpoint-hash',1.)

    def tearDown(self):
        self.store.source.cache_clear();self.store.labels.cache_clear();self.store.probability.cache_clear()
        self.temp.cleanup()

    def test_reopen_preserves_source_predictions_identity_and_measurements(self):
        reopened=Projects(self.temp.name)
        meta=reopened.get(self.id)
        self.assertEqual(meta['status'],'complete')
        self.assertEqual(meta['model']['sha256'],'checkpoint-hash')
        self.assertEqual(meta['count'],1)
        np.testing.assert_array_equal(reopened.source(self.id),self.image)
        self.assertEqual(reopened.cells(self.id)[0]['area'],225)
        self.assertEqual(reopened.probability(self.id).shape,(100,120))
        self.assertEqual(len(list(Path(self.temp.name).rglob('source*'))),1)

    def test_edit_reopen_and_undo_use_same_saved_label_map(self):
        self.store.edit(self.id,points=[[70,60],[85,60],[85,75],[70,75]])
        reopened=Projects(self.temp.name)
        self.assertEqual(reopened.get(self.id)['count'],2)
        self.assertEqual(sum(c['manual'] for c in reopened.cells(self.id)),1)
        meta=reopened.undo(self.id)
        self.assertEqual(meta['count'],1)
        reopened.edit(self.id,delete_id=1)
        self.assertEqual(reopened.get(self.id)['count'],0)
        self.assertFalse(reopened.labels(self.id,reopened.get(self.id)['revision']).any())

    def test_overlapping_addition_is_rejected_without_incrementing_count(self):
        with self.assertRaisesRegex(ValueError,'overlaps'):
            self.store.edit(self.id,points=[[20,20],[40,20],[40,40],[20,40]])
        self.assertEqual(self.store.get(self.id)['count'],1)

    def test_reopen_uses_atomic_label_state_if_summary_index_is_stale(self):
        import json
        index=self.store.folder(self.id)/'project.json'
        previous=json.loads(index.read_text(encoding='utf-8'))
        self.store.edit(self.id,points=[[70,60],[85,60],[85,75],[70,75]])
        index.write_text(json.dumps(previous),encoding='utf-8')
        reopened=Projects(self.temp.name)
        self.assertEqual(reopened.get(self.id)['count'],2)
        self.assertEqual(len(reopened.cells(self.id)),2)

    def test_interrupted_job_is_recoverable_after_restart(self):
        self.store.update(self.id,status='running')
        reopened=Projects(self.temp.name)
        self.assertEqual(reopened.get(self.id)['status'],'interrupted')

    def test_paths_cannot_escape_the_project_directory(self):
        with self.assertRaises(KeyError):self.store.folder('../../outside')


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        os.environ['OCLAST_DATA_DIR']=cls.temp.name
        import api
        cls.previous_store=api.store
        api.store=Projects(cls.temp.name)
        cls.api=api
        from fastapi.testclient import TestClient
        cls.client=TestClient(api.app)

    @classmethod
    def tearDownClass(cls):
        cls.api.store.source.cache_clear();cls.api.store.labels.cache_clear();cls.api.store.probability.cache_clear()
        cls.api.store=cls.previous_store
        cls.temp.cleanup()

    def test_bad_input_returns_actionable_error(self):
        response=self.client.post('/api/projects',files={'file':('broken.tif',b'not a TIFF','image/tiff')})
        self.assertEqual(response.status_code,400)
        self.assertIn('decoded',response.json()['detail'])

    def test_saved_api_tiles_exports_and_revision_conflicts(self):
        image=np.full((100,120,3),220,np.uint8)
        encoded=cv2.imencode('.png',image)[1].tobytes()
        response=self.client.post('/api/projects',files={'file':('sample.png',encoded,'image/png')})
        self.assertEqual(response.status_code,201)
        meta=response.json();identifier=meta['id']
        probability=np.zeros((100,120),np.float32);probability[10:30,10:30]=1
        self.api.store.save_analysis(identifier,probability,separate_whole_image(probability),'hash',1)
        base=f'/api/projects/{identifier}'
        image_response=self.client.get(base+'/tiles/raw/0/0/0')
        self.assertEqual(cv2.imdecode(np.frombuffer(image_response.content,np.uint8),1).shape,(100,120,3))
        overlay=self.client.get(base+'/tiles/labels/0/0/0')
        self.assertEqual(cv2.imdecode(np.frombuffer(overlay.content,np.uint8),-1).shape,(100,120,4))
        meta=self.client.get(base).json()
        self.assertEqual(meta['count'],1)
        csv=self.client.get(base+'/export/measurements.csv')
        self.assertIn('CentroidX_px',csv.text)
        import zipfile
        bundle=self.client.get(base+'/export/analysis.zip')
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as z:
            with np.load(io.BytesIO(z.read('labels.npz'))) as d:self.assertEqual(int(d['labels'].max()),1)
        response=self.client.post(base+'/edits',json={'delete_id':1,'revision':meta['revision']-1})
        self.assertEqual(response.status_code,409)
        response=self.client.post(base+'/edits',json={'delete_id':1,'revision':meta['revision']})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['count'],0)


if __name__=='__main__':unittest.main()
