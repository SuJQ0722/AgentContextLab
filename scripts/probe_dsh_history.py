#!/usr/bin/env python3
"""Admit rendered recall-probe images through native DSH, without helper tools."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from lab import ROOT, environment, command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-dir', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    source = args.probe_dir.resolve()
    if not args.live:
        print(json.dumps({'source': str(source), 'live': False}))
        return
    expected = json.loads((source / 'results.json').read_text())['expected']
    out = source / 'native-dsh'
    if out.exists():
        raise SystemExit('Native probe attempt already exists; inspect before retrying.')
    workspace = out / 'workspace'
    workspace.mkdir(parents=True)
    env, cfg = environment(ROOT, 'dsh')
    env.update(DSH_HOME=str(out / 'dsh-home'), ACL_WORKSPACE=str(workspace))
    patch = out / 'observer.patch.json'
    patch.write_text(json.dumps([{'insert': [{'id': 'acl-evaluation',
        'name': str(ROOT / 'plugins/dsh-evaluation/index.mjs'), 'config': {
            'inputFile': str(source / 'native-input.json'), 'metricsDir': str(out / 'metrics'),
            'maxSteps': 2, 'allowedTools': []}}]}]))
    prompt = (source / 'question.txt').read_text() + '\nAnswer directly from the attached images; no tools are available.'
    cmd = command(ROOT, 'dsh', prompt, env)
    cmd[-1:] = ['--patch', str(patch), '--json', '--approval-policy', 'never', prompt]
    start = time.monotonic()
    timed_out = False
    with (out / 'stdout.jsonl').open('w') as stdout, (out / 'stderr.log').open('w') as stderr:
        process = subprocess.Popen(cmd, cwd=workspace, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            process.wait(timeout=240)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    events = []
    for line in (out / 'stdout.jsonl').read_text().splitlines():
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                events.append(event)
        except ValueError:
            pass
    final = next((event for event in reversed(events) if event.get('type') == 'final'), {})
    answer = final.get('text') or ''
    try:
        fields = json.loads(answer[answer.index('{'):answer.rindex('}') + 1])
    except (ValueError, json.JSONDecodeError):
        fields = {}
    record = {'synthetic_probe': True, 'model': cfg['model'], 'exit_code': process.returncode,
              'timeout': timed_out, 'client_cli_seconds': time.monotonic() - start,
              'correct_fields': sum(fields.get(k) == v for k, v in expected.items()),
              'total_fields': len(expected), 'final': final}
    (out / 'result.json').write_text(json.dumps(record, indent=2))
    print(json.dumps(record))


if __name__ == '__main__':
    main()
