"""Transfer unstarted V18 reservations; never grant another paid attempt."""
import hashlib
import json
from pathlib import Path
import recovery_once_contract_v18 as original

VERSION = 'mmbc-recent10-pending-v23'
CUTOFF, DEADLINE = original.CUTOFF, original.DEADLINE
IDENTITY = original.IDENTITY
digest = original.digest
dispatch_allowed = original.dispatch_allowed
TRANSPORT = 'core-page-caps-then-recent-ten-v22'


def bound(path, expected):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Migration evidence changed: ' + str(path))
    return json.loads(raw)


def validate_retry(spec, config):
    for row in (spec, config):
        if row.get('one_pass_version') != VERSION:
            raise ValueError('Explicit pending-only migration version required')
        if row.get('native_image_policy') != 'core_recent10' or row.get('core_transport_version') != TRANSPORT:
            raise ValueError('Explicit core recent-ten policy required')
    original.validate_retry({**spec, 'one_pass_version': original.VERSION},
                            {**config, 'one_pass_version': original.VERSION})


def validate_turns(spec, config):
    validate_retry(spec, config)
    return original.validate_turns({**spec, 'one_pass_version': original.VERSION},
                                   {**config, 'one_pass_version': original.VERSION})


def validate_transfer(spec, manifest):
    if manifest.get('version') != VERSION or manifest.get('transferred_existing_grant') is not True:
        raise ValueError('Not a transfer of an unused grant')
    row = manifest['jobs'][spec['slot_id']]
    root = Path(row['source_campaign_root']).resolve()
    if Path(row['destination_root']).resolve() != Path(spec['campaign_root']).resolve():
        raise ValueError('Frozen transfer destination differs')
    if Path(row['source_plan_path']).resolve() != root / 'plan.json':
        raise ValueError('Source plan/root mismatch')
    plan = bound(row['source_plan_path'], row['source_plan_sha256'])
    matches = [j for j in plan['jobs'] if j['slot_id'] == spec['slot_id']]
    if len(matches) != 1:
        raise ValueError('Original reservation must be unique')
    source = matches[0]
    original.validate_authorization({**source, 'campaign_root': str(root)})
    for key in ('job_id', 'model', 'harness', 'strategy', 'question_id', 'repeat',
                'slot_id', 'prior_attempts_consumed', 'new_authorized_ordinal'):
        if spec.get(key) != source.get(key):
            raise ValueError('Transferred identity/ordinal changed: ' + key)
    if digest(spec['prior_attempt_costs']) != digest(source['prior_attempt_costs']):
        raise ValueError('Transferred historical costs changed')
    stop = Path(row['stop_path']).resolve()
    if stop != root / 'STOP':
        raise ValueError('Whole old controller dispatch must remain stopped')
    if hashlib.sha256(stop.read_bytes()).hexdigest() != row['stop_sha256']:
        raise ValueError('Old dispatch stop changed')
    status_path = Path(row['source_controller_status_path']).resolve()
    if not status_path.is_relative_to(root / 'controllers'):
        raise ValueError('Source controller proof outside original root')
    status = json.loads(status_path.read_text())
    if status.get('controller_id') != row['source_controller_id'] or status.get('stop_dispatch') is not True:
        raise ValueError('Old controller has not acknowledged dispatch stop')
    if status.get('reserved_not_started') == source['job_id']:
        raise ValueError('Old controller reserved this task')
    jobdir = root / 'jobs' / source['job_id']
    if (jobdir / 'claim').exists() or (jobdir / 'spec.json').exists():
        raise ValueError('Original task was claimed; migration forbidden')
    attempts = jobdir / 'attempts'
    if attempts.exists() and any(attempts.iterdir()):
        raise ValueError('Original task has attempt artifacts; migration forbidden')
    return source


def validate_authorization(spec):
    if (spec.get('benchmark'), spec.get('harness'), spec.get('strategy')) != ('mmbc100', 'hermes', 'visual'):
        raise ValueError('Only pending MMBC Hermes VERA may migrate')
    auth = bound(spec['one_pass_authorization_path'], spec['one_pass_authorization_sha256'])
    if (auth.get('version') != VERSION or auth.get('user_authorized') is not True
            or auth.get('transferred_existing_grant') is not True
            or type(auth.get('additional_attempts_per_slot')) is not int
            or auth['additional_attempts_per_slot'] != 0
            or auth.get('cutoff_utc') != CUTOFF or auth.get('deadline_utc') != DEADLINE):
        raise ValueError('Migration must not add a new attempt or deadline')
    row = auth['jobs'][spec['slot_id']]
    for key in IDENTITY:
        if row.get(key) != spec.get(key):
            raise ValueError('Migrated authorization identity differs: ' + key)
    if Path(row['destination_root']).resolve() != Path(spec['campaign_root']).resolve():
        raise ValueError('Migration destination differs')
    if row.get('dispatch_allowed') is not True or row.get('active_at_cutoff') is not False or row.get('completed_retained') is not False:
        raise ValueError('Only unstarted reservations may migrate')
    if row.get('prior_attempts_consumed') != spec['prior_attempts_consumed'] or row.get('prior_cost_ledger_sha256') != digest(spec['prior_attempt_costs']):
        raise ValueError('Migrated cost ledger differs')
    manifest = bound(spec['migration_manifest_path'], spec['migration_manifest_sha256'])
    validate_transfer(spec, manifest)
    return auth
