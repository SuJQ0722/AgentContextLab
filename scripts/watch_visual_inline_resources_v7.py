"""Read-only V7 accounting and controller observer; exits after the grader finishes."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import threading
import time
from lab import ROOT
from watch_visual_inline_resources_v5 import refresh_once, atomic_json, load_cells

DEFAULT_ROOT=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v7-two-hour'
OUTPUT=ROOT/'outputs/grading/visual-inline-two-hour-v7'


def read(path):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return {}


def controller_status(root):
    cells,_=load_cells(root);rows={}
    for name,item in cells.items():
        statuses=[]
        for path in (item['root']/'controllers').glob('*/*/status.json'):
            value=read(path);end=read(path.parent/'exit.json')
            statuses.append({'pid':value.get('pid'),'heartbeat_unix':value.get('heartbeat_unix'),
               'active_local':value.get('active_local'),'target_concurrency':value.get('target_concurrency'),
               'launched':value.get('launched'),'stop_dispatch':value.get('stop_dispatch'),
               'error_type':value.get('error_type'),'exit':end})
        rows[name]={'planned':len(item['plan']['jobs']),'controllers':statuses}
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    p.add_argument('--output',type=Path,default=OUTPUT);p.add_argument('--interval',type=int,default=300);a=p.parse_args()
    if not 60<=a.interval<=3600:p.error('Interval 60..3600 seconds')
    root=a.root.resolve();out=a.output.resolve()
    if root==out or root in out.parents:raise ValueError('Observer output outside prediction root required')
    out.mkdir(parents=True,exist_ok=True);stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
    with (out/'resources-observer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        atomic_json(out/'v7-observer-service.json',{'pid':os.getpid(),'started_at_unix':time.time(),'interval':a.interval,'model_calls':0,'automatic_retry':False})
        while not stop.is_set():
            ok,status=refresh_once(root,out)
            grade=read(out/'status.json')
            try:controllers=controller_status(root);error=None
            except Exception as exc:controllers={};error=type(exc).__name__
            atomic_json(out/'v7-progress.json',{'at_unix':time.time(),'observer_pid':os.getpid(),'resources_refreshed':ok,
                'grader':grade,'cells':controllers,'controller_read_error':error,'model_calls':0,'native_signaled':False})
            if grade.get('finished') and grade.get('all_terminal'):
                atomic_json(out/'v7-observer-exit.json',{'at_unix':time.time(),'reason':'all_predictions_terminal_and_private_grader_finished','native_signaled':False});return
            stop.wait(a.interval)
        atomic_json(out/'v7-observer-exit.json',{'at_unix':time.time(),'reason':'observer_stop_signal','native_signaled':False})


if __name__=='__main__':main()
