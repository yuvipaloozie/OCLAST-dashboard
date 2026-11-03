"""Persistent sequential image jobs and image-level descriptive exports."""
import csv
import json
import logging
import threading
from pathlib import PurePosixPath

import numpy as np

from .projects import write_json

log=logging.getLogger(__name__)


def source_path(value, filename):
    """Retain a browser folder-relative label, never an arbitrary local path."""
    value=(value or filename).replace('\\','/')
    path=PurePosixPath(value)
    if (len(value)>1000 or path.is_absolute() or ':' in value or
            any(part in ('..','.') for part in value.split('/')) or
            any(ord(char)<32 for char in value)):
        raise ValueError('Use a relative image path without parent folders or drive letters.')
    return str(path)


class AnalysisQueue:
    def __init__(self, store, executor, resource_lock, run):
        self.store=store
        self.executor=executor
        self.resource_lock=resource_lock
        self.run=run
        self.lock=threading.RLock()
        self.path=store.root/'queue.json'
        self.paused=False
        self.active_id=None
        self.pending_ids=[]
        self.failed_ids=[]
        self.completed_ids=[]
        self._scheduled=False
        if self.path.exists():
            try:
                saved=json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(saved,dict):raise ValueError('Queue state must be an object')
                self.failed_ids=saved.get('failed_ids',[])
                self.completed_ids=saved.get('completed_ids',[])
                candidates=([saved['active_id']] if saved.get('active_id') else [])+saved.get('pending_ids',[])
                for identifier in dict.fromkeys(candidates):
                    try:
                        if store.get(identifier)['status']=='complete':
                            if identifier not in self.completed_ids:self.completed_ids.append(identifier)
                        else:self.pending_ids.append(identifier)
                    except (KeyError,OSError,ValueError):pass
                # A restarted app never silently starts a long batch again.
                self.paused=bool(self.pending_ids) or bool(saved.get('paused'))
            except (OSError,ValueError,TypeError):
                log.exception('Could not read saved image queue; saved projects remain available')

    def snapshot(self):
        with self.lock:
            return dict(paused=self.paused,active_id=self.active_id,
                        pending_ids=self.pending_ids[:],failed_ids=self.failed_ids[:],
                        completed_ids=self.completed_ids[:])

    def _save(self):
        write_json(self.path,self.snapshot())

    def _start(self):
        if not self.paused and self.pending_ids and not self._scheduled:
            self._scheduled=True
            try:self.executor.submit(self._drain)
            except BaseException:
                self._scheduled=False
                raise

    def enqueue(self, identifiers):
        with self.lock:
            unique=list(dict.fromkeys(identifiers))
            metas=[self.store.get(identifier) for identifier in unique]
            for meta in metas:
                identifier=meta['id']
                if identifier in self.pending_ids or identifier==self.active_id or meta['status']=='complete':continue
                if meta['status'] not in ('ready','error','interrupted'):
                    raise ValueError('An image is already being analyzed outside this queue.')
            actionable=[meta for meta in metas if meta['status']!='complete' and
                        meta['id'] not in self.pending_ids and meta['id']!=self.active_id]
            if actionable and not self.pending_ids and self.active_id is None:
                # Progress belongs to this new batch, not every job ever run.
                # Existing project results/errors remain in the image library.
                self.completed_ids=[]
                self.failed_ids=[]
            for meta in metas:
                identifier=meta['id']
                if identifier in self.pending_ids or identifier==self.active_id or meta['status']=='complete':continue
                self.store.update(identifier,status='queued',stage='Waiting in image queue',progress=0,
                                  completed_tiles=0,error=None)
                self.pending_ids.append(identifier)
                self.failed_ids=[item for item in self.failed_ids if item!=identifier]
            self._save()
            self._start()
            return self.snapshot()

    def control(self, action):
        with self.lock:
            if action=='pause':self.paused=True
            elif action=='resume':self.paused=False
            elif action=='clear':
                for identifier in self.pending_ids:
                    self.store.update(identifier,status='ready',stage='Ready to analyze',progress=0,error=None)
                self.pending_ids=[]
            else:raise ValueError('Choose pause, resume, or clear.')
            self._save()
            self._start()
            return self.snapshot()

    def _drain(self):
        while True:
            # Wait only in the background. Imports and exports can hold this
            # same slot, and only one model/image job may own full-size arrays.
            with self.resource_lock:
                with self.lock:
                    if self.paused or not self.pending_ids:
                        self._scheduled=False
                        return
                    identifier=self.pending_ids.pop(0)
                    self.active_id=identifier
                    try:self._save()
                    except OSError:
                        self.pending_ids.insert(0,identifier)
                        self.active_id=None
                        self.paused=True
                        self._scheduled=False
                        log.exception('Queue persistence failed before starting an image')
                        return
                try:
                    self.run(identifier)
                except Exception as exc:
                    log.exception('Queued analysis failed for %s',identifier)
                    self.store.mark_error(identifier,str(exc) or 'Analysis failed. Retry this image.',0)
                finally:
                    with self.lock:
                        self.active_id=None
                        if self.store.get(identifier)['status']=='complete':
                            if identifier not in self.completed_ids:self.completed_ids.append(identifier)
                        elif identifier not in self.failed_ids:self.failed_ids.append(identifier)
                        try:self._save()
                        except OSError:
                            self.paused=True
                            self._scheduled=False
                            log.exception('Queue persistence failed after analysis; queue paused')
                            return


