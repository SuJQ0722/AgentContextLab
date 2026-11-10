"""Freeze transport-v4 recovery only after each old controller has drained."""
import argparse
import ast
import copy
from pathlib import Path

from lab import ROOT
from prepare_mmbc100_campaign import read, sha, immutable, immutable_json
from prepare_visual_hosted_retry_v1 import DEFAULT, VERSION, load_validate

DEST = DEFAULT / 'cells/transport-v4'
NEW = (
    'prepare_visual_hosted_retry_v2.py', 'verified_hosted_images_v4.py',
    'run_visual_hosted_retry_v2.py', 'run_visual_hosted_retry_trial_v2.py',
    'hermes_visual_hosted_retry_worker_v2.py', 'dsh_hosted_bc_worker_v2.py',
    'dsh_hosted_wire_v2.mjs', 'dsh_hosted_transport_bridge_v2.py',
    'controlled_hosted_visual_worker_v2.py',
    'isolated_verified_image_host_v1.py', 'recent_ten_hosted_selection_v1.py',
    'bootstrap_visual_hosted_transport_v4.py', 'run_visual_hosted_transport_v4.py',
    'provision_visual_hosted_transport_v4.py', 'monitor_visual_hosted_transport_v4.py',
    'preflight_visual_hosted_transport_v4.py',
    'preflight_dsh_transport_v4.py',
)


def source_closure(names):
    """Bind local imports, including imports inside deferred runtime functions."""
    pending = [ROOT / 'scripts' / name for name in names]
    found = {}
    while pending:
        path = pending.pop()
        key = str(path.relative_to(ROOT))
        if key in found:
            continue
        found[key] = sha(path)
        if path.suffix != '.py':
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            modules = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            for module in modules:
                dependency = ROOT / 'scripts' / (module.split('.')[0] + '.py')
                if dependency.exists():
                    pending.append(dependency)
    return found


def copy_cache(source, dest):
    if source.exists():
        for path in source.rglob('*'):
            if path.is_file() and path.suffix not in ('.lock', '.tmp'):
                immutable(dest / path.relative_to(source), path.read_bytes(), private=True)


def drained(source, plan):
    evidence = {}
    for maintenance in (source / 'controllers').glob('*/*/maintenance.json'):
        exit_path = maintenance.parent / 'exit.json'
        if not exit_path.exists():
            raise RuntimeError('Controller still draining: ' + str(maintenance.parent))
        owner, final = read(maintenance), read(exit_path)
        if final.get('controller_id') != owner.get('controller_id') or final.get('drained') is not True:
            raise RuntimeError('Unconfirmed controller drain')
        evidence[str(exit_path)] = sha(exit_path)
    for job in plan['jobs']:
        directory = source / 'jobs' / job['job_id']
        result = directory / 'attempts/attempt_001/result.json'
        if (directory / 'claim').exists() and not result.exists():
            raise RuntimeError('Claim without confirmed result: ' + job['job_id'])
        if result.exists():
            value = read(result)
            if value.get('slot_released') is not True or value.get('unconfirmed_child_termination') != []:
                raise RuntimeError('Unconfirmed native cleanup: ' + job['job_id'])
            if value['status'] not in ('completed', 'failed', 'timeout', 'not_started'):
                raise RuntimeError('Unsupported predecessor status')
            evidence[str(result)] = sha(result)
    return evidence


