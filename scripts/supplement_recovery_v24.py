"""Frozen timeout-only recovery, 3 CCIs per scope, 8 workers each. No automatic replay."""
import argparse
import copy
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import signal
import socket
import subprocess
import sys
import time
from unittest.mock import patch

from lab import ROOT, environment, python_for
from supplement_worker_v24 import VERSION, validate

DEFAULT = ROOT/'outputs/campaigns/supplement-timeout-v24'


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path, value):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_name(p.name+'.'+str(os.getpid())+'.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n'); temp.replace(p)
def immutable(path, value):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n'
    if p.exists():
        if p.read_text() != raw: raise ValueError('Immutable file differs: '+str(p))
    else:
        with p.open('x') as f: f.write(raw)


def configuration(source):
    cfg = copy.deepcopy(source)
    cfg.update(supplement_version=VERSION, max_rounds=200, timeout_seconds=10800,
               max_http_sends=3, max_attempts=1, max_timeout_retries=0)
    for key in ('pilot','bc100','bc100_campaign','mmbc100_campaign','mmbc_vanilla_campaign'):
        if key in cfg: cfg[key].update(max_rounds=200, timeout_seconds=10800)
    cfg['transport_runtime_policy']['max_failed_sends'] = 3
    return cfg


def source_job(path):
    p = Path(path); result = read(p)
    root = next(a for a in p.parents if (a/'plan.json').exists())
    plan = read(root/'plan.json')
    job = next(j for j in plan['jobs'] if j['job_id'] == result['job_id'])
    return copy.deepcopy(job), root


