#!/usr/bin/env python3
"""Controlled fixed-prefix v2: frozen 180-arm cohort, six-arm pilot gate first."""
import argparse,fcntl,gzip,hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path
from lab import ROOT,environment,python_for
from run_bc_trial import atomic,process_identity
from experiment_admission_v4 import spawn_admitted
from monitor_dsh import read_lines,sum_usage
METHODS=['visual','summary','window'];DATASETS=['browsecomp_v3','mmbrowsecomp'];THRESHOLD=16384
DEFAULT=ROOT/'outputs/experiment3/controlled-native-v4'

def digest(raw):return hashlib.sha256(raw).hexdigest()

def extract_prefix(source,out):
    """Select first measured input >= threshold, never correctness/final-answer based."""
    rows=[json.loads(l) for l in (source/'metrics/calls.jsonl').read_text().splitlines()]
    row=next((r for r in rows if r.get('purpose')=='agent' and isinstance((r.get('raw_provider_usage') or {}).get('prompt_tokens'),int)
              and r['raw_provider_usage']['prompt_tokens']>=THRESHOLD),None)
    if not row:raise ValueError('No provider-measured prefix reaches declared threshold')
    full=None;request=None
    with gzip.open(source/'metrics/requests-responses.jsonl.gz','rt') as f:
        for line in f:
            r=json.loads(line)
            if r.get('type')=='full_request':full=r['request']
            if r.get('type')=='request' and r.get('call_id')==row['call_id']:
                if full and full.get('messages')==r.get('messages') and full.get('model')==r.get('model'):request=full
                else:request={k:r[k] for k in ['model','messages','max_tokens'] if k in r}
                break
    if request is None:raise ValueError('Measured request missing from archive')
    from capture_multimodal_prefix import image_ledger
    ledger=image_ledger(request['messages'])
    if not ledger or any(not r['inline'] for r in ledger):raise ValueError('Native evidence not fully inline')
    out.mkdir(parents=True,exist_ok=True);raw=json.dumps(request,ensure_ascii=False,sort_keys=True).encode();(out/'prefix.json').write_bytes(raw)
    atomic(out/'manifest.json',{'status':'prepared','prefix_sha256':digest(raw),'source':str(source),'call_id':row['call_id'],
        'measured_prompt_tokens':row['raw_provider_usage']['prompt_tokens'],'threshold':THRESHOLD,'native_ledger':ledger,
        'selection':'First provider-measured prompt at or above16384, independent of correctness; no response/final answer included.'})


def pilot_gate(records):
    if len(records)!=6:return {'passed':False,'reason':'waiting_for_six_pilot_results'}
    groups={ds:[r for r in records if r['dataset']==ds] for ds in DATASETS};checks={}
    for ds,rows in groups.items():
        states=[r.get('control_gate',{}) for r in rows];counts=[s.get('first_actual_prompt_tokens') for s in states]
        known=len(rows)==3 and {r['method'] for r in rows}==set(METHODS) and all(isinstance(n,int) and not isinstance(n,bool) and 0<n<=THRESHOLD for n in counts)
        same=len({s.get('prefix_sha256') for s in states})==1 and all(s.get('prefix_sha256') for s in states) and len({s.get('actual_route') for s in states})==1
        natives=[s.get('native_hashes') for s in states];native_ok=bool(natives and natives[0]) and all(n==natives[0] for n in natives)
        spread=(max(counts)-min(counts))/max(counts) if known else None
        checks[ds]={'known_actual_usage':known,'identical_prefix':same,'identical_native_payloads':native_ok,'realized_spread':spread,
          'passed':bool(known and same and native_ok and spread<=.05 and all(s.get('passed') and s.get('native_identity_verified') for r,s in zip(rows,states)))}
    return {'passed':all(c['passed'] for c in checks.values()),'datasets':checks,'scope':'New fixed-prefix small-cohort continuation; not BC100 or original32k-trigger full baseline'}


