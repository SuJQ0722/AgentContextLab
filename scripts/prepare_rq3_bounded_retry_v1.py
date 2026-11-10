#!/usr/bin/env python3
"""Freeze RQ3 failure/timeout-only recovery under a new bounded renderer protocol."""
import argparse
import copy
import json
from pathlib import Path

from lab import ROOT
from prepare_mmbc100_campaign import sha, read, digest, immutable, immutable_json, implementation_hashes

VERSION = 'rq3-bounded-failure-retry-v1'
PROTOCOL = 'rq3-bounded-pages-v1'
SCALES = (0., .25, .5, .7, .75, .8, 1.)
SCALE_KEYS = tuple(f'scale_{round(s*1000):04d}' for s in SCALES)
DEFAULT_ROOT = ROOT / 'outputs/campaigns' / VERSION
SOURCE_REPORT = ROOT / 'outputs/grading/rq3-final-seven-v3'
PARENT = ROOT / 'outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3'
PRIVATE = ROOT / 'outputs/grading' / VERSION / 'private'
NEW_SOURCES = ('prepare_rq3_bounded_retry_v1.py', 'run_rq3_bounded_retry_v1.py',
    'run_rq3_bounded_retry_trial_v1.py', 'rq3_bounded_renderer_v2.py', 'hermes_bounded_rq3_worker_v1.py',
    'bounded_multimodal_renderer_v1.py', 'bounded_lossless_transport_v1.py', 'bounded_visual_request_guard_v1.py',
    'bootstrap_rq3_bounded_retry_v1.py')


def key(scale):
    if type(scale) not in (int, float) or scale not in SCALES: raise ValueError('Unexpected RQ3 scale')
    return f'scale_{round(scale*1000):04d}'


def classify(row):
    """Selection reads execution status only, never correctness or judge outcome."""
    path = Path(row['attempt']) / 'result.json'
    if not path.is_file(): raise ValueError('Selected original attempt has no terminal result')
    result = read(path)
    if result.get('job_id') != row['job_id'] or result.get('question_id') != row['question_id'] or result.get('repeat') != row['repeat']:
        raise ValueError('Original result identity differs from the fixed comparison')
    if result.get('status') != row['prediction_status']: raise ValueError('Stale comparison execution status')
    if result.get('slot_released') is not True or result.get('unconfirmed_child_termination') != []:
        raise ValueError('Unknown original child cleanup; no automatic recovery')
    status = result['status']
    if status not in ('completed', 'timeout', 'failed'): raise ValueError('Unresolved original attempt')
    return {'job_id': row['job_id'], 'question_id': row['question_id'], 'repeat': row['repeat'],
            'scale': row['scale'], 'scale_key': key(row['scale']), 'status': status,
            'selected_for_retry': status in ('timeout', 'failed'), 'result_path': str(path),
            'result_sha256': sha(path), 'old_route': row.get('actual_route'),
            'original_selection': row.get('selection')}


def scale_config(base, scale, model):
    cfg = copy.deepcopy(base)
    cfg.update(model=model, execution_version='hermes-parity-v3', campaign_version=VERSION,
               bounded_rq3_protocol=PROTOCOL, bounded_transport_encoding='bounded-canvas-lossless-webp-v1')
    cfg['visual_renderer'].update(history_scale=scale, font_size=16, layout='highlight',
        notes='Independent bounded failure retry: fixed source pages then true far-page downsampling; no old far pre-enlargement, no recent vertical merge.')
    cfg['shared_policy']['strategy_configs']['visual'].update(history_scale=scale, font_size=16,
        image_width=1024, max_image_height=2048, history_max_image_height=2048,
        keep_rounds=1, recent_rounds=5, text_only=False)
    cfg['bc100_campaign'] = {'name': VERSION, 'max_rounds': 60, 'timeout_seconds': 1800,
                            'models': {'hermes': model}, 'strategies': ['visual']}
    cfg['rq3'] = {'protocol': PROTOCOL, 'far_history_scale': scale, 'scale': scale,
        'zero_semantics': 'Omit far history only; bounded recent pages and protected native head/tail remain.',
        'selection': 'Original execution timeout or failed, independent of answer correctness.',
        'maximum_new_attempts_per_selected_job': 1,
        'old_route': 'deepseek-v4.1-flash-1017/zijian/sfb', 'new_route': model,
        'route_migration_explicit': True, 'renderer_protocol_changed': True,
        'mixed_protocol_overlay_is_clean_resolution_ablation': False}
    return cfg


