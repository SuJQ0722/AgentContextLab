#!/usr/bin/env python3
"""Read-only client latency accounting for independent inline recovery cells."""
import argparse,collections,json,math,statistics,time
from datetime import datetime
from pathlib import Path
from lab import ROOT
DEFAULT=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v5'

def numeric(x):return isinstance(x,(int,float))and not isinstance(x,bool)and math.isfinite(x)and x>=0

def summary(values,missing=0):
 good=sorted(v for v in values if numeric(v));missing+=sum(not numeric(v)for v in values)
 def percentile(q):
  if not good:return None
  position=(len(good)-1)*q;i=int(position);j=min(i+1,len(good)-1)
  return good[i]+(good[j]-good[i])*(position-i)
 return {'observed_count':len(good),'missing_count':missing,'known_subtotal_seconds':sum(good)if good else None,'mean_seconds':statistics.mean(good)if good else None,'median_seconds':percentile(.5),'p95_seconds':percentile(.95)}

def read(path,issues):
 try:return json.loads(path.read_text())
 except (OSError,ValueError)as exc:issues.append({'file':str(path),'error_type':type(exc).__name__});return {}

def rows(path,issues):
 try:lines=path.read_text().splitlines()
 except OSError as exc:issues.append({'file':str(path),'error_type':type(exc).__name__});return
 for number,line in enumerate(lines,1):
  try:yield json.loads(line)
  except ValueError:issues.append({'file':str(path),'line':number,'error_type':'partial_or_invalid_json'})

def blank():return {'values':collections.defaultdict(list),'request_ids':set(),'status_codes':collections.Counter(),'event_counts':collections.Counter(),'attempts':set(),'request_details':{}}

