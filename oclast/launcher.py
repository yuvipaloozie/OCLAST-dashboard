"""Desktop startup without importing the image stack before reserving a port."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import sys
import threading
import urllib.error
import urllib.request
import webbrowser


HOST = '127.0.0.1'


def existing_instance(port, directory=None):
    """Ignore proxy settings and never open an unrelated service's page."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://{HOST}:{port}/api/health', timeout=.75) as response:
            health = json.loads(response.read(65536))
        if not isinstance(health, dict) or health.get('application') != 'OCLAST' or health.get('local_only') is not True:
            return False
        return directory is None or Path(health.get('project_directory', '')).resolve() == directory.resolve()
    except (OSError, ValueError, urllib.error.URLError):
        return False


def reserve_socket(port=None, directory=None):
    """Reserve the actual socket to avoid a free-port check/bind race."""
    explicit = port is not None
    preferred = int(port) if explicit else 8000
    if not 1 <= preferred <= 65535:
        raise ValueError('OCLAST_PORT must be between 1 and 65535')
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        listener.bind((HOST, preferred))
    except OSError as exc:
        if existing_instance(preferred, directory):
            listener.close()
            return None, preferred
        if explicit:
            listener.close()
            raise OSError(f'Port {preferred} is occupied. Close the other app or set OCLAST_PORT to another port.') from exc
        try:
            listener.bind((HOST, 0))
        except BaseException:
            listener.close()
            raise
    listener.listen(128)
    return listener, listener.getsockname()[1]


def data_directory():
    if os.environ.get('OCLAST_DATA_DIR'):
        return Path(os.environ['OCLAST_DATA_DIR'])
    if getattr(sys, 'frozen', False):
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'OCLAST' / 'projects'
    return Path(__file__).resolve().parent.parent / 'data' / 'projects'


class DirectoryLock:
    """One desktop writer per project directory, including during slow startup.

    OS locks are released on process termination; stale lock files are harmless.
    The URL starts after the locked byte so another process can read it on Windows.
    """
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self.file = (directory / '.desktop.lock').open('a+b')
        self.locked = False
        if self.file.seek(0, 2) == 0:
            self.file.write(b' ')
            self.file.flush()

    def acquire(self):
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        self.locked = True
        return True

    def publish_port(self, port):
        self.file.seek(1)
        self.file.truncate()
        self.file.write(str(port).encode('ascii'))
        self.file.flush()

    def read_port(self):
        try:
            self.file.seek(1)
            return int(self.file.read(10))
        except ValueError:
            return None

    def close(self):
        if self.locked:
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()


def configure_logging():
    root = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'OCLAST' / 'logs'
    root.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(root / 'desktop.log', maxBytes=1_000_000, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    if sys.stderr is not None:
        logging.getLogger().addHandler(logging.StreamHandler())
    return root / 'desktop.log'


def open_when_ready(server, url, stopped):
    """Open only after Uvicorn has completed application startup."""
    while not stopped.wait(.1):
        if server.started:
            webbrowser.open(url)
            return
        if server.should_exit:
            return


def run(app_factory):
    """Start one local desktop service; callers supply a lazy app factory."""
    import multiprocessing
    multiprocessing.freeze_support()
    # Set before NumPy/SciPy/OpenCV load: their background pools otherwise
    # reserve hundreds of MB on Windows even though this app runs one image job.
    # ONNX has its own independently bounded inference thread pool.
    for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ.setdefault(name,'1')
    listener = None
    directory_lock = None
    stopped = threading.Event()
    log_path = configure_logging()
    log = logging.getLogger('oclast.desktop')
    try:
        directory_lock = DirectoryLock(data_directory())
        if not directory_lock.acquire():
            port = directory_lock.read_port()
            log.info('This project directory is already open in OCLAST. Reuse its existing window.')
            if port and existing_instance(port, data_directory()) and not os.environ.get('OCLAST_NO_BROWSER'):
                webbrowser.open(f'http://{HOST}:{port}')
            return
        listener, port = reserve_socket(os.environ.get('OCLAST_PORT'), data_directory())
        url = f'http://{HOST}:{port}'
        if listener is None:
            log.info('OCLAST is already running at %s', url)
            if not os.environ.get('OCLAST_NO_BROWSER'):
                webbrowser.open(url)
            return
        # In the frozen entry point this is the first import of api/Projects:
        # opening the EXE twice must not mark the live process's jobs interrupted.
        directory_lock.publish_port(port)
        app = app_factory()
        import uvicorn
        server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_config=None))
        log.info('OCLAST ready to start at %s; diagnostic log: %s', url, log_path)
        print(f'OCLAST â€” {url}\nKeep this window open while using OCLAST. Close it to stop the app.', flush=True)
        if not os.environ.get('OCLAST_NO_BROWSER'):
            threading.Thread(target=open_when_ready, args=(server, url, stopped), daemon=True).start()
        server.run(sockets=[listener])
    except Exception:
        log.exception('OCLAST could not start. Diagnostic log: %s', log_path)
        raise
    finally:
        stopped.set()
        if listener is not None:
            listener.close()
        if directory_lock is not None:
            directory_lock.close()

