#!/usr/bin/env python3
"""Credential-isolated launchers for the pinned research harnesses."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def runtime_path(root):
    """Prefer the isolated research runtime without replacing system Node."""
    bins = [root / '.tools/node-v24.11.0-linux-x64/bin',
            root / '.tools/pnpm/node_modules/.bin',
            root / '.tools/poppler/usr/bin',
            root / '.tools/bubblewrap/usr/bin']
    return os.pathsep.join([str(p) for p in bins if p.is_dir()] + [os.environ.get('PATH', '')])


def read_env(path):
    """Read ordinary dotenv assignments without shell evaluation."""
    result = {}
    if not path.exists():
        return result
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith('export '):
            line = line[7:]
        key, sep, value = line.partition('=')
        if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key.strip()):
            continue
        try:
            words = shlex.split(value, comments=True)
        except ValueError:
            continue
        result[key.strip()] = ' '.join(words)
    return result


def environment(root, harness, config_path=None):
    common = read_env(root / '.env')
    child = root / ('hermes-agent' if harness == 'hermes' else 'deepseekHarness')
    env = {**read_env(child / '.env'), **common, **os.environ}
    env['PATH'] = runtime_path(root)
    poppler_lib = root / '.tools/poppler/usr/lib/x86_64-linux-gnu'
    if poppler_lib.is_dir():
        env['LD_LIBRARY_PATH'] = os.pathsep.join([str(poppler_lib), env.get('LD_LIBRARY_PATH', '')]).rstrip(os.pathsep)
    # Explicit shared gateway settings win over legacy harness-specific keys.
    for key in ('TOKENHUB_BASE_URL', 'TOKENHUB_API_KEY'):
        env[key] = os.environ.get(key, common.get(key, ''))
    cfg = json.loads(Path(config_path or root / 'configs/experiment.json').read_text())
    env.update(ACL_MODEL=cfg['model'], ACL_INPUT_MODALITIES=json.dumps(cfg['input_modalities']),
               ACL_CONTEXT_WINDOW=str(cfg['context_window']),
               ACL_MAX_OUTPUT_TOKENS=str(cfg['max_output_tokens']),
               ACL_ROOT=str(root), ACL_PYTHON=python_for(root),
               ACL_COMPRESSION_TRIGGER=str(cfg.get('pilot', {}).get('compression_trigger_tokens', 32768)),
               ACL_VISUAL_FONT_SIZE=str(cfg.get('visual_renderer', {}).get('font_size', 8)),
               ACL_VISUAL_HISTORY_SCALE=str(cfg.get('visual_renderer', {}).get('history_scale', .75)),
               ACL_POST_COMPRESSION_BUDGET=str(cfg.get('pilot', {}).get('post_compression_budget_tokens', 16384)),
               ACL_WORKSPACE=str(root / 'outputs/workspaces' / harness))
    if harness == 'hermes':
        env.update(OPENAI_API_KEY=env['TOKENHUB_API_KEY'], HERMES_API_KEY=env['TOKENHUB_API_KEY'],
                   OPENAI_BASE_URL=env['TOKENHUB_BASE_URL'], HERMES_BASE_URL=env['TOKENHUB_BASE_URL'],
                   HERMES_HOME=str(root / '.state/hermes'))
        env['PYTHONPATH'] = os.pathsep.join([str(child), str(child / 'Browsecomp_eval')])
    else:
        env['DSH_HOME'] = str(root / '.state/dsh')
    return env, cfg


def python_for(root):
    for p in (root / '.venv/bin/python', root / 'hermes-agent/.venv/bin/python'):
        if p.exists():
            return str(p)
    return sys.executable


def command(root, harness, prompt, env):
    if harness == 'hermes':
        return [python_for(root), '-m', 'hermes_cli.main', 'chat', '--query', prompt,
                '--model', env['ACL_MODEL'], '--provider', 'custom']
    # Invoke the built dsh CLI entry directly so the task's cwd is preserved.
    # pnpm --dir changes cwd to the harness checkout before starting the CLI.
    cmd = ['node', str(root / 'deepseekHarness/apps/cli/lib/bin.js'), '--profile', 'headless',
           '--patch', str(root / 'configs/tokenhub.dsh.patch.yml')]
    if env.get('ACL_STRATEGY'):
        cmd.extend(['--patch', str(root / '.state/dsh-research.patch.yml')])
    return cmd + [prompt]


def doctor(root):
    errors = []
    for name in ('hermes-agent', 'deepseekHarness'):
        if not (root / name / 'AGENTS.md').exists():
            errors.append(f'{name} is missing; initialize the pinned submodule')
    node = shutil.which('node', path=runtime_path(root))
    version = subprocess.check_output([node, '--version'], text=True).strip() if node else 'missing'
    numbers = tuple(map(int, re.findall(r'\d+', version)[:2]))
    if numbers < (24, 9):
        errors.append(f'DSH requires Node >=24.9; found {version}')
    if not shutil.which('pnpm', path=runtime_path(root)):
        errors.append('pnpm is missing; use the version in deepseekHarness/package.json')
    if not (root / 'deepseekHarness/apps/cli/lib/bin.js').exists():
        errors.append('DSH CLI artifacts are missing; run bash scripts/setup.sh dsh')
    env, cfg = environment(root, 'hermes')
    if not env['TOKENHUB_API_KEY']:
        errors.append('TOKENHUB_API_KEY is not configured in root .env')
    if not env['TOKENHUB_BASE_URL'] or 'your-tokenhub-host' in env['TOKENHUB_BASE_URL']:
        errors.append('TOKENHUB_BASE_URL is not configured in root .env')
    print(json.dumps({'model': cfg['model'], 'node': version, 'issues': errors}, indent=2))
    return int(bool(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('doctor')
    run = sub.add_parser('run')
    run.add_argument('harness', choices=['hermes', 'dsh'])
    run.add_argument('--prompt', required=True)
    run.add_argument('--dry-run', action='store_true')
    run.add_argument('--strategy', choices=['none', 'discard', 'summarize', 'summarize_native', 'sliding_window_native', 'visual_native'])
    args = parser.parse_args()
    if args.action == 'doctor':
        return doctor(ROOT)
    env, cfg = environment(ROOT, args.harness)
    if args.strategy:
        if args.harness != 'dsh':
            parser.error('For Hermes strategies use scripts/eval_hermes.py -- --context-engine')
        env['ACL_STRATEGY'] = args.strategy
    cmd = command(ROOT, args.harness, args.prompt, env)
    if args.dry_run:
        print(json.dumps({'harness': args.harness, 'command': cmd,
                          'model': cfg['model'], 'credential_configured': bool(env['TOKENHUB_API_KEY'])}, indent=2))
        return 0
    if not env['TOKENHUB_API_KEY'] or not env['TOKENHUB_BASE_URL']:
        parser.error('Configure TOKENHUB_BASE_URL and TOKENHUB_API_KEY in root .env first')
    if args.harness == 'dsh' and doctor(ROOT):
        return 1
    if args.harness == 'dsh' and args.strategy:
        overlay = ROOT / '.state/dsh-research.patch.yml'
        overlay.parent.mkdir(parents=True, exist_ok=True)
        overlay.write_text((ROOT / 'configs/research.dsh.patch.yml').read_text().replace(
            '"@ACL_DSH_CONTEXT_PLUGIN@"', json.dumps(str(ROOT / 'plugins/dsh-context/index.mjs'))))
    Path(env['ACL_WORKSPACE']).mkdir(parents=True, exist_ok=True)
    if args.harness == 'hermes':
        home = Path(env['HERMES_HOME']); home.mkdir(parents=True, exist_ok=True)
        path = home / 'config.yaml'
        if not path.exists():
            path.write_text(json.dumps({'model': {'provider': 'custom', 'default': cfg['model'],
                'base_url': env['TOKENHUB_BASE_URL'], 'context_length': cfg['context_window']}}))
    return subprocess.call(cmd, cwd=env['ACL_WORKSPACE'], env=env)


if __name__ == '__main__':
    raise SystemExit(main())
