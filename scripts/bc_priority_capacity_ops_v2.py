#!/usr/bin/env python3
"""Use a proven monotonically draining RQ3 upper bound for BC admission."""
from pathlib import Path
from unittest.mock import patch
import bc_priority_capacity_ops_v1 as base
from monitor_rq3_cci7_lifecycle import same_identity

CONTROLLER='scripts/run_rq3_bounded_retry_v1.py'
TERMINAL={'completed','failed','timeout','interrupted','not_started'}

def stopped_bound(root,plan,key):
    root=Path(root).resolve();require=base.require;read=base.read
    marker=root/'stops'/key;stop=read(marker)
    require(type(stop.get('at')) in (float,int),'Stop timestamp unknown')
    marker_bytes=marker.read_bytes();lease_path=root/'leases'/key/'owner.json'
    lease_bytes=lease_path.read_bytes();lease=read(lease_path)
    expected_source=plan['definition']['implementation_sha256'][CONTROLLER]
    require(base.sha(base.ROOT/CONTROLLER)==expected_source,'Controller source changed')
    plan_sha=base.sha(root/'plan.json');allowed={j['job_id'] for j in plan['jobs'] if j['scale_key']==key}
    controllers={};current=None
    for path in (root/'controllers'/key).glob('*/maintenance.json'):
        m=read(path);cid=m.get('controller_id')
        require(cid==path.parent.name and cid not in controllers,'Controller directory mismatch')
        require(m.get('scale_key')==key and m.get('shard')==key and m.get('version')=='rq3-bounded-retry-controller-v1','Controller scope mismatch')
        require(m.get('plan_sha256')==plan_sha and m.get('source_sha256')==expected_source,'Controller provenance mismatch')
        require(m.get('cell_cap')==16 and m.get('target_concurrency')==16,'Controller capacity mismatch')
        require(m.get('run_directory')==str(path.parent),'Controller run path mismatch')
        status=read(path.parent/'status.json');require(same_identity(m,status),'Status identity mismatch')
        xp=path.parent/'exit.json';exit_record=read(xp) if xp.exists() else None
        if exit_record is not None:
            require(same_identity(m,exit_record) and exit_record.get('drained') is True,'Unconfirmed prior controller exit')
            require(not(status.get('at',0)>exit_record.get('at',0) and (status.get('active_local') or status.get('reserved_not_started'))),'Activity after drain')
        else:
            require(current is None and same_identity(m,lease),'Multiple or unleased active controllers')
            current=cid
            require(status.get('stop_dispatch') is True and status.get('at',0)>=stop['at'],'Stop not acknowledged')
            require(type(status.get('active_local')) is int and 0<=status['active_local']<=16,'Invalid active count')
        require(type(status.get('launched')) is int and status['launched']>=0,'Unknown launch coverage')
        controllers[cid]={'owner':m,'status':status,'exit':exit_record,'claims':{},'unconfirmed':set()}
    require(controllers and lease.get('controller_id') in controllers,'Missing lease/controller evidence')
    require(same_identity(lease,controllers[lease['controller_id']]['owner']),'Lease identity mismatch')
    require(read(root/'leases'/key/'runtime.json').get('directory')==lease.get('run_directory'),'Lease runtime differs')
    claims={}
    for path in (root/'jobs/hermes'/key).glob('*/claim/owner.json'):
        owner=read(path);jid=owner.get('job_id');cid=owner.get('controller_id')
        require(jid in allowed and jid not in claims and cid in controllers,'Uncovered claim')
        c=controllers[cid];require(same_identity(owner,c['owner']),'Claim identity differs')
        require(path.parent.parent==root/'jobs'/jid,'Claim directory mismatch')
        rp=path.parent.parent/'attempts/attempt_001/result.json';r=read(rp) if rp.exists() else {}
        confirmed=(r.get('job_id')==jid and r.get('status') in TERMINAL and r.get('slot_released') is True and r.get('unconfirmed_child_termination')==[])
        c['claims'][jid]=owner;claims[jid]=owner
        if not confirmed:c['unconfirmed'].add(jid)
    slot_jobs=set()
    for path in (root/'cells/hermes'/key/'slots').glob('*/owner.json'):
        owner=read(path);jid=owner.get('job_id');require(jid in claims and jid not in slot_jobs,'Uncovered/duplicate occupied slot')
        require(same_identity(owner,claims[jid]) and claims[jid].get('slot')==str(path.parent),'Slot claim identity differs')
        slot_jobs.add(jid)
    bound=0;proof=[]
    for cid,c in controllers.items():
        s=c['status'];reserved=s.get('reserved_not_started');require(reserved is None or reserved in c['claims'],'Reserved claim missing')
        require(len(c['claims'])>=s['launched']+int(reserved is not None),'Claims do not cover launches/reservation')
        unconfirmed=c['unconfirmed']|{j for j in slot_jobs if claims[j]['controller_id']==cid}
        if c['exit'] is not None:require(not unconfirmed,'Exited controller has unconfirmed native claims');upper=0
        else:upper=max(s['active_local']+int(reserved is not None),len(unconfirmed))
        bound+=upper;proof.append({'controller_id':cid,'upper':upper,'active_status':s.get('active_local'),'reserved':reserved,'unconfirmed_claims':len(unconfirmed)})
    require(bound<=16,'Contradictory cell occupancy')
    require(marker.read_bytes()==marker_bytes and lease_path.read_bytes()==lease_bytes,'Stop/lease changed during assessment')
    return {'upper':bound,'scale_key':key,'controllers':proof,'source_sha256':expected_source,'stop_sha256':base.sha(marker),'plan_sha256':plan_sha}

def scale_bound(root,plan,key):
    jobs=[j for j in plan['jobs'] if j['scale_key']==key];base.require(jobs,'Missing planned scale')
    if base.complete(root,jobs):return 0
    if not (Path(root)/'stops'/key).exists():return 16
    try:return stopped_bound(root,plan,key)['upper']
    except (OSError,ValueError,KeyError,TypeError):return 16

_original_prepare=base.prepare_restore
_original_file=base.__file__
def prepare_restore(key):
    # Continue immutable v1 receipts without rewriting their recorded source.
    directory=base.RESTORE/base.restore_name(key);p=directory/'prepared.json'
    if p.exists():
        old=base.read(p);base.require(old.get('source_sha256') in {base.sha(_original_file),base.sha(__file__)},'Unknown restore preparation source')
        with patch.object(base,'__file__',_original_file if old['source_sha256']==base.sha(_original_file) else __file__):return _original_prepare(key)
    return _original_prepare(key)

def main():
    # The same lock, receipts, restore marker namespace, and admission algorithm
    # remain authoritative. Only stop-drain evidence and source provenance differ.
    with patch.object(base,'scale_bound',scale_bound),patch.object(base,'prepare_restore',prepare_restore),patch.object(base,'__file__',__file__):base.main()

if __name__=='__main__':main()
