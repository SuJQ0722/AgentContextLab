#!/usr/bin/env python3
"""Audited hot-policy cutover: pause dispatch ACK, then fixed-route cell cap16.

No process signals, model calls, new claims, source changes or route reassignment.
Existing controllers keep their child ledgers and enforce total target16.
"""
import argparse,fcntl,hashlib,json,os,socket,time,uuid
from pathlib import Path
from bc_retry1 import DEFAULT_ROOT,ROOT,load_ledger,sha
from run_bc_campaign_v3 import atomic,identity,validate_sources
from bc_route_runtime_v1 import immutable_json,SOURCE_FILES
VERSION='bc-retry1-hot-concurrency-ops2'
HOT=ROOT/'configs/cloud-dispatch-routes-v1.json'
DESIRED=ROOT/'configs/cloud-dispatch-retry1-ops2.json'
IDENTITY=('hostname','boot_id','pid_namespace','pid','start_identity')
CELLS={h+'/'+s for h in ('hermes','dsh') for s in ('none','summarize','sliding_window','discard','visual')}
def read(path):return json.loads(Path(path).read_text())
def digest(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,indent=2)+'\n').encode()
def atomic_bytes(path,raw):
    path=Path(path);tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with tmp.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
def validate_policy(d):
    old='deepseek-v4.1-flash-1017/huoshan/huoshan';sfb='deepseek-v4.1-flash-1017/zijian/sfb'
    if d.get('active_workers_per_cloud_instance')!=16 or d.get('local_target_workers')!=0 or d.get('worker_ceiling_per_instance')!=32:raise ValueError('Require cloud total16 and local0')
    if d.get('per_route_cloud_caps')!={old:16,sfb:16,'deepseek-v4.1-flash-1017/huoshan/sfc':0,'deepseek-v4.1-flash-1017/zijian/sfc':0}:raise ValueError('Unexpected route caps')
    if not d.get('per_route_local_caps') or any(v!=0 for v in d['per_route_local_caps'].values()):raise ValueError('Local dispatch must stay off')
def discover(root,hot,now=None):
    now=time.time() if now is None else now;selected=[];cells=[]
    for path in (Path(root)/'controllers').glob('*/status.json'):
        s=read(path)
        if now-s.get('heartbeat_unix',0)>90 or s.get('stop_dispatch') is True:continue
        if Path(s.get('root','/missing')).resolve()!=Path(root).resolve():raise ValueError('Controller root mismatch')
        d=s.get('dispatch_policy') or {}
        if Path(d.get('config_path','/missing')).resolve()!=Path(hot).resolve() or d.get('valid') is not True:raise ValueError('Controller not on expected hot policy')
        owner=read(path.parent/'owner.json')
        if any(owner.get(k)!=s.get(k) for k in IDENTITY):raise ValueError('Controller/owner identity mismatch')
        role=d.get('dispatch_role');selection=owner['selection']
        if role=='cloud':
            if len(selection['harness'])!=1 or len(selection['strategy'])!=1:raise ValueError('Cloud controller is not one cell')
            cell=selection['harness'][0]+'/'+selection['strategy'][0];cells.append(cell)
        elif role=='local':
            if s.get('active_local')!=0:raise ValueError('Local children must drain before per-cell16 cutover')
            if any(identity(s['pid']).get(k)!=s.get(k) for k in IDENTITY):raise ValueError('Local controller is not alive with exact identity')
            cell=None
        else:raise ValueError('Unknown dispatch role')
        selected.append({'status_path':str(path),'owner':{k:s[k] for k in IDENTITY},'cell':cell,'role':role,'before_active':s.get('active_local'),'before_by_route':s.get('active_by_route')})
    if len(cells)!=10 or set(cells)!=CELLS:raise ValueError('Require exactly one fresh controller for each of10 cells')
    if not any(c['role']=='local' for c in selected):raise ValueError('Expected fresh local controller to pause')
    return selected

def acknowledged(item,expected_sha,target):
    s=read(item['status_path']);owner=item['owner']
    if any(s.get(k)!=owner[k] for k in IDENTITY):raise ValueError('Controller identity changed during cutover')
    if time.time()-s.get('heartbeat_unix',0)>90:raise ValueError('Controller heartbeat stale during cutover')
    d=s.get('dispatch_policy') or {}
    if d.get('config_sha256')!=expected_sha or d.get('target')!=target or d.get('valid') is not True:return None
    if item['role']=='local' and s.get('active_local')!=0:raise ValueError('Local native remains active')
    return {'cell':item['cell'],'role':item['role'],'identity':owner,'at':s.get('updated_at'),'config_sha256':expected_sha,'target':target,'active_local':s.get('active_local'),'active_by_route':s.get('active_by_route'),'launches':s.get('launches')}

