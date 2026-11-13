"""Pending-only formal V14 grading and strict three-arm eligibility report.

No generation or judge retries. Dry by default; calibration is never accuracy.
Known SDK costs include compaction/calibration separately; route-level extra
attempt costs remain in their original transport ledger and are not invented.
"""
import argparse
import collections
import concurrent.futures
import fcntl
import io
import json
import time
import urllib.error
from pathlib import Path
import httpx
import judge_bc_v3_completed as bc
from judge_visual_hosted_retry_v1 import gold_sources, gold_key
from lab import ROOT, environment
from controlled_single_pass_v14 import DEFAULT, FINISH_BY, read, sha, save
from info_loss_report import summarize_usage

OUT = ROOT / 'outputs/grading/controlled-formal-single-pass-v14'


def measured_costs(attempt):
    def lines(name):
        path = attempt / 'metrics' / name
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    sdk = lines('calls.jsonl'); starts = lines('call-starts.jsonl')
    by_purpose = {}
    for purpose in sorted({row.get('purpose') for row in starts} | {row.get('purpose') for row in sdk}, key=str):
        observations = [{'usage': r.get('raw_provider_usage'), 'client_http_seconds': r.get('client_stream_seconds')}
                        for r in sdk if r.get('purpose') == purpose]
        by_purpose[str(purpose)] = summarize_usage(observations, sum(r.get('purpose') == purpose for r in starts))
    wire_started = set(); wire = {}
    for row in lines('transport-phases-v3.jsonl'):
        rid = row.get('request_id')
        if not rid: continue
        if row.get('event') == 'request_started': wire_started.add(rid)
        if row.get('event') in ('stream_complete', 'route_returned', 'route_failed'):
            wire[rid] = {**wire.get(rid, {}), **row}
    physical = summarize_usage([{'usage': r.get('raw_provider_usage'), 'client_http_seconds': r.get('elapsed_seconds')}
                                for r in wire.values()], len(wire_started))
    control = read(attempt / 'compression-control.json') if (attempt / 'compression-control.json').exists() else {}
    return {'sdk_by_purpose': by_purpose, 'physical_wire_all_purposes': physical,
            'views_overlap_do_not_add_sdk_to_physical': True,
            'physical_purpose_attribution_not_instrumented': True,
            'calibration_included_in_actual_spend_not_accuracy': True,
            'render_seconds': control.get('render_seconds'), 'encoding_seconds': control.get('canvas_encoding_seconds'),
            'provider_latency_unmeasured': True}


def valid_control(control, target):
    prompt = control.get('first_actual_prompt_tokens'); expected = target.get('first_actual_prompt_tokens')
    return bool(control.get('passed') is True and control.get('final_wire_native_identity_preserved') is True
        and control.get('prefix_sha256') == target.get('prefix_sha256') and control.get('native_hashes') == target.get('native_hashes')
        and control.get('actual_route') == target.get('actual_route')
        and type(prompt) is int and type(expected) is int and 0 < prompt <= 16384 and expected > 0
        and abs(prompt - expected) / expected <= .02)


def matched_group(rows):
    if len(rows) != 3 or {r['method'] for r in rows} != {'visual', 'summary', 'window'}: return False
    if not all(r.get('control_valid') and r.get('score') is not None for r in rows): return False
    if len({r['prefix_sha256'] for r in rows}) != 1 or len({tuple(r['native_hashes']) for r in rows}) != 1: return False
    tokens = [r['actual_prompt_tokens'] for r in rows]
    return (max(tokens) - min(tokens)) / max(tokens) <= .05