def prepare(root=DEFAULT):
    root = Path(root).resolve()
    if (root/'plan.json').exists(): return read(root/'plan.json')
    settings = read(ROOT/'configs/experiment.json')['supplement_recovery_v24']
    if settings != {'status':'authorized','max_rounds':200,'timeout_seconds':10800,
                    'max_http_sends':3,'concurrency_per_cci':8,'core_ccis':3,'controlled_ccis':3,
                    'max_new_attempts_per_timeout_slot':1,'selection':'latest_timeout_only',
                    'new_concurrency_comparison':False}:
        raise ValueError('User settings differ from frozen authorization')
    monitor = read(ROOT/'outputs/cloud-runtime/deepseek-once24h-v15/monitor/latest.json')
    if not all(x.get('controller_exit') and x.get('active') == 0 for x in monitor['rows']):
        raise ValueError('Old main controllers not drained')
    for p in [ROOT/'outputs/controlled-mmbc-vera-nontimeout-summary-v23/cells/summary/status.json',
              ROOT/'outputs/controlled-mmbc-vera-nontimeout-v20/cells/window/status.json']:
        if not read(p).get('drained'): raise ValueError('Old controlled controller not drained')
    snapshots = {}
    for label, rel in [('core','outputs/reports/once24h-v15/latest.json'),
                       ('overlay','outputs/reports/mmbc-timeout-overlay-v18/latest.json'),
                       ('controlled','outputs/reports/controlled-source-v20/latest.json')]:
        snapshots[label] = read(ROOT/rel); immutable(root/'sources'/f'{label}.json', snapshots[label])
    observations = [r for r in snapshots['core']['observations'] if not (r['benchmark']=='mmbc100' and r['method']=='visual')]
    observations += snapshots['overlay']['observations']
    jobs=[]; image_assets={}
    for row in observations:
        if row['status'] not in ('timeout_unresolved','active'): continue
        result_path = Path(row['latest_terminal_result_path'])
        if row['status']=='active':
            candidates=list(Path(row['observed_this_pass_attempt_paths'][0]).glob('result.json.*.tmp'))
            if len(candidates)!=1 or read(candidates[0]).get('status')!='timeout':
                raise ValueError('Unresolved active slot cannot be replayed')
            result_path=candidates[0]
        result=read(result_path)
        if result['status']!='timeout': raise ValueError('Selection must be timeout-only')
        source, oldroot=source_job(result_path)
        job=copy.deepcopy(source)
        # Archive the old authorization and cost lineage, but never reuse its permit.
        key=hashlib.sha256(row['slot_id'].encode()).hexdigest()[:20]
        immutable(root/'lineage'/f'{key}.json',{'source_job':source,'latest_result_path':str(result_path),
                  'latest_result_sha256':sha(result_path),'source_plan_path':str(oldroot/'plan.json'),
                  'source_plan_sha256':sha(oldroot/'plan.json')})
        for k in list(job):
            if k.startswith(('one_pass_','additional_attempt_')):job.pop(k)
        cfg=configuration(read(source['config_path']))
        cpath=root/'configs'/f'{key}.json';immutable(cpath,cfg)
        job.update(job_id=key, original_job_id=source['job_id'], scope='core', method=row['method'],
            slot_id=row['slot_id'], config_path=str(cpath),config_sha256=sha(cpath),
            campaign_root=str(root), supplement_version=VERSION,max_rounds=200,timeout_seconds=10800,
            max_http_sends=3,max_attempts=1,max_timeout_retries=0,authorized_new_attempts=1,
            recovery_source_path=str(result_path),recovery_source_sha256=sha(result_path),
            source_plan_path=str(oldroot/'plan.json'),lineage_path=str(root/'lineage'/f'{key}.json'))
        if not job.get('native_cohort_path'):
            job['native_cohort_path']=str(oldroot/'cohort.jsonl');job['native_cohort_sha256']=sha(oldroot/'cohort.jsonl')
        if row['benchmark']=='mmbc100':
            assets=read(oldroot/'image-assets/manifest.json')
            for url in job.get('image',[]):
                item=copy.deepcopy(assets['images'][url]);src=oldroot/item['relative_path']
                if sha(src)!=item['sha256']:raise ValueError('Original image changed')
                destination=root/'image-assets'/src.name
                destination.parent.mkdir(parents=True,exist_ok=True)
                if not destination.exists(): shutil.copyfile(src,destination)
                if sha(destination)!=item['sha256']:raise ValueError('Copied input image changed')
                item['relative_path']=str(destination.relative_to(root));image_assets[url]=item
        jobs.append(job)
    source_control_plans=[ROOT/'outputs/controlled-mmbc-vera-nontimeout-v20/plan.json',
                          ROOT/'outputs/controlled-mmbc-vera-nontimeout-summary-v23/plan.json']
    lookup={j['job_id']:(j,p) for p in source_control_plans for j in read(p)['jobs']}
    for row in snapshots['controlled']['rows']:
        if row['status']!='timeout':continue
        source,source_plan=lookup[row['job_id']];old_terminal=Path(source['output_path'])/'terminal.json'
        if read(old_terminal)['status']!='timeout':raise ValueError('Controlled source not timeout')
        key='controlled-'+row['method']+'-'+row['question_id']+f"-r{row['repeat']}"
        cfg=configuration(read(source['config_path']));cpath=root/'configs'/f'{key}.json';immutable(cpath,cfg)
        cspec=read(source['spec_path']);cspec.update(config_path=str(cpath),max_rounds=200)
        spath=root/'controlled-specs'/f'{key}.json';immutable(spath,cspec)
        cj=copy.deepcopy(source);cj.update(config_path=str(cpath),config_sha256=sha(cpath),spec_path=str(spath),
             spec_sha256=sha(spath),max_iterations=200,timeout_seconds=10800,
             output_path=str(root/'jobs'/key/'attempts/attempt_001/native'))
        immutable(root/'lineage'/f'{key}.json',{'source_job':source,'source_plan_path':str(source_plan),
                   'source_plan_sha256':sha(source_plan),'latest_result_path':str(old_terminal),'latest_result_sha256':sha(old_terminal)})
        jobs.append({'job_id':key,'slot_id':'controlled:'+row['job_id'],'scope':'controlled','method':row['method'],
            'harness':'hermes','strategy':row['method'],'benchmark':'controlled_mmbc',
            'question_id':row['question_id'],'repeat':row['repeat'],'model':source['model'],
            'config_path':str(cpath),'config_sha256':sha(cpath),'campaign_root':str(root),
            'supplement_version':VERSION,'max_rounds':200,'timeout_seconds':10800,'max_http_sends':3,
            'authorized_new_attempts':1,'controlled_job':cj,'recovery_source_path':str(old_terminal),
            'recovery_source_sha256':sha(old_terminal),'lineage_path':str(root/'lineage'/f'{key}.json')})
    for scope in ('core','controlled'):
        own=sorted([j for j in jobs if j['scope']==scope],key=lambda j:j['job_id'])
        random.Random(20261114).shuffle(own)
        for i,j in enumerate(own):j['shard']=i%3
    for j in jobs:validate(j,read(j['config_path']))
    if len({j['slot_id']for j in jobs})!=len(jobs):raise ValueError('Duplicate slot')
    immutable(root/'image-assets/manifest.json',{'version':'mmbc-original-input-images-v1','images':image_assets})
    sources={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'scripts').glob('*') if p.suffix in ('.py','.mjs')}
    plan={'version':VERSION,'at':time.time(),'settings':settings,'jobs':jobs,'source_sha256':sources,
          'definition':{'input_images_sha256':sha(root/'image-assets/manifest.json')},
          'harness_lock_sha256':sha(ROOT/'harness-lock.json'),'selection_uses_answers':False,
          'old_results_modified':False,'max_new_attempts_per_slot':1,'maximum_concurrency':48,
          'shared_core_queue':'P0/P2/P5','model_calls_by_prepare':0}
    immutable(root/'plan.json',plan)
    return plan


