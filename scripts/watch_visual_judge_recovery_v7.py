"""Persistent four-channel recovery of explicit failed V7 judge calls only."""
import argparse
import concurrent.futures
import fcntl
import hashlib
import json
from pathlib import Path
import time

import recover_visual_judging_v1 as recovery
from lab import ROOT, environment

base = recovery.base
VERSION = 'visual-inline-v7-judge-recovery-watch-v1'
SOURCE = ROOT / 'outputs/grading/visual-inline-two-hour-v7'
OUT = ROOT / 'outputs/grading/visual-inline-two-hour-judge-recovery-v1'


def runnable(state, now):
    return state.get('status') in (None, 'running', 'retry_deadline') and now >= state.get('next_eligible_unix', 0)


def preserve_unknown(call):
    def guarded(*args, **kwargs):
        value = call(*args, **kwargs)
        # Preserve the original on-disk error and do not repeat unknown acceptance.
        return {**value, 'status': 'unknown_judge_acceptance_requires_audit'} if value.get('status') == 'judge_error' else value
    return guarded


def recover_checked(candidate, env):
    if not (candidate['directory'] / 'resolved.json').exists():
        for path in (candidate['directory'] / 'attempts').glob('attempt_*/grade.json'):
            if base.read(path).get('status') == 'judge_error':
                return {'status': 'unknown_judge_acceptance_requires_audit',
                        'cell': candidate['cell'], 'job_id': candidate['job_id']}
    return recovery.recover(candidate, env, call=preserve_unknown(recovery.judge_one))


