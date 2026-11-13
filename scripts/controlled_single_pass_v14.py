"""Reviewable formal three-arm repair: one native launch per slot, no timeout retry.

V8 visual/native evidence is retained. Nine groups pin historical measured
targets; five groups must publish a new real visual target before either text
arm can launch. Old calibration completions never count as formal accuracy.
"""
import argparse
import copy
import datetime
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

from lab import ROOT, python_for, environment
import controlled_inline_retry_v8 as v8
import controlled_native_worker_bounded_v1 as bounded
import controlled_native_engine_v14 as engine
import controlled_visual_same_target_v13 as replay
from controlled_transport_v5 import DiagnosticRecorder

VERSION = 'controlled-formal-single-pass-v14'
DEFAULT = ROOT / 'outputs/campaigns/visual-hosted-failure-retry-v1/cells/formal-single-pass-v14'
REVIEW = ROOT / 'outputs/recovery-controlled-info-v13/formal-visual-extra-one-review/manifest.json'
FINISH_BY = datetime.datetime(2026, 11, 14, 18, 20, 6, tzinfo=datetime.timezone.utc).timestamp()


def read(path): return json.loads(Path(path).read_text())
def sha(path): return replay.sha(path)
def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)); temporary.replace(path)


def prepare(root):
    if (root / 'plan.json').exists(): raise ValueError('Frozen plan exists')
    oldroot = ROOT / 'outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v8-one-hour-retry5/cells'
    source_plan_path = ROOT / 'outputs/experiment3/controlled-native-bounded-v1/plan.json'
    source_plan = read(source_plan_path); specs = {j['job_id']: j for j in source_plan['jobs']}
    old = {j['job_id']: j for cell in ('controlled_bc', 'controlled_mmbc') for j in read(oldroot / cell / 'plan.json')['jobs']}
    groups = []; jobs = []
    for reviewed in read(REVIEW)['jobs']:
        original = old[reviewed['job_id']]; key = original['controlled_prefix_key']
        dataset = key.split('/')[0]
        cell = root / 'cells' / dataset; group = {'prefix_key': key, 'dataset': dataset,
            'target_mode': 'historical_pinned' if reviewed['current_target_available'] else 'new_visual_measured',
            'previous_v8_attempts': 6, 'previous_formal_success': False}
        reference = None
        if reviewed['current_target_available']:
            reference = Path(reviewed['target_source']); value = read(reference)
            if sha(reference) != reviewed['target_sha256'] or not v8.valid_target(value): raise ValueError('Invalid old target')
            destination = v8.target_path(cell, key); replay.immutable(destination, reference.read_bytes())
            group.update(target_source=str(reference), target_sha256=sha(reference), target_tokens=value['first_actual_prompt_tokens'])
        for method in ('visual', 'summary', 'window'):
            source = specs[key + '/' + method]
            if not source['eligible'] or sha(source['spec_path']) != source['spec_sha256']: raise ValueError('Eligible fixed cohort source required')
            spec = read(source['spec_path']); prefix = Path(spec['prefix_path'])
            if len(engine.native_parts(read(prefix)['messages'])) > 10: raise ValueError('Cannot omit native evidence')
            job = copy.deepcopy(original)
            spec.update(model=original['model'], config_path=original['config_path'],
                controlled_retry_version=v8.VERSION, controlled_retention_policy='recent_rendered_text_pages_then_all_native')
            if method != 'visual': spec['target_reference_path'] = str(v8.target_path(cell, key))
            specpath = cell / 'controlled-specs' / (key.replace('/', '_') + '_' + method + '.json')
            replay.immutable(specpath, (json.dumps(spec, sort_keys=True, indent=2) + '\n').encode())
            job.update(job_id='controlled/' + key + '/' + method, campaign_root=str(cell), dataset=dataset,
                controlled_target_root=str(cell), control_target_path=str(v8.target_path(cell, key)),
                controlled_dependency=None if method == 'visual' else str(v8.target_path(cell, key)),
                controlled_method=method, controlled_spec_path=str(specpath), controlled_spec_sha256=sha(specpath),
                timeout_seconds=3600, max_timeout_retries=0, calibration_not_scored=False,
                single_pass_v14={'version': VERSION, 'maximum_native_launches': 1, 'max_iterations': 500,
                    'target_mode': group['target_mode'], 'config_sha256': sha(original['config_path']),
                    'prefix_sha256': sha(prefix), 'new_summary_fitting_protocol': True})
            if reference and method == 'visual':
                representation = reference.parent / 'representation.json'
                job['single_pass_v14'].update(target_source=str(reference), target_sha256=sha(reference),
                    representation_path=str(representation), representation_sha256=sha(representation))
            jobs.append(job)
        groups.append(group)
    sources = ['controlled_single_pass_v14.py', 'controlled_native_engine_v14.py', 'summary_prefix_fit_v14.py',
        'controlled_visual_same_target_v13.py', 'controlled_inline_retry_v8.py', 'controlled_native_worker_bounded_v1.py',
        'controlled_visual_inline_worker_v4.py', 'network_entry_v13.py']
    plan = {'version': VERSION, 'groups': groups, 'jobs': jobs, 'formal_groups': len(groups),
        'maximum_new_trajectories': len(jobs), 'concurrency_per_cell': 16,
        'deadline_seconds_per_trajectory': 3600, 'max_iterations': 500, 'timeout_retry': False,
        'stop_new_trajectories_by_utc': '2026-11-14T17:20:06Z',
        'operational_transport_override': {'write_seconds': 300, 'stream_seconds': 630,
            'four_route_error_failover': 'unchanged', 'no_retry_scope': 'new trajectory after 3600s timeout'},
        'launch_authorized': False, 'review_sha256': sha(REVIEW), 'source_plan_sha256': sha(source_plan_path),
        'source_sha256': {name: sha(ROOT / 'scripts' / name) for name in sources},
        'comparison': 'Same prefix/native and target within group. New summary fitting protocol; not pooled with older summary protocols.'}
    save(root / 'plan.json', plan); return plan


