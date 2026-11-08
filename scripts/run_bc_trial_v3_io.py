#!/usr/bin/env python3
"""Explicit heartbeat-I/O maintenance entrypoint over the frozen v3 trial."""
import errno
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import uuid

import run_bc_trial_v3 as frozen_trial
from lab import ROOT

MAINTENANCE_VERSION = 'bc-v3-heartbeat-io-v1'
RETRY_ERRNOS = frozenset(getattr(errno, name) for name in
    ('EIO', 'ESTALE', 'EINTR', 'EAGAIN', 'ETIMEDOUT', 'EBUSY') if hasattr(errno, name))
RETRY_DELAYS = (0.25, 0.75, 1.5)


def maintenance_record():
    files = ['scripts/run_bc_trial_v3_io.py', 'scripts/run_bc_campaign_v3_io.py']
    return {'maintenance_version': MAINTENANCE_VERSION,
            'implementation_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
            'frozen_validation': 'Original validate_sources/validate_spec unchanged',
            'scope': 'Only heartbeat persistence retries; original model, tools, context, budget, claims, terminal writes and pending-only resume unchanged',
            'retry_errno_names': sorted(errno.errorcode[n] for n in RETRY_ERRNOS),
            'max_heartbeat_write_attempts': len(RETRY_DELAYS) + 1}


class HeartbeatAtomic:
    def __init__(self, strict_atomic, local_dir=None, sleep=time.sleep):
        self.strict_atomic = strict_atomic
        self.local_dir = Path(local_dir) if local_dir else Path('/tmp/agentcontextlab-bc-v3-io')
        self.sleep = sleep
        self.sequence = 0

    def diagnostic(self, path, record):
        self.sequence += 1
        record = {'maintenance_version': MAINTENANCE_VERSION, 'timestamp': frozen_trial.now(),
                  'hostname': socket.gethostname(), 'pid': os.getpid(), 'sequence': self.sequence,
                  'attempt_path': str(path.parent), **record}
        encoded = json.dumps(record, ensure_ascii=False) + '\n'
        # The local append is independent of AFS. Never print exception messages,
        # command lines, or environment. AFS sidecar failure does not hide I/O failure.
        try:
            self.local_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            local = self.local_dir / f'{os.getpid()}-heartbeat.jsonl'
            fd = os.open(local, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, 'a') as stream:
                stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
        except OSError:
            print(encoded.rstrip(), file=sys.stderr, flush=True)
        try:
            with (path.parent / 'heartbeat-io.jsonl').open('a') as stream:
                stream.write(encoded)
        except OSError:
            pass

    def __call__(self, path, value):
        path = Path(path)
        if path.name != 'heartbeat.json':
            return self.strict_atomic(path, value)
        failure_seen = False
        for index in range(len(RETRY_DELAYS) + 1):
            stage = 'mkdir'; stream = None; temporary = None
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
                stage = 'open'; stream = temporary.open('x')
                stage = 'write'; json.dump(value, stream, ensure_ascii=False, indent=2)
                stage = 'flush'; stream.flush()
                stage = 'fsync'; os.fsync(stream.fileno())
                stage = 'close'; stream.close(); stream = None
                stage = 'replace'; temporary.replace(path)
            except OSError as exc:
                # Keep every failed temporary as evidence. Do not let cleanup
                # replace the original stage/errno or decide whether to retry.
                if stream is not None:
                    try: stream.close()
                    except OSError: pass
                retry = exc.errno in RETRY_ERRNOS and index < len(RETRY_DELAYS)
                self.diagnostic(path, {'event': 'heartbeat_write_failed', 'stage': stage,
                    'errno': exc.errno, 'errno_name': errno.errorcode.get(exc.errno, 'UNKNOWN'),
                    'attempt_number': index + 1, 'will_retry': retry,
                    'retry_delay_seconds': RETRY_DELAYS[index] if retry else None,
                    'temporary_file': temporary.name if temporary is not None else None})
                if not retry:
                    raise
                failure_seen = True
                self.sleep(RETRY_DELAYS[index])
            else:
                if failure_seen:
                    self.diagnostic(path, {'event': 'heartbeat_write_recovered', 'stage': 'complete',
                                          'attempt_number': index + 1})
                return


def main():
    # No global Popen patch. All inference is launched by the original trial main.
    if '--live' in sys.argv:
        out = Path(sys.argv[sys.argv.index('--out') + 1]).resolve()
        spec = json.loads(Path(sys.argv[sys.argv.index('--spec') + 1]).read_text())
        frozen_trial.validate_spec(spec, out)
        if not (out / 'result.json').exists():
            marker = out / 'maintenance.json'
            record = maintenance_record()
            if marker.exists():
                if json.loads(marker.read_text()) != record:
                    raise ValueError('Maintenance identity differs; preserve existing attempt')
            else:
                frozen_trial.atomic(marker, record)
    frozen_trial.atomic = HeartbeatAtomic(frozen_trial.atomic)
    frozen_trial.main()


if __name__ == '__main__': main()
