#!/usr/bin/env python3
"""Resume only the ten original reviewed ACP jobs after verified Reader maintenance.

Default queries metadata and writes a dry-run report. --live permits one start
attempt per original job. A durable request without a response is UNKNOWN and
never retried automatically. No job creation, failed-trial retry, or model probe.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / 'outputs/campaigns/bc100-r3-hermes-parity-v3'
CELLS = [(h, s) for h in ('hermes', 'dsh') for s in ('none', 'summarize', 'sliding_window', 'discard', 'visual')]


def now(): return datetime.now(timezone.utc).isoformat()
def read(path): return json.loads(Path(path).read_text())
def stamp(value): return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def redact(value):
    # Never expose CLI credentials even in an error response. No --debug used.
    text = str(value)
    path = ROOT / '.state/sco/tianjin-credentials.json'
    if path.exists():
        secrets = read(path)
        for secret in secrets.values():
            if isinstance(secret, str) and secret: text = text.replace(secret, '<redacted>')
    return re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+', r'\1<redacted>', text)


def cli(sco, operation, name):
    argv = [str(sco), 'acp', 'jobs', operation, '--workspace-name', 'rl', name]
    if operation == 'describe': argv += ['--format', 'json']
    try:
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=90)
        return {'returncode': result.returncode, 'stdout': redact(result.stdout), 'stderr': redact(result.stderr)}
    except subprocess.TimeoutExpired:
        return {'returncode': None, 'error_type': 'TimeoutExpired'}
    except OSError as exc:
        return {'returncode': None, 'error_type': type(exc).__name__, 'errno': exc.errno}


def original_jobs(submissions):
    jobs = []
    for harness, strategy in CELLS:
        name = 'acl-bc-v3-' + harness + '-' + strategy.replace('_', '-')
        path = submissions / (name + '.json'); row = read(path)
        if any(row.get(k) != v for k, v in {'name': name, 'harness': harness, 'strategy': strategy,
                                          'state': 'submitted', 'returncode': 0}.items()):
            raise ValueError('Original submission receipt is missing or invalid: ' + name)
        jobs.append({'name': name, 'harness': harness, 'strategy': strategy,
                     'submission_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return jobs


def pending_count(root, plan, job):
    # Claims are permanent. Unknown, interrupted, failed, and not_started jobs
    # remain excluded even if there is no result; never infer retry permission.
    return sum(1 for row in plan['jobs'] if row['harness'] == job['harness'] and row['strategy'] == job['strategy']
               and not (root / 'jobs' / row['job_id'] / 'claim').exists()
               and not (root / 'jobs' / row['job_id'] / 'attempts').exists())


def assess(root, plan, job, description):
    result = {'name': job['name'], 'cell': job['harness'] + '/' + job['strategy'], 'eligible': False}
    if description.get('name') != job['name'] or description.get('workspace_name') != 'rl':
        return dict(result, reason='ACP identity mismatch')
    uid = description.get('uid', '')
    if not re.fullmatch(r'[0-9a-f]{32}', uid): return dict(result, reason='Missing or invalid ACP uid')
    host = 'pt-' + uid + '-worker-0'
    result.update(uid=uid, hostname=host, acp_state=description.get('state'))
    state = description.get('state')
    if state not in ('SUCCEEDED', 'STOPPED'):
        return dict(result, reason='ACP failed: manual review required' if state == 'FAILED' else 'ACP not eligible terminal')
    candidates = []
    for node in (root / 'runtime/nodes').glob(host + '-*'):
        bootstrap_path = node / (job['harness'] + '-' + job['strategy']) / 'bootstrap.json'
        if not bootstrap_path.exists(): continue
        bootstrap = read(bootstrap_path)
        if bootstrap.get('cell') == result['cell']:
            candidates.append((bootstrap.get('started_at_unix', 0), node, bootstrap_path))
    if not candidates: return dict(result, reason='Missing bound bootstrap')
    _, node, bootstrap_path = max(candidates, key=lambda x: x[0])
    exit_path = bootstrap_path.parent / 'exit.json'
    if not exit_path.exists(): return dict(result, reason='Bootstrap not durably drained')
    exited = read(exit_path)
    if exited.get('controller_exit_code') != 0 or exited.get('stopped') is not True:
        return dict(result, reason='Bootstrap exit requires manual review')
    deployments = sorted((node / 'reader-ops').glob('*/deployment.json'))
    if not deployments: return dict(result, reason='Missing Reader deployment evidence')
    deployment_path = deployments[-1]; deploy = read(deployment_path)
    proxy = deploy.get('egress_proxy', {})
    proxy_present = any(isinstance(proxy.get(k), dict) and proxy[k].get('hostname') for k in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY'))
    if not (deploy.get('state') == 'verified' and deploy.get('live') is True and deploy.get('new_slots') == 32
            and deploy.get('hostname') == host and node.name == host + '-' + deploy.get('boot_id', '')
            and deploy.get('cold_fetch', {}).get('success') is True and proxy_present):
        return dict(result, reason='Reader32/proxy/cold-fetch deployment not verified')
    if exited.get('finished_at_unix', 0) < stamp(deploy['maintenance_started_at']):
        return dict(result, reason='Bootstrap exit predates maintenance')
    telemetry_path = node / 'telemetry.json'
    if not telemetry_path.exists(): return dict(result, reason='Missing old namespace telemetry')
    telemetry = read(telemetry_path)
    if (telemetry.get('hostname') != host or telemetry.get('boot_id') != deploy['boot_id']
            or not telemetry.get('pid_namespace')):
        return dict(result, reason='Old namespace identity not proven')
    result['retired_pid_namespace'] = telemetry['pid_namespace']
    result['retired_boot_id'] = telemetry['boot_id']
    pending = pending_count(root, plan, job)
    result.update(pending=pending, node_directory=str(node), bootstrap_exit=str(exit_path),
                  reader_deployment=str(deployment_path), deployment_sha256=hashlib.sha256(deployment_path.read_bytes()).hexdigest())
    return dict(result, eligible=pending > 0, reason='Ready for one original-job start' if pending else 'No untouched pending jobs')


def start_once(receipts, job, evidence, sco, invoke=cli, stopping=lambda: False):
    directory = receipts / job['name']
    if stopping(): return {'state': 'stopping_no_start'}
    try: directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError: return {'state': 'existing_request_never_repeated'}
    request = {'requested_at': now(), 'requested_at_unix': time.time(), 'job': job, 'evidence': evidence,
               'operation': 'start', 'workspace': 'rl', 'automatic_repeat_allowed': False}
    atomic(directory / 'request.json', request)
    if evidence.get('node_directory') and evidence.get('retired_pid_namespace'):
        atomic(Path(evidence['node_directory']) / 'retired.json', {
            'hostname': evidence['hostname'], 'pid_namespace': evidence['retired_pid_namespace'],
            'boot_id': evidence['retired_boot_id'],
            'job_name': job['name'], 'retired_at': now(), 'retired_at_unix': time.time(),
            'reason': 'Verified Reader maintenance, clean bootstrap drain and ACP terminal before original-job start',
            'bootstrap_exit': evidence['bootstrap_exit'], 'reader_deployment': evidence['reader_deployment'],
            'request_receipt': str(directory / 'request.json')})
    if stopping():
        response = {'state': 'not_sent_stopping', 'completed_at': now()}
    else:
        outcome = invoke(sco, 'start', job['name'])
        response = {'state': 'accepted' if outcome.get('returncode') == 0 else 'unknown' if outcome.get('returncode') is None else 'rejected',
                    'completed_at': now(), **outcome}
    atomic(directory / 'response.json', response)
    return {'state': response['state'], 'receipt': str(directory)}


def post_start(root, job, request, description):
    result = {'state': 'awaiting_new_bootstrap', 'acp_state': description.get('state'),
              'proxy_verification': 'not_yet_proven'}
    if description.get('name') != job['name'] or description.get('workspace_name') != 'rl':
        return dict(result, state='ACP_identity_mismatch')
    if description.get('state') == 'FAILED': return dict(result, state='failed_manual_review')
    uid = description.get('uid', '')
    if not re.fullmatch(r'[0-9a-f]{32}', uid): return result
    host = 'pt-' + uid + '-worker-0'
    for node in (root / 'runtime/nodes').glob(host + '-*'):
        path = node / (job['harness'] + '-' + job['strategy']) / 'bootstrap.json'
        if not path.exists(): continue
        boot = read(path)
        if boot.get('started_at_unix', 0) <= request['requested_at_unix']: continue
        commands = boot.get('commands', {})
        controller = commands.get('controller', []); reader = commands.get('reader', [])
        expected_controller='run_bc_campaign_v3_capacity1.py' if job['harness']=='dsh' or job['strategy']=='visual' else 'run_bc_campaign_v3_io2.py'
        valid = any(Path(x).name == expected_controller for x in controller)
        valid = valid and any(Path(x).name == 'reader-text-v1-workers32.json' for x in reader)
        proxy = boot.get('reader_egress_proxy', {})
        proxy_ok = any(isinstance(proxy.get(k), dict) and proxy[k].get('hostname')
                       for k in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY'))
        readiness_path = root / 'web-readiness' / (node.name + '.json')
        ready = read(readiness_path) if readiness_path.exists() else {}
        readiness_ok = (ready.get('passed') is True and ready.get('hostname') == host
                        and node.name == host + '-' + ready.get('boot_id', '')
                        and ready.get('checked_at_unix', 0) > request['requested_at_unix']
                        and ready.get('config_sha256') == hashlib.sha256((root/'experiment.json').read_bytes()).hexdigest())
        result.update(state='bootstrap_configuration_verified' if valid else 'bootstrap_configuration_mismatch',
                      bootstrap=str(path), runtime_controller_and_reader32=valid,expected_controller=expected_controller,
                      proxy_verification='actual_reader_env_and_new_web_readiness' if proxy_ok and readiness_ok else 'not_yet_proven',
                      actual_reader_env_proxy=proxy_ok, new_web_readiness_passed=readiness_ok)
        telemetry_path = node / 'telemetry.json'
        if telemetry_path.exists():
            telemetry = read(telemetry_path)
            fresh = 0 <= time.time() - stamp(telemetry['timestamp']) <= 90
            roles = telemetry.get('processes', {}).get('core_v3_roles', {})
            result.update(telemetry_fresh=fresh, reported_trials=roles.get('trial'), reported_controllers=roles.get('controller'))
            # Process presence alone does not prove new claims; inspect only this cell.
        new_claims = 0
        for owner_path in (root / 'jobs' / job['harness'] / job['strategy']).glob('*/claim/owner.json'):
            owner = read(owner_path)
            claimed = owner.get('claimed_at', 0)
            if isinstance(claimed, str): claimed = stamp(claimed)
            if (owner.get('hostname') == host and node.name == host + '-' + owner.get('boot_id', '')
                    and claimed > request['requested_at_unix']): new_claims += 1
        result['new_claims_since_request'] = new_claims
        if valid and proxy_ok and readiness_ok and new_claims: result['state'] = 'resumed_claiming_pending'
        elif valid and new_claims: result['state'] = 'claiming_but_proxy_or_web_verification_missing'
        return result
    return result


def cycle(root, submissions, receipts, sco, live, stopping=lambda:False, invoke=cli):
    plan = read(root / 'plan.json'); rows = []
    for job in original_jobs(submissions):
        if stopping(): break
        outcome = invoke(sco, 'describe', job['name'])
        if outcome.get('returncode') != 0:
            rows.append({'name': job['name'], 'reason': 'ACP query failed', 'query_returncode': outcome.get('returncode')}); continue
        try: description = json.loads(outcome['stdout'])
        except (ValueError, KeyError):
            rows.append({'name': job['name'], 'reason': 'ACP query invalid JSON'}); continue
        directory = receipts / job['name']
        if directory.exists():
            response = read(directory/'response.json') if (directory/'response.json').exists() else {'state':'unknown'}
            row = {'name':job['name'], 'start_receipt_state':response['state'], 'automatic_repeat_allowed':False}
            if response['state'] == 'accepted' and (directory/'request.json').exists():
                try: row['post_start'] = post_start(root,job,read(directory/'request.json'),description)
                except (OSError,ValueError,TypeError,KeyError) as exc:
                    row['post_start'] = {'state':'evidence_unavailable','error_type':type(exc).__name__}
            rows.append(row); continue
        try: row = assess(root,plan,job,description)
        except (OSError,ValueError,TypeError,KeyError) as exc:
            row={'name':job['name'],'eligible':False,'reason':'Evidence incomplete or invalid','error_type':type(exc).__name__}
        if row.get('eligible') and live: row['start'] = start_once(receipts,job,row,sco,invoke,stopping)
        rows.append(row)
    return {'timestamp':now(),'mode':'live' if live else 'dry_run','jobs':rows,'model_probes':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=CAMPAIGN)
    parser.add_argument('--submissions',type=Path,default=ROOT/'outputs/cloud-runtime/submissions')
    parser.add_argument('--receipts',type=Path,default=ROOT/'outputs/cloud-runtime/reader-resume')
    parser.add_argument('--sco',type=Path,default=ROOT/'.tools/sco-tj/cli/sco')
    parser.add_argument('--watch',action='store_true');parser.add_argument('--live',action='store_true')
    args=parser.parse_args();stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while not stopped:
        try: report=cycle(args.root,args.submissions,args.receipts,args.sco,args.live,lambda:stopped)
        except (OSError,ValueError,TypeError,KeyError) as exc:
            report={'timestamp':now(),'mode':'live' if args.live else 'dry_run',
                    'state':'evidence_error_no_dispatch','error_type':type(exc).__name__}
        atomic(args.receipts/'status.json',report)
        print(json.dumps(report),flush=True)
        if not args.watch:break
        deadline=time.monotonic()+30
        while not stopped and time.monotonic()<deadline:time.sleep(.2)


if __name__=='__main__':main()