class Observer:
    def __init__(self, source, out):
        self.source, self.out = Path(source).resolve(), Path(out).resolve()
        if self.source == self.out or self.source in self.out.parents or self.out in self.source.parents:
            raise ValueError('Independent judge recovery namespace required')
        self.out.mkdir(parents=True, exist_ok=True); self.out.chmod(0o700)
        self.gold, self.gold_hashes = recovery.parent.gold_sources()
        self.contexts = {}
        for cell in sorted((self.source / 'cells').iterdir()):
            binding = base.read(cell / 'source-binding.json'); root = Path(binding['root'])
            if 'transport-v7-two-hour' not in root.parts:
                raise ValueError('Only V7 predictions are eligible')
            plan = base.read(root / 'plan.json')
            if base.sha(root / 'plan.json') != binding['plan_sha256']:
                raise ValueError('Prediction plan changed')
            self.contexts[cell.name] = {'binding': binding, 'root': root,
                                       'jobs': {j['job_id']: j for j in plan['jobs']}}
        protocol = {'version': VERSION, 'source': str(self.source), 'allowed_models': list(recovery.ALLOWED_MODELS),
            'concurrency': 4, 'poll_seconds': 20, 'max_tokens': 8192, 'temperature': 0, 'top_p': 1,
            'eligible_original_http_status': [408, 429, 500, 502, 503, 504],
            'unknown_acceptance_automatic_retry': False, 'successful_scores_never_rejudged': True,
            'old_grades_preserved': True, 'prediction_files_modified': False,
            'gold_sources_sha256': self.gold_hashes,
            'source_binding_sha256': {c: base.sha(self.source / 'cells' / c / 'source-binding.json') for c in self.contexts},
            'source_sha256': {str(p): base.sha(p) for p in (Path(__file__), ROOT / 'scripts/recover_visual_judging_v1.py')}}
        base.immutable(self.out / 'protocol.json', protocol)

    def candidates(self):
        result = []
        for row in base.read(self.source / 'observations.json'):
            if row['prediction_status'] != 'completed' or row.get('score') is not None:
                continue
            cell, jid = row['cell'], row['job_id']; context = self.contexts[cell]
            job = context['jobs'][jid]; gd = self.source / 'cells' / cell / 'jobs' / jid
            gp = gd / 'grade.json'
            if not gp.exists() or not recovery.eligible(base.read(gp)):
                continue
            binding = base.read(gd / 'binding.json'); rp = Path(binding['result_path'])
            expected = context['root'] / 'jobs' / jid / 'attempts/attempt_001/result.json'
            prediction_result = base.read(rp)
            if rp != expected or base.sha(rp) != binding['result_sha256'] or prediction_result['status'] != 'completed' or not base.clean(prediction_result):
                raise ValueError('Prediction identity/cleanup changed')
            if binding['gold_sources_sha256'] != self.gold_hashes:
                raise ValueError('Gold binding changed')
            secret = self.gold[recovery.parent.gold_key(job)][job['question_id']]
            if secret['question'] != job['question']:
                raise ValueError('Question identity mismatch')
            final = prediction_result['final']; prediction = final if isinstance(final, str) else final.get('text', '')
            prompt = base.bc.build_judge_prompt(job['question'], prediction, secret['answer'])
            expected_request = {'model': base.MODEL, 'messages': [{'role': 'user', 'content': prompt}],
                                'max_tokens': 8192, 'temperature': 0, 'top_p': 1}
            if base.read(gd / 'request.json') != expected_request:
                raise ValueError('Existing answer-equivalence protocol changed')
            candidate = {'cell': cell, 'job_id': jid, 'binding': binding, 'question': job['question'],
                'answer': secret['answer'], 'prediction': prediction, 'old_grade_path': str(gp),
                'old_grade_sha256': base.sha(gp), 'directory': self.out / 'cells' / cell / 'jobs' / jid}
            base.immutable(candidate['directory'] / 'candidate-binding.json',
                {k: candidate[k] for k in ('cell', 'job_id', 'old_grade_path', 'old_grade_sha256', 'binding')})
            result.append(candidate)
        return result

    def publish(self, states, active=0):
        source_bytes = (self.source / 'observations.json').read_bytes()
        rows = json.loads(source_bytes); usage = []; unknown = 0; resolved_rows = []
        for row in rows:
            directory = self.out / 'cells' / row['cell'] / 'jobs' / row['job_id']
            rp = directory / 'resolved.json'
            if rp.exists():
                value = base.read(rp); grade = base.read(value['grade_path'])
                if base.sha(value['old_grade_path']) != value['old_grade_sha256'] or grade.get('status') != 'scored' or grade.get('score') != value['score']:
                    raise ValueError('Resolved grade binding changed')
                row.update(score=value['score'], score_reason='judged_completed_recovered', recovery_grade=value['grade_path'])
                resolved_rows.append(value)
            for attempt in (directory / 'attempts').glob('attempt_*'):
                gp = attempt / 'grade.json'
                if gp.exists():
                    grade = base.read(gp)
                    if grade.get('api_calls') != 0:
                        usage.append({'raw_provider_usage': grade.get('raw_provider_usage'), '_incomplete': grade.get('raw_provider_usage') is None})
                elif (attempt / 'request-started.json').exists():
                    unknown += 1; usage.append({'raw_provider_usage': None, '_incomplete': True})
        base.atomic(self.out / 'observations-merged.json', rows)
        base.atomic(self.out / 'resources.json', {'at': base.bc.now(), 'scope': 'Additional V7 judging only; original prediction/judge costs remain separate',
            'usage': base.aggregate(usage), 'unresolved_started_attempts': unknown, 'usd': None,
            'original_resources_path': str(self.source / 'resources.json')})
        summary = {'at': base.bc.now(), 'version': VERSION, 'active_recovery_jobs': active,
            'recovery_jobs_seen': len(states), 'recovered_scored': len(resolved_rows),
            'completed': sum(r['prediction_status'] == 'completed' for r in rows),
            'completed_missing_grade': sum(r['prediction_status'] == 'completed' and r.get('score') is None for r in rows),
            'rows': len(rows), 'results': resolved_rows, 'state_counts': dict(__import__('collections').Counter(s['status'] for s in states.values())),
            'source_observations_sha256': hashlib.sha256(source_bytes).hexdigest(), 'old_files_preserved': True}
        base.atomic(self.out / 'summary.json', summary)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE); parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--live', action='store_true'); parser.add_argument('--watch', action='store_true')
    args = parser.parse_args(); observer = Observer(args.source, args.output)
    recovery.VERSION = VERSION
    candidates = observer.candidates()
    if not args.live:
        print(json.dumps({'live': False, 'eligible': len(candidates), 'model_calls': 0})); return
    env, _ = environment(ROOT, 'hermes'); state_path = observer.out / 'state.json'
    states = base.read(state_path) if state_path.exists() else {}
    with (observer.out / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            pending = {}
            while True:
                for future in list(pending):
                    if not future.done(): continue
                    key = pending.pop(future)
                    try: value = future.result()
                    except Exception as exc: value = {'status': 'requires_audit', 'error_type': type(exc).__name__}
                    states[key] = {**value, 'finished_at': base.bc.now()}
                    if value['status'] == 'retry_deadline': states[key]['next_eligible_unix'] = time.time() + 120
                    base.atomic(state_path, states)
                candidates = observer.candidates()
                for candidate in candidates:
                    if (observer.out / 'STOP').exists(): break
                    key = candidate['cell'] + '|' + candidate['job_id']
                    if len(pending) >= 4: break
                    if key in pending.values() or not runnable(states.get(key, {}), time.time()): continue
                    states[key] = {'status': 'running', 'started_at': base.bc.now()}; base.atomic(state_path, states)
                    future = pool.submit(recover_checked, candidate, env)
                    pending[future] = key
                observer.publish(states, len(pending))
                if not args.watch and not pending: break
                if (observer.out / 'STOP').exists() and not pending: break
                time.sleep(5 if pending else 20)


if __name__ == '__main__': main()