def await_ack(items,hot,expected_sha,cloud_target,timeout):
    until=time.monotonic()+timeout
    while True:
        if sha(hot)!=expected_sha:raise ValueError('Hot policy changed concurrently')
        checks=[acknowledged(x,expected_sha,cloud_target if x['role']=='cloud' else 0) for x in items]
        if all(checks):return checks
        if time.monotonic()>=until:raise TimeoutError('Not all controllers acknowledged policy; no automatic replacement/retry')
        time.sleep(1)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT_ROOT);p.add_argument('--desired',type=Path,default=DESIRED);p.add_argument('--live',action='store_true');p.add_argument('--ack-timeout',type=int,default=90);a=p.parse_args()
    root=a.root.resolve();ledger=load_ledger(root);plan=read(root/'plan.json');desired=read(a.desired);validate_policy(desired)
    if str(HOT.relative_to(ROOT)) in plan['definition']['implementation_sha256'] or str(HOT.relative_to(ROOT)) in ledger['implementation_sha256'] or str(HOT.relative_to(ROOT)) in SOURCE_FILES:raise ValueError('Hot config unexpectedly frozen into scientific source hashes')
    controllers=discover(root,HOT)
    if not a.live:print(json.dumps({'live':False,'cloud_cells':10,'local_controllers':sum(x['role']=='local' for x in controllers),'new_total_cell_target':16,'new_huoshan_cap':16,'new_local_target':0,'retains_children_and_claims':True}));return
    area=root/'operations'/VERSION;area.mkdir(parents=True,exist_ok=True);lock=(area/'operator.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (area/'cutover-started.json').exists():raise ValueError('Prior cutover exists; inspect receipts, never automatically replay')
    validate_sources(plan,root);controllers=discover(root,HOT)
    before=HOT.read_bytes();pause=read(HOT);pause.update(version=VERSION+'-pause',active_workers_per_cloud_instance=0,local_target_workers=0)
    for key in ('per_route_cloud_caps','per_route_local_caps'):pause[key]={r:0 for r in pause[key]}
    paused=encoded(pause);after=Path(a.desired).read_bytes()
    frozen={name:sha(root/name) for name in ('plan.json','experiment.json','cohort.jsonl','retry-ledger.json','route-plan-v1.json')}
    (area/'before-policy.json').write_bytes(before);(area/'pause-policy.json').write_bytes(paused);(area/'after-policy.json').write_bytes(after)
    immutable_json(area/'cutover-started.json',{'version':VERSION,'started_unix':time.time(),'operator':identity(),'source_sha256':sha(__file__),'controllers':controllers,'before_sha256':digest(before),'pause_sha256':digest(paused),'after_sha256':digest(after),'desired_path':str(a.desired.resolve()),'frozen_inputs_sha256':frozen,'signals_sent':0,'native_or_paid_retry':False,'scope':'Hot dispatch policy only; existing controller child ledgers, claims and fixed routes retained'})
    try:
        if HOT.read_bytes()!=before:raise ValueError('Hot policy changed before publish')
        atomic_bytes(HOT,paused);acks=await_ack(controllers,HOT,digest(paused),0,a.ack_timeout);atomic(area/'pause-ack.json',{'at':time.time(),'controllers':acks,'workers_signaled':False})
        if any(sha(root/name)!=value for name,value in frozen.items()):raise ValueError('Scientific inputs changed during pause')
        atomic_bytes(HOT,after);acks=await_ack(controllers,HOT,digest(after),16,a.ack_timeout);atomic(area/'enabled-ack.json',{'at':time.time(),'controllers':acks,'new_total_cell_target':16,'new_local_target':0,'source_sha256':sha(__file__)})
        print(json.dumps({'state':'enabled_acknowledged','cloud_cells':10,'target_per_cell':16,'local_target':0,'receipt':str(area)}))
    except BaseException as exc:
        atomic(area/'cutover-error.json',{'at':time.time(),'type':type(exc).__name__,'current_policy_sha256':sha(HOT),'no_automatic_replay':True});raise
if __name__=='__main__':main()
