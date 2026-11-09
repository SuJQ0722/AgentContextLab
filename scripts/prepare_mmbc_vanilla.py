#!/usr/bin/env python3
"""Independent, fixed MMBC text-only visual-rendering addon; no model calls."""
import argparse
import copy
import fcntl
import json
from pathlib import Path

import prepare_mmbc100_campaign as parent
from mmbc_input_images import validate_assets

ROOT = parent.ROOT
VERSION = 'mmbc100-hermes-vanilla-v1'
PARENT = parent.DEFAULT_ROOT
DEFAULT_ROOT = ROOT / 'outputs/campaigns' / VERSION
METHOD_LABEL = 'vanilla_visual'
PROTOCOL = {
    'version': 'mmbc-vanilla-text-render-v1',
    'method_label': METHOD_LABEL,
    'engine': 'visual',
    'compression_region_images': 'omitted',
    'caption_generation': False,
    'table_policy': 'preserve original table text; disable structured table extraction',
    'head_tail_native_images': 'unchanged from parent VERA',
    'tools_and_initial_images': 'unchanged from parent VERA',
    'selection_and_budget': 'same trigger, protected span, retained rounds, font, layout and history scale as parent VERA',
    'image_tokens_matched': False,
    'interpretation': 'Visual-evidence-removal ablation; not a text-only agent or caption baseline',
    'authorization': 'User explicitly defined vanilla as rendering without visual evidence and authorized one additional CCI with16workers',
}
NEW_SOURCES = ('prepare_mmbc_vanilla.py', 'mmbc_vanilla_renderer.py',
               'hermes_mmbc_vanilla_worker_v1.py', 'run_mmbc_vanilla_trial.py',
               'run_mmbc_vanilla_campaign.py', 'bootstrap_mmbc_vanilla_cci.py',
               'provision_mmbc_vanilla_cci.py', 'render_dsh_history.py')
sha, read, digest = parent.sha, parent.read, parent.digest


def expected_config(cfg):
    result = copy.deepcopy(cfg)
    result['shared_policy']['strategy_configs']['visual']['text_only'] = True
    result['campaign_version'] = VERSION
    result['vanilla_visual_protocol'] = copy.deepcopy(PROTOCOL)
    return result


def make_jobs(parent_plan, root):
    jobs = []
    for original in parent_plan['jobs']:
        if original['harness'] != 'hermes' or original['strategy'] != 'visual':
            continue
        job = copy.deepcopy(original)
        job.update(method_label=METHOD_LABEL, config_path=str(Path(root).resolve() / 'experiment.json'),
                   config_sha256=sha(Path(root) / 'experiment.json'))
        jobs.append(job)
    if len(jobs) != 300 or len({j['job_id'] for j in jobs}) != 300 or {j['repeat'] for j in jobs} != {1, 2, 3}:
        raise ValueError('Parent must supply the same100 x3 visual observations')
    return jobs


def prepare_inputs(root=DEFAULT_ROOT, parent_root=PARENT):
    root, parent_root = Path(root).resolve(), Path(parent_root).resolve()
    if root == parent_root or root in parent_root.parents or parent_root in root.parents:
        raise ValueError('Vanilla must have a separate campaign root')
    plan, manifest = parent.load_validate(parent_root)
    if plan['definition']['execution_version'] != parent.VERSION or plan['definition']['strategies'] != list(parent.METHODS):
        raise ValueError('Only the frozen five-method MMBC campaign is an approved parent')
    assets = validate_assets(parent_root, deep=True)
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'prepare.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for filename in ('cohort.jsonl', 'cohort-manifest.json'):
            parent.immutable(root / filename, (parent_root / filename).read_bytes())
        parent.immutable_json(root / 'experiment.json', expected_config(read(parent_root / 'experiment.json')))
        # Independent copies avoid aliasing the parent's immutable asset inodes.
        for record in assets['images'].values():
            source = (parent_root / record['relative_path']).resolve()
            target = (root / record['relative_path']).resolve()
            if not target.is_relative_to(root / 'image-assets'):
                raise ValueError('Asset destination outside the new frozen image directory')
            parent.immutable(target, source.read_bytes())
            if sha(target) != record['sha256']:
                raise ValueError('Copied original image bytes differ')
        parent.immutable(root / 'image-assets/manifest.json', (parent_root / 'image-assets/manifest.json').read_bytes())
        lineage = {'version': VERSION, 'parent_root': str(parent_root),
                   'parent_plan_sha256': sha(parent_root / 'plan.json'),
                   'parent_campaign_manifest_sha256': sha(parent_root / 'campaign-manifest.json'),
                   'parent_config_sha256': sha(parent_root / 'experiment.json'),
                   'cohort_sha256': sha(root / 'cohort.jsonl'),
                   'input_images_sha256': sha(root / 'image-assets/manifest.json'),
                   'method_label': METHOD_LABEL, 'protocol': PROTOCOL,
                   'parent_results_reused': False, 'gold_source': 'Reuse the isolated parent grader source map; no gold stored in this campaign'}
        parent.immutable_json(root / 'vanilla-lineage.json', lineage)
    return lineage


def new_source_hashes():
    return {'scripts/' + name: sha(ROOT / 'scripts' / name) for name in NEW_SOURCES}


