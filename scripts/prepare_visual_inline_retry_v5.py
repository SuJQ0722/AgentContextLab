"""Resume drained failures with direct images and the four authorized routes."""
import argparse
import copy
from pathlib import Path

from lab import ROOT
from prepare_mmbc100_campaign import read, sha, immutable, immutable_json
from prepare_visual_hosted_retry_v1 import VERSION, load_validate
from prepare_visual_hosted_retry_v2 import drained, source_closure

SOURCE = ROOT / 'outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v4'
DEST = ROOT / 'outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v5'
ROUTES = ['deepseek-v4.1-flash-1017/' + suffix for suffix in
          ('huoshan/huoshan', 'zijian/sfb', 'huoshan/sfc', 'zijian/sfc')]
NEW = (
    'prepare_visual_inline_retry_v5.py', 'inline_visual_transport_v1.py', 'page_window_renderer_v1.py',
    'visual_transport_runtime_v3.py', 'recent_ten_hosted_selection_v1.py',
    'run_visual_hosted_retry_v3.py', 'run_visual_hosted_retry_trial_v3.py',
    'hermes_visual_hosted_retry_worker_v3.py', 'controlled_hosted_visual_worker_v3.py',
    'dsh_hosted_bc_worker_v3.py', 'dsh_hosted_wire_v3.mjs',
    'dsh_inline_transport_bridge_v1.py', 'preflight_dsh_hosted_dispatcher_v3.mjs',
    'bootstrap_visual_hosted_transport_v5.py', 'run_visual_hosted_transport_v5.py',
    'provision_visual_hosted_transport_v5.py', 'monitor_visual_hosted_transport_v5.py',
    'preflight_dsh_transport_v5.py',
)
SETTINGS = {'image_transport': 'inline-recent-ten-chunked-v1',
            'transport_delivery_version': 'inline-direct-v1',
            'transport_runtime_version': 'visual-transport-runtime-v3',
            'model_route_policy': 'four-route-rotation-v1', 'approved_model_routes': ROUTES,
            'compression_image_upload': False, 'request_body_chunk_bytes': 65536,
            'max_inline_body_bytes': 32 * 1024 * 1024}


def prepare_cell(cell):
    source, dest = SOURCE / 'cells' / cell, DEST / 'cells' / cell
    if (dest / 'campaign-manifest.json').exists():
        load_validate(dest)
        return read(dest / 'campaign-manifest.json')
    plan, manifest = load_validate(source)
    if not (source / 'STOP').exists():
        raise RuntimeError('Predecessor dispatch must be stopped')
    bindings = {**plan['definition']['source_results_sha256'], **drained(source, plan),
                str(source / 'plan.json'): sha(source / 'plan.json')}
    cfg = read(source / 'experiment.json')
    cfg.pop('hosted_runtime_version', None)
    cfg.update(copy.deepcopy(SETTINGS))
    immutable_json(dest / 'experiment.json', cfg)
    immutable(dest / 'cohort.jsonl', (source / 'cohort.jsonl').read_bytes())
    if (source / 'image-assets').exists():
        for path in (source / 'image-assets').rglob('*'):
            if path.is_file():
                immutable(dest / path.relative_to(source), path.read_bytes())
    records, jobs = [], []
    for old in plan['jobs']:
        result = source / 'jobs' / old['job_id'] / 'attempts/attempt_001/result.json'
        status = read(result)['status'] if result.exists() else 'pending_never_claimed'
        selected = status != 'completed'
        records.append({'job_id': old['job_id'], 'predecessor_status': status,
                        'selected': selected, 'result_path': str(result) if result.exists() else None})
        if selected:
            job = copy.deepcopy(old)
            job.pop('hosted_runtime_version', None)
            job.update(copy.deepcopy(SETTINGS))
            job.update(config_path=str(dest / 'experiment.json'), config_sha256=sha(dest / 'experiment.json'))
            jobs.append(job)
    definition = {**plan['definition'], 'planned_runs': len(jobs),
                  'config_sha256': sha(dest / 'experiment.json'),
                  'implementation_sha256': {**plan['definition']['implementation_sha256'], **source_closure(NEW)},
                  'source_results_sha256': bindings, 'predecessor_root': str(source),
                  'selection_uses_answers': False, **copy.deepcopy(SETTINGS)}
    definition.pop('hosted_runtime_version', None)
    immutable_json(dest / 'selection.json', {'records': records, 'retain_all_completed': True,
                                           'old_records_preserved': True, 'image_host_used': False})
    immutable_json(dest / 'plan.json', {'definition': definition, 'jobs': jobs})
    result = {'version': VERSION, 'cell': cell, 'root': str(dest), 'harness': manifest['harness'],
              'planned_runs': len(jobs), 'retained_completed_this_wave': len(records) - len(jobs),
              'plan_sha256': sha(dest / 'plan.json'), **copy.deepcopy(SETTINGS)}
    immutable_json(dest / 'campaign-manifest.json', result)
    load_validate(dest)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cells', nargs='+')
    a = p.parse_args()
    names = [cell['cell'] for cell in read(SOURCE / 'inventory.json')['cells']]
    selected = a.cells or names
    if len(selected) != len(set(selected)) or not set(selected) <= set(names):
        p.error('Unique predecessor cell names required')
    for cell in selected:
        result = prepare_cell(cell)
        print(cell, result['planned_runs'], flush=True)
    if all((DEST / 'cells' / cell / 'campaign-manifest.json').exists() for cell in names):
        immutable_json(DEST / 'inventory.json', {'version': VERSION,
            'cells': [read(DEST / 'cells' / c / 'campaign-manifest.json') for c in names],
            'concurrency_per_cell': 16, 'global_cap': None, **copy.deepcopy(SETTINGS)})


if __name__ == '__main__':
    main()
