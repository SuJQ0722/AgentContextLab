"""Read-only incremental progress; no replay, model calls, or cloud mutation."""
import json,time,fcntl,os
from pathlib import Path
R=Path('/mnt/afs_agents/sujiaqi/workspace/projects/AgentContextLab');ROOT=R/'outputs/campaigns/mmbc-timeout-once-v18';OUT=R/'outputs/cloud-runtime/mmbc-timeout-once-v18';AREA=OUT/'monitor';AREA.mkdir(parents=True,exist_ok=True);lock=(AREA/'lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
plans={};tails={};counts={};last={}
def read(p):return json.loads(p.read_text())
def atomic(p,v):t=p.with_suffix('.tmp');t.write_text(json.dumps(v,indent=2));t.replace(p)
def wire(p):
 key=str(p);entry=counts.setdefault(key,{'requests':0,'complete_usage':0,'route_errors':0,'providers':{}})
 if not p.exists():return entry
 start=tails.get(key,0)
 with p.open('rb')as f:
  f.seek(start)
  while True:
   pos=f.tell();raw=f.readline()
   if not raw or not raw.endswith(b'\n'):tails[key]=pos;break
   try:v=json.loads(raw)
   except Exception:continue
   event=v.get('event');entry['requests']+=event in('request_started','final_inline_request');entry['complete_usage']+=event=='stream_complete'and bool(v.get('raw_provider_usage'));entry['route_errors']+=event in('route_failed','route_http_error','route_transport_error')
   route=v.get('route')or v.get('actual_model')
   if route:
    q=entry['providers'].setdefault(route,{'requests':0,'complete_usage':0,'errors':{},'http_status':{}});q['requests']+=event in('request_started','final_inline_request');q['complete_usage']+=event=='stream_complete'and bool(v.get('raw_provider_usage'))
    if event in('route_failed','route_http_error','route_transport_error'):
     err=v.get('provider_code')or v.get('error_type')or'unknown';q['errors'][err]=q['errors'].get(err,0)+1;code=str(v.get('status_code',v.get('status','unknown')));q['http_status'][code]=q['http_status'].get(code,0)+1
 return entry
atomic(AREA/'launch.json',{'pid':os.getpid(),'at':time.time(),'read_only':True,'incremental_ledgers':True})
while True:
 rows=[];items=read(ROOT/'inventory.json')['cells']
 for item in items:
  cell=item['cell'];root=Path(item['root'])
  try:
   plan=plans.setdefault(cell,read(root/'plan.json'))if cell not in plans else plans[cell];row={'cell':cell,'harness':item['harness'],'planned':len(plan['jobs']),'active':0,'terminal':{},'requests':0,'complete_usage':0,'route_errors':0,'controller_exit':False,'heartbeat_age_seconds':None,'providers':{}}
   for p in(root/'controllers').glob('*/*/status.json'):
    v=read(p);row['active']+=v.get('active_local',0);row['heartbeat_age_seconds']=round(time.time()-v.get('at',0),1);row['stop_dispatch']=v.get('stop_dispatch');row['controller_error']=v.get('error_type');row['controller_exit']|=(p.parent/'exit.json').exists()
   for j in plan['jobs']:
    a=root/'jobs'/j['job_id']/'attempts/attempt_001';p=a/'result.json'
    if p.exists():v=read(p);row['terminal'][v['status']]=row['terminal'].get(v['status'],0)+1
    n=a/'runs'/f"attempt_{j['new_authorized_ordinal']:03d}"/'native'
    paths=list(n.glob('*/'+j['question_id']+'/workspace/metrics/inline-images-wire-dsh-v1.jsonl'))if j['harness']=='dsh'else[n/'metrics/transport-phases-v3.jsonl']
    for p in paths:
     v=wire(p)
     for k in('requests','complete_usage','route_errors'):row[k]+=v[k]
     for route,stats in v['providers'].items():
      target=row['providers'].setdefault(route,{'requests':0,'complete_usage':0,'errors':{},'http_status':{}})
      for k in('requests','complete_usage'):target[k]+=stats[k]
      for k in('errors','http_status'):
       for label,count in stats[k].items():target[k][label]=target[k].get(label,0)+count
   row['remaining_without_terminal']=row['planned']-sum(row['terminal'].values());rows.append(row)
  except Exception as e:rows.append({'cell':cell,'error_type':type(e).__name__})
 value={'at':time.time(),'rows':rows,'model_calls_by_monitor':0,'concurrency_per_cci':16,'max_new_attempts_per_slot':1};atomic(AREA/'latest.json',value)
 with(AREA/'history.jsonl').open('a')as f:f.write(json.dumps(value)+'\n')
 if all(r.get('remaining_without_terminal')==0 for r in rows):atomic(AREA/'exit.json',{'at':time.time(),'all_prediction_slots_terminal':True});break
 time.sleep(60)
