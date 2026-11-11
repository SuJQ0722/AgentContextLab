"""Freeze one supplementary controlled retry after a zero-model input failure."""
import copy
from prepare_visual_inline_canary_v6 import DEST as V6
from prepare_visual_hosted_retry_v1 import VERSION, load_validate
from prepare_visual_hosted_retry_v2 import drained, source_closure
from prepare_mmbc100_campaign import read, sha, immutable, immutable_json
from controlled_frozen_input_reuse_v1 import resolve_inputs, VERSION as REUSE

DEST = V6 / 'cells/input-reuse-v1'
NEW = ('prepare_controlled_input_reuse_canary_v1.py', 'controlled_frozen_input_reuse_v1.py',
       'controlled_visual_inline_worker_v5.py', 'run_controlled_input_reuse_trial_v1.py',
       'run_controlled_input_reuse_canary_v1.py')


def prepare():
    source = V6 / 'cells/controlled_mmbc'; root = DEST / 'cells/controlled_mmbc'
    plan, _ = load_validate(source); old = plan['jobs'][0]
    attempt = source / 'jobs' / old['job_id'] / 'attempts/attempt_001'
    result = read(attempt / 'result.json'); native = read(attempt / 'native/native-result.json')
    if result.get('status') != 'failed' or native.get('error_type') != 'URLError':
        raise ValueError('Only the documented input failure is eligible')
    metrics = attempt / 'native/metrics'
    if any((metrics / name).exists() for name in ('transport-phases-v3.jsonl', 'calls.jsonl', 'call-starts.jsonl')):
        raise ValueError('Input failure must have no model request evidence')
    spec = read(old['controlled_spec_path']); ledger_path, ledger = resolve_inputs(spec)
    cfg = read(source / 'experiment.json')
    immutable_json(root / 'experiment.json', cfg)
    immutable(root / 'cohort.jsonl', (source / 'cohort.jsonl').read_bytes())
    job = copy.deepcopy(old); job.update(config_path=str(root / 'experiment.json'),
        config_sha256=sha(root / 'experiment.json'), controlled_input_reuse_version=REUSE)
    bindings = {**plan['definition']['source_results_sha256'], **drained(source, plan),
                str(source / 'plan.json'): sha(source / 'plan.json'), str(ledger_path): sha(ledger_path)}
    bindings.update({item['path']: item['sha256'] for item in ledger})
    definition = {**plan['definition'], 'config_sha256': sha(root / 'experiment.json'),
        'source_results_sha256': bindings, 'predecessor_root': str(source),
        'controlled_input_reuse_version': REUSE,
        'implementation_sha256': {**plan['definition']['implementation_sha256'], **source_closure(NEW)}}
    immutable_json(root / 'plan.json', {'definition': definition, 'jobs': [job]})
    manifest = {'version': VERSION, 'cell': 'controlled_mmbc', 'root': str(root), 'harness': 'hermes',
                'planned_runs': 1, 'plan_sha256': sha(root / 'plan.json'), 'controlled_input_reuse_version': REUSE}
    immutable_json(root / 'campaign-manifest.json', manifest)
    immutable_json(DEST / 'inventory.json', {'version': VERSION, 'cells': [manifest],
        'controlled_input_reuse_version': REUSE, 'maximum_total_new_trials': 1,
        'retain_all_completed': True, 'predecessor_preserved': True, 'concurrency_per_cell': 16})
    load_validate(root)
    return root


if __name__ == '__main__': print(prepare())
