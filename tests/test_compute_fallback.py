import unittest
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