def validate_plan(root, plan):
    for name, digest in plan['source_sha256'].items():
        if sha(ROOT / 'scripts' / name) != digest: raise ValueError('Frozen implementation changed')
    for job in plan['jobs']:
        if sha(job['controlled_spec_path']) != job['controlled_spec_sha256']: raise ValueError('Spec changed')
        spec = read(job['controlled_spec_path']); proof = job['single_pass_v14']
        if sha(spec['prefix_path']) != proof['prefix_sha256'] or sha(job['config_path']) != proof['config_sha256']:
            raise ValueError('Frozen prefix/config changed')


def offline_preflight(root, plan):
    """Real fixed-prefix rendering/transport, zero model calls and no targets invented."""
    from inline_visual_transport_v1 import transform
    env, _ = environment(ROOT, 'hermes')
    for key in ('PATH', 'LD_LIBRARY_PATH'):
        if key in env: os.environ[key] = env[key]
    run_root = root / 'offline-preflight' / ('run-' + str(time.time_ns()))
    results = []
    for job in plan['jobs']:
        if job['controlled_method'] != 'visual': continue
        spec = read(job['controlled_spec_path']); proof = job['single_pass_v14']
        directory = run_root / job['controlled_prefix_key']
        cls = bounded.BoundedAdapter
        if proof['target_mode'] == 'historical_pinned':
            target = read(proof['target_source'])
            cls = replay.adapter_class(target, Path(proof['representation_path']), proof['representation_sha256'])
        with patch.object(bounded, 'v5', engine):
            adapter = cls(spec, directory)
            adapter.original_compose = lambda current, question, native, parts: v8.native_last_compose(
                engine.compose, directory, current, question, native, parts)
            prefix = read(spec['prefix_path']); clean = engine.text_only(prefix['messages'])
            pages, seconds = adapter.render_prefix(clean, 16)
            messages = adapter.compose([{'role': 'user', 'content': job['question']}], job['question'], adapter.native, pages)
            body, audit = transform(json.dumps({'model': job['model'], 'messages': messages}).encode(), rendered_registry=adapter.registry)
        result = {'prefix_key': job['controlled_prefix_key'], 'paid_calls': 0,
            'target_mode': proof['target_mode'], 'body_bytes_test_envelope': len(body),
            'image_count': len(audit['selection']['retained']), 'render_seconds': seconds,
            'native_omitted': any(x['origin'] == 'native' for x in audit['selection']['removed']),
            'provider_budget_measured': False, 'new_target_created': False}
        if result['native_omitted']: raise ValueError('Offline native evidence omission')
        save(directory / 'result.json', result); results.append(result)
    save(root / 'offline-preflight.json', {'paid_calls': 0, 'groups': results})
    return results


