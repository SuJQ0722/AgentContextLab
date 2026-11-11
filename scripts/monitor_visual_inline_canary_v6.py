"""Read-only minute snapshots of eight canaries; no prediction or grading calls."""
import argparse
from datetime import datetime, timezone, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import time

from lab import ROOT
from prepare_visual_inline_canary_v6 import DEST, CELLS
from visual_inline_route_accounting_v5 import resources
from run_bc_campaign_v3 import atomic

OUTPUT = ROOT / 'outputs/monitoring/visual-inline-canary-v6'
GRADES = ROOT / 'outputs/grading/visual-inline-canary-v6'
SUPPLEMENT = DEST / 'cells/input-reuse-v1'
SUPPLEMENT_GRADES = ROOT / 'outputs/grading/visual-inline-canary-v6-input-reuse-v1'
OBSERVER_PID = 806586
OBSERVER_START = '905400780'


def read(path):
    try: return json.loads(Path(path).read_text())
    except (OSError, ValueError): return {}


def process(pid):
    try:
        path = Path('/proc') / str(pid)
        fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
        command = (path / 'cmdline').read_bytes()
        return {'pid': int(pid), 'state': fields[0], 'start_identity': fields[19],
                'command_sha256': hashlib.sha256(command).hexdigest(),
                'alive': fields[0] != 'Z'}
    except (OSError, ValueError, TypeError): return {'pid': pid, 'alive': False}


def grade_state(result, grade, local_error, request_started, grader_alive):
    terminal = result.get('status') in ('completed', 'failed', 'timeout', 'not_started')
    clean = result.get('slot_released') is True and result.get('unconfirmed_child_termination') == []
    if not terminal or not clean: return {'done': False, 'state': 'prediction_pending_or_cleanup_unconfirmed', 'score': None}
    if result['status'] != 'completed':
        return {'done': True, 'state': 'confirmed_operational_failure', 'score': 0.0}
    if grade.get('status') == 'scored' and type(grade.get('score')) in (int, float) and grade['score'] in (0, 1):
        return {'done': True, 'state': 'scored', 'score': grade['score']}
    if grade or local_error:
        return {'done': True, 'state': grade.get('status', 'judge_local_error'),
                'score': None, 'error_type': grade.get('error_type', local_error.get('error_type'))}
    if not grader_alive:
        return {'done': True, 'state': 'judge_error_recorded_by_monitor', 'score': None,
                'error_type': 'UnresolvedJudgeRequest' if request_started else 'GraderExitedWithoutScore'}
    return {'done': False, 'state': 'judging' if request_started else 'awaiting_grade', 'score': None}


def compact_usage(value):
    return {k: v for k, v in value.items() if k not in ('http_attempt_records', 'attempt_accounting')}


def snapshot():
    rows = []; now = time.time()
    for cell in CELLS:
        replacement = cell == 'controlled_mmbc'
        root = (SUPPLEMENT if replacement else DEST) / 'cells' / cell
        grading = SUPPLEMENT_GRADES if replacement else GRADES
        plan = read(root / 'plan.json'); job = plan['jobs'][0]
        attempt = root / 'jobs' / job['job_id'] / 'attempts/attempt_001'
        result = read(attempt / 'result.json')
        gs = read(grading / 'status.json'); gp = process(gs.get('pid'))
        gd = grading / 'cells' / cell / 'jobs' / job['job_id']
        scored = grade_state(result, read(gd / 'grade.json'), read(gd / 'local-error.json'),
                             (gd / 'request-started.json').exists(), gp['alive'])
        controllers = []
        for path in (root / 'controllers').glob('*/*/status.json'):
            status = read(path); info = process(status.get('pid'))
            controllers.append({**info, 'heartbeat_age_seconds': max(0, now - status.get('at', now)),
                'active': status.get('active_local'), 'target_concurrency': status.get('target_concurrency'),
                'launched': status.get('launched'), 'stop_dispatch': status.get('stop_dispatch'),
                'error_type': status.get('error_type'), 'exit': read(path.with_name('exit.json'))})
        usage = resources({cell: {'root': root, 'plan': plan}}, grading)['cells'][cell]
        row = {'cell': cell, 'job_id': job['job_id'], 'effective_root': str(root),
               'replacement_attempt': replacement, 'prediction_status': result.get('status', 'running_or_pending'),
               'end_to_end_seconds': result.get('end_to_end_seconds'), 'grading': scored,
               'controllers': controllers, 'grader': {**gp, 'status': gs}, 'actual_token_accounting': compact_usage(usage)}
        if replacement:
            prior = DEST / 'cells' / cell / 'jobs' / job['job_id'] / 'attempts/attempt_001'
            r = read(prior / 'result.json'); native = read(prior / 'native/native-result.json')
            row['retained_prior_attempt'] = {'path': str(prior), 'status': r.get('status'),
                'error_type': native.get('error_type'), 'end_to_end_seconds': r.get('end_to_end_seconds'),
                'included_in_effective_score': False, 'preserved': True}
        rows.append(row)
    return {'version': 'readonly-canary-monitor-v6', 'at_unix': time.time(),
            'beijing_time': datetime.now(timezone(timedelta(hours=8))).isoformat(),
            'interval_seconds': 60, 'model_calls': 0, 'auto_retry': False, 'auto_create_cci': False,
            'full_campaign_resume': False, 'all_finished_and_accounted': all(r['grading']['done'] for r in rows),
            'interpretation': 'Eight conditional canary trials, not full benchmark accuracy. Original input failure retained separately; current controlled MMBC uses its explicit supplementary attempt. Missing token usage remains unknown, never free; grading tokens are separate.',
            'rows': rows}


