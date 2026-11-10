#!/usr/bin/env python3
"""Operational readiness recovery without changing scientific frozen sources."""
import time,json,socket,hashlib,sys
from pathlib import Path
import bootstrap_visual_hosted_retry_v1 as bootstrap

def main():
 bootstrap.ROLES['run_visual_hosted_retry_ops2.py']='controller'
 original_serve=bootstrap.base.serve
 def serve(args,plan,*a,**kw):
  plan['operational_readiness_version']='visual-hosted-ops2'
  plan['operational_readiness_sha256']={n:hashlib.sha256((bootstrap.ROOT/'scripts'/n).read_bytes()).hexdigest() for n in ('bootstrap_visual_hosted_ops2.py','run_visual_hosted_retry_ops2.py')}
  return original_serve(args,plan,*a,**kw)
 bootstrap.base.serve=serve
 checked=bootstrap.base.checked;commands=bootstrap.commands
 def retry(argv,*a,**kw):
  for attempt in range(1,6):
   try:return checked(argv,*a,**kw)
   except Exception:
    if not any(str(x).endswith('preflight_bc_v3_web.py')for x in argv)or attempt==5:raise
    time.sleep(3)
 def operational(args):
  result=commands(args)
  result['telemetry']=[str(x).replace('bootstrap_visual_hosted_retry_v1.py','bootstrap_visual_hosted_ops2.py')for x in result['telemetry']]
  result['controller']=[str(x).replace('run_visual_hosted_retry_v1.py','run_visual_hosted_retry_ops2.py')for x in result['controller']]
  return result
 bootstrap.base.checked=retry;bootstrap.commands=operational
 try:bootstrap.main()
 finally:bootstrap.base.checked=checked;bootstrap.commands=commands;bootstrap.base.serve=original_serve
if __name__=='__main__':main()
