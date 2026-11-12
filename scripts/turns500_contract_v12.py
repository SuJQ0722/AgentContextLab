"""Explicit 500-turn mapping, with inherited one-hour/three-attempt accounting."""
from one_hour_timeout_retry_v10 import validate as validate_retry
from hermes_canvas_budget_worker_v11 import VERSION as RECOVERY_VERSION
VERSION = 'seven-page-turns500-v12'
MAX_ROUNDS = 500
SECTIONS = ('pilot','bc100','bc100_campaign','mmbc100_campaign','mmbc_vanilla_campaign')


def validate(spec, config):
    validate_retry(spec, config)
    for row in (spec, config):
        if row.get('turn_limit_version') != VERSION or row.get('runtime_recovery_version') != RECOVERY_VERSION:
            raise ValueError('Explicit V12 turn policy and V11 runtime required')
        if type(row.get('max_rounds')) is not int or row['max_rounds'] != MAX_ROUNDS:
            raise ValueError('Explicit max_rounds=500 required')
        if type(row.get('max_attempts')) is not int or row['max_attempts'] != 3:
            raise ValueError('Three total attempts, including prior generations, required')
    for section in SECTIONS:
        if section not in config:
            if section in ('pilot','bc100','bc100_campaign'): raise ValueError('Required native turn section missing: '+section)
            continue
        row=config[section]
        if type(row.get('max_rounds')) is not int or row['max_rounds'] != MAX_ROUNDS:
            raise ValueError('Native max_rounds differs in '+section)
        if row.get('timeout_seconds') != 3600 or type(row.get('timeout_seconds')) is not int:
            raise ValueError('Native timeout differs in '+section)
    consumed=spec.get('prior_attempts_consumed')
    if type(consumed) is not int or not 0 <= consumed <= 3:
        raise ValueError('Explicit cumulative prior_attempts_consumed required')
    costs=spec.get('prior_attempt_costs')
    if not isinstance(costs,list) or len(costs)!=consumed:
        raise ValueError('Cumulative prior cost ledger must match consumed attempts')
    paths=[x.get('result_path') for x in costs]
    if any(not isinstance(x,str) or not x for x in paths) or len(set(paths))!=len(paths):
        raise ValueError('Prior attempt costs need unique physical result paths')
    return {'hermes_max_iterations':config['bc100_campaign']['max_rounds'],
            'dsh_bc100_maxSteps':config['bc100']['max_rounds'],
            'prior_attempts_consumed':consumed,'remaining_attempts':3-consumed}