def image_summary(meta, cells):
    area=np.asarray([cell['area'] for cell in cells],dtype=float)
    circularity=np.asarray([cell['circularity'] for cell in cells],dtype=float)
    total=float(area.sum())
    return dict(id=meta['id'],name=meta['name'],source_path=meta.get('source_path',meta['name']),
                width=meta['width'],height=meta['height'],count=len(cells),
                mean_area=float(area.mean()) if len(area) else None,
                median_area=float(np.median(area)) if len(area) else None,
                area_q1=float(np.percentile(area,25)) if len(area) else None,
                area_q3=float(np.percentile(area,75)) if len(area) else None,
                mean_circularity=float(circularity.mean()) if len(area) else None,
                median_circularity=float(np.median(circularity)) if len(area) else None,
                total_mask_area=total,mask_coverage_percent=100*total/(meta['width']*meta['height']),
                mean_solidity=float(np.mean([cell['solidity'] for cell in cells])) if len(area) else None,
                mean_eccentricity=float(np.mean([cell['eccentricity'] for cell in cells])) if len(area) else None,
                elapsed_seconds=meta.get('elapsed_seconds'),compute_device=meta.get('compute',{}).get('device'),
                revision=meta['revision'])


def spreadsheet_text(value):
    value=str(value or '')
    return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value


SUMMARY_COLUMNS=[('ProjectID','id'),('Source','name'),('SourcePath','source_path'),('Width_px','width'),
                 ('Height_px','height'),('ObjectCount','count'),('MeanArea_px2','mean_area'),
                 ('MedianArea_px2','median_area'),('AreaQ1_px2','area_q1'),('AreaQ3_px2','area_q3'),
                 ('MeanCircularity','mean_circularity'),('MedianCircularity','median_circularity'),
                 ('TotalMaskArea_px2','total_mask_area'),('ImageMaskCoverage_percent','mask_coverage_percent'),
                 ('MeanSolidity','mean_solidity'),('MeanEccentricity','mean_eccentricity'),
                 ('AnalysisTime_s','elapsed_seconds'),('ComputeDevice','compute_device'),('Revision','revision')]


def write_collection_csv(stream, store, identifiers, kind):
    """Write rows to a disk stream; each image keeps its own identity/units."""
    writer=csv.writer(stream)
    provenance=['SourceSHA256','ModelSHA256']
    if kind=='summary.csv':writer.writerow([name for name,_ in SUMMARY_COLUMNS]+provenance)
    else:writer.writerow(['ProjectID','Source','SourcePath','ObjectID','CentroidX_px','CentroidY_px',
                          'Area_px2','Circularity','Solidity','Eccentricity','Manual','Revision']+provenance)
    for identifier in identifiers:
        with store.lock:
            meta=store.get(identifier)
            if meta['status']!='complete':raise ValueError('Finish analysis for every selected image before exporting.')
            cells=store.cells(identifier)
            hashes=[meta.get('source_sha256',''),meta.get('model',{}).get('sha256','')]
            if kind=='summary.csv':
                row=image_summary(meta,cells)
                writer.writerow([spreadsheet_text(row.get(key)) if key in ('name','source_path') else row.get(key)
                                 for _,key in SUMMARY_COLUMNS]+hashes)
            else:
                for cell in cells:
                    writer.writerow([identifier,spreadsheet_text(meta['name']),
                                     spreadsheet_text(meta.get('source_path',meta['name'])),cell['id'],
                                     cell['x'],cell['y'],cell['area'],cell['circularity'],cell['solidity'],
                                     cell['eccentricity'],cell['manual'],meta['revision']]+hashes)
