"""Persist fresh read-only route accounting without changing the running grader."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import threading
import time
import uuid
from lab import ROOT
from monitor_bc_campaign_v3 import aggregate
from visual_inline_route_accounting_v5 import resources

VERSION='visual-inline-resource-observer-v5'
DEFAULT_ROOT=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v5'
DEFAULT_OUTPUT=ROOT/'outputs/grading/visual-inline-failure-retry-v5'

def utc_now():return datetime.now(timezone.utc).isoformat()

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('x',encoding='utf-8')as output:
            os.chmod(temporary,0o600)
            json.dump(value,output,ensure_ascii=False,indent=2,allow_nan=False)
            output.write('\n');output.flush();os.fsync(output.fileno())
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()

def load_cells(root):
    root=Path(root).resolve();raw=(root/'inventory.json').read_bytes();inventory=json.loads(raw)
    cells={};bindings={}
    for item in inventory['cells']:
        name=item['cell'];directory=(root/'cells'/name).resolve()
        if directory.parent!=root/'cells' or name in cells:raise ValueError('Invalid or duplicate cell identity')
        data=(directory/'plan.json').read_bytes();digest=hashlib.sha256(data).hexdigest()
        if digest!=item['plan_sha256']:raise ValueError('Frozen plan binding differs')
        cells[name]={'root':directory,'plan':json.loads(data)};bindings[name]=digest
    return cells,{'inventory_sha256':hashlib.sha256(raw).hexdigest(),'plan_sha256':bindings}

def build_snapshot(root,output):
    started=utc_now();clock=time.monotonic();cells,bindings=load_cells(root)
    value=resources(cells,Path(output));all_rows=[];issue_counts=Counter();issue_examples=[]
    for name,cell in value['cells'].items():
        rows=cell.pop('http_attempt_records',[]);all_rows.extend(rows)
        attempts=cell.pop('attempt_accounting',[]);issues=[i for a in attempts for i in a.get('issues',[])]
        cell['accounting_issues']=dict(Counter(i.get('kind','unknown')for i in issues))
        cell['accounting_issue_examples']=issues[:20]
        cell['sdk_observations_suppressed']=sum(a.get('sdk_observations_suppressed',0)for a in attempts)
        issue_counts.update(cell['accounting_issues'])
        issue_examples.extend({'cell':name,**i}for i in issues[:3])
    totals=aggregate(all_rows)
    value.update(observer_version=VERSION,scan_started_at=started,scan_finished_at=utc_now(),
       client_scan_seconds=time.monotonic()-clock,source_bindings=bindings,model_calls=0,
       prediction_tree_read_only=True,scan_is_atomic_across_workers=False,
       total_prediction_usage=totals,
       observed_http_attempts=sum(c['http_attempts']for c in value['cells'].values()),
       unknown_usage_attempts=sum(c['unknown_usage_attempts']for c in value['cells'].values()),
       accounting_issues=dict(issue_counts),accounting_issue_examples=issue_examples[:30],
       alias_and_conservation_issues=totals['conservation_issues'],
       previous_success_preserved_on_refresh_error=True)
    return value

def refresh_once(root,output,builder=None):
    """A failed collection/serialization never replaces the prior good snapshot."""
    output=Path(output);current=output/'resources-current.json';status=output/'resources-observer-status.json'
    started=utc_now()
    try:
        value=(builder or build_snapshot)(root,output)
        atomic_json(current,value)
    except Exception as exc:
        report={'version':VERSION,'pid':os.getpid(),'state':'refresh_failed','at':utc_now(),
                'scan_started_at':started,'error_type':type(exc).__name__,
                'previous_success_snapshot_present':current.exists(),'model_calls':0}
        atomic_json(status,report)
        return False,report
    report={'version':VERSION,'pid':os.getpid(),'state':'watching','at':utc_now(),
            'last_success_at':value['scan_finished_at'],'client_scan_seconds':value['client_scan_seconds'],
            'snapshot_path':str(current.resolve()),'model_calls':0,
            'observed_http_attempts':value['observed_http_attempts'],
            'unknown_usage_attempts':value['unknown_usage_attempts'],
            'accounting_issues':value['accounting_issues'],
            'alias_and_conservation_issues':value['alias_and_conservation_issues']}
    atomic_json(status,report)
    return True,report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=DEFAULT_ROOT);p.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    p.add_argument('--interval',type=float,default=60);p.add_argument('--once',action='store_true');args=p.parse_args()
    if not 10<=args.interval<=3600:p.error('Refresh interval must be 10..3600 seconds')
    root=args.root.resolve();output=args.output.resolve()
    if root==output or root in output.parents:raise ValueError('Statistics must be outside prediction tree')
    output.mkdir(parents=True,exist_ok=True);stop=threading.Event()
    signal.signal(signal.SIGINT,lambda *_:stop.set());signal.signal(signal.SIGTERM,lambda *_:stop.set())
    with (output/'resources-observer.lock').open('a')as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        atomic_json(output/'resources-observer-status.json',{'version':VERSION,'pid':os.getpid(),
            'state':'starting','at':utc_now(),'refresh_interval_seconds':args.interval,'model_calls':0})
        while not stop.is_set():
            ok,report=refresh_once(root,output)
            print(json.dumps(report,ensure_ascii=False),flush=True)
            if args.once:break
            stop.wait(args.interval)
        if not args.once:
            atomic_json(output/'resources-observer-status.json',{'version':VERSION,'pid':os.getpid(),
                'state':'stopped','at':utc_now(),'previous_success_snapshot_present':(output/'resources-current.json').exists(),'model_calls':0})
if __name__=='__main__':main()
