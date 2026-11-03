"""Real queue/persistence races and collection identity without model inference."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from oclast.batch import AnalysisQueue, image_summary, source_path
from oclast.projects import Projects, write_json


def wait_idle(queue):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        with queue.lock:
            if not queue._scheduled:return
        time.sleep(.005)
    raise AssertionError('Queue did not become idle')


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Projects(self.temp.name)
        self.executor=ThreadPoolExecutor(max_workers=1)
        self.resource=threading.Lock()
        self.ids=[self.store.create(np.full((20,20,3),210,np.uint8),f'image{i}.png',str(i))['id'] for i in range(3)]

    def tearDown(self):
        self.executor.shutdown(wait=True)
        self.store.source.cache_clear();self.store.labels.cache_clear();self.store.probability.cache_clear()
        self.temp.cleanup()

    def complete(self,identifier):
        self.store.update(identifier,status='complete')

    def test_serial_execution_waits_for_shared_resources_and_deduplicates(self):
        started=threading.Event();calls=[]
        def run(identifier):
            calls.append(identifier);started.set();self.complete(identifier)
        queue=AnalysisQueue(self.store,self.executor,self.resource,run)
        self.resource.acquire()
        queue.enqueue([self.ids[0],self.ids[0],self.ids[1]])
        self.assertFalse(started.wait(.05))
        self.assertEqual(queue.snapshot()['pending_ids'],self.ids[:2])
        self.resource.release();wait_idle(queue)
        self.assertEqual(calls,self.ids[:2])
        self.assertEqual(queue.snapshot()['completed_ids'],self.ids[:2])
        queue.enqueue([self.ids[0]]);wait_idle(queue)
        self.assertEqual(calls,self.ids[:2])

    def test_pause_finishes_active_then_resume_and_clear_only_pending(self):
        started=threading.Event();finish=threading.Event();calls=[]
        def run(identifier):
            calls.append(identifier)
            if identifier==self.ids[0]:started.set();self.assertTrue(finish.wait(3))
            self.complete(identifier)
        queue=AnalysisQueue(self.store,self.executor,self.resource,run)
        queue.enqueue(self.ids);self.assertTrue(started.wait(2))
        state=queue.control('pause');self.assertEqual(state['active_id'],self.ids[0])
        finish.set();wait_idle(queue)
        self.assertEqual(calls,self.ids[:1])
        self.assertTrue(queue.snapshot()['paused'])
        queue.control('clear')
        self.assertEqual(self.store.get(self.ids[1])['status'],'ready')
        self.assertEqual(queue.snapshot()['pending_ids'],[])
        queue.enqueue(self.ids[1:]);self.assertEqual(calls,self.ids[:1])
        queue.control('resume');wait_idle(queue)
        self.assertEqual(calls,self.ids)

    def test_failed_image_does_not_stop_next_and_can_be_retried(self):
        fail={self.ids[0]}
        def run(identifier):
            if identifier in fail:raise OSError('Simulated bad source')
            self.complete(identifier)
        queue=AnalysisQueue(self.store,self.executor,self.resource,run)
        with self.assertLogs('oclast.batch',level='ERROR'):
            queue.enqueue(self.ids[:2]);wait_idle(queue)
        self.assertEqual(queue.snapshot()['failed_ids'],self.ids[:1])
        self.assertEqual(queue.snapshot()['completed_ids'],self.ids[1:2])
        self.assertEqual(self.store.get(self.ids[0])['status'],'error')
        fail.clear();queue.enqueue(self.ids[:1]);wait_idle(queue)
        self.assertEqual(queue.snapshot()['failed_ids'],[])
        self.assertTrue(self.resource.acquire(blocking=False));self.resource.release()

    def test_fifty_lightweight_images_fifo_failure_continuation_and_retry(self):
        """Exercise queue scale with tiny sources and fake inference, not full TIFFs."""
        identifiers=self.ids+[
            self.store.create(np.full((20,20,3),210,np.uint8),f'stress{i}.png',f'stress{i}')['id']
            for i in range(47)
        ]
        failed_id=identifiers[17]
        calls=[];active=0;peak_active=0;attempts={}
        counter_lock=threading.Lock()
        def run(identifier):
            nonlocal active,peak_active
            with counter_lock:
                active+=1;peak_active=max(peak_active,active)
                calls.append(identifier)
                attempts[identifier]=attempts.get(identifier,0)+1
            try:
                self.store.update(identifier,status='running',progress=0,completed_tiles=0,total_tiles=1)
                if identifier==failed_id and attempts[identifier]==1:
                    raise OSError('Injected image 18 failure')
                self.store.update(identifier,status='complete',progress=100,completed_tiles=1,total_tiles=1)
            finally:
                with counter_lock:active-=1

        # Spare executor threads must not allow the queue to overlap image jobs.
        with ThreadPoolExecutor(max_workers=4) as executor:
            queue=AnalysisQueue(self.store,executor,self.resource,run)
            with self.assertLogs('oclast.batch',level='ERROR'):
                queue.enqueue(identifiers);wait_idle(queue)
            state=queue.snapshot()
            self.assertEqual(calls,identifiers)
            self.assertEqual(peak_active,1);self.assertEqual(active,0)
            self.assertIsNone(state['active_id']);self.assertEqual(state['pending_ids'],[])
            self.assertEqual(state['failed_ids'],[failed_id])
            self.assertEqual(state['completed_ids'],[identifier for identifier in identifiers if identifier!=failed_id])
            self.assertEqual(len(state['completed_ids'])+len(state['failed_ids']),50)
            self.assertFalse(state['paused'])
            for identifier in state['completed_ids']:
                meta=self.store.get(identifier)
                self.assertEqual((meta['progress'],meta['completed_tiles'],meta['total_tiles']),(100,1,1))
            self.assertEqual(self.store.get(failed_id)['status'],'error')

            queue.enqueue([failed_id]);wait_idle(queue)
            self.assertEqual(calls,identifiers+[failed_id])
            self.assertEqual(attempts[failed_id],2)
            self.assertEqual(peak_active,1);self.assertEqual(active,0)
            # An idle retry is a new batch epoch: its progress is 1/1.
            self.assertEqual(queue.snapshot()['completed_ids'],[failed_id])
            self.assertEqual(queue.snapshot()['failed_ids'],[])
            self.assertTrue(all(self.store.get(identifier)['status']=='complete' for identifier in identifiers))
            self.assertEqual(self.store.get(failed_id)['progress'],100)

    def test_restart_restores_active_and_pending_paused_without_automatic_inference(self):
        self.store.update(self.ids[0],status='running')
        self.store.update(self.ids[1],status='queued')
        write_json(Path(self.temp.name)/'queue.json',dict(active_id=self.ids[0],pending_ids=self.ids[1:2],paused=False))
        reopened=Projects(self.temp.name);calls=[]
        queue=AnalysisQueue(reopened,self.executor,self.resource,lambda identifier:(calls.append(identifier),reopened.update(identifier,status='complete')))
        self.assertTrue(queue.snapshot()['paused'])
        self.assertEqual(queue.snapshot()['pending_ids'],self.ids[:2])
        self.assertEqual(reopened.get(self.ids[0])['status'],'interrupted')
        self.assertEqual(calls,[])
        queue.control('resume');wait_idle(queue)
        self.assertEqual(calls,self.ids[:2])

    def test_invalid_selection_has_no_partial_status_changes(self):
        queue=AnalysisQueue(self.store,self.executor,self.resource,self.complete)
        with self.assertRaises(KeyError):queue.enqueue([self.ids[0],'missing'])
        self.assertEqual(self.store.get(self.ids[0])['status'],'ready')
        self.assertFalse(queue.snapshot()['pending_ids'])

    def test_restart_recognizes_analysis_committed_before_queue_index_write(self):
        self.complete(self.ids[0])
        write_json(Path(self.temp.name)/'queue.json',dict(active_id=self.ids[0],pending_ids=self.ids[1:2]))
        calls=[]
        queue=AnalysisQueue(self.store,self.executor,self.resource,lambda identifier:calls.append(identifier))
        self.assertEqual(queue.snapshot()['completed_ids'],self.ids[:1])
        self.assertEqual(queue.snapshot()['pending_ids'],self.ids[1:2])
        self.assertTrue(queue.snapshot()['paused'])
        self.assertEqual(calls,[])

    def test_new_idle_batch_resets_progress_but_complete_only_request_keeps_it(self):
        queue=AnalysisQueue(self.store,self.executor,self.resource,self.complete)
        queue.enqueue(self.ids[:1]);wait_idle(queue)
        self.assertEqual(queue.snapshot()['completed_ids'],self.ids[:1])
        queue.enqueue(self.ids[:1])
        self.assertEqual(queue.snapshot()['completed_ids'],self.ids[:1])
        queue.control('pause');queue.enqueue(self.ids[1:2])
        self.assertEqual(queue.snapshot()['completed_ids'],[])
        self.assertEqual(queue.snapshot()['pending_ids'],self.ids[1:2])
        queue.control('resume');wait_idle(queue)
        self.assertEqual(queue.snapshot()['completed_ids'],self.ids[1:2])


class CollectionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        with patch.dict(os.environ,{'OCLAST_DATA_DIR':self.temp.name}):import api
        self.api=api;self.previous=api.store;api.store=Projects(self.temp.name)
        self.client=TestClient(api.app)
        self.image=cv2.imencode('.png',np.full((100,100,3),210,np.uint8))[1].tobytes()

    def tearDown(self):
        self.api.queue_for.cache_clear()
        self.api.store.source.cache_clear();self.api.store.labels.cache_clear();self.api.store.probability.cache_clear()
        self.api.store=self.previous
        self.temp.cleanup()

    def upload(self,path='folder/sample.png',reuse=False):
        return self.client.post('/api/projects',files={'file':('sample.png',self.image,'image/png')},
                                data={'source_path':path,'reuse_existing':str(reuse).lower()})

    def finish(self,identifier,empty=False):
        labels=np.zeros((100,100),np.uint32)
        if not empty:labels[10:30,10:30]=1
        self.api.store.save_analysis(identifier,(labels>0).astype(np.float32),labels,'model-hash',2.)

    def test_relative_provenance_and_reuse_preserve_existing_ready_image(self):
        first=self.upload(reuse=True);self.assertEqual(first.status_code,201)
        meta=first.json();self.assertEqual(meta['source_path'],'folder/sample.png')
        self.assertEqual(meta['source_size_bytes'],len(self.image))
        second=self.upload(reuse=True);self.assertEqual(second.json()['id'],meta['id'])
        other=self.upload(path='other/sample.png',reuse=True)
        self.assertNotEqual(other.json()['id'],meta['id'])
        self.assertEqual(self.upload(path='../outside.png').status_code,400)

    def test_completed_model_change_creates_new_image_instead_of_overwriting_review(self):
        first=self.upload(reuse=True).json();self.finish(first['id'])
        with patch.object(self.api,'model_hash',return_value='new-model-hash'):
            replacement=self.upload(reuse=True).json()
        self.assertNotEqual(first['id'],replacement['id'])
        self.assertEqual(self.api.store.get(first['id'])['status'],'complete')

    def test_summary_zero_statistics_identity_and_all_object_exports(self):
        first=self.upload('one/sample.png').json()['id']
        second=self.upload('two/sample.png').json()['id']
        self.finish(first);self.finish(second,empty=True)
        response=self.client.post('/api/collection/summary',json={'project_ids':[first,second]})
        self.assertEqual(response.status_code,200)
        rows=response.json();self.assertEqual(rows[0]['median_area'],400)
        self.assertEqual(rows[1]['count'],0);self.assertIsNone(rows[1]['mean_circularity'])
        self.assertEqual(rows[0]['source_path'],'one/sample.png')
        objects=self.client.get(f'/api/collection/export/objects.csv?ids={first},{second}')
        self.assertEqual(objects.status_code,200)
        exported=list(csv.DictReader(io.StringIO(objects.content.decode('utf-8-sig'))))
        self.assertEqual(len(exported),1);self.assertEqual(exported[0]['ProjectID'],first)
        self.assertEqual(exported[0]['SourcePath'],'one/sample.png')
        summary=self.client.get(f'/api/collection/export/summary.csv?ids={first},{second}')
        summaries=list(csv.DictReader(io.StringIO(summary.content.decode('utf-8-sig'))))
        self.assertEqual(len(summaries),2);self.assertEqual(summaries[1]['MeanArea_px2'],'')
        single=self.client.get(f'/api/projects/{first}/export/measurements.csv')
        self.assertIn('sample_',single.headers['content-disposition'])
        self.assertIn(first[:8],single.headers['content-disposition'])

    def test_incomplete_export_rejected_without_partial_download(self):
        identifier=self.upload().json()['id']
        self.assertEqual(self.client.get(f'/api/collection/export/objects.csv?ids={identifier}').status_code,409)
        self.assertEqual(self.client.post('/api/collection/summary',json={'project_ids':[identifier]}).status_code,409)

    def test_actual_queue_api_owns_resource_once_and_finishes_every_image(self):
        identifiers=[self.upload(f'folder{i}/sample.png').json()['id'] for i in range(2)]
        def predict(image,progress):
            self.assertTrue(self.api.resource_lock.locked())
            progress(1,1)
            return np.zeros(image.shape[:2],np.float32)
        with patch.object(self.api,'infer_image',side_effect=predict),patch.object(self.api,'model_hash',return_value='model-hash'):
            response=self.client.post('/api/queue',json={'project_ids':identifiers})
            self.assertEqual(response.status_code,202)
            wait_idle(self.api.queue_for(self.api.store))
        self.assertEqual(self.client.get('/api/queue').json()['completed_ids'],identifiers)
        self.assertTrue(all(self.api.store.get(identifier)['status']=='complete' for identifier in identifiers))
        self.assertFalse(self.api.resource_lock.locked())

    def test_next_analysis_releases_old_inspection_maps_before_predicting(self):
        previous=self.upload('old/sample.png').json()['id'];self.finish(previous)
        old_meta=self.api.store.get(previous)
        self.api.store.labels(previous,old_meta['revision'])
        self.api.store.probability(previous)
        current=self.upload('new/sample.png').json()['id']
        def predict(image,progress):
            self.assertEqual(self.api.store.labels.cache_info().currsize,0)
            self.assertEqual(self.api.store.probability.cache_info().currsize,0)
            return np.zeros(image.shape[:2],np.float32)
        with patch.object(self.api,'infer_image',side_effect=predict),patch.object(self.api,'model_hash',return_value='model-hash'):
            self.client.post('/api/queue',json={'project_ids':[current]})
            wait_idle(self.api.queue_for(self.api.store))
        self.assertEqual(self.api.store.get(current)['status'],'complete')

    def test_legacy_analysis_cannot_lock_out_an_already_scheduled_queue_worker(self):
        first=self.upload('one/sample.png').json()['id']
        second=self.upload('two/sample.png').json()['id']
        with patch.object(self.api.workers,'submit'):
            response=self.client.post('/api/queue',json={'project_ids':[first]})
            self.assertEqual(response.status_code,202)
            legacy=self.client.post(f'/api/projects/{second}/analyze')
            self.assertEqual(legacy.status_code,409)
            self.assertFalse(self.api.resource_lock.locked())
        self.api.queue_for(self.api.store)._scheduled=False

    def test_collection_csv_escapes_formula_like_source_labels(self):
        identifier=self.upload('=folder/sample.png').json()['id'];self.finish(identifier)
        self.api.store.update(identifier,name='  =sample.png')
        for kind in ('summary.csv','objects.csv'):
            response=self.client.get(f'/api/collection/export/{kind}?ids={identifier}')
            row=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))[0]
            self.assertEqual(row['Source'],"'  =sample.png")
            self.assertEqual(row['SourcePath'],"'=folder/sample.png")


class RelativePathTests(unittest.TestCase):
    def test_absolute_and_parent_paths_are_not_provenance_labels(self):
        for value in ('../x.png','C:\\images\\x.png','/root/x.png','folder/../x.png'):
            with self.subTest(value=value),self.assertRaises(ValueError):source_path(value,'x.png')