def validate_plan(root, deep=False):
    root=Path(root);plan=read(root/'plan.json')
    if plan['version']!=VERSION or sha(ROOT/'harness-lock.json')!=plan['harness_lock_sha256']:raise ValueError('Pin changed')
    for path,digest in plan['source_sha256'].items():
        if sha(ROOT/path)!=digest:raise ValueError('Frozen source changed: '+path)
    if deep:
        for job in plan['jobs']:
            if sha(job['config_path'])!=job['config_sha256'] or sha(job['recovery_source_path'])!=job['recovery_source_sha256']:
                raise ValueError('Frozen job source changed')
            validate(job,read(job['config_path']))
    return plan


def trial(spec_path, out):
    import run_bc_trial_v3 as base
    from run_bc_trial_v3_io import HeartbeatAtomic
    spec=read(spec_path);root=Path(spec['campaign_root']);plan=validate_plan(root)
    expected=next(j for j in plan['jobs'] if j['job_id']==spec['job_id'])
    if any(spec.get(k)!=v for k,v in expected.items()):raise ValueError('Job binding differs')
    if Path(out).resolve()!=root/'jobs'/spec['job_id']/'attempts/attempt_001':raise ValueError('Output scope differs')
    validate(spec,read(spec['config_path']))
    if sha(spec['config_path'])!=spec['config_sha256'] or sha(spec['recovery_source_path'])!=spec['recovery_source_sha256']:
        raise ValueError('Source/config changed before dispatch')
    def command(job,out):
        result=out/'native/native-result.json'
        if job['harness']=='dsh':
            method={'visual':'visual_native','sliding_window':'sliding_window_native'}.get(job['strategy'],job['strategy'])
            result=out/'native'/method/job['question_id']/'result.json'
        return [python_for(ROOT),str(ROOT/'scripts/supplement_worker_v24.py'),'--spec',str(spec_path),'--out',str(out/'native'),'--live'],result,10800
    with patch.object(sys,'argv',[str(__file__),'--spec',str(spec_path),'--out',str(out),'--live']), \
         patch.object(base,'validate_spec',lambda *_:root),patch.object(base,'native_command',command), \
         patch.object(base,'atomic',HeartbeatAtomic(base.atomic)),patch.object(base,'release_slot',lambda *_:None):
        base.main()
    result=read(Path(out)/'result.json')
    result.update(supplement_version=VERSION,source_slot_id=spec['slot_id'],max_rounds=200,
                  timeout_seconds=10800,max_http_sends=3,new_attempts=1,will_retry=False)
    if result.get('exit_code')==78:result['failure_category']='transport_request_budget_exhausted'
    save(Path(out)/'result.json',result)


