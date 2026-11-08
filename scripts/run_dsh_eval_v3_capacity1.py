#!/usr/bin/env python3
"""Capacity1 DSH entry: explicit 64 MiB inline image cap; native offload disabled.

Parent protocol/config remain v3; runtime lineage separately records this change.
"""
import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
import urllib.request
from lab import ROOT, environment, command
from local_web import configure_web
from lab import python_for
from dsh_image_preservation_capacity1 import preservation_patches, IMAGE_PRESERVATION_VERSION, runtime_record
from review_execution import enforce, enforce_resolved_web
from native_image_origins import write_origin_map
from shared_context_policy import policy_config

TOOLS = ['web_search', 'web_extract', 'image_search', 'image_crop', 'image_zoom_in']

STRATEGIES = ['none', 'discard', 'summarize', 'sliding_window_native', 'visual_native']


def stage_images(row, workspace):
    value = row.get('image') or []
    images = value if isinstance(value, list) else [value]
    staged = []
    for index, source in enumerate(images):
        path = workspace / f'input_image_{index}'
        if source.startswith('https://'):
            with urllib.request.urlopen(source, timeout=45) as stream:
                data = stream.read(25 * 1024 * 1024 + 1)
                media_type = stream.headers.get_content_type()
            if len(data) > 25 * 1024 * 1024:
                raise ValueError('Input image exceeds the 25 MiB admission cap')
        else:
            data = Path(source).read_bytes()
            media_type = mimetypes.guess_type(source)[0]
        if media_type not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif'):
            raise ValueError(f'Unsupported image type: {media_type}')
        path.write_bytes(data)
        staged.append({'path': str(path), 'media_type': media_type,
                       'sha256': hashlib.sha256(data).hexdigest()})
    return staged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    # The repaired five-tool protocol is validated only for BC-100. Do not
    # expose the legacy data-task branch's filesystem/shell tools by selecting
    # another dataset; controlled data protocols need separate review first.
    parser.add_argument('--dataset', required=True, choices=['bc100'])
    parser.add_argument('--strategies', nargs='+', choices=STRATEGIES, required=True)
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--timeout', type=int, default=1200)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--offline-fixture', action='store_true')
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/experiment.v3.review.json')
    parser.add_argument('--question-id')
    parser.add_argument('--cohort-file',type=Path,help='Explicit campaign-frozen cohort; requires --cohort-sha256')
    parser.add_argument('--cohort-sha256',help='Expected SHA256 of explicit frozen cohort')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('--web-prevalidated', action='store_true', help='Coordinator already checked frozen web configuration')
    parser.add_argument('--permission-mode', choices=['workspace-write', 'danger-full-access'], default='workspace-write')
    args = parser.parse_args()
    args.config = args.config.resolve()
    if args.output_root is not None:
        args.output_root = args.output_root.resolve()
    if args.limit < 1 or args.timeout < 1:
        parser.error('limit and timeout must be positive')
    cfg = json.loads(args.config.read_text())
    if cfg.get('execution_version') != 'hermes-parity-v3':
        raise ValueError('Use a separately versioned repaired configuration')
    manifest_name = 'bc100-manifest.json' if args.dataset == 'bc100' else 'manifest.json'
    manifest = json.loads((ROOT / 'outputs/cohorts' / manifest_name).read_text())
    dataset = manifest['datasets'][args.dataset]
    if bool(args.cohort_file)!=bool(args.cohort_sha256):
        raise ValueError('Explicit cohort file and SHA256 must be provided together')
    if args.cohort_file:
        dataset={**dataset,'cohort_path':str(args.cohort_file.resolve()),'cohort_sha256':args.cohort_sha256,
                 'dataset_sha256':None,'source':'explicit frozen campaign cohort; full upstream dataset hash not asserted'}
    raw = Path(dataset['cohort_path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != dataset['cohort_sha256']:
        raise ValueError('Frozen cohort changed')
    rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()][:args.limit]
    if args.question_id:
        rows = [row for row in rows if row['id'] == args.question_id]
        if len(rows) != 1: raise SystemExit('Question ID not present exactly once in frozen cohort')
    print(json.dumps({'dataset': args.dataset, 'questions': len(rows), 'strategies': args.strategies,
                      'runs': len(rows) * len(args.strategies), 'live': args.live, 'tools': TOOLS, 'execution_version': 'hermes-parity-v3'}), flush=True)
    if not args.live:
        return
    if args.dataset not in ('agenticdatabench', 'bc100'):
        raise SystemExit('This runner currently validates only BC-100 and AgenticDataBench.')
    # Fail before any paid request when native command execution is unavailable.
    runtime_env, _ = environment(ROOT, 'dsh', args.config)
    if args.output_root is None:
        raise ValueError('Repaired runs require an explicit versioned output root')
    enforce(cfg,runtime_env,args.output_root,offline_fixture=args.offline_fixture)
    if args.dataset == 'bc100':
        configure_web(ROOT, runtime_env, args.config)
        enforce_resolved_web(runtime_env, offline_fixture=args.offline_fixture)
        if not args.web_prevalidated:
            raise ValueError('Require a fresh same-handler web readiness check before reviewed dispatch')
    probe = shutil.which('bwrap', path=runtime_env['PATH'])
    if args.dataset == 'agenticdatabench' and args.permission_mode == 'workspace-write' and (not probe or subprocess.run([
        probe,
        '--ro-bind', '/', '/', '--dev', '/dev', '--unshare-pid', '--proc', '/proc',
        '--die-with-parent', '--', 'true'], capture_output=True).returncode):
        raise SystemExit('Native process sandbox unavailable; live data tasks are blocked.')
    source = ROOT.parent / 'databench/sources/AgenticDataBench/datasets'
    for row in rows:
        qid = str(row['id'])
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', qid):
            raise ValueError('Unsafe question ID')
        for strategy in args.strategies:
            run_dir = (args.output_root or ROOT / 'outputs/pilot' / args.dataset) / strategy / qid
            result_path = run_dir / 'result.json'
            if result_path.exists():
                # Do not silently repeat paid attempts, including failed ones.
                old_manifest = json.loads((run_dir/'manifest.json').read_text())
                expected_config = hashlib.sha256(args.config.read_bytes()).hexdigest()
                if (old_manifest.get('repeat') != args.repeat or old_manifest.get('model') != cfg['model']
                        or old_manifest.get('config_sha256') != expected_config
                        or old_manifest.get('cohort_sha256') != dataset['cohort_sha256']):
                    raise SystemExit(f'Existing result has different or unverified inputs: {run_dir}; use a new output root.')
                print(f'Existing attempt: {result_path}', flush=True)
                continue
            if (run_dir / 'manifest.json').exists():
                raise SystemExit(f'Attempt already started without a result: {run_dir}; inspect before retrying.')
            run_dir.mkdir(parents=True, exist_ok=True)
            try:
                with (run_dir / 'attempt-started.json').open('x') as claim:
                    json.dump({'pid':os.getpid(),'repeat':args.repeat,'started_at':datetime.now(timezone.utc).isoformat()},claim)
            except FileExistsError:
                raise SystemExit(f'Attempt was already claimed: {run_dir}; preserve it and review before retrying.')
            workspace = run_dir / 'workspace'
            workspace.mkdir(parents=True, exist_ok=True)
            prompt = row['question']
            if args.dataset == 'agenticdatabench':
                domain = source / row['domain']
                for name in row['data_sources']:
                    file = domain / name
                    if not file.resolve().is_relative_to(domain.resolve()):
                        raise ValueError('Dataset path escapes its domain')
                    destination = workspace / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, destination)
                prompt += '\nWork only inside the current directory. Produce these files: ' + ', '.join(row['output_file_name'])
            images = stage_images(row, workspace)
            if images:
                prompt += '\n\nImage files available for crop/zoom:\n'+'\n'.join(image['path'] for image in images)
            input_file = run_dir / 'input.json'
            input_file.write_text(json.dumps({'question_id': qid, 'images': images}))
            env, _ = environment(ROOT, 'dsh', args.config)
            env.update(ACL_STRATEGY=strategy, ACL_WORKSPACE=str(workspace), DSH_HOME=str(run_dir / 'dsh-home'),
                       HERMES_IMAGE_ROOT=str(workspace),HERMES_IMAGE_CACHE=str(workspace/'image-cache'))
            env['ACL_IMAGE_ORIGIN_MAP']=write_origin_map(row,images,run_dir/'input-origins.json')
            env['ACL_IMAGE_WIRE_AUDIT_DIR']=str(workspace/'metrics/wire')
            env['ACL_IMAGE_WIRE_EXPECTED']=str(workspace/'metrics/expected-wire.json')
            env['ACL_IMAGE_WIRE_APPLY_DETAILS']='1'
            env['NODE_OPTIONS']=(env.get('NODE_OPTIONS','')+' --import '+str(ROOT/'scripts/dsh_wire_image_guard_capacity1.mjs')).strip()
            web_metadata = configure_web(ROOT, env, args.config) if args.dataset == 'bc100' else None
            if web_metadata:
                enforce_resolved_web(env, offline_fixture=args.offline_fixture)
            overlay = run_dir / 'research.patch.yml'
            canonical_strategy={'visual_native':'visual','sliding_window_native':'sliding_window'}.get(strategy,strategy)
            template = json.dumps([
                {'id':'compaction-basic','disabled':True},
                {'id':'tool-result-pruner','disabled':True},
                {'insert':[{'id':'acl-hermes-shared-compaction',
                    'name':str(ROOT/'plugins/dsh-context/hermes-policy-v3.mjs'),
                    'config':{'strategy':strategy,'python':python_for(ROOT),
                        'sharedPolicy':str(ROOT/'scripts/shared_context_policy.py'),
                        'policyConfig':policy_config(canonical_strategy,cfg,workspace/'metrics/raw-canvases'),
                        'metricsDir':str(workspace/'metrics'),
                        'toolBridge':{'bridge':str(ROOT/'scripts/hermes_tool_bridge.py'),
                            'workspace':str(workspace),'metricsDir':str(workspace/'metrics'),
                            'timeoutMs':210000,'maxResultBytes':70*1024*1024}}}]}])
            # JSON is a YAML subset; the second layer mounts the run-scoped observer.
            observer = run_dir / 'evaluation.patch.json'
            plugins = [{'id': 'acl-evaluation',
                'name': str(ROOT / 'plugins/dsh-evaluation/index.mjs'),
                'config': {'inputFile': str(input_file), 'metricsDir': str(workspace / 'metrics'),
                           'expectedStrategy': strategy,
                           'maxSteps': cfg.get(args.dataset, cfg['pilot'])['max_rounds'], 'allowedTools': TOOLS if args.dataset=='bc100' else None}}]
            plugins.append({'id': 'acl-wire-expectations', 'name': str(ROOT/'scripts/dsh_wire_expectations.mjs'),
                            'config': {'expectedFile': env['ACL_IMAGE_WIRE_EXPECTED']}})
            patches = preservation_patches(env) + [
                {'id': 'session-title-llm', 'disabled': True},
                {'id': 'agent-instructions', 'disabled': True},
            ]
            if web_metadata:
                plugins.append({'id': 'acl-hermes-tools-v2', 'name': str(ROOT/'plugins/dsh-local-web/hermes-tools-v2.mjs'),
                                'config': {'python': python_for(ROOT), 'bridge': str(ROOT/'scripts/hermes_tool_bridge.py'),
                                           'workspace': str(workspace), 'metricsDir': str(workspace/'metrics'),
                                           'timeoutMs': 200000, 'maxResultBytes': 70*1024*1024}})
                patches.append({'id': 'tool-web', 'disabled': True})
            observer.write_text(json.dumps([{'insert': plugins}, *patches]))
            overlay.write_text(template)
            cmd = command(ROOT, 'dsh', prompt, env)
            cmd[cmd.index(str(ROOT / '.state/dsh-research.patch.yml'))] = str(overlay)
            cmd[-1:] = ['--patch', str(observer), '--json', '--permission-mode', args.permission_mode,
                        '--approval-policy', 'never', prompt]
            run_manifest = {'dataset': args.dataset, 'question_id': qid, 'strategy': strategy,
                'model': cfg['model'], 'seed': cfg['pilot']['seed'], 'repeat': args.repeat,
                'config_sha256':hashlib.sha256(args.config.read_bytes()).hexdigest(),
                'cohort_sha256':dataset['cohort_sha256'],
                'dataset_sha256': dataset['dataset_sha256'], 'images': images,
                'settings': cfg['pilot'], 'harness_lock': json.loads((ROOT / 'harness-lock.json').read_text())}
            run_manifest.update(web=web_metadata, benchmark_settings=cfg.get(args.dataset),
                                policy_verification_required=True,
                                visual_renderer=cfg.get('visual_renderer'),
                                timeout_seconds=args.timeout, allowed_tools=TOOLS if web_metadata else None,
                                execution_version='hermes-parity-v3', image_transport=IMAGE_PRESERVATION_VERSION, runtime_lineage=runtime_record(),
                                canonical_strategy=canonical_strategy, context_policy='actual Hermes ContextEngine',
                                post_compression_budget_enforcement='Hermes native policy; no DSH-only local-meter hard cap; controlled baseline is separate')
            (run_dir / 'manifest.json').write_text(json.dumps(run_manifest, indent=2))
            start = time.monotonic()
            process = subprocess.Popen(cmd, cwd=workspace, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, start_new_session=True)
            (run_dir / 'running.json').write_text(json.dumps({'pid': process.pid,
                'started_at': datetime.now(timezone.utc).isoformat(), 'timeout_seconds': args.timeout}))
            timed_out = False
            try:
                stdout, stderr = process.communicate(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    stdout, stderr = process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    stdout, stderr = process.communicate()
            elapsed = time.monotonic() - start
            for key, value in env.items():
                if len(value) >= 8 and re.search(r'KEY|SECRET|TOKEN|PASSWORD', key):
                    stdout, stderr = stdout.replace(value, '[REDACTED]'), stderr.replace(value, '[REDACTED]')
            (run_dir / 'stdout.jsonl').write_text(stdout)
            (run_dir / 'stderr.log').write_text(stderr)
            events = []
            for line in stdout.splitlines():
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        events.append(event)
                except json.JSONDecodeError:
                    pass
            final = next((event for event in reversed(events) if event.get('type') == 'final'), None)
            completed = process.returncode == 0 and final is not None and (final.get('reason') or {}).get('kind') == 'completed'
            reason = (final.get('reason') or {}).get('kind') if final else None
            step_limited = (workspace / 'metrics/limits.jsonl').exists()
            # A predeclared wall-clock cap is an experimental outcome, just
            # like an output/step cap. Preserve it and advance, without retry.
            budget_exhausted = timed_out or reason == 'max-tokens' or step_limited
            result = {'status': 'timeout' if timed_out else 'completed' if completed else 'failed',
                'exit_code': process.returncode, 'end_to_end_seconds': elapsed,
                'final': final, 'score': None, 'evaluation_status': 'not_judged',
                'failure_category': 'timeout' if timed_out else 'output_limit' if reason == 'max-tokens' else
                    'step_limit' if step_limited else None if completed else 'execution_error',
                'finished_at': datetime.now(timezone.utc).isoformat()}
            result_path.write_text(json.dumps(result, indent=2))
            print(json.dumps({'question_id': qid, 'strategy': strategy, 'status': result['status']}), flush=True)
            if not completed and not budget_exhausted:
                raise SystemExit('Pilot stopped on failed execution; diagnose before spending on remaining runs.')


if __name__ == '__main__':
    main()