def cell_report(cell):
 issues=[];attempts=[];byroute=collections.defaultdict(blank);phase_files=0;render_missing=0;renders=[];sdk=[];sdk_missing=0
 for attempt in sorted((cell/'jobs').glob('**/attempts/attempt_*')):
  if not attempt.is_dir():continue
  result=read(attempt/'result.json',issues)if(attempt/'result.json').exists()else{}
  record={'attempt':str(attempt),'status':result.get('status','unfinished'),'end_to_end_seconds':result.get('end_to_end_seconds'),'native_end_to_end_seconds':result.get('native_end_to_end_seconds'),'queue_wait_before_dispatch_seconds':None,'dispatch_to_worker_start_seconds':None}
  if (attempt/'controller-dispatched.json').exists()and(attempt/'worker-started.json').exists():
   dispatch=read(attempt/'controller-dispatched.json',issues);worker=read(attempt/'worker-started.json',issues)
   try:
    value=datetime.fromisoformat(worker['started_at']).timestamp()-dispatch['at']
    if numeric(value):record['dispatch_to_worker_start_seconds']=value
   except (KeyError,ValueError,TypeError):pass
  attempts.append(record)
  metrics={p.parent for p in attempt.glob('**/metrics/*.jsonl')}
  render_values=[];sdk_files=0
  for directory in sorted(metrics):
   if (directory/'render.jsonl').exists():render_values.extend(r.get('render_seconds')for r in rows(directory/'render.jsonl',issues))
   elif(directory/'shared-policy.jsonl').exists():render_values.extend(r.get('render_seconds')for r in rows(directory/'shared-policy.jsonl',issues))
   elif(directory/'compression.jsonl').exists():render_values.extend(r.get('render_seconds')for r in rows(directory/'compression.jsonl',issues)if 'render_seconds'in r)
   calls=directory/'calls.jsonl'
   if calls.exists():
    sdk_files+=1
    for r in rows(calls,issues):
     value=r.get('client_stream_seconds');sdk.append(value)
   candidates=[directory/'transport-phases-v3.jsonl',directory/'inline-images-wire-dsh-v1.jsonl',directory/'inline-images-wire-dsh-v3.jsonl',directory/'hosted-images-wire-dsh-v3.jsonl',directory/'hosted-images-wire-dsh-v1.jsonl']
   for ledger in candidates:
    if not ledger.exists():continue
    phase_files+=1;request_routes={};request_info=collections.defaultdict(dict)
    events=list(rows(ledger,issues))
    for r in events:
     rid=r.get('request_id')or r.get('attempt_id');route=r.get('route')or r.get('actual_model')
     if rid and route:request_routes[rid]=route
    for r in events:
     event=r.get('event','unknown');rid=r.get('request_id')or r.get('attempt_id');route=r.get('route')or r.get('actual_model')or request_routes.get(rid)or ('shared_route_cycle_wait'if event.startswith('route_cycle_backoff')or event=='route_backoff_complete'else'missing_actual_route');group=byroute[route];group['attempts'].add(str(attempt));group['event_counts'][event]+=1
     if rid:
      key=(str(ledger),rid);group['request_ids'].add(key)
      detail=group['request_details'].setdefault(key,{'attempt_id':str(attempt),'request_id':rid,'sdk_request_id':r.get('sdk_request_id'),'route':route,'ledger':str(ledger),'events':[]})
      if r.get('sdk_request_id'):detail['sdk_request_id']=r['sdk_request_id']
      detail['events'].append({k:r[k]for k in ('event','phase','elapsed_seconds','phase_seconds','client_seconds','client_stream_seconds','client_wait_seconds','status_code','http_status')if k in r})
     if isinstance(r.get('status_code',r.get('http_status')),int):group['status_codes'][str(r.get('status_code',r.get('http_status')))]+=1
     value=r.get('elapsed_seconds',r.get('client_seconds'))
     if event=='transport_phase'and str(r.get('phase','')).endswith('send_request_body.complete'):group['values']['request_upload'].append(r.get('phase_seconds'))
     if event in ('upload_complete','request_upload_complete'):group['values']['request_upload'].append(r.get('client_upload_seconds',r.get('client_seconds')))
     if event=='request_body_sent':
      if rid:request_info[rid].update(body_sent_elapsed=value,body_sent_route=route)
      else:issues.append({'file':str(ledger),'error_type':'body_sent_missing_request_identity'})
     if event=='body_stream_exhausted':group['values']['bytes_offered_to_transport_elapsed'].append(value)
     if event=='response_headers':group['values']['time_to_response_headers'].append(value);request_info[rid]['headers']=value
     if event=='first_response_bytes':group['values']['time_to_first_response_bytes'].append(value)
     if event=='stream_complete':
      group['values']['http_request_wall'].append(value)
      stream=r.get('client_stream_seconds')
      if rid and not numeric(stream)and numeric(value)and numeric(request_info[rid].get('headers')):
       stream=value-request_info[rid]['headers']
      group['values']['response_stream'].append(stream)
     if event in ('rate_limit_backoff','route_backoff','route_cycle_backoff_complete','route_backoff_complete'):group['values']['quota_backoff_wait'].append(r.get('client_wait_seconds'))
     if event=='send_error':group['values']['failed_send_elapsed'].append(value)
    for rid,info in request_info.items():
     if 'body_sent_elapsed'in info:byroute[info['body_sent_route']]['values']['time_to_request_body_sent'].append(info['body_sent_elapsed'])
  if not sdk_files:sdk_missing+=1
  if not render_values:render_missing+=1
  renders.extend(render_values)
  record['render_metric_records']=len(render_values);record['render_known_subtotal_seconds']=sum(x for x in render_values if numeric(x))if any(numeric(x)for x in render_values)else None
 routes={}
 for route,g in sorted(byroute.items()):
  fields=('request_upload','time_to_request_body_sent','bytes_offered_to_transport_elapsed','time_to_response_headers','time_to_first_response_bytes','response_stream','http_request_wall','quota_backoff_wait','failed_send_elapsed')
  routes[route]={'http_request_ids':len(g['request_ids']),'attempts_with_events':len(g['attempts']),'status_events':dict(g['status_codes']),'event_counts':dict(g['event_counts']),'client_metrics':{key:summary(g['values'][key])for key in fields},'provider_internal_latency_seconds':None,'http_request_details':list(g['request_details'].values())}
 return {'cell':cell.name,'attempts':len(attempts),'terminal_states':dict(collections.Counter(x['status']for x in attempts)),
  'queue_wait_before_dispatch':summary([x['queue_wait_before_dispatch_seconds']for x in attempts]),'dispatch_to_worker_start':summary([x['dispatch_to_worker_start_seconds']for x in attempts]),'trial_end_to_end':summary([x['end_to_end_seconds']for x in attempts]),'native_end_to_end':summary([x['native_end_to_end_seconds']for x in attempts]),
  'trial_end_to_end_by_status':{status:summary([x['end_to_end_seconds']for x in attempts if x['status']==status])for status in sorted({x['status']for x in attempts})},
  'native_render':{**summary(renders),'attempts_without_render_records':render_missing},'sdk_client_logged_duration':{**summary(sdk),'attempts_without_sdk_logs':sdk_missing},'transport_ledgers_present':phase_files,
  'provider_internal_latency_seconds':None,'per_actual_route':routes,'attempt_details':attempts,'issues':issues}

def diagnostic():
 path=ROOT/'outputs/preflight/inline-chunked-transport-v1/result.json'
 if not path.exists():return None
 issues=[];row=read(path,issues);prepared=read(path.with_name('prepared.json'),issues)
 return {'source':str(path),'representative_of_benchmark_latency':False,'status':row.get('status'),'image_count':prepared.get('image_count'),'body_bytes':row.get('body_bytes'),'actual_model_http_attempts':row.get('actual_model_http_attempts'),'client_upload_seconds':row.get('request_body_phase_seconds'),'client_wall_seconds':row.get('client_wall_seconds'),'provider_internal_latency_seconds':None}