def run(root, scope, shard):
    root=Path(root);plan=validate_plan(root,deep=True);state=root/'runtime'/scope/str(shard);state.mkdir(parents=True,exist_ok=True)
    lock=(state/'lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    jobs=[j for j in plan['jobs'] if j['scope']==scope and j['shard']==shard]
    active={};unknown=[];pending=[];stopping=False;launcher_failures=0
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    for j in jobs:
        out=root/'jobs'/j['job_id']/'attempts/attempt_001'
        if (out/'result.json').exists():continue
        if (out/'dispatch.json').exists():unknown.append(j['job_id'])
        else:pending.append(j)
    if unknown:raise RuntimeError('Unknown prior dispatch; refusing replay')
    reader=None;env,_=environment(ROOT,'hermes',jobs[0]['config_path'])
    # Each CCI gets its own local Reader. Existing healthy local service is reused.
    from bootstrap_mmbc100_cci import health
    from bootstrap_bc_retry1 import runtime_snapshot, local_git_wrapper, compare_runtime, resource_snapshot
    local_git_wrapper(env,Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    runtime=runtime_snapshot(env,sys.executable)
    compare_runtime(runtime,read(ROOT/'configs/cloud-runtime-v3.json'))
    if not resource_snapshot()['minimum_capacity_passed']:raise RuntimeError('CCI requires 8 CPU and 32 GiB')
    if not health(runtime['reader_source_sha256']):
        log=(state/'reader.log').open('a')
        reader=subprocess.Popen([sys.executable,str(ROOT/'scripts/local_reader_text_service.py'),
              '--config',str(ROOT/'configs/reader-text-v1-workers32.json')],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        until=time.monotonic()+90
        while not health(runtime['reader_source_sha256']):
            if reader.poll() is not None or time.monotonic()>until:raise RuntimeError('Reader startup failed')
            time.sleep(.5)
    from preflight_controlled_source_web_v20 import run_check
    from local_web import configure_web
    webenv=dict(env);configure_web(ROOT,webenv,jobs[0]['config_path'])
    readiness=dict(run_check(kind,state/'web-preflight',webenv,120) for kind in ('search','fetch'))
    save(state/'web-readiness.json',{'at':time.time(),'paid_model_calls':0,'checks':readiness})
    if not all(x['passed'] for x in readiness.values()):raise RuntimeError('Web readiness failed before task dispatch')
    immutable(state/'started.json',{'at':time.time(),'hostname':socket.gethostname(),'pid':os.getpid(),
               'plan_sha256':sha(root/'plan.json'),'scope':scope,'shard':shard,'concurrency':8})
    try:
        while active or pending and not stopping:
            while pending and len(active)<8 and not stopping:
                job=pending.pop(0);out=root/'jobs'/job['job_id']/'attempts/attempt_001';out.mkdir(parents=True,exist_ok=True)
                immutable(out/'dispatch.json',{'at':time.time(),'hostname':socket.gethostname(),'pid':os.getpid(),
                        'job_id':job['job_id'],'plan_sha256':sha(root/'plan.json'),'attempts_authorized':1})
                spec={**job,'slot_path':str(out/'slot')};spath=out.parent.parent/'spec.json';immutable(spath,spec)
                log=(out/'launcher.log').open('a')
                p=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'trial','--spec',str(spath),'--out',str(out)],
                          cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                log.close();active[job['job_id']]=(p,out)
            for key,(proc,out) in list(active.items()):
                if proc.poll() is not None:
                    if not(out/'result.json').exists():
                        save(out/'result.json',{'status':'failed','failure_category':'launcher_error','job_id':key,
                            'exit_code':proc.returncode,'new_attempts':1,'will_retry':False,'finished_at_unix':time.time()})
                    elif read(out/'result.json').get('slot_released') is False:
                        stopping=True;unknown.append(key)
                    result=read(out/'result.json')
                    if result.get('failure_category') in ('launcher_error','execution_error') and result.get('end_to_end_seconds',0)<90:
                        launcher_failures+=1
                        if launcher_failures>=2:stopping=True
                    del active[key]
            from monitor_bc_v3_node import cgroup_snapshot
            telemetry={'at':time.time(),'active':len(active),'pending':len(pending),
                  'finished':False,'unknown':unknown,'concurrency':8,'cgroup':cgroup_snapshot(),'launcher_failures':launcher_failures}
            save(state/'status.json',telemetry)
            with (state/'telemetry.jsonl').open('a') as stream:stream.write(json.dumps(telemetry)+'\n')
            time.sleep(3)
    finally:
        if reader and reader.poll() is None:reader.terminate();reader.wait(timeout=15)
    save(state/'status.json',{'at':time.time(),'active':0,'pending':len(pending),'finished':not pending and not unknown,'unknown':unknown,'concurrency':8})


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run','trial','validate'])
    p.add_argument('--root',type=Path,default=DEFAULT);p.add_argument('--scope',choices=['core','controlled'])
    p.add_argument('--shard',type=int,choices=range(3));p.add_argument('--spec',type=Path);p.add_argument('--out',type=Path)
    a=p.parse_args()
    if a.action=='prepare':
        plan=prepare(a.root);print(json.dumps({'jobs':len(plan['jobs']),'scopes':dict(Counter(j['scope'] for j in plan['jobs'])),'model_calls':0}))
    elif a.action=='validate':validate_plan(a.root,True);print('Validated frozen recovery plan; model_calls=0')
    elif a.action=='trial':trial(a.spec,a.out)
    else:run(a.root,a.scope,a.shard)


if __name__=='__main__':main()
