import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from app.server import make_server
from app.server_lock import DataDirectoryLock
from app.store import Problem


class ServerLockTests(unittest.TestCase):
    def test_same_directory_different_ports_rejected_then_close_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            first = make_server(folder, 0)
            try:
                with self.assertRaisesRegex(Problem, '数据目录正被另一工作台使用'):
                    make_server(Path(folder) / '.', 0)
                with tempfile.TemporaryDirectory() as other:
                    independent = make_server(other, 0)
                    independent.server_close()
            finally:
                first.server_close()
            second = make_server(folder, 0)
            second.server_close()

    def test_failed_port_bind_releases_directory_lock(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = make_server(first_dir, 0)
            try:
                with self.assertRaises(OSError):
                    make_server(second_dir, first.server_port)
                second = make_server(second_dir, 0)
                second.server_close()
            finally:
                first.server_close()

    def test_os_releases_lock_after_process_exit_without_deleting_lock_file(self):
        with tempfile.TemporaryDirectory() as folder:
            code = 'import sys; from app.server_lock import DataDirectoryLock; lock=DataDirectoryLock(sys.argv[1]); print("locked",flush=True); sys.stdin.read()'
            child = subprocess.Popen([sys.executable, '-c', code, folder],
                                     cwd=Path(__file__).resolve().parents[1],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'locked')
                with self.assertRaises(Problem):
                    DataDirectoryLock(folder)
            finally:
                child.terminate(); child.wait(timeout=5)
                child.stdin.close(); child.stdout.close()
            self.assertTrue((Path(folder) / '.server.lock').is_file())
            lock = DataDirectoryLock(folder)
            lock.close()

    def test_close_keeps_lock_until_active_worker_finishes(self):
        with tempfile.TemporaryDirectory() as folder:
            server = make_server(folder, 0)
            gate = threading.Event()
            worker = threading.Thread(target=gate.wait, daemon=True)
            worker.start()
            server.worker_threads = [worker]
            server.worker_stop = threading.Event()
            try:
                server.server_close()
                self.assertTrue(server.worker_stop.is_set())
                with self.assertRaises(Problem):
                    DataDirectoryLock(folder)
            finally:
                gate.set(); worker.join(timeout=2)
            deadline = time.monotonic() + 2
            while True:
                try:
                    lock = DataDirectoryLock(folder)
                    lock.close(); break
                except Problem:
                    if time.monotonic() >= deadline:
                        self.fail('Worker completion did not release directory lock')
                    time.sleep(.01)
