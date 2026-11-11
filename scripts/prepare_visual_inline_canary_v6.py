"""Prepare an eight-trial failure-only canary without launching model calls."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from lab import ROOT
from prepare_mmbc100_campaign import read, sha, immutable, immutable_json
from prepare_visual_hosted_retry_v1 import VERSION, load_validate
from prepare_visual_hosted_retry_v2 import drained, source_closure

SOURCE = ROOT / 'outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v5'
DEST = ROOT / 'outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v6-canary'
CELLS = ('bc_hermes', 'bc_dsh', 'mmbc_vera', 'mmbc_vanilla',
         'rq3_scale_0750', 'rq3_scale_1000', 'controlled_bc', 'controlled_mmbc')
NEW = ('prepare_visual_inline_canary_v6.py', 'launch_visual_inline_canary_v6.py',
       'run_visual_inline_canary_v6.py', 'run_visual_inline_canary_trial_v6.py',
       'hermes_visual_inline_retry_worker_v4.py', 'controlled_visual_inline_worker_v4.py',
       'visual_transport_runtime_v4.py', 'inline_route_contract_v2.py',
       'dsh_inline_bc_worker_v5.py', 'dsh_inline_bc_worker_v4.py',
       'dsh_hosted_wire_v3.mjs')


def select_failed(source, plan):
    """Selection uses execution status only, retaining every completed attempt."""
    for old in plan['jobs']:
        result = source / 'jobs' / old['job_id'] / 'attempts/attempt_001/result.json'
        if not result.exists() or read(result).get('status') != 'timeout':
            continue
        suffix = '/jobs/' + old['job_id'] + '/attempts/attempt_001/result.json'
        ancestors = [Path(p) for p in plan['definition']['source_results_sha256'] if p.endswith(suffix)]
        if any(read(p).get('status') == 'completed' for p in ancestors):
            continue
        value = read(result)
        if value.get('slot_released') is not True or value.get('unconfirmed_child_termination') != []:
            raise ValueError('Selected predecessor native cleanup is unconfirmed')
        return old, result, ancestors
    raise ValueError('No eligible timeout without a historical completion: ' + source.name)


def proposal():
    rows = []
    for cell in CELLS:
        source = SOURCE / 'cells' / cell
        plan, _ = load_validate(source)
        drained(source, plan)
        old, result, ancestors = select_failed(source, plan)
        rows.append({'cell': cell, 'job_id': old['job_id'], 'question_id': old['question_id'],
                     'repeat': old['repeat'], 'harness': old['harness'],
                     'timeout_seconds': old['timeout_seconds'], 'predecessor_status': 'timeout',
                     'result_path': str(result), 'result_sha256': sha(result),
                     'ancestor_result_bindings': {str(p): sha(p) for p in ancestors}})
    return {'version': 'visual-inline-canary-v6', 'model_calls': 0,
            'selection_uses_answers': False, 'retains_all_completed': True,
            'trial_count': len(rows), 'records': rows}


def freeze(settings=None, new_sources=NEW):
    allowed = {'transport_runtime_version', 'gateway_proxy', 'dsh_buffered_watchdog_version'}
    root_section = read(ROOT / 'configs/experiment.json')['visual_inline_repair_v6']
    required = {'canary_trials': 8, 'concurrency_per_cell': 16, 'compression_image_upload': False,
                'retain_recent_images': 10, 'scientific_output_budget_changed': False,
                'task_deadlines_changed': False, 'full_recovery_requires_canary_review': True}
    if any(root_section.get(key) != value for key, value in required.items()):
        raise ValueError('Root canary scope differs from the reviewed eight-trial contract')
    configured = {key: root_section[key] for key in allowed}
    if settings is None:
        settings = configured
    if set(settings) - allowed:
        raise ValueError('Canary transport settings cannot modify scientific budgets or deadlines')
    if settings != configured:
        raise ValueError('Canary transport settings must match configs/experiment.json visual_inline_repair_v6')
    if settings.get('transport_runtime_version') != 'visual-transport-runtime-v4' or settings.get('gateway_proxy') != 'http://10.120.0.246:7890':
        raise ValueError('Explicit approved V6 proxy/runtime required')
    selected = proposal()
    section_sha = hashlib.sha256(json.dumps(root_section, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    snapshot = DEST / 'repair-settings-source.json'
    immutable_json(snapshot, {'source': 'configs/experiment.json', 'section': 'visual_inline_repair_v6',
                             'section_sha256': section_sha, 'settings': root_section})
    for row in selected['records']:
        cell = row['cell']; source = SOURCE / 'cells' / cell; dest = DEST / 'cells' / cell
        plan, manifest = load_validate(source)
        old = next(j for j in plan['jobs'] if j['job_id'] == row['job_id'])
        cfg = copy.deepcopy(read(source / 'experiment.json')); cfg.update(copy.deepcopy(settings))
        immutable_json(dest / 'experiment.json', cfg)
        immutable(dest / 'cohort.jsonl', (source / 'cohort.jsonl').read_bytes())
        if (source / 'image-assets').exists():
            for path in (source / 'image-assets').rglob('*'):
                if path.is_file(): immutable(dest / path.relative_to(source), path.read_bytes())
        job = copy.deepcopy(old); job.update(copy.deepcopy(settings))
        job.update(config_path=str(dest / 'experiment.json'), config_sha256=sha(dest / 'experiment.json'))
        bindings = {**plan['definition']['source_results_sha256'], **drained(source, plan),
                    str(source / 'plan.json'): sha(source / 'plan.json'), str(snapshot): sha(snapshot)}
        definition = {**plan['definition'], 'planned_runs': 1,
                      'config_sha256': sha(dest / 'experiment.json'),
                      'implementation_sha256': {**plan['definition']['implementation_sha256'], **source_closure(new_sources)},
                      'source_results_sha256': bindings, 'predecessor_root': str(source),
                      'root_settings_section_sha256': section_sha,
                      'canary_version': 'visual-inline-canary-v6', **copy.deepcopy(settings)}
        immutable_json(dest / 'selection.json', row)
        immutable_json(dest / 'plan.json', {'definition': definition, 'jobs': [job]})
        immutable_json(dest / 'campaign-manifest.json', {'version': VERSION, 'cell': cell,
                       'root': str(dest), 'harness': manifest['harness'], 'planned_runs': 1,
                       'root_settings_section_sha256': section_sha,
                       'plan_sha256': sha(dest / 'plan.json'), 'canary_version': 'visual-inline-canary-v6'})
        load_validate(dest)
    immutable_json(DEST / 'inventory.json', {**selected, 'version': VERSION,
                   'canary_version': 'visual-inline-canary-v6',
                   'cells': [read(DEST / 'cells' / c / 'campaign-manifest.json') for c in CELLS],
                   'concurrency_per_cell': 16, 'live_release_required': True,
                   'maximum_total_new_trials': 8})
    return selected


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--proposal-out', type=Path, required=True)
    a = p.parse_args()
    immutable_json(a.proposal_out, proposal())
    print('Prepared failure-only eight-trial proposal; no source freeze or model calls.')


if __name__ == '__main__': main()
