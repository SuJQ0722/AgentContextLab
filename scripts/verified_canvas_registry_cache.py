"""Reuse verified immutable canvas hashes while all filesystem identities match.

This is a process-local optimization, not an alternative integrity validator.
The existing full validator still runs initially and after any file change.
"""
import os
from pathlib import Path
import threading
import time


class VerifiedCanvasRegistryCache:
    def __init__(self, directory, validator, observer=None):
        self.directory = Path(directory).resolve()
        self.validator = validator
        self.observer = observer
        self._signature = None
        self._hashes = None
        self._lock = threading.Lock()

    def _snapshot(self):
        if not self.directory.exists():
            return ()
        entries = []
        def visit(directory):
            with os.scandir(directory) as listing:
                for entry in listing:
                    # Do not hide externally changing targets behind symlink metadata.
                    if entry.is_symlink():
                        raise ValueError('Canvas registry cache forbids symlinks')
                    s = entry.stat(follow_symlinks=False)
                    entries.append((str(Path(entry.path).relative_to(self.directory)),
                                    s.st_dev, s.st_ino, s.st_mode, s.st_size,
                                    s.st_mtime_ns, s.st_ctime_ns))
                    if entry.is_dir(follow_symlinks=False):
                        visit(entry.path)
        visit(self.directory)
        return tuple(sorted(entries))

    def __call__(self):
        start = time.monotonic()
        with self._lock:
            before = self._snapshot()
            # Some mounted filesystems expose only second-resolution ctime even
            # through st_ctime_ns. Never reuse a signature in its update window:
            # a same-size write + restored mtime may otherwise go undetected.
            stable = all(max(row[-2:]) < time.time_ns() - 2_000_000_000
                         for row in before)
            hit = self._hashes is not None and before == self._signature and stable
            if not hit:
                # Invalidate first: an unsuccessful revalidation cannot resurrect
                # a previous cached result, even if the caller retries.
                self._hashes = self._signature = None
                hashes = frozenset(self.validator(self.directory))
                after = self._snapshot()
                if before != after:
                    raise ValueError('Canvas artifacts changed during validation')
                self._hashes, self._signature = hashes, after
            if self.observer:
                self.observer({'event': 'canvas_registry_validation',
                               'cache_hit': hit, 'artifact_entries': len(before),
                               'verified_hashes': len(self._hashes),
                               'client_local_seconds': time.monotonic() - start,
                               'provider_api_seconds': None})
            return set(self._hashes)
