"""Prepare V12 after a cell drains: 500 turns, 1h attempts, three total model attempts.

No caller freezes output without explicit freeze=True / --freeze. Existing V11
sources and completed outcomes remain untouched; historical limits are recorded.
"""
import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path
from lab import ROOT
from prepare_mmbc100_campaign import immutable, immutable_json
import prepare_seven_runtime_v11 as previous

VERSION = 'seven-page-turns500-v12'
SOURCE = previous.DEST
DEST = previous.BASE / 'seven-page-turns500-v12'
ZERO_MODEL_REASONS = {'verified_pre_model_contract_rejection', 'verified_pre_network_image_guard_rejection'}


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def configure(source):
    config = copy.deepcopy(source)
    config.update(turn_limit_version=VERSION, max_rounds=500, timeout_seconds=3600,
                  max_attempts=3, max_total_model_attempts=3, max_timeout_retries=2)
    for name in ('pilot', 'bc100', 'bc100_campaign', 'mmbc100_campaign', 'mmbc_vanilla_campaign'):
        if name in ('pilot', 'bc100', 'bc100_campaign') or name in config:
            if name in config and not isinstance(config[name], dict):
                raise ValueError('Invalid native configuration section: ' + name)
            config.setdefault(name, {}).update(max_rounds=500, timeout_seconds=3600)
    return config


def normalized_path(record):
    path = record.get('result_path')
    if not path: raise ValueError('Consumed model attempt lacks a result/evidence path')
    return str(Path(path).resolve())


def attempt_budget(original, result, attempt_root):
    """Count distinct physical model attempts, retaining conservative unknowns."""
    prior = original.get('prior_attempts_consumed', 0)
    if type(prior) is not int or not 0 <= prior <= 3:
        raise ValueError('Invalid inherited model attempt count')
    operational = {normalized_path(r): copy.deepcopy(r)
                   for r in original.get('prior_operational_attempts', [])}
    costs = {}
    for item in original.get('prior_attempt_costs', []):
        item = copy.deepcopy(item); path = normalized_path(item)
        if path in costs: raise ValueError('Duplicate inherited attempt path')
        if path in operational or item.get('classification') in ZERO_MODEL_REASONS:
            operational[path] = item
        else: costs[path] = item
    if len(costs) != prior:
        raise ValueError('Inherited consumed count differs from unique model-cost records')
    if result and 'prior_attempts_consumed' in result and result['prior_attempts_consumed'] != prior:
        raise ValueError('Result and plan disagree on predecessor attempt count')
    current = {}
    for item in (result or {}).get('attempts', []):
        path = normalized_path(item)
        if path in current: raise ValueError('Duplicate current attempt path')
        current[path] = copy.deepcopy(item)
    # Include a process interrupted by STOP even if its aggregate ledger was incomplete.
    for folder in sorted((Path(attempt_root) / 'runs').glob('attempt_*')):
        if not any((folder / n).exists() for n in ('result.json', 'worker-started.json', 'command.json', 'running.json')):
            continue
        path = str((folder / 'result.json').resolve())
        if path not in current:
            native = read(path) if Path(path).exists() else {}
            current[path] = {'result_path': path, 'result_sha256': sha(path) if Path(path).exists() else None,
                             'status': native.get('status', 'interrupted_unknown_acceptance'),
                             'native_artifact_root': native.get('native_artifact_root') or str(folder / 'native'),
                             'native_result_path': native.get('native_result_path'),
                             'end_to_end_seconds': native.get('end_to_end_seconds')}
    declared = (result or {}).get('attempt_count', len(current))
    if type(declared) is not int or declared < 0 or declared > len(current):
        raise ValueError('Current count has missing attempt paths; cannot reset unknown consumption')
    for path, item in current.items():
        if path in costs or path in operational:
            raise ValueError('Cross-generation attempt path reused')
        try:
            used, reason = previous.attempt_has_model_or_unknown(item)
        except (OSError, TypeError, ValueError, KeyError):
            used, reason = True, 'conservative_unknown_acceptance'
        item['classification'] = reason
        (costs if used else operational)[path] = item
    return {'prior_attempts_consumed': len(costs), 'prior_attempt_costs': list(costs.values()),
            'prior_operational_attempts': list(operational.values()),
            'current_generation_attempt_limit': max(0, 3 - len(costs))}


