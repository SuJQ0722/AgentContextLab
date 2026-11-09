#!/usr/bin/env python3
"""Preserve one proven pre-native reservation while handing other pending jobs to cloud."""
import argparse,json,fcntl,time
from pathlib import Path
import handoff_rq3_scale0700_local_cloud_ops1 as base
from bc_route_runtime_v2 import immutable_json

VERSION='rq3-scale0700-held-reservation-handoff-ops2'
JOB='hermes/scale_0700/q_045_r02'


def held_proof(record,status):
    root=Path(record['root']);jid=status.get('reserved_not_started')
    if jid!=JOB:raise ValueError('Only the explicitly identified q045r02 reservation is authorized')
    d=root/'jobs'/jid;a=d/'attempts/attempt_001';claim=base.read(d/'claim/owner.json');spec=base.read(d/'spec.json');slot=Path(spec['slot_path'])
    if not base.same_owner(claim,record['owner']) or claim.get('slot')!=str(slot) or spec.get('controller_id')!=record['owner']['controller_id']:
        raise ValueError('Held claim does not belong to stopped exact dispatcher')
    plan=base.read(root/'plan.json');job=next(j for j in plan['jobs'] if j['job_id']==jid)
    if any(spec.get(k)!=v for k,v in job.items()) or spec.get('plan_sha256')!=base.sha(root/'plan.json'):raise ValueError('Held scientific specification changed')
    if slot.parent!=Path(record['shared_slots']) or base.read(slot/'owner.json').get('job_id')!=jid or not base.same_owner(base.read(slot/'owner.json'),claim):raise ValueError('Held slot owner differs')
    allowed={'cloud-scale-dispatch-ops2.json'}
    if {p.name for p in a.iterdir()}-allowed:raise ValueError('Held attempt has execution evidence or an unreviewed artifact')
    paths=[d/'claim/owner.json',d/'claim/spec.json',d/'spec.json',slot/'owner.json',a/'cloud-scale-dispatch-ops2.json']
    return {'version':VERSION,'job_id':jid,'attempt':str(a),'slot_path':str(slot),'original_controller':record['owner'],
            'native_never_started_at_checkpoint':True,'source_sha256':base.sha(__file__),
            'bindings':{str(p):base.sha(p) for p in paths},'recovery_rule':'Do not launch now. Wait exact old owner exit, drained exit and original not_started/api_calls0/slot_released before one first native attempt.',
            'shared_scale_capacity':16,'old_slot_removed':False,'old_claim_removed':False}


def extended_ack(record,now=None):
    now=time.time() if now is None else now;s=base.read(record['old_status_path'])
    if not base.same_owner(record['owner'],s):raise ValueError('Old stop checkpoint identity changed')
    if type(s.get('at')) not in (int,float) or s['at']<record['requested_at_unix'] or not 0<=now-s['at']<=90:return None,'waiting_fresh_stop_ack'
    if s.get('stop_dispatch') is not True:return None,'waiting_stop_ack'
    proof=held_proof(record,s);out=base.directory(Path(record['root']));immutable_json(out/'held-reservation.json',proof)
    return {**s,'handoff_extension':VERSION,'held_reservation_path':str(out/'held-reservation.json'),'held_reservation_sha256':base.sha(out/'held-reservation.json')},'ready_with_held_slot_retained'


def handoff(record):
    original=base.acknowledged_status;base.acknowledged_status=extended_ack
    try:ready,state=base.archive_lease(record)
    finally:base.acknowledged_status=original
    if ready:
        out=base.directory(Path(record['root']));proof=base.read(out/'held-reservation.json')
        if base.sha(__file__)!=proof['source_sha256']:raise ValueError('Held guard changed')
        result={'version':VERSION,'ready_sha256':base.sha(out/'ready.json'),'held_reservation_sha256':base.sha(out/'held-reservation.json'),
                'old_dispatch_fully_stopped':True,'old_reserved_job_stays_claimed':JOB,'shared_slots_unchanged':True,
                'source_sha256':base.sha(__file__),'native_retries_started':0,'cloud_may_resume_other_pending':True}
        immutable_json(out/'held-ready.json',result)
    return ready,state


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=base.pending.old.scientific.DEFAULT_ROOT);p.add_argument('--live',action='store_true');args=p.parse_args();out=base.directory(args.root.resolve())
    with (out/'operation.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);record=base.read(out/'request.json');base.verify_request(record)
        if not args.live:
            status,state=extended_ack(record);print(json.dumps({'live':False,'state':state}));return
        ready,state=handoff(record);print(json.dumps({'state':state,'ready':bool(ready),'held_ready_path':str(out/'held-ready.json') if ready else None}))

if __name__=='__main__':main()
