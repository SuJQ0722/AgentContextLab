#!/usr/bin/env python3
"""Retry only zero-model tool readiness; preserve frozen inference controller."""
import json,time
import preflight_bc_v3_web as readiness
import run_visual_hosted_retry_v2 as controller
from pathlib import Path

def main():
 original=readiness.preflight
 def probe(root,config):
  for attempt in range(1,6):
   result=original(root,config)
   with (Path(root)/'preflight-transport-v4.jsonl').open('a')as f:f.write(json.dumps({'at':time.time(),'attempt':attempt,'passed':result['passed'],'model_calls':0})+'\n')
   if result['passed']or attempt==5:return result
   time.sleep(3)
 readiness.preflight=probe
 try:controller.main()
 finally:readiness.preflight=original
if __name__=='__main__':main()
