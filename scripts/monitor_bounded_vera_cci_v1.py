#!/usr/bin/env python3
"""Observe only this bounded retry deployment; stop proven drained CCIs once."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import signal
import time
import yaml

from lab import ROOT
from run_bc_campaign_v3 import atomic, identity
from bc_route_runtime_v1 import immutable_json
from replace_sco_bc_v3_after_reader_ops import create_cli
from provision_bounded_vera_retry_v1 import RECEIPTS, app_name
from prepare_bounded_vera_retry_v1 import DEFAULT_ROOT
from monitor_rq3_cci7_lifecycle import read, require, same_identity, same_host, FIELDS

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def assess_local(root,uid,marker,shard):
    strategy = "shard-"+str(shard)
    root=Path(root).resolve();marker=Path(marker)
    if not marker.exists():return {'eligible':False,'reason':'launch_marker_absent_observe_only'}
    candidates=list((root/'runtime/nodes').glob('app-'+uid+'-*/'+strategy+'/bootstrap.json'))
    if not candidates:return {'eligible':False,'reason':'no_bootstrap_evidence_unknown_not_safe_to_stop'}
    require(len(candidates)==1,'Ambiguous node/epoch; no stop')
    bp=candidates[0];b=read(bp);ep=bp.parent/'exit.json'
    require(b.get('hostname','').startswith('app-'+uid+'-'),'Bootstrap host not bound to CCI UID')
    require(bp.parent.parent.name==b['hostname']+'-'+b.get('boot_id',''),'Node-directory identity mismatch')
    require(Path(b.get('campaign_root','/missing')).resolve()==root and b.get('strategy')==strategy and b.get('shard')==shard,'Bootstrap scope mismatch')
    require(b.get('version')=='bounded-vera-retry-bootstrap-v1','Unexpected bootstrap version')
    require(b.get('plan_sha256')==sha(root/'plan.json'),'Bootstrap plan differs')
    if not ep.exists():return {'eligible':False,'reason':'bootstrap_not_exited','bootstrap_path':str(bp)}
    e=read(ep)
    require(e.get('hostname')==b['hostname'] and e.get('boot_id')==b['boot_id'] and e.get('scale')==strategy,'Bootstrap exit identity mismatch')
    require(isinstance(e.get('finished_at_unix'),(int,float)) and e['finished_at_unix']>=b.get('started_at_unix',float('inf')),'Bootstrap exit predates current epoch')
    require(isinstance(e.get('bootstrap_exit_code'),int) and not isinstance(e['bootstrap_exit_code'],bool),'Unknown bootstrap exit')
    require(e.get('native_processes_signaled') is False,'Bootstrap native termination unknown')
    controllers=[]
    for p in (root/'controllers').glob('*/*/maintenance.json'):
        m=read(p)
        if m.get('hostname')==b['hostname'] or (m.get('boot_id')==b['boot_id'] and m.get('pid_namespace')==b.get('pid_namespace')):
            controllers.append((p,m))
    claims=[]
    for p in (root/'jobs/hermes/visual').glob('*/claim/owner.json'):
        o=read(p)
        if o.get('hostname')==b['hostname']:claims.append((p,o))
    evidence={'bootstrap_path':str(bp),'bootstrap_sha256':sha(bp),'bootstrap_exit_path':str(ep),'bootstrap_exit_sha256':sha(ep),'hostname':b['hostname'],'boot_id':b['boot_id'],'pid_namespace':b.get('pid_namespace')}
    for p in (root/'cells/hermes/visual/slots').glob('*/owner.json'):
        if read(p).get('hostname')==b['hostname']:raise ValueError('Bound host still owns a scale slot')
    if b.get('controller_pid') is None:
        require(e.get('controller_exit_code') is None and e['bootstrap_exit_code']!=0,'No proven pre-controller failure')
        require(not controllers and not claims,'Controller/claim evidence exists despite pre-controller failure')
        return {'eligible':True,'reason':'bootstrap_failed_before_controller_no_native_claims','evidence':evidence,'owned_claims':0,'failure_recorded':True}
    require(len(controllers)==1,'Exactly one bound controller required')
    mp,m=controllers[0]
    require(same_host(m,b) and m.get('pid')==b['controller_pid'],'Controller and bootstrap identities differ')
    require(m.get('shard')==shard and m.get('controller_id')==mp.parent.name,'Controller scope/directory mismatch')
    require(m.get('plan_sha256')==b['plan_sha256'],'Controller plan differs')
    xp=mp.parent/'exit.json'
    if not xp.exists():return {'eligible':False,'reason':'controller_exit_missing','evidence':evidence}
    x=read(xp)
    require(same_identity(m,x),'Controller exit identity mismatch')
    require(x.get('drained') is True,'Controller not drained')
    require(isinstance(e.get('controller_exit_code'),int),'Controller exit code unknown')
    require(isinstance(x.get('at'),(int,float)) and b['started_at_unix']<=x['at']<=e['finished_at_unix'],'Controller exit outside bootstrap epoch')
    # A stale pre-exit status may still say >0; the terminal drain proof and all
    # owned attempts are authoritative. A newer nonzero status is contradictory.
    sp=mp.parent/'status.json'
    if sp.exists():
        s=read(sp);require(same_identity(m,s),'Controller status identity mismatch')
        require(not (s.get('at',0)>x['at'] and (s.get('active_local',0)!=0 or s.get('reserved_not_started'))),'Post-exit controller activity')
    verified=[]
    for cp,o in claims:
        require(same_identity(m,o),'Another controller/epoch owns claims on bound host')
        jobdir=cp.parent.parent;attempt=jobdir/'attempts/attempt_001';rp=attempt/'result.json'
        require(rp.exists(),'Owned attempt lacks terminal result')
        r=read(rp)
        require(r.get('job_id')==o.get('job_id'),'Result/claim job mismatch')
        require(r.get('status') in ('completed','failed','timeout','interrupted','not_started'),'Unknown/nonterminal prediction')
        require(r.get('slot_released') is True and r.get('unconfirmed_child_termination')==[],'Native child termination unconfirmed')
        verified.append({'job_id':o['job_id'],'result_path':str(rp),'result_sha256':sha(rp),'claim_sha256':sha(cp)})
    require(isinstance(x.get('launched'),int) and len(claims)>=x['launched'],'Claim coverage below controller launches')
    # No surviving owned slot may hide an unaccounted native task.
    for p in (root/'cells/hermes/visual/slots').glob('*/owner.json'):
        if read(p).get('hostname')==b['hostname']:raise ValueError('Bound host still owns a scale slot')
    evidence.update(controller_maintenance_path=str(mp),controller_maintenance_sha256=sha(mp),controller_exit_path=str(xp),controller_exit_sha256=sha(xp),controller_identity={k:m[k]for k in FIELDS},owned_attempts=verified)
    return {'eligible':True,'reason':'bootstrap_and_exact_controller_exited_all_owned_native_confirmed_terminal','evidence':evidence,'owned_claims':len(claims),'controller_failed':e['controller_exit_code']!=0}

def query_app(name, invoke=create_cli):
    result = invoke([str(ROOT/'.tools/sco-tj/cli/sco'), 'cci', 'apps', 'describe', name,
                     '--workspace-name', 'rl', '--profile', 'agentcontextlab-tj', '-o', 'json'])
    require(result.get('returncode') == 0, 'CCI describe unavailable')
    value = json.loads(result['stdout'])
    require(value.get('name') == name and value.get('uid'), 'Application identity unavailable')
    return value


def cycle(shard, live=False, invoke=create_cli, receipts=RECEIPTS, expected_root=DEFAULT_ROOT,
          cache=None, clock=time.time):
    name = app_name(shard); directory = Path(receipts)/name; area = directory/'lifecycle'
    if not (directory/'response.json').exists():
        return {'shard':shard, 'name':name, 'state':'not_submitted'}
    response = read(directory/'response.json')
    require(response.get('state') == 'submitted', 'Creation unknown/rejected; no automatic retry')
    prepared = read(directory/'prepared.json'); request = read(directory/'request.json')
    root = Path(prepared['root']).resolve()
    require(root == Path(expected_root).resolve(), 'Wrong campaign root')
    require(prepared['shard'] == shard and request['shard'] == shard, 'Deployment shard mismatch')
    require(prepared['name'] == name and request['name'] == name, 'Deployment name mismatch')
    require(request['plan_sha256'] == prepared['plan_sha256'] == sha(root/'plan.json'), 'Plan binding changed')
    require(request['config_sha256'] == prepared['config_sha256'] == sha(prepared['config_path']), 'Configuration binding changed')
    marker = Path(prepared['launch_marker'])
    if not marker.exists(): return {'shard':shard,'name':name,'state':'waiting_for_launch_marker'}
    require(read(marker).get('plan_sha256') == prepared['plan_sha256'], 'Launch marker plan binding missing/changed')
    cached = cache.get(name) if cache is not None else None
    if cached is None or clock()-cached['at'] >= 120:
        platform = query_app(name, invoke)
        if cache is not None: cache[name] = {'at':clock(),'platform':platform}
    else: platform = cached['platform']
    uid = platform['uid']; binding = area/'binding.json'
    desired = yaml.safe_load(Path(prepared['config_path']).read_text())
    expected = desired['template']['containers'][0]
    actual = platform['template']['containers'][0]
    require(actual['command'] == expected['command'] and actual['image_path'] == expected['image_path'], 'Platform command/image changed')
    if binding.exists():
        bound = read(binding)
        require(bound['uid'] == uid and bound['name'] == name and bound['plan_sha256'] == prepared['plan_sha256']
                and bound['config_sha256'] == prepared['config_sha256'], 'Existing UID/plan/config binding changed')
    else:
        immutable_json(binding, {'name':name,'uid':uid,'shard':shard,'plan_sha256':prepared['plan_sha256'],
                                 'config_sha256':prepared['config_sha256'],'created_at_unix':clock()})
    row = {'shard':shard,'name':name,'uid':uid,'platform_state':platform.get('state'),
           'ready_replicas':platform.get('ready_replicas'),'state':'watching'}
    if platform.get('state') in ('SUSPENDED','STOPPED'): return {**row,'state':'stopped'}
    if (area/'stop-request.json').exists(): return {**row,'state':'stop_attempted_never_repeated'}
    assessment = assess_local(root, uid, marker, shard)
    row.update(eligible=assessment['eligible'], reason=assessment['reason'])
    # Failure is visible and never launches a replacement. A proven pre-controller
    # failure can still qualify for stopping its idle allocation below.
    if platform.get('state') in ('FAILED','ERROR','DEGRADED'):
        row['generation_failed'] = True
    if assessment['eligible'] and live:
        fresh = query_app(name, invoke)
        require(fresh['uid'] == uid and fresh['name'] == name, 'UID changed immediately before stop')
        container = fresh['template']['containers'][0]
        require(container['command'] == expected['command'] and container['image_path'] == expected['image_path'], 'Command/image changed before stop')
        if fresh.get('state') in ('SUSPENDED','STOPPED'): return {**row,'state':'stopped'}
        assessment = assess_local(root, uid, marker, shard)
        require(assessment['eligible'], 'Drain proof changed before stop')
        require(sha(root/'plan.json') == prepared['plan_sha256'] and sha(prepared['config_path']) == prepared['config_sha256'] and read(marker).get('plan_sha256') == prepared['plan_sha256'], 'Plan/config/marker changed before stop')
        immutable_json(area/'stop-request.json', {'at':clock(),'name':name,'uid':uid,'shard':shard,
            'plan_sha256':prepared['plan_sha256'],'evidence':assessment,'operator':identity(),
            'source_sha256':sha(__file__),'automatic_retry':False})
        result = invoke([str(ROOT/'.tools/sco-tj/cli/sco'), 'cci', 'apps', 'stop', name,
                         '--workspace-name','rl','--profile','agentcontextlab-tj'])
        atomic(area/'stop-response.json', {**result,'at':clock()})
        row['state'] = 'stop_submitted' if result.get('returncode') == 0 else 'stop_unknown_or_rejected_no_retry'
        if cache is not None: cache.pop(name, None)
    return row


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--shards',type=int,choices=range(3),nargs='+',default=list(range(3)))
    p.add_argument('--watch',action='store_true'); p.add_argument('--live',action='store_true'); args=p.parse_args()
    if args.live and not args.watch: p.error('Official stop requires both --watch and --live')
    if len(set(args.shards)) != len(args.shards): p.error('Duplicate shard')
    area=RECEIPTS/'lifecycle'; area.mkdir(parents=True,exist_ok=True)
    lock=(area/'observer.lock').open('a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    generation=area/'generations'/str(time.time_ns()); generation.mkdir(parents=True)
    immutable_json(generation/'service.json', {**identity(),'at':time.time(),'source_sha256':sha(__file__),
        'shards':args.shards,'watch':args.watch,'live':args.live,'cloud_poll_seconds':120,'local_poll_seconds':30})
    stopped=False; cache={}
    def stop(*unused):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
    while not stopped:
        rows=[]
        for shard in args.shards:
            try: row=cycle(shard,args.live,cache=cache)
            except Exception as exc: row={'shard':shard,'state':'unknown_no_stop','error_type':type(exc).__name__,'reason':str(exc)}
            rows.append(row)
        result={'at':time.time(),'shards':rows,'live':args.live,'model_calls':0,'auto_create':False,'auto_prediction_retry':False}
        atomic(area/'status.json',result)
        with (generation/'history.jsonl').open('a') as f: f.write(json.dumps(result)+'\n')
        if not args.watch or all(r['state']=='stopped' for r in rows): break
        until=time.monotonic()+30
        while not stopped and time.monotonic()<until: time.sleep(.5)
    atomic(generation/'exit.json',{'at':time.time(),'stop_requested':stopped})


if __name__ == '__main__': main()
