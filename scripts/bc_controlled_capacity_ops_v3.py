#!/usr/bin/env python3
"""Reserve controlled16, preserve BC16+16, and restore drained RQ3 cells within128."""
import argparse
import fcntl
import json
import signal
import time
from pathlib import Path
from unittest.mock import patch
import yaml

import bc_priority_capacity_ops_v1 as base
import bc_priority_capacity_ops_v2 as drain
from run_bc_trial import process_identity

ROOT=base.ROOT
AREA=ROOT/'outputs/cloud-runtime/bc-controlled-capacity-ops-v3'
RESTORE=AREA/'restored-rq3'
CONTROLLED_ROOT=ROOT/'outputs/experiment3/controlled-native-bounded-v1'
CONTROLLED_MARKER=AREA/'markers/controlled16.json'
DISPATCHER='scripts/run_controlled_bounded_ops16_v1.py'
HELD=('scale_0700','scale_0800','scale_1000')
RESERVE=6
CONTROLLED_CAP=16
GLOBAL_CAP=128
COORDINATORS=({'pid':558793,'identity':'897942253'},{'pid':566980,'identity':'898169066'})
VERSION='bc-controlled-capacity-ops-v3'


def restore_name(key):
    base.require(key in HELD,'Unapproved restore scale')
    return 'acl-rq3-controlled16-v3-s'+key.removeprefix('scale_')


def controlled_binding():
    from prepare_controlled_bounded_v1 import load_validate
    plan,_=load_validate(CONTROLLED_ROOT)
    base.require(plan['definition']['eligible_arms']==120,'Controlled eligible inventory changed')
    base.require((ROOT/DISPATCHER).is_file(),'Controlled16 dispatcher not prepared')
    return {'controlled_plan_sha256':base.sha(CONTROLLED_ROOT/'plan.json'),
            'dispatcher_source_sha256':base.sha(ROOT/DISPATCHER)}


def marker_valid(value,binding):
    base.require(value.get('version')=='controlled-bounded-ops16-capacity-v1' and value.get('ready') is True,'Controlled marker not ready')
    base.require(value.get('controlled_native_slots')==16 and value.get('judge_reserve')==6 and value.get('global_cap')==128,'Controlled marker cap changed')
    base.require(type(value.get('global_reserved_total')) is int and 22<=value['global_reserved_total']<=128,'Invalid marker upper bound')
    for key,expected in binding.items():base.require(value.get(key)==expected,'Controlled marker binding changed: '+key)


def controlled_capacity(binding):
    """One existing pilot before admission; after admission reserve16 until proven drained."""
    if not CONTROLLED_MARKER.exists():return {'upper':1,'state':'old_pilot_reserved'}
    marker=base.read(CONTROLLED_MARKER);marker_valid(marker,binding)
    path=CONTROLLED_ROOT/'ops16-v1/status.json'
    if not path.exists():return {'upper':16,'state':'marker_published_waiting_dispatcher'}
    value=base.read(path)
    if value.get('state')=='waiting_capacity_marker' and not value.get('capacity_marker_sha256'):
        return {'upper':16,'state':'marker_published_dispatcher_handoff_pending'}
    base.require(value.get('capacity_marker_sha256')==base.sha(CONTROLLED_MARKER),'Controlled status marker mismatch')
    done=(value.get('all_eligible_resolved') is True and value.get('no_active_native') is True
          and value.get('unknown_reserved_slots')==0 and value.get('running_native')==0
          and value.get('occupied_slots')==0 and value.get('eligible_arms')==120
          and value.get('pending_eligible')==0 and value.get('terminal_eligible')==120)
    if not done:return {'upper':16,'state':'controlled16_reserved','reported_state':value.get('state')}
    pid=value.get('pid');ident=value.get('identity')
    base.require(type(pid) is int and isinstance(ident,str) and ident,'Controlled dispatcher identity missing')
    live_ident=process_identity(pid)
    if live_ident==ident:return {'upper':16,'state':'controlled_finished_dispatcher_not_exited'}
    if Path('/proc',str(pid)).exists() and live_ident is None:
        # A zombie is exited, but permission/unknown proc state is not assumed dead.
        try:state=Path('/proc',str(pid),'stat').read_text().split(') ',1)[1].split()[0]
        except (OSError,IndexError):return {'upper':16,'state':'controlled_exit_unknown'}
        if state!='Z':return {'upper':16,'state':'controlled_exit_unknown'}
    return {'upper':0,'state':'controlled16_finished_and_exited'}


def capacity(mm,rq,bc,controlled):return mm+rq+bc+controlled+RESERVE


