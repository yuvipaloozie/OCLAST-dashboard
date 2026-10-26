"""Local, lossless, versioned projects. Nothing is uploaded to a hosted service."""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
from .analysis import measurements, summary


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, allow_nan=False), encoding='utf-8')
    os.replace(temporary, path)


class Projects:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        # A process restart must not leave old jobs pretending to be live.
        for path in self.root.glob('*/project.json'):
            try:
                meta = json.loads(path.read_text(encoding='utf-8'))
                if meta['status'] in ('queued','running'):
                    meta.update(status='interrupted',stage='Interrupted',error='The app stopped before analysis finished. You can run it again.')
                    write_json(path, meta)
            except (ValueError,KeyError,OSError):
                pass

    def folder(self, project_id):
        try:
            identifier = str(uuid.UUID(project_id))
        except ValueError:
            raise KeyError('Unknown project') from None
        folder = self.root / identifier
        if not (folder/'project.json').exists():
            raise KeyError('Unknown project')
        return folder

    def get(self, project_id):
        with self.lock:
            folder = self.folder(project_id)
            meta = json.loads((folder/'project.json').read_text(encoding='utf-8'))
            if meta['status'] == 'complete':
                state = self.label_state(folder)
                if state:
                    meta.update({k:state[k] for k in ('revision','manual_ids','edit_count','count','mean_area','mean_circularity','updated_at')})
            return meta

    @staticmethod
    def label_state(folder):
        path = folder/'labels.npz'
        if not path.exists():
            return None
        with np.load(path,allow_pickle=False) as data:
            return json.loads(data['state'].item()) if 'state' in data.files else None

    def update(self, project_id, **changes):
        with self.lock:
            meta = self.get(project_id)
            meta.update(changes, updated_at=now())
            write_json(self.folder(project_id)/'project.json', meta)
            return meta

    def list(self):
        result = []
        for path in self.root.glob('*/project.json'):
            try:
                result.append(self.get(path.parent.name))
            except (ValueError,KeyError,OSError):
                continue
        return sorted(result, key=lambda m:m['updated_at'], reverse=True)

    def create(self, image, filename, source_hash):
        identifier = str(uuid.uuid4())
        folder = self.root / identifier
        folder.mkdir()
        # One lossless pixel master, not the uploaded TIFF plus a decoded copy.
        if not cv2.imwrite(str(folder/'source.png'), image, [cv2.IMWRITE_PNG_COMPRESSION,3]):
            raise OSError('Could not save the source image')
        meta = dict(schema_version=1,id=identifier,name=Path(filename).name,
                    width=image.shape[1],height=image.shape[0],created_at=now(),updated_at=now(),
                    source_sha256=source_hash,status='ready',stage='Ready to analyze',
                    completed_tiles=0,total_tiles=0,progress=0,revision=0,
                    count=0,mean_area=0,mean_circularity=0,manual_ids=[],edit_count=0,
                    settings=dict(threshold=.5,min_area_px=50,min_peak_distance_px=20,
                                  preprocessing='V9',tile_size=512),error=None)
        write_json(folder/'project.json',meta)
        return meta

    @lru_cache(maxsize=1)
    def source(self, project_id):
        image = cv2.imread(str(self.folder(project_id)/'source.png'), cv2.IMREAD_COLOR)
        if image is None:
            raise OSError('Saved source image could not be read')
        return image

    @lru_cache(maxsize=1)
    def labels(self, project_id, revision):
        with np.load(self.folder(project_id)/'labels.npz', allow_pickle=False) as data:
            return data['labels']

    @lru_cache(maxsize=1)
    def probability(self, project_id):
        with np.load(self.folder(project_id)/'probability.npz', allow_pickle=False) as data:
            return data['probability']

    def cells(self, project_id):
        with self.lock:
            folder = self.folder(project_id)
            state = self.label_state(folder)
            if state:
                return state['cells']
            path = folder/'measurements.json'
            return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []

    def save_analysis(self, project_id, probability, labels, model_hash, elapsed):
        folder = self.folder(project_id)
        np.savez_compressed(folder/'probability.npz', probability=probability)
        self.probability.cache_clear()
        self.save_labels(project_id, labels, [], first=True)
        return self.update(project_id,status='complete',stage='Analysis complete',progress=100,
                           model=dict(id='unetpp_curriculum',file='unetplusplus.onnx',sha256=model_hash),
                           elapsed_seconds=elapsed() if callable(elapsed) else elapsed,error=None)

    def save_labels(self, project_id, labels, manual_ids, first=False):
        with self.lock:
            folder = self.folder(project_id)
            meta = self.get(project_id)
            rows = measurements(labels, manual_ids)
            state = dict(revision=meta['revision']+1,manual_ids=manual_ids,cells=rows,
                         edit_count=0 if first else meta['edit_count']+1,updated_at=now(),**summary(rows))
            temporary = folder/'labels.next.npz'
            # Geometry, measurements and review identity commit together. If the
            # app closes before the separate project index is updated, reopening
            # reads this authoritative state instead of stale summary values.
            np.savez_compressed(temporary, labels=labels,state=np.array(json.dumps(state)))
            os.replace(temporary,folder/'labels.npz')
            write_json(folder/'measurements.json', rows)
            self.labels.cache_clear()
            return self.update(project_id,**{k:v for k,v in state.items() if k not in ('cells','updated_at')})

    def edit(self, project_id, points=None, delete_id=None):
        with self.lock:
            meta = self.get(project_id)
            if meta['status'] != 'complete':
                raise ValueError('Finish analysis before editing')
            folder = self.folder(project_id)
            labels = self.labels(project_id, meta['revision']).copy()
            manual_ids = meta['manual_ids'][:]
            if delete_id is not None:
                if delete_id not in {c['id'] for c in self.cells(project_id)}:
                    raise ValueError('Select an existing object')
                labels[labels == delete_id] = 0
                manual_ids = [i for i in manual_ids if i != delete_id]
            else:
                polygon = np.asarray(points,dtype=np.float64)
                if polygon.ndim != 2 or polygon.shape[1] != 2 or len(polygon)<3 or not np.isfinite(polygon).all():
                    raise ValueError('Draw a polygon with at least three points')
                h,w = labels.shape
                if (polygon[:,0]<0).any() or (polygon[:,0]>=w).any() or (polygon[:,1]<0).any() or (polygon[:,1]>=h).any():
                    raise ValueError('Draw within the image')
                x0,y0 = np.floor(polygon.min(axis=0)).astype(int)
                x1,y1 = np.ceil(polygon.max(axis=0)).astype(int)
                selected = np.zeros((y1-y0+1,x1-x0+1),np.uint8)
                cv2.fillPoly(selected, [np.rint(polygon-[x0,y0]).astype(np.int32)],1)
                if selected.sum()<=50:
                    raise ValueError('The added object must be larger than 50 pixels')
                region = labels[y0:y1+1,x0:x1+1]
                if (region[selected>0]>0).any():
                    raise ValueError('The polygon overlaps an existing object. Delete that object first if replacing it.')
                identifier = int(labels.max())+1
                region[selected>0] = identifier
                manual_ids.append(identifier)
            # One undo slot, compressed; it does not accumulate a full-image history.
            if (folder/'labels.npz').exists():
                import shutil
                shutil.copyfile(folder/'labels.npz',folder/'undo.npz')
                write_json(folder/'undo.json',dict(manual_ids=meta['manual_ids']))
            return self.save_labels(project_id,labels,manual_ids)

    def undo(self, project_id):
        with self.lock:
            folder = self.folder(project_id)
            if not (folder/'undo.npz').exists():
                raise ValueError('There is no edit to undo')
            with np.load(folder/'undo.npz',allow_pickle=False) as data:
                labels = data['labels']
            manual = json.loads((folder/'undo.json').read_text(encoding='utf-8'))['manual_ids']
            meta = self.save_labels(project_id,labels,manual)
            (folder/'undo.npz').unlink()
            (folder/'undo.json').unlink()
            return meta
