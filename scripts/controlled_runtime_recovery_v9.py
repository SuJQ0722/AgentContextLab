"""Certify an exact predecessor visual target, then retain all V8 validation.

Only the stopped shared text cell may cross generations. Its measured target is
copied byte-for-byte into the new campaign namespace; no image, budget, or
scientific input is regenerated and no V8 artifact is modified.
"""
import copy
import json
import os
import uuid
from pathlib import Path
from unittest.mock import patch

import controlled_inline_retry_v8 as base
from prepare_inline_runtime_recovery_v9 import SOURCE, DEST, VERSION
from prepare_visual_hosted_retry_v1 import load_validate

ORIGINAL_VALIDATE = base.validate


def read(path):
    return json.loads(Path(path).read_text())


def immutable_bytes(path, raw):
    """Publish all bytes before exposing a shared target to parallel text arms."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ValueError('Previously copied target bytes differ')
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def validate(job, out):
    if job.get('operational_recovery_version') != VERSION:
        raise ValueError('Explicit V9 runtime recovery required')
    root = Path(job['campaign_root']).resolve()
    old = (SOURCE / 'cells/shared_baselines').resolve()
    if root != (DEST / 'cells/shared_baselines').resolve() or job.get('controlled_method') not in ('summary', 'window'):
        raise ValueError('Only frozen shared text baselines may reuse predecessor targets')
    plan, _ = load_validate(root)
    frozen = next((x for x in plan['jobs'] if x['job_id'] == job['job_id']), None)
    if frozen is None or any(job.get(k) != v for k, v in frozen.items()):
        raise ValueError('Recovery job differs from frozen plan')
    oldplan = old / 'plan.json'
    if plan['definition']['source_results_sha256'].get(str(oldplan)) != base.sha(oldplan):
        raise ValueError('Predecessor plan is not hash bound')
    matches = [x for x in read(oldplan)['jobs'] if x['job_id'] == job['job_id']]
    if len(matches) != 1:
        raise ValueError('Unique predecessor job required')
    prior = matches[0]
    changed_paths = {'config_path', 'controlled_spec_path', 'controlled_spec_sha256', 'native_cohort_path'}
    if any(job.get(k) != v for k, v in prior.items() if k not in changed_paths):
        raise ValueError('Predecessor scientific identity changed')
    previous_attempt = old / 'jobs' / job['job_id'] / 'attempts/attempt_001'
    if Path(job['previous_v8_attempt']).resolve() != previous_attempt:
        raise ValueError('Predecessor attempt differs from frozen job')
    if base.sha(job['config_path']) != base.sha(prior['config_path']):
        raise ValueError('Predecessor config bytes changed')
    source_path = Path(job['controlled_spec_path'])
    if base.sha(source_path) != job['controlled_spec_sha256']:
        raise ValueError('Controlled source spec changed')
    source = read(source_path)
    oldspec = read(prior['controlled_spec_path'])
    if source != {**oldspec, 'config_path': job['config_path']}:
        raise ValueError('Only controlled config location may change')
    # This validates the old same-family target, native identities, protocol,
    # prefix, measured budget, route, and transport without modifying old files.
    ORIGINAL_VALIDATE({**prior, 'campaign_root': str(old)}, previous_attempt / 'native')
    target = Path(source['target_reference_path'])
    raw = target.read_bytes()
    copied = base.target_path(root, job['controlled_prefix_key'])
    immutable_bytes(copied, raw)
    runtime_spec = {**source, 'target_reference_path': str(copied)}
    runtime_path = out / 'recovery-controlled-spec.json'
    base.immutable_json(runtime_path, runtime_spec)
    delegated = {**copy.deepcopy(job), 'controlled_target_root': str(root),
                 'control_target_path': str(copied), 'controlled_spec_path': str(runtime_path),
                 'controlled_spec_sha256': base.sha(runtime_path)}
    result = ORIGINAL_VALIDATE(delegated, out)
    base.immutable_json(out / 'predecessor-target-recovery.json', {
        'version': VERSION, 'previous_plan': str(oldplan), 'previous_plan_sha256': base.sha(oldplan),
        'source_target': str(target), 'source_target_sha256': base.sha(target),
        'copied_target': str(copied), 'copied_target_sha256': base.sha(copied),
        'target_bytes_unchanged': raw == copied.read_bytes(),
        'source_spec_sha256': job['controlled_spec_sha256'],
        'runtime_spec_sha256': base.sha(runtime_path), 'all_v8_validation_retained': True})
    return result


def main():
    with patch.object(base, 'validate', validate):
        base.main()


if __name__ == '__main__':
    main()
