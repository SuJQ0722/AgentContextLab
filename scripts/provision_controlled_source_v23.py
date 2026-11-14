"""Two independently bound 8c32g / 16-worker controlled baseline CCIs.

Preparation is offline. Creation and activation are explicit and never replayed
after an unknown cloud response. Model secrets remain in existing local files.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shlex
import time

import yaml
from lab import ROOT
from bc_route_runtime_v1 import immutable_json
import provision_mmbc_cci_v1 as cloud

DEFAULT = ROOT / 'outputs/controlled-mmbc-vera-nontimeout-summary-v23'
OUT = ROOT / 'outputs/cloud-runtime/controlled-mmbc-summary-v23'
TEMPLATE = ROOT / 'outputs/cloud-runtime/seven-page-runtime-v11-rsi/acl-v11r-rsi-bc-hermes/config.yaml'
METHODS = ('summary',)
BOOTSTRAP = ROOT / 'scripts/bootstrap_controlled_source_v23.py'
NETWORK = ROOT / 'scripts/network_entry_v13.py'
RUNNER = ROOT / 'scripts/controlled_mmbc_source_v23.py'


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(condition, reason):
    if not condition: raise ValueError(reason)


def template_value(template=TEMPLATE):
    value = copy.deepcopy(yaml.safe_load(Path(template).read_text()))
    require(value.get('replicas') == 1, 'One CCI replica required')
    require(value['template']['resource_spec'] == {'name': 'N4lS.Iu.I80.8c32g'}, '8 CPU / 32 GiB required')
    cs = value['template']['containers']; require(len(cs) == 1, 'One container required')
    c = cs[0]
    require(c['resource_request'] == {'cpu': '8', 'memory': '32GiB'} and c.get('env') == [], 'Resource/env contract changed')
    require(c['image_path'] == 'registry.cn-tj-01.sensecore.cn/ccr-zuhu2026/sjq-dev-cpu:sjq-dev-20261108063401', 'Private image changed')
    mounts = c['volume_mounts']; require(len(mounts) == 1, 'Exactly one mount required')
    require(mounts[0]['id'] == '019ed8e0-f4f8-71f7-830c-f8a1e667a9ec' and mounts[0]['mount_path'] == '/mnt/afs_agents' and mounts[0]['subdir'] == '/', 'afs_agents mount changed')
    require(value['scheduling']['priority'] == 'NORMAL', 'Priority changed')
    return value


def prepare(method, root=DEFAULT, out=OUT, pool='design'):
    require(method in METHODS, 'Only the two authorized text/native methods')
    root = Path(root).resolve(); out = Path(out).resolve()
    require(root == DEFAULT.resolve(), 'Unexpected experiment root')
    plan = read(root / 'plan.json')
    from controlled_mmbc_source_v23 import validate_plan
    validate_plan(root, plan)
    name = 'acl-controlled23-' + method
    directory = out / name; directory.mkdir(parents=True, exist_ok=True)
    marker = directory / 'launch-ready.json'
    value = template_value(); value['resource_pool']['name'] = pool; value['display_name'] = name
    command = ['/opt/conda/bin/python', str(NETWORK), '--target', str(BOOTSTRAP),
               '--root', str(root), '--method', method, '--concurrency', '16', '--live']
    shell = 'while [ ! -f ' + shlex.quote(str(marker)) + ' ]; do sleep 3; done; cd ' + shlex.quote(str(ROOT)) + ' && ' + shlex.join(command) + '; exec sleep infinity'
    value['template']['containers'][0].update(name='controlled-' + method, command=['/bin/bash', '-c', shell])
    path = directory / 'config.yaml'; raw = yaml.safe_dump(value, sort_keys=False).encode()
    if path.exists(): require(path.read_bytes() == raw, 'Prepared cloud config changed')
    else: path.write_bytes(raw)
    record = {'version': 'controlled-source-cloud-v23', 'name': name, 'method': method,
              'cell': method, 'root': str(root), 'pool': pool, 'plan_sha256': sha(root / 'plan.json'),
              'config_path': str(path), 'config_sha256': sha(path), 'launch_marker': str(marker),
              'cpu': 8, 'memory_gib': 32, 'concurrency': 16, 'new_attempts_per_slot': 1,
              'runtime_sources_sha256': {str(p): sha(p) for p in (BOOTSTRAP, NETWORK, RUNNER, ROOT / 'scripts/preflight_bc_v3_web.py')},
              'automatic_create_replay': False}
    immutable_json(directory / 'prepared.json', record)
    return record


def bind(record):
    answer = cloud.describe(record['name']); require(answer.get('returncode') == 0, 'CCI identity unavailable')
    value = json.loads(answer['stdout']); expected = yaml.safe_load(Path(record['config_path']).read_text())
    require(value['name'] == record['name'] and value.get('uid'), 'CCI identity mismatch')
    require(value['resource_pool']['name'] == record['pool'], 'CCI pool mismatch')
    require(len(value['template']['containers']) == 1, 'Container count changed')
    actual = value['template']['containers'][0]; wanted = expected['template']['containers'][0]
    for key in ('command', 'image_path', 'env', 'resource_request'):
        require(actual[key] == wanted[key], 'Cloud ' + key + ' changed')
    require(len(actual['volume_mounts']) == 1, 'Mount count changed')
    for key in ('id', 'mount_path', 'subdir'):
        require(actual['volume_mounts'][0][key] == wanted['volume_mounts'][0][key], 'Mount ' + key + ' changed')
    directory = Path(record['config_path']).parent
    immutable_json(directory / 'binding.json', {'uid': value['uid'], 'name': value['name'],
                   'plan_sha256': record['plan_sha256'], 'config_sha256': record['config_sha256']})
    return value


def launch(record, activate=False):
    from controlled_mmbc_source_v23 import validate_plan
    root = Path(record['root']); plan = read(root / 'plan.json'); validate_plan(root, plan)
    require(sha(root / 'plan.json') == record['plan_sha256'], 'Plan changed')
    for path, digest in record['runtime_sources_sha256'].items(): require(sha(path) == digest, 'Runtime changed')
    response = cloud.submit(record)
    require(response['state'] in ('submitted', 'existing_request_never_repeated'), 'Cloud creation unconfirmed; never replay')
    receipt = read(Path(record['config_path']).parent / 'response.json')
    require(receipt.get('state') == 'submitted' and receipt.get('returncode') == 0, 'Creation not confirmed')
    value = bind(record)
    if activate:
        immutable_json(Path(record['launch_marker']), {'at': time.time(), 'uid': value['uid'],
                       'method': record['method'], 'plan_sha256': record['plan_sha256'],
                       'runtime_sources_sha256': record['runtime_sources_sha256'], 'user_authorized_text_arms_only': True})
    return {'name': record['name'], 'uid': value['uid'], 'state': value['state'], 'activated': activate}


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--method', choices=METHODS, required=True)
    p.add_argument('--root', type=Path, default=DEFAULT); p.add_argument('--pool', default='design')
    p.add_argument('--create', action='store_true'); p.add_argument('--activate', action='store_true'); args = p.parse_args()
    require(not args.activate or args.create, 'Activation requires confirmed creation')
    record = prepare(args.method, args.root, pool=args.pool)
    print(json.dumps(launch(record, args.activate) if args.create else {'prepared': record, 'model_calls': 0, 'cloud_mutations': 0}))


if __name__ == '__main__': main()
