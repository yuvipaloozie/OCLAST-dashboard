"""Verify the frozen EXE survives interruption and reports CPU allocation failures.

Uses isolated project directories and Windows Job Objects. No server mocks and no
production data are changed. Failed native processes are reported as failures.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time

import cv2
import httpx

from verify_cpu_package import ConstraintJob, memory_sample, windows_api


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, default=Path(__file__).resolve().parents[1]/'dist/OCLAST.exe')
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--low-memory-gib', type=float, default=1)
    args = parser.parse_args()
    if os.name != 'nt': raise RuntimeError('Windows is required')
    args.exe=args.exe.resolve(); args.image=args.image.resolve(); args.output=args.output.resolve()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    k,p=windows_api()
    report={'status':'running','exe_sha256':hashlib.file_digest(args.exe.open('rb'),'sha256').hexdigest(),
            'scenarios':[], 'limits':{'cpu_threads':2,'logical_cpus':2,'normal_commit_gib':4,
                                     'low_memory_commit_gib':args.low_memory_gib}}
    process=job=log=client=None
    with tempfile.TemporaryDirectory(prefix='oclast-failure-recovery-') as directory:
        root=Path(directory)
        source=cv2.imread(str(args.image))
        if source is None: raise ValueError('Could not read sample image')
        crop=source[2800:3824,3000:4024].copy(); del source
        if crop.shape!=(1024,1024,3): raise ValueError('Expected the full high-resolution sample TIFF')
        crop_path=root/'real-crop.png'; assert cv2.imwrite(str(crop_path),crop); del crop
        (root/'cwd').mkdir(); (root/'temp').mkdir()
        active_user=active_suffix=None
        def save():
            args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
        def stop():
            nonlocal process,job,log,client
            if job: job.close(); job=None  # KILL_ON_JOB_CLOSE releases the whole frozen process tree.
            if process:
                try: process.wait(timeout=30)
                finally:
                    if process.poll() is None: process.kill(); process.wait(timeout=10)
                process=None
            if log: log.close(); log=None
            if client: client.close(); client=None
            if active_user:
                desktop=root/active_user/'OCLAST/logs/desktop.log'
                if desktop.exists():
                    args.output.with_name(args.output.stem+'-'+active_suffix+'-desktop.log').write_bytes(desktop.read_bytes())
        def start(user,suffix,limit):
            nonlocal process,job,log,client,active_user,active_suffix
            active_user=user; active_suffix=suffix
            (root/user).mkdir(exist_ok=True)
            with socket.socket() as available:
                available.bind(('127.0.0.1',0)); port=available.getsockname()[1]
            env=os.environ.copy()
            for name in list(env):
                if name.startswith(('OCLAST_','PYTHON','CONDA')): env.pop(name)
            env.update(OCLAST_PORT=str(port),OCLAST_NO_BROWSER='1',OCLAST_DEVICE='cpu',OCLAST_CPU_THREADS='2',
                       LOCALAPPDATA=str(root/user),TEMP=str(root/'temp'),TMP=str(root/'temp'),
                       PATH=os.environ['SystemRoot']+'\\System32;'+os.environ['SystemRoot'])
            log=args.output.with_name(args.output.stem+'-'+suffix+'.log').open('w',encoding='utf-8')
            process=subprocess.Popen([str(args.exe)],cwd=root/'cwd',env=env,stdout=log,stderr=subprocess.STDOUT,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            job=ConstraintJob(k,process,limit)
            client=httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=30,trust_env=False)
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                if process.poll() is not None: raise RuntimeError(f'Native process exited during {suffix} startup; see log')
                try:
                    health=client.get('/api/health',timeout=2)
                    if health.status_code==200 and health.json().get('application')=='OCLAST':
                        expected=(root/user/'OCLAST/projects').resolve()
                        assert Path(health.json()['project_directory']).resolve()==expected
                        actual=memory_sample(k,p,process.pid)
                        assert all(item['affinity_mask']==job.affinity for item in actual['processes']),actual
                        return
                except (httpx.HTTPError,ValueError): pass
                time.sleep(.5)
            raise TimeoutError('Frozen startup timed out')
        def upload():
            with crop_path.open('rb') as source:
                response=client.post('/api/projects',files={'file':('real-crop.png',source,'image/png')})
            response.raise_for_status(); return response.json()['id']
        def begin(identifier):
            response=client.post(f'/api/projects/{identifier}/analyze');response.raise_for_status()
        def wait(identifier,until='terminal'):
            began=time.monotonic(); deadline=began+600; peak=0; last=None
            while time.monotonic()<deadline:
                if process.poll() is not None: raise RuntimeError('Native app crashed instead of reporting a recoverable error')
                health=client.get('/api/health',timeout=10);health.raise_for_status()
                response=client.get(f'/api/projects/{identifier}',timeout=10);response.raise_for_status();meta=response.json()
                peak=max(peak,memory_sample(k,p,process.pid)['largest_process_peak_commit_bytes'])
                state=(meta['status'],meta.get('completed_tiles'),meta['stage'])
                if state!=last: print(active_suffix,state,flush=True);last=state
                if until=='first-tile' and meta['status']=='running' and meta.get('completed_tiles',0)>=1:
                    return meta,peak
                if meta['status'] in ('complete','error','interrupted'):
                    if until!='terminal': raise RuntimeError(f'Analysis completed before intended interruption: {meta}')
                    return meta,peak
                time.sleep(.25)
            raise TimeoutError('Crop analysis timed out')
        try:
            start('interrupted-user','before-kill',4)
            identifier=upload();begin(identifier);before,peak=wait(identifier,'first-tile')
            stop()  # Abrupt whole-tree termination: no graceful application shutdown.
            start('interrupted-user','restart-after-kill',4)
            interrupted=client.get(f'/api/projects/{identifier}').json()
            assert interrupted['status']=='interrupted',interrupted
            begin(identifier);normal,peak=wait(identifier)
            assert normal['status']=='complete',normal
            normal_cells=client.get(f'/api/projects/{identifier}/cells').json()
            normal_csv=client.get(f'/api/projects/{identifier}/export/measurements.csv');normal_csv.raise_for_status()
            assert len(normal_cells)==normal['count']>0
            report['scenarios'].append({'scenario':'forced_termination_during_cpu_inference','result':'passed',
                'completed_tiles_before_kill':before['completed_tiles'],'reopened_status':interrupted['status'],
                'rerun_status':normal['status'],'count':normal['count'],'elapsed_seconds':normal['elapsed_seconds'],
                'peak_process_commit_bytes':peak})
            save();stop()
            start('low-memory-user','one-gib-limit',args.low_memory_gib)
            low_id=upload();begin(low_id);failed,peak=wait(low_id)
            assert failed['status']=='error', 'The selected commit limit did not induce failure; this is not a demonstrated low-memory recovery pass: '+str(failed)
            assert failed.get('error'),failed
            assert client.get('/api/health').status_code==200
            assert client.get('/api/projects').status_code==200
            assert client.get(f'/api/projects/{low_id}/export/measurements.csv').status_code==409
            report['scenarios'].append({'scenario':'cpu_allocation_failure','result':'passed',
                'commit_limit_bytes':int(args.low_memory_gib*1024**3),'project_error':failed['error'],
                'api_alive_after_error':True,'peak_process_commit_bytes':peak})
            save();stop()
            start('low-memory-user','retry-with-memory',4)
            retry=client.get(f'/api/projects/{low_id}').json();assert retry['status']=='error',retry
            begin(low_id);recovered,peak=wait(low_id)
            assert recovered['status']=='complete' and recovered['count']==normal['count'],recovered
            assert client.get(f'/api/projects/{low_id}/cells').json()==normal_cells
            assert client.get(f'/api/projects/{low_id}/export/measurements.csv').content==normal_csv.content
            report['scenarios'].append({'scenario':'retry_after_allocation_failure','result':'passed',
                'count':recovered['count'],'exact_cells_and_csv_preserved':True,'elapsed_seconds':recovered['elapsed_seconds']})
            report['status']='passed'
        except BaseException as exc:
            report['status']='failed';report['error']=repr(exc);raise
        finally:
            stop();save()
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    main()
