"""Explicit 200-turn/3-hour recovery entry; frozen harnesses remain unchanged."""
import argparse
import builtins
import json
import os
from pathlib import Path
import sys
from contextlib import ExitStack
from unittest.mock import patch

from lab import ROOT, environment
import mmbc_bounded_route_runtime_v1 as bounded

VERSION = 'supplement-timeout-200turn-3h-v24'
PROXY_INSTALL = bounded.proxy_runtime.install


def validate(spec, config):
    for row in (spec, config):
        if row.get('supplement_version') != VERSION:
            raise ValueError('Independent V24 authorization required')
        if type(row.get('max_rounds')) is not int or row['max_rounds'] != 200:
            raise ValueError('Exactly 200 agent turns required')
        if row.get('timeout_seconds') != 10800 or row.get('max_http_sends') != 3:
            raise ValueError('Three-hour/three-send policy required')
    if config.get('max_output_tokens') != 8192:
        raise ValueError('Output budget changed')
    for name in ('bc100', 'bc100_campaign', 'pilot'):
        if config[name]['max_rounds'] != 200 or config[name]['timeout_seconds'] != 10800:
            raise ValueError('Native budget differs')
    if config['transport_runtime_policy']['max_failed_sends'] != 3:
        raise ValueError('Physical request limit differs')


def install_runtime(policy, out, **kwargs):
    kwargs['deadline_seconds'] = 10800
    policy = {**policy, 'max_failed_sends': 3}
    with patch.object(bounded.proxy_runtime, 'install', PROXY_INSTALL):
        return bounded.install(policy, out, max_http_attempts=3, **kwargs)


def checked_init(original, out):
    def init(self, *args, **kwargs):
        if kwargs.get('max_iterations') != 200:
            raise ValueError('Actual Hermes constructor must receive 200')
        result = original(self, *args, **kwargs)
        if self.max_iterations != 200:
            raise ValueError('Actual Hermes turn limit differs')
        p = Path(out)/'metrics/turn-limit-v24.json'; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({'version': VERSION, 'actual_max_iterations': 200,
                                'timeout_seconds': 10800, 'max_http_sends': 3}))
        return result
    return init


def hermes(spec, cfg, out):
    old_import = builtins.__import__; restores = []
    def importing(name, globals=None, locals=None, fromlist=(), level=0):
        mod = old_import(name, globals, locals, fromlist, level)
        if name == 'run_agent' and 'AIAgent' in (fromlist or ()) and not restores:
            cls = mod.AIAgent; restores.append((cls, cls.__init__))
            cls.__init__ = checked_init(cls.__init__, out)
        return mod
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(builtins, '__import__', importing))
            if spec.get('scope') == 'controlled':
                import controlled_mmbc_source_v23 as worker
                import visual_transport_runtime_v4 as transport
                stack.enter_context(patch.object(transport, 'install', install_runtime))
                job = spec['controlled_job']
                worker.worker(Path(spec['campaign_root']), {}, job)
            elif spec['strategy'] == 'visual':
                import hermes_visual_inline_retry_worker_v4 as worker
                import hermes_canvas_budget_worker_v11 as budget
                import inline_visual_transport_v1 as transport
                stack.enter_context(patch.object(worker, 'runtime', install_runtime))
                # Preserve the selected source's image policy; do not migrate other arms.
                if cfg.get('native_image_policy') == 'core_recent10':
                    import hermes_core_recent_ten_worker_v23 as core
                    core.validate(spec, cfg)
                    stack.enter_context(patch.object(transport, 'transform', core.transform))
                    stack.enter_context(patch.object(transport, 'transport_version', lambda *a, **k: core.TRANSPORT_VERSION))
                    stack.enter_context(patch.object(worker, 'transport_version', lambda *a, **k: core.TRANSPORT_VERSION))
                else:
                    stack.enter_context(patch.object(transport, 'transform', budget.transform))
                worker.main()
            else:
                import hermes_baseline_inline_worker_v8 as worker
                stack.enter_context(patch.object(worker, 'validate', validate))
                stack.enter_context(patch.object(worker, 'install', install_runtime))
                worker.main()
    finally:
        for cls, original in restores: cls.__init__ = original


