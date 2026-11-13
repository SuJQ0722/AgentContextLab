"""Keep AFS status writes and claim checks off the grading dispatcher.

The V15 queue, four-way scoring protocol, gold bindings and judgment function
remain unchanged. This entrypoint adds a coalescing status writer and performs
late claim checks inside workers so filesystem stalls cannot starve admission.
"""
import argparse
import fcntl
import os
from pathlib import Path
import signal
import threading
import time

import judge_once_queue_v15 as v15
from lab import ROOT, environment

VERSION = 'once24h-queued-private-judge-io-v16'
base = v15.base


class LatestStatusWriter:
    """One bounded latest-state slot; publishing never waits for filesystem I/O."""
    def __init__(self, write, interval=5.):
        self.write = write; self.interval = interval
        self.condition = threading.Condition(); self.pending = None
        self.closing = False; self.error = None; self.writes = 0
        self.thread = threading.Thread(target=self._run, name='grading-status-writer')
        self.thread.start()

    def publish(self, value):
        with self.condition:
            if self.closing: raise RuntimeError('Status writer already closing')
            self.pending = dict(value)
            self.condition.notify()

    def _run(self):
        last = float('-inf')
        while True:
            with self.condition:
                while self.pending is None:
                    if self.closing: return
                    self.condition.wait()
                delay = self.interval - (time.monotonic() - last)
                if delay > 0 and not self.closing:
                    self.condition.wait(delay); continue
                value = self.pending; self.pending = None
            try:
                self.write(value); self.writes += 1; self.error = None
            except Exception as exc:
                self.error = type(exc).__name__
            last = time.monotonic()

    def close(self):
        with self.condition:
            self.closing = True; self.condition.notify()
        self.thread.join()
        if self.error:
            raise RuntimeError('Final status write failed: ' + self.error)


def grade_if_unclaimed(candidate, grade, allowed=v15.unclaimed):
    if not allowed(candidate): return {'status': 'already_claimed'}
    return grade(candidate)


def run_queue(scan, grade, on_error, status, *, allowed=v15.unclaimed, **kwargs):
    # Inventory already filters claims. Recheck after admission in the worker;
    # the frozen grade function also uses an exclusive request-started claim.
    return v15.run_queue(scan, lambda c: grade_if_unclaimed(c, grade, allowed),
                         on_error, status, allowed=lambda c: True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=v15.PREDICTIONS)
    parser.add_argument('--output', type=Path, default=v15.OUTPUT)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    cells, cfg = v15.prepare(args.root, args.output)
    base.immutable(args.output / 'queue-io-protocol-v16.json', {
        'version': VERSION, 'source_sha256': base.sha(__file__),
        'queue_v15_source_sha256': base.sha(v15.__file__),
        'frozen_scoring_protocol_sha256': base.sha(args.output / 'protocol.json'),
        'concurrency': 4, 'status_write_interval_seconds': 5,
        'status_queue_max_pending': 1, 'claims_checked_inside_workers': True,
        'unknown_or_failed_judgments_replayed': False})
    if not args.live:
        candidates, summary = v15.judge.v8.report(cells, args.output, False)
        print({'live': False, 'model_calls': 0, 'ready_to_grade': len(candidates), 'all_terminal': summary['all_terminal']})
        return
    lock = (args.output / 'controller.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    env, _ = environment(ROOT, 'hermes')
    stopped = False
    def stop(*unused):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGTERM, stop)
    generation = args.output / 'queue-generations' / str(time.time_ns())
    base.immutable(generation / 'launch.json', {'at': base.base.bc.now(), 'pid': os.getpid(),
        'version': VERSION, 'source_sha256': base.sha(__file__), 'concurrency': 4,
        'protocol_sha256': base.sha(args.output / 'protocol.json')})
    writer = LatestStatusWriter(lambda row: base.atomic(args.output / 'status.json', row))
    def status(row):
        writer.publish({'at': base.base.bc.now(), 'pid': os.getpid(), 'version': VERSION, **row})
    def error(candidate, exc):
        base.atomic(Path(candidate['directory']) / 'local-error.json', {
            'at': base.base.bc.now(), 'error_type': type(exc).__name__, 'automatic_retry': False})
    try:
        result = run_queue(lambda cost: v15.judge.v8.report(cells, args.output, cost),
            lambda c: v15.judge.grade_bound(c, cfg, env), error, status, stop=lambda: stopped)
    finally:
        writer.close()
    v15.judge.v8.report(cells, args.output, True)
    base.atomic(generation / 'exit.json', {'at': base.base.bc.now(), **result})
    base.atomic(args.output / 'status.json', {'at': base.base.bc.now(), 'pid': os.getpid(),
        'version': VERSION, 'active': 0, 'pending': 0, 'finished': True, **result})


if __name__ == '__main__':
    main()
