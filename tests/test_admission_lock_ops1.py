import errno
import fcntl
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from admission_lock_ops1 import AdmissionFlock, install


class AdmissionLockTests(unittest.TestCase):
    def backend(self, effects):
        return types.SimpleNamespace(flock=Mock(side_effect=effects),
                                     LOCK_EX=fcntl.LOCK_EX, LOCK_NB=fcntl.LOCK_NB, LOCK_UN=fcntl.LOCK_UN)

    def test_only_acquisition_eagain_is_retried(self):
        backend = self.backend([BlockingIOError(errno.EAGAIN, 'busy'), None])
        sleeps = []
        events = []
        AdmissionFlock(backend, sleep=sleeps.append, on_wait=events.append).flock(10, fcntl.LOCK_EX)
        self.assertEqual(backend.flock.call_count, 2)
        self.assertEqual(len(sleeps), 1)
        self.assertFalse(events[0]['paid_api_retry'])

    def test_nonblocking_controller_lock_is_not_retried(self):
        backend = self.backend([BlockingIOError(errno.EAGAIN, 'busy')])
        with self.assertRaises(BlockingIOError):
            AdmissionFlock(backend).flock(10, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(backend.flock.call_count, 1)

    def test_non_eagain_io_error_is_not_retried(self):
        backend = self.backend([OSError(errno.EIO, 'IO')])
        with self.assertRaises(OSError):
            AdmissionFlock(backend).flock(10, fcntl.LOCK_EX)
        self.assertEqual(backend.flock.call_count, 1)

    def test_timeout_preserves_error(self):
        backend = self.backend([BlockingIOError(errno.EAGAIN, 'busy')])
        with self.assertRaises(BlockingIOError):
            AdmissionFlock(backend, timeout=0).flock(10, fcntl.LOCK_EX)
        self.assertEqual(backend.flock.call_count, 1)

    def test_patch_is_module_local_and_single_install(self):
        original = fcntl.flock
        module = types.SimpleNamespace(fcntl=fcntl)
        record = install(module)
        self.assertIs(fcntl.flock, original)
        self.assertEqual(record['retry_errno'], 'EAGAIN')
        with self.assertRaises(ValueError):
            install(module)


if __name__ == '__main__':
    unittest.main()
