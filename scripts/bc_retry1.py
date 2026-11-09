"""Explicit one-pass recovery ledger; originals are never edited or selected by score."""
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from run_bc_campaign_v3 import ROOT, atomic, identity, job_state, now
from bc_route_runtime_v1 import RoutePlan, immutable_json

VERSION = 'bc-v3-explicit-retry1'
DEFAULT_ROOT = ROOT / 'outputs/campaigns/bc100-r3-hermes-parity-v3-retry1'
PARENT = ROOT / 'outputs/campaigns/bc100-r3-hermes-parity-v3'
SOURCES = ('scripts/bc_retry1.py', 'scripts/run_bc_retry1.py',
           'scripts/run_bc_retry1_trial.py', 'scripts/bootstrap_bc_retry1.py')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_ledger(root, verify_sources=True):
    root = Path(root)
    ledger = json.loads((root / 'retry-ledger.json').read_text())
    if ledger.get('version') != VERSION or ledger.get('max_additional_attempts') != 1:
        raise ValueError('Explicit one-retry authorization ledger required')
    for filename in ('plan.json', 'experiment.json', 'cohort.jsonl'):
        if sha(root / filename) != ledger['frozen_sha256'][filename]:
            raise ValueError('Frozen retry input changed: ' + filename)
        if sha(Path(ledger['parent_root']) / filename) != ledger['frozen_sha256'][filename]:
            raise ValueError('Parent scientific input changed')
    if sha(root / 'route-plan-v1.json') != ledger['route_plan_sha256']:
        raise ValueError('Retry route plan changed')
    if verify_sources:
        for name, expected in ledger['implementation_sha256'].items():
            if sha(ROOT / name) != expected:
                raise ValueError('Retry operational source changed: ' + name)
    entries = ledger['entries']
    if len({e['job_id'] for e in entries}) != len(entries):
        raise ValueError('Duplicate retry job')
    return ledger


def validate_entry(root, job_id):
    ledger = load_ledger(root)
    matches = [e for e in ledger['entries'] if e['job_id'] == job_id]
    if len(matches) != 1:
        raise ValueError('Job is not in the explicit retry selection')
    entry = matches[0]
    parent_result = Path(entry['parent_attempt']) / 'result.json'
    if entry['parent_result_sha256']:
        if sha(parent_result) != entry['parent_result_sha256']:
            raise ValueError('Parent result changed after retry selection')
        if json.loads(parent_result.read_text()).get('status') == 'completed':
            raise ValueError('Completed originals must not be retried')
    elif parent_result.exists():
        raise ValueError('Previously unknown parent acquired a result; review selection')
    proof = Path(ledger['termination_evidence_path'])
    if sha(proof) != ledger['termination_evidence_sha256']:
        raise ValueError('Predecessor termination evidence changed')
    return entry


def publish_claim(root, job, owner, routes, cap=32):
    """Publish a complete claim directory atomically, without shared-AFS flock.

    Temporary directories are outside the canonical claim path. A crash holds
    capacity and is never interpreted as authorization for a second dispatch.
    """
    root = Path(root)
    validate_entry(root, job['job_id'])
    metadata = routes.claim_metadata(job)
    jobdir = root / 'jobs' / job['job_id']
    jobdir.mkdir(parents=True, exist_ok=True)
    if job_state(jobdir) != 'pending':
        return None
    cell = root / 'cells' / job['harness'] / job['strategy'] / 'slots'
    cell.mkdir(parents=True, exist_ok=True)
    slot = None
    for i in range(cap):
        candidate = cell / f'{i:02}'
        try:
            candidate.mkdir()
            slot = candidate
            break
        except FileExistsError:
            pass
    if slot is None:
        return None
    record = {**owner, **metadata, 'job_id': job['job_id'], 'claimed_at': now()}
    atomic(slot / 'owner.json', record)
    staging = jobdir / ('.claim-staging-' + uuid.uuid4().hex)
    staging.mkdir()
    atomic(staging / 'owner.json', {**record, 'slot': str(slot)})
    try:
        os.rename(staging, jobdir / 'claim')
    except OSError:
        # Only a complete winner is treated as contention. Preserve uncertain
        # publication/IO failures for diagnosis, never recycle their capacity.
        if not (jobdir / 'claim/owner.json').exists():
            raise
        (staging / 'owner.json').unlink()
        staging.rmdir()
        (slot / 'owner.json').unlink()
        slot.rmdir()
        return None
    return jobdir, slot


