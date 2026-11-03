"""Failure admission must leave the service usable for the next request."""
import io
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient
from oclast.projects import Projects
from oclast.resources import require_memory


class ApiResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        with patch.dict(os.environ,{'OCLAST_DATA_DIR':self.temp.name}):
            import api
        self.api=api
        self.previous=api.store
        api.store=Projects(self.temp.name)
        self.client=TestClient(api.app)
        self.image=cv2.imencode('.png',np.full((100,100,3),220,np.uint8))[1].tobytes()

    def tearDown(self):
        self.api.store.source.cache_clear()
        self.api.store.labels.cache_clear()
        self.api.store.probability.cache_clear()
        self.api.store=self.previous
        self.temp.cleanup()

    def upload(self):
        return self.client.post('/api/projects',files={'file':('sample.png',self.image,'image/png')})

    def test_low_memory_import_is_rejected_and_next_import_succeeds(self):
        with patch('oclast.resources.available_memory_bytes',return_value=1):
            self.assertEqual(self.upload().status_code,413)
        self.assertEqual(self.client.get('/api/health').status_code,200)
        self.assertEqual(self.upload().status_code,201)

    def test_oversized_header_rejected_before_decode(self):
        with patch.object(self.api,'MAX_IMAGE_PIXELS',10),patch.object(self.api.cv2,'imread') as decode:
            self.assertEqual(self.upload().status_code,413)
            decode.assert_not_called()

    def test_upload_size_limit_and_busy_worker_do_not_poison_lock(self):
        with patch.object(self.api,'MAX_UPLOAD_BYTES',10):
            self.assertEqual(self.upload().status_code,413)
        self.api.resource_lock.acquire()
        try:
            self.assertEqual(self.upload().status_code,409)
        finally:
            self.api.resource_lock.release()
        self.assertEqual(self.upload().status_code,201)

    def test_one_analysis_admitted_and_failure_releases_worker(self):
        identifier=self.upload().json()['id']
        path=f'/api/projects/{identifier}/analyze'
        with patch.object(self.api.workers,'submit'):
            self.assertEqual(self.client.post(path).status_code,202)
            second=self.upload()
            self.assertEqual(second.status_code,409)
        with patch.object(self.api,'infer_image',side_effect=MemoryError('Not enough memory; crop the image')):
            self.api.analyze(identifier)
        self.assertEqual(self.api.store.get(identifier)['status'],'error')
        self.assertEqual(self.upload().status_code,201)

    def test_failed_export_cleans_temp_and_releases_worker(self):
        identifier=self.upload().json()['id']
        p=np.zeros((100,100),np.float32)
        self.api.store.save_analysis(identifier,p,p.astype(np.uint32),'hash',1.)
        with patch.object(self.api.tempfile,'mkstemp',side_effect=OSError('Disk full')):
            response=self.client.get(f'/api/projects/{identifier}/export/analysis.zip')
            self.assertEqual(response.status_code,507)
        self.assertEqual(self.upload().status_code,201)

    def test_streamed_export_removes_temporary_archive(self):
        identifier=self.upload().json()['id']
        p=np.zeros((100,100),np.float32)
        self.api.store.save_analysis(identifier,p,p.astype(np.uint32),'hash',1.)
        original=self.api.tempfile.mkstemp
        paths=[]
        def temporary(**kwargs):
            fd,name=original(**kwargs);paths.append(Path(name));return fd,name
        with patch.object(self.api.tempfile,'mkstemp',side_effect=temporary):
            response=self.client.get(f'/api/projects/{identifier}/export/training.zip')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.content.startswith(b'PK'))
        self.assertTrue(paths)
        self.assertTrue(all(not path.exists() for path in paths))

    def test_disconnected_export_removes_temporary_archive(self):
        path=Path(self.temp.name)/'disconnected.zip'
        path.write_bytes(b'archive')
        async def disconnected_send(message):
            raise ConnectionError('Download disconnected')
        async def receive():
            return {'type':'http.disconnect'}
        scope={'type':'http','method':'GET','headers':[], 'extensions':{}}
        with self.assertRaises(Exception):
            asyncio.run(self.api.TemporaryArchiveResponse(path)(scope,receive,disconnected_send))
        self.assertFalse(path.exists())

    def test_failed_import_does_not_leave_an_unlisted_source(self):
        with patch.object(self.api.cv2,'imwrite',return_value=False):
            self.assertEqual(self.upload().status_code,507)
        self.assertEqual(list(Path(self.temp.name).iterdir()),[])

    def test_failed_prediction_save_does_not_replace_existing_file(self):
        identifier=self.upload().json()['id']
        folder=self.api.store.folder(identifier)
        (folder/'probability.npz').write_bytes(b'previous-file')
        def interrupted(path,**kwargs):
            Path(path).write_bytes(b'incomplete-write')
            raise OSError('Disk full')
        with patch('oclast.projects.np.savez_compressed',side_effect=interrupted):
            with self.assertRaises(OSError):
                self.api.store.save_analysis(identifier,np.zeros((100,100),np.float32),
                                             np.zeros((100,100),np.uint32),'hash',1.)
        self.assertEqual((folder/'probability.npz').read_bytes(),b'previous-file')
        self.assertFalse((folder/'probability.next.npz').exists())


class MemoryBudgetTests(unittest.TestCase):
    def test_headroom_and_unknown_platform(self):
        with patch('oclast.resources.available_memory_bytes',return_value=300*1024**2):
            with self.assertRaisesRegex(MemoryError,'crop'):
                require_memory(100*1024**2)
        with patch('oclast.resources.available_memory_bytes',return_value=None):
            require_memory(100*1024**2)