def prepare_restore(key):
    name=restore_name(key);directory=RESTORE/name;marker=RESTORE/'markers'/(key+'.json')
    cfg=base.rqcloud.build_config(yaml.safe_load(base.rqcloud.base.TEMPLATE.read_text()),key,base.RQ_ROOT,marker)
    cfg['display_name']=name;raw=yaml.safe_dump(cfg,sort_keys=False).encode();directory.mkdir(parents=True,exist_ok=True);path=directory/'config.yaml'
    if path.exists():base.require(path.read_bytes()==raw,'Restore configuration changed')
    else:
        with path.open('xb') as f:f.write(raw)
    value={'name':name,'scale_key':key,'root':str(base.RQ_ROOT),'plan_sha256':base.sha(base.RQ_ROOT/'plan.json'),
           'config_path':str(path),'config_sha256':base.sha(path),'launch_marker':str(marker),'concurrency':16,
           'source_sha256':base.sha(__file__),'restores_old_name':base.rqcloud.app_name(key)}
    base.immutable_json(directory/'prepared.json',value);return value


def legacy_restore_absent():
    # Switching is authorized before the two legacy restore cells launch. Unknown
    # external generations must be explicitly reconciled, never double-created.
    for key in ('scale_0800','scale_1000'):
        base.require(not(base.RESTORE/'markers'/(key+'.json')).exists(),'Legacy RQ3 restore already released; explicit adoption required')
        receipt=base.RESTORE/base.restore_name(key)/'request.json'
        base.require(not receipt.exists(),'Legacy cloud restore submission exists; explicit adoption required')