def dsh(spec, cfg, out):
    import run_dsh_eval_v3 as native
    import dsh_inline_bc_worker_v6 as buffered
    from dsh_inline_bc_worker_v4 import separate_prompt
    from inline_route_contract_v2 import validate_routes
    validate_routes(cfg, cfg)
    original_command = native.command
    original_preservation = native.preservation_patches
    def verify_timeout(value):
        if type(value) is not int or value != 10800: raise ValueError('Three hours required')
    def command(root, harness, prompt, env):
        metrics = Path(env['ACL_WORKSPACE'])/'metrics'; metrics.mkdir(parents=True, exist_ok=True)
        wire = str(ROOT/'scripts/dsh_wire_v24.mjs')
        if spec['strategy'] == 'visual':
            old = str(ROOT/'scripts/dsh_hosted_wire_v4.mjs')
            if env.get('NODE_OPTIONS', '').count(old) != 1: raise ValueError('Unexpected DSH wire')
            env['NODE_OPTIONS'] = env['NODE_OPTIONS'].replace(old, wire)
        else:
            env.update(ACL_INLINE_DSH_RETAIN_IMAGES='10', ACL_INLINE_DSH_TIMEOUT_SECONDS='10800',
                       ACL_INLINE_DSH_LEDGER=str(metrics/'inline-images-wire-dsh-v1.jsonl'),
                       ACL_INLINE_DSH_JOB_ID=spec['job_id'], ACL_BOUNDED_PYTHON=env['ACL_PYTHON'],
                       ACL_BOUNDED_CANVAS_ROOT=str(metrics/'raw-canvases'))
            env['NODE_OPTIONS'] = '--import '+wire+' '+env.get('NODE_OPTIONS', '')
        argv = original_command(root, harness, prompt, env)
        observer=Path(env['ACL_WORKSPACE']).parent/'evaluation.patch.json'
        patches = json.loads(observer.read_text())
        observers=[p for row in patches for p in row.get('insert',[]) if p.get('id')=='acl-wire-expectations']
        if len(observers)!=1 or observers[0]['name']!=str(ROOT/'scripts/dsh_wire_expectations.mjs'):
            raise ValueError('Pinned wire observer differs')
        observers[0]['name']=str(ROOT/'scripts/dsh_wire_expectations_v9.mjs')
        observer.write_text(json.dumps(patches))
        env['NODE_OPTIONS']+=' --import '+str(ROOT/'scripts/dsh_fetch_diagnostics_v11.mjs')
        limits = [p['config']['maxSteps'] for row in patches for p in row.get('insert', []) if p.get('id') == 'acl-evaluation']
        if limits != [200]: raise ValueError('Actual DSH maxSteps differs')
        (metrics/'turn-limit-v24.json').write_text(json.dumps({'version': VERSION, 'actual_maxSteps': 200,
            'timeout_seconds': 10800, 'max_http_sends': 3, 'image_policy_preserved': True}))
        return argv
    def preservation(env):
        buffered.configure_proxy(env, cfg['gateway_proxy'])
        return buffered.adapt_patches(original_preservation(env), timeout_seconds=10800)
    strategy = {'visual': 'visual_native', 'sliding_window': 'sliding_window_native'}.get(spec['strategy'], spec['strategy'])
    argv = [str(ROOT/'scripts/run_dsh_eval_v3.py'), '--dataset', 'bc100', '--strategies', strategy,
            '--question-id', spec['question_id'], '--repeat', str(spec['repeat']), '--limit', '100',
            '--timeout', '10800', '--output-root', str(out), '--config', spec['config_path'],
            '--cohort-file', spec['native_cohort_path'], '--cohort-sha256', spec['native_cohort_sha256'],
            '--web-prevalidated', '--live']
    with ExitStack() as stack:
        stack.enter_context(patch.object(sys, 'argv', argv))
        stack.enter_context(patch.object(native, 'command', command))
        stack.enter_context(patch.object(buffered, 'validate_timeout', verify_timeout))
        if spec['strategy'] == 'visual':
            stack.enter_context(patch.object(buffered, 'VERSION', cfg['dsh_buffered_watchdog_version']))
            buffered.main()
        else:
            stack.enter_context(patch.object(native, 'preservation_patches', preservation))
            original_popen=native.subprocess.Popen
            stack.enter_context(patch.object(native.subprocess,'Popen',lambda cmd,*a,**kw:original_popen(separate_prompt(cmd),*a,**kw)))
            native.main()


def main():
    p = argparse.ArgumentParser(); p.add_argument('--spec', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True); p.add_argument('--live', action='store_true')
    a = p.parse_args(); spec = json.loads(a.spec.read_text()); cfg = json.loads(Path(spec['config_path']).read_text())
    validate(spec, cfg)
    if not a.live:
        print(json.dumps({'version': VERSION, 'job_id': spec['job_id'], 'model_calls': 0})); return
    (a.out/'metrics').mkdir(parents=True, exist_ok=True)
    (a.out/'metrics/protocol-v24.json').write_text(json.dumps({'version': VERSION, 'max_rounds': 200,
         'timeout_seconds': 10800, 'max_http_sends': 3, 'scope': spec['scope'], 'source_protocol_retained': True}))
    if spec['harness'] == 'hermes': hermes(spec, cfg, a.out)
    elif spec['harness'] == 'dsh': dsh(spec, cfg, a.out)
    else: raise ValueError('Unknown harness')


if __name__ == '__main__': main()
