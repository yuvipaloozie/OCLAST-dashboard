"""OCLAST local desktop service: saved projects and full-resolution image tiles."""
import csv
import hashlib
import io
import json
import os
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from functools import lru_cache

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from oclast.analysis import infer_image, separate_whole_image, model_hash, compute_status
from oclast.projects import Projects
from oclast.thumbnails import object_thumbnail

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'OCLAST' / 'projects' if getattr(sys,'frozen',False) else ROOT/'data'/'projects'
store = Projects(os.environ.get('OCLAST_DATA_DIR',str(DEFAULT_DATA)))
workers = ThreadPoolExecutor(max_workers=1, thread_name_prefix='oclast-analysis')
job_lock = Lock()
app = FastAPI(title='OCLAST local analysis',version='1.2.0')
app.add_middleware(CORSMiddleware,allow_origins=['http://127.0.0.1:5173','http://localhost:5173'],
                   allow_methods=['GET','POST','PATCH'],allow_headers=['Content-Type'])


@app.exception_handler(KeyError)
async def missing_project(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=404,content={'detail':'Saved project not found'})


@app.get('/api/health')
def health():
    return dict(status='ok',project_directory=str(store.root.resolve()),local_only=True,compute=compute_status())


@app.get('/api/projects')
def list_projects():
    return store.list()


@app.post('/api/projects',status_code=201)
async def create_project(file: UploadFile=File(...)):
    # Spool uploaded bytes to disk through Starlette, decode once, save one
    # lossless source master. Reject unsupported precision instead of downcasting.
    contents = await file.read()
    if not contents:
        raise HTTPException(400,'Choose a nonempty TIFF, PNG, or JPEG image.')
    image = cv2.imdecode(np.frombuffer(contents,np.uint8),cv2.IMREAD_UNCHANGED)
    if image is None:
        raise HTTPException(400,'This image could not be decoded. Choose a readable TIFF, PNG, or JPEG.')
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise HTTPException(400,'This model expects a single 8-bit RGB image. Convert grayscale, 16-bit, RGBA, or stack data before analysis.')
    return store.create(image,Path(file.filename or 'Untitled image').name,hashlib.sha256(contents).hexdigest())


@app.get('/api/projects/{project_id}')
def get_project(project_id:str):
    meta=store.get(project_id)
    folder=store.folder(project_id)
    return dict(**meta,can_undo=(folder/'undo.npz').exists(),
                storage_bytes=sum(p.stat().st_size for p in folder.iterdir() if p.is_file()))


@app.get('/api/projects/{project_id}/cells')
def cells(project_id:str):
    return store.cells(project_id)


@lru_cache(maxsize=128)
def cached_object_thumbnail(project_id, revision, object_id, masks):
    cell=next(c for c in store.cells(project_id) if c['id']==object_id)
    return object_thumbnail(store.source(project_id),store.labels(project_id,revision),cell,masks)


@app.get('/api/projects/{project_id}/objects/{object_id}/thumbnail')
def thumbnail(project_id:str,object_id:int,revision:int,masks:bool=True):
    with store.lock:
        meta=store.get(project_id)
        if meta['status']!='complete':
            raise HTTPException(409,'Finish analysis before inspecting objects')
        if revision!=meta['revision']:
            raise HTTPException(409,'This object changed. Reopen the project to refresh its masks.')
        if not any(c['id']==object_id for c in store.cells(project_id)):
            raise HTTPException(404,'Object not found')
        data=cached_object_thumbnail(project_id,revision,object_id,masks)
    return Response(data,media_type='image/jpeg',headers={'Cache-Control':'private, max-age=3600'})


class Rename(BaseModel):
    name: str=Field(min_length=1,max_length=200)


@app.patch('/api/projects/{project_id}')
def rename(project_id:str,body:Rename):
    return store.update(project_id,name=body.name.strip() or 'Untitled analysis')


