"""Disk-full failures must preserve the previous project and allow retry."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from oclast.projects import Projects, write_json


class ProjectFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Projects(self.temp.name)
        meta = self.store.create(np.full((100,120,3),210,np.uint8), 'field.png', 'hash')
        self.identifier = meta['id']
        self.folder = self.store.folder(self.identifier)
        self.labels = np.zeros((100,120),np.uint32)
        self.labels[10:30,10:30] = 1
        self.store.save_analysis(self.identifier, np.zeros(self.labels.shape,np.float32),
                                 self.labels, 'model-hash', 1.)

    def tearDown(self):
        self.store.source.cache_clear()
        self.store.labels.cache_clear()
        self.store.probability.cache_clear()
        self.temp.cleanup()

    def test_disk_full_error_status_visible_and_successful_retry_clears_overlay(self):
        self.store.update(self.identifier,status='running')
        with patch('oclast.projects.write_json',side_effect=OSError('Disk full')):
            with self.assertLogs('oclast.projects',level='ERROR'):
                self.store.mark_error(self.identifier,'Disk full; free some space and retry',4.)
            self.assertEqual(self.store.get(self.identifier)['status'],'error')
            self.assertEqual(self.store.list()[0]['error'],'Disk full; free some space and retry')
        self.assertEqual(json.loads((self.folder/'project.json').read_text())['status'],'running')
        self.store.update(self.identifier,status='queued',error=None)
        self.assertEqual(self.store.get(self.identifier)['status'],'queued')
        self.assertEqual(self.store._errors,{})
        self.assertEqual(Projects(self.temp.name).get(self.identifier)['status'],'interrupted')

    def test_failed_undo_backup_preserves_previous_undo_and_labels(self):
        self.store.edit(self.identifier,points=[[50,50],[65,50],[65,65],[50,65]])
        previous_undo = (self.folder/'undo.npz').read_bytes()
        previous_labels = (self.folder/'labels.npz').read_bytes()
        def failed_copy(source,target):
            Path(target).write_bytes(b'partial-backup')
            raise OSError('Disk full')
        with patch('shutil.copyfile',side_effect=failed_copy):
            with self.assertRaisesRegex(OSError,'Disk full'):
                self.store.edit(self.identifier,points=[[80,50],[95,50],[95,65],[80,65]])
        self.assertEqual((self.folder/'undo.npz').read_bytes(),previous_undo)
        self.assertEqual((self.folder/'labels.npz').read_bytes(),previous_labels)
        self.assertFalse((self.folder/'undo.next.npz').exists())
        self.assertEqual(self.store.undo(self.identifier)['count'],1)

    def test_new_undo_restores_embedded_manual_identity_without_sidecar(self):
        first=self.store.edit(self.identifier,points=[[50,50],[65,50],[65,65],[50,65]])
        self.store.edit(self.identifier,points=[[80,50],[95,50],[95,65],[80,65]])
        self.assertFalse((self.folder/'undo.json').exists())
        restored=self.store.undo(self.identifier)
        self.assertEqual(restored['manual_ids'],first['manual_ids'])
        self.assertEqual(restored['count'],first['count'])

    def test_old_undo_sidecar_remains_readable(self):
        self.store.edit(self.identifier,points=[[50,50],[65,50],[65,65],[50,65]])
        np.savez_compressed(self.folder/'undo.npz',labels=self.labels)
        (self.folder/'undo.json').write_text(json.dumps({'manual_ids':[]}))
        self.assertEqual(self.store.undo(self.identifier)['count'],1)
        self.assertFalse((self.folder/'undo.json').exists())

    def test_failed_label_write_preserves_master_and_removes_partial(self):
        previous=(self.folder/'labels.npz').read_bytes()
        def failed_save(path,**kwargs):
            Path(path).write_bytes(b'partial-prediction')
            raise OSError('Disk full')
        with patch('oclast.projects.np.savez_compressed',side_effect=failed_save):
            with self.assertRaisesRegex(OSError,'Disk full'):
                self.store.save_labels(self.identifier,self.labels,[])
        self.assertEqual((self.folder/'labels.npz').read_bytes(),previous)
        self.assertFalse((self.folder/'labels.next.npz').exists())

    def test_failed_json_write_preserves_master_and_removes_partial(self):
        target=self.folder/'project.json'
        previous=target.read_bytes()
        original=Path.write_text
        def failed_write(path,*args,**kwargs):
            original(path,'partial-json',encoding='utf-8')
            raise OSError('Disk full')
        with patch.object(Path,'write_text',failed_write):
            with self.assertRaisesRegex(OSError,'Disk full'):
                write_json(target,{'status':'running'})
        self.assertEqual(target.read_bytes(),previous)
        self.assertFalse(target.with_suffix('.tmp').exists())
