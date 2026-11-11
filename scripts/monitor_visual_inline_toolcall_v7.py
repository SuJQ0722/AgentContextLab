"""Stop only exact naturally drained allocations of the independent toolcall-server deployment."""
import argparse
import fcntl
import os
import signal
import threading
import time
from unittest.mock import patch
from repool_visual_inline_toolcall_v7 import CELLS,RECEIPTS,app_name
import monitor_visual_inline_two_hour_v7 as parent
from run_bc_campaign_v3 import atomic,identity

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--watch',action='store_true');p.add_argument('--live',action='store_true');a=p.parse_args()
    if a.live and not a.watch:p.error('Live requires watch')
    area=RECEIPTS/'lifecycle';area.mkdir(parents=True,exist_ok=True);stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
    with (area/'controller.lock').open('a') as lock,patch.object(parent,'app_name',app_name):
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);cache={}
        atomic(area/'service.json',{'pid':os.getpid(),'identity':identity(),'source_sha256':parent.sha(__file__),'at_unix':time.time()})
        while not stop.is_set():
            rows=[]
            for cell in CELLS:
                try:row=parent.cycle(cell,a.live,receipts=RECEIPTS,cache=cache)
                except Exception as e:row={'cell':cell,'state':'unknown_no_stop','error_type':type(e).__name__,'reason':str(e)}
                rows.append(row)
            atomic(area/'latest.json',{'at_unix':time.time(),'cells':rows,'model_calls':0,'auto_create':False})
            if not a.watch or all(row['state']=='stopped'for row in rows):break
            stop.wait(30)
        atomic(area/'exit.json',{'at_unix':time.time(),'native_signaled':False})

if __name__=='__main__':main()
