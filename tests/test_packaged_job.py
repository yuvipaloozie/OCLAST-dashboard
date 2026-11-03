"""Verify stress-harness teardown waits for native child DLL handles to close."""
import ctypes
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.name=='nt', 'Windows Job Objects are platform-specific')
class PackagedJobTests(unittest.TestCase):
    def test_job_close_waits_for_child_and_releases_native_dll(self):
        source=Path(__file__).resolve().parents[1]/'packaging/verify_cpu_package.py'
        spec=importlib.util.spec_from_file_location('cpu_package_harness',source)
        harness=importlib.util.module_from_spec(spec);spec.loader.exec_module(harness)
        k,_=harness.windows_api()
        with tempfile.TemporaryDirectory(prefix='oclast-job-teardown-') as directory:
            library=Path(directory)/'oclast-test-native.dll'
            shutil.copyfile(Path(os.environ['SystemRoot'])/'System32/version.dll',library)
            child_code="import ctypes,sys,time; dll=ctypes.WinDLL(sys.argv[1]); print('loaded',flush=True); time.sleep(60)"
            parent_code=("import subprocess,sys,time; input(); "
                         "child=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); "
                         "print('child:'+str(child.pid),flush=True); time.sleep(60)")
            process=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-c',parent_code,child_code,str(library)],
                                     stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            job=None; child_handle=None
            try:
                job=harness.ConstraintJob(k,process,4)
                process.stdin.write('\n');process.stdin.flush()
                lines=[process.stdout.readline().strip(),process.stdout.readline().strip()]
                self.assertIn('loaded',lines)
                child_pid=int(next(line.split(':')[1] for line in lines if line.startswith('child:')))
                child_handle=k.OpenProcess(0x100000,False,child_pid)
                self.assertTrue(child_handle)
                with self.assertRaises(PermissionError):
                    library.unlink()  # Prove the native DLL is actually held by the child.
                job.close()
                self.assertEqual(k.WaitForSingleObject(child_handle,0),0)
                process.wait(timeout=10)
                library.unlink()  # No retry/sleep: close must have synchronized teardown.
                self.assertFalse(library.exists())
            finally:
                if job: job.close()
                if child_handle: k.CloseHandle(child_handle)
                if process.poll() is None:
                    process.kill();process.wait(timeout=10)
                for stream in (process.stdin,process.stdout,process.stderr): stream.close()


if __name__=='__main__':
    unittest.main()
