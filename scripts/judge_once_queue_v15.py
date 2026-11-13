"""One-pass grading queue with asynchronous inventory scans and frozen scoring.

Only scheduling changes: four concurrent first judgments, immutable prediction /
answer / protocol bindings, and existing unknown requests are never replayed.
"""
import argparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import fcntl
import os
from pathlib import Path
import signal
import time

import judge_inline_model_alias_v9 as judge
from lab import ROOT, environment

VERSION = 'once24h-queued-private-judge-v15'
PREDICTIONS = ROOT / 'outputs/campaigns/deepseek-once24h-v15'
OUTPUT = ROOT / 'outputs/grading/deepseek-once24h-v15'
base = judge.v8.parent


def require(value, reason):
    if not value:
        raise ValueError(reason)


def prepare(root, out):
    root, out = Path(root).resolve(), Path(out).resolve()
    require(root == PREDICTIONS and out == OUTPUT, 'Unexpected campaign scope')
    receipt = base.read(out / 'dry-validation.json')
    require(receipt['exit_code'] == 0 and receipt['model_calls'] == 0, 'Missing original zero-call validation')
    require(base.sha(root / 'inventory.json') == receipt['inventory_sha256'], 'Inventory changed')
    require(base.sha(out / 'protocol.json') == receipt['protocol_sha256'], 'Scoring protocol changed')
    cfg = base.read(out / 'protocol.json')
    require(cfg['concurrency_cap'] == 4, 'Preserve frozen four-way scoring cap')
    for name, digest in cfg['sources_sha256'].items():
        require(base.sha(ROOT / 'scripts' / name) == digest, 'Frozen scoring source changed')
    require(base.sha(ROOT / 'hermes-agent/Browsecomp_eval/browsecomp_eval/judge.py') == cfg['hermes_judge_sha256'], 'Answer-equivalence source changed')
    alias = base.read(out / 'model-alias-protocol.json')
    require(alias['source_sha256'] == base.sha(Path(judge.__file__)), 'Alias validator source changed')
    require(alias['base_protocol_sha256'] == receipt['protocol_sha256'], 'Alias protocol differs')
    gold, hashes = base.gold_sources()
    cells = {}
    for item in base.read(root / 'inventory.json')['cells']:
        cell = item['cell']; source = root / 'cells' / cell
        binding = base.read(out / 'cells' / cell / 'source-binding.json')
        require(binding['root'] == str(source) and binding['cell'] == cell, 'Prediction binding differs')
        require(base.sha(source / 'plan.json') == binding['plan_sha256'] == item['plan_sha256'], 'Plan changed')
        require(base.sha(source / 'experiment.json') == binding['config_sha256'], 'Configuration changed')
        require(binding['gold_sources_sha256'] == hashes, 'Private gold changed')
        plan = base.read(source / 'plan.json'); answers = {}
        for job in plan['jobs']:
            require(job['model'] == base.base.MODEL and job['job_id'] not in answers, 'Job model / identity differs')
            value = gold[base.gold_key(job)][job['question_id']]
            require(value['question'] == job['question'], 'Question differs from bound gold')
            answers[job['job_id']] = value['answer']
        all_jobs = plan['jobs']
        cells[cell] = {'root': source, 'plan': {**plan, 'jobs': [j for j in all_jobs if not j.get('calibration_not_scored')]},
                       'answers': answers, 'binding': binding, 'all_jobs': all_jobs,
                       'calibration_jobs': [j for j in all_jobs if j.get('calibration_not_scored')]}
    base.immutable(out / 'queue-protocol-v15.json', {
        'version': VERSION, 'source_sha256': base.sha(__file__),
        'frozen_protocol_sha256': receipt['protocol_sha256'],
        'original_dry_validation_sha256': base.sha(out / 'dry-validation.json'),
        'max_concurrent_judgments': 4, 'prediction_mutation': False,
        'failed_or_unknown_judgment_replay': False, 'inventory_runs_asynchronously': True,
        'scientific_scoring_and_http_fallback_protocol': 'unchanged'})
    return cells, cfg