def prepare_cell(cell):
    source, dest = DEFAULT / 'cells' / cell, DEST / 'cells' / cell
    if (dest / 'campaign-manifest.json').exists():
        load_validate(dest)
        return read(dest / 'campaign-manifest.json')
    plan, manifest = load_validate(source)
    # The old stop marker is required even for a cell which failed preflight.
    if not (source / 'STOP').exists():
        raise RuntimeError('Predecessor dispatch must be stopped explicitly')
    bindings = {**plan['definition']['source_results_sha256'], **drained(source, plan),
                str(source / 'plan.json'): sha(source / 'plan.json')}
    cfg = read(source / 'experiment.json')
    cfg.update(image_transport='verified-imgbb-url-v2', hosted_runtime_version='verified-hosted-images-v4')
    immutable_json(dest / 'experiment.json', cfg)
    immutable(dest / 'cohort.jsonl', (source / 'cohort.jsonl').read_bytes())
    if (source / 'image-assets').exists():
        for p in (source / 'image-assets').rglob('*'):
            if p.is_file():
                immutable(dest / p.relative_to(source), p.read_bytes())
    records, jobs = [], []
    for old in plan['jobs']:
        result = source / 'jobs' / old['job_id'] / 'attempts/attempt_001/result.json'
        state = read(result)['status'] if result.exists() else 'pending_never_claimed'
        selected = state != 'completed'
        records.append({'job_id': old['job_id'], 'predecessor_status': state, 'selected': selected,
                        'result_path': str(result) if result.exists() else None})
        if selected:
            job = copy.deepcopy(old)
            job.update(config_path=str(dest / 'experiment.json'), config_sha256=sha(dest / 'experiment.json'),
                       image_transport='verified-imgbb-url-v2', hosted_runtime_version='verified-hosted-images-v4')
            jobs.append(job)
            # Never pre-create an attempt directory: reservation creates it
            # exclusively. This wave's controlled/DSH failures had no upload
            # receipts; assert that rather than silently discarding any cache.
            attempt = Path('jobs') / old['job_id'] / 'attempts/attempt_001/native'
            if old.get('controlled_spec_path'):
                relative = attempt / 'hosted-image-cache'
                if list((source / relative / 'hosted').glob('*.upload.json')):
                    raise ValueError('Per-job receipt migration needs a separate cache namespace')
            elif old['harness'] == 'dsh':
                relative = attempt / 'visual_native' / old['question_id'] / 'workspace/metrics/hosted-image-cache'
                if list((source / relative / 'hosted').glob('*.upload.json')):
                    raise ValueError('Per-job receipt migration needs a separate cache namespace')
    # Copy immutable upload receipts and verified caches, not lock files. This
    # reuses uploads without removing failed-verification evidence from v1.
    copy_cache(source / 'hosted-image-cache', dest / 'hosted-image-cache')
    hashes = dict(plan['definition']['implementation_sha256'])
    hashes.update(source_closure(NEW))
    definition = {**plan['definition'], 'planned_runs': len(jobs),
                  'config_sha256': sha(dest / 'experiment.json'),
                  'implementation_sha256': hashes, 'source_results_sha256': bindings,
                  'hosted_runtime_version': 'verified-hosted-images-v4',
                  'predecessor_root': str(source), 'selection_uses_answers': False}
    immutable_json(dest / 'selection.json', {'records': records, 'retain_all_completed': True,
        'shared_cache_migrated': True, 'per_job_upload_receipts_found': False,
        'old_cache_records_preserved': True})
    immutable_json(dest / 'plan.json', {'definition': definition, 'jobs': jobs})
    result = {'version': VERSION, 'cell': cell, 'root': str(dest), 'harness': manifest['harness'],
              'planned_runs': len(jobs), 'retained_completed_this_wave': len(records) - len(jobs),
              'plan_sha256': sha(dest / 'plan.json'), 'hosted_runtime_version': 'verified-hosted-images-v4'}
    immutable_json(dest / 'campaign-manifest.json', result)
    load_validate(dest)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cells', nargs='+')
    a = p.parse_args()
    original = read(DEFAULT / 'inventory.json')['cells']
    names = [c['cell'] for c in original]
    selected = a.cells or names
    if len(selected) != len(set(selected)) or not set(selected) <= set(names):
        p.error('Unique original cell names required')
    for cell in selected:
        result = prepare_cell(cell)
        print(cell, result['planned_runs'], flush=True)
    if all((DEST / 'cells' / c / 'campaign-manifest.json').exists() for c in names):
        immutable_json(DEST / 'inventory.json', {'version': VERSION,
            'cells': [read(DEST / 'cells' / c / 'campaign-manifest.json') for c in names],
            'concurrency_per_cell': 16, 'global_cap': None,
            'hosted_runtime_version': 'verified-hosted-images-v4'})


if __name__ == '__main__':
    main()
