#!/usr/bin/env python3
"""Release prepared per-scale markers under128 prediction+judge capacity; no cloud create."""
import argparse,fcntl,json,time,signal
from pathlib import Path
from lab import ROOT
from run_bc_campaign_v3 import atomic,identity
from bc_route_runtime_v1 import immutable_json
from bootstrap_rq3_bounded_retry_v1 import SCALE_KEYS,DEFAULT_ROOT,load_validate
from provision_rq3_bounded_retry_v1 import RECEIPTS,app_name,launch_marker
from prepare_bounded_vera_retry_v1 import DEFAULT_ROOT as MMBC_ROOT
from monitor_rq3_bounded_cci_v1 import sha,require,read

MAX_INFERENCE=128
JUDGE_RESERVE=4
TERMINAL={'completed','failed','timeout','interrupted','not_started'}

def remaining_count(root,jobs):
    seen=set();remaining=0
    for job in jobs:
        jid=job['job_id'];rel=Path(jid)
        require(jid not in seen and not rel.is_absolute() and '..' not in rel.parts,'Invalid/duplicate job identity')
        seen.add(jid);path=Path(root)/'jobs'/jid/'attempts/attempt_001/result.json'
        if not path.exists():remaining+=1;continue
        result=read(path);require(result.get('job_id')==jid,'Result identity differs')
        if result.get('status') not in TERMINAL or result.get('slot_released') is not True or result.get('unconfirmed_child_termination')!=[]:
            remaining+=1
    return remaining

def capacity(mmbc_remaining,released_active):
    if type(mmbc_remaining) is not int or mmbc_remaining<0 or type(released_active) is not int or not 0<=released_active<=7:
        raise ValueError('Unknown capacity')
    return min(48,mmbc_remaining)+released_active*16+JUDGE_RESERVE

def cycle(live=False,root=DEFAULT_ROOT,receipts=RECEIPTS,mmbc_root=MMBC_ROOT):
    root,receipts,mmbc_root=map(Path,(root,receipts,mmbc_root));plan,_=load_validate(root);plan_sha=sha(root/'plan.json')
    mmbc_plan=read(mmbc_root/'plan.json');mmbc_manifest=read(mmbc_root/'campaign-manifest.json')
    require(mmbc_manifest['plan_sha256']==sha(mmbc_root/'plan.json'),'MMBC plan binding changed')
    require(mmbc_plan['definition']['planned_runs']==len(mmbc_plan['jobs']) and mmbc_plan['definition']['per_cell_concurrency_cap']==48,'MMBC capacity contract changed')
    remaining=remaining_count(mmbc_root,mmbc_plan['jobs'])
    by_scale={key:[j for j in plan['jobs'] if j.get('scale_key')==key] for key in SCALE_KEYS}
    require(sum(map(len,by_scale.values()))==len(plan['jobs']) and all(by_scale.values()),'Incomplete seven-scale retry plan')
    released={};active=0
    for key in SCALE_KEYS:
        marker=launch_marker(key,receipts)
        if marker.exists():
            record=read(marker);require(record.get('plan_sha256')==plan_sha and record.get('scale_key')==key,'Release marker binding differs')
            outstanding=remaining_count(root,by_scale[key]);released[key]=outstanding
            active+=bool(outstanding)
    rows=[]
    for key in SCALE_KEYS:
        if key in released:
            rows.append({'scale_key':key,'state':'already_released','remaining':released[key]});continue
        upper=capacity(remaining,active+1)
        if upper>MAX_INFERENCE:
            rows.append({'scale_key':key,'state':'held_for_capacity','projected_upper':upper});continue
        directory=receipts/app_name(key)
        if not(directory/'response.json').exists():
            rows.append({'scale_key':key,'state':'not_submitted'});continue
        response=read(directory/'response.json');prepared=read(directory/'prepared.json');request=read(directory/'request.json')
        require(response.get('state')=='submitted','Unknown or rejected CCI creation')
        require(prepared['root']==str(root.resolve()) and prepared['scale_key']==key and prepared['name']==app_name(key),'Prepared scope mismatch')
        require(prepared['plan_sha256']==request['plan_sha256']==plan_sha,'Prepared plan differs')
        require(prepared['config_sha256']==request['config_sha256']==sha(prepared['config_path']),'Prepared config differs')
        require(Path(prepared['launch_marker']).resolve()==launch_marker(key,receipts).resolve(),'Wrong per-scale marker')
        record={'version':'rq3-bounded-capacity-release-v1','at':time.time(),'scale_key':key,'plan_sha256':plan_sha,
                'mmbc_remaining_at_release':remaining,'mmbc_capacity_upper':min(48,remaining),'rq3_active_scales_after':active+1,
                'judge_capacity_reserved':JUDGE_RESERVE,'combined_inference_upper':upper,'source_sha256':sha(__file__),
                'meaning':'Job worker capacity plus four judge slots, not OS process count or HTTP-level retries.'}
        if live:immutable_json(launch_marker(key,receipts),record)
        active+=1;rows.append({'scale_key':key,'state':'released' if live else 'would_release','projected_upper':upper})
    return {'at':time.time(),'live':live,'mmbc_remaining':remaining,'mmbc_capacity_upper':min(48,remaining),
            'reserved_judges':JUDGE_RESERVE,'capacity_limit':MAX_INFERENCE,'rows':rows,'cloud_create_calls':0,'model_calls':0}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true');p.add_argument('--watch',action='store_true');a=p.parse_args()
    area=RECEIPTS/'release';area.mkdir(parents=True,exist_ok=True)
    with (area/'observer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        generation=area/'generations'/str(time.time_ns());generation.mkdir(parents=True)
        immutable_json(generation/'service.json',{**identity(),'at':time.time(),'source_sha256':sha(__file__),'live':a.live,'watch':a.watch})
        stopped=False
        def stop(*unused):
            nonlocal stopped;stopped=True
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        while not stopped:
            try:report=cycle(a.live)
            except Exception as exc:report={'at':time.time(),'state':'unknown_no_release','error_type':type(exc).__name__,'reason':str(exc),'rows':[]}
            atomic(area/'status.json',report)
            with (generation/'history.jsonl').open('a') as stream:stream.write(json.dumps(report)+'\n')
            if not a.watch or report['rows'] and all(x['state'] in ('released','already_released') for x in report['rows']):break
            until=time.monotonic()+30
            while not stopped and time.monotonic()<until:time.sleep(.5)
        atomic(generation/'exit.json',{'at':time.time(),'stop_requested':stopped})
if __name__=='__main__':main()