def prepare(root=DEFAULT_ROOT):
    root = Path(root).resolve()
    if root != DEFAULT_ROOT.resolve(): raise ValueError('Independent fixed retry root required')
    raw = (SOURCE_REPORT / 'observations.jsonl').read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if len(rows) != 2100 or len({r['job_id'] for r in rows}) != 2100:
        raise ValueError('Expected seven complete100x3 execution cohorts')
    records = [classify(row) for row in rows]
    source_rows = [json.loads(line) for line in (PARENT / 'cohort.jsonl').read_text().splitlines() if line.strip()]
    if len(source_rows) != 100 or len({r['id'] for r in source_rows}) != 100: raise ValueError('Invalid source cohort')
    public = [{'id': r['id'], 'question': r['question']} for r in source_rows]
    by_id = {r['id']: r for r in public}
    for s in SCALES:
        selected = [r for r in records if r['scale'] == s]
        if {(r['question_id'], r['repeat']) for r in selected} != {(q, rep) for q in by_id for rep in (1,2,3)}:
            raise ValueError('Scale lacks original fixed100x3 observations')
    # Old cohorts contain reference answers. Only public fields enter the new prediction root.
    immutable(root / 'cohort.jsonl', ''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in public).encode())
    immutable_json(PRIVATE / 'gold.json', {r['id']: {'question': r['question'], 'answer': r['answer']} for r in source_rows}, private=True)
    immutable(PRIVATE / 'original-observations.jsonl', raw, private=True)
    immutable(PRIVATE / 'comparison-plan.json', (SOURCE_REPORT / 'comparison-plan.json').read_bytes(), private=True)
    immutable_json(PRIVATE / 'selection.json', {'records': records,
        'selected_using_answer_correctness': False, 'selected_statuses': ['failed','timeout'],
        'original_runs': 2100, 'new_runs': sum(r['selected_for_retry'] for r in records),
        'completed_wrong_and_ungraded_predictions_retained': True}, private=True)
    model = read(ROOT / 'configs/experiment.json')['model']
    if model != 'deepseek-v4.1-flash-1017/huoshan/huoshan': raise ValueError('Unexpected latest approved route')
    base = read(ROOT / 'configs/experiment.v3.review.json')
    immutable_json(root / 'experiment.json', scale_config(base, 1., model))
    hashes = {}
    for scale in SCALES:
        path = root / 'configs' / (key(scale)+'.json'); immutable_json(path, scale_config(base, scale, model))
        hashes[str(path.relative_to(root))] = sha(path)
    jobs = []
    for r in records:
        if not r['selected_for_retry']: continue
        cfg = root / 'configs' / (r['scale_key']+'.json')
        jobs.append({'job_id': r['job_id'], 'harness': 'hermes', 'strategy': 'visual',
            'scale': r['scale'], 'scale_key': r['scale_key'], 'bounded_rq3_protocol': PROTOCOL,
            'question_id': r['question_id'], 'question': by_id[r['question_id']]['question'],
            'repeat': r['repeat'], 'model': model, 'timeout_seconds': 1800,
            'config_path': str(cfg), 'config_sha256': sha(cfg)})
    source_hashes = implementation_hashes()
    source_hashes.update({'scripts/'+n: sha(ROOT/'scripts'/n) for n in NEW_SOURCES})
    d = {'execution_version': VERSION, 'protocol': PROTOCOL, 'scales': list(SCALES), 'scale_keys': list(SCALE_KEYS),
        'config_sha256': sha(root/'experiment.json'), 'cohort_sha256': sha(root/'cohort.jsonl'),
        'scale_config_sha256': hashes, 'selection_path': str(PRIVATE/'selection.json'),
        'selection_sha256': sha(PRIVATE/'selection.json'), 'original_observations_path': str(PRIVATE/'original-observations.jsonl'),
        'original_observations_sha256': sha(PRIVATE/'original-observations.jsonl'),
        'comparison_plan_sha256': sha(PRIVATE/'comparison-plan.json'), 'gold_path': str(PRIVATE/'gold.json'),
        'gold_sha256': sha(PRIVATE/'gold.json'), 'source_cohort_sha256': sha(PARENT/'cohort.jsonl'),
        'jobs_sha256': digest(jobs), 'planned_runs': len(jobs), 'original_runs': 2100,
        'per_cell_concurrency_cap': 112, 'per_scale_concurrency_cap': 16,
        'global_other_campaign_admission_cap': 128, 'reserved_judge_slots': 4,
        'implementation_sha256': source_hashes, 'harness_lock': read(ROOT/'harness-lock.json'),
        'selection_uses_prior_answers': False, 'selection_uses_execution_failure': True,
        'renderer_and_route_migration': True, 'maximum_new_attempts_per_job': 1}
    immutable_json(root/'plan.json', {'definition': d, 'jobs': jobs})
    immutable_json(root/'campaign-manifest.json', {'version': VERSION, 'root': str(root),
        'plan_sha256': sha(root/'plan.json'), 'planned_runs': len(jobs),
        'per_scale': {key(s): sum(j['scale']==s for j in jobs) for s in SCALES},
        'scope': 'Only original RQ3 failed/timeout executions; completed wrong/unknown grades are not rerun.',
        'old_results_deleted': False, 'overlay_is_clean_single_protocol_accuracy': False})
    validate_sources(read(root/'plan.json'), root)
    return read(root/'campaign-manifest.json')


