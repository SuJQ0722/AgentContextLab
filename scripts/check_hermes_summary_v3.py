#!/usr/bin/env python3
"""Real native Hermes summary -> auxiliary helper -> SDK -> localhost fixture."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from lab import ROOT, environment, python_for


def guard_worker():
    import asyncio
    import httpx
    import requests
    import os
    sys.path.insert(0, str(ROOT / 'hermes-agent'))
    from openai import OpenAI, AsyncOpenAI
    from agent import auxiliary_client
    from hermes_bc_worker_v3 import ReviewedTextRecorder
    spec = json.loads(Path(sys.argv[sys.argv.index('--spec') + 1]).read_text())
    out = Path(sys.argv[sys.argv.index('--out') + 1])
    recorder = ReviewedTextRecorder(out / 'metrics'); recorder.install()
    model = spec['model']; base = os.environ['TOKENHUB_BASE_URL']
    records = []
    def rejected(label, action):
        try:
            action()
        except RuntimeError:
            records.append(label)
        else:
            raise AssertionError('Guard did not reject ' + label)
    client = OpenAI(api_key='fixture-only', base_url=base, max_retries=0)
    rejected('sdk-wrong-model', lambda: client.chat.completions.create(model='unapproved', messages=[]))
    wrong = OpenAI(api_key='fixture-only', base_url=base + '/wrong', max_retries=0)
    rejected('sdk-wrong-route', lambda: wrong.chat.completions.create(model=model, messages=[]))
    rejected('uninstrumented-httpx', lambda: httpx.post(base + '/chat/completions', json={'model': model, 'messages': []}))
    rejected('uninstrumented-requests', lambda: requests.post(base + '/chat/completions', json={'model': model, 'messages': []}))
    rejected('wrong-aux-task', lambda: auxiliary_client.call_llm(task='vision', main_runtime={'model': model}, messages=[]))
    rejected('wrong-aux-model', lambda: auxiliary_client.call_llm(task='compression', main_runtime={'model': 'unapproved'}, messages=[]))
    for changed in ('model', 'endpoint'):
        def mutate(request, changed=changed):
            if changed == 'endpoint':
                request.url = httpx.URL(base + '/wrong/chat/completions')
            else:
                body = json.loads(request.content); body['model'] = 'unapproved'
                request._content = json.dumps(body).encode()
        hooked = OpenAI(api_key='fixture-only', base_url=base, max_retries=0,
                        http_client=httpx.Client(event_hooks={'request': [mutate]}))
        # SDK wraps transport errors; the guard evidence and server counters
        # independently prove that altered requests never reached the server.
        try:
            hooked.chat.completions.create(model=model, messages=[])
        except Exception:
            records.append('final-wire-' + changed)
        else:
            raise AssertionError('Mutated final request escaped the guard')
    async def async_call():
        c = AsyncOpenAI(api_key='fixture-only', base_url=base)
        await c.chat.completions.create(model=model, messages=[])
    rejected('async-inference', lambda: asyncio.run(async_call()))
    web = httpx.post(base.removesuffix('/v1') + '/search', json={'query': 'allowed web fixture'})
    assert web.status_code == 200
    blocked = [json.loads(line) for line in (out / 'metrics/route-guard.jsonl').read_text().splitlines()]
    assert len(blocked) >= 9 and any('HTTP body' in r['reason'] for r in blocked) and any('endpoint differs' in r['reason'] for r in blocked)
    (out / 'result.json').write_text(json.dumps({'passed': True, 'rejected_cases': records,
                                               'web_request_passed': True, 'guard_records': len(blocked)}, indent=2))


class Fixture(BaseHTTPRequestHandler):
    main_calls = 0
    summary_requests = []
    model = None

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/api/show':
            self.send_response(404); self.end_headers(); return
        if self.path == '/search':
            data = {'organic': [{'title': 'Offline archive', 'link': 'https://example.org/record',
                                 'snippet': 'Archival record includes catalog CEDAR and confirmed measurements. ' * 200}]}
        else:
            assert body['model'] == Fixture.model
            messages = body['messages']
            first = messages[0].get('content', '') if messages else ''
            summary = len(messages) == 1 and isinstance(first, str) and 'You are a summarization agent creating a context checkpoint.' in first
            if summary:
                Fixture.summary_requests.append(body)
                answer = {'role': 'assistant', 'content': 'OFFLINE SUMMARY CHECKPOINT: preserve the archival task and verified CEDAR evidence.'}
                reason = 'stop'; prompt = 200; completion = 20; cached = 50
            else:
                Fixture.main_calls += 1
                if any('OFFLINE SUMMARY CHECKPOINT' in str(m.get('content')) for m in messages):
                    answer = {'role': 'assistant', 'content': 'SUMMARY-NATIVE-LOOP-PASSED'}; reason = 'stop'
                else:
                    assert Fixture.main_calls <= 16, 'Expected a real native summary by this point'
                    answer = {'role': 'assistant', 'content': None, 'tool_calls': [{
                        'index': 0, 'id': f'fixture-{Fixture.main_calls}', 'type': 'function',
                        'function': {'name': 'web_search', 'arguments': json.dumps({'query': f'archive {Fixture.main_calls}', 'limit': 1})}}]}
                    reason = 'tool_calls'
                prompt = 40000; completion = 10; cached = 100
            data = {'id': 'offline-fixture', 'object': 'chat.completion', 'created': 1, 'model': body['model'],
                    'choices': [{'index': 0, 'message': answer, 'finish_reason': reason}],
                    'usage': {'prompt_tokens': prompt, 'completion_tokens': completion, 'total_tokens': prompt + completion,
                              'prompt_tokens_details': {'cached_tokens': cached}}}
        if body.get('stream'):
            data['object'] = 'chat.completion.chunk'
            data['choices'][0]['delta'] = data['choices'][0].pop('message')
            raw = ('data: ' + json.dumps(data) + '\n\ndata: [DONE]\n\n').encode(); kind = 'text/event-stream'
        else:
            raw = json.dumps(data).encode(); kind = 'application/json'
        self.send_response(200); self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)


def main():
    out = ROOT / 'outputs/preflight' / f'hermes-summary-v3-{time.time_ns()}'
    out.mkdir(parents=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env, cfg = environment(ROOT, 'hermes')
        url = f'http://127.0.0.1:{server.server_port}'
        env.update(TOKENHUB_BASE_URL=url + '/v1', TOKENHUB_API_KEY='offline-fixture',
                   NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1')
        cfg.update(execution_version='hermes-parity-v3', execution_approved=False)
        cfg['bc100_campaign']['max_rounds'] = 20
        cfg['web'].update(search_host='127.0.0.1', search_port=server.server_port, fetch_base_url=url)
        cfg['shared_policy'] = {'strategy_configs': {'summarize': {'protect_last_n': 3, 'summary_target_ratio': .1}}}
        Fixture.model = cfg['model']
        (out / 'experiment.json').write_text(json.dumps(cfg))
        spec = {'model': cfg['model'], 'strategy': 'summarize', 'job_id': 'offline-summary-v3',
                'question': 'Search the archival records until a checkpoint summary preserves the evidence, then finish.',
                'config_path': str(out / 'experiment.json')}
        (out / 'spec.json').write_text(json.dumps(spec))
        with (out / 'process.log').open('w') as log:
            completed = subprocess.run([python_for(ROOT), str(ROOT / 'scripts/hermes_bc_worker_v3.py'),
                                        '--spec', str(out / 'spec.json'), '--out', str(out / 'native'),
                                        '--live', '--offline-fixture'], cwd=ROOT, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, timeout=180)
        if completed.returncode:
            raise RuntimeError(f'Native summary worker failed; inspect {out}/process.log')
        result = json.loads((out / 'native/native-result.json').read_text())
        assert result['final']['text'] == 'SUMMARY-NATIVE-LOOP-PASSED', result
        calls = [json.loads(line) for line in (out / 'native/metrics/calls.jsonl').read_text().splitlines()]
        summaries = [call for call in calls if call['purpose'] == 'compaction']
        assert summaries and Fixture.summary_requests
        assert len(summaries) == len(Fixture.summary_requests)
        assert all(call['model'] == cfg['model'] and call['usage'] == {
            'inputTokens': 150, 'cacheReadTokens': 50, 'outputTokens': 20, 'totalTokens': 220} for call in summaries)
        prior_model_calls = Fixture.main_calls + len(Fixture.summary_requests)
        with (out / 'guard.log').open('w') as log:
            denied = subprocess.run([python_for(ROOT), str(Path(__file__).resolve()), '--guard-worker',
                                     '--spec', str(out / 'spec.json'), '--out', str(out / 'guard')],
                                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=60)
        if denied.returncode:
            raise RuntimeError(f'Route denial fixture failed; inspect {out}/guard.log')
        assert Fixture.main_calls + len(Fixture.summary_requests) == prior_model_calls
        denials = json.loads((out / 'guard/result.json').read_text())
        (out / 'actual-summary-requests.json').write_text(json.dumps(Fixture.summary_requests, indent=2))
        report = {'passed': True, 'paid_calls': 0, 'model_calls': Fixture.main_calls + len(Fixture.summary_requests),
                  'summary_calls': len(summaries), 'summary_route': 'actual Hermes auxiliary_client.call_llm -> SDK -> loopback',
                  'summary_usage_per_call': summaries[0]['usage'], 'same_model': True,
                  'final': result['final']['text'], 'denial_cases': denials,
                  'denied_requests_reached_server': 0}
        (out / 'result.json').write_text(json.dumps(report, indent=2))
        print(json.dumps({'passed': True, 'paid_calls': 0, 'artifact': str(out / 'result.json'), 'summary_calls': len(summaries)}))
    finally:
        server.shutdown()


if __name__ == '__main__':
    guard_worker() if '--guard-worker' in sys.argv else main()
