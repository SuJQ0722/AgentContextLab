"""Native DSH text baselines; no visual-only policy override or upstream changes."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
import run_dsh_eval_v3 as native
from dsh_inline_bc_worker_v7 import adapt_patches
from dsh_inline_bc_worker_v4 import separate_prompt
from dsh_inline_bc_worker_v6 import configure_proxy
from lab import ROOT
from one_hour_timeout_retry_v1 import VERSION
from inline_route_contract_v2 import validate_routes


def main():
    p=argparse.ArgumentParser(add_help=False);p.add_argument('--config',type=Path,required=True);p.add_argument('--timeout',type=int,required=True)
    args,_=p.parse_known_args();cfg=json.loads(args.config.read_text())
    if args.timeout!=3600 or cfg.get('one_hour_retry_version')!=VERSION:raise ValueError('One-hour baseline config required')
    validate_routes(cfg,cfg)
    original_command,original_preservation=native.command,native.preservation_patches
    def command(root,harness,prompt,env):
        if env.get('ACL_STRATEGY') not in ('none','discard','summarize','sliding_window_native','sliding_window'):
            raise ValueError('Only native text baselines authorized')
        metrics=Path(env['ACL_WORKSPACE'])/'metrics';metrics.mkdir(parents=True,exist_ok=True)
        env.update(ACL_INLINE_DSH_RETAIN_IMAGES='10',ACL_INLINE_DSH_TIMEOUT_SECONDS='3600',
                   ACL_INLINE_DSH_LEDGER=str(metrics/'inline-images-wire-dsh-v1.jsonl'),
                   ACL_INLINE_DSH_JOB_ID=str(Path(env['ACL_WORKSPACE']).parent),
                   ACL_BOUNDED_PYTHON=env['ACL_PYTHON'],ACL_BOUNDED_CANVAS_ROOT=str(metrics/'raw-canvases'))
        env['NODE_OPTIONS']='--import '+str(ROOT/'scripts/dsh_inline_wire_v5.mjs')+' '+env.get('NODE_OPTIONS','')
        return separate_prompt(original_command(root,harness,prompt,env))
    def preservation(env):
        configure_proxy(env,cfg['gateway_proxy'])
        return adapt_patches(original_preservation(env),timeout_seconds=3600)
    with patch.object(native,'command',command),patch.object(native,'preservation_patches',preservation):native.main()


if __name__=='__main__':main()
