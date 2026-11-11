"""Unchanged text baselines with audited four-route transport and one-hour deadline."""
import argparse
import json
from pathlib import Path
import hermes_bc_worker_v3 as bc
import hermes_mmbc_worker_v1 as mmbc
from lab import ROOT, environment
from one_hour_timeout_retry_v1 import validate
from inline_route_contract_v2 import validate_routes
from visual_transport_runtime_v4 import install
from inline_visual_transport_v1 import install as inline


def main():
    p = argparse.ArgumentParser(add_help=False);p.add_argument('--spec',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args,_=p.parse_known_args();job=json.loads(args.spec.read_text());env,cfg=environment(ROOT,'hermes',job['config_path'])
    validate(job,cfg);validate_routes(job,cfg)
    if job['strategy'] not in ('none','discard','summarize','sliding_window'):
        raise ValueError('Only native text-management baselines use this entry')
    rt=install(cfg['transport_runtime_policy'],args.out/'metrics',approved_base_url=env['TOKENHUB_BASE_URL'],
               route_policy=cfg['model_route_policy'],worker_key=job['job_id'],deadline_seconds=3600,gateway_proxy=cfg['gateway_proxy'])
    images=inline(args.out/'metrics',rendered_registry=set(),approved_base_url=env['TOKENHUB_BASE_URL'])
    try:(mmbc if job.get('experiment_kind')=='mmbc' else bc).main()
    finally:images['uninstall']();rt['uninstall']()


if __name__=='__main__':main()
