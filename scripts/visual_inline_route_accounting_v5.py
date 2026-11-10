"""Read-only HTTP-attempt token accounting for inline four-route recovery.

Prediction transport records are authoritative whenever present. SDK records are
fallback only when an entire prediction attempt has no HTTP transport evidence;
there is no trustworthy cross-ledger call-ID join for guessing partial coverage.
"""
from collections import Counter,defaultdict
from datetime import datetime,timezone
import hashlib,json,math
from pathlib import Path
from monitor_bc_campaign_v3 import aggregate,accounting,_known_metric_path

VERSION='visual-inline-route-accounting-v5'
LEDGERS=('transport-phases-v3.jsonl','inline-images-wire-dsh-v1.jsonl')
ATTEMPT_EVENTS={'request_started','final_inline_request','transport_phase','response_headers',
 'first_response_bytes','stream_complete','route_returned','route_failed','route_http_error',
 'route_transport_error','global_authentication_rejected','request_body_sent',
 'body_stream_started','body_stream_exhausted','send_error','stream_error','stream_abandoned'}
FAILED_EVENTS={'route_failed','route_http_error','route_transport_error','global_authentication_rejected','send_error','stream_error','stream_abandoned'}

def _read(path):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return None

def _lines(path,issues):
    try:
        with path.open()as f:
            for number,line in enumerate(f,1):
                if not line.strip():continue
                try:
                    row=json.loads(line)
                    if not isinstance(row,dict):raise ValueError()
                    yield row
                except ValueError:issues.append({'kind':'partial_or_invalid_ledger_line','path':str(path),'line':number})
    except OSError:issues.append({'kind':'unreadable_ledger','path':str(path)})

def _number(value):return isinstance(value,(int,float))and not isinstance(value,bool)and math.isfinite(value)and value>=0

def metric_directories(attempt,harness):
    attempt=Path(attempt);known=_known_metric_path(attempt,harness)
    candidates=[attempt/'native/metrics']
    if known is not None:candidates.append(known)
    # Bounded DSH uses this fixed layout; avoid a walk through images/workspaces.
    if harness=='dsh':candidates.extend((attempt/'native/visual_native').glob('*/workspace/metrics'))
    return sorted({p for p in candidates if p.is_dir()})

def collect_transport(attempt,events,issues=None):
    """events are (ledger-path, row) pairs; return one row per actual HTTP ID."""
    issues=issues if issues is not None else []
    groups={};seen_events=set();waits=[];wait_seen=set();cycle_429=defaultdict(bool)
    for file,row in events:
        signature=hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if signature in seen_events:continue
        seen_events.add(signature)
        event=row.get('event');sdk=row.get('sdk_request_id')or 'unmapped'
        status=row.get('status_code',row.get('http_status'))
        if status==429:cycle_429[sdk]=True
        if event in('route_backoff','route_backoff_complete','rate_limit_backoff'):
            cycle=row.get('route_cycle_completed',row.get('cycle',row.get('request_id')))
            key=(sdk,event,cycle)
            if key not in wait_seen:
                wait_seen.add(key)
                seconds=row.get('client_wait_seconds')
                waits.append({'sdk_request_id':None if sdk=='unmapped'else sdk,'cycle':cycle,
                  'client_wait_seconds':seconds if _number(seconds)else None,
                  'planned_wait_seconds':row.get('planned_wait_seconds',row.get('planned_wait_ms',0)/1000),
                  'followed_cycle_with_429':cycle_429[sdk],
                  'provider_internal_latency_seconds':None})
                cycle_429[sdk]=False
        identity=row.get('request_id')or row.get('attempt_id')
        if not identity or event not in ATTEMPT_EVENTS:continue
        key=(str(Path(attempt).absolute()),str(identity))
        item=groups.setdefault(key,{'attempt_path':key[0],'request_id':key[1],'source':'http_transport',
             'routes':set(),'sdk_ids':set(),'usage_candidates':{},'event_counts':Counter(),
             'status_codes':set(),'errors':set(),'provider_codes':set(),'ledger_paths':set(),'start_observed':False})
        item['event_counts'][event]+=1;item['ledger_paths'].add(str(file))
        route=row.get('route')or row.get('actual_model')
        if route:item['routes'].add(route)
        if row.get('sdk_request_id'):item['sdk_ids'].add(row['sdk_request_id'])
        if event in('request_started','final_inline_request'):item['start_observed']=True
        if isinstance(status,int):item['status_codes'].add(status)
        for field,target in [('error_type','errors'),('provider_code','provider_codes')]:
            if row.get(field):item[target].add(row[field])
        raw=row.get('raw_provider_usage')
        if isinstance(raw,dict)and raw:
            fingerprint=json.dumps(raw,sort_keys=True,separators=(',',':'))
            item['usage_candidates'][fingerprint]=raw
    rows=[]
    for item in groups.values():
        candidates=list(item.pop('usage_candidates').values());routes=item.pop('routes')
        conflict=len(candidates)>1
        if conflict:issues.append({'kind':'conflicting_raw_usage_for_http_attempt','request_id':item['request_id'],'candidate_count':len(candidates)})
        if len(routes)>1:issues.append({'kind':'conflicting_actual_routes_for_http_id','request_id':item['request_id']})
        known=candidates[0]if len(candidates)==1 else None
        events_count=item.pop('event_counts');statuses=sorted(item.pop('status_codes'))
        failed=bool(set(events_count)&FAILED_EVENTS)or any(x>=400 for x in statuses)
        row={**item,'actual_route':next(iter(routes))if len(routes)==1 else None,
             'sdk_request_ids':sorted(item.pop('sdk_ids')),'ledger_paths':sorted(item['ledger_paths']),
             'errors':sorted(item['errors']),'provider_codes':sorted(item['provider_codes']),
             'events':dict(events_count),'status_codes':statuses,'failed':failed,
             'raw_provider_usage':known,'usage_known':known is not None,
             'usage_conflict':conflict,'_incomplete':conflict,
             'failed_cost_unknown':failed and known is None,'actual_usd':None}
        # Remove mutable internal set retained by dictionary expansion.
        row.pop('sdk_ids',None);rows.append(row)
    return rows,waits

