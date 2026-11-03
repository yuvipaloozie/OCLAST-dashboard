import unittest
import gc
import threading
import time
import weakref
from unittest.mock import patch
import numpy as np
from oclast.runtime import InferenceEngine,provider_order


class FakeSession:
    def __init__(self,provider,fail=False):
        self.provider=provider;self.fail=fail;self.calls=0
    def get_providers(self):return [self.provider]
    def run(self,outputs,inputs):
        self.calls+=1
        if self.fail:raise RuntimeError('Simulated GPU device/memory failure')
        return [inputs['input']*2]


class FallbackTests(unittest.TestCase):
    def test_gpu_priority_and_cpu_only_override(self):
        available=['DmlExecutionProvider','CUDAExecutionProvider','CPUExecutionProvider']
        self.assertEqual(provider_order(available),['CUDAExecutionProvider','DmlExecutionProvider','CPUExecutionProvider'])
        self.assertEqual(provider_order(available,'cpu'),['CPUExecutionProvider'])

    def test_cpu_only_machine_still_runs(self):
        def factory(path,sess_options,providers):
            self.assertEqual(providers,['CPUExecutionProvider'])
            return FakeSession('CPUExecutionProvider')
        engine=InferenceEngine('model.onnx',session_factory=factory,available=['CPUExecutionProvider'])
        np.testing.assert_array_equal(engine.run(None,{'input':np.array([3])})[0],[6])
        self.assertEqual(engine.info()['device'],'cpu')

    def test_gpu_initialization_failure_uses_cpu(self):
        def factory(path,sess_options,providers):
            if isinstance(providers[0],tuple):raise RuntimeError('No supported GPU adapter')
            return FakeSession('CPUExecutionProvider')
        engine=InferenceEngine('model.onnx',session_factory=factory,available=['DmlExecutionProvider','CPUExecutionProvider'])
        self.assertEqual(engine.provider,'CPUExecutionProvider')
        self.assertEqual(len(engine.info()['fallback_events']),1)

    def test_silent_gpu_initialization_fallback_is_detected(self):
        engine=InferenceEngine('model.onnx',available=['DmlExecutionProvider','CPUExecutionProvider'],session_factory=lambda *a,**k:FakeSession('CPUExecutionProvider'))
        self.assertEqual(engine.provider,'CPUExecutionProvider')
        self.assertIn('did not initialize',engine.info()['fallback_events'][0]['reason'])

    def test_gpu_runtime_failure_retries_same_tile_on_cpu(self):
        def factory(path,sess_options,providers):
            if isinstance(providers[0],tuple):
                self.assertFalse(sess_options.enable_mem_pattern)
                return FakeSession('DmlExecutionProvider',fail=True)
            return FakeSession('CPUExecutionProvider')
        engine=InferenceEngine('model.onnx',session_factory=factory,available=['DmlExecutionProvider','CPUExecutionProvider'])
        result=engine.run(None,{'input':np.array([7])})[0]
        np.testing.assert_array_equal(result,[14])
        self.assertEqual(engine.info()['providers_used'],['CPUExecutionProvider'])

    def test_mixed_execution_is_recorded_and_cpu_errors_propagate(self):
        gpu=FakeSession('DmlExecutionProvider')
        cpu=FakeSession('CPUExecutionProvider')
        engine=InferenceEngine('model.onnx',available=['DmlExecutionProvider','CPUExecutionProvider'],session_factory=lambda *a,**k:gpu if isinstance(k['providers'][0],tuple) else cpu)
        engine.run(None,{'input':np.array([1])})
        gpu.fail=True
        engine.run(None,{'input':np.array([2])})
        self.assertEqual(engine.info()['device'],'mixed')
        self.assertEqual(engine.info()['providers_used'],['DmlExecutionProvider','CPUExecutionProvider'])
        cpu.fail=True
        with self.assertRaises(RuntimeError):engine.run(None,{'input':np.array([3])})


