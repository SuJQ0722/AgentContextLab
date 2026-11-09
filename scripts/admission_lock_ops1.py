"""Bounded retry of acquisition-only EAGAIN on the shared admission lock.

Never retries spawning a process or any ledger read/write. The replacement is
local to the importing coordinator's admission module, not the stdlib module.
Nonblocking exclusive controller locks retain their immediate-busy semantics.
"""
import errno
import fcntl
import hashlib
from pathlib import Path
import time


class AdmissionFlock:
    def __init__(self, original=fcntl, *, timeout=30., sleep=time.sleep,
                 clock=time.monotonic, on_wait=None):
        self.original = original
        self.timeout = timeout
        self.sleep = sleep
        self.clock = clock
        self.on_wait = on_wait

    def __getattr__(self, name):
        return getattr(self.original, name)

    def flock(self, fd, operation):
        if operation & self.original.LOCK_NB or operation & self.original.LOCK_UN:
            return self.original.flock(fd, operation)
        deadline = self.clock() + self.timeout
        attempt = 0
        while True:
            try:
                return self.original.flock(fd, operation)
            except OSError as exc:
                if exc.errno != errno.EAGAIN or self.clock() >= deadline:
                    raise
                attempt += 1
                delay = min(.05 * (2 ** min(attempt - 1, 4)), max(0., deadline - self.clock()))
                if self.on_wait:
                    self.on_wait({'event': 'admission_flock_wait', 'errno': errno.EAGAIN,
                                  'attempt': attempt, 'delay_seconds': delay,
                                  'phase': 'lock_acquisition_before_spawn', 'paid_api_retry': False})
                self.sleep(delay)


def install(admission_module, *, timeout=30., on_wait=None):
    """Call once in an explicitly versioned operational coordinator."""
    if isinstance(admission_module.fcntl, AdmissionFlock):
        raise ValueError('Admission lock maintenance was already installed')
    original = admission_module.fcntl
    admission_module.fcntl = AdmissionFlock(original, timeout=timeout, on_wait=on_wait)
    path = Path(__file__).resolve()
    return {'version': 'admission-flock-eagain-ops1', 'source_path': str(path),
            'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'retry_errno': 'EAGAIN', 'timeout_seconds': timeout,
            'scope': 'Acquiring blocking advisory lock only; no spawn, ledger IO or model retry'}
