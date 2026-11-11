"""Freeze two-hour operational recovery of the existing V5 slots only; zero API calls."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from lab import ROOT
from prepare_mmbc100_campaign import read, sha, immutable, immutable_json
from prepare_visual_hosted_retry_v1 import VERSION, load_validate
from prepare_visual_hosted_retry_v2 import drained, source_closure
from controlled_frozen_input_reuse_v1 import resolve_inputs, VERSION as INPUT_REUSE

BASE = ROOT / 'outputs/campaigns/visual-hosted-failure-retry-v1/cells'
SOURCE = BASE / 'transport-v5'
DEST = BASE / 'transport-v7-two-hour'
PROTOCOL = 'visual-inline-two-hour-v7'
TIMEOUT = 7200
CELLS = ('bc_hermes', 'bc_dsh', 'rq3_scale_0000', 'rq3_scale_0250',
         'rq3_scale_0500', 'rq3_scale_0700', 'rq3_scale_0750', 'rq3_scale_0800',
         'rq3_scale_1000', 'mmbc_vera', 'mmbc_vanilla', 'controlled_bc', 'controlled_mmbc')
NEW = ('prepare_visual_inline_two_hour_v7.py', 'run_visual_inline_two_hour_v7.py',
       'run_visual_inline_two_hour_trial_v7.py', 'hermes_visual_inline_retry_worker_v4.py',
       'controlled_visual_inline_worker_v5.py', 'visual_transport_runtime_v4.py',
       'dsh_inline_bc_worker_v6.py', 'dsh_hosted_wire_v4.mjs',
       'preflight_dsh_transport_v6.py', 'preflight_dsh_hosted_dispatcher_v4.mjs',
       'bootstrap_visual_inline_two_hour_v7.py', 'run_visual_inline_transport_v7.py',
       'provision_visual_inline_two_hour_v7.py', 'monitor_visual_inline_two_hour_v7.py',
       'warm_visual_inline_worker_v7.py', 'launch_visual_inline_two_hour_local_v7.py')


def successor_roots(cell):
    candidates = [BASE / 'dsh-cli-separator-v1/cells' / cell,
                  BASE / 'transport-v6-canary/cells' / cell,
                  BASE / 'transport-v6-canary/cells/input-reuse-v1/cells' / cell]
    return [p for p in candidates if (p / 'plan.json').exists()]


def choose(records):
    """Never examine answers or grades. Any completed execution is retained."""
    if any(r['status'] == 'completed' for r in records):
        return False, 'historical_completed_retained'
    if not records:
        return False, 'missing_execution_evidence'
    if records[-1]['status'] in ('failed', 'timeout'):
        return True, 'latest_execution_failed_or_timeout'
    return False, 'latest_execution_not_retryable'


def settings():
    section = read(ROOT / 'configs/experiment.json')['visual_inline_two_hour_v7']
    expected = {'timeout_seconds': TIMEOUT, 'transport_runtime_version': 'visual-transport-runtime-v4',
        'gateway_proxy': 'http://10.120.0.246:7890', 'dsh_buffered_watchdog_version': 'dsh-buffered-sdk-watchdog-v2',
        'concurrency_per_cell': 16, 'global_cap': None, 'compression_image_upload': False,
        'retain_recent_images': 10, 'max_output_tokens': 8192, 'excluded_benchmarks': ['agenticdatabench'],
        'http_attempt_deadline_seconds': 300, 'route_policy': 'four-route-rotation-v1'}
    if any(section.get(k) != v for k, v in expected.items()):
        raise ValueError('Root V7 settings differ from approved deadline-only recovery contract')
    return section


def inspect_cell(cell):
    if cell not in CELLS:
        raise ValueError('Cell outside fixed thirteen-cell scope')
    source = SOURCE / 'cells' / cell
    plan, manifest = load_validate(source)
    bindings = {**plan['definition']['source_results_sha256'], **drained(source, plan),
                str(source / 'plan.json'): sha(source / 'plan.json')}
    successors = []
    for path in successor_roots(cell):
        successor, _ = load_validate(path)
        if successor['definition'].get('selection_uses_answers') is not False:
            raise ValueError('Answer-selected successor prohibited')
        bindings.update(drained(path, successor))
        bindings[str(path / 'plan.json')] = sha(path / 'plan.json')
        successors.append((path, {j['job_id']: j for j in successor['jobs']}))
    records = []
    for job in plan['jobs']:
        suffix = '/jobs/' + job['job_id'] + '/attempts/attempt_001/result.json'
        paths = [Path(p) for p in plan['definition']['source_results_sha256'] if p.endswith(suffix)]
        paths.append(source / 'jobs' / job['job_id'] / 'attempts/attempt_001/result.json')
        paths.extend(path / 'jobs' / job['job_id'] / 'attempts/attempt_001/result.json'
                     for path, jobs in successors if job['job_id'] in jobs)
        lineage = []
        for path in dict.fromkeys(paths):
            if not path.exists():
                raise ValueError('Missing terminal source result: ' + str(path))
            value = read(path)
            if value.get('slot_released') is not True or value.get('unconfirmed_child_termination') != []:
                raise ValueError('Source native cleanup unconfirmed: ' + str(path))
            if any(value.get(k) != job[k] for k in ('job_id', 'question_id', 'repeat')):
                raise ValueError('Source trajectory identity changed')
            bindings[str(path)] = sha(path)
            lineage.append({'path': str(path), 'sha256': bindings[str(path)], 'status': value['status']})
        selected, reason = choose(lineage)
        assets = []
        if selected and job.get('controlled_spec_path'):
            cp = Path(job['controlled_spec_path'])
            if sha(cp) != job['controlled_spec_sha256']:
                raise ValueError('Controlled source spec changed')
            bindings[str(cp)] = sha(cp)
            ledger_path, ledger = resolve_inputs(read(cp))
            bindings[str(ledger_path)] = sha(ledger_path)
            for item in ledger:
                bindings[item['path']] = item['sha256']
            assets = [{'path': item['path'], 'sha256': item['sha256']} for item in ledger]
        records.append({'job_id': job['job_id'], 'question_id': job['question_id'], 'repeat': job['repeat'],
            'selected': selected, 'selection_reason': reason, 'lineage': lineage,
            'validated_original_input_assets': assets})
    return plan, manifest, bindings, records


def proposal(cells=CELLS):
    section = settings(); result = []
    for cell in cells:
        plan, manifest, bindings, records = inspect_cell(cell)
        result.append({'cell': cell, 'harness': manifest['harness'], 'original_v5_slots': len(plan['jobs']),
            'planned_runs': sum(r['selected'] for r in records),
            'retained_completed': sum(r['selection_reason'] == 'historical_completed_retained' for r in records),
            'not_retryable': sum(not r['selected'] and r['selection_reason'] != 'historical_completed_retained' for r in records),
            'records': records, 'source_results_sha256': bindings})
    return {'version': PROTOCOL, 'model_calls': 0, 'timeout_seconds': TIMEOUT,
        'selection_uses_answers': False, 'existing_v5_scope_only': True,
        'excluded_benchmarks': section['excluded_benchmarks'], 'cells': result}


def prepare_cell(cell, implementation):
    dest = DEST / 'cells' / cell
    if (dest / 'campaign-manifest.json').exists():
        load_validate(dest)
        return read(dest / 'campaign-manifest.json')
    section = settings(); plan, old_manifest, bindings, records = inspect_cell(cell)
    section_sha = hashlib.sha256(json.dumps(section, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    snapshot = DEST / 'repair-settings-source.json'
    immutable_json(snapshot, {'source': 'configs/experiment.json', 'section': 'visual_inline_two_hour_v7',
        'section_sha256': section_sha, 'settings': section})
    bindings[str(snapshot)] = sha(snapshot)
    source = SOURCE / 'cells' / cell
    cfg = copy.deepcopy(read(source / 'experiment.json'))
    overrides = {k: section[k] for k in ('transport_runtime_version', 'gateway_proxy', 'dsh_buffered_watchdog_version', 'timeout_seconds')}
    cfg.update(overrides)
    if cfg['max_output_tokens'] != 8192 or cfg['transport_runtime_policy']['stream_seconds'] != 300:
        raise ValueError('Output budget or single HTTP wall changed')
    for name in ('bc100', 'bc100_campaign', 'mmbc100_campaign', 'mmbc_vanilla_campaign'):
        if isinstance(cfg.get(name), dict):
            cfg[name]['timeout_seconds'] = TIMEOUT
    immutable_json(dest / 'experiment.json', cfg)
    immutable(dest / 'cohort.jsonl', (source / 'cohort.jsonl').read_bytes())
    if (source / 'image-assets').exists():
        for path in (source / 'image-assets').rglob('*'):
            if path.is_file():
                immutable(dest / path.relative_to(source), path.read_bytes())
    selected = {r['job_id'] for r in records if r['selected']}; jobs = []
    for old in plan['jobs']:
        if old['job_id'] not in selected:
            continue
        job = copy.deepcopy(old); job.update(overrides)
        job.update(config_path=str(dest / 'experiment.json'), config_sha256=sha(dest / 'experiment.json'),
                   two_hour_recovery_version=PROTOCOL)
        if job.get('controlled_spec_path'):
            original = Path(job['controlled_spec_path']); controlled = read(original)
            controlled.update(timeout_seconds=TIMEOUT, config_path=str(dest / 'experiment.json'))
            copied = dest / 'controlled-specs' / (hashlib.sha256(job['job_id'].encode()).hexdigest() + '.json')
            immutable_json(copied, controlled)
            job.update(controlled_spec_path=str(copied), controlled_spec_sha256=sha(copied),
                original_controlled_spec_path=str(original), original_controlled_spec_sha256=sha(original),
                controlled_input_reuse_version=INPUT_REUSE)
            bindings[str(copied)] = sha(copied)
        jobs.append(job)
    definition = {**plan['definition'], 'planned_runs': len(jobs), 'config_sha256': sha(dest / 'experiment.json'),
        'implementation_sha256': {**plan['definition']['implementation_sha256'], **implementation},
        'source_results_sha256': bindings, 'predecessor_root': str(source),
        'two_hour_recovery_version': PROTOCOL, 'timeout_seconds': TIMEOUT,
        'root_settings_section_sha256': section_sha, 'selection_uses_answers': False,
        'retain_any_historical_completed': True, 'existing_v5_scope_only': True}
    immutable_json(dest / 'selection.json', {'records': records, 'selection_uses_answers': False})
    immutable_json(dest / 'plan.json', {'definition': definition, 'jobs': jobs})
    manifest = {'version': VERSION, 'cell': cell, 'root': str(dest), 'harness': old_manifest['harness'],
        'planned_runs': len(jobs), 'retained_completed': sum(r['selection_reason'] == 'historical_completed_retained' for r in records),
        'timeout_seconds': TIMEOUT, 'two_hour_recovery_version': PROTOCOL, 'plan_sha256': sha(dest / 'plan.json')}
    immutable_json(dest / 'campaign-manifest.json', manifest)
    load_validate(dest)
    return manifest


def freeze(cells=CELLS):
    implementation = source_closure(NEW)
    for name in ('tests/test_visual_inline_two_hour_v7.py', 'tests/test_dsh_two_hour_v2.py',
                 'tests/test_visual_inline_cloud_v7.py'):
        implementation[name] = sha(ROOT / name)
    manifests = [prepare_cell(cell, implementation) for cell in cells]
    if tuple(cells) == CELLS:
        immutable_json(DEST / 'inventory.json', {'version': VERSION, 'two_hour_recovery_version': PROTOCOL,
            'cells': manifests, 'concurrency_per_cell': 16, 'global_cap': None,
            'timeout_seconds': TIMEOUT, 'selection_uses_answers': False, 'excluded_benchmarks': ['agenticdatabench']})
    return manifests


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cells', nargs='+', choices=CELLS)
    parser.add_argument('--proposal-out', type=Path)
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args(); cells = tuple(args.cells) if args.cells else CELLS
    if args.freeze:
        print(json.dumps(freeze(cells)))
    else:
        result = proposal(cells)
        if args.proposal_out:
            immutable_json(args.proposal_out, result)
        print(json.dumps([{k: c[k] for k in ('cell', 'original_v5_slots', 'planned_runs', 'retained_completed', 'not_retryable')} for c in result['cells']]))