def prepare(root):
    root.mkdir(parents=True,exist_ok=True)
    cfg=json.loads((ROOT/'configs/experiment.v3.review.json').read_text())
    source_model=cfg['model'];cfg['model']='deepseek-v4.1-flash-1017/zijian/sfb'
    cfg['controlled_protocol']='native-fixed-prefix-budget-fit-v4';cfg['review_approved']=True
    cfgraw=json.dumps(cfg,ensure_ascii=False,indent=2).encode();(root/'experiment.json').write_bytes(cfgraw)
    jobs=[];prefixes=[];cohort=[];historical=[]
    for ds in DATASETS:
        raw=(ROOT/'outputs/cohorts'/f'{ds}.jsonl').read_bytes();rows=[json.loads(l) for l in raw.splitlines()][:10]
        if len(rows)!=10:raise ValueError('Expected fixed ten-question cohort')
        for i,row in enumerate(rows):
            cohort.append({'dataset':ds,'ordinal':i+1,'question_id':row['id'],'question_sha256':digest(row['question'].encode())})
            for repeat in [1,2,3]:
                key=f'{ds}/q_{i+1:03d}_r{repeat:02d}';prefix=root/'prefixes'/key
                asset=(ROOT/'outputs/experiment3/prefix-capture'/ds) if (i==0 and repeat==1) else root/'collectors'/key
                spec={'native_asset_roots':[str(asset/'input-images'),str(asset/'workspace')], 'question':row['question'],'question_id':row['id'],'image':row.get('image') or [],'dataset':ds,'model':cfg['model'],
                    'config_path':str(root/'experiment.json'),'source_prefix_model':source_model if i==0 and repeat==1 else cfg['model'],
                    'explicit_route_migration':bool(i==0 and repeat==1),'threshold':THRESHOLD,'max_rounds':60,'repeat':repeat,
                    'protocolversion':'native-fixed-prefix-budget-fit-v4','prefix_path':str(prefix/'prefix.json')}
                pilot=i==0 and repeat==1
                if pilot:
                    source=ROOT/'outputs/experiment3/prefix-capture'/ds;extract_prefix(source,prefix)
                    selected=json.loads((prefix/'manifest.json').read_text())['call_id'];cost=[]
                    for call in read_lines(source/'metrics/calls.jsonl'):
                        cost.append({k:call.get(k) for k in ('call_id','purpose','model','raw_provider_usage','client_stream_seconds')})
                        if call['call_id']==selected:break
                    historical.append({'prefix_key':key,'source':str(source),'selected_call_id':selected,'calls':cost,'definition':'Historical acquisition through first provider-measured threshold call, counted once across three arms; no answer output supplied.'})
                capture=root/'collectors'/key;capture.mkdir(parents=True,exist_ok=True);atomic(capture/'spec.json',spec)
                prefixes.append({'key':key,'pilot':pilot,'spec':spec})
                for method in METHODS:
                    jobid=key+'/'+method;out=root/'jobs'/jobid;out.mkdir(parents=True,exist_ok=True)
                    atomic(out/'spec.json',{**spec,'method':method});jobs.append({'job_id':jobid,'prefix_key':key,'method':method,'dataset':ds,'pilot':pilot})
    plan={'protocol':'native-fixed-prefix-budget-fit-v4','cohort':cohort,'jobs':jobs,'prefixes':prefixes,
      'definition':{'planned_arms':180,'pilot_arms':6,'questions_per_dataset':10,'repeats':3,'methods':METHODS,'datasets':DATASETS,
                    'concurrency':4,'timeout_seconds':3600,'config_sha256':digest(cfgraw),'threshold':THRESHOLD,
                    'gate':'Both pilot triples have valid native/actualbudget evidence within5pct and<=16384; completion/accuracy separately reported, no success selection'}}
    atomic(root/'historical-prefix-acquisition.json',historical)
    atomic(root/'plan.json',plan)
    atomic(root/'fit-worker-ready.json',{'worker_script':'controlled_native_worker_v4.py','sha256':digest((ROOT/'scripts/controlled_native_worker_v4.py').read_bytes())})
    names=['controlled_native_worker_v4.py','capture_multimodal_prefix_v4.py','controlled_native_guard_v4.py','run_controlled_native_v4.py','controlled_native_preflight.py','hermes_bc_worker.py','hermes_bc_worker_v3.py','controlled_native_report_v4.py','experiment_admission_v4.py']
    atomic(root/'implementation.json',{name:digest((ROOT/'scripts'/name).read_bytes()) for name in names})
    freeze_inputs(root);return plan


def freeze_inputs(root):
    paths=[root/'plan.json',root/'experiment.json',root/'historical-prefix-acquisition.json',*root.glob('jobs/*/*/*/spec.json'),*root.glob('collectors/*/*/spec.json')]
    atomic(root/'input-fingerprints.json',{str(p.relative_to(root)):digest(p.read_bytes()) for p in paths})

