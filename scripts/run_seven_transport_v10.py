#!/usr/bin/env python3
"""Retry only zero-model tool readiness; preserve frozen inference controller."""
import json,time
import preflight_bc_v3_web as readiness
import run_seven_retry3_v10 as controller
from pathlib import Path

def main():
 original=readiness.preflight
 def probe(root,config):
  for attempt in range(1,6):
   try:result=original(root,config)
   except Exception as exc:result={'passed':False,'error_type':type(exc).__name__}
   with (Path(root)/'preflight-seven-transport-v10.jsonl').open('a')as f:f.write(json.dumps({'at':time.time(),'attempt':attempt,'passed':result['passed'],'model_calls':0})+'\n')
   if result['passed']or attempt==5:return result
   time.sleep(3)
 readiness.preflight=probe
 try:controller.main()
 finally:readiness.preflight=original
if __name__=='__main__':main()
