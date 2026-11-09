#!/usr/bin/env python3
"""Stop only local dispatch, archive its lease, preserve all shared in-flight slots."""
import argparse
import fcntl
import os
from pathlib import Path
import signal
import time
import json
import run_rq3_scale0700_resume_ops5 as pending
from run_bc_campaign_v3 import identity,atomic
from bc_route_runtime_v2 import immutable_json

VERSION='rq3-scale0700-local-cloud-handoff-ops1'
KEYS=('hostname','boot_id','pid_namespace','pid','start_identity','controller_id')


def directory(root):return pending.area(root)/'handoffs/local-to-cloud1'
def read(p):return pending.read(p)
def sha(p):return pending.sha(p)


def same_owner(a,b):return all(a.get(k) is not None and a.get(k)==b.get(k) for k in KEYS)


def verify_local_controller(root,owner,proc_root=Path('/proc'),get_identity=identity):
    actual=get_identity(owner['pid'])
    if any(actual.get(k)!=owner.get(k) for k in KEYS if k!='controller_id'):raise ValueError('Controller process identity changed')
    argv=[os.fsdecode(v) for v in (proc_root/str(owner['pid'])/'cmdline').read_bytes().split(b'\0') if v]
    expected=(pending.ROOT/'scripts/run_rq3_scale0700_resume_ops5.py').resolve()
    if sum(Path(arg).resolve()==expected for arg in argv)!=1:raise ValueError('Signal target is not the approved dispatch controller')
    if '--root' not in argv or Path(argv[argv.index('--root')+1]).resolve()!=Path(root).resolve() or '--live' not in argv:
        raise ValueError('Signal target has wrong campaign or mode')
    return argv


def prepare(root):
    root=Path(root).resolve();pending.verify_authorization(root);out=directory(root);out.mkdir(parents=True,exist_ok=True)
    request=out/'request.json'
    if request.exists():
        saved=read(request)
        if Path(saved['root'])!=root or saved['source_sha256']!=sha(__file__):raise ValueError('Handoff request source changed')
        return saved
    lease=pending.area(root)/'leases'/pending.LABEL;owner=read(lease/'owner.json');runtime=read(lease/'runtime.json');run=Path(runtime['directory']);status=read(run/'status.json')
    if owner.get('version')!=pending.VERSION or not same_owner(owner,status):raise ValueError('Lease and status identity differ')
    if not run.is_relative_to(pending.area(root)/'controllers'/pending.LABEL):raise ValueError('Unexpected original controller directory')
    argv=verify_local_controller(root,owner)
    record={'version':VERSION,'root':str(root),'requested_at_unix':time.time(),'source_sha256':sha(__file__),
        'resume_authorization_path':str(pending.authorization_path(root)),'resume_authorization_sha256':sha(pending.authorization_path(root)),
        'owner':owner,'lease_path':str(lease),'lease_owner_sha256':sha(lease/'owner.json'),'lease_runtime_sha256':sha(lease/'runtime.json'),
        'old_run':str(run),'old_status_path':str(run/'status.json'),'old_command':argv,
        'shared_slots':str(pending.area(root)/'slots'/pending.LABEL),'signals':'Only SIGTERM to exact dispatcher; no native or retry-controller signal',
        'handoff_policy':'Fresh stop_dispatch acknowledgment and no reserved-not-started job before atomic whole-lease archive. Existing claims and slots remain untouched.'}
    immutable_json(request,record);return record


def verify_request(record):
    if record.get('version')!=VERSION or sha(__file__)!=record['source_sha256']:raise ValueError('Handoff implementation changed')
    if sha(record['resume_authorization_path'])!=record['resume_authorization_sha256']:raise ValueError('Scope authorization changed')
    pending.verify_authorization(Path(record['root']))


