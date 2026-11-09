#!/usr/bin/env python3
"""Freeze a gold-isolated, deterministic MMBC-100 Hermes campaign; no API calls."""
import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'mmbc100-hermes-deepseek-v1'
DEFAULT_ROOT = ROOT / 'outputs/campaigns' / VERSION
GRADING = ROOT / 'outputs/grading' / VERSION
SOURCE = ROOT.parent / 'hermes-agent/Browsecomp_eval/data/mmbrowsecomp/questions.jsonl'
SOURCE_SHA256 = '4b39d5dfaf29111ca5b4d6577a39023f01f66bf7c67d80807b214bf08909093f'
ROOT_CONFIG = ROOT / 'configs/experiment.json'
BASE_CONFIG = ROOT / 'configs/experiment.v3.review.json'
METHODS = ('none', 'summarize', 'sliding_window', 'discard', 'visual')
SEED = 20261107
MODEL = 'deepseek-v4.1-flash-1017/huoshan/huoshan'
NEW_SOURCES = ('prepare_mmbc100_campaign.py', 'mmbc_input_images.py',
               'hermes_mmbc_worker_v1.py', 'run_mmbc100_trial.py',
               'run_mmbc100_campaign.py', 'bootstrap_mmbc100_cci.py', 'provision_mmbc_cci_v1.py')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def immutable(path, raw, private=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if private:
        path.parent.chmod(0o700)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f'Refusing to overwrite frozen input: {path}')
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if private else 0o644)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())


def immutable_json(path, value, private=False):
    immutable(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode(), private)


def jsonl(rows):
    return ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in rows).encode()


def select_rows(source=SOURCE, expected_sha=SOURCE_SHA256):
    source = Path(source)
    if sha(source) != expected_sha:
        raise ValueError('MMBC source SHA differs from the reviewed 400-question source')
    rows = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    if len(rows) != 400 or len({r.get('id') for r in rows}) != 400:
        raise ValueError('Expected exactly 400 unique MMBC source rows')
    for row in rows:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', str(row.get('id', ''))):
            raise ValueError('Unsafe question ID')
        if not isinstance(row.get('question'), str) or not row['question'].strip() or not str(row.get('answer', '')).strip():
            raise ValueError('Missing question or private standard answer')
        if not isinstance(row.get('image'), list) or any(not isinstance(u, str) or not u.startswith(('http://', 'https://')) for u in row['image']):
            raise ValueError('Source image list must contain HTTP(S) URLs')
    return sorted(rows, key=lambda r: hashlib.sha256(f"{SEED}:mmbrowsecomp:{r['id']}".encode()).digest())[:100]


def input_summary(rows):
    return {'questions': len(rows), 'with_initial_images': sum(bool(r['image']) for r in rows),
            'without_initial_images': sum(not r['image'] for r in rows),
            'initial_image_occurrences': sum(len(r['image']) for r in rows),
            'unique_image_urls': len({u for r in rows for u in r['image']})}


def experiment_config(root_config=ROOT_CONFIG, base_config=BASE_CONFIG):
    root = read(root_config)
    cfg = copy.deepcopy(read(base_config))
    campaign = copy.deepcopy(root['mmbc100_campaign'])
    if root['model'] != MODEL or campaign['model'] != MODEL or campaign['judge_model'] != MODEL:
        raise ValueError('MMBC route must match the approved root model; no route fallback')
    if campaign['strategies'] != list(METHODS) or campaign['questions'] != 100 or campaign['repeats'] != 3 or campaign['seed'] != SEED:
        raise ValueError('MMBC scope must be fixed 100 x 3 x five Hermes methods')
    if campaign['concurrency_per_method'] != 16 or campaign['harnesses'] != ['hermes'] or campaign['vanilla_visual']['status'] != 'pending_definition':
        raise ValueError('Unexpected MMBC operational scope or unapproved vanilla definition')
    expected = {'context_window': 131072, 'max_output_tokens': 8192,
                'compression_threshold_tokens': 32768, 'max_rounds': 60, 'timeout_seconds': 1800}
    if any(campaign.get(k) != v for k, v in expected.items()):
        raise ValueError('MMBC budgets differ from the approved BC comparison protocol')
    if cfg['context_window'] != expected['context_window'] or cfg['max_output_tokens'] != expected['max_output_tokens'] or cfg['pilot']['compression_trigger_tokens'] != expected['compression_threshold_tokens']:
        raise ValueError('Reviewed native configuration differs from the MMBC budget declaration')
    # Keep the reviewed native worker contract; the independent plan carries MMBC scope.
    cfg['execution_version'] = 'hermes-parity-v3'
    cfg['campaign_version'] = VERSION
    cfg['model'] = MODEL
    cfg['mmbc100_campaign'] = campaign
    cfg['source_experiment_sha256'] = sha(root_config)
    cfg['source_review_config_sha256'] = sha(base_config)
    cfg['bc100_campaign'] = {'name': VERSION, 'max_rounds': campaign['max_rounds'],
                           'timeout_seconds': campaign['timeout_seconds'],
                           'models': {'hermes': MODEL}, 'strategies': list(METHODS),
                           'adapter_only': True,
                           'note': 'Legacy native worker configuration adapter; scientific scope comes exclusively from mmbc100_campaign and its plan'}
    # Hermes has a per-input staging limit; DSH's request-size normalization is inapplicable.
    cfg['image_transport'] = {'version': 'hermes-native-image-bytes-v1',
                            'max_staged_image_bytes': 25 * 1024 * 1024,
                            'resize': False, 'source': 'frozen input image assets plus actual tool output',
                            'provider_total_payload_limit': None}
    cfg['visual_renderer'].update(layout='highlight', font_size=16, history_scale=1.0)
    return cfg