def prepare_retry(root, evidence):
    """Called once after reviewed official termination and local process proof."""
    root = Path(root).resolve()
    if root.exists():
        raise ValueError('Refuse to overwrite an existing recovery root')
    proof = json.loads(Path(evidence).read_text())
    if proof.get('version') != 'bc-v3-retry-predecessors-terminated-v1':
        raise ValueError('Wrong predecessor proof')
    if len(proof['current_cloud']) != 10 or any(x['state'] not in ('SUCCEEDED', 'FAILED', 'STOPPED') for x in proof['current_cloud']):
        raise ValueError('All ten predecessor namespaces must have terminated')
    if proof.get('local_native_alive') is not False or proof.get('old_unknown_namespace_verified') is not True:
        raise ValueError('Local and older unknown namespace evidence required')
    for row in [*proof['current_cloud'], *proof['older_cloud']]:
        path = Path(row['describe_path'])
        if sha(path) != row['describe_sha256']:
            raise ValueError('Official describe artifact changed')
        described = json.loads(path.read_text())
        if (described.get('name') != row['name'] or described.get('uid') != row['uid']
                or described.get('state') != row['state'] or described.get('workspace_name') != 'rl'
                or row['state'] not in ('SUCCEEDED', 'FAILED', 'STOPPED')):
            raise ValueError('Official predecessor termination does not match')
    from run_bc_campaign_v3 import owner_alive
    for row in proof['local_unknown_claims']:
        if owner_alive(row) is not False:
            raise ValueError('Local predecessor identity is alive or unverified')
    root.mkdir(parents=True)
    for name in ('plan.json', 'experiment.json', 'cohort.jsonl'):
        (root / name).write_bytes((PARENT / name).read_bytes())
    original_plan = json.loads((root / 'plan.json').read_text())
    final_routes = json.loads((PARENT / 'route-plan-v2.json').read_text())
    route = json.loads((PARENT / 'route-plan-v1.json').read_text())
    route.update(assignments=final_routes['assignments'], created_at_unix=time.time(),
                 basis='Explicit retry1 root: exact final parent routes2 pair assignments, no route reassignment',
                 source_route_plan_path=str(PARENT / 'route-plan-v2.json'),
                 source_route_plan_sha256=sha(PARENT / 'route-plan-v2.json'))
    immutable_json(root / 'route-plan-v1.json', route)
    (root / 'route-plan-v1.sha256').write_text(sha(root / 'route-plan-v1.json') + '\n')
    entries = []
    for job in original_plan['jobs']:
        attempt = PARENT / 'jobs' / job['job_id'] / 'attempts/attempt_001'
        result = attempt / 'result.json'
        value = json.loads(result.read_text()) if result.exists() else {}
        if value.get('status') == 'completed':
            continue
        entries.append({'job_id': job['job_id'], 'parent_attempt': str(attempt),
                        'parent_status': value.get('status', 'unknown' if attempt.exists() else 'pending'),
                        'parent_result_sha256': sha(result) if result.exists() else None,
                        'reason': 'User authorized exactly one additional attempt for every non-completed job',
                        'retry_attempt': str(root / 'jobs' / job['job_id'] / 'attempts/attempt_001')})
    ledger = {'version': VERSION, 'created_at': now(), 'parent_root': str(PARENT),
              'max_additional_attempts': 1, 'planned_scientific_jobs': 3000,
              'selected_jobs': len(entries), 'entries': entries,
              'frozen_sha256': {n: sha(root / n) for n in ('plan.json', 'experiment.json', 'cohort.jsonl')},
              'route_plan_sha256': sha(root / 'route-plan-v1.json'),
              'implementation_sha256': {n: sha(ROOT / n) for n in SOURCES},
              'termination_evidence_path': str(Path(evidence).resolve()),
              'termination_evidence_sha256': sha(evidence),
              'analysis_policy': 'Keep first-pass results. Operational recovered view always selects retry1 for selected jobs, regardless of grade; otherwise original. Never best-of-two or extra seeds. Include all attempt costs.',
              'resume_semantics': 'Fresh native session for each authorized extra attempt; exact interrupted-session continuation is not validated. Existing retry claims are never replayed.'}
    immutable_json(root / 'retry-ledger.json', ledger)
    RoutePlan(root).bind()
    return ledger