def inspect_attempt(attempt,harness):
    attempt=Path(attempt);issues=[];directories=metric_directories(attempt,harness);events=[];ledger_files=[]
    for directory in directories:
        for name in LEDGERS:
            for path in (directory/name,directory/'wire'/name):
                if path.exists():
                    ledger_files.append(str(path));events.extend((str(path),r)for r in _lines(path,issues))
    rows,waits=collect_transport(attempt,events,issues)
    sdk_rows=[]
    for directory in directories:
        raw,_,_,_=accounting(directory,harness,issues);sdk_rows.extend(raw)
    source='http_transport'if rows else'sdk_fallback_no_transport'
    suppressed=len(sdk_rows)if rows else 0
    if not rows:
        for index,raw in enumerate(sdk_rows):
            rows.append({**raw,'attempt_path':str(attempt.absolute()),'request_id':str(raw.get('call_id',raw.get('request_id','missing_'+str(index)))),
                         'source':source,'actual_route':raw.get('request_model')or raw.get('model'),
                         'usage_known':isinstance(raw.get('raw_provider_usage'),dict)and not raw.get('_incomplete'),
                         'failed':bool(raw.get('error_type'))or bool(raw.get('_incomplete')),
                         'failed_cost_unknown':(bool(raw.get('error_type'))or bool(raw.get('_incomplete'))),
                         'actual_usd':None})
    summary={'attempt_path':str(attempt.absolute()),'source':source,'http_ledger_files':ledger_files,
             'observations':len(rows),'sdk_observations_suppressed':suppressed,
             'sdk_fallback_only_if_no_transport_attempts':True,'waits':waits,'issues':issues}
    return rows,summary

def resources(cells,out):
    out=Path(out);result={}
    for cell,data in cells.items():
        rows=[];judges=[];details=[];waits=[]
        for job in data['plan']['jobs']:
            directory=Path(data['root'])/'jobs'/job['job_id']/'attempts'
            for attempt in sorted(directory.glob('attempt_*')):
                if not attempt.is_dir():continue
                observed,info=inspect_attempt(attempt,job['harness']);rows.extend(observed);details.append(info);waits.extend(info['waits'])
            gd=out/'cells'/cell/'jobs'/job['job_id']
            if (gd/'request-started.json').exists():
                grade=_read(gd/'grade.json')or{}
                if grade.get('api_calls')!=0:
                    judges.append({'raw_provider_usage':grade.get('raw_provider_usage'),'_incomplete':not bool(grade)})
        by_route=defaultdict(list)
        for row in rows:by_route[row.get('actual_route')or'unknown'].append(row)
        result[cell]={'new_prediction_all_attempts':aggregate(rows),
           'prediction_by_actual_route':{route:aggregate(group)for route,group in sorted(by_route.items())},
           'judge':aggregate(judges),'private_judge_separate_from_prediction':True,
           'observed_attempts':len(details),'http_attempts':sum(r['source']=='http_transport'for r in rows),
           'sdk_fallback_observations':sum(r['source']!='http_transport'for r in rows),
           'unknown_usage_attempts':sum(not r.get('usage_known')for r in rows),
           'failed_attempts':sum(r.get('failed',False)for r in rows),
           'failed_attempts_with_unknown_cost':sum(r.get('failed_cost_unknown',False)for r in rows),
           'known_client_route_wait_seconds':sum(w['client_wait_seconds']for w in waits if _number(w['client_wait_seconds'])),
           'client_wait_missing_count':sum(not _number(w['client_wait_seconds'])for w in waits),
           'known_wait_seconds_after_cycles_with_429':sum(w['client_wait_seconds']for w in waits if w['followed_cycle_with_429']and _number(w['client_wait_seconds'])),
           'http_attempt_records':rows,'attempt_accounting':details,
           'actual_usd':None,'provider_api_latency_seconds':None}
    return {'at':datetime.now(timezone.utc).isoformat(),'version':VERSION,'cells':result,
       'scope':'New campaign predictions only, all attempted routes including failures. One observation per (prediction attempt path, HTTP request/attempt ID). SDK usage is suppressed when transport evidence exists; never added to the same prediction attempt. Judge usage remains separate.',
       'missing_policy':'Missing or conflicting raw usage remains unknown; no failed request is assumed free. Cached/non-cache splits require provider evidence. Dollar cost and provider-internal latency are not inferred.',
       'wait_policy':'Backoff is client waiting, not provider API latency; waiting after a mixed-failure cycle with HTTP429 is labeled separately, not attributed wholly to rate limiting.'}