def cycle(live=False):
    legacy_restore_absent()
    bcplan,_=base.load_validate(base.BC_ROOT);rqplan,_=base.rqcloud.load_validate(base.RQ_ROOT)
    mmplan=base.read(base.MM_ROOT/'plan.json')
    base.require(base.read(base.MM_ROOT/'campaign-manifest.json')['plan_sha256']==base.sha(base.MM_ROOT/'plan.json'),'MMBC plan changed')
    binding=controlled_binding();control=controlled_capacity(binding)
    mm=min(48,base.remaining_count(base.MM_ROOT,mmplan['jobs']));bc=0
    for harness in base.HARNESSES:
        marker=base.bccloud.launch_marker(harness)
        base.require(marker.exists() and base.read(marker).get('plan_sha256')==base.sha(base.BC_ROOT/'plan.json'),'Existing BC release binding changed')
        if not base.complete(base.BC_ROOT,[j for j in bcplan['jobs'] if j['harness']==harness]):bc+=16
    bounds={k:drain.scale_bound(base.RQ_ROOT,rqplan,k) for k in base.rqcloud.SCALE_KEYS};rq=sum(bounds.values())
    admission={'state':'already_released'}
    if not CONTROLLED_MARKER.exists():
        projected=capacity(mm,rq,bc,CONTROLLED_CAP)
        admission={'state':'held_for_drain','projected_upper':projected,'required_rq3_0700_bound_at_most':GLOBAL_CAP-capacity(mm,rq-bounds['scale_0700'],bc,CONTROLLED_CAP)}
        if projected<=GLOBAL_CAP:
            marker={'version':'controlled-bounded-ops16-capacity-v1','ready':True,'controlled_native_slots':16,'judge_reserve':RESERVE,
                    'global_cap':GLOBAL_CAP,'global_reserved_total':projected,**binding,'coordinator_stops':list(COORDINATORS),
                    'at':time.time(),'source_sha256':base.sha(__file__),'capacity_components':{'mmbc':mm,'rq3':bounds,'bc':bc,'controlled':16,'other_models':RESERVE},
                    'reason':'User authorized controlled16; reservation includes adopted old pilot, not16+1'}
            if live:base.immutable_json(CONTROLLED_MARKER,marker)
            control={'upper':16,'state':'released' if live else 'would_release'};admission={'state':control['state'],'projected_upper':projected}
    total=capacity(mm,rq,bc,control['upper']);base.require(total<=GLOBAL_CAP,'Observed reservation exceeds128; no further release')
    restored=[];simulated_releases=set();bc_done=base.complete(base.BC_ROOT,bcplan['jobs'])
    for key in HELD:
        marker=RESTORE/'markers'/(key+'.json');directory=RESTORE/restore_name(key)
        if marker.exists():
            with patch.object(base.rqmon,'app_name',restore_name):restored.append(base.rqmon.cycle(key,live,receipts=RESTORE))
            continue
        if base.complete(base.RQ_ROOT,[j for j in rqplan['jobs'] if j['scale_key']==key]):
            restored.append({'scale_key':key,'state':'stopped','reason':'all_jobs_terminal_no_restore_needed'});continue
        if not CONTROLLED_MARKER.exists():
            restored.append({'scale_key':key,'state':'held_until_controlled16_admitted'});continue
        if key!='scale_0700' and not bc_done:
            restored.append({'scale_key':key,'state':'held_until_both_bc_cells_complete'});continue
        bounds={k:drain.scale_bound(base.RQ_ROOT,rqplan,k) for k in base.rqcloud.SCALE_KEYS}
        for simulated in simulated_releases:bounds[simulated]=16
        # Reopening a stopped cell replaces its draining upper bound with16.
        projected=capacity(mm,sum(bounds.values())-bounds[key]+16,bc,control['upper'])
        if projected>GLOBAL_CAP:
            restored.append({'scale_key':key,'state':'restore_capacity_hold','projected_upper':projected});continue
        if bounds[key]!=0:
            restored.append({'scale_key':key,'state':'waiting_for_native_drain','draining_upper':bounds[key]});continue
        platform=base.rqmon.query_app(base.rqcloud.app_name(key))
        if platform['state'] not in ('SUSPENDED','STOPPED'):
            restored.append({'scale_key':key,'state':'waiting_for_old_cci_stop','platform_state':platform['state']});continue
        proof=base.rqmon.assess_local(base.RQ_ROOT,platform['uid'],base.rqcloud.launch_marker(key),key)
        base.require(proof['eligible'],'Old RQ3 native drain not proven')
        if not live:
            restored.append({'scale_key':key,'state':'would_restore_in_new_cci','projected_upper':projected});simulated_releases.add(key);continue
        record=prepare_restore(key);base.rqcloud.submit(record);base.marker_binding(directory,base.RQ_ROOT,key)
        stop=base.RQ_ROOT/'stops'/key;base.require(stop.exists(),'Stop marker missing before restore')
        base.immutable_json(directory/'prior-drain-proof.json',proof)
        archive=directory/'prior-stop-marker.json';base.require(not archive.exists(),'Unknown prior restore transition; inspect manually')
        archive.write_bytes(stop.read_bytes());stop.unlink()
        base.immutable_json(marker,{'plan_sha256':base.sha(base.RQ_ROOT/'plan.json'),'scale_key':key,'at':time.time(),
            'source_sha256':base.sha(__file__),'combined_inference_upper':projected,'controlled_capacity_reserved':control['upper'],'judge_reserve':RESERVE})
        restored.append({'scale_key':key,'state':'new_restore_cci_released','name':restore_name(key),'projected_upper':projected})
    final_bounds={k:drain.scale_bound(base.RQ_ROOT,rqplan,k) for k in base.rqcloud.SCALE_KEYS}
    for simulated in simulated_releases:final_bounds[simulated]=16
    return {'version':VERSION,'at':time.time(),'live':live,'mmbc_capacity_upper':mm,'rq3_bounds':final_bounds,'rq3_capacity_upper':sum(final_bounds.values()),
            'bc_capacity_upper':bc,'controlled_capacity':control,'judge_reserved':RESERVE,'global_cap':GLOBAL_CAP,
            'global_reserved_total':capacity(mm,sum(final_bounds.values()),bc,control['upper']),'controlled_admission':admission,
            'restored':restored,'paid_model_calls':0}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--watch',action='store_true');p.add_argument('--live',action='store_true');a=p.parse_args()
    AREA.mkdir(parents=True,exist_ok=True)
    # Shared with v1/v2: only one global capacity authority may mutate markers.
    with (base.AREA/'observer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);generation=AREA/'generations'/str(time.time_ns());generation.mkdir(parents=True)
        base.immutable_json(generation/'service.json',{**base.identity(),'source_sha256':base.sha(__file__),'at':time.time(),'live':a.live})
        stopping=False
        def stop(*unused):
            nonlocal stopping;stopping=True
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        while not stopping:
            try:row=cycle(a.live)
            except Exception as exc:row={'version':VERSION,'at':time.time(),'state':'unknown_no_release','error_type':type(exc).__name__,'reason':str(exc)}
            base.atomic(AREA/'status.json',row)
            with (generation/'history.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
            if not a.watch:print(json.dumps(row));break
            if row.get('controlled_capacity',{}).get('upper')==0 and len(row.get('restored',[]))==3 and all(x['state']=='stopped' for x in row['restored']):break
            until=time.monotonic()+15
            while not stopping and time.monotonic()<until:time.sleep(.5)
        base.atomic(generation/'exit.json',{'at':time.time(),'stop_requested':stopping})

if __name__=='__main__':main()
