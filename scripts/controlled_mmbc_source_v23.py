"""Single-attempt split-native baselines on a frozen source-VERA cohort.

The source VERA embeds visual evidence in canvases. These two treatments keep
native parts separately and match actual source TOTAL prompt tokens, not image
tokens. This is a single-intervention continuation, not a fresh full benchmark.
"""
import argparse
import copy
import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from unittest.mock import patch

from lab import ROOT, environment, python_for
import controlled_native_engine_v23 as engine
import controlled_native_engine_v17 as window_engine
from controlled_mmbc_source_v22 import validate_plan as validate_predecessor
from inline_route_contract_v2 import ROUTES
from run_bc_campaign_v3 import identity

VERSION = 'controlled-mmbc-source-summary-v23'
REFERENCE_VERSION = 'source-vera-total-prompt-reference-v17'
DEFAULT = ROOT / 'outputs/controlled-mmbc-vera-nontimeout-summary-v23'
DEADLINE = datetime.datetime(2026, 11, 14, 19, 20, 6, tzinfo=datetime.timezone.utc).timestamp()
METHODS = ('summary',)
SOURCES = ['controlled_mmbc_source_v23.py', 'controlled_native_engine_v23.py', 'controlled_native_engine_v17.py', 'review_execution.py', 'controlled_native_guard_v4.py', 'hermes_bc_worker_v3.py',
           'capture_multimodal_prefix_v5.py', 'controlled_transport_v5.py',
           'controlled_native_preflight.py', 'summary_prefix_fit_v14.py', 'summary_prefix_fit_v17.py',
           'visual_transport_runtime_v4.py', 'inline_visual_transport_v1.py',
           'inline_route_contract_v2.py', 'network_entry_v13.py']


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)); temp.replace(path)

