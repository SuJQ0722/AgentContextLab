"""Independent V11 worker dispatch; V10 timeout and cleanup contract unchanged."""
import json
from pathlib import Path
from unittest.mock import patch
import run_seven_retry3_trial_v10 as base
from lab import ROOT
from hermes_canvas_budget_worker_v11 import VERSION
_ORIGINAL_COMMAND = base.native_command
_ORIGINAL_EXECUTE = base.execute
_ORIGINAL_DECISION = base.retry_decision


def native_command(spec, out):
    cfg = json.loads(Path(spec['config_path']).read_text())
    if spec.get('runtime_recovery_version') != VERSION or cfg.get('runtime_recovery_version') != VERSION:
        raise ValueError('Explicit independent runtime recovery required')
    command, result, timeout = _ORIGINAL_COMMAND(spec, out)
    name = Path(command[1]).name
    replacements = {
        'hermes_baseline_inline_worker_v8.py': 'hermes_baseline_retry3_v10.py',
        'dsh_baseline_inline_worker_v8.py': 'dsh_retry3_worker_v11.py',
        'dsh_retry3_worker_v10.py': 'dsh_retry3_worker_v11.py',
        'hermes_visual_inline_retry_worker_v4.py': 'hermes_canvas_budget_worker_v11.py'}
    if name in replacements:
        command[1] = str(ROOT / 'scripts' / replacements[name])
    elif name != 'dsh_retry3_worker_v10.py':
        raise ValueError('Unexpected recovery worker')
    return command, result, timeout


def prior_attempts(spec):
    value = spec.get('prior_attempts_consumed', 0)
    if type(value) is not int or not 0 <= value <= 3:
        raise ValueError('prior_attempts_consumed must be an integer from 0 to 3')
    return value


def execute(spec_path, spec, out, **kwargs):
    consumed = prior_attempts(spec)
    remaining = 3 - consumed
    if remaining == 0:
        return {'job_id': spec['job_id'], 'status': 'not_started',
                'failure_category': 'prior_attempt_budget_exhausted', 'api_calls': 0,
                'native_cleanup_confirmed': True, 'unconfirmed_child_termination': [],
                'attempts': [], 'score': None, 'end_to_end_seconds': 0,
                'prior_attempts_consumed': consumed, 'max_total_model_attempts': 3}
    def decide(result, number, stopped=False):
        again, reason = _ORIGINAL_DECISION(result, number, stopped)
        if again and number >= remaining: return False, 'total_attempt_budget_exhausted'
        return again, reason
    with patch.object(base, 'MAX_ATTEMPTS', remaining), patch.object(base, 'retry_decision', decide):
        result = _ORIGINAL_EXECUTE(spec_path, spec, out, **kwargs)
    result.update(prior_attempts_consumed=consumed, max_total_model_attempts=3,
                  current_generation_attempt_limit=remaining,
                  total_attempts_including_prior=consumed + result.get('attempt_count', 0),
                  prior_attempt_costs=spec.get('prior_attempt_costs', []),
                  prior_operational_attempts=spec.get('prior_operational_attempts', []))
    return result


def main():
    with patch.object(base, 'native_command', native_command), patch.object(base, 'execute', execute):
        base.main()

if __name__ == '__main__': main()