def prepare_inputs(root=DEFAULT_ROOT, source=SOURCE, grading_root=GRADING,
                   root_config=ROOT_CONFIG, base_config=BASE_CONFIG, expected_source_sha=SOURCE_SHA256):
    root, grading_root = Path(root).resolve(), Path(grading_root).resolve()
    if grading_root == root or root in grading_root.parents:
        raise ValueError('Gold namespace must be outside the prediction campaign')
    rows = select_rows(source, expected_source_sha)
    public = [{'question_id': r['id'], 'question': r['question'], 'image': r['image']} for r in rows]
    cfg = experiment_config(root_config, base_config)
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'prepare.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        immutable(root / 'cohort.jsonl', jsonl(public))
        immutable_json(root / 'experiment.json', cfg)
        # This file is private to the grader; it is never a native worker input.
        private_rows = [{'question_id': r['id'], 'answer': r['answer'],
                         'source_row': r} for r in rows]
        private = grading_root / 'private/selected-source.jsonl'
        immutable(private, jsonl(private_rows), private=True)
        private_map = {'version': VERSION, 'source_path': str(Path(source).resolve()),
                       'source_sha256': sha(source), 'selected_source_sha256': sha(private),
                       'cohort_sha256': sha(root / 'cohort.jsonl'),
                       'selected_ids': [r['id'] for r in rows],
                       'answer_isolation': 'Not mounted or copied into native workspace; scoring only'}
        immutable_json(grading_root / 'private/source-map.json', private_map, private=True)
        manifest = {'version': VERSION, 'source_sha256': sha(source), 'source_rows': 400,
                    'seed': SEED, 'selection': 'SHA256(seed:mmbrowsecomp:original_id) ascending binary digest; first 100 of all 400',
                    'selection_uses_answers_or_predictions': False, 'filter_initial_image_presence': False,
                    'cohort_sha256': sha(root / 'cohort.jsonl'), 'selected_ids': [r['id'] for r in rows],
                    **input_summary(rows), 'image_content_frozen': False,
                    'image_freeze_requirement': 'plan.json must bind image-assets/manifest.json before dispatch'}
        immutable_json(root / 'cohort-manifest.json', manifest)
    return manifest


def implementation_hashes():
    names = list(NEW_SOURCES) + ['run_bc_trial_v3.py', 'run_bc_trial_v3_io.py', 'run_bc_campaign_v3.py', 'hermes_bc_worker_v3.py',
            'hermes_bc_worker.py', 'hermes_native_vision_worker_v2.py', 'local_web.py', 'lab.py',
            'review_execution.py', 'shared_context_policy.py', 'native_image_origins.py', 'rq3_pdf_renderer.py',
            'local_reader_text_service.py', 'run_dsh_eval.py', 'preflight_bc_v3_web.py',
            'bootstrap_bc_retry1.py', 'replace_bc_v3_reader.py', 'cloud_python_stage.py',
            'bc_route_runtime_v1.py', 'replace_sco_bc_v3_after_reader_ops.py', 'resume_sco_bc_v3_after_reader_ops.py']
    paths = [ROOT / 'scripts' / n for n in names]
    paths += list((ROOT / 'hermes-agent').glob('*.py'))
    for folder in ('agent', 'plugins/context_engine', 'tools'):
        paths += list((ROOT / 'hermes-agent' / folder).rglob('*.py'))
    paths += [ROOT / 'configs/reader-text-v1.json', ROOT / 'configs/reader-text-v1-workers32.json']
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(paths))}


def make_jobs(rows, cfg, root):
    jobs = []
    for repeat in range(1, 4):
        for row in rows:
            for method in METHODS:
                jobs.append({'job_id': f"hermes/{method}/{row['question_id']}_r{repeat:02}",
                             'harness': 'hermes', 'strategy': method, **row, 'repeat': repeat,
                             'model': cfg['model'], 'timeout_seconds': cfg['mmbc100_campaign']['timeout_seconds'],
                             'config_path': str(Path(root).resolve() / 'experiment.json'),
                             'config_sha256': sha(Path(root) / 'experiment.json')})
    return jobs