def verify_inputs(root):
    for name,sha in json.loads((root/'implementation.json').read_text()).items():
        if digest((ROOT/'scripts'/name).read_bytes())!=sha:raise ValueError('Implementation changed after freezing: '+name)
    for name,sha in json.loads((root/'input-fingerprints.json').read_text()).items():
        if digest((root/name).read_bytes())!=sha:raise ValueError('Frozen input changed: '+name)
    for manifest in root.glob('prefixes/*/*/manifest.json'):
        m=json.loads(manifest.read_text())
        if digest((manifest.parent/'prefix.json').read_bytes())!=m['prefix_sha256']:raise ValueError('Frozen prefix changed: '+str(manifest.parent))

def usage_snapshot(root):
    from controlled_native_report_v4 import accounting
    return accounting(root)


def active(out):
    for name in ['supervisor.json','dispatch.json']:
        p=out/name
        if p.exists():
            r=json.loads(p.read_text())
            if process_identity(r['pid'])==r.get('identity'):return True
    return False


def trial(spec_path,out,kind):
    out.mkdir(parents=True,exist_ok=True);atomic(out/'supervisor.json',{'pid':os.getpid(),'identity':process_identity(os.getpid()),'started':time.time()})
    spec=json.loads(spec_path.read_text());env,_=environment(ROOT,'hermes',Path(spec['config_path']))
    script='capture_multimodal_prefix_v4.py' if kind=='capture' else 'controlled_native_worker_v4.py'
    if script not in ['capture_multimodal_prefix_v4.py','controlled_native_worker_v4.py']:raise ValueError('Unexpected worker script')
    cmd=[python_for(ROOT),str(ROOT/'scripts'/script),'--spec',str(spec_path),'--out',str(out)]
    if kind=='capture':cmd.insert(2,'--worker')
    with (out/'native.log').open('a') as log:
        child=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        def stop(sig,frame):
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
            atomic(out/'result.json',{'status':'interrupted','reason':'supervisor_signal','usage_unknown_preserved':True});raise SystemExit(128+sig)
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        try:child.wait(timeout=3600)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
            atomic(out/'result.json',{'status':'timeout','reason':'3600s_trial_wall_limit','usage_unknown_preserved':True})
    if not (out/'result.json').exists():atomic(out/'result.json',{'status':'failed','exit_code':child.returncode})