def analyze(project_id):
    started=time.perf_counter()
    try:
        image=store.source(project_id)
        total=((image.shape[0]+511)//512)*((image.shape[1]+511)//512)
        store.update(project_id,status='running',stage='Predicting image tiles',total_tiles=total,started_at=time.time(),error=None)
        def progress(done,total):
            store.update(project_id,completed_tiles=done,progress=round(85*done/total,1),
                         elapsed_seconds=round(time.perf_counter()-started,1),compute=compute_status())
        probability=infer_image(image,progress)
        store.update(project_id,stage='Separating objects across the whole image',progress=88)
        labels=separate_whole_image(probability)
        store.update(project_id,stage='Saving predictions and measurements',progress=95)
        store.save_analysis(project_id,probability,labels,model_hash(),lambda:round(time.perf_counter()-started,2))
    except Exception as exc:
        store.update(project_id,status='error',stage='Analysis failed',error=str(exc),elapsed_seconds=round(time.perf_counter()-started,1))


@app.post('/api/projects/{project_id}/analyze',status_code=202)
def run_analysis(project_id:str):
    with job_lock:
        meta=store.get(project_id)
        if meta['status'] not in ('ready','error','interrupted'):
            raise HTTPException(409,'This analysis is already running or saved. Create another project to run it again.')
        store.update(project_id,status='queued',stage='Waiting for the local analysis worker',progress=0,error=None)
        workers.submit(analyze,project_id)
    return store.get(project_id)


@app.get('/api/projects/{project_id}/tiles/{layer}/{level}/{column}/{row}')
def image_tile(project_id:str,layer:str,level:int,column:int,row:int):
    # Serialize cache misses: several visible tiles must not each decompress
    # the same full-resolution source/label array at the same time.
    with store.lock:
        return render_tile(project_id,layer,level,column,row)


def render_tile(project_id:str,layer:str,level:int,column:int,row:int):
    meta=store.get(project_id)
    if layer not in ('raw','labels','probability') or not 0<=level<=8 or column<0 or row<0:
        raise HTTPException(400,'Invalid image tile')
    step=2**level
    y,x=row*512*step,column*512*step
    bottom,right=min(y+512*step,meta['height']),min(x+512*step,meta['width'])
    if y>=bottom or x>=right:
        raise HTTPException(404,'Outside image bounds')
    size=((right-x+step-1)//step,(bottom-y+step-1)//step)
    if layer=='raw':
        crop=store.source(project_id)[y:bottom,x:right]
        tile=cv2.resize(crop,size,interpolation=cv2.INTER_AREA)
        ok,encoded=cv2.imencode('.jpg',tile,[cv2.IMWRITE_JPEG_QUALITY,92])
        media='image/jpeg'
    else:
        if meta['status']!='complete':
            raise HTTPException(409,'Analysis is not complete')
        if layer=='labels':
            labels=store.labels(project_id,meta['revision'])[y:bottom,x:right]
            labels=labels[::step,::step]
            tile=np.zeros((*labels.shape,4),np.uint8)
            tile[labels>0]=[177,42,185,105]  # BGRA; identical filtered objects as counts.
            manual=np.isin(labels,meta['manual_ids']) if meta['manual_ids'] else np.zeros(labels.shape,bool)
            tile[manual]=[84,180,35,120]
            # Make adjacent watershed objects visibly separate.
            edges=(labels!=np.roll(labels,1,axis=0))|(labels!=np.roll(labels,1,axis=1))
            tile[edges & (labels>0)]=[255,255,255,230]
        else:
            values=store.probability(project_id)[y:bottom,x:right]
            values=cv2.resize(values,size,interpolation=cv2.INTER_AREA)
            tile=cv2.cvtColor(cv2.applyColorMap(np.uint8(np.clip(values,0,1)*255),cv2.COLORMAP_TURBO),cv2.COLOR_BGR2BGRA)
            tile[...,3]=140
        ok,encoded=cv2.imencode('.png',tile)
        media='image/png'
    if not ok:
        raise HTTPException(500,'Could not render image tile')
    return Response(encoded.tobytes(),media_type=media,headers={'Cache-Control':'private, max-age=3600'})


class Edit(BaseModel):
    points: list[list[float]] | None=None
    delete_id: int | None=None
    revision: int


@app.post('/api/projects/{project_id}/edits')
def edit(project_id:str,body:Edit):
    with store.lock:
        if store.get(project_id)['revision']!=body.revision:
            raise HTTPException(409,'This project changed in another window. Reopen it before editing.')
        if (body.points is None)==(body.delete_id is None):
            raise HTTPException(400,'Choose one edit action')
        try:
            store.edit(project_id,body.points,body.delete_id)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc
    return get_project(project_id)


class Revision(BaseModel):
    revision:int


@app.post('/api/projects/{project_id}/undo')
def undo(project_id:str,body:Revision):
    with store.lock:
        if store.get(project_id)['revision']!=body.revision:
            raise HTTPException(409,'This project changed in another window. Reopen it before editing.')
        try:
            store.undo(project_id)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc
    return get_project(project_id)


def csv_data(project_id):
    stream=io.StringIO(newline='')
    writer=csv.writer(stream)
    writer.writerow(['Source','ObjectID','CentroidX_px','CentroidY_px','Area_px2','Circularity','Solidity','Eccentricity','Manual'])
    name=store.get(project_id)['name']
    # Prevent filenames from becoming spreadsheet formulas on export.
    if name.startswith(('=','+','-','@')): name="'"+name
    for c in store.cells(project_id):
        writer.writerow([name,c['id'],c['x'],c['y'],c['area'],c['circularity'],c['solidity'],c['eccentricity'],c['manual']])
    return stream.getvalue().encode('utf-8-sig')


@app.get('/api/projects/{project_id}/export/{kind}')
def export(project_id:str,kind:str):
    meta=store.get(project_id)
    if meta['status']!='complete':
        raise HTTPException(409,'Finish analysis before exporting')
    if kind=='measurements.csv':
        return Response(csv_data(project_id),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="oclast_measurements.csv"'})
    buffer=io.BytesIO()
    with store.lock,zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        meta=store.get(project_id)
        labels=store.labels(project_id,meta['revision'])
        if kind=='analysis.zip':
            archive.writestr('project.json',json.dumps(meta,indent=2))
            archive.writestr('measurements.csv',csv_data(project_id))
            archive.write(store.folder(project_id)/'labels.npz','labels.npz')
            ok,png=cv2.imencode('.png',np.uint8(labels>0)*255)
            archive.writestr('foreground_mask.png',png.tobytes())
        elif kind=='training.zip':
            image=store.source(project_id)
            for y in range(0,meta['height'],512):
                for x in range(0,meta['width'],512):
                    crop=image[y:y+512,x:x+512]
                    mask=np.uint8(labels[y:y+512,x:x+512]>0)*255
                    name=f'tile_y{y}_x{x}'
                    archive.writestr(f'images/{name}.png',cv2.imencode('.png',crop)[1].tobytes())
                    archive.writestr(f'masks/{name}.png',cv2.imencode('.png',mask)[1].tobytes())
            archive.writestr('project.json',json.dumps(meta,indent=2))
        else:
            raise HTTPException(404,'Unknown export')
    return Response(buffer.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="oclast_{kind}"'})


frontend=ROOT/'frontend'/'dist'
if frontend.is_dir():
    app.mount('/assets',StaticFiles(directory=frontend/'assets'),name='assets')
    if (frontend/'fonts').is_dir():
        app.mount('/fonts',StaticFiles(directory=frontend/'fonts'),name='fonts')
    @app.get('/favicon.svg')
    def favicon():
        return FileResponse(frontend/'favicon.svg')
    @app.get('/')
    def index():
        return FileResponse(frontend/'index.html')

if __name__=='__main__':
    import multiprocessing
    import threading
    import webbrowser
    import uvicorn
    multiprocessing.freeze_support()
    port=int(os.environ.get('OCLAST_PORT','8000'))
    if not 1<=port<=65535:
        raise ValueError('OCLAST_PORT must be between 1 and 65535')
    print(f'OCLAST 1.2.0 — http://127.0.0.1:{port}',flush=True)
    print(f'Saved projects: {store.root.resolve()}',flush=True)
    print('Keep this window open while using OCLAST. Close it to stop the app.',flush=True)
    if not os.environ.get('OCLAST_NO_BROWSER'):
        threading.Timer(1.5,lambda:webbrowser.open(f'http://127.0.0.1:{port}')).start()
    uvicorn.run(app,host='127.0.0.1',port=port)