def report(root):
 root=Path(root);cells=[cell_report(p)for p in sorted((root/'cells').iterdir())if(p/'plan.json').exists()]if(root/'cells').exists()else[]
 return {'version':'visual-inline-client-latency-report-v5','at':time.time(),'root':str(root),'read_only':True,'model_calls':0,'population_scope':{'selection':'V5 conditional retry population: prior execution failures/timeouts or not-yet-started trials only; all prior completed trials retained without rerun.','representative_of_full_100x3_cohort':False,'directly_comparable_to_old_text_baseline_mean':False,'cross_version_pooling':False,'measurement_scope':'New-version retried trials only; this is not an all-method, full-cohort latency rerun.'},
  'definitions':{'non_additivity':'Render, compression, SDK and E2E durations can overlap or contain one another; do not sum them as independent latency components.','queue_wait_before_dispatch':'Missing: no explicit queue-enqueue timestamp. Worker startup from dispatch is reported separately and is not queue wait.','route_request_identity':'Grouped by attempt path + ledger + actual route + HTTP request_id. Multiple route attempts for one sdk_request_id remain separate.','trial_end_to_end':'Measured trial runtime, includes worker overhead; unfinished trials remain missing.','request_upload':'Client send-request-body phase duration when instrumented; not inferred from headers.','time_to_request_body_sent':'DSH undici request:bodySent elapsed from HTTP-attempt start, includes connection/setup; kept separate from Python body-only phase.','bytes_offered_to_transport_elapsed':'Generator exhaustion; not socket-upload completion proof and not counted as upload latency.','time_to_response_headers':'Client elapsed from HTTP attempt start; includes upload and network.','response_stream':'Client header-to-stream-completion duration or explicit instrumented stream duration.','quota_backoff_wait':'Measured client wait; never attributed to provider inference latency.','native_render':'Native render events; absent instrumentation stays missing.','provider_internal_latency':'Unmeasured; always null.','known_subtotal':'Partial sum of observed values; not a complete total when instrumentation is absent.','per_actual_route':'Only explicit actual route instrumentation; missing route is not guessed from initial config.'},'cells':cells,'separate_nonbenchmark_diagnostic':diagnostic()}

def markdown(value):
 lines=['# Client latency — inline recovery','','All timings are client measurements in seconds. Missing instrumentation is shown as `missing`; provider inference latency is unmeasured. Render/compression/SDK/E2E measurements may overlap and must not be summed as independent components. Queue wait before dispatch is uninstrumented and separate from measured API quota backoff. V5 covers only previously failed or unstarted trials; old completed trials were not rerun. These conditional-sample means do not represent the complete 100×3 cohort and cannot be directly compared with historical text-baseline means. Old and new versions are not pooled.','','| Cell | Attempts | Completed / failed / unfinished | Trial mean | Trial p95 | Queue wait | Worker startup | Render observed subtotal | Transport ledgers |','|---|---:|---|---:|---:|---:|---:|---:|---:|']
 def fmt(x):return f'{x:.3f}'if numeric(x)else'missing'
 for c in value['cells']:
  s=c['terminal_states'];lines.append(f"| {c['cell']} | {c['attempts']} | {s.get('completed',0)} / {s.get('failed',0)} / {s.get('unfinished',0)} | {fmt(c['trial_end_to_end']['mean_seconds'])} | {fmt(c['trial_end_to_end']['p95_seconds'])} | {fmt(c['queue_wait_before_dispatch']['mean_seconds'])} | {fmt(c['dispatch_to_worker_start']['mean_seconds'])} | {fmt(c['native_render']['known_subtotal_seconds'])} | {c['transport_ledgers_present']} |")
 lines+=['','| Cell / actual route | Upload mean | Headers mean | Stream mean | 429 wait observed subtotal |','|---|---:|---:|---:|---:|']
 for c in value['cells']:
  for route,r in c['per_actual_route'].items():
   m=r['client_metrics'];lines.append(f"| {c['cell']} / {route} | {fmt(m['request_upload']['mean_seconds'])} | {fmt(m['time_to_response_headers']['mean_seconds'])} | {fmt(m['response_stream']['mean_seconds'])} | {fmt(m['quota_backoff_wait']['known_subtotal_seconds'])} |")
 return '\n'.join(lines)+'\n'

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT);p.add_argument('--out',type=Path,required=True);a=p.parse_args();value=report(a.root);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.with_suffix('.json').write_text(json.dumps(value,indent=2)+'\n');a.out.with_suffix('.md').write_text(markdown(value));print(json.dumps({'cells':len(value['cells']),'report':str(a.out),'model_calls':0}))
if __name__=='__main__':main()