def unclaimed(candidate):
    directory = Path(candidate['directory'])
    return not any((directory / name).exists() for name in
                   ('grade.json', 'request-started.json', 'local-error.json'))


def run_queue(scan, grade, on_error, status, *, concurrency=4, stop=lambda: False,
              allowed=unclaimed, scan_interval=60., cost_interval=300., poll=.1):
    """Inventory I/O never occupies a grading worker or blocks replenishment."""
    require(1 <= concurrency <= 4, 'Preserve four-way frozen concurrency cap')
    pending = OrderedDict(); issued = set(); futures = {}; summary = {'all_terminal': False}
    next_scan = 0.; last_cost = time.monotonic(); completed = 0; scan_count = 0
    with ThreadPoolExecutor(max_workers=concurrency) as workers, ThreadPoolExecutor(max_workers=1) as scanner:
        scan_future = None
        while True:
            now = time.monotonic()
            if not stop() and scan_future is None and now >= next_scan:
                with_cost = now - last_cost >= cost_interval
                scan_future = scanner.submit(scan, with_cost)
                if with_cost: last_cost = now
            if scan_future is not None and scan_future.done():
                candidates, summary = scan_future.result(); scan_future = None; scan_count += 1
                for candidate in candidates:
                    key = str(candidate['directory'])
                    if key not in issued and key not in pending and allowed(candidate):
                        pending[key] = candidate
                next_scan = time.monotonic() + scan_interval
            while pending and not stop() and len(futures) < concurrency:
                key, candidate = pending.popitem(last=False)
                if key in issued or not allowed(candidate): continue
                issued.add(key)
                futures[workers.submit(grade, candidate)] = candidate
            if futures:
                done, _ = wait(futures, timeout=poll, return_when=FIRST_COMPLETED)
                for future in done:
                    candidate = futures.pop(future)
                    try: future.result()
                    except Exception as exc: on_error(candidate, exc)
                    completed += 1
            else:
                time.sleep(poll)
            status({'active': len(futures), 'pending': len(pending), 'stopping': stop(),
                    'all_terminal': summary['all_terminal'], 'inventory_inflight': scan_future is not None,
                    'inventory_scans': scan_count, 'submitted_this_generation': len(issued),
                    'returned_this_generation': completed, 'concurrency': concurrency})
            if stop() and not futures: break
            if not futures and not pending and scan_future is None and summary['all_terminal']:
                break
    return {'submitted': len(issued), 'returned': completed, 'inventory_scans': scan_count,
            'all_terminal': summary['all_terminal'], 'stopped': stop()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=PREDICTIONS)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--concurrency', type=int, default=4)
    args = parser.parse_args()
    require(args.concurrency == 4, 'This deployment retains exactly four concurrent judges')
    cells, cfg = prepare(args.root, args.output)
    if not args.live:
        candidates, summary = judge.v8.report(cells, args.output, False)
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
    last_status = [0.]
    def status(row):
        if time.monotonic() - last_status[0] < 1.: return
        last_status[0] = time.monotonic()
        base.atomic(args.output / 'status.json', {'at': base.base.bc.now(), 'pid': os.getpid(), 'version': VERSION, **row})
    def error(candidate, exc):
        base.atomic(Path(candidate['directory']) / 'local-error.json', {
            'at': base.base.bc.now(), 'error_type': type(exc).__name__, 'automatic_retry': False})
    result = run_queue(lambda with_cost: judge.v8.report(cells, args.output, with_cost),
                       lambda c: judge.grade_bound(c, cfg, env), error, status, stop=lambda: stopped)
    judge.v8.report(cells, args.output, True)
    base.atomic(generation / 'exit.json', {'at': base.base.bc.now(), **result})
    base.atomic(args.output / 'status.json', {'at': base.base.bc.now(), 'pid': os.getpid(),
        'version': VERSION, 'active': 0, 'pending': 0, 'finished': True, **result})


if __name__ == '__main__':
    main()
