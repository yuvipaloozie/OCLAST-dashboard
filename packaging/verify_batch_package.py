"""Verify the shipped EXE's batch queue on CPU, with isolated temporary projects.

This exercises queue persistence and exports on three 1024px crops. For a full
60MP image under the same laptop constraints use verify_cpu_package.py.
"""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time

import cv2
import httpx
from verify_cpu_package import ConstraintJob, windows_api


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,default=Path(__file__).resolve().parents[1]/'dist/OCLAST.exe')
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.exe=args.exe.resolve();args.output=args.output.resolve()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    report={'status':'running','exe_sha256':hashlib.sha256(args.exe.read_bytes()).hexdigest(),
            'scope':'Actual Windows EXE; three 1024px crops, CPU; not a full-image batch benchmark.'}
    k,_=windows_api();process=job=log=None
    with tempfile.TemporaryDirectory(prefix='oclast-batch-package-') as scratch:
        root=Path(scratch)
        for name in ['user','temp','cwd']:(root/name).mkdir()
        with socket.socket() as available:
            available.bind(('127.0.0.1',0));port=available.getsockname()[1]
        env=os.environ.copy()
        for key in list(env):
            if key.startswith(('PYTHON','CONDA','OCLAST_')):env.pop(key)
        env.update(OCLAST_PORT=str(port),OCLAST_NO_BROWSER='1',OCLAST_DEVICE='cpu',OCLAST_CPU_THREADS='2',
                   LOCALAPPDATA=str(root/'user'),TEMP=str(root/'temp'),TMP=str(root/'temp'),
                   PATH=os.environ['SystemRoot']+'\\System32;'+os.environ['SystemRoot'])
        client=httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=60,trust_env=False)
        def request(method,path,**kwargs):
            response=client.request(method,path,**kwargs);response.raise_for_status();return response
        def stop():
            nonlocal process,job,log
            if job:job.close();job=None
            if process:
                if process.poll() is None:subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
                process.wait(timeout=30);process=None
            if log:log.close();log=None
        def start(label):
            nonlocal process,job,log
            log=args.output.with_name(args.output.stem+'-'+label+'.log').open('w',encoding='utf-8')
            process=subprocess.Popen([str(args.exe)],cwd=root/'cwd',env=env,stdout=log,stderr=subprocess.STDOUT,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            job=ConstraintJob(k,process,4,2);report['constraints']=job.report
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('Packaged app exited during startup')
                try:
                    if client.get('/api/health',timeout=2).json().get('application')=='OCLAST':return
                except (httpx.HTTPError,ValueError):pass
                time.sleep(.25)
            raise TimeoutError('Packaged app did not start')
        try:
            start('initial')
            image=cv2.imread(str(args.image))
            assert image is not None
            ids=[]
            for index,(x,y) in enumerate([(2600,2600),(3400,3400),(4200,4200)],1):
                crop=image[y:y+1024,x:x+1024];assert crop.shape[:2]==(1024,1024)
                ok,encoded=cv2.imencode('.png',crop);assert ok
                payload=encoded.tobytes();name=f'sample-{index}.png'
                def upload():
                    return request('POST','/api/projects',files={'file':(name,payload,'image/png')},
                                   data={'source_path':f'batch/{name}','reuse_existing':'true'}).json()
                project=upload();ids.append(project['id'])
                assert upload()['id']==project['id']
            del image
            assert len(request('GET','/api/projects').json())==3
            request('POST','/api/queue/control',json={'action':'pause'})
            queued=request('POST','/api/queue',json={'project_ids':ids}).json()
            assert queued['paused'] and queued['pending_ids']==ids and queued['active_id'] is None
            stop();start('restart')
            recovered=request('GET','/api/queue').json()
            assert recovered['paused'] and recovered['pending_ids']==ids and recovered['active_id'] is None
            report['paused_restart_recovery']='passed'
            request('POST','/api/queue/control',json={'action':'resume'})
            deadline=time.monotonic()+300
            while time.monotonic()<deadline:
                queue=request('GET','/api/queue').json()
                if not queue['active_id'] and not queue['pending_ids']:break
                time.sleep(.25)
            else:raise TimeoutError('Packaged CPU queue did not finish')
            assert queue['completed_ids']==ids and not queue['failed_ids']
            projects=[request('GET',f'/api/projects/{identifier}').json() for identifier in ids]
            assert all(p['status']=='complete' and p['compute']['device']=='cpu' for p in projects)
            summaries=request('POST','/api/collection/summary',json={'project_ids':ids}).json()
            assert [r['count'] for r in summaries]==[p['count'] for p in projects]
            raw=request('GET','/api/collection/export/objects.csv',params={'ids':','.join(ids)}).text
            rows=list(csv.DictReader(io.StringIO(raw.lstrip("\ufeff"))))
            assert len(rows)==sum(p['count'] for p in projects)
            assert all(r['ProjectID'] in ids and r['SourcePath'].startswith('batch/') for r in rows)
            report.update(status='passed',duplicate_import_reuse='passed',completed_images=len(projects),
                          object_rows=len(rows),all_objects_csv='passed',
                          cpu_analysis_seconds=[p['elapsed_seconds'] for p in projects])
        except BaseException as exc:
            report.update(status='failed',error=repr(exc));raise
        finally:
            stop();client.close();args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
