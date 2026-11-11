#!/usr/bin/env python3
"""Validate Node HTTPS reachability with unauthenticated, zero-model GET."""
import json,os,subprocess,time,socket,uuid
from pathlib import Path
from lab import ROOT
NODE=ROOT/'.tools/node-v24.11.0-linux-x64/bin/node'
PROBE="""const base=process.env.TOKENHUB_BASE_URL;if(!base)throw Error('base missing');try{const r=await fetch(base.replace(/\/$/,'')+'/models',{signal:AbortSignal.timeout(20000)});await r.body?.cancel();console.log(JSON.stringify({status:r.status,passed:[401,403].includes(r.status)}));}catch(e){console.log(JSON.stringify({passed:false,error_type:e.name,cause_code:e.cause?.code,cause_codes:e.cause?.errors?.map(x=>x.code)}));}"""

def check(root):
 from bootstrap_bc_retry1 import read_env
 environment=dict(os.environ)
 environment['TOKENHUB_BASE_URL']=environment.get('TOKENHUB_BASE_URL')or read_env(ROOT/'.env').get('TOKENHUB_BASE_URL','')
 if not environment['TOKENHUB_BASE_URL']:raise ValueError('Node probe requires configured gateway')
 directory=Path(root)/'runtime/node-preflight'/socket.gethostname();directory.mkdir(parents=True,exist_ok=True)
 rows=[]
 for attempt in range(1,6):
  try:
   completed=subprocess.run([str(NODE),'--input-type=module','-e',PROBE],env=environment,capture_output=True,text=True,timeout=50)
   row=json.loads(completed.stdout.strip());row['exit_code']=completed.returncode
   if row.get('passed'):
    models_status=row.get('status')
    completed=subprocess.run([str(NODE),str(ROOT/'scripts/preflight_dsh_hosted_dispatcher_v4.mjs')],env=environment,capture_output=True,text=True,timeout=45)
    row=json.loads(completed.stdout.strip());row.update(exit_code=completed.returncode,models_status=models_status)
    row['passed']=row.get('passed')is True and completed.returncode==0
  except Exception as exc:row={'passed':False,'error_type':type(exc).__name__}
  row.update(at=time.time(),attempt=attempt,model_calls=0,authorization_sent=False)
  rows.append(row)
  if row.get('passed'):break
  if attempt<5:time.sleep(3)
 result={'version':'dsh-native-node-transport-readiness-v6','passed':rows[-1]['passed'],'attempts':rows,'model_calls':0}
 (directory/(uuid.uuid4().hex+'.json')).write_text(json.dumps(result,indent=2)+'\n')
 if not result['passed']:raise RuntimeError('Native Node gateway transport failed; dispatch prohibited')
 return result
