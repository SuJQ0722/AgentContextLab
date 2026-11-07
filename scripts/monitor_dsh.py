#!/usr/bin/env python3
"""Continuously audit persisted DSH usage and export reviewer-facing tables (no API calls)."""
import argparse
import collections
import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import time


def read_lines(path):
    if not path.exists():
        return []
    result = []
    text = path.read_text()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        try:
            result.append(json.loads(line))
        except ValueError:
            # Only a final partial line can be a concurrent write. Never hide
            # a corrupt completed record from statistical validation.
            if i == len(lines)-1 and not text.endswith('\n'):
                continue
            raise ValueError(f'Invalid completed JSON record: {path}:{i+1}')
    return result


def atomic(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(value)
    temporary.replace(path)


def normalized_usage(call):
    u = call.get('usage')
    # pi-ai may emit a zero-initialized usage object on transport failure even
    # though the provider returned no counters. Keep the raw log, mark unknown.
    if (call.get('finish') or {}).get('kind') in (None, 'error') and u and not u.get('totalTokens'):
        u = None
    if not u or any(u.get(k) is None for k in ('inputTokens', 'outputTokens', 'totalTokens')):
        return dict(cached_input=None, non_cache_input=None, cache_write_input=None,
                    output=None, total_input=None, total_tokens=None, cache_hit_rate=None, conserved=None)
    # Pinned llm-pi-ai mapUsage omits *zero* cache fields. This convention is
    # specific to that adapter; it is NOT applied to an absent usage object.
    cached, writes = u.get('cacheReadTokens', 0), u.get('cacheWriteTokens', 0)
    uncached, output = u['inputTokens'], u['outputTokens']
    total_input = cached + writes + uncached
    return dict(cached_input=cached, non_cache_input=uncached, cache_write_input=writes,
                output=output, total_input=total_input, total_tokens=u['totalTokens'],
                cache_hit_rate=cached / total_input if total_input else None,
                conserved=total_input + output == u['totalTokens'])


def sum_usage(calls):
    values = [normalized_usage(c) for c in calls]
    observed = [v for v in values if v['total_tokens'] is not None]
    totals = {key: sum(v[key] for v in observed) if observed else None for key in
              ('cached_input', 'non_cache_input', 'cache_write_input', 'output', 'total_input', 'total_tokens')}
    totals['cache_hit_rate'] = totals['cached_input'] / totals['total_input'] if totals['total_input'] else None
    totals.update(calls=len(calls), calls_with_usage=len(observed), missing_usage=len(calls)-len(observed),
                  conservation_failures=sum(v['conserved'] is False for v in values))
    return totals


def judge_call(record):
    u=record.get('usage')
    if not u:return {'usage':None}
    cached=(u.get('prompt_tokens_details') or {}).get('cached_tokens')
    if cached is None:return {'usage':None}
    return {'usage':{'inputTokens':u['prompt_tokens']-cached,'cacheReadTokens':cached,
                     'outputTokens':u['completion_tokens'],'totalTokens':u['total_tokens']}}


def write_csv(path, rows):
    stream = io.StringIO()
    if rows:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    atomic(path, stream.getvalue())


def alive(pid):
    try:
        stat = Path(f'/proc/{pid}/stat').read_text()
        return stat.split(') ', 1)[1].split()[0] != 'Z'
    except (OSError, IndexError):
        return False


def snapshot(root):
    output = root / 'monitor'
    output.mkdir(exist_ok=True)
    all_calls, grading_calls, call_rows, rows, issues = [], [], [], [], []
    groups = collections.defaultdict(list)
    for manifest_file in sorted(root.glob('*/*/manifest.json')):
        run = manifest_file.parent
        m = json.loads(manifest_file.read_text())
        metrics = run / 'workspace/metrics'
        calls = read_lines(metrics / 'calls.jsonl')
        all_calls.extend(calls); groups[m['strategy']].extend(calls)
        for i, call in enumerate(calls):
            call_rows.append(dict(question_id=m['question_id'], strategy=m['strategy'], call_index=i,
                call_id=call.get('call_id'), purpose=call.get('purpose'), started_at=call.get('started_at'),
                ended_at=call.get('ended_at'), **normalized_usage(call),
                client_stream_seconds=call.get('client_stream_seconds'),
                first_text_delta_seconds=call.get('first_text_delta_seconds'),
                finish=(call.get('finish') or {}).get('kind')))
        usage = sum_usage(calls)
        result_path = run / 'result.json'
        result = json.loads(result_path.read_text()) if result_path.exists() else {}
        judge_path=run/'judge.json'
        judge=json.loads(judge_path.read_text()) if judge_path.exists() else {}
        if judge.get('api_calls'):
            grading_calls.append(judge_call(judge))
        if judge and judge.get('status')!='scored':
            issues.append({'kind':'judge_failure','run':str(run),'status':judge.get('status')})
        reason = ((result.get('final') or {}).get('reason') or {}).get('kind')
        webs = read_lines(metrics / 'web.jsonl')
        searches = [w for w in webs if w['kind'] == 'search']
        hits = sum(str(w.get('cache_header')).lower() == 'true' for w in searches)
        misses = sum(str(w.get('cache_header')).lower() == 'false' for w in searches)
        compressions = read_lines(metrics / 'compression.jsonl')
        renders = read_lines(metrics / 'render.jsonl')
        policies = read_lines(metrics / 'policy.jsonl')
        if m.get('policy_verification_required') and calls and not any(
                p.get('verified') and p.get('strategy') == m['strategy'] for p in policies):
            issues.append({'kind':'research_policy_not_verified', 'run':str(run)})
        if m['strategy'] == 'visual_native' and any(c.get('purpose') == 'compaction' for c in calls):
            issues.append({'kind':'unexpected_text_compaction_in_visual_policy', 'run':str(run)})
        if any(not c.get('valid') for c in compressions):
            issues.append({'kind':'invalid_post_compression_budget', 'run':str(run)})
        row = dict(question_id=m['question_id'], strategy=m['strategy'], model=m['model'],
            status=result.get('status', 'running'), finish_reason=reason,
            failure_category=result.get('failure_category'), **usage,
            api_client_seconds=sum(c.get('client_stream_seconds', 0) for c in calls) if calls else None,
            end_to_end_seconds=result.get('end_to_end_seconds'),
            logged_compression_count=len(compressions), compression_triggered=bool(compressions),
            policy_verified=any(p.get('verified') and p.get('strategy') == m['strategy'] for p in policies),
            render_count=len(renders), render_seconds=sum(r['render_seconds'] for r in renders) if renders else None,
            serper_requests=len(searches), serper_cache_hits=hits, serper_cache_misses=misses,
            serper_cache_unknown=len(searches)-hits-misses,
            serper_cache_hit_rate=hits/(hits+misses) if hits+misses else None,
            web_errors=sum(not w['success'] for w in webs), score=judge.get('score',result.get('score')),
            grading_status=judge.get('status','pending'),
            billed_usd=None, estimated_usd=None)
        rows.append(row)
        if usage['conservation_failures']:
            issues.append({'kind':'token_conservation', 'run':str(run), 'count':usage['conservation_failures']})
        if usage['missing_usage']:
            issues.append({'kind':'missing_usage', 'run':str(run), 'count':usage['missing_usage']})
        for call in calls:
            if (call.get('finish') or {}).get('kind') == 'error':
                issues.append({'kind':'llm_call_error', 'run':str(run), 'purpose':call.get('purpose'),
                               'call_id':call.get('call_id'), 'code':((call['finish'].get('failure') or {}).get('code'))})
        if result and reason not in ('completed', 'max-tokens') and result.get('failure_category') not in ('step_limit','timeout'):
            issues.append({'kind':'execution_failure', 'run':str(run), 'reason':reason})
        if not result and (run / 'running.json').exists():
            active = json.loads((run / 'running.json').read_text())
            latest = max((p.stat().st_mtime for p in metrics.glob('*.jsonl')), default=manifest_file.stat().st_mtime)
            if not alive(active['pid']):
                issues.append({'kind':'worker_disappeared', 'run':str(run)})
            elif time.time()-latest > min(active['timeout_seconds']+60, 300):
                issues.append({'kind':'no_metric_activity_5min', 'run':str(run)})
        if result:
            # Hermes-compatible aggregate keys; raw native trajectory remains authoritative.
            export = dict(question_id=m['question_id'], model=m['model'], strategy=m['strategy'],
                status=result['status'], session_id=(result.get('final') or {}).get('sessionId'),
                model_response=(result.get('final') or {}).get('text'), duration_seconds=result['end_to_end_seconds'],
                score=row['score'], judge_path=str(judge_path) if judge else None,
                token_usage={'input_tokens':usage['non_cache_input'], 'cache_read_tokens':usage['cached_input'],
                    'cache_write_tokens':usage['cache_write_input'], 'output_tokens':usage['output'],
                    'total_tokens':usage['total_tokens']},
                usage_quality='DSH normalized provider counters; includes auxiliary calls; not an invoice',
                compression_count_logged=len(compressions),
                native_session_files=[str(p) for p in (run/'dsh-home/sessions').rglob('session.v4.jsonl.zstd')],
                trajectory_events_path=str(run/'stdout.jsonl'), manifest_path=str(manifest_file))
            atomic(run / 'conv.json', json.dumps(export, indent=2))
    campaign = json.loads((root/'campaign.json').read_text())
    campaign_alive = alive(campaign['pid'])
    ids = [c['call_id'] for c in all_calls if c.get('call_id')]
    if len(ids) != len(set(ids)):
        issues.append({'kind':'duplicate_call_ids','duplicate_count':len(ids)-len(set(ids))})
    finished = sum(r['status'] != 'running' for r in rows)
    if not campaign_alive and finished < campaign['planned_runs']:
        issues.append({'kind':'campaign_stopped_early', 'finished':finished})
    status = dict(updated_at=datetime.now(timezone.utc).isoformat(), monitor_pid=os.getpid(),
        campaign_pid=campaign['pid'], campaign_alive=campaign_alive, planned_runs=campaign['planned_runs'],
        started_runs=len(rows), finished_runs=finished,
        completed_runs=sum(r['status']=='completed' for r in rows),
        output_limited_runs=sum(r['finish_reason']=='max-tokens' for r in rows),
        timed_out_runs=sum(r['status']=='timeout' for r in rows),
        step_limited_runs=sum(r['failure_category']=='step_limit' for r in rows),
        totals=sum_usage(all_calls), by_strategy={s:sum_usage(c) for s,c in groups.items()},
        grading_totals=sum_usage(grading_calls), totals_including_grading=sum_usage(all_calls+grading_calls),
        scores_by_strategy={s:{'judged':sum(r['score'] is not None for r in rows if r['strategy']==s),
            'accuracy_on_judged':(sum(r['score'] for r in rows if r['strategy']==s and r['score'] is not None)/
                sum(r['score'] is not None for r in rows if r['strategy']==s)) if any(r['score'] is not None for r in rows if r['strategy']==s) else None}
            for s in groups},
        by_purpose={p:sum_usage([c for c in all_calls if c.get('purpose')==p]) for p in sorted({c.get('purpose','agent') for c in all_calls})},
        issues=issues, accuracy=None,
        limitations=['Unjudged executions are not accuracy measurements.',
          'Stream timing includes adapter retries; not provider-internal latency.',
          'Cache counters use pinned pi-ai zero-omission convention; missing usage stays missing.',
          'Reasoning is included in output; raw provider request IDs and invoices unavailable.',
          'Logged compression counts report observed events, not inferred from strategy names.'])
    prior_path=root/'prior_invalid_campaigns.json'
    prior=json.loads(prior_path.read_text()) if prior_path.exists() else []
    status['prior_invalid_campaigns']=prior
    overhead=sum(p['tokens_observed']['total_tokens'] or 0 for p in prior)
    status['invalid_configuration_tokens_observed']=overhead
    status['all_campaigns_tokens_observed']=(status['totals_including_grading']['total_tokens'] or 0)+overhead
    status['compression_by_strategy']={s:{'events':sum(r['logged_compression_count'] for r in rows if r['strategy']==s),
        'runs_triggered':sum(r['compression_triggered'] for r in rows if r['strategy']==s),
        'renders':sum(r['render_count'] for r in rows if r['strategy']==s)} for s in groups}
    write_csv(output/'calls.csv', call_rows); write_csv(output/'records.csv', rows)
    atomic(output/'status.json', json.dumps(status, indent=2))
    return status


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--watch',action='store_true')
    p.add_argument('--interval',type=int,default=30)
    args=p.parse_args()
    if args.interval < 5: p.error('interval must be at least 5 seconds')
    prior=None
    while True:
        try:
            status=snapshot(args.root)
        except (OSError, ValueError, KeyError, TypeError) as error:
            record={'updated_at':datetime.now(timezone.utc).isoformat(), 'monitor_pid':os.getpid(),
                    'monitor_error':type(error).__name__, 'detail':str(error)}
            print(json.dumps(record),flush=True)
            atomic(args.root/'monitor/read-error.json',json.dumps(record,indent=2))
            if not args.watch:raise
            time.sleep(args.interval)
            continue
        (args.root/'monitor/read-error.json').unlink(missing_ok=True)
        signature=json.dumps(status['issues'],sort_keys=True)
        if signature != prior:
            with (args.root/'monitor/alerts.jsonl').open('a') as f:
                f.write(json.dumps({'timestamp':status['updated_at'],'issues':status['issues']})+'\n')
            prior=signature
        print(json.dumps({k:status[k] for k in ('updated_at','campaign_alive','started_runs','finished_runs','issues')}),flush=True)
        if not args.watch or (status['finished_runs']>=status['planned_runs'] and
            sum(v['judged'] for v in status['scores_by_strategy'].values())>=status['planned_runs']): break
        time.sleep(args.interval)


if __name__=='__main__': main()