def inventory(root, out, plan, gold, hashes):
    rows = []; candidates = []
    for job in plan['jobs']:
        attempt = Path(job['campaign_root']) / 'jobs' / job['job_id'] / 'attempt_001'
        terminal = read(attempt / 'terminal.json') if (attempt / 'terminal.json').exists() else {}
        result = read(attempt / 'native-result.json') if (attempt / 'native-result.json').exists() else {}
        control = read(attempt / 'compression-control.json') if (attempt / 'compression-control.json').exists() else {}
        target = read(job['control_target_path']) if Path(job['control_target_path']).exists() else {}
        destination = out / 'jobs' / job['job_id']; grade = read(destination / 'grade.json') if (destination / 'grade.json').exists() else {}
        valid = valid_control(control, target)
        row = {'job_id': job['job_id'], 'prefix_key': job['controlled_prefix_key'], 'dataset': job['dataset'],
            'method': job['controlled_method'], 'status': terminal.get('status', 'not_terminal'),
            'control_valid': valid, 'prefix_sha256': control.get('prefix_sha256'), 'native_hashes': control.get('native_hashes'),
            'actual_prompt_tokens': control.get('first_actual_prompt_tokens'), 'grade_status': grade.get('status'),
            'score': grade.get('score') if grade.get('status') == 'scored' and valid else None}
        if terminal:
            accounting = destination / 'prediction-accounting.json'
            if not accounting.exists(): save(accounting, measured_costs(attempt))
            row['prediction_accounting_path'] = str(accounting)
        if terminal.get('status') == result.get('status') == 'completed' and valid and not job.get('calibration_not_scored'):
            if not (destination / 'request-started.json').exists():
                secret = gold[gold_key(job)][job['question_id']]
                if secret['question'] != job['question']: raise ValueError('Gold question mismatch')
                binding = {'job_id': job['job_id'], 'plan_sha256': sha(root / 'plan.json'),
                    'result_path': str(attempt / 'native-result.json'), 'result_sha256': sha(attempt / 'native-result.json'),
                    'control_sha256': sha(attempt / 'compression-control.json'), 'target_sha256': sha(job['control_target_path']),
                    'gold_sources_sha256': hashes, 'calibration_not_scored': False}
                candidates.append({'directory': destination, 'binding': binding, 'question': secret['question'],
                                   'answer': secret['answer'], 'prediction': result['final']['text']})
        rows.append(row)
    return rows, candidates


def main():
    p = argparse.ArgumentParser(); p.add_argument('--root', type=Path, default=DEFAULT); p.add_argument('--out', type=Path, default=OUT)
    p.add_argument('--watch', action='store_true'); p.add_argument('--live', action='store_true'); p.add_argument('--concurrency', type=int, default=2)
    args = p.parse_args(); root = args.root.resolve(); out = args.out.resolve()
    if not 1 <= args.concurrency <= 4: raise ValueError('Judge concurrency cap four')
    if out == root or root in out.parents or out in root.parents: raise ValueError('Private grading outside prediction tree required')
    out.mkdir(parents=True, exist_ok=True); out.chmod(0o700)
    lock = (out / 'run.lock').open('a'); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    plan = read(root / 'plan.json'); gold, hashes = gold_sources(); env, _ = environment(ROOT, 'hermes')
    cfg = {'judge_model': 'deepseek-v4.1-flash-1017/huoshan/huoshan', 'max_tokens': 8192, 'temperature': 0, 'top_p': 1, 'timeout_seconds': 180}
    bc.immutable(out / 'protocol.json', {'version': 'controlled-formal-single-pass-grading-v14',
        'plan_sha256': sha(root / 'plan.json'), 'gold_sha256': hashes, 'config': cfg, 'retries': 0,
        'maximum_new_judges': len(plan['jobs']), 'calibration_is_not_accuracy': True,
        'sources_sha256': {name: sha(ROOT / 'scripts' / name) for name in
            [Path(__file__).name, 'judge_bc_v3_completed.py', 'judge_visual_hosted_retry_v1.py', 'info_loss_report.py']}})
    def opener(request, timeout):
        with httpx.Client(proxy=env.get('HTTPS_PROXY') or env.get('https_proxy'), trust_env=False, timeout=timeout) as client:
            response = client.post(request.full_url, content=request.data, headers=dict(request.header_items()))
        if response.status_code >= 400:
            raise urllib.error.HTTPError(request.full_url, response.status_code, 'Provider error', response.headers, io.BytesIO(response.content))
        buffer = io.BytesIO(response.content); buffer.status = response.status_code; buffer.headers = response.headers; return buffer
    while True:
        rows, pending = inventory(root, out, plan, gold, hashes)
        groups = collections.defaultdict(list)
        for row in rows: groups[row['prefix_key']].append(row)
        matched = {key: value for key, value in groups.items() if matched_group(value)}
        save(out / 'report.json', {'at': time.time(), 'rows': rows, 'matched_scored_groups': matched,
            'matched_group_count': len(matched), 'pending_judges': len(pending), 'missing_not_zero': True,
            'not_a_complete_100x3_benchmark': True, 'old_protocol_scores_not_merged': True})
        if args.live and time.time() < FINISH_BY and not (out / 'STOP').exists():
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                list(pool.map(lambda candidate: bc.grade(candidate, cfg, env, opener=opener), pending))
        if not args.watch or time.time() >= FINISH_BY or (out / 'STOP').exists(): return
        if all(row['status'] != 'not_terminal' for row in rows) and not pending: return
        time.sleep(30)


if __name__ == '__main__': main()