def prepare(root=DEFAULT_ROOT, parent_root=PARENT):
    root, parent_root = Path(root).resolve(), Path(parent_root).resolve()
    lineage = prepare_inputs(root, parent_root)
    original, _ = parent.load_validate(parent_root)
    jobs = make_jobs(original, root)
    d = copy.deepcopy(original['definition'])
    d.update(execution_version=VERSION, config_sha256=sha(root / 'experiment.json'),
             planned_runs=300, strategies=['visual'], method_labels=[METHOD_LABEL],
             jobs_sha256=digest(jobs), parent_root=str(parent_root),
             parent_plan_sha256=lineage['parent_plan_sha256'],
             parent_config_sha256=lineage['parent_config_sha256'],
             vanilla_lineage_sha256=sha(root / 'vanilla-lineage.json'),
             vanilla_visual={'status': 'approved', 'executable': True, 'protocol': PROTOCOL})
    d['implementation_sha256'].update(new_source_hashes())
    plan = {'definition': d, 'jobs': jobs}
    parent.immutable_json(root / 'plan.json', plan)
    manifest = {'version': VERSION, 'root': str(root), 'plan_sha256': sha(root / 'plan.json'),
                'parent_root': str(parent_root), 'parent_plan_sha256': lineage['parent_plan_sha256'],
                'cohort_sha256': d['cohort_sha256'], 'input_images_sha256': d['input_images_sha256'],
                'method_label': METHOD_LABEL, 'actual_engine_strategy': 'visual', 'planned_runs': 300,
                'image_content_frozen': True, 'vanilla_lineage_sha256': d['vanilla_lineage_sha256'],
                'science_difference': 'Only compressed-region image omission with original table text preserved; same initial/native retained images and all other scientific settings'}
    parent.immutable_json(root / 'campaign-manifest.json', manifest)
    validate_sources(plan, root)
    return manifest


def validate_sources(plan, root):
    root = Path(root).resolve()
    d = plan['definition']
    if d.get('execution_version') != VERSION or d.get('strategies') != ['visual'] or d.get('method_labels') != [METHOD_LABEL] or d.get('planned_runs') != 300 or d.get('per_cell_concurrency_cap') != 16:
        raise ValueError('Unexpected vanilla scope')
    parent_root = Path(d['parent_root']).resolve()
    original, _ = parent.load_validate(parent_root)
    if sha(parent_root / 'plan.json') != d['parent_plan_sha256'] or sha(parent_root / 'experiment.json') != d['parent_config_sha256']:
        raise ValueError('Vanilla parent lineage differs')
    cfg = read(root / 'experiment.json')
    if cfg != expected_config(read(parent_root / 'experiment.json')):
        raise ValueError('Vanilla config changes more than the authorized text-only intervention')
    for key, filename in [('config_sha256', 'experiment.json'), ('cohort_sha256', 'cohort.jsonl'),
                          ('cohort_manifest_sha256', 'cohort-manifest.json'), ('input_images_sha256', 'image-assets/manifest.json'),
                          ('vanilla_lineage_sha256', 'vanilla-lineage.json')]:
        if sha(root / filename) != d[key]:
            raise ValueError(f'Frozen vanilla input changed: {filename}')
    for key in ('cohort_sha256', 'cohort_manifest_sha256', 'input_images_sha256'):
        if d[key] != original['definition'][key]:
            raise ValueError('Vanilla must retain exact parent questions and images')
    lineage = read(root / 'vanilla-lineage.json')
    if lineage['parent_root'] != str(parent_root) or lineage['parent_plan_sha256'] != d['parent_plan_sha256'] or lineage['protocol'] != PROTOCOL:
        raise ValueError('Vanilla lineage protocol mismatch')
    if sha(parent_root / 'campaign-manifest.json') != lineage['parent_campaign_manifest_sha256']:
        raise ValueError('Parent campaign manifest differs')
    if plan['jobs'] != make_jobs(original, root) or digest(plan['jobs']) != d['jobs_sha256']:
        raise ValueError('Vanilla jobs differ from the fixed parent visual question/repeats')
    required = {**original['definition']['implementation_sha256'], **new_source_hashes()}
    if d['implementation_sha256'] != required:
        raise ValueError('Vanilla source lineage changed or lost a parent implementation binding')
    for name, expected in d['implementation_sha256'].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f'Vanilla implementation changed: {name}')
    validate_assets(root, deep=False)
    return root


validate = validate_sources


def load_validate(root=DEFAULT_ROOT):
    root = Path(root).resolve()
    plan, manifest = read(root / 'plan.json'), read(root / 'campaign-manifest.json')
    if manifest.get('version') != VERSION or manifest.get('plan_sha256') != sha(root / 'plan.json'):
        raise ValueError('Vanilla campaign manifest/plan mismatch')
    validate_sources(plan, root)
    return plan, manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    p.add_argument('--parent', type=Path, default=PARENT)
    modes = p.add_mutually_exclusive_group()
    modes.add_argument('--prepare-inputs', action='store_true')
    modes.add_argument('--prepare', action='store_true')
    modes.add_argument('--validate', action='store_true')
    a = p.parse_args()
    if a.prepare or a.prepare_inputs:
        result = (prepare if a.prepare else prepare_inputs)(a.root, a.parent)
    elif a.validate:
        _, result = load_validate(a.root)
    else:
        original, _ = parent.load_validate(a.parent)
        result = {'paid_calls': 0, 'writes': False, 'root': str(a.root), 'parent': str(a.parent),
                  'method_label': METHOD_LABEL, 'strategy': 'visual', 'runs': sum(j['strategy'] == 'visual' for j in original['jobs']),
                  'concurrency': 16, 'protocol': PROTOCOL}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
