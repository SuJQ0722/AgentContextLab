#!/usr/bin/env python3
"""Offline, provenance-preserving profile of selected benchmark attempts.

No model calls. A successful agent SDK response is a decision, not an HTTP
attempt; compaction calls and failed calls are counted separately. Timings are
client observations, with right-censored calls retained separately.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import time

ROOT = Path(__file__).resolve().parents[1]


def number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def timestamp(x):
    if number(x):
        return x
    try:
        return datetime.fromisoformat(x.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError, TypeError):
        return {}


def lines(path, issues):
    if not path.exists():
        return []
    out = []
    try:
        with path.open() as stream:
            for i, line in enumerate(stream, 1):
                try:
                    out.append(json.loads(line))
                except ValueError:
                    issues.append({'file': str(path), 'line': i, 'error': 'invalid_json'})
    except OSError as exc:
        issues.append({'file': str(path), 'error': type(exc).__name__})
    return out


def describe(values):
    good = sorted(x for x in values if number(x))
    if not good:
        return {'n': 0, 'mean': None, 'median': None, 'p95': None, 'sum': None}
    def quantile(q):
        j = (len(good)-1)*q
        a = int(j)
        return good[a] + (good[min(a+1, len(good)-1)]-good[a])*(j-a)
    return dict(n=len(good), mean=statistics.mean(good), median=quantile(.5),
                p95=quantile(.95), sum=sum(good), min=good[0], max=good[-1])


def union_seconds(intervals, start=None, end=None):
    valid = []
    for a, b in intervals:
        if not (number(a) and number(b)):
            continue
        if number(start):
            a = max(a, start)
        if number(end):
            b = min(b, end)
        if b >= a:
            valid.append((a, b))
    total = 0
    last = None
    for a, b in sorted(valid):
        if last is None or a > last:
            total += b-a
        elif b > last:
            total += b-last
        last = b if last is None else max(last, b)
    return total


def error_call(row):
    return bool(row.get('error_type')) or (row.get('finish') or {}).get('kind') in ('error', 'failed')


def partition_intervals(groups, start, end):
    """Priority partition of observed intervals, with explicit unassigned wall time."""
    if not (number(start) and number(end) and end>=start):return {}
    prior=[];total=0;out={}
    for name, intervals in groups:
        prior.extend(intervals);new=union_seconds(prior,start,end)
        out[name]=max(0,new-total);total=new
    out['unassigned']=max(0,end-start-total)
    return out


def parse_transport(events, attempt_end):
    requests = {}
    backoff = []
    for e in events:
        ev = e.get('event', '')
        if ev in ('route_backoff', 'rate_limit_backoff', 'route_cycle_backoff_complete', 'route_backoff_complete'):
            if number(e.get('client_wait_seconds')):
                backoff.append(e['client_wait_seconds'])
        rid = e.get('request_id') or e.get('attempt_id')
        if not rid:
            continue
        r = requests.setdefault(rid, {'request_id': rid, 'phases': {}, 'events': [], 'errors': []})
        r['events'].append(ev)
        r['last_event'] = ev
        r['last_at'] = e.get('at_unix')
        r['route'] = e.get('route', e.get('actual_model', r.get('route')))
        elapsed = e.get('elapsed_seconds', e.get('client_seconds'))
        if ev in ('request_started', 'final_inline_request'):
            r.update(start=e.get('at_unix'), body_bytes=e.get('body_bytes'),
                     sdk_request_id=e.get('sdk_request_id'))
        if ev == 'transport_phase':
            phase = e.get('phase', '')
            r['last_phase'] = phase
            if phase.endswith(('.complete', '.failed')) and number(e.get('phase_seconds')):
                r['phases'][phase] = e['phase_seconds']
            if phase.endswith('send_request_body.complete'):
                r['body_sent_elapsed'] = elapsed
        if ev == 'request_body_sent':
            r['body_sent_elapsed'] = elapsed
        if ev == 'response_headers':
            r['headers_elapsed'] = elapsed
            r['status_code'] = e.get('status_code', e.get('http_status'))
        if ev == 'first_response_bytes':
            r['first_bytes_elapsed'] = elapsed
        if ev == 'stream_complete':
            r['completed'] = True
            # DSH request_wall_seconds starts before route rotation; client_seconds
            # starts at this physical HTTP request. Never charge prior routes twice.
            r['wall_seconds'] = elapsed
            r['sdk_route_cycle_wall_seconds'] = e.get('request_wall_seconds')
            r['stream_seconds'] = e.get('client_stream_seconds')
            if not number(r['stream_seconds']) and number(elapsed) and number(r.get('headers_elapsed')):
                r['stream_seconds'] = max(0, elapsed-r['headers_elapsed'])
        if ev in ('route_failed', 'route_transport_error', 'route_http_error', 'send_error', 'stream_error', 'request_error'):
            r['failed'] = True
            r['failed_seconds'] = elapsed
            r['errors'].append(e.get('error_type', e.get('failure_kind', 'HTTP_'+str(e.get('http_status',e.get('status_code','unknown'))) if ev=='route_http_error' else 'unknown')))
    for r in requests.values():
        phases = r['phases']
        for name, suffix in [('upload_seconds', 'send_request_body.complete'),
                             ('failed_upload_seconds', 'send_request_body.failed'),
                             ('response_header_wait_seconds', 'receive_response_headers.complete'),
                             ('failed_header_wait_seconds', 'receive_response_headers.failed')]:
            vals = [v for k, v in phases.items() if k.endswith(suffix)]
            r[name] = sum(vals) if vals else None
        if number(r.get('body_sent_elapsed')) and number(r.get('headers_elapsed')):
            r['after_upload_to_headers_seconds'] = max(0, r['headers_elapsed']-r['body_sent_elapsed'])
        r['censored'] = not (r.get('completed') or r.get('failed')) and number(r.get('start'))
        if r['censored'] and number(attempt_end):
            r['censored_elapsed_until_attempt_end'] = max(0, attempt_end-r['start'])
    return list(requests.values()), backoff


def dsh_session_profile(metric_dir, steps, attempt_end, issues):
    import zstandard
    files = list((metric_dir.parent.parent/'dsh-home/sessions').glob('*/*/session.v4.jsonl.zstd'))
    events=[]
    for file in files:
        try:
            with file.open('rb')as raw, zstandard.ZstdDecompressor().stream_reader(raw)as stream, io.TextIOWrapper(stream)as text:
                for line in text:
                    e=json.loads(line)
                    if e.get('type') in ('tool/call','tool/result','step/start','step/end'):
                        events.append(e)
        except (OSError,ValueError,zstandard.ZstdError)as exc:
            issues.append({'file':str(file),'error':type(exc).__name__})
    starts={};tool_intervals=[];fingerprints=[];prestep=[]
    observed_steps={(s.get('session_id'),s.get('step')):timestamp(s.get('timestamp')) for s in steps}
    # Session IDs are encoded in the parent directory. Step numbers in selected
    # tasks are unique; use metrics steps as a fallback after filtering main run.
    step_times={s.get('step'):timestamp(s.get('timestamp')) for s in steps}
    for e in sorted(events,key=lambda e:e['time']):
        d=e['data'];t=e['time']/1000
        if e['type']=='tool/call':
            starts[d['callId']]=t
            fingerprints.append(hashlib.sha256(json.dumps([d.get('name'),d.get('arguments')],sort_keys=True).encode()).hexdigest())
        elif e['type']=='tool/result':
            cid=(d.get('message')or{}).get('toolCallId',(d.get('message')or{}).get('tool_call_id'))
            if cid in starts:tool_intervals.append((starts.pop(cid),t))
        elif e['type']=='step/start':
            s=step_times.get(d.get('step'))
            if number(s) and 0<=t-s<7200:prestep.append((s,t))
    censored=[(s,attempt_end)for s in starts.values()if number(attempt_end)]
    return {'session_files':len(files),'tool_intervals':tool_intervals,'censored_tool_intervals':censored,
            'prestep_intervals':prestep,'tool_call_count':len(fingerprints),
            'exact_duplicate_tool_calls':len(fingerprints)-len(set(fingerprints))}


def profile(obs):
    row = {k: obs.get(k) for k in ('slot_id', 'benchmark', 'harness', 'method', 'question_id', 'repeat', 'status', 'score')}
    row['outcome'] = ('completed' if obs['status'].startswith('completed') else
                      'timeout' if obs['status']=='timeout_unresolved' else 'other')
    path = obs.get('selected_result_path') or obs.get('latest_terminal_result_path')
    row['result_path'] = path
    wrapper = read(path)
    if not wrapper.get('native_artifact_root'):
        row['missing_native_root'] = True
        return row
    root = Path(wrapper['native_artifact_root'])
    physical = read(root.parent/'result.json')
    if physical.get('native_artifact_root') != str(root):
        physical = wrapper
    row['native_root'] = str(root)
    row['physical_status'] = physical.get('status')
    row['e2e_seconds'] = physical.get('end_to_end_seconds')
    row['native_seconds'] = physical.get('native_end_to_end_seconds')
    start = timestamp(physical.get('started_at_unix_estimate', physical.get('started_at')))
    end = timestamp(physical.get('finished_at', physical.get('finished_at_unix')))
    if start is None and number(end) and number(row['e2e_seconds']):
        start = end-row['e2e_seconds']
    row.update(start_unix=start, end_unix=end,
               day=datetime.fromtimestamp(start).strftime('%Y-%m-%d') if number(start) else None)
    row['campaign'] = str(root).split('/outputs/campaigns/', 1)[-1].split('/jobs/',1)[0]
    row['protocol'] = {k: wrapper.get(k) for k in ('execution_version', 'one_hour_retry_version', 'one_pass_version') if wrapper.get(k)}
    dirs = [root/'metrics', root/'workspace/metrics'] + list(root.glob('*/*/workspace/metrics'))
    dirs = sorted(set(p for p in dirs if p.is_dir()))
    row['metric_dirs'] = [str(p) for p in dirs]
    issues = []
    logs = defaultdict(list)
    presence = Counter()
    names = ('calls.jsonl', 'call-starts.jsonl', 'web.jsonl', 'web-starts.jsonl', 'render.jsonl',
             'compression.jsonl', 'shared-policy.jsonl', 'steps.jsonl', 'hermes-tool-bridge.jsonl',
             'inline-images-wire-v1.jsonl')
    requests = []
    backoff = []
    for p in dirs:
        for name in names:
            if (p/name).exists():
                presence[name] += 1
                logs[name].extend(lines(p/name, issues))
        ledger = p/'transport-phases-v3.jsonl'
        if not ledger.exists():
            ledger = next((p/n for n in ('inline-images-wire-dsh-v1.jsonl','inline-images-wire-dsh-v3.jsonl','hosted-images-wire-dsh-v3.jsonl') if (p/n).exists()), ledger)
        if ledger.exists():
            presence['transport'] += 1
            req, waits = parse_transport(lines(ledger, issues), end)
            requests.extend(req)
            backoff.extend(waits)
        binding = read(p/'turn-limit-binding-v12.json')
        limit = binding.get('actual_agent_max_iterations', binding.get('actual_evaluation_maxSteps'))
        if limit is not None:
            row['turn_limit_measured'] = limit
    calls = list({r.get('call_id', str(i)): r for i,r in enumerate(logs['calls.jsonl'])}.values())
    starts = list({r.get('call_id', str(i)): r for i,r in enumerate(logs['call-starts.jsonl'])}.values())
    agent = [c for c in calls if c.get('purpose', 'agent')=='agent']
    success = [c for c in agent if not error_call(c)]
    failed = [c for c in agent if error_call(c)]
    compaction = [c for c in calls if c.get('purpose', 'agent')!='agent']
    done = {c.get('call_id') for c in calls}
    pending = [s for s in starts if s.get('call_id') not in done]
    intervals = [(timestamp(c.get('started_at')), timestamp(c.get('ended_at'))) for c in calls]
    pending_intervals = [(timestamp(s.get('started_at')), end) for s in pending]
    first = min((timestamp(c.get('started_at')) for c in starts if timestamp(c.get('started_at')) is not None), default=None)
    has_calls = bool(presence['calls.jsonl'] or presence['call-starts.jsonl'])
    row['decisions_observed'] = len(success) if has_calls else None
    row['tool_decisions_observed'] = sum((c.get('finish') or {}).get('kind') in ('tool_calls','tool-calls') for c in success) if has_calls else None
    row['agent_call_starts'] = sum(s.get('purpose', 'agent')=='agent' for s in starts) if presence['call-starts.jsonl'] else None
    row['agent_errors'] = len(failed) if has_calls else None
    row['agent_error_types'] = dict(Counter(c.get('error_type', (c.get('finish') or {}).get('kind')) for c in failed))
    row['pending_sdk_calls'] = len(pending) if presence['call-starts.jsonl'] else None
    row['compaction_calls'] = len(compaction) if has_calls else None
    row['agent_success_seconds'] = describe([c.get('client_stream_seconds') for c in success])
    row['agent_failure_seconds'] = describe([c.get('client_stream_seconds') for c in failed])
    row['compaction_call_seconds'] = describe([c.get('client_stream_seconds') for c in compaction])
    row['sdk_union_seconds'] = union_seconds(intervals, start, end) if has_calls else None
    row['sdk_plus_censored_union_seconds'] = union_seconds(intervals+pending_intervals, start, end) if has_calls else None
    row['pending_sdk_elapsed_until_attempt_end'] = union_seconds(pending_intervals, start, end) if has_calls else None
    row['initialization_to_first_sdk_seconds'] = max(0, first-start) if number(first) and number(start) else None
    if number(row['e2e_seconds']) and row['e2e_seconds']>0 and has_calls:
        row['sdk_observed_fraction'] = row['sdk_union_seconds']/row['e2e_seconds']
        row['sdk_plus_censored_fraction'] = row['sdk_plus_censored_union_seconds']/row['e2e_seconds']
    render = logs['render.jsonl']
    policies = logs['shared-policy.jsonl']
    compressions = logs['compression.jsonl']
    render_values = [r.get('render_seconds') for r in render] if presence['render.jsonl'] else [r.get('render_seconds') for r in policies]
    # No render event means no observed completed render, not a measured zero duration.
    row['render_seconds'] = describe(render_values)
    row['render_events'] = len(render) if presence['render.jsonl'] else sum((r.get('render_seconds') or 0)>0 for r in policies)
    row['compression_events'] = sum(c.get('count_delta',0) for c in compressions) if presence['compression.jsonl'] else sum(c.get('compression_count_delta',0) for c in policies)
    row['compression_seconds'] = describe([c.get('compression_seconds') for c in compressions])
    row['policy_ipc_seconds'] = describe([c.get('policy_ipc_seconds') for c in policies])
    render_intervals = []
    for r in render:
        t = timestamp(r.get('timestamp')); v=r.get('render_seconds')
        if number(t) and number(v):
            render_intervals.append((t-v,t))
    compression_intervals=[]
    for r in compressions:
        t=timestamp(r.get('timestamp'));v=r.get('compression_seconds')
        if number(t) and number(v):
            compression_intervals.append((t-v,t))
    render_stats=[r.get('stats') or {} for r in render]+[r.get('render_stats') or {} for r in policies]
    row['omitted_prefix_pages_max'] = max((r.get('omitted_prefix_pages',0) or 0 for r in render_stats),default=0)
    row['generated_pages_max'] = max((r.get('source_page_count',r.get('image_count',0)) or 0 for r in render_stats),default=0)
    web=logs['web.jsonl']; webstarts={r.get('transport_id'):r.get('started_unix') for r in logs['web-starts.jsonl']}
    web_intervals=[]
    for r in web:
        v=r.get('client_http_seconds');t=timestamp(r.get('timestamp'));ws=webstarts.get(r.get('transport_id'))
        if number(v) and number(t):web_intervals.append((t-v,t))
        elif number(v) and number(ws):web_intervals.append((ws,ws+v))
    row['web_http_seconds'] = describe([r.get('client_http_seconds') for r in web])
    row['web_requests'] = len(web)
    row['web_errors'] = sum(bool(r.get('error_type')) or (number(r.get('proxy_http_status')) and r['proxy_http_status']>=400) for r in web)
    row['web_interval_union_seconds'] = union_seconds(web_intervals,start,end) if web_intervals else None
    row['bridge_handler_seconds'] = describe([r.get('handler_seconds') for r in logs['hermes-tool-bridge.jsonl']])
    row['bridge_seconds'] = describe([r.get('bridge_seconds') for r in logs['hermes-tool-bridge.jsonl']])
    all_intervals=intervals+pending_intervals+web_intervals+render_intervals+compression_intervals
    row['observed_union_seconds'] = union_seconds(all_intervals,start,end) if has_calls else None
    row['unassigned_seconds'] = max(0,row['e2e_seconds']-row['observed_union_seconds']) if number(row['e2e_seconds']) and has_calls else None
    row['step_counter_max'] = max((r.get('step',0) for r in logs['steps.jsonl']),default=None)
    ti=[];cti=[];pi=[]
    if obs['harness']=='dsh' and dirs:
        session=dsh_session_profile(dirs[0],logs['steps.jsonl'],end,issues)
        ti=session.pop('tool_intervals');cti=session.pop('censored_tool_intervals');pi=session.pop('prestep_intervals')
        row['dsh_session']=session
        row['tool_wall_union_seconds']=union_seconds(ti,start,end) if session['session_files']else None
        row['tool_plus_censored_wall_union_seconds']=union_seconds(ti+cti,start,end) if session['session_files']else None
        row['prestep_union_seconds']=union_seconds(pi,start,end) if session['session_files']else None
        row['prestep_seconds']=describe([b-a for a,b in pi])
        row['dsh_tool_duration_seconds']=describe([b-a for a,b in ti])
        all_intervals+=ti+cti+pi
        row['observed_union_seconds']=union_seconds(all_intervals,start,end)
        row['unassigned_seconds']=max(0,row['e2e_seconds']-row['observed_union_seconds']) if number(row['e2e_seconds']) else None
    row['exclusive_wall_partition']=partition_intervals([
        ('sdk_completed',intervals),('sdk_inflight_to_termination',pending_intervals),
        ('web_http',web_intervals),('other_tool_execution',ti+cti),
        ('compression_excluding_sdk',compression_intervals+render_intervals),
        ('prestep_excluding_nested',pi),
        ('initialization',[(start,first)] if number(first) and number(start) else [])],start,end)
    for r in requests:
        containing=[c for c in calls if number(r.get('start')) and number(timestamp(c.get('started_at'))) and number(timestamp(c.get('ended_at'))) and timestamp(c['started_at'])-.1<=r['start']<=timestamp(c['ended_at'])+.1]
        r['purpose']=containing[0].get('purpose','agent') if len(containing)==1 else 'unknown'
    row['transport_present'] = bool(presence['transport'])
    row['http_requests'] = len(requests) if presence['transport'] else None
    row['http_failed_requests'] = sum(bool(r.get('failed')) for r in requests) if presence['transport'] else None
    row['http_censored_requests'] = sum(bool(r.get('censored')) for r in requests) if presence['transport'] else None
    row['http_error_types'] = dict(Counter(e for r in requests for e in r['errors']))
    row['http_last_phase'] = requests[-1].get('last_phase',requests[-1].get('last_event')) if requests else None
    row['backoff_measured_seconds'] = describe(backoff)
    fields=('wall_seconds','failed_seconds','upload_seconds','failed_upload_seconds',
            'body_sent_elapsed','headers_elapsed','after_upload_to_headers_seconds','stream_seconds',
            'failed_header_wait_seconds','body_bytes','censored_elapsed_until_attempt_end')
    row['http_metrics']={k:describe([r.get(k) for r in requests]) for k in fields}
    prep=logs['inline-images-wire-v1.jsonl']
    row['image_preparation_seconds']=describe([r.get('client_image_preparation_seconds') for r in prep])
    row['image_removed_events']=sum((r.get('selection') or {}).get('removed_image_count',0)>0 for r in prep)
    row['image_retention_versions']=dict(Counter(r.get('version','unknown') for r in prep))
    row['presence']=dict(presence)
    row['issues']=issues
    # Compact call records permit chronological, pre/post-compression and token analyses.
    row['calls']=[dict(call_id=c.get('call_id'),purpose=c.get('purpose','agent'),
        start=timestamp(c.get('started_at')),end=timestamp(c.get('ended_at')),
        seconds=c.get('client_stream_seconds'),error=error_call(c),error_type=c.get('error_type'),
        finish=(c.get('finish')or{}).get('kind'),
        input_tokens=(c.get('raw_provider_usage')or{}).get('prompt_tokens'),
        output_tokens=(c.get('raw_provider_usage')or{}).get('completion_tokens',(c.get('usage')or{}).get('outputTokens')),
        reasoning_tokens=((c.get('raw_provider_usage')or{}).get('completion_tokens_details')or{}).get('reasoning_tokens')) for c in calls]
    row['compression_end_times']=[timestamp(c.get('timestamp')) for c in compressions if c.get('count_delta',0)>0]
    row['http_details']=requests
    return row


def summarize(rows):
    groups=defaultdict(list)
    for r in rows:
        groups[(r['benchmark'],r['harness'],r['method'],r['outcome'])].append(r)
    out=[]
    scalar=('decisions_observed','tool_decisions_observed','agent_call_starts','agent_errors','compaction_calls',
            'e2e_seconds','sdk_union_seconds','sdk_plus_censored_union_seconds','sdk_observed_fraction',
            'sdk_plus_censored_fraction','pending_sdk_elapsed_until_attempt_end','initialization_to_first_sdk_seconds',
            'render_events','compression_events','web_requests','web_errors','web_interval_union_seconds',
            'unassigned_seconds','http_requests','http_failed_requests','http_censored_requests','image_removed_events',
            'tool_wall_union_seconds','tool_plus_censored_wall_union_seconds','prestep_union_seconds')
    nested=('agent_success_seconds','agent_failure_seconds','compaction_call_seconds','render_seconds','compression_seconds',
            'web_http_seconds','bridge_seconds','policy_ipc_seconds','image_preparation_seconds','backoff_measured_seconds')
    for key,rr in sorted(groups.items()):
        g=dict(zip(('benchmark','harness','method','outcome'),key));g['n']=len(rr)
        g['metrics']={k:describe([r.get(k) for r in rr]) for k in scalar}
        for k in nested:
            g['metrics'][k+'_per_episode']=describe([(r.get(k)or{}).get('sum') for r in rr])
            g['metrics'][k+'_episode_means']=describe([(r.get(k)or{}).get('mean') for r in rr])
        g['transport_episodes']=sum(r.get('transport_present',False) for r in rr)
        g['exclusive_wall_partition']={k:describe([r.get('exclusive_wall_partition',{}).get(k)for r in rr])for k in
            ('sdk_completed','sdk_inflight_to_termination','web_http','other_tool_execution','compression_excluding_sdk',
             'prestep_excluding_nested','initialization','unassigned')}
        g['http']={k:describe([q.get(k) for r in rr for q in r.get('http_details',[])]) for k in
            ('wall_seconds','failed_seconds','upload_seconds','failed_upload_seconds','body_sent_elapsed','headers_elapsed',
             'after_upload_to_headers_seconds','stream_seconds','failed_header_wait_seconds','body_bytes')}
        g['sdk_success_call_distribution']=describe([c.get('seconds') for r in rr for c in r.get('calls',[]) if c['purpose']=='agent'and not c['error']])
        g['http_errors']=dict(sum((Counter(r.get('http_error_types',{}))for r in rr),Counter()))
        g['sdk_errors']=dict(sum((Counter(r.get('agent_error_types',{}))for r in rr),Counter()))
        g['zero_observed_decisions']=sum(r.get('decisions_observed')==0 for r in rr)
        g['zero_observed_compressions']=sum(r.get('compression_events')==0 for r in rr)
        g['turn_limit_500_episodes']=sum(r.get('turn_limit_measured')==500 for r in rr)
        g['campaigns']=dict(Counter(r.get('campaign','missing')for r in rr))
        out.append(g)
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=ROOT/'outputs/analysis/stage-profile-20261114')
    p.add_argument('--workers',type=int,default=8)
    p.add_argument('--limit',type=int)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/'outputs/reports/once24h-v15/latest.json',ROOT/'outputs/reports/mmbc-timeout-overlay-v18/latest.json']
    snapshots=[json.loads(p.read_text()) for p in sources]
    rows=[r for r in snapshots[0]['observations'] if not(r['benchmark']=='mmbc100'and r['method']=='visual')]+snapshots[1]['observations']
    if a.limit:rows=rows[:a.limit]
    source_records=[]
    for p,d in zip(sources,snapshots):
        raw=json.dumps(d,ensure_ascii=False,sort_keys=True).encode();dest=a.out/(p.parent.name+'-snapshot.json');dest.write_bytes(raw)
        source_records.append(dict(source=str(p),snapshot=str(dest),at=d.get('at'),sha256=hashlib.sha256(raw).hexdigest()))
    begin=time.time();profiled=[]
    with ThreadPoolExecutor(max_workers=a.workers)as pool, (a.out/'episodes.jsonl').open('w')as f:
        for i,r in enumerate(pool.map(profile,rows),1):
            profiled.append(r);f.write(json.dumps(r,ensure_ascii=False)+'\n')
            if i%300==0:print(json.dumps(dict(processed=i,total=len(rows),elapsed=round(time.time()-begin,1))),flush=True)
    report=dict(version='offline-selected-attempt-stage-profile-v1',sources=source_records,model_calls=0,
        selection='Earliest retained completion, otherwise latest terminal physical attempt. Not cumulative historical retry spend.',
        definitions={'decisions':'Successfully returned purpose=agent SDK responses; not HTTP attempts, not tool invocations; terminated in-flight response excluded.',
          'censoring':'Timeout decision count is observed progress, not the number of rounds required for eventual completion.',
          'sdk':'Client SDK wrapper including serialization/archive, route retries and backoff; not provider inference latency.',
          'unassigned':'E2E minus union of observed SDK, censored SDK-to-termination intervals, web HTTP and compression/render intervals. Includes uninstrumented tools, archive, local work and cleanup.',
          'missing':'Absent timing remains null. No completed compression event does not exclude an unfinished compression.',
          'cohorts':'Historical completion and latest failures use different dates/protocols. Aggregate comparisons are descriptive; use same-question, same-budget sensitivity analysis.'},
        episodes=len(profiled),groups=summarize(profiled),elapsed_seconds=time.time()-begin,
        issues=[dict(slot_id=r['slot_id'],issues=r['issues'])for r in profiled if r.get('issues')])
    (a.out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(episodes=len(profiled),groups=len(report['groups']),issues=len(report['issues']),output=str(a.out),elapsed=round(time.time()-begin,1))),flush=True)


if __name__=='__main__':main()