def markdown(value):
    lines = ['# V6 canary 当前状态', '', value['beijing_time'], '',
             '只读监控；不会重跑、开CCI或恢复整批。仅8题条件验证，不代表benchmark准确率。', '',
             '| Cell | 预测 | 评分状态 | 分数 | 活跃任务 | Cached | Non-cache | Output | Total | 未知usage请求 |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in value['rows']:
        accounting = row['actual_token_accounting']; fields = accounting['new_prediction_all_attempts']['fields']
        def token(key):
            x = fields[key]
            return str(x['complete_total']) if x.get('complete_total') is not None else f"{x.get('known_subtotal', 0)} known / {x.get('missing_count', 0)} missing"
        score = row['grading']['score']; active = sum(c.get('active') or 0 for c in row['controllers'] if c['alive'])
        lines.append(f"| {row['cell']} | {row['prediction_status']} | {row['grading']['state']} | {score if score is not None else 'missing'} | {active} | {token('cached_input')} | {token('noncache_input')} | {token('output')} | {token('total')} | {accounting['unknown_usage_attempts']} |")
    lines += ['', 'controlled MMBC使用独立input-reuse补充尝试；原URLError轨迹保留，未删除或覆盖。预测和评分token分开存于JSON，无法观测的usage/费用不视为零。', '',
              '所有题次已结束并评分或明确记录错误：' + str(value['all_finished_and_accounted'])]
    return '\n'.join(lines) + '\n'


def stop_observer(binding):
    current = process(OBSERVER_PID)
    if not current['alive']: return {'action': 'already_exited', 'pid': OBSERVER_PID}
    if current.get('start_identity') != OBSERVER_START or any(current.get(k) != binding.get(k) for k in ('start_identity', 'command_sha256')):
        return {'action': 'not_signaled_identity_mismatch', 'pid': OBSERVER_PID}
    os.kill(OBSERVER_PID, signal.SIGTERM)
    return {'action': 'sigterm_exact_readonly_resource_observer', 'pid': OBSERVER_PID, 'at_unix': time.time()}


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--watch', action='store_true'); p.add_argument('--out', type=Path, default=OUTPUT); a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    lock = (a.out / 'monitor.lock').open('a'); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    observer = process(OBSERVER_PID)
    if observer['alive']:
        args = (Path('/proc') / str(OBSERVER_PID) / 'cmdline').read_bytes().split(b'\0')
        if observer['start_identity'] != OBSERVER_START or b'scripts/watch_visual_inline_resources_v5.py' not in args:
            raise ValueError('Resource observer identity differs; no signal authority')
    atomic(a.out / 'service.json', {'pid': os.getpid(), 'identity': process(os.getpid()), 'observer_binding': observer,
                                   'started_at_unix': time.time(), 'interval_seconds': 60})
    stopping = False
    def stop(*unused):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    while not stopping:
        try:
            value = snapshot(); atomic(a.out / 'monitor.json', value)
            temporary = a.out / 'monitor.md.tmp'; temporary.write_text(markdown(value)); temporary.replace(a.out / 'monitor.md')
        except Exception as e:
            atomic(a.out / 'read-error.json', {'at_unix': time.time(), 'error_type': type(e).__name__, 'read_only': True})
            value = {'all_finished_and_accounted': False}
        if value['all_finished_and_accounted']:
            action = stop_observer(observer); atomic(a.out / 'observer-stop.json', action)
            atomic(a.out / 'exit.json', {'at_unix': time.time(), 'reason': 'all_eight_final_scores_or_recorded_errors', 'observer_action': action}); return
        if not a.watch: return
        deadline = time.monotonic() + 60
        while not stopping and time.monotonic() < deadline: time.sleep(min(1, deadline - time.monotonic()))
    atomic(a.out / 'exit.json', {'at_unix': time.time(), 'reason': 'monitor_stop_signal', 'native_signaled': False})


if __name__ == '__main__': main()