class LaptopRuntimeTests(unittest.TestCase):
    def test_thread_budget_and_sleeping_workers(self):
        for logical, expected in ((None,1),(1,1),(2,1),(4,2),(16,4)):
            def factory(path,sess_options,providers):
                self.assertFalse(sess_options.enable_mem_pattern)
                self.assertEqual(sess_options.intra_op_num_threads,expected)
                self.assertEqual(sess_options.inter_op_num_threads,1)
                self.assertEqual(sess_options.get_session_config_entry('session.intra_op.allow_spinning'),'0')
                self.assertEqual(sess_options.get_session_config_entry('session.inter_op.allow_spinning'),'0')
                return FakeSession('CPUExecutionProvider')
            with patch('oclast.runtime.os.cpu_count',return_value=logical),patch.dict('os.environ',{},clear=True):
                engine=InferenceEngine('model',session_factory=factory,available=['CPUExecutionProvider'])
                self.assertEqual(engine.info()['cpu_threads'],expected)

    def test_explicit_thread_override_and_invalid_values(self):
        factory=lambda *a,**k:FakeSession('CPUExecutionProvider')
        with patch.dict('os.environ',{'OCLAST_CPU_THREADS':'2'}):
            engine=InferenceEngine('model',session_factory=factory,available=['CPUExecutionProvider'])
            self.assertEqual(engine.cpu_threads,2)
            engine=InferenceEngine('model',cpu_threads=1,session_factory=factory,available=['CPUExecutionProvider'])
            self.assertEqual(engine.cpu_threads,1)
        for threads in (0,-1,'invalid'):
            with self.assertRaises(ValueError):
                InferenceEngine('model',cpu_threads=threads,session_factory=factory,available=['CPUExecutionProvider'])

    def test_failed_gpu_is_released_before_cpu_allocation(self):
        gpu_ref=None
        def factory(path,sess_options,providers):
            nonlocal gpu_ref
            if isinstance(providers[0],tuple):
                gpu=FakeSession('DmlExecutionProvider',fail=True)
                gpu_ref=weakref.ref(gpu)
                return gpu
            gc.collect()
            self.assertIsNone(gpu_ref(),'GPU memory must be releasable before allocating CPU session')
            return FakeSession('CPUExecutionProvider')
        engine=InferenceEngine('model',session_factory=factory,available=['DmlExecutionProvider','CPUExecutionProvider'])
        np.testing.assert_array_equal(engine.run(None,{'input':np.array([5])})[0],[10])

    def test_concurrent_callers_serialize_and_preserve_results(self):
        active=0
        class SerialSession(FakeSession):
            def run(inner,outputs,inputs):
                nonlocal active
                active+=1
                self.assertEqual(active,1)
                time.sleep(.005)
                result=super().run(outputs,inputs)
                active-=1
                return result
        session=SerialSession('CPUExecutionProvider')
        engine=InferenceEngine('model',session_factory=lambda *a,**k:session,available=['CPUExecutionProvider'])
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda n:engine.run(None,{'input':np.array([n])})[0][0],range(24)))
        self.assertEqual(results,[n*2 for n in range(24)])
        self.assertEqual(session.calls,24)

    def test_health_status_does_not_wait_for_native_inference(self):
        started=threading.Event()
        release=threading.Event()
        class BlockingSession(FakeSession):
            def run(inner,outputs,inputs):
                started.set()
                release.wait(2)
                return super().run(outputs,inputs)
        engine=InferenceEngine('model',session_factory=lambda *a,**k:BlockingSession('CPUExecutionProvider'),available=['CPUExecutionProvider'])
        worker=threading.Thread(target=engine.run,args=(None,{'input':np.array([1])}))
        worker.start()
        try:
            self.assertTrue(started.wait(1))
            start=time.monotonic()
            self.assertEqual(engine.info()['active_provider'],'CPUExecutionProvider')
            self.assertLess(time.monotonic()-start,.25)
        finally:
            release.set()
            worker.join(2)

    def test_memory_pattern_policy_preserves_cuda_and_disables_cpu_and_directml(self):
        for provider, preference, expected in (
                ('CPUExecutionProvider','cpu',False),
                ('DmlExecutionProvider','directml',False),
                ('CUDAExecutionProvider','cuda',True)):
            def factory(path,sess_options,providers):
                self.assertEqual(sess_options.enable_mem_pattern,expected)
                return FakeSession(provider)
            with patch('oclast.runtime.ort.preload_dlls',create=True):
                engine=InferenceEngine('model',preference=preference,session_factory=factory,available=[provider,'CPUExecutionProvider'])
            self.assertEqual(engine.provider,provider)