def selection(original, result, attempt_root):
    if result and result.get('status') == 'completed':
        return 'retain_completed', None
    # A completed native attempt must also be retained when STOP interrupted aggregation.
    physical = list((result or {}).get('attempts', []))
    physical.extend({'result_path': str(p)} for p in (Path(attempt_root) / 'runs').glob('attempt_*/result.json'))
    for entry in [*original.get('prior_attempt_costs', []), *physical]:
        path = entry.get('result_path')
        saved = read(path) if path and Path(path).exists() else entry
        if saved.get('status') == 'completed':
            return 'retain_completed_native', {'retained_result_path': path}
    if result and result.get('status') in ('failed', 'blocked'):
        return 'exclude_final_non_timeout_failure', None
    status = (result or {}).get('status', 'pending')
    if status not in ('pending', 'not_started', 'timeout', 'interrupted'):
        raise ValueError('Unrecognized predecessor outcome: ' + status)
    budget = attempt_budget(original, result, attempt_root)
    if budget['prior_attempts_consumed'] >= 3:
        return 'retain_attempt_budget_exhausted', budget
    return 'continue_timeout_or_unfinished', budget


def source_hashes():
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    if 'scripts/prepare_seven_turns500_v12.py' not in paths:
        raise ValueError('Commit the V12 sources before freezing any campaign')
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all', '--',
                                     'scripts', 'plugins', 'hermes-agent', 'harness-lock.json'], cwd=ROOT).decode()
    if dirty.strip(): raise ValueError('Commit all runtime changes before freezing source hashes')
    hashes = {name: sha(ROOT / name) for name in paths if name and (ROOT / name).is_file()
              and (name.startswith(('scripts/', 'plugins/', 'hermes-agent/'))
                   and Path(name).suffix in ('.py', '.mjs', '.js', '.ts') or name == 'harness-lock.json')}
    return hashes, subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()


