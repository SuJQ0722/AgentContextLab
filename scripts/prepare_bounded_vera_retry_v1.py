#!/usr/bin/env python3
"""Freeze one answer-selected retry, retaining every original attempt and cost."""
import argparse
import copy
import json
from pathlib import Path

import prepare_mmbc100_campaign as original
from mmbc_input_images import validate_assets

ROOT = original.ROOT
VERSION = 'mmbc-vera-bounded-retry-v1'
DEFAULT_ROOT = ROOT / 'outputs/campaigns' / VERSION
PARENT = original.DEFAULT_ROOT
GRADING = ROOT / 'outputs/grading/mmbc100-deepseek-hermes-v1'
PROTOCOL = 'bounded-multimodal-pages-v1'
SHARDS = 3
NEW_SOURCES = ('prepare_bounded_vera_retry_v1.py', 'run_bounded_vera_retry_v1.py',
               'run_bounded_vera_trial_v1.py', 'bootstrap_bounded_vera_retry_v1.py',
               'hermes_bounded_mmbc_worker_v1.py', 'bounded_multimodal_renderer_v1.py',
               'bounded_visual_request_guard_v1.py', 'bounded_lossless_transport_v1.py')
sha, read, digest, immutable, immutable_json = original.sha, original.read, original.digest, original.immutable, original.immutable_json


def classify(job, parent, grading):
    path = parent / 'jobs' / job['job_id'] / 'attempts/attempt_001/result.json'
    if not path.is_file(): raise ValueError('Original attempt is unresolved; do not replay')
    result = read(path)
    if result.get('job_id') != job['job_id'] or result.get('slot_released') is not True or result.get('unconfirmed_child_termination') != []:
        raise ValueError('Original identity/child cleanup is unconfirmed')
    record = {'job_id': job['job_id'], 'result_path': str(path), 'result_sha256': sha(path),
              'status': result['status'], 'score': None, 'grade_path': None, 'grade_sha256': None}
    if result['status'] in ('failed', 'timeout'):
        record.update(score=0, reason='confirmed_operational_failure')
    elif result['status'] == 'completed':
        grade_path = grading / 'jobs' / job['job_id'] / 'grade.json'
        if not grade_path.is_file(): raise ValueError('Completed prediction needs grading before selection')
        grade = read(grade_path)
        if grade.get('status') != 'scored' or type(grade.get('score')) not in (float, int) or grade['score'] not in (0, 1):
            raise ValueError('Unknown grade must not be selected as incorrect')
        if grade.get('result_sha256') != record['result_sha256'] or grade.get('plan_sha256') != sha(parent / 'plan.json'):
            raise ValueError('Original grade is not bound to this result and plan')
        record.update(score=int(grade['score']), reason='judged_original', grade_path=str(grade_path), grade_sha256=sha(grade_path))
    else:
        raise ValueError('Interrupted/not-started/unknown outcome requires explicit resolution')
    return record


def retry_config(parent_config):
    cfg = copy.deepcopy(parent_config)
    cfg.update(campaign_version=VERSION, bounded_visual_protocol=PROTOCOL,
               bounded_transport_encoding='bounded-canvas-lossless-webp-v1')
    cfg['visual_renderer'].update(history_scale=.75, font_size=16,
        notes='New bounded pages and pixel-identical WebP retry; original first-pass results unchanged.')
    cfg['shared_policy']['strategy_configs']['visual'].update(
        font_size=16, history_scale=.75, image_width=1024, max_image_height=2048,
        history_max_image_height=2048, keep_rounds=1, recent_rounds=5, text_only=False)
    cfg['bounded_retry'] = {'version': VERSION, 'prior_correct_retained': True,
        'maximum_new_attempts_per_selected_job': 1, 'shards': SHARDS, 'workers_per_shard': 16,
        'selection_uses_prior_answers': True, 'mixed_protocol_union_is_single_attempt_accuracy': False,
        'retain_all_original_costs_and_failures': True, 'automatic_retry_until_correct': False}
    return cfg


def make_jobs(parent_jobs, records, root):
    selected = {r['job_id'] for r in records if r['score'] == 0}
    jobs = []
    for source in parent_jobs:
        if source['job_id'] not in selected: continue
        job = copy.deepcopy(source)
        job.update(config_path=str(root / 'experiment.json'), config_sha256=sha(root / 'experiment.json'),
                   bounded_visual_protocol=PROTOCOL, shard=len(jobs) % SHARDS)
        # No old answer, judge rationale, or correctness flag enters worker specs.
        jobs.append(job)
    if len(jobs) != len(selected): raise ValueError('Retry selection does not match original jobs')
    return jobs


