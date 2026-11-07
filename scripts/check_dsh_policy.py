#!/usr/bin/env python3
"""Boot both research policies against a local synthetic API; no paid requests."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import threading
import time
from lab import ROOT, command, environment


class Fixture(BaseHTTPRequestHandler):
    requests = 0

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        Fixture.requests += 1
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        base = {'id': 'local-fixture', 'object': 'chat.completion.chunk', 'created': 1,
                'model': 'fixture'}
        chunks = [dict(base, choices=[{'index': 0, 'delta': {'role': 'assistant', 'content': 'POLICY-OK'}, 'finish_reason': None}]),
                  dict(base, choices=[{'index': 0, 'delta': {}, 'finish_reason': 'stop'}],
                       usage={'prompt_tokens': 10, 'completion_tokens': 3, 'total_tokens': 13,
                              'prompt_tokens_details': {'cached_tokens': 0}})]
        for chunk in chunks:
            self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n')


def main():
    root = ROOT / 'outputs/preflight' / ('policy-boot-' + str(time.time_ns()))
    root.mkdir(parents=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for strategy in ['none', 'summarize', 'sliding_window_native', 'discard', 'visual_native']:
            out = root / strategy
            workspace = out / 'workspace'
            workspace.mkdir(parents=True)
            env, _ = environment(ROOT, 'dsh')
            env.update(TOKENHUB_BASE_URL=f'http://127.0.0.1:{server.server_port}/v1',
                       TOKENHUB_API_KEY='synthetic-fixture', ACL_STRATEGY=strategy,
                       ACL_WORKSPACE=str(workspace), DSH_HOME=str(out / 'dsh-home'))
            overlay = out / 'research.patch.yml'
            overlay.write_text((ROOT / 'configs/research.dsh.patch.yml').read_text().replace(
                '"@ACL_DSH_CONTEXT_PLUGIN@"', json.dumps(str(ROOT / 'plugins/dsh-context/index.mjs'))))
            inputs = out / 'input.json'
            inputs.write_text(json.dumps({'question_id': 'fixture', 'images': []}))
            patch = out / 'observer.json'
            patch.write_text(json.dumps([{'insert': [{'id': 'evaluation',
                'name': str(ROOT / 'plugins/dsh-evaluation/index.mjs'), 'config': {
                    'inputFile': str(inputs), 'metricsDir': str(workspace / 'metrics'),
                    'maxSteps': 2, 'expectedStrategy': strategy, 'allowedTools': []}}]}]))
            cmd = command(ROOT, 'dsh', 'Return POLICY-OK', env)
            cmd[cmd.index(str(ROOT / '.state/dsh-research.patch.yml'))] = str(overlay)
            cmd[-1:] = ['--patch', str(patch), '--json', '--approval-policy', 'never', 'Return POLICY-OK']
            result = subprocess.run(cmd, cwd=workspace, env=env, capture_output=True, text=True, timeout=90)
            (out / 'stdout.jsonl').write_text(result.stdout)
            (out / 'stderr.log').write_text(result.stderr)
            policy = workspace / 'metrics/policy.jsonl'
            assert result.returncode == 0 and policy.exists(), f'Policy boot failed: {out}'
            assert 'POLICY-OK' in result.stdout, f'No fixture answer: {out}'
            assert all(json.loads(line)['strategy'] == strategy for line in policy.read_text().splitlines())
        record = {'passed': True, 'local_fixture_requests': Fixture.requests, 'paid_requests': 0}
        (root / 'result.json').write_text(json.dumps(record, indent=2))
        print(json.dumps({'artifacts': str(root), **record}))
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