def prepare(root=DEFAULT_ROOT, **kwargs):
    root = Path(root).resolve()
    cohort = prepare_inputs(root, **kwargs)
    image_manifest = root / 'image-assets/manifest.json'
    if not image_manifest.is_file():
        raise ValueError('Freeze all initial image assets before preparing the executable plan')
    from mmbc_input_images import validate_assets
    validate_assets(root, deep=True)
    cfg = read(root / 'experiment.json')
    rows = [json.loads(line) for line in (root / 'cohort.jsonl').read_text().splitlines()]
    jobs = make_jobs(rows, cfg, root)
    definition = {'execution_version': VERSION, 'config_sha256': sha(root / 'experiment.json'),
                  'cohort_sha256': sha(root / 'cohort.jsonl'), 'input_images_sha256': sha(image_manifest),
                  'cohort_manifest_sha256': sha(root / 'cohort-manifest.json'),
                  'planned_runs': 1500, 'harnesses': ['hermes'], 'strategies': list(METHODS),
                  'questions': 100, 'repeats': 3, 'per_cell_concurrency_cap': 16,
                  'jobs_sha256': digest(jobs), 'implementation_sha256': implementation_hashes(),
                  'harness_lock': read(ROOT / 'harness-lock.json'), 'harness_lock_validation_scope': 'recorded lineage; only Hermes implementation used/validated',
                  'vanilla_visual': {'status': 'pending_definition', 'executable': False},
                  'image_transport': cfg['image_transport'], 'resume_policy': 'pending only; all existing claims/attempts retained; no automatic retry'}
    plan = {'definition': definition, 'jobs': jobs}
    immutable_json(root / 'plan.json', plan)
    manifest = {'version': VERSION, 'root': str(root), 'plan_sha256': sha(root / 'plan.json'),
                'cohort_sha256': cohort['cohort_sha256'], 'input_images_sha256': definition['input_images_sha256'],
                'image_content_frozen': True,
                'planned_runs': 1500, 'scientific_scope': 'five methods; vanilla pending; native-retention controlled baselines remain a separate protocol'}
    immutable_json(root / 'campaign-manifest.json', manifest)
    validate_sources(plan, root)
    return manifest


def validate_sources(plan, root):
    root = Path(root).resolve()
    d = plan['definition']
    if d['execution_version'] != VERSION or d['strategies'] != list(METHODS) or d['harnesses'] != ['hermes'] or d['planned_runs'] != 1500:
        raise ValueError('Unexpected MMBC scientific scope')
    for key, file in [('config_sha256', 'experiment.json'), ('cohort_sha256', 'cohort.jsonl'),
                      ('cohort_manifest_sha256', 'cohort-manifest.json'), ('input_images_sha256', 'image-assets/manifest.json')]:
        if sha(root / file) != d[key]:
            raise ValueError(f'Frozen MMBC input changed: {file}')
    rows = [json.loads(line) for line in (root / 'cohort.jsonl').read_text().splitlines()]
    if len(rows) != 100 or len({r['question_id'] for r in rows}) != 100 or any(set(r) != {'question_id', 'question', 'image'} for r in rows):
        raise ValueError('Public MMBC cohort contains duplicate IDs, incorrect size, or private fields')
    if plan['jobs'] != make_jobs(rows, read(root / 'experiment.json'), root) or digest(plan['jobs']) != d['jobs_sha256']:
        raise ValueError('Frozen MMBC job list changed')
    for name, expected in d['implementation_sha256'].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f'MMBC implementation changed: {name}; use a new version')
    from mmbc_input_images import validate_assets
    validate_assets(root, deep=False)
    return root


validate = validate_sources


def load_validate(root=DEFAULT_ROOT):
    root = Path(root).resolve()
    plan, manifest = read(root / 'plan.json'), read(root / 'campaign-manifest.json')
    if sha(root / 'plan.json') != manifest['plan_sha256']:
        raise ValueError('MMBC campaign manifest/plan mismatch')
    validate_sources(plan, root)
    return plan, manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    p.add_argument('--source', type=Path, default=SOURCE)
    p.add_argument('--grading-root', type=Path, default=GRADING)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--prepare-inputs', action='store_true')
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--validate', action='store_true')
    a = p.parse_args()
    if a.validate:
        _, result = load_validate(a.root)
    elif a.prepare or a.prepare_inputs:
        result = (prepare if a.prepare else prepare_inputs)(a.root, source=a.source, grading_root=a.grading_root)
    else:
        result = {**input_summary(select_rows(a.source)), 'root': str(a.root), 'methods': METHODS,
                  'planned_runs': 1500, 'paid_calls': 0, 'writes': False, 'vanilla': 'pending_definition'}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
