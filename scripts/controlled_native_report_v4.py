"""Field-wise raw accounting, including failed/unknown and calibration calls."""
import collections,json
from pathlib import Path
FIELDS=('prompt','cached','non_cache','output','total')
def lines(path):
    if not path.exists():return []
    result=[]
    for line in path.read_text().splitlines():
        try:result.append(json.loads(line))
        except ValueError:pass # Concurrent final line remains unknown until complete.
    return result

def values(row):
    u=row.get('raw_provider_usage') or {};p=u.get('prompt_tokens');c=(u.get('prompt_tokens_details') or {}).get('cached_tokens')
    if c is None:c=u.get('prompt_cache_hit_tokens')
    valid=lambda x:isinstance(x,int) and not isinstance(x,bool) and x>=0
    p=p if valid(p) else None;c=c if valid(c) else None
    return {'prompt':p,'cached':c,'non_cache':p-c if p is not None and c is not None and c<=p else None,
        'output':u.get('completion_tokens') if valid(u.get('completion_tokens')) else None,
        'total':u.get('total_tokens') if valid(u.get('total_tokens')) else None}

def aggregate(rows):
    vals=[values(r) for r in rows];missing={k:sum(v[k] is None for v in vals) for k in FIELDS}
    known={k:sum(v[k] for v in vals if v[k] is not None) for k in FIELDS}
    failures=sum(v['prompt']+v['output']!=v['total'] for v in vals if all(v[k] is not None for k in ('prompt','output','total')))
    failures+=sum(v['cached']>v['prompt'] for v in vals if v['cached'] is not None and v['prompt'] is not None)
    return {'calls':len(rows),'known_subtotals':known,'missing_by_field':missing,
        'complete_totals':{k:known[k] if rows and not missing[k] else None for k in FIELDS},'conservation_failures':failures,
        'cache_token_hit_rate':known['cached']/known['prompt'] if known['prompt'] and not missing['cached'] and not missing['prompt'] else None,
        'sdk_client_seconds_known':sum(r['client_stream_seconds'] for r in rows if isinstance(r.get('client_stream_seconds'),(int,float))) if any(isinstance(r.get('client_stream_seconds'),(int,float)) for r in rows) else None,
        'sdk_client_seconds_missing':sum(not isinstance(r.get('client_stream_seconds'),(int,float)) for r in rows),
        'latency_definition':'SDK client duration includes SDK retries and stream; not provider internal latency',
        'usd':None,'provider_image_tokens':None}

def accounting(root):
    rows=[];web=collections.Counter();purpose=collections.defaultdict(list)
    for kind in ('jobs','collectors'):
        for metrics in (Path(root)/kind).glob('**/metrics'):
            calls=lines(metrics/'calls.jsonl');ids={r.get('call_id') for r in calls}
            calls += [dict(s,raw_provider_usage=None,inflight_or_interrupted=True) for s in lines(metrics/'call-starts.jsonl') if s.get('call_id') not in ids]
            rows.extend(calls)
            for r in calls:purpose[r.get('purpose','unknown')].append(r)
            for r in lines(metrics/'web.jsonl'):
                cache=r.get('cache_hit');header=str(r.get('cache_header') or '').strip().lower()
                if cache is None and header in ('true','false'):cache=header=='true'
                web['hit' if cache is True else 'miss' if cache is False else 'unknown']+=1
    historical=Path(root)/'historical-prefix-acquisition.json'
    prior=json.loads(historical.read_text()) if historical.exists() else []
    return {'historical_shared_prefix_acquisition':aggregate([call for entry in prior for call in entry['calls']]),'all_attempts':aggregate(rows),'by_purpose':{k:aggregate(v) for k,v in purpose.items()},'web_cache':dict(web),
        'calibration_cache_warning':'Fitting warms prefix cache; cache rate is measured under calibration, not untreated production cache behavior',
        'shared_prefix_acquisition':'Historical pilot acquisition costs retained in source directories; new collectors included here; never counted three times'}