def prepare(cell, freeze=False):
    if cell not in {r['cell'] for r in read(SOURCE / 'inventory.json')['cells']}:
        raise ValueError('Cell outside frozen V11 inventory')
    old, new = SOURCE / 'cells' / cell, DEST / 'cells' / cell
    if (new / 'campaign-manifest.json').exists(): return read(new / 'campaign-manifest.json')
    if not (old / 'STOP').exists() or not previous.drained(old):
        return {'cell': cell, 'state': 'waiting_for_v11_stop_and_drain'}
    plan = read(old / 'plan.json'); chosen, decisions = [], []
    bindings = {str(old / 'plan.json'): sha(old / 'plan.json'), str(old / 'STOP'): sha(old / 'STOP')}
    for path in (old / 'controllers').glob('*/*/exit.json'): bindings[str(path)] = sha(path)
    for original in plan['jobs']:
        attempt = old / 'jobs' / original['job_id'] / 'attempts/attempt_001';rp = attempt / 'result.json'
        result = read(rp) if rp.exists() else None
        if rp.exists(): bindings[str(rp)] = sha(rp)
        decision, budget = selection(original, result, attempt)
        row = {'job_id': original['job_id'], 'decision': decision,
               'predecessor_result_path': str(rp) if rp.exists() else None}
        if budget: row.update({k: v for k, v in budget.items() if k not in ('prior_attempt_costs', 'prior_operational_attempts')})
        decisions.append(row)
        if decision != 'continue_timeout_or_unfinished': continue
        cfgpath = Path(original['config_path'])
        if sha(cfgpath) != original['config_sha256']: raise ValueError('Predecessor configuration changed')
        oldcfg = read(cfgpath); bindings[str(cfgpath)] = sha(cfgpath)
        for record in budget['prior_attempt_costs'] + budget['prior_operational_attempts']:
            path = Path(record['result_path'])
            if path.exists(): bindings[str(path)] = sha(path)
            else:
                for name in ('worker-started.json', 'command.json', 'running.json'):
                    evidence = path.parent / name
                    if evidence.exists(): bindings[str(evidence)] = sha(evidence)
        chosen.append((original, oldcfg, configure(oldcfg), budget, rp))
    preview = {'cell': cell, 'state': 'ready_to_freeze', 'planned_runs': len(chosen),
               'selection_uses_answers': False, 'decisions': decisions}
    if not freeze: return preview
    hashes, commit = source_hashes()  # No output mutation before this passes.
    new.mkdir(parents=True, exist_ok=True)
    for name in ('cohort.jsonl', 'cohorts', 'image-assets'):
        source = old / name
        paths = [source] if source.is_file() else list(source.rglob('*')) if source.exists() else []
        for path in paths:
            if path.is_file(): immutable(new / path.relative_to(old), path.read_bytes())
    jobs, rawconfigs = [], []
    for original, oldcfg, cfg, budget, rp in chosen:
        raw = (json.dumps(cfg, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
        digest = hashlib.sha256(raw).hexdigest();cfgpath = new / 'configs' / (digest + '.json')
        immutable(cfgpath, raw);rawconfigs.append(raw)
        history = copy.deepcopy(original.get('historical_turn_limits', []))
        history.append({'generation': 'V11', 'source_config_path': original['config_path'],
                        'max_rounds': oldcfg.get('bc100_campaign', {}).get('max_rounds', oldcfg.get('bc100', {}).get('max_rounds')),
                        'timeout_seconds': oldcfg.get('timeout_seconds'),
                        'native_attempts_are_not_all_500_turns': True})
        job = copy.deepcopy(original)
        job.update(budget, turn_limit_version=VERSION, max_rounds=500, timeout_seconds=3600,
                   max_attempts=3, max_total_model_attempts=3, max_timeout_retries=2,
                   config_path=str(cfgpath), config_sha256=digest, historical_turn_limits=history,
                   predecessor_plan_path=str(old / 'plan.json'),
                   predecessor_result_path=str(rp) if rp.exists() else None)
        if job.get('native_cohort_path'):
            job['native_cohort_path'] = str(new / Path(job['native_cohort_path']).relative_to(old))
        jobs.append(job)
    fallback = (json.dumps(configure(read(old / 'experiment.json')), indent=2) + '\n').encode()
    immutable(new / 'experiment.json', rawconfigs[0] if rawconfigs else fallback)
    definition = {**plan['definition'], 'turn_limit_version': VERSION, 'planned_runs': len(jobs),
                  'max_rounds': 500, 'timeout_seconds': 3600, 'max_attempts': 3, 'max_timeout_retries': 2,
                  'maximum_new_attempts': 3, 'max_total_model_attempts': 3,
                  'config_sha256': sha(new / 'experiment.json'), 'cohort_sha256': sha(new / 'cohort.jsonl'),
                  'implementation_sha256': hashes, 'implementation_git_commit': commit,
                  'source_results_sha256': bindings, 'selection_uses_answers': False,
                  'attempt_budget_includes_predecessor_real_or_unknown_model_attempts': True,
                  'historical_limits_not_relabelled_as_500': True}
    if (new / 'image-assets/manifest.json').exists(): definition['input_images_sha256'] = sha(new / 'image-assets/manifest.json')
    immutable_json(new / 'plan.json', {'definition': definition, 'jobs': jobs})
    manifest = {**read(old / 'campaign-manifest.json'), 'root': str(new), 'planned_runs': len(jobs),
                'turn_limit_version': VERSION, 'plan_sha256': sha(new / 'plan.json'),
                'retained_completed': sum(r['decision'].startswith('retain_completed') for r in decisions)}
    immutable_json(new / 'campaign-manifest.json', manifest)
    immutable_json(new / 'selection.json', preview)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cell', required=True)
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args(); print(json.dumps(prepare(args.cell, freeze=args.freeze)))
