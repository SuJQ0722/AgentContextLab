"""Same one-hour retry5 contract; only DSH middleware/CLI setup is replaced."""
from pathlib import Path
from unittest.mock import patch
import run_visual_inline_retry5_trial_v8 as base
from lab import ROOT
original=base.native_command


def native_command(spec,out):
    if spec.get('operational_recovery_version')!='inline-runtime-recovery-v9':raise ValueError('Explicit recovery required')
    command,result,timeout=original(spec,out)
    if spec.get('controlled_retry_version')=='controlled-inline-matched-retry-v8':
        if Path(command[1]).name!='controlled_inline_retry_v8.py':raise ValueError('Unexpected controlled worker')
        command[1]=str(ROOT/'scripts/controlled_runtime_recovery_v9.py')
    elif spec['harness']=='dsh':
        if Path(command[1]).name not in ('dsh_inline_bc_worker_v7.py','dsh_baseline_inline_worker_v8.py'):raise ValueError('Unexpected DSH worker')
        command[1]=str(ROOT/'scripts/dsh_readonly_recovery_worker_v9.py')
    return command,result,timeout


if __name__=='__main__':
    with patch.object(base,'native_command',native_command):base.main()