def worker(root, job, out):
    plan = read(root / 'plan.json'); validate_plan(root, plan)
    if job not in plan['jobs']: raise ValueError('Job not authorized by frozen plan')
    if out != Path(job['campaign_root']) / 'jobs' / job['job_id'] / 'attempt_001': raise ValueError('One canonical attempt required')
    original_validate = v8.validate; original_adapter = bounded.BoundedAdapter
    proof = job['single_pass_v14']; gate = None
    if proof['target_mode'] == 'historical_pinned' and job['controlled_method'] == 'visual':
        if sha(proof['target_source']) != proof['target_sha256']: raise ValueError('Historical target changed')
        target = read(proof['target_source']); gate = replay.TargetGate(target)
        original_adapter = replay.adapter_class(target, Path(proof['representation_path']), proof['representation_sha256'])
    class Adapter(original_adapter):
        def annotate(self, value):
            result = super().annotate(value)
            result.update(controlled_single_pass_version=VERSION, summary_fit_version='summary-prefix-fit-v14')
            if gate: gate.annotate(result)
            # Publication occurs after bounded and actual-wire annotations.
            # Old V8 tried before bounded annotation and could miss a true target.
            v8.publish_target(job, result)
            return result
    def validate(j, directory):
        spec, cfg = original_validate(j, directory)
        return {**spec, 'max_rounds': 500}, cfg
    original_write = DiagnosticRecorder.write
    original_transport = v8.parent.runtime_install
    def transport(policy, directory, **kwargs):
        effective = {**policy, 'write_seconds': 300., 'stream_seconds': 630.}
        save(out / 'single-pass-transport.json', {'version': VERSION, 'original_policy': policy,
            'effective_policy': effective, 'trajectory_wall_seconds': 3600,
            'route_error_failover_unchanged': True, 'new_trajectory_retry': False,
            'SDK_call_counts_not_physical_HTTP_attempt_counts': True})
        return original_transport(effective, directory, **kwargs)
    def record(self, name, value, *args, **kwargs):
        result = original_write(self, name, value, *args, **kwargs)
        if gate and name == 'budget-attempts.jsonl': gate.budget(value)
        if gate and name == 'calls.jsonl' and value.get('purpose') == 'agent' and not gate.first_agent_observed:
            gate.first_agent_observed = True
            gate.check((value.get('raw_provider_usage') or {}).get('prompt_tokens'), 'first actual including failed stream')
        return result
    specpath = out / 'job.json'; save(specpath, job)
    sys.argv = [v8.__file__, '--spec', str(specpath), '--out', str(out), '--live']
    with patch.object(bounded, 'v5', engine), patch.object(bounded, 'BoundedAdapter', Adapter), \
            patch.object(v8, 'validate', validate), patch.object(DiagnosticRecorder, 'write', record), \
            patch.object(v8.parent, 'runtime_install', transport):
        v8.main()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--root', type=Path, default=DEFAULT)
    parser.add_argument('--prepare', action='store_true'); parser.add_argument('--live', action='store_true')
    parser.add_argument('--offline-preflight', action='store_true')
    parser.add_argument('--dataset', choices=['browsecomp_v3', 'mmbrowsecomp']); parser.add_argument('--concurrency', type=int, default=16)
    parser.add_argument('--worker-job'); parser.add_argument('--authorization', type=Path)
    args = parser.parse_args(); root = args.root.resolve()
    plan = prepare(root) if args.prepare else read(root / 'plan.json'); validate_plan(root, plan)
    if args.offline_preflight:
        if args.live: raise ValueError('Offline preflight cannot enable live')
        result = offline_preflight(root, plan); print(json.dumps({'paid_calls': 0, 'offline_groups': len(result)})); return
    if not args.live:
        print(json.dumps({'live': False, 'groups': plan['formal_groups'], 'maximum_new_trajectories': len(plan['jobs'])})); return
    if not args.authorization: raise ValueError('Explicit reviewed additional-attempt authorization required')
    auth = read(args.authorization)
    if auth.get('authorized') is not True or auth.get('plan_sha256') != sha(root / 'plan.json') or auth.get('attempts_per_slot') != 1:
        raise ValueError('Authorization does not match one-attempt plan')
    if args.worker_job:
        job = next(j for j in plan['jobs'] if j['job_id'] == args.worker_job)
        if job['job_id'] not in auth.get('job_ids', []): raise ValueError('Slot not explicitly authorized')
        out = Path(job['campaign_root']) / 'jobs' / job['job_id'] / 'attempt_001'
        worker(root, job, out); return
    if args.dataset is None or not 1 <= args.concurrency <= 16: raise ValueError('One dataset per container, <=16 workers')
    lease_path = root / (args.dataset + '.lock'); lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease = lease_path.open('a'); fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stopping = False; active = {}; jobs = [j for j in plan['jobs'] if j['dataset'] == args.dataset and j['job_id'] in auth.get('job_ids', [])]
    def stop(*unused):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    env, _ = environment(ROOT, 'hermes')
    try:
        while True:
            stopping = stopping or (root / 'STOP').exists() or time.time() >= FINISH_BY - 3600
            for jid, (process, out, begin, log) in list(active.items()):
                elapsed = time.monotonic() - begin
                if process.poll() is None and elapsed > 3600:
                    os.killpg(process.pid, signal.SIGTERM); time.sleep(2)
                    if process.poll() is None: os.killpg(process.pid, signal.SIGKILL)
                if process.poll() is not None:
                    result = read(out / 'native-result.json') if (out / 'native-result.json').exists() else {}
                    save(out / 'terminal.json', {'status': 'timeout' if elapsed > 3600 else result.get('status', 'failed'),
                        'exit_code': process.returncode, 'elapsed': elapsed, 'new_attempts': 1, 'will_retry': False})
                    log.close(); del active[jid]
            pending = []
            for job in jobs:
                out = Path(job['campaign_root']) / 'jobs' / job['job_id'] / 'attempt_001'
                if out.exists(): continue  # Unknown claims never reset.
                if job['controlled_method'] != 'visual':
                    target = Path(job['control_target_path'])
                    if not target.exists() or not v8.valid_target(read(target)): continue
                pending.append((job, out))
            if not stopping:
                for job, out in pending[:max(0, args.concurrency - len(active))]:
                    out.mkdir(parents=True, exist_ok=False); log = (out / 'worker.log').open('a')
                    command = [python_for(ROOT), str(ROOT / 'scripts/network_entry_v13.py'), '--target', str(Path(__file__).resolve()),
                        '--root', str(root), '--worker-job', job['job_id'], '--authorization', str(args.authorization), '--live']
                    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    save(out / 'dispatch.json', {'pid': process.pid, 'started': time.time(), 'new_attempt': 1})
                    active[job['job_id']] = (process, out, time.monotonic(), log)
            save(root / (args.dataset + '-status.json'), {'at': time.time(), 'active': list(active), 'pending_ready': len(pending), 'stop_dispatch': stopping})
            if not active and (stopping or not pending): break
            time.sleep(3)
    finally:
        # A scheduler/AFS exception must not abruptly terminate paid children.
        # Drain each already launched trajectory within its original 1h limit.
        for jid, (process, out, begin, log) in list(active.items()):
            try:
                process.wait(timeout=max(.01, 3600-(time.monotonic()-begin)))
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try: process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait()
            finally:
                log.close()
                if not (out/'terminal.json').exists():
                    result=read(out/'native-result.json') if(out/'native-result.json').exists() else {}
                    save(out/'terminal.json', {'status': 'timeout' if time.monotonic()-begin>=3600 else result.get('status','failed'),
                        'exit_code':process.returncode,'elapsed':time.monotonic()-begin,'new_attempts':1,'will_retry':False,
                        'controller_finally_drain':True})



if __name__ == '__main__': main()
