"""Desktop startup regressions independent of the model or a running dev server."""
import json
import os
import socket
import tempfile
import subprocess
import sys
from pathlib import Path
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import Mock, patch

from oclast import launcher


class DesktopLauncherTests(unittest.TestCase):
    def test_explicit_busy_port_has_actionable_error(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            with patch.object(launcher, 'existing_instance', return_value=False):
                with self.assertRaisesRegex(OSError, 'occupied.*OCLAST_PORT'):
                    launcher.reserve_socket(occupied.getsockname()[1])

    def test_existing_application_is_reused_without_importing_projects(self):
        factory = Mock()
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher, 'data_directory', return_value=Path(directory)), patch.object(launcher, 'configure_logging'), patch.object(launcher, 'reserve_socket', return_value=(None, 12345)), patch.dict(os.environ, {'OCLAST_NO_BROWSER': '1'}):
            launcher.run(factory)
        factory.assert_not_called()

    def test_unrelated_service_is_not_treated_as_oclast(self):
        class Handler(BaseHTTPRequestHandler):
            payload = {'local_only': True, 'status': 'ok'}
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(self.payload).encode())
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            self.assertFalse(launcher.existing_instance(server.server_port))
            Handler.payload['application'] = 'OCLAST'
            self.assertTrue(launcher.existing_instance(server.server_port))
            self.assertFalse(launcher.existing_instance(server.server_port, Path('different-project-directory')))
            listener, port = launcher.reserve_socket(server.server_port)
            self.assertIsNone(listener)
            self.assertEqual(port, server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_default_port_collision_binds_an_os_assigned_port(self):
        listener = Mock()
        listener.bind.side_effect = [OSError('occupied'), None]
        listener.getsockname.return_value = ('127.0.0.1', 49152)
        with patch.object(launcher.socket, 'socket', return_value=listener), patch.object(launcher, 'existing_instance', return_value=False):
            actual, port = launcher.reserve_socket()
        self.assertIs(actual, listener)
        self.assertEqual(port, 49152)
        self.assertEqual(listener.bind.call_args_list[1].args, (('127.0.0.1', 0),))

    def test_browser_is_not_opened_after_failed_startup(self):
        server = Mock(started=False, should_exit=True)
        stopped = threading.Event()
        with patch.object(launcher.webbrowser, 'open') as browser:
            launcher.open_when_ready(server, 'http://127.0.0.1:12345', stopped)
        browser.assert_not_called()

    def test_browser_opens_only_after_startup(self):
        server = Mock(started=True, should_exit=False)
        with patch.object(launcher.webbrowser, 'open') as browser:
            launcher.open_when_ready(server, 'http://127.0.0.1:12345', threading.Event())
        browser.assert_called_once_with('http://127.0.0.1:12345')

    def test_directory_lock_blocks_second_writer_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            first = launcher.DirectoryLock(Path(directory))
            second = launcher.DirectoryLock(Path(directory))
            try:
                self.assertTrue(first.acquire())
                first.publish_port(12345)
                self.assertFalse(second.acquire())
                self.assertEqual(second.read_port(), 12345)
                first.close()
                first = None
                self.assertTrue(second.acquire())
            finally:
                if first is not None:
                    first.close()
                second.close()

    def test_second_launch_during_startup_does_not_import_projects(self):
        factory = Mock()
        with tempfile.TemporaryDirectory() as directory:
            first = launcher.DirectoryLock(Path(directory))
            self.assertTrue(first.acquire())
            try:
                with patch.object(launcher, 'data_directory', return_value=Path(directory)), patch.object(launcher, 'configure_logging'), patch.object(launcher, 'reserve_socket') as reserve:
                    launcher.run(factory)
                reserve.assert_not_called()
                factory.assert_not_called()
            finally:
                first.close()

    def test_terminated_process_releases_directory_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            code = ("from pathlib import Path; from oclast.launcher import DirectoryLock; "
                    "import sys,time; lock=DirectoryLock(Path(sys.argv[1])); "
                    "assert lock.acquire(); print('locked',flush=True); time.sleep(30)")
            # Launch the real interpreter, not the Windows venv redirector.
            # Popen's own process handle permits deterministic termination even
            # when taskkill process enumeration is denied by restricted tokens.
            child = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-c', code, directory],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'locked')
                contender = launcher.DirectoryLock(Path(directory))
                try:
                    self.assertFalse(contender.acquire())
                    child.terminate()
                    child.wait(timeout=10)
                    self.assertTrue(contender.acquire())
                finally:
                    contender.close()
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=10)
                child.stdout.close()
                child.stderr.close()

    def test_invalid_port_is_rejected(self):
        for port in (0, -1, 65536):
            with self.subTest(port=port), self.assertRaises(ValueError):
                launcher.reserve_socket(port)

    def test_background_thread_defaults_precede_native_import_and_keep_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ,{'OPENBLAS_NUM_THREADS':'3'},clear=True), \
                 patch.object(launcher,'data_directory',return_value=Path(directory)), \
                 patch.object(launcher,'configure_logging'), \
                 patch.object(launcher,'reserve_socket',return_value=(None,8000)), \
                 patch.object(launcher.webbrowser,'open'):
                launcher.run(Mock())
                self.assertEqual(os.environ['OPENBLAS_NUM_THREADS'],'3')
                for name in ('MKL_NUM_THREADS','OMP_NUM_THREADS','NUMEXPR_NUM_THREADS'):
                    self.assertEqual(os.environ[name],'1')


if __name__ == '__main__':
    unittest.main()
