#!/usr/bin/env python3
"""Attempt-bound BC judging with isolated gold, raw usage, and no automatic API retry."""
import argparse
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import signal
import sys
import time
import urllib.error
import urllib.request
from lab import ROOT, environment
from run_bc_campaign_v3 import identity
sys.path.insert(0, str(ROOT / 'hermes-agent/Browsecomp_eval'))
from browsecomp_eval.judge import build_judge_prompt, analyse_judgemodel_res, extract_judge_object

VERSION = 'bc-completed-judge-deepseek-sfb-v1'
MODEL = 'deepseek-v4.1-flash-1017/zijian/sfb'
DEFAULT_ROOT = ROOT / 'outputs/campaigns/bc100-r3-hermes-parity-v3'
DEFAULT_RETRY = ROOT / 'outputs/campaigns/bc100-r3-hermes-parity-v3-retry1'
DEFAULT_OUT = ROOT / 'outputs/grading/bc100-v3-deepseek-sfb-v1'


def now(): return datetime.now(timezone.utc).isoformat()
def sha_bytes(value): return hashlib.sha256(value).hexdigest()
def sha(path): return sha_bytes(Path(path).read_bytes())
def read(path): return json.loads(Path(path).read_text())


def atomic(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    with temporary.open('w') as stream:
        os.chmod(temporary, 0o600); json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def immutable(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x') as stream:
            os.chmod(path, 0o600); json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    except FileExistsError:
        if read(path) != data: raise ValueError('Immutable grading source/configuration changed: ' + path.name)


def namespace(root):
    root = Path(root).resolve()
    return root.name + '-' + sha_bytes(str(root).encode())[:12]


def protocol(args):
    return {'version': VERSION, 'judge_model': MODEL, 'max_tokens': args.max_tokens,
            'temperature': 0, 'top_p': 1, 'timeout_seconds': args.timeout,
            'api_retry_policy': 'One request per completed result; unknown/error/invalid responses are never automatically retried',
            'empty_completed_prediction_rule': 'Score zero, no API request',
            'score_parser': 'Hermes standard answer-equivalence prompt; require explicit numeric JSON score 0 or 1 before original parser',
            'roots': [str(p.resolve()) for p in args.root],
            'cohort_sha256': sha(DEFAULT_ROOT / 'cohort.jsonl'),
            'environment_config': str(args.environment_config.resolve()),
            'environment_config_sha256': sha(args.environment_config),
            'sources_sha256': {'judge_script': sha(__file__),
                'hermes_judge': sha(ROOT / 'hermes-agent/Browsecomp_eval/browsecomp_eval/judge.py')},
            'answer_isolation': 'Only this judge process receives standard answers; private grading files are never added to native workspaces or model/tool inputs',
            'usd': None, 'pricing_status': 'Unknown gateway route pricing; retain raw provider usage separately from prediction spend',
            'selected_outcome_policy': 'Grading is per source result. Final attempt selection is external and must not choose by grade.'}


def usage_fields(raw):
    raw = raw if isinstance(raw, dict) else {}
    def valid(v): return type(v) in (int, float) and math.isfinite(v) and v >= 0
    prompt, output, total = (raw.get(k) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'))
    details = raw.get('prompt_tokens_details') or {}
    cached = details.get('cached_tokens') if isinstance(details, dict) else None
    present = isinstance(details, dict) and 'cached_tokens' in details
    return {'prompt_tokens': prompt if valid(prompt) else None,
            'cached_input_tokens': cached if valid(cached) else None,
            'cached_input_presence': present,
            'noncache_input_tokens': prompt-cached if valid(prompt) and valid(cached) and cached <= prompt else None,
            'output_tokens': output if valid(output) else None, 'total_tokens': total if valid(total) else None,
            'conservation': (prompt + output == total) if all(valid(v) for v in (prompt, output, total)) else None}


def strict_score(content):
    if not isinstance(content, str): return None
    obj = extract_judge_object(content)
    value = obj.get('score') if isinstance(obj, dict) else None
    if type(value) not in (int, float) or value not in (0, 1): return None
    return analyse_judgemodel_res(content)


def source_inventory(root, output, expected_cohort):
    root = Path(root).resolve()
    if not (root/'plan.json').exists(): return [], {'state': 'awaiting_campaign_materialization', 'root': str(root)}
    paths = {name: root/name for name in ('plan.json', 'experiment.json', 'cohort.jsonl')}
    if not all(p.exists() for p in paths.values()): return [], {'state': 'awaiting_campaign_materialization', 'root': str(root)}
    hashes = {name: sha(p) for name, p in paths.items()}; plan = read(paths['plan.json'])
    if hashes['cohort.jsonl'] != expected_cohort or plan['definition']['cohort_sha256'] != expected_cohort:
        raise ValueError('Grading cohort differs from the frozen BC cohort')
    if not str(read(paths['experiment.json'])['model']).startswith('deepseek-v4.1-flash-1017/'):
        raise ValueError('Only exact-version DeepSeek prediction sources are admitted')
    destination = output/'sources'/namespace(root)
    immutable(destination/'source.json', {'root': str(root), 'sha256': hashes})
    cohort = {row['id']: row for row in (json.loads(line) for line in paths['cohort.jsonl'].read_text().splitlines() if line.strip())}
    candidates = []; states = Counter(); grade_states = Counter(); cells = Counter()
    for job in plan['jobs']:
        qid = job['question_id']; row = cohort[qid]
        if job['question'] != row['question']: raise ValueError('Job question differs from frozen gold cohort question')
        relative = Path(job['job_id'])
        if relative.is_absolute() or '..' in relative.parts: raise ValueError('Invalid job path')
        attempt = root/'jobs'/relative/'attempts/attempt_001'; result_path = attempt/'result.json'
        if not result_path.exists(): states['no_terminal_result'] += 1; continue
        data = result_path.read_bytes(); result = json.loads(data); states[result.get('status', 'unknown')] += 1
        if result.get('status') != 'completed': continue
        if result.get('slot_released') is not True or result.get('unconfirmed_child_termination') != []:
            states['completed_cleanup_unconfirmed'] += 1; continue
        if result.get('job_id') != job['job_id']: raise ValueError('Result job identity mismatch')
        final = result.get('final'); prediction = final if isinstance(final, str) else final.get('text') if isinstance(final, dict) else None
        if prediction is None: prediction = ''
        if not isinstance(prediction, str): raise ValueError('Final prediction is not text')
        directory = destination/'jobs'/relative
        binding = {'root': str(root), 'job_id': job['job_id'], 'question_id': qid,
            'harness': job['harness'], 'strategy': job['strategy'], 'repeat': job['repeat'],
            'attempt_path': str(attempt), 'result_path': str(result_path), 'result_sha256': sha_bytes(data),
            'prediction_sha256': sha_bytes(prediction.encode()), 'question_sha256': sha_bytes(row['question'].encode()),
            'cohort_sha256': expected_cohort}
        if (directory/'binding.json').exists() and read(directory/'binding.json') != binding:
            raise ValueError('Already bound completed prediction changed')
        if (directory/'grade.json').exists(): grade_states[read(directory/'grade.json').get('status', 'unknown')] += 1; continue
        if (directory/'request-started.json').exists(): grade_states['request_outcome_unresolved'] += 1; continue
        candidates.append({'directory': directory, 'binding': binding, 'question': row['question'],
                           'answer': row['answer'], 'prediction': prediction})
        cells[job['harness']+'/'+job['strategy']] += 1
    return candidates, {'state': 'ready', 'root': str(root), 'planned': len(plan['jobs']), 'prediction_states': dict(states),
                         'existing_grades': dict(grade_states), 'ready_completed': len(candidates), 'ready_by_cell': dict(cells)}


def grade(candidate, config, env, opener=urllib.request.urlopen):
    directory = candidate['directory']; binding = candidate['binding']
    if sha(binding['result_path']) != binding['result_sha256']: raise ValueError('Prediction changed before grading')
    immutable(directory/'binding.json', binding)
    if (directory/'grade.json').exists() or (directory/'request-started.json').exists(): return {'status': 'already_claimed'}
    prompt = build_judge_prompt(candidate['question'], candidate['prediction'], candidate['answer'])
    payload = {'model': config['judge_model'], 'messages': [{'role': 'user', 'content': prompt}],
               'max_tokens': config['max_tokens'], 'temperature': config['temperature'], 'top_p': config['top_p']}
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode()
    immutable(directory/'request.json', payload)
    record = {'version': VERSION, **binding, 'purpose': 'judge', 'judge_model': config['judge_model'],
              'request_sha256': sha_bytes(payload_bytes), 'started_at': now(), 'api_calls': None,
              'score': None, 'raw_provider_usage': None, 'usage': usage_fields(None), 'usd': None,
              'provider_internal_latency_seconds': None, 'status': 'unknown', 'worker_identity': identity()}
    try:
        with (directory/'request-started.json').open('x') as stream:
            os.chmod(directory/'request-started.json', 0o600); json.dump(record, stream); stream.flush(); os.fsync(stream.fileno())
    except FileExistsError: return {'status': 'already_claimed'}
    if not candidate['prediction'].strip():
        record.update(status='scored', score=0., api_calls=0, rule='empty_completed_prediction', finished_at=now())
        atomic(directory/'grade.json', record); return record
    request = urllib.request.Request(env['TOKENHUB_BASE_URL'].rstrip('/')+'/chat/completions', data=payload_bytes,
        headers={'Authorization': 'Bearer '+env['TOKENHUB_API_KEY'], 'Content-Type': 'application/json'})
    record['api_calls'] = 1
    atomic(directory/'request-dispatched.json', {'at': now(), 'request_sha256': record['request_sha256'],
        'meaning': 'Durable intent immediately before one HTTP operation; if no result follows, whether the provider billed it is unknown'})
    started = time.monotonic()
    try:
        with opener(request, timeout=config['timeout_seconds']) as response:
            data = json.load(response); record['http_status'] = getattr(response, 'status', 200)
            record['provider_request_id'] = response.headers.get('x-request-id')
        atomic(directory/'response.json', data)
        raw = data.get('usage'); record['raw_provider_usage'] = raw; record['usage'] = usage_fields(raw)
        record['returned_model'] = data.get('model'); record['returned_model_matches_preflight_observation'] = data.get('model') == 'deepseek-v4-1-flash-261017'
        record['backend_weights_equivalence_verified'] = None
        choice = data['choices'][0]; record['finish_reason'] = choice.get('finish_reason')
        score = strict_score(choice.get('message', {}).get('content'))
        record.update(status='scored' if score is not None else 'invalid_judge_response', score=score)
    except urllib.error.HTTPError as error:
        record.update(status='http_error', http_status=error.code, error_type=type(error).__name__)
    except Exception as error:
        record.update(status='judge_error', error_type=type(error).__name__)
    record.update(finished_at=now(), client_http_seconds=time.monotonic()-started,
                  timing_definition='Client request plus response body wall time; no retry; not provider-internal latency')
    atomic(directory/'grade.json', record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, action='append')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--environment-config', type=Path, default=DEFAULT_ROOT/'experiment.json')
    parser.add_argument('--concurrency', type=int, default=4); parser.add_argument('--max-tokens', type=int, default=8192)
    parser.add_argument('--timeout', type=int, default=180); parser.add_argument('--limit', type=int)
    parser.add_argument('--watch', action='store_true'); parser.add_argument('--live', action='store_true')
    args = parser.parse_args(); args.root = args.root or [DEFAULT_ROOT, DEFAULT_RETRY]
    if not 1 <= args.concurrency <= 4 or args.max_tokens != 8192 or args.timeout < 1:
        parser.error('Reviewed judge protocol requires concurrency 1–4, max_tokens 8192, positive timeout')
    args.output.mkdir(parents=True, exist_ok=True); os.chmod(args.output, 0o700)
    config = protocol(args); immutable(args.output/'protocol.json', config)
    if not args.live:
        inventory = [source_inventory(root, args.output, config['cohort_sha256'])[1] for root in args.root]
        n = sum(row.get('ready_completed', 0) for row in inventory)
        print(json.dumps({'live': False, 'judge_model': MODEL, 'inventory': inventory,
                          'maximum_new_requests': n, 'output_tokens_upper_bound': n*8192, 'usd_estimate': None})); return
    import fcntl
    lease = (args.output/'controller.lock').open('a'); fcntl.flock(lease, fcntl.LOCK_EX|fcntl.LOCK_NB)
    env, _ = environment(ROOT, 'dsh', args.environment_config)
    stopped = False
    def stop(*unused):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    pending = deque(); futures = {}; submitted = 0; results = Counter(); inventory = []; scanned = 0.; next_scan = 0.
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        while True:
            current = time.time()
            if not stopped and not pending and current >= next_scan:
                batch = []; inventory = []
                for root in args.root:
                    candidates, info = source_inventory(root, args.output, config['cohort_sha256']); batch.extend(candidates); inventory.append(info)
                rng = random.Random(20261109); rng.shuffle(batch)
                pending.extend(c for c in batch if str(c['directory']) not in futures.values())
                scanned = time.time(); next_scan = scanned + 60
            while not stopped and pending and len(futures) < args.concurrency and (args.limit is None or submitted < args.limit):
                candidate = pending.popleft(); future = pool.submit(grade, candidate, config, env)
                futures[future] = str(candidate['directory']); submitted += 1
            if futures:
                finished, _ = wait(futures, timeout=1, return_when=FIRST_COMPLETED)
                for future in finished:
                    directory = futures.pop(future)
                    try: result = future.result(); results[result['status']] += 1
                    except Exception as error:
                        results['local_error'] += 1
                        atomic(args.output/'last-local-error.json', {'at': now(), 'directory': directory, 'error_type': type(error).__name__})
            state = {'at': now(), 'identity': identity(), 'stopping': stopped, 'active_requests': len(futures),
                     'pending_in_snapshot': len(pending), 'submitted_this_controller': submitted, 'outcomes_this_controller': dict(results),
                     'last_scan_unix': scanned, 'inventory': inventory, 'usage_authority': 'Per-grade raw_provider_usage; never add normalized tokens twice', 'usd': None}
            atomic(args.output/'status.json', state)
            exhausted = args.limit is not None and submitted >= args.limit
            if not futures and (stopped or exhausted or not args.watch and not pending): break
            if not futures: time.sleep(1)


if __name__ == '__main__': main()