def prepare(root=DEFAULT_ROOT, parent=PARENT, grading=GRADING):
    root, parent, grading = (Path(x).resolve() for x in (root, parent, grading))
    if root == parent or root in parent.parents or parent in root.parents:
        raise ValueError('Independent retry namespace required')
    parent_plan, _ = original.load_validate(parent)
    visual = [j for j in parent_plan['jobs'] if j['strategy'] == 'visual' and j['harness'] == 'hermes']
    if len(visual) != 300: raise ValueError('Expected original MMBC100 x3 VERA cohort')
    records = [classify(j, parent, grading) for j in visual]
    if any(r['score'] is None for r in records): raise ValueError('Unresolved original grade')
    for filename in ('cohort.jsonl', 'cohort-manifest.json'):
        immutable(root / filename, (parent / filename).read_bytes())
    immutable_json(root / 'experiment.json', retry_config(read(parent / 'experiment.json')))
    assets = validate_assets(parent, deep=True)
    for item in assets['images'].values():
        immutable(root / item['relative_path'], (parent / item['relative_path']).read_bytes())
    immutable(root / 'image-assets/manifest.json', (parent / 'image-assets/manifest.json').read_bytes())
    selection = {'version': VERSION, 'parent_root': str(parent), 'grading_root': str(grading),
        'parent_plan_sha256': sha(parent / 'plan.json'), 'records': records,
        'retained_correct': sum(r['score'] == 1 for r in records),
        'retry_selected': sum(r['score'] == 0 for r in records),
        'deletion_performed': False, 'original_results_preserved_in_place': True,
        'interpretation': 'Original records are the immutable archive. The active retry queue excludes correct originals. This is answer-selected retry, not an unbiased new avg3 benchmark.'}
    private = ROOT / 'outputs/grading' / VERSION / 'private/selection.json'
    immutable_json(private, selection, private=True)
    jobs = make_jobs(visual, records, root)
    hashes = dict(parent_plan['definition']['implementation_sha256'])
    hashes.update({'scripts/' + n: sha(ROOT / 'scripts' / n) for n in NEW_SOURCES})
    definition = {'execution_version': VERSION, 'config_sha256': sha(root / 'experiment.json'),
        'cohort_sha256': sha(root / 'cohort.jsonl'), 'cohort_manifest_sha256': sha(root / 'cohort-manifest.json'),
        'input_images_sha256': sha(root / 'image-assets/manifest.json'), 'jobs_sha256': digest(jobs),
        'implementation_sha256': hashes, 'harness_lock': read(ROOT / 'harness-lock.json'),
        'parent_root': str(parent), 'parent_plan_sha256': sha(parent / 'plan.json'),
        'parent_config_sha256': sha(parent / 'experiment.json'), 'selection_path': str(private),
        'selection_sha256': sha(private), 'planned_runs': len(jobs), 'original_runs': 300,
        'retained_correct': selection['retained_correct'], 'per_cell_concurrency_cap': 48,
        'shards': SHARDS, 'per_shard_concurrency_cap': 16, 'maximum_new_attempts_per_job': 1,
        'selection_uses_prior_answers': True, 'single_attempt_accuracy_valid': False,
        'mixed_old_and_new_renderer_protocol': True, 'old_failures_and_usage_retained': True}
    immutable_json(root / 'plan.json', {'definition': definition, 'jobs': jobs})
    immutable_json(root / 'campaign-manifest.json', {'version': VERSION, 'root': str(root),
        'plan_sha256': sha(root / 'plan.json'), 'planned_runs': len(jobs), 'retained_correct': selection['retained_correct'],
        'scope': 'MMBC Hermes VERA only; no vanilla, text baseline, BC, RQ3 or information-loss dispatch',
        'reporting': 'Report original300, new selected retries and any retained-correct union separately; include all attempts/costs. Do not publish union as single-attempt avg3.'})
    validate_sources(read(root / 'plan.json'), root)
    return read(root / 'campaign-manifest.json')


def validate_sources(plan, root):
    root = Path(root).resolve(); d = plan['definition']
    if d.get('execution_version') != VERSION or d.get('shards') != SHARDS or d.get('per_cell_concurrency_cap') != 48:
        raise ValueError('Unexpected retry protocol')
    for key, name in [('config_sha256', 'experiment.json'), ('cohort_sha256', 'cohort.jsonl'),
                      ('cohort_manifest_sha256', 'cohort-manifest.json'), ('input_images_sha256', 'image-assets/manifest.json')]:
        if sha(root / name) != d[key]: raise ValueError('Frozen retry input changed: ' + name)
    parent = Path(d['parent_root']); parent_plan = read(parent / 'plan.json')
    if sha(parent / 'plan.json') != d['parent_plan_sha256'] or sha(parent / 'experiment.json') != d['parent_config_sha256']:
        raise ValueError('Original scientific plan changed')
    private = Path(d['selection_path'])
    if sha(private) != d['selection_sha256']: raise ValueError('Frozen answer-based selection changed')
    selection = read(private)
    for r in selection['records']:
        if sha(r['result_path']) != r['result_sha256'] or r['grade_path'] and sha(r['grade_path']) != r['grade_sha256']:
            raise ValueError('Original result/grade archive changed')
    if read(root / 'experiment.json') != retry_config(read(parent / 'experiment.json')):
        raise ValueError('Unrecorded change to retry configuration')
    if plan['jobs'] != make_jobs(parent_plan['jobs'], selection['records'], root) or digest(plan['jobs']) != d['jobs_sha256'] or len(plan['jobs']) != d['planned_runs']:
        raise ValueError('Frozen retry selection changed')
    for name, expected in d['implementation_sha256'].items():
        if sha(ROOT / name) != expected: raise ValueError('Frozen implementation changed: ' + name)
    if read(ROOT / 'harness-lock.json') != d['harness_lock']: raise ValueError('Harness pin changed')
    validate_assets(root, deep=False)
    return root


def load_validate(root=DEFAULT_ROOT):
    root = Path(root).resolve(); plan = read(root / 'plan.json'); manifest = read(root / 'campaign-manifest.json')
    if manifest['version'] != VERSION or manifest['plan_sha256'] != sha(root / 'plan.json'):
        raise ValueError('Retry manifest identity changed')
    validate_sources(plan, root)
    return plan, manifest


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    p.add_argument('--prepare', action='store_true'); p.add_argument('--validate', action='store_true'); a = p.parse_args()
    if a.prepare: print(json.dumps(prepare(a.root)))
    elif a.validate: print(json.dumps(load_validate(a.root)[1]))
    else: print(json.dumps({'paid_calls': 0, 'scope': 'MMBC VERA', 'prepare_required': True, 'delete_old_results': False}))


if __name__ == '__main__': main()
