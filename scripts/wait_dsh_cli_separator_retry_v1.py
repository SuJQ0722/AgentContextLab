"""Persistently wait for original DSH drain, then run and score its CLI supplement."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from lab import ROOT
from run_bc_campaign_v3 import atomic, identity
from prepare_dsh_cli_separator_retry_v1 import ORIGINAL, DESTINATION, prepare, read

RUNTIME = ROOT / 'outputs/cloud-runtime/dsh-cli-separator-v1'
GRADING = ROOT / 'outputs/grading/dsh-cli-separator-v1'


def drained(original):
    p = original / 'leases/dsh/owner.json'
    if not p.exists():
        return False
    owner = read(p);run = Path(owner['run_directory']).resolve()
    if not run.is_relative_to((original / 'controllers/dsh').resolve()):
        raise ValueError('Unexpected original controller namespace')
    p = run / 'exit.json'
    if not p.exists():
        return False
    result = read(p)
    if result.get('controller_id') != owner['controller_id'] or result.get('drained') is not True:
        return False
    slots = original / 'cells/dsh/visual/slots'
    return not slots.exists() or not any(slots.iterdir())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original', type=Path, default=ORIGINAL)
    p.add_argument('--destination', type=Path, default=DESTINATION)
    p.add_argument('--live', action='store_true')
    a = p.parse_args();RUNTIME.mkdir(parents=True, exist_ok=True)
    lock = (RUNTIME / 'waiter.lock').open('a');fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if not a.live:
        print(json.dumps({'live': False, 'original_drained': drained(a.original), 'model_calls': 0}));return
    env = os.environ.copy()
    for name in ('ALL_PROXY', 'all_proxy'):
        env.pop(name, None)
    affinity = set(range(8, 16)) & os.sched_getaffinity(0)
    if affinity:
        os.sched_setaffinity(0, affinity)
    def status(stage, **kwargs):
        atomic(RUNTIME / 'status.json', {**identity(), 'at_unix': time.time(), 'stage': stage,
               'original_root': str(a.original), 'supplement_root': str(a.destination), **kwargs})
    while not drained(a.original):
        status('waiting_for_original_drain', model_calls_by_waiter=0)
        time.sleep(30)
    result = prepare(a.original, a.destination, False)
    if not result['prepared']:
        raise RuntimeError('Original drained but supplement source remains unconfirmed')
    def run(stage, command):
        status(stage, command_entry=Path(command[1]).name)
        with (RUNTIME / (stage + '.log')).open('ab') as log:
            result = subprocess.run(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            status('blocked', failed_stage=stage, exit_code=result.returncode)
            raise RuntimeError(stage + ' failed; no automatic prediction replay')
    run('prediction', [sys.executable, str(ROOT / 'scripts/run_dsh_prompt_retry_v1.py'), '--root', str(a.destination / 'cells/bc_dsh'), '--harness', 'dsh', '--concurrency', '16', '--resume', '--live'])
    grading = [sys.executable, str(ROOT / 'scripts/judge_visual_inline_retry_v5.py'), '--root', str(a.destination), '--output', str(GRADING), '--concurrency', '4']
    run('grading_prepare', grading)
    run('grading', grading + ['--live', '--watch'])
    status('finished', prediction_and_grading_complete=True)


if __name__ == '__main__':
    main()