def queue(root,plan):
    verify_inputs(root)
    processes={};worker=ROOT/'scripts/controlled_native_worker_v4.py'
    fingerprint=digest(worker.read_bytes());version=root/'worker-version.json'
    if version.exists() and json.loads(version.read_text())['sha256']!=fingerprint:raise ValueError('Worker changed after campaign start')
    if not version.exists():atomic(version,{'sha256':fingerprint})
    atomic(root/'coordinator.json',{'pid':os.getpid(),'identity':process_identity(os.getpid()),'started':time.time()})
    while True:
        for pid,p in list(processes.items()):
            if p.poll() is not None:processes.pop(pid)
        pilot=[]
        for j in plan['jobs']:
            f=root/'jobs'/j['job_id']/'result.json'
            if j['pilot'] and f.exists():
                value=json.loads(f.read_text());control=f.parent/'compression-control.json'
                if control.exists():value['control_gate']=json.loads(control.read_text())
                pilot.append({**value,'method':j['method'],'dataset':j['dataset']})
        gate=pilot_gate(pilot);atomic(root/'pilot-gate.json',gate)
        if len(pilot)==6 and not gate['passed']:
            atomic(root/'status.json',{'state':'blocked','reason':'pilot_realized_budget_or_native_gate_failed','pilot_gate':gate,'requested_concurrency':4,'effective_running':0,'new_usage_known':usage_snapshot(root)});return
        tasks=[]
        for p in plan['prefixes']:
            if p['pilot'] or not gate['passed']:continue
            prefix=root/'prefixes'/p['key'];collector=root/'collectors'/p['key']
            if (prefix/'prefix.json').exists() or (prefix/'blocked.json').exists():continue
            if (collector/'result.json').exists():
                try:extract_prefix(collector,prefix)
                except (ValueError,OSError) as e:prefix.mkdir(parents=True,exist_ok=True);atomic(prefix/'blocked.json',{'reason':str(e)})
            else:tasks.append(('capture',collector))
        for j in plan['jobs']:
            if not j['pilot'] and not gate['passed']:continue
            prefix=root/'prefixes'/j['prefix_key'];out=root/'jobs'/j['job_id']
            if (prefix/'blocked.json').exists() and not (out/'result.json').exists():
                atomic(out/'result.json',{'status':'not_run_prefix_unavailable','reason':json.loads((prefix/'blocked.json').read_text()),'api_calls':0})
            elif (prefix/'prefix.json').exists():
                if j['method']!='visual':
                    reference=root/'jobs'/j['prefix_key']/'visual/compression-control.json'
                    ready=root/'fit-worker-ready.json'
                    control=json.loads(reference.read_text()) if reference.exists() else {}
                    if not control.get('passed') or not control.get('first_actual_prompt_tokens'):
                        visual_result=reference.parent/'result.json'
                        if visual_result.exists() and not (out/'result.json').exists():
                            atomic(out/'result.json',{'status':'not_run_visual_gate_unavailable','api_calls':0})
                        continue
                    if not ready.exists():continue
                    version=json.loads(ready.read_text());fit=ROOT/'scripts'/version['worker_script']
                    if fit.name!='controlled_native_worker_v4.py' or digest(fit.read_bytes())!=version['sha256']:raise ValueError('Fitting worker fingerprint changed')
                    runtime={**json.loads((out/'spec.json').read_text()),'worker_script':fit.name,'target_reference_path':str(reference),'worker_sha256':version['sha256']}
                    if (out/'runtime-spec.json').exists() and json.loads((out/'runtime-spec.json').read_text())!=runtime:raise ValueError('Frozen fitting runtime spec changed')
                    if not (out/'runtime-spec.json').exists():atomic(out/'runtime-spec.json',runtime)
                tasks.append(('method',out))
        all_dirs=[root/'jobs'/j['job_id'] for j in plan['jobs']]+[root/'collectors'/p['key'] for p in plan['prefixes']]
        running=sum(active(out) for out in all_dirs);launched=0;reason=None
        for kind,out in tasks:
            if running>=4:break
            if (out/'result.json').exists() or active(out):continue
            if (out/'dispatch.json').exists():
                atomic(out/'result.json',{'status':'interrupted_unknown','reason':'prior_dispatch_not_alive_no_automatic_retry'});continue
            cmd=[sys.executable,str(Path(__file__).resolve()),'--trial',kind,'--spec',str(out/'runtime-spec.json' if (out/'runtime-spec.json').exists() else out/'spec.json'),'--root',str(out)]
            proc,reason=spawn_admitted(cmd,owner='controlled-baseline',job_id=str(out.relative_to(root)),log_path=out/'supervisor.log',process_cost=4)
            if proc is None:break
            processes[proc.pid]=proc;atomic(out/'dispatch.json',{'pid':proc.pid,'identity':process_identity(proc.pid),'at':time.time()});running+=1;launched+=1
        terminal=sum((root/'jobs'/j['job_id']/'result.json').exists() for j in plan['jobs'])
        atomic(root/'status.json',{'state':'running' if gate['passed'] else 'waiting_pilot_gate','formal_arms_eligible':174 if gate['passed'] else 0,'fitting_worker_ready':(root/'fit-worker-ready.json').exists(),'pilot_gate':gate,'arms_terminal':terminal,'planned_arms':180,'running_slots':running,'concurrency':4,'requested_concurrency':4,'effective_running':running,'new_usage_known':usage_snapshot(root),'admission':reason,'new_launches':launched})
        if terminal==len(plan['jobs']):return
        time.sleep(5)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT);p.add_argument('--live',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--trial',choices=['capture','method']);p.add_argument('--spec',type=Path);a=p.parse_args();root=a.root.resolve()
    if a.trial:return trial(a.spec,root,a.trial)
    root.mkdir(parents=True,exist_ok=True)
    with (root/'queue.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (root/'plan.json').exists():
            if not a.resume:raise SystemExit('Use --resume for existing frozen plan')
            plan=json.loads((root/'plan.json').read_text())
        else:plan=prepare(root)
        if digest((root/'experiment.json').read_bytes())!=plan['definition']['config_sha256']:raise ValueError('Frozen config changed')
        print(json.dumps({'prepared':len(plan['jobs']),'pilot':6,'live':a.live}),flush=True)
        verify_inputs(root)
        if a.live:queue(root,plan)
if __name__=='__main__':main()
