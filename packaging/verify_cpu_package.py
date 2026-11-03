"""Stress the actual Windows EXE on CPU in an isolated, constrained process tree.

Run with the developer Python (numpy/OpenCV/httpx), not from inside the EXE:
  python packaging/verify_cpu_package.py --image path/to/full.tif --output report.json
Nothing is uploaded externally. Only this harness's temporary files are removed.
"""
import argparse
import csv
import ctypes as C
from ctypes import wintypes as W
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import zipfile

import cv2
import httpx
import numpy as np

SIZE = C.c_size_t


class BasicLimits(C.Structure):
    _fields_ = [('process_time', C.c_longlong), ('job_time', C.c_longlong),
                ('flags', W.DWORD), ('min_ws', SIZE), ('max_ws', SIZE),
                ('active', W.DWORD), ('affinity', SIZE), ('priority', W.DWORD), ('scheduling', W.DWORD)]


class IOCounters(C.Structure):
    _fields_ = [(x, C.c_ulonglong) for x in ['read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes']]


class ExtendedLimits(C.Structure):
    _fields_ = [('basic', BasicLimits), ('io', IOCounters), ('process_memory', SIZE),
                ('job_memory', SIZE), ('peak_process', SIZE), ('peak_job', SIZE)]


class MemoryCounters(C.Structure):
    _fields_ = [('cb', W.DWORD), ('faults', W.DWORD)] + [(x, SIZE) for x in [
        'peak_working', 'working', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private']]


class ProcessEntry(C.Structure):
    _fields_ = [('size', W.DWORD), ('usage', W.DWORD), ('pid', W.DWORD), ('heap', SIZE),
                ('module', W.DWORD), ('threads', W.DWORD), ('parent', W.DWORD),
                ('priority', W.LONG), ('flags', W.DWORD), ('exe', W.WCHAR * 260)]


def windows_api():
    k = C.WinDLL('kernel32', use_last_error=True)
    p = C.WinDLL('psapi', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([C.c_void_p, W.LPCWSTR], W.HANDLE),
        'SetInformationJobObject': ([W.HANDLE, C.c_int, C.c_void_p, W.DWORD], W.BOOL),
        'AssignProcessToJobObject': ([W.HANDLE, W.HANDLE], W.BOOL),
        'OpenProcess': ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
        'GetProcessAffinityMask': ([W.HANDLE, C.POINTER(SIZE), C.POINTER(SIZE)], W.BOOL),
        'CloseHandle': ([W.HANDLE], W.BOOL),
        'WaitForSingleObject': ([W.HANDLE, W.DWORD], W.DWORD),
        'CreateToolhelp32Snapshot': ([W.DWORD, W.DWORD], W.HANDLE),
        'Process32FirstW': ([W.HANDLE, C.POINTER(ProcessEntry)], W.BOOL),
        'Process32NextW': ([W.HANDLE, C.POINTER(ProcessEntry)], W.BOOL),
    }
    for name, (args, result) in signatures.items():
        method = getattr(k, name); method.argtypes = args; method.restype = result
    p.GetProcessMemoryInfo.argtypes = [W.HANDLE, C.POINTER(MemoryCounters), W.DWORD]
    p.GetProcessMemoryInfo.restype = W.BOOL
    return k, p


class ConstraintJob:
    def __init__(self, k, process, gib, logical_cpus=2):
        self.k = k
        self.process_id = process.pid
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        available, system = SIZE(), SIZE()
        if not k.GetProcessAffinityMask(W.HANDLE(int(process._handle)), C.byref(available), C.byref(system)):
            raise C.WinError(C.get_last_error())
        bits = [1 << bit for bit in range(C.sizeof(SIZE)*8) if available.value & (1 << bit)][:logical_cpus]
        self.affinity = sum(bits)
        limits = ExtendedLimits()
        limits.basic.flags = 0x10 | 0x100 | 0x2000  # affinity, per-process memory, kill tree on close
        limits.basic.affinity = self.affinity
        limits.process_memory = int(gib * 1024**3)
        if not k.SetInformationJobObject(self.handle, 9, C.byref(limits), C.sizeof(limits)):
            raise C.WinError(C.get_last_error())
        if not k.AssignProcessToJobObject(self.handle, W.HANDLE(int(process._handle))):
            raise C.WinError(C.get_last_error())
        self.report = {'enforced': True, 'logical_cpus': len(bits), 'affinity_mask': self.affinity,
                       'per_process_commit_limit_bytes': limits.process_memory,
                       'scope': 'JobObject inherited by frozen child process; not a whole-machine RAM simulation'}

    def close(self):
        if not self.handle:
            return
        # The one-file bootloader can exit before its native child has unloaded
        # extracted DLLs. Retain synchronization handles BEFORE killing the job;
        # waiting only for Popen's parent PID races TemporaryDirectory cleanup.
        handles = []
        try:
            for pid in descendants(self.k, self.process_id):
                handle = self.k.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
                if handle:
                    handles.append((pid, handle))
            self.k.CloseHandle(self.handle)  # KILL_ON_JOB_CLOSE terminates descendants.
            self.handle = None
            deadline = time.monotonic()+10
            pending = []
            for pid, handle in handles:
                remaining = max(0, int((deadline-time.monotonic())*1000))
                if self.k.WaitForSingleObject(handle, remaining) != 0:
                    pending.append(pid)
            if pending:
                raise TimeoutError(f'Frozen process teardown did not finish in 10 seconds: {pending}')
        finally:
            for _, handle in handles:
                self.k.CloseHandle(handle)



def descendants(k, root):
    snapshot = k.CreateToolhelp32Snapshot(2, 0)
    if snapshot == C.c_void_p(-1).value:
        return [root]
    edges = []
    try:
        item = ProcessEntry(); item.size = C.sizeof(item)
        more = k.Process32FirstW(snapshot, C.byref(item))
        while more:
            edges.append((item.pid, item.parent))
            more = k.Process32NextW(snapshot, C.byref(item))
    finally:
        k.CloseHandle(snapshot)
    found = {root}
    for _ in range(8):
        enlarged = found | {pid for pid, parent in edges if parent in found}
        if enlarged == found: break
        found = enlarged
    return sorted(found)


def memory_sample(k, p, root):
    working = private = peak_one = 0
    processes = []
    for pid in descendants(k, root):
        handle = k.OpenProcess(0x410, False, pid)
        if not handle: continue
        try:
            stats = MemoryCounters(); stats.cb = C.sizeof(stats)
            if p.GetProcessMemoryInfo(handle, C.byref(stats), C.sizeof(stats)):
                working += stats.working; private += stats.private
                peak_one = max(peak_one, stats.peak_pagefile)
                affinity, system = SIZE(), SIZE()
                k.GetProcessAffinityMask(handle, C.byref(affinity), C.byref(system))
                processes.append({'pid': pid, 'working_bytes': stats.working, 'private_bytes': stats.private,
                                  'affinity_mask': affinity.value})
        finally:
            k.CloseHandle(handle)
    return {'tree_working_bytes': working, 'tree_private_bytes': private,
            'largest_process_peak_commit_bytes': peak_one, 'processes': processes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, default=Path(__file__).resolve().parents[1]/'dist/OCLAST.exe')
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--memory-gib', type=float, default=4)
    parser.add_argument('--deadline', type=int, default=1800)
    parser.add_argument('--expected-count', type=int, default=858)
    parser.add_argument('--logical-cpus', type=int, default=2)
    parser.add_argument('--cpu-threads', type=int, default=2)
    args = parser.parse_args()
    if args.logical_cpus<1 or args.cpu_threads<1:
        parser.error('CPU counts must be positive')
    if os.name != 'nt': raise RuntimeError('This harness requires Windows Job Objects.')
    args.exe = args.exe.resolve(); args.image = args.image.resolve(); args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    k, p = windows_api()
    report = {'status': 'running', 'exe_sha256': hashlib.file_digest(args.exe.open('rb'), 'sha256').hexdigest(),
              'image_name': args.image.name, 'image_sha256': hashlib.file_digest(args.image.open('rb'), 'sha256').hexdigest(),
              'runs': [], 'limitations': ['CPU affinity and process commit limits emulate constraints, not a particular laptop CPU or total system RAM.']}
    process = job = log = None
    samples = []; sampling_stop = threading.Event(); sampler = None
    with tempfile.TemporaryDirectory(prefix='oclast-cpu-package-') as scratch:
        root = Path(scratch)
        for name in ['user', 'temp', 'cwd']: (root/name).mkdir()
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0)); port = available.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = os.environ.copy()
        for key in list(env):
            if key.startswith(('PYTHON', 'CONDA', 'OCLAST_')): env.pop(key)
        env.update(OCLAST_PORT=str(port), OCLAST_NO_BROWSER='1', OCLAST_DEVICE='cpu', OCLAST_CPU_THREADS=str(args.cpu_threads),
                   LOCALAPPDATA=str(root/'user'), TEMP=str(root/'temp'), TMP=str(root/'temp'),
                   PATH=os.environ['SystemRoot']+'\\System32;'+os.environ['SystemRoot'])
        client = httpx.Client(base_url=base, timeout=180, trust_env=False)
        def save():
            args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        def sample_loop():
            while not sampling_stop.wait(.5):
                active = process
                if active is not None:
                    samples.append(memory_sample(k, p, active.pid))
        def stop():
            nonlocal process, job, log
            if job: job.close(); job = None
            if process:
                if process.poll() is None:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                process.wait(timeout=30); process = None
            if log: log.close(); log = None
        def start(suffix):
            nonlocal process, job, log
            log = args.output.with_name(args.output.stem+f'-{suffix}.log').open('w', encoding='utf-8')
            process = subprocess.Popen([str(args.exe)], cwd=root/'cwd', env=env, stdout=log,
                                       stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                job = ConstraintJob(k, process, args.memory_gib,args.logical_cpus)
                report['constraints'] = job.report
            except Exception as exc:
                report['constraints'] = {'enforced': False, 'error': str(exc)}
                raise RuntimeError('Could not enforce laptop resource limits; refusing an unconstrained result.') from exc
            deadline = time.monotonic()+180
            while time.monotonic()<deadline:
                if process.poll() is not None: raise RuntimeError(f'EXE exited; inspect {log.name}')
                try:
                    health = client.get('/api/health', timeout=2).json()
                    if health.get('application') == 'OCLAST':
                        assert Path(health['project_directory']).resolve() == (root/'user/OCLAST/projects').resolve()
                        actual = memory_sample(k,p,process.pid)
                        assert actual['processes'], 'Could not inspect actual frozen processes'
                        assert all(item['affinity_mask']==job.affinity for item in actual['processes']), actual
                        report.setdefault('startup_memory',[]).append(actual)
                        return health
                except (httpx.HTTPError, ValueError): pass
                time.sleep(.5)
            raise TimeoutError('Packaged application startup timed out')
        def upload(path):
            with path.open('rb') as image:
                response = client.post('/api/projects', files={'file': (path.name, image, 'image/tiff')})
            response.raise_for_status(); return response.json()['id']
        def analyze(identifier, duplicate=False):
            response = client.post(f'/api/projects/{identifier}/analyze'); response.raise_for_status()
            started = time.monotonic(); latencies = []; progress = []; duplicate_done = False; previous = None
            while time.monotonic()-started < args.deadline:
                if process.poll() is not None: raise RuntimeError('Packaged service exited during inference')
                before = time.monotonic(); health = client.get('/api/health', timeout=30); health.raise_for_status()
                latencies.append(time.monotonic()-before)
                response = client.get(f'/api/projects/{identifier}', timeout=30); response.raise_for_status(); meta = response.json()
                state = (meta['stage'], meta.get('completed_tiles'))
                if state != previous:
                    item = {'seconds': round(time.monotonic()-started, 2), 'stage': state[0], 'tiles': state[1]}
                    progress.append(item); print(identifier[:8], item, flush=True); previous = state
                if duplicate and not duplicate_done and meta['status']=='running' and meta.get('completed_tiles', 0)>=1:
                    with args.output.with_name(args.output.stem+'-duplicate.log').open('w') as duplicate_log:
                        other = subprocess.Popen([str(args.exe)], cwd=root/'cwd', env=env, stdout=duplicate_log,
                                                 stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
                        try: assert other.wait(timeout=120)==0
                        finally:
                            if other.poll() is None:
                                subprocess.run(['taskkill','/PID',str(other.pid),'/T','/F'],capture_output=True)
                    live = client.get(f'/api/projects/{identifier}').json()
                    assert live['status'] in ('running', 'complete'), live
                    duplicate_done = True; report['duplicate_during_inference'] = 'passed'
                if meta['status']=='complete':
                    assert meta['compute']['device']=='cpu', meta['compute']
                    report['runs'].append({'id': identifier, 'elapsed_seconds': meta['elapsed_seconds'],
                        'wall_seconds': round(time.monotonic()-started,2), 'count': meta['count'], 'compute': meta['compute'],
                        'health_latency_max_seconds': max(latencies), 'health_latency_p95_seconds': float(np.quantile(latencies,.95)),
                        'progress': progress, 'settled_memory': memory_sample(k,p,process.pid)})
                    save(); return meta
                if meta['status'] in ('error','interrupted'): raise RuntimeError(meta)
                time.sleep(1)
            raise TimeoutError('CPU inference exceeded configured deadline')
        try:
            start('initial'); sampler = threading.Thread(target=sample_loop, daemon=True); sampler.start()
            assert client.get('/').status_code==200
            assert client.post('/api/projects', files={'file': ('bad.tif', b'not an image', 'image/tiff')}).status_code==400
            full_id = upload(args.image); full = analyze(full_id, duplicate=True)
            assert (full['width'],full['height'])==(8057,7479), full
            assert full['count']==args.expected_count, full
            cells = client.get(f'/api/projects/{full_id}/cells').json()
            ids = [cell['id'] for cell in cells]; assert len(ids)==len(set(ids))==full['count']
            original_csv = client.get(f'/api/projects/{full_id}/export/measurements.csv'); original_csv.raise_for_status()
            assert len(list(csv.DictReader(io.StringIO(original_csv.content.decode('utf-8-sig')))))==full['count']
            for layer in ['raw','labels','probability']:
                response = client.get(f'/api/projects/{full_id}/tiles/{layer}/4/0/0'); response.raise_for_status()
                assert cv2.imdecode(np.frombuffer(response.content,np.uint8),-1) is not None
            with client.stream('GET', f'/api/projects/{full_id}/export/analysis.zip') as response:
                response.raise_for_status()
                bundle = root/'bundle.zip'
                with bundle.open('wb') as target:
                    for chunk in response.iter_bytes(): target.write(chunk)
            with zipfile.ZipFile(bundle) as archive:
                assert {'project.json','measurements.csv','labels.npz','foreground_mask.png'} <= set(archive.namelist())
            report['full_image_tiles_csv_analysis_bundle'] = 'passed'
            image = cv2.imread(str(args.image)); crop = image[2800:3824,3000:4024].copy(); del image
            crop_path = root/'repeated-crop.png'; assert cv2.imwrite(str(crop_path),crop); del crop
            reference_labels = reference_probability = reference_cells = None
            for iteration in range(3):
                identifier = upload(crop_path); analyze(identifier)
                folder = root/'user/OCLAST/projects'/identifier
                with np.load(folder/'labels.npz',allow_pickle=False) as data: labels = data['labels']
                with np.load(folder/'probability.npz',allow_pickle=False) as data: probability = data['probability']
                current_cells = client.get(f'/api/projects/{identifier}/cells').json()
                if iteration==0:
                    reference_labels=labels; reference_probability=probability; reference_cells=current_cells
                else:
                    np.testing.assert_array_equal(labels,reference_labels)
                    np.testing.assert_allclose(probability,reference_probability,rtol=0,atol=1e-7)
                    assert current_cells==reference_cells
                report['runs'][-1]['labels_sha256'] = hashlib.sha256(labels.tobytes()).hexdigest()
                report['runs'][-1]['probability_sha256'] = hashlib.sha256(probability.tobytes()).hexdigest()
            report['repeated_crop_labels_measurements_probability'] = 'passed'
            crops = report['runs'][-3:]
            report['crop_private_memory_change_first_to_third_bytes'] = crops[-1]['settled_memory']['tree_private_bytes']-crops[0]['settled_memory']['tree_private_bytes']
            stop(); start('restart')
            reopened = client.get(f'/api/projects/{full_id}').json()
            assert reopened['status']=='complete' and reopened['count']==full['count']
            assert client.get(f'/api/projects/{full_id}/cells').json()==cells
            assert client.get(f'/api/projects/{full_id}/export/measurements.csv').content==original_csv.content
            report['restart_preserves_full_image_csv_and_cells'] = 'passed'
            report['status']='passed'
        except BaseException as exc:
            report['status']='failed'; report['error']=repr(exc)
            raise
        finally:
            sampling_stop.set()
            if sampler: sampler.join(timeout=5)
            report['memory'] = {key:max((sample[key] for sample in samples), default=0) for key in [
                'tree_working_bytes','tree_private_bytes','largest_process_peak_commit_bytes']}
            report['memory']['sample_count']=len(samples)
            source_log = root/'user/OCLAST/logs/desktop.log'
            if source_log.exists():
                args.output.with_name(args.output.stem+'-desktop.log').write_bytes(source_log.read_bytes())
            save(); stop(); client.close()
    print(json.dumps({key:value for key,value in report.items() if key!='runs'},indent=2),flush=True)


if __name__=='__main__':
    main()
