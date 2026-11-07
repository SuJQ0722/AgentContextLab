#!/usr/bin/env python3
"""Run one immutable campaign job; retain interrupted attempts and native artifacts."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from lab import ROOT, environment, python_for


def atomic(path,data):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.replace(path)


def process_identity(pid):
    try:
        fields=Path(f'/proc/{pid}/stat').read_text().split(') ',1)[1].split()
        return fields[19] if fields[0]!='Z' else None
    except (OSError,IndexError):return None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--live',action='store_true');args=p.parse_args()
    spec=json.loads(args.spec.read_text());out=args.out.resolve()
    if not args.live:print(json.dumps({'live':False,'job_id':spec['job_id']}));return
    out.mkdir(parents=True,exist_ok=True)
    lease=(out/'lease.lock').open('a');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (out/'result.json').exists():return
    start=time.monotonic();interrupted=False;child=None;timed_out=False
    atomic(out/'running.json',{'pid':os.getpid(),'start_identity':process_identity(os.getpid()),
        'started_at':datetime.now(timezone.utc).isoformat(),'job_id':spec['job_id']})
    def stop(signum=None,frame=None):
        nonlocal interrupted
        interrupted=True
        # DSH CLI owns a nested process group; terminate it explicitly too.
        for f in out.glob('native/*/*/running.json'):
            try:os.killpg(json.loads(f.read_text())['pid'],signal.SIGTERM)
            except (ProcessLookupError,KeyError):pass
        if child and child.poll() is None:
            try:os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError:pass
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    env,cfg=environment(ROOT,spec['harness'],spec['config_path'])
    if spec['harness']=='dsh':
        strategy={'visual':'visual_native','sliding_window':'sliding_window_native'}.get(spec['strategy'],spec['strategy'])
        cmd=[sys.executable,str(ROOT/'scripts/run_dsh_eval.py'),'--dataset','bc100','--strategies',strategy,
            '--question-id',spec['question_id'],'--repeat',str(spec['repeat']),'--limit','100',
            '--timeout',str(spec['timeout_seconds']),'--output-root',str(out/'native'),
            '--config',spec['config_path'],'--web-prevalidated','--live']
        native_result=out/'native'/strategy/spec['question_id']/'result.json'
        hard_timeout=spec['timeout_seconds']+240
    else:
        cmd=[python_for(ROOT),str(ROOT/'scripts/hermes_bc_worker.py'),'--spec',str(args.spec.resolve()),'--out',str(out/'native'),'--live']
        native_result=out/'native/native-result.json';hard_timeout=spec['timeout_seconds']
    (out/'native').mkdir(exist_ok=True)
    with (out/'worker.log').open('a') as log:
        child=subprocess.Popen(cmd,env=env,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        while child.poll() is None:
            if interrupted or time.monotonic()-start>hard_timeout:
                timed_out=not interrupted;stop();interrupted=not timed_out
                try:child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    try:os.killpg(child.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    child.wait()
                break
            time.sleep(.5)
    native=json.loads(native_result.read_text()) if native_result.exists() else {}
    status='interrupted' if interrupted else 'timeout' if timed_out else native.get('status','failed')
    result={'job_id':spec['job_id'],'harness':spec['harness'],'strategy':spec['strategy'],
        'question_id':spec['question_id'],'repeat':spec['repeat'],'model':spec['model'],
        'status':status,'failure_category':'user_or_scheduler_stop' if interrupted else 'timeout' if timed_out else native.get('failure_category'),
        'exit_code':child.returncode,'end_to_end_seconds':time.monotonic()-start,
        'native_end_to_end_seconds':native.get('end_to_end_seconds'),
        'final':native.get('final'),'native_result_path':str(native_result) if native else None,
        'finished_at':datetime.now(timezone.utc).isoformat()}
    atomic(out/'result.json',result)


if __name__=='__main__':main()
