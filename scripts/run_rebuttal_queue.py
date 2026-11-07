#!/usr/bin/env python3
"""Two parallel, bounded native-prefix captures with conservative process admission.

Default makes no API calls. Core BC workers are never modified. Started captures
are preserved without automatic retry; SIGTERM stops dispatch only.
"""
import argparse
from datetime import datetime,timezone
import fcntl
import json
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import time
from lab import ROOT,python_for
from monitor_rebuttal import process_snapshot,read_json
from run_bc_trial import atomic,process_identity


def auxiliary_workers(live):
    """Count model workers, excluding reports and capture parent/child duplication."""
    selected={}; capture={}
    for pid,info in live.items():
        try:argv=[os.fsdecode(x) for x in (Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0') if x]
        except OSError:continue
        names=[Path(x).name for x in argv if ' ' not in x and '\n' not in x]
        if 'capture_multimodal_prefix.py' in names:capture[pid]=info
        elif 'controlled_native_preflight.py' in names:selected[pid]='calibration'
        elif 'info_loss_eval.py' in names or 'info_loss_campaign.py' in names:selected[pid]='information_loss'
        elif any(n in names for n in ('run_bc_trial.py','rq3_trial.py')) and any('/rq3-deepseek-bc100-r3/' in x for x in argv):selected[pid]='rq3'
    # A capture launcher reserves one slot before its native model child starts.
    for pid,info in capture.items():
        if info['ppid'] not in capture:selected[pid]='capture'
    for pid in list(selected):
        if selected[pid]=='information_loss' and selected.get(live[pid]['ppid'])=='information_loss':
            del selected[pid]
    return selected


def capture_gate(queue):
    """Only original successful captures with intact hashes admit the next stage."""
    for ds in ['browsecomp_v3','mmbrowsecomp']:
        folder=queue/ds;result=read_json(folder/'result.json')
        if not result:return 'waiting',ds+' capture pending'
        if result.get('status')!='captured':return 'blocked',ds+' capture '+str(result.get('status'))
        manifest=read_json(folder/'prefix-manifest.json')
        try:actual=hashlib.sha256((folder/'prefix.json').read_bytes()).hexdigest()
        except OSError:return 'blocked',ds+' prefix missing'
        if not manifest or manifest.get('status')!='captured' or actual!=manifest.get('sha256'):
            return 'blocked',ds+' prefix fingerprint mismatch'
    return 'ready','both original prefixes captured and verified'


def fresh_stage(queue,admit,live):
    """At most one automatic launch; uncertain started stages are never retried."""
    out=queue.parent/'native-budget-preflight-fresh';status_path=queue/'fresh-stage.json'
    def status(state,reason,**extra):
        result={'state':state,'reason':reason,'updated_at':datetime.now(timezone.utc).isoformat(),
                'output':str(out),'request_cap':12,'formal_baseline_started':False,**extra}
        atomic(status_path,result);return state
    old=read_json(status_path) or {}
    if old.get('state')=='blocked':return 'blocked'
    result=read_json(out/'results.json')
    if result and result.get('status')=='completed':return status('completed','bounded calibration ended; inspect budget gates')
    marker=read_json(out/'stage-started.json')
    if marker:
        pid=marker.get('pid');identity=marker.get('start_identity')
        if pid in live and identity and live[pid]['start_identity']==identity:return status('running','single existing stage adopted',pid=pid)
        return status('blocked','started stage no longer alive; preserve unknown calls; automatic retry forbidden')
    state,reason=capture_gate(queue)
    if state!='ready':return status(state,reason)
    if not admit:return status('waiting','resource admission: auxiliary <6, live <104 and visible <128 required')
    try:
        from controlled_native_preflight import prepare_captures
        out.mkdir(parents=True,exist_ok=True)
        if not (out/'manifest.json').exists():prepare_captures(out,queue)
        else:
            # Validate existing prepared fixture against the exact captured sources.
            manifest=json.loads((out/'manifest.json').read_text())
            if manifest.get('request_cap')!=12 or manifest.get('post_compression_token_ceiling')!=16384:raise ValueError('Prepared budget/cap mismatch')
            expected={json.loads((queue/d/'spec.json').read_text())['question_id'] for d in ['browsecomp_v3','mmbrowsecomp']}
            if {s['question_id'] for s in manifest['samples']}!=expected:raise ValueError('Prepared cohort mismatch')
            for sample in manifest['samples']:
                if hashlib.sha256(Path(sample['source_path']).read_bytes()).hexdigest()!=sample['source_sha256']:raise ValueError('Prepared prefix changed')
                if not sample.get('complete_native_evidence'):raise ValueError('Incomplete prepared native evidence')
                for item in sample['input_images']:
                    if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Prepared native image changed')
        if list((out/'calls').glob('*/started.json')):return status('blocked','calls already started without stage marker; no automatic retry')
        current=process_snapshot();current_live={p:r for p,r in current.items() if r['state']!='Z'}
        if len(current_live)>=104 or len(current)>=128 or len(auxiliary_workers(current_live))>=6:
            return status('waiting','prepared; admission recheck deferred launch')
        atomic(out/'stage-started.json',{'pid':None,'start_identity':None,'started_at':datetime.now(timezone.utc).isoformat(),'request_cap':12})
        with (out/'process.log').open('a') as log:
            child=subprocess.Popen([python_for(ROOT),str(ROOT/'scripts/controlled_native_preflight.py'),
                '--prefix-capture-root',str(queue),'--output',str(out),'--live','--resume'],cwd=ROOT,
                stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        atomic(out/'stage-started.json',{'pid':child.pid,'start_identity':process_identity(child.pid),
            'started_at':datetime.now(timezone.utc).isoformat(),'request_cap':12})
        return status('running','prepared without API, then launched once',pid=child.pid)
    except Exception as error:return status('blocked','prepare or launch failed: '+type(error).__name__)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true');a=p.parse_args()
    queue=ROOT/'outputs/experiment3/prefix-capture';queue.mkdir(parents=True,exist_ok=True)
    datasets=['browsecomp_v3','mmbrowsecomp']
    if not a.live:
        print(json.dumps({'paid_calls':0,'queue':datasets,'concurrency':2,'wait_for_calibration':False,
            'live_process_admission_below':104,'visible_process_ceiling':128,'auxiliary_model_worker_cap':6}));return
    lease=(queue/'queue.lock').open('a');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    atomic(queue/'queue-service.json',{'pid':os.getpid(),'start_identity':process_identity(os.getpid()),'started_at':datetime.now(timezone.utc).isoformat()})
    stopped=False
    def stop(*unused):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    children={}
    while not stopped:
        for ds,child in list(children.items()):
            if child.poll() is not None:del children[ds]
        processes=process_snapshot();live={p:r for p,r in processes.items() if r['state']!='Z'}
        workers=auxiliary_workers(live);captures=sum(v=='capture' for v in workers.values())
        statuses={ds:('terminal' if (queue/ds/'result.json').exists() else 'started_preserved' if (queue/ds/'started.json').exists() else 'dispatching' if ds in children else 'pending') for ds in datasets}
        atomic(queue/'queue-status.json',{'updated_at':datetime.now(timezone.utc).isoformat(),'states':statuses,
            'waiting_for_calibration':False,'capture_alive':captures,'visible_live_processes':len(live),
            'visible_processes_including_zombies':len(processes),'process_admission_threshold':104,
            'visible_process_ceiling':128,'capture_concurrency':2,'auxiliary_model_worker_cap':6,
            'auxiliary_workers':workers,'formal_baseline_started':False})
        admission=len(workers)<6 and len(live)<104 and len(processes)<128
        stage=fresh_stage(queue,admission,live)
        if stage=='waiting' and all(s!='pending' for s in statuses.values()) and not captures and not children and any(not (queue/d/'result.json').exists() for d in datasets):
            atomic(queue/'fresh-stage.json',{'state':'blocked','reason':'capture exited without result; preserve unknown calls, no automatic retry','formal_baseline_started':False});stage='blocked'
        if all(s!='pending' for s in statuses.values()) and not captures and not children and stage in ('completed','blocked'):return
        # Rescan after every launch; leave >=24 slots for native child creation.
        if captures<2 and len(workers)<6 and len(live)<104 and len(processes)<128:
            ds=next((d for d,s in statuses.items() if s=='pending'),None)
            if ds:
                with (queue/f'{ds}-launcher.log').open('a') as log:
                    children[ds]=subprocess.Popen([python_for(ROOT),str(ROOT/'scripts/capture_multimodal_prefix.py'),'--dataset',ds,'--live'],cwd=ROOT,
                        stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                time.sleep(2)
                continue
        time.sleep(5)


if __name__=='__main__':main()
