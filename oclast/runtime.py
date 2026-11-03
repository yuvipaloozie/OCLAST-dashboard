"""GPU-first ONNX inference with verified initialization and CPU retry."""
import logging
import os
import threading
import onnxruntime as ort

log=logging.getLogger(__name__)
GPU_PROVIDERS=('CUDAExecutionProvider','DmlExecutionProvider')


def provider_order(available, preference='auto'):
    if preference not in ('auto','cpu','cuda','directml'):
        raise ValueError('OCLAST_DEVICE must be auto, cpu, cuda, or directml')
    requested={'auto':GPU_PROVIDERS,'cuda':GPU_PROVIDERS[:1],
               'directml':GPU_PROVIDERS[1:],'cpu':()}[preference]
    return [p for p in requested if p in available]+['CPUExecutionProvider']


class InferenceEngine:
    def __init__(self,path,preference=None,device_id=None,session_factory=None,available=None,cpu_threads=None):
        self.path=str(path)
        self.preference=preference or os.environ.get('OCLAST_DEVICE','auto').lower()
        self.device_id=int(device_id if device_id is not None else os.environ.get('OCLAST_GPU_DEVICE_ID','0'))
        # Leave CPU capacity for image decoding, the browser, and the OS. Fixed
        # 512px tiles do not benefit from unbounded laptop-wide thread pools.
        logical_cpus=os.cpu_count() or 1
        requested_threads=cpu_threads if cpu_threads is not None else os.environ.get('OCLAST_CPU_THREADS')
        self.cpu_threads=int(requested_threads) if requested_threads is not None else min(4,max(1,logical_cpus//2))
        if self.cpu_threads < 1:
            raise ValueError('OCLAST_CPU_THREADS must be a positive integer')
        self.available=list(available if available is not None else ort.get_available_providers())
        self.pending=provider_order(self.available,self.preference)
        self.factory=session_factory or ort.InferenceSession
        self.failures=[]
        self.used=[]
        self.lock=threading.RLock()
        self.session=None
        self.provider=None
        self._activate_next()

    def _activate_next(self):
        # Drop failed GPU allocations before constructing a CPU replacement.
        # Keeping both sessions alive can turn a recoverable GPU error into OOM.
        self.session=None
        self.provider=None
        session=None
        while self.pending:
            session=None
            candidate=self.pending.pop(0)
            try:
                if candidate=='CUDAExecutionProvider' and hasattr(ort,'preload_dlls'):
                    ort.preload_dlls()
                options=ort.SessionOptions()
                options.intra_op_num_threads=self.cpu_threads
                options.inter_op_num_threads=1
                options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
                # Sleeping workers keep the laptop responsive between tiles/jobs.
                options.add_session_config_entry('session.intra_op.allow_spinning','0')
                options.add_session_config_entry('session.inter_op.allow_spinning','0')
                if candidate in ('CPUExecutionProvider','DmlExecutionProvider'):
                    # DirectML requires this. On CPU, disabling the pattern's
                    # additional cached reservation plus bounded native pools
                    # halved measured tile-process commit at a modest time cost.
                    # This is an allocation policy, not a model/precision change.
                    options.enable_mem_pattern=False
                providers=['CPUExecutionProvider'] if candidate=='CPUExecutionProvider' else [(candidate,{'device_id':self.device_id}),'CPUExecutionProvider']
                session=self.factory(self.path,sess_options=options,providers=providers)
                if candidate not in session.get_providers():
                    raise RuntimeError(f'{candidate} did not initialize; runtime reported {session.get_providers()}')
                self.session=session
                self.provider=candidate
                return
            except Exception as exc:
                self.failures.append(dict(provider=candidate,reason=str(exc)[:2000]))
                log.warning('OCLAST could not initialize %s; trying next backend: %s',candidate,exc)
        raise RuntimeError('Unable to initialize ONNX inference on GPU or CPU: '+self.failures[-1]['reason'])

    def run(self,output_names,inputs):
        # DirectML sessions must not be executed concurrently. The same guard
        # also keeps provider replacement safe if a GPU fails during inference.
        with self.lock:
            while True:
                try:
                    output=self.session.run(output_names,inputs)
                    if self.provider not in self.used:self.used.append(self.provider)
                    return output
                except Exception as exc:
                    if self.provider=='CPUExecutionProvider':
                        raise
                    self.failures.append(dict(provider=self.provider,reason=str(exc)[:2000]))
                    log.warning('OCLAST %s inference failed; retrying this tile with the next backend: %s',self.provider,exc)
                    # The failed run traceback can itself retain the old session.
                    exc.__traceback__=None
                    self._activate_next()

    def get_inputs(self):
        return self.session.get_inputs()

    def get_outputs(self):
        return self.session.get_outputs()

    def get_providers(self):
        return self.session.get_providers()

    def info(self):
        # Health polling must not wait for native inference to finish. Capture
        # small metadata snapshots, rather than taking the execution lock.
        provider=self.provider
        used=self.used[:]
        failures=self.failures[:]
        mixed='CPUExecutionProvider' in used and any(p in GPU_PROVIDERS for p in used)
        device='mixed' if mixed else ('cpu' if provider=='CPUExecutionProvider' else 'gpu')
        return dict(status='switching' if provider is None else ('active' if used else 'ready'),device=device,
                    active_provider=provider,providers_used=used,
                    available_providers=self.available[:],gpu_device_id=self.device_id if device!='cpu' else None,
                    preference=self.preference,cpu_threads=self.cpu_threads,fallback_events=failures)
