"""New turn-limit entry, retaining V11 worker repairs and all prior attempt costs."""
import argparse,json
from pathlib import Path
from unittest.mock import patch
import run_seven_retry3_trial_v11 as previous
from turns500_contract_v12 import validate,VERSION
_NATIVE=previous.native_command
_EXECUTE=previous.execute

def check(spec):return validate(spec,json.loads(Path(spec['config_path']).read_text()))

def native_command(spec,out):
    check(spec)
    command,result,timeout=_NATIVE(spec,out)
    names={'hermes_canvas_budget_worker_v11.py':'hermes_turns500_worker_v12.py',
           'hermes_baseline_retry3_v10.py':'hermes_turns500_worker_v12.py',
           'dsh_retry3_worker_v11.py':'dsh_turns500_worker_v12.py'}
    name=Path(command[1]).name
    if name not in names:raise ValueError('Unexpected native V12 entry')
    command[1]=str(Path(command[1]).with_name(names[name]))
    return command,result,timeout

def execute(spec_path,spec,out,**kwargs):
    check(spec)
    result=_EXECUTE(spec_path,spec,out,**kwargs)
    result.update(turn_limit_version=VERSION,max_rounds=500,
                  native_turn_mapping={'hermes':'bc100_campaign.max_rounds -> AIAgent.max_iterations',
                                       'dsh':'bc100.max_rounds -> acl-evaluation.maxSteps'})
    return result

def main():
    p=argparse.ArgumentParser(add_help=False);p.add_argument('--spec',type=Path,required=True)
    a,_=p.parse_known_args();check(json.loads(a.spec.read_text()))
    with patch.object(previous,'native_command',native_command),patch.object(previous,'execute',execute):previous.main()

if __name__=='__main__':main()
