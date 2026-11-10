#!/usr/bin/env python3
"""Validate Node HTTPS reachability with unauthenticated, zero-model GET."""
import json,os,subprocess,time,socket,uuid
from pathlib import Path
from lab import ROOT
NODE=ROOT/'.tools/node-v24.11.0-linux-x64/bin/node'
PROBE="""const base=process.env.TOKENHUB_BASE_URL;if(!base)throw Error('base missing');let phase='get_models';try{const r=await fetch(base.replace(/\/$/,'')+'/models',{signal:AbortSignal.timeout(20000)});await r.body?.cancel();if(![401,403].includes(r.status)){console.log(JSON.stringify({status:r.status,phase,passed:false}));process.exit(0);}phase='guarded_post';const {guardedFetch,safeError}=await import(process.env.ACL_NODE_PREFLIGHT_MODULE);const endpoint=base.replace(/\/$/,'')+'/chat/completions';const guarded=guardedFetch({original:globalThis.fetch,transform:async body=>({wire:body,ledger:{preflight:true}}),endpoint,emit:()=>{},terminate:()=>{throw Error('preflight guard terminal');},timeoutMs:20000});const body=JSON.stringify({probe:'网络验证'});const post=await guarded(endpoint,{method:'POST',headers:{'content-type':'application/json','content-length':String(Buffer.byteLength(body))},body});await post.body?.cancel();console.log(JSON.stringify({status:post.status,phase,passed:[401,403].includes(post.status)}));}catch(e){console.log(JSON.stringify({passed:false,phase,error_type:e.name,cause_code:e.cause?.code,cause_codes:e.cause?.errors?.map(x=>x.code)}));}"""

def check(root):
 from bootstrap_bc_retry1 import read_env
 environment=dict(os.environ)
 environment['ACL_NODE_PREFLIGHT_MODULE']=(ROOT/'scripts/dsh_hosted_wire_v2.mjs').as_uri()
 environment['TOKENHUB_BASE_URL']=environment.get('TOKENHUB_BASE_URL')or read_env(ROOT/'.env').get('TOKENHUB_BASE_URL','')
 if not environment['TOKENHUB_BASE_URL']:raise ValueError('Node probe requires configured gateway')
 directory=Path(root)/'runtime/node-preflight'/socket.gethostname();directory.mkdir(parents=True,exist_ok=True)
 rows=[]
 for attempt in range(1,6):
  try:
   completed=subprocess.run([str(NODE),'--input-type=module','-e',PROBE],env=environment,capture_output=True,text=True,timeout=50)
   row=json.loads(completed.stdout.strip());row['exit_code']=completed.returncode
  except Exception as exc:row={'passed':False,'error_type':type(exc).__name__}
  row.update(at=time.time(),attempt=attempt,model_calls=0,authorization_sent=False)
  rows.append(row)
  if row.get('passed'):break
  if attempt<5:time.sleep(3)
 result={'version':'dsh-native-node-transport-readiness-v4','passed':rows[-1]['passed'],'attempts':rows,'model_calls':0}
 (directory/(uuid.uuid4().hex+'.json')).write_text(json.dumps(result,indent=2)+'\n')
 if not result['passed']:raise RuntimeError('Native Node gateway transport failed; dispatch prohibited')
 return result
