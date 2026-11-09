#!/usr/bin/env python3
"""Explicit v5 native supervisor; frozen v4 scientific inputs and wall limit."""
import argparse,json,os,signal,subprocess,time
from pathlib import Path
from run_controlled_native_v4 import ROOT,atomic,process_identity,digest
from lab import environment,python_for
SOURCES=('controlled_native_worker_v5.py','capture_multimodal_prefix_v5.py','controlled_transport_v5.py','run_controlled_native_v5_trial.py','controlled_attempts_v5.py','run_controlled_native_v5_ops3.py')
def runtime_hashes():return {n:digest((ROOT/'scripts'/n).read_bytes()) for n in SOURCES}
def trial(spec_path,out,kind):
    out.mkdir(parents=True,exist_ok=True)
    if any((out/n).exists() for n in ('result.json','worker-started.json','supervisor.json')):raise ValueError('Prior execution exists; no automatic retry')
    atomic(out/'supervisor.json',{'pid':os.getpid(),'identity':process_identity(os.getpid()),'started':time.time()})
    spec=json.loads(spec_path.read_text());env,_=environment(ROOT,'hermes',Path(spec['config_path']))
    script='capture_multimodal_prefix_v5.py' if kind=='capture' else 'controlled_native_worker_v5.py'
    if script not in ['capture_multimodal_prefix_v5.py','controlled_native_worker_v5.py']:raise ValueError('Unexpected worker script')
    cmd=[python_for(ROOT),str(ROOT/'scripts'/script),'--spec',str(spec_path),'--out',str(out)]
    if kind=='capture':cmd.insert(2,'--worker')
    else:cmd.append('--live')
    atomic(out/'runtime-dispatch-v5.json',{'version':'controlled-v5-ops3','kind':kind,'worker':script,'spec_sha256':digest(spec_path.read_bytes()),'sources_sha256':runtime_hashes(),'new_retry_loop':False,'wall_limit_seconds':3600})
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


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--spec',type=Path,required=True);p.add_argument('--root',type=Path,required=True);p.add_argument('--trial',choices=['capture','method'],required=True);p.add_argument('--live',action='store_true');a=p.parse_args()
    if not a.live:print(json.dumps({'live':False,'runtime':'controlled-v5-ops3'}))
    else:trial(a.spec,a.root,a.trial)