def immutable(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    if path.exists():
        if path.read_bytes() != data: raise ValueError('Immutable artifact differs: ' + str(path))
        return
    with path.open('xb') as stream: stream.write(data)


def prepare(root, cohort_path, pending_manifest):
    root = Path(root).resolve(); cohort_path = Path(cohort_path).resolve()
    if (root / 'plan.json').exists(): raise ValueError('Frozen plan already exists')
    cohort = read(cohort_path); slots = cohort['slots']
    pending_manifest=Path(pending_manifest).resolve(); migration=read(pending_manifest)
    if migration.get('paid_task_retry_authorized') is not False or migration.get('already_dispatched_count')!=1:raise ValueError('No paid attempt replay authorized')
    for key in ['stop','controller_pause_snapshot']:
        if sha(migration[key+'_path'])!=migration[key+'_sha256']:raise ValueError('Pause proof changed')
    whitelist={x['job_id']:x for x in migration['never_dispatched']}
    if len(whitelist)!=len(migration['never_dispatched']) or len(whitelist)!=83:raise ValueError('Exact frozen83 unstarted summary jobs required')
    previous_root=Path(migration['source_root']).resolve()
    if sha(previous_root/'plan.json')!=migration['source_plan_sha256']:raise ValueError('Previous plan changed')
    validate_predecessor(previous_root,read(previous_root/'plan.json'))
    for entry in whitelist.values():
        if sha(entry['source_spec_path'])!=entry['source_spec_sha256']:raise ValueError('Previous spec changed')
        previous=previous_root/'cells/summary/jobs'/entry['job_id'].split('/')[-1]/'attempt_001'
        if any((previous/name).exists() for name in ['dispatch.json','attempt-started.json','terminal.json']):raise ValueError('Previously attempted slot cannot migrate')
    # The live source comes from configs/experiment.json; transport settings are
    # an explicit copy of the already reviewed four-channel inline protocol.
    base = read(ROOT / 'configs/experiment.json')
    old = read(ROOT / 'outputs/campaigns/visual-hosted-failure-retry-v1/cells/formal-single-pass-v14/plan.json')
    transport = read(old['jobs'][0]['config_path'])
    for key in ['image_transport', 'transport_runtime_version', 'transport_delivery_version',
                'model_route_policy', 'approved_model_routes', 'gateway_proxy', 'transport_runtime_policy']:
        base[key] = copy.deepcopy(transport[key])
    base.update(model=ROUTES[0], execution_version='hermes-parity-v3', timeout_seconds=3600, max_output_tokens=8192,
                controlled_source_version=VERSION, review_approved=True)
    base['transport_runtime_policy'].update(write_seconds=300., stream_seconds=630.)
    config = root / 'config.json'; immutable(config, base)
    jobs = []
    for slot in slots:
        qid = slot.get('question_id', slot.get('qid')); repeat = int(slot['repeat'])
        if not qid or '/' in qid or repeat not in (1, 2, 3): raise ValueError('Invalid slot identity')
        key = f'{qid}_r{repeat:02d}'
        if 'summary/'+key not in whitelist:continue
        if whitelist['summary/'+key]['source_result_sha256']!=slot['source_result_sha256']:raise ValueError('Source result differs from pending whitelist')
        action = slot['execution']
        if action not in ('matched_continuation', 'no_compression_reuse', 'blocked'):
            raise ValueError('Unknown source action')
        target = None
        if action == 'matched_continuation':
            prefix = Path(slot['prefix_path']); evidence_path = Path(slot['target_evidence_path'])
            if sha(prefix) != slot['prefix_sha256'] or sha(evidence_path) != slot['target_evidence_sha256']:
                raise ValueError('Extracted source changed')
            evidence = read(evidence_path); request = read(prefix)
            native = engine.native_parts(request['messages'])
            tokens = slot.get('source_post_prompt_tokens', slot.get('source_first_post_prompt_tokens'))
            if type(tokens) is not int or tokens <= 0: raise ValueError('Actual source provider token count required')
            if (evidence.get('target_is_provider_measured') is not True
                    or evidence.get('first_actual_prompt_tokens') != tokens
                    or evidence.get('prefix_sha256') != sha(prefix)
                    or evidence.get('source_result_sha256') != slot['source_result_sha256']
                    or not evidence.get('source_call_id')):
                raise ValueError('Target count lacks bound provider-call evidence')
            calls = Path(evidence['source_calls_path'])
            if sha(calls) != evidence['source_calls_sha256']: raise ValueError('Source usage ledger changed')
            matches = [json.loads(line) for line in calls.read_text().splitlines()
                       if json.loads(line).get('call_id') == evidence['source_call_id']]
            if len(matches) != 1 or (matches[0].get('raw_provider_usage') or {}).get('prompt_tokens') != tokens:
                raise ValueError('Target is not the referenced provider response')
            if len(native) > 10: raise ValueError('Extractor must block more than ten native images')
            upper = math.floor(tokens * 1.02)
            if upper + base['max_output_tokens'] > base['context_window']:
                raise ValueError('Matched input target leaves insufficient configured context')
            target = {'version': REFERENCE_VERSION, 'source_usage_verified': True,
                'prefix_sha256': sha(prefix), 'baseline_native_hashes': engine.image_ids(native),
                'source_first_post_prompt_tokens': tokens,
                'source_target_evidence_path': str(evidence_path), 'source_target_evidence_sha256': sha(evidence_path),
                'source_result_path': slot['source_result_path'], 'source_result_sha256': slot['source_result_sha256'],
                'source_post_request_path': slot.get('source_post_request_path'),
                'source_post_request_sha256': slot.get('source_post_request_sha256'),
                'source_model': request.get('model'), 'image_token_parity_claimed': False,
                'source_vera_evidence': 'embedded in canvas; baseline original native parts remain separate',
                'source_proof': evidence}
            target_path = root / 'references' / (key + '.json'); immutable(target_path, target)
        for method in METHODS:
            cell = root / 'cells' / method
            job = {'job_id': f'{method}/{key}', 'question_id': qid, 'repeat': repeat,
                'method': method, 'strategy': method, 'dataset': 'mmbrowsecomp', 'benchmark': 'controlled_mmbc',
                'source_slot_id': slot.get('slot_id', slot.get('slot')), 'action': action,
                'reason': slot.get('reason'), 'source_result_path': slot['source_result_path'],
                'source_result_sha256': slot['source_result_sha256'],
                'source_status': slot.get('source_status', slot.get('status')),
                'question': slot.get('question'),
                'source_grade_path': slot.get('source_grade_path'),
                'source_grade_sha256': slot.get('source_grade_sha256'),
                'source_score': slot.get('source_score'),
                'model': ROUTES[0], 'config_path': str(config), 'config_sha256': sha(config),
                'cell': str(cell), 'output_path': str(cell / 'jobs' / key / 'attempt_001'),
                'timeout_seconds': 3600, 'max_iterations': 500, 'maximum_new_attempts': 1}
            if action == 'matched_continuation':
                original_images = slot.get('original_input_images', [])
                spec = {'version': VERSION, 'dataset': 'mmbrowsecomp', 'method': method,
                    'question_id': qid, 'repeat': repeat, 'question': slot['question'],
                    'model': ROUTES[0], 'source_prefix_model': request.get('model'),
                    'explicit_route_migration': request.get('model') != ROUTES[0],
                    'prefix_path': str(prefix), 'prefix_sha256': sha(prefix),
                    'target_reference_path': str(target_path), 'source_target_upper': upper,
                    'source_native_root': slot['source_native_root'],
                    'native_asset_roots': slot.get('native_asset_roots', [str(Path(slot['source_native_root']) / 'workspace')]),
                    'source_vera_status': job['source_status'], 'source_protocol': slot.get('source_protocol'),
                    'image': [x['path'] for x in original_images], 'frozen_input_images': original_images,
                    'config_path': str(config), 'threshold': 0, 'max_rounds': 500}
                spec_path = root / 'specs' / method / (key + '.json'); immutable(spec_path, spec)
                job.update(spec_path=str(spec_path), spec_sha256=sha(spec_path), prefix_path=str(prefix),
                           prefix_sha256=sha(prefix), target_path=str(target_path), target_sha256=sha(target_path))
            jobs.append(job)
    if len({j['job_id'] for j in jobs}) != len(jobs): raise ValueError('Duplicate selected slot')
    if {j['job_id'] for j in jobs}!=set(whitelist):raise ValueError('Cohort and pending whitelist differ')
    plan = {'version': VERSION, 'pending_manifest_path':str(pending_manifest),'pending_manifest_sha256':sha(pending_manifest),
        'previous_root':str(previous_root),'previous_plan_sha256':sha(previous_root/'plan.json'),
        'previous_paid_slots_not_replayed':26,'canary_job_id':jobs[0]['job_id'],
        'canary_policy':'Only the first formal slot may run until actual TOTAL +/-2% and native integrity gates pass; failed canary stops new dispatch without retry.', 'created_at': time.time(), 'cohort_path': str(cohort_path),
        'cohort_sha256': sha(cohort_path), 'cohort_slots': len(slots), 'denominator': 300,
        'jobs': jobs, 'concurrency_per_method': 16, 'attempts_per_slot': 1,
        'stop_new_at_unix': DEADLINE - 4200, 'finish_by_utc': '2026-11-14T19:20:06Z',
        'predecessor_execution': 'V20 summary25 paid slots and V22 formal canary097r03 are retained and never replayed. Only83 never-dispatched slots migrate under frozen SHA whitelist. Plain factual summary body is the specified new output protocol, replacing JSON; no fallback parsing of old malformed responses.',
        'user_authorization': 'Run both baselines on current MMBC VERA non-timeout subset; each16. VERA embeds images, controls keep them separate.',
        'image_token_parity_claimed': False, 'summary_output_protocol':'Plain factual body only; nonempty, finish stop, no tool calls/base64/executable markup; no JSON or boundary-marker requirement', 'summary_generation_policy': 'Up to32 fine-grained disjoint source partitions, each one generation with max8192 output, desired text<=1000 and explicit detailed-evidence prompt about2000 tokens; measured full-source feasibility and combined-summary prefix calibration; no padding or generation retry', 'comparison': 'Fixed-source-prefix single intervention, source total input matched +/-2%; not fresh end-to-end avg3.',
        'source_sha256': {name: sha(ROOT / 'scripts' / name) for name in SOURCES},
        'harness_lock_sha256': sha(ROOT / 'harness-lock.json'), 'config_sha256': sha(config)}
    immutable(root / 'plan.json', plan); return plan


def validate_plan(root, plan, *, deep=False):
    root = Path(root).resolve()
    if plan.get('version') != VERSION or plan.get('attempts_per_slot') != 1:
        raise ValueError('Explicit single-attempt source-cohort protocol required')
    if sha(plan['pending_manifest_path'])!=plan['pending_manifest_sha256']:raise ValueError('Pending whitelist changed')
    if sha(Path(plan['previous_root'])/'plan.json')!=plan['previous_plan_sha256']:raise ValueError('Predecessor plan changed')
    validate_predecessor(Path(plan['previous_root']),read(Path(plan['previous_root'])/'plan.json'))
    migration=read(plan['pending_manifest_path'])
    for key in ['stop','controller_pause_snapshot']:
        if sha(migration[key+'_path'])!=migration[key+'_sha256']:raise ValueError('Pause proof changed')
    for entry in migration['never_dispatched']:
        prior=Path(plan['previous_root'])/'cells/summary/jobs'/entry['job_id'].split('/')[-1]/'attempt_001'
        if any((prior/name).exists() for name in ['dispatch.json','attempt-started.json','terminal.json']):raise ValueError('Previously attempted slot cannot run')
    if sha(plan['cohort_path']) != plan['cohort_sha256']: raise ValueError('Cohort changed')
    if sha(ROOT / 'harness-lock.json') != plan['harness_lock_sha256']: raise ValueError('Harness pin changed')
    for name, digest in plan['source_sha256'].items():
        if sha(ROOT / 'scripts' / name) != digest: raise ValueError('Frozen implementation changed: ' + name)
    ids = set()
    for job in plan['jobs']:
        if job['job_id'] in ids or job['method'] not in METHODS: raise ValueError('Invalid/duplicate method slot')
        ids.add(job['job_id'])
        expected = root / 'cells' / job['method'] / 'jobs' / f"{job['question_id']}_r{job['repeat']:02d}" / 'attempt_001'
        if Path(job['output_path']).resolve() != expected: raise ValueError('Wrong output scope')
        if deep: validate_job(job)
    if sha(root / 'config.json') != plan['config_sha256']: raise ValueError('Frozen configuration changed')
    # Exercise the same no-network review/config gate as native capture.worker.
    from review_execution import enforce
    enforce(read(root / 'config.json'), {}, root)


def validate_job(job):
    if sha(job['source_result_path']) != job['source_result_sha256']: raise ValueError('Source result changed')
    if job['action'] != 'matched_continuation': return
    for kind in ('spec', 'prefix', 'target', 'config'):
        if sha(job[kind + '_path']) != job[kind + '_sha256']: raise ValueError(kind + ' changed')
    spec = read(job['spec_path']); target = read(job['target_path'])
    if spec['method'] != job['method'] or spec['question_id'] != job['question_id'] or spec['repeat'] != job['repeat']:
        raise ValueError('Spec identity changed')
    if sha(target['source_target_evidence_path']) != target['source_target_evidence_sha256']:
        raise ValueError('Measured target proof changed')
    parts = engine.native_parts(read(spec['prefix_path'])['messages'])
    if len(parts)>10 or engine.image_ids(parts) != target['baseline_native_hashes']:
        raise ValueError('Native evidence differs')
    for entry in spec['frozen_input_images']:
        if sha(entry['path']) != entry['sha256']: raise ValueError('Frozen original input image changed')


def annotate(out, value):
    rows = []
    p = Path(out) / 'metrics/inline-images-wire-v1.jsonl'
    if p.exists(): rows = [json.loads(x) for x in p.read_text().splitlines() if x]
    allowed = [x for x in rows if x.get('decision') == 'allow']
    removed = sum(len(x['selection']['removed']) for x in allowed)
    value = copy.deepcopy(value)
    value.update(version=VERSION, image_token_parity_claimed=False, source_vera_embeds_native=True,
        baseline_native_separate=True, final_wire_observed=bool(allowed), final_wire_native_removals=removed,
        final_wire_native_identity_preserved=bool(allowed) and removed == 0)
    value['passed'] = bool(value.get('passed') and allowed and removed == 0)
    return value


def worker(root, plan, job):
    if job['action'] != 'matched_continuation': raise ValueError('No model for reuse/blocked slots')
    validate_job(job); out = Path(job['output_path']); out.mkdir(parents=True, exist_ok=True)
    with (out / 'attempt-started.json').open('x') as f:
        json.dump({**identity(), 'at': time.time(), 'version': VERSION, 'job_id': job['job_id'], 'attempt': 1}, f)
    import capture_multimodal_prefix_v5 as capture
    from visual_transport_runtime_v4 import install as runtime_install
    from inline_visual_transport_v1 import install as inline_install
    spec = read(job['spec_path']); cfg = read(job['config_path']); env, _ = environment(ROOT, 'hermes', job['config_path'])
    selected_engine = engine if job['method'] == 'summary' else window_engine
    old_load = capture.load_images; old_write = selected_engine.write
    def load(row, directory):
        for item in spec['frozen_input_images']:
            if sha(item['path']) != item['sha256']: raise ValueError('Original image changed before staging')
        result = old_load({**row, 'image': [x['path'] for x in spec['frozen_input_images']]}, directory)
        save(directory / 'source-input-reuse.json', {'source_input_sha256': [x['sha256'] for x in spec['frozen_input_images']],
            'remote_downloads': 0, 'source_native_root': spec['source_native_root']})
        return result
    def write(path, value):
        if Path(path).name == 'compression-control.json': value = annotate(out, value)
        elif Path(path).name == 'result.json' and 'control_gate' in value:
            value = {**value, 'control_gate': annotate(out, value['control_gate'])}
            if value['status'] == 'completed' and not value['control_gate']['passed']:
                value.update(status='budget_infeasible', error_type='FinalWireNativeIntegrity')
        return old_write(path, value)
    policy = {**cfg['transport_runtime_policy'], 'write_seconds': 300., 'stream_seconds': 630.}
    h1 = runtime_install(policy, out / 'metrics', approved_base_url=env['TOKENHUB_BASE_URL'],
        route_policy=cfg['model_route_policy'], worker_key=job['job_id'], deadline_seconds=3600,
        gateway_proxy=cfg['gateway_proxy'])
    h2 = inline_install(out / 'metrics', rendered_registry=set(), approved_base_url=env['TOKENHUB_BASE_URL'])
    try:
        with patch.object(capture, 'load_images', load), patch.object(selected_engine, 'write', write), \
                patch.object(sys, 'argv', [sys.argv[0], '--spec', job['spec_path'], '--out', str(out), '--live']):
            selected_engine.run(spec, out)
    finally:
        h2['uninstall'](); h1['uninstall']()
    result = read(out / 'result.json') if (out / 'result.json').exists() else {}
    convo = read(out / 'conversation.json') if (out / 'conversation.json').exists() else {}
    final = convo.get('final_response') or ''
    save(out / 'native-result.json', {'version': VERSION,
        'status': 'completed' if result.get('status') == 'completed' and final else 'failed',
        'final': {'text': final}, 'source_controlled_status': result.get('status'),
        'error_type': result.get('error_type'), 'job_id': job['job_id'],
        'control_gate': result.get('control_gate'), 'source_result_sha256': job['source_result_sha256'],
        'spec_sha256': job['spec_sha256'], 'image_token_parity_claimed': False,
        'single_intervention': True, 'formal_full_benchmark_completed': False})


def process_group_exists(pid):
    try: os.killpg(pid, 0); return True
    except ProcessLookupError: return False


def reap(process, *, timed_out=False):
    if timed_out or process.poll() is not None and process_group_exists(process.pid):
        try: os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try: process.wait(timeout=2)
        except subprocess.TimeoutExpired: pass
        if process_group_exists(process.pid):
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
    process.wait()
    until = time.monotonic() + 5
    while process_group_exists(process.pid) and time.monotonic() < until: time.sleep(.05)
    return not process_group_exists(process.pid)


def terminal(job, out, *, process=None, elapsed=0, timeout=False, cleanup=True, action=None):
    path = out / 'terminal.json'
    if path.exists(): return read(path)
    result = read(out / 'native-result.json') if (out / 'native-result.json').exists() else {}
    status = action or ('timeout' if timeout else result.get('status', 'failed'))
    row = {'version': VERSION, 'job_id': job['job_id'], 'question_id': job['question_id'], 'repeat': job['repeat'],
        'method': job['method'], 'status': status, 'source_status': job.get('source_status'),
        'exit_code': process.returncode if process else None, 'elapsed_seconds': elapsed,
        'native_cleanup_confirmed': cleanup, 'new_attempts': int(process is not None),
        'will_retry': False, 'source_result_path': job['source_result_path'],
        'source_result_sha256': job['source_result_sha256'], 'reason': job.get('reason'),
        'finished_at_unix': time.time()}
    immutable(path, row); return row


def canary_gate_valid(job,gate):
    target=read(job['target_path']);actual=gate.get('first_actual_prompt_tokens');expected=target['source_first_post_prompt_tokens']
    return (gate.get('passed') is True and gate.get('native_identity_verified') is True
        and gate.get('final_wire_native_identity_preserved') is True
        and gate.get('prefix_sha256')==job['prefix_sha256']
        and gate.get('native_hashes')==target['baseline_native_hashes']
        and isinstance(actual,int) and math.ceil(expected*.98)<=actual<=math.floor(expected*1.02))


def run_controller(root, plan, method, *, concurrency=16, popen=subprocess.Popen, clock=time.monotonic):
    if method not in METHODS or concurrency != 16: raise ValueError('Each method uses exactly16 concurrency')
    cell = root / 'cells' / method; cell.mkdir(parents=True, exist_ok=True)
    lock = (cell / 'controller.lock').open('a'); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    jobs = [j for j in plan['jobs'] if j['method'] == method]
    pending = []; unresolved = []; active = {}; stopped = False
    prior_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    def stop(*unused):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    service = {**identity(), 'at': time.time(), 'version': VERSION, 'method': method,
        'concurrency': concurrency, 'plan_sha256': sha(root / 'plan.json')}
    immutable(cell / 'generations' / str(time.time_ns()) / 'service.json', service)
    for job in jobs:
        out = Path(job['output_path'])
        if (out / 'terminal.json').exists(): continue
        if (out / 'dispatch.json').exists() or (out / 'attempt-started.json').exists():
            unresolved.append(job['job_id']); continue
        if job['action'] != 'matched_continuation':
            out.mkdir(parents=True, exist_ok=True); terminal(job, out, action=job['action']); continue
        pending.append(job)
    env, _ = environment(ROOT, 'hermes', root / 'config.json')
    failed = None
    canary_id=plan.get('canary_job_id'); released=not bool(canary_id)
    try:
        while pending or active:
            stopped = stopped or (root / 'STOP').exists() or (cell / 'STOP').exists() or time.time() >= plan['stop_new_at_unix']
            for jid, item in list(active.items()):
                process, job, out, begin, log = item; elapsed = clock() - begin
                timeout = elapsed >= 3600
                if process.poll() is not None or timeout:
                    clean = reap(process, timed_out=timeout); log.close()
                    terminal(job, out, process=process, elapsed=elapsed, timeout=timeout, cleanup=clean)
                    if not clean: unresolved.append(jid)
                    del active[jid]
            if canary_id and not released:
                canary=next(j for j in jobs if j['job_id']==canary_id);cdir=Path(canary['output_path']);gate_path=cdir/'compression-control.json'
                gate=read(gate_path) if gate_path.exists() else {}
                if gate and canary_gate_valid(canary,gate):
                    immutable(cell/'canary-release.json',{'version':VERSION,'canary_job_id':canary_id,'at':time.time(),
                        'plan_sha256':sha(root/'plan.json'),'spec_sha256':canary['spec_sha256'],'gate_snapshot':gate})
                    released=True
                elif (cdir/'terminal.json').exists():stopped=True
            dispatch_limit=concurrency if released else 1
            while pending and not stopped and len(active) < dispatch_limit:
                job = pending.pop(0); out = Path(job['output_path']); out.mkdir(parents=True, exist_ok=True)
                claim = out / 'dispatch.json'
                if claim.exists() or (out / 'attempt-started.json').exists() or (out / 'terminal.json').exists():
                    unresolved.append(job['job_id']); continue
                immutable(claim, {**identity(), 'at': time.time(), 'job_id': job['job_id'],
                    'attempt': 1, 'dispatch_reserved_before_spawn': True})
                log = (out / 'worker.log').open('a')
                command = [python_for(ROOT), str(ROOT / 'scripts/network_entry_v13.py'), '--target', str(Path(__file__).resolve()),
                    '--root', str(root), '--worker-job', job['job_id'], '--live']
                try:
                    process = popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                except BaseException:
                    log.close()
                    raise
                # Register ownership before any further AFS write can fail.
                active[job['job_id']] = (process, job, out, clock(), log)
                save(out / 'worker-process.json', {'pid': process.pid, 'started_at': time.time(), 'job_id': job['job_id']})
            save(cell / 'status.json', {**service, 'at': time.time(), 'active': len(active),
                'active_job_ids': list(active), 'canary_released':released,'canary_job_id':canary_id, 'pending': len(pending), 'stopping': stopped,
                'unknown_prior_claims': unresolved, 'finished': False})
            if stopped and not active: break
            time.sleep(2)
    except BaseException as error:
        failed = type(error).__name__
        raise
    finally:
        for jid, (process, job, out, begin, log) in list(active.items()):
            try: process.wait(timeout=max(.01, 3600 - (clock() - begin)))
            except subprocess.TimeoutExpired: pass
            timeout = clock() - begin >= 3600
            clean = reap(process, timed_out=timeout); log.close()
            terminal(job, out, process=process, elapsed=clock()-begin, timeout=timeout, cleanup=clean)
            if not clean: unresolved.append(jid)
        save(cell / 'status.json', {**service, 'at': time.time(), 'active': 0, 'pending': len(pending),
            'unknown_prior_claims': unresolved, 'finished': True, 'drained': not bool(unresolved),
            'controller_error_type': failed, 'will_retry': False})
        lock.close()
        for sig, handler in prior_signals.items(): signal.signal(sig, handler)


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--root', type=Path, default=DEFAULT)
    p.add_argument('--prepare', action='store_true'); p.add_argument('--cohort', type=Path); p.add_argument('--pending-manifest',type=Path)
    p.add_argument('--method', choices=METHODS); p.add_argument('--concurrency', type=int, default=16)
    p.add_argument('--worker-job'); p.add_argument('--live', action='store_true')
    args = p.parse_args(); root = args.root.resolve()
    if args.prepare:
        if args.live or not args.cohort or not args.pending_manifest: raise ValueError('Preparation requires cohort and cannot be live')
        plan = prepare(root, args.cohort, args.pending_manifest)
    else: plan = read(root / 'plan.json')
    validate_plan(root, plan, deep=not args.live)
    if not args.live:
        print(json.dumps({'version': VERSION, 'model_calls': 0, 'cohort_slots': plan['cohort_slots'],
            'planned': len(plan['jobs']), 'runnable': sum(j['action']=='matched_continuation' for j in plan['jobs']),
            'no_intervention_reuse': sum(j['action']=='no_compression_reuse' for j in plan['jobs']),
            'blocked': sum(j['action']=='blocked' for j in plan['jobs'])})); return
    if args.worker_job:
        matches = [j for j in plan['jobs'] if j['job_id'] == args.worker_job]
        if len(matches) != 1: raise ValueError('Unlisted worker slot')
        worker(root, plan, matches[0]); return
    run_controller(root, plan, args.method, concurrency=args.concurrency)


if __name__ == '__main__': main()