def signal_dispatcher(record,kill=os.kill,verifier=verify_local_controller):
    verify_request(record);out=directory(Path(record['root']));receipt=out/'signal-delivered.json'
    if receipt.exists():return read(receipt)
    verifier(record['root'],record['owner'])
    kill(record['owner']['pid'],signal.SIGTERM)
    result={'at_unix':time.time(),'owner':record['owner'],'signal':'SIGTERM','target':'exact_local_dispatch_controller','native_signals':0}
    immutable_json(receipt,result);return result


def acknowledged_status(record,now=None):
    now=time.time() if now is None else now;status=read(record['old_status_path'])
    if not same_owner(record['owner'],status):raise ValueError('Stop acknowledgment identity differs')
    timestamp=status.get('at')
    if type(timestamp) not in (int,float) or timestamp<record['requested_at_unix'] or not 0<=now-timestamp<=90:
        return None,'waiting_fresh_post_request_status'
    if status.get('stop_dispatch') is not True:return None,'waiting_stop_dispatch_ack'
    if status.get('reserved_not_started') is not None:return None,'reserved_not_started_requires_separate_resolution'
    return status,'ready_to_archive_dispatch_lease'


def archive_lease(record,now=None):
    verify_request(record);out=directory(Path(record['root']));ready=out/'ready.json';archive=out/'archived-lease';lease=Path(record['lease_path'])
    if ready.exists():
        saved=read(ready)
        if saved['request_sha256']!=sha(out/'request.json') or sha(archive/'owner.json')!=record['lease_owner_sha256'] or sha(archive/'runtime.json')!=record['lease_runtime_sha256']:
            raise ValueError('Existing handoff archive changed')
        return saved,'already_ready_no_second_handoff'
    status,reason=acknowledged_status(record,now)
    if status is None:return None,reason
    if archive.exists():
        if lease.exists():raise ValueError('Canonical lease occupied after uncommitted handoff; never steal it')
        if sha(archive/'owner.json')!=record['lease_owner_sha256'] or sha(archive/'runtime.json')!=record['lease_runtime_sha256']:raise ValueError('Archive has unexpected identity')
    else:
        if sha(lease/'owner.json')!=record['lease_owner_sha256'] or sha(lease/'runtime.json')!=record['lease_runtime_sha256']:raise ValueError('Canonical lease changed before handoff')
        # No native claims/slots are removed. The pinned old controller writes
        # this lease only at startup and cannot dispatch after this checkpoint.
        immutable_json(out/'stop-ack.json',status)
        os.rename(lease,archive)
    result={'version':VERSION,'ready_at_unix':time.time(),'root':record['root'],'scale':pending.LABEL,
        'request_sha256':sha(out/'request.json'),'predecessor_identity':record['owner'],'predecessor_stop_ack_path':str(out/'stop-ack.json'),
        'predecessor_stop_ack_sha256':sha(out/'stop-ack.json'),'archived_lease':str(archive),
        'archived_owner_sha256':sha(archive/'owner.json'),'archived_runtime_sha256':sha(archive/'runtime.json'),
        'shared_slots':record['shared_slots'],'shared_scale_ceiling':16,'old_active_at_ack':status.get('active_local'),
        'native_interrupted':False,'retry15_touched':False,'new_claim_policy':'Original ops5 authorization219 only; shared slots count all old children and retry15'}
    immutable_json(ready,result);return result,'ready'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=pending.old.scientific.DEFAULT_ROOT);parser.add_argument('--live',action='store_true');parser.add_argument('--watch',action='store_true');args=parser.parse_args()
    root=args.root.resolve();out=directory(root);out.mkdir(parents=True,exist_ok=True)
    with (out/'operation.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);record=prepare(root)
        if not args.live:print(json.dumps({'live':False,'old_pid':record['owner']['pid'],'out':str(out)}));return
        signal_dispatcher(record)
        while True:
            ready,state=archive_lease(record);atomic(out/'status.json',{'at_unix':time.time(),'state':state,'new_native_calls':0})
            print(json.dumps({'state':state,'ready_path':str(out/'ready.json') if ready else None}),flush=True)
            if ready or not args.watch:return
            time.sleep(3)

if __name__=='__main__':main()