def validate_sources(plan, root):
    root = Path(root).resolve(); d = plan['definition']
    if d.get('execution_version') != VERSION or d.get('scale_keys') != list(SCALE_KEYS): raise ValueError('Wrong protocol')
    checks = {root/'experiment.json': d['config_sha256'], root/'cohort.jsonl': d['cohort_sha256'],
        Path(d['selection_path']): d['selection_sha256'], Path(d['original_observations_path']): d['original_observations_sha256']}
    checks.update({root/name: expected for name,expected in d['scale_config_sha256'].items()})
    for p, expected in checks.items():
        if sha(p) != expected: raise ValueError('Frozen retry artifact changed: '+str(p))
    records = read(d['selection_path'])['records']
    for r in records:
        if sha(r['result_path']) != r['result_sha256']: raise ValueError('Original result archive changed')
    if digest(plan['jobs']) != d['jobs_sha256'] or len(plan['jobs']) != d['planned_runs']:
        raise ValueError('Frozen new job list changed')
    expected_ids = {r['job_id'] for r in records if r['selected_for_retry']}
    if {j['job_id'] for j in plan['jobs']} != expected_ids: raise ValueError('Retry selection changed')
    if any(r['selected_for_retry'] != (r['status'] in ('timeout','failed')) for r in records):
        raise ValueError('Selection must use execution status only')
    if any(set(json.loads(line)) != {'id','question'} for line in (root/'cohort.jsonl').read_text().splitlines()):
        raise ValueError('Private answer leaked into public cohort')
    for name, expected in d['implementation_sha256'].items():
        if sha(ROOT/name) != expected: raise ValueError('Frozen implementation changed: '+name)
    if read(ROOT/'harness-lock.json') != d['harness_lock']: raise ValueError('Harness pin changed')
    return root


def load_validate(root=DEFAULT_ROOT):
    root = Path(root).resolve(); plan, manifest = read(root/'plan.json'), read(root/'campaign-manifest.json')
    if manifest['version'] != VERSION or manifest['plan_sha256'] != sha(root/'plan.json'): raise ValueError('Plan binding differs')
    validate_sources(plan,root); return plan,manifest


def validate_trial(spec, out):
    root = Path(spec['campaign_root']).resolve(); plan,_ = load_validate(root)
    if sha(root/'plan.json') != spec['plan_sha256'] or spec['cohort_sha256'] != plan['definition']['cohort_sha256']:
        raise ValueError('Trial plan/cohort binding differs')
    job = next((j for j in plan['jobs'] if j['job_id']==spec['job_id']), None)
    if job is None or any(spec.get(k)!=v for k,v in job.items()): raise ValueError('Trial differs from frozen job')
    if Path(out).resolve() != root/'jobs'/job['job_id']/'attempts/attempt_001': raise ValueError('Wrong attempt namespace')
    if Path(spec['config_path']).resolve() != root/'configs'/(job['scale_key']+'.json') or sha(spec['config_path']) != job['config_sha256']:
        raise ValueError('Trial scale configuration changed')
    claim=read(root/'jobs'/job['job_id']/'claim/owner.json');slot=read(Path(spec['slot_path'])/'owner.json')
    if claim.get('controller_id')!=spec['controller_id'] or claim.get('slot')!=spec['slot_path'] or slot.get('job_id')!=job['job_id'] or slot.get('controller_id')!=spec['controller_id']:
        raise ValueError('Trial has no exact owned claim/slot')
    return root


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    p.add_argument('--prepare',action='store_true');p.add_argument('--validate',action='store_true');a=p.parse_args()
    if a.prepare: print(json.dumps(prepare(a.root)))
    elif a.validate: print(json.dumps(load_validate(a.root)[1]))
    else: print(json.dumps({'paid_calls':0,'scope':'Seven RQ3 scales, execution failure/timeout only'}))


if __name__=='__main__': main()
