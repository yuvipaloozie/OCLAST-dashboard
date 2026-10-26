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
    def __init__(self,path,preference=None,device_id=None,session_factory=None,available=None):
        self.path=str(path)
        self.preference=preference or os.environ.get('OCLAST_DEVICE','auto').lower()
        self.device_id=int(device_id if device_id is not None else os.environ.get('OCLAST_GPU_DEVICE_ID','0'))
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
        while self.pending:
            candidate=self.pending.pop(0)
            try:
                if candidate=='CUDAExecutionProvider' and hasattr(ort,'preload_dlls'):
                    ort.preload_dlls()
                options=ort.SessionOptions()
                options.intra_op_num_threads=4
                options.inter_op_num_threads=1
                options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
                if candidate=='DmlExecutionProvider':
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
                    self._activate_next()

    def get_inputs(self):
        return self.session.get_inputs()

    def get_outputs(self):
        return self.session.get_outputs()

    def get_providers(self):
        return self.session.get_providers()

    def info(self):
        with self.lock:
            mixed='CPUExecutionProvider' in self.used and any(p in GPU_PROVIDERS for p in self.used)
            device='mixed' if mixed else ('cpu' if self.provider=='CPUExecutionProvider' else 'gpu')
            return dict(status='active' if self.used else 'ready',device=device,
                        active_provider=self.provider,providers_used=self.used[:],
                        available_providers=self.available[:],gpu_device_id=self.device_id if device!='cpu' else None,
                        preference=self.preference,fallback_events=self.failures[:])
