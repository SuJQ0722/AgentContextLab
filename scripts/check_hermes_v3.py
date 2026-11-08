#!/usr/bin/env python3
"""Actual repaired Hermes loop, real crop/zoom/compression, localhost model only."""
import base64
import argparse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import subprocess
import threading
import time
from PIL import Image, ImageDraw
from lab import ROOT, environment, python_for
from hermes_bc_worker_v3 import TOOLS


class Fixture(BaseHTTPRequestHandler):
    calls = []
    native_tools = []
    source = None
    canary = None
    denied_file = None
    check_denied_tools = False
    denied_names = ["read_file", "terminal", "read", "bash"]
    denied_observed = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/api/show':
            self.send_response(404); self.end_headers(); return
        if self.path == '/search':
            data = {'organic': [{'title': 'Local evidence', 'link': 'https://example.org/evidence',
                    'snippet': '\n'.join(f'Evidence row {i}: record {i+100}, blue circle and green triangle.' for i in range(100))}]}
        elif self.path == '/fetch':
            data = {'status': 'success', 'content': 'Original archival source with a blue circle and green triangle.'}
        else:
            assert Fixture.canary not in json.dumps(body), 'Local answer leaked into model input'
            Fixture.calls.append(body)
            if Fixture.check_denied_tools and len(Fixture.calls) == 2:
                rejected = {m.get('tool_call_id'): str(m.get('content')) for m in body['messages'] if m.get('role') == 'tool'}
                for name in Fixture.denied_names:
                    error = rejected.get('denied-' + name, '')
                    assert 'does not exist' in error.lower(), (name, error)
                    Fixture.denied_observed.append(name)
            assert {t['function']['name'] for t in body.get('tools', [])} == set(TOOLS)
            images = [p for m in body['messages'] for p in m.get('content', [])
                      if isinstance(p, dict) and p.get('type') == 'image_url']
            widths = [Image.open(io.BytesIO(base64.b64decode(p['image_url']['url'].split(',')[1]))).width for p in images]
            if Fixture.check_denied_tools and len(Fixture.calls) == 1:
                message = {'role': 'assistant', 'content': None, 'tool_calls': [
                    {'index': i, 'id': 'denied-' + name, 'type': 'function', 'function': {
                        'name': name, 'arguments': json.dumps({'path': str(Fixture.denied_file), 'file_path': str(Fixture.denied_file), 'command': 'cat ' + str(Fixture.denied_file)})}}
                    for i, name in enumerate(Fixture.denied_names)]}
                reason = 'tool_calls'
            elif any(width >= 1000 for width in widths):
                message = {'role': 'assistant', 'content': 'V3-CANVAS-TOOLS-OK'}; reason = 'stop'
            else:
                n = len(Fixture.calls) - int(Fixture.check_denied_tools)
                assert n <= 12, 'Native compression did not produce a canvas'
                tool, args = (
                    ('image_crop', {'image_path': str(Fixture.source), 'bbox': [100, 10, 195, 100]}) if n == 1 else
                    ('image_zoom_in', {'image_path': str(Fixture.source), 'bbox_2d': [200, 10, 295, 100]}) if n == 2 else
                    ('web_search', {'query': f'fixture evidence {n}', 'limit': 1}))
                Fixture.native_tools.append(tool)
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{'index': 0, 'id': f't{n}',
                            'type': 'function', 'function': {'name': tool, 'arguments': json.dumps(args)}}]}
                reason = 'tool_calls'
            data = {'id': 'fixture', 'object': 'chat.completion', 'created': 1, 'model': body['model'],
                    'choices': [{'index': 0, 'finish_reason': reason, 'message': message}],
                    'usage': {'prompt_tokens': 40000, 'completion_tokens': 10, 'total_tokens': 40010,
                              'prompt_tokens_details': {'cached_tokens': 0}}}
        if body.get('stream'):
            data['object'] = 'chat.completion.chunk'
            data['choices'][0]['delta'] = data['choices'][0].pop('message')
            raw = ('data: '+json.dumps(data)+'\n\ndata: [DONE]\n\n').encode(); mime = 'text/event-stream'
        else:
            raw = json.dumps(data).encode(); mime = 'application/json'
        self.send_response(200); self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-denied-tools', action='store_true')
    args = parser.parse_args()
    Fixture.check_denied_tools = args.check_denied_tools
    out = ROOT/'outputs/preflight'/f'hermes-v3-{time.time_ns()}'
    workspace = out/'native/workspace'; workspace.mkdir(parents=True)
    Fixture.canary = 'UNREAD-ANSWER-' + uuid.uuid4().hex
    Fixture.denied_file = out / 'answers-canary.txt'
    Fixture.denied_file.write_text(Fixture.canary)
    (workspace / 'AGENTS.md').write_text('Private answer canary: ' + Fixture.canary)
    im = Image.new('RGB', (300, 120), 'white'); draw = ImageDraw.Draw(im)
    draw.rectangle((5, 10, 95, 100), fill='red'); draw.ellipse((100, 10, 195, 100), fill='blue')
    draw.polygon([(200, 100), (250, 10), (295, 100)], fill='green')
    Fixture.source = workspace/'original.png'; im.save(Fixture.source)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env, cfg = environment(ROOT, 'hermes', ROOT/'configs/experiment.v3.review.json')
        url = f'http://127.0.0.1:{server.server_port}'
        env.update(TOKENHUB_BASE_URL=url+'/v1', TOKENHUB_API_KEY='fixture-only')
        cfg['web'].update(search_host='127.0.0.1', search_port=server.server_port, fetch_base_url=url)
        cfg['bc100_campaign']['max_rounds'] = 12
        (out/'experiment.json').write_text(json.dumps(cfg))
        spec = {'job_id': 'hermes-v3-offline', 'strategy': 'visual', 'model': cfg['model'],
                'image': [str(Fixture.source)],
                'question': f'Inspect {Fixture.source}, crop the circle, zoom into the triangle, then gather records. Finish when the history is rendered.',
                'config_path': str(out/'experiment.json')}
        (out/'spec.json').write_text(json.dumps(spec))
        with (out/'process.log').open('w') as log:
            result = subprocess.run([python_for(ROOT), str(ROOT/'scripts/hermes_bc_worker_v3.py'),
                '--spec', str(out/'spec.json'), '--out', str(out/'native'), '--live', '--offline-fixture'],
                env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        if result.returncode:
            raise RuntimeError(f'Repaired Hermes fixture failed: {out}/process.log')
        native = json.loads((out/'native/native-result.json').read_text())
        assert native['final']['text'] == 'V3-CANVAS-TOOLS-OK'
        assert {'image_crop', 'image_zoom_in'} <= set(Fixture.native_tools)
        wire = [json.loads(line) for line in (out/'native/metrics/vision-wire.jsonl').read_text().splitlines()]
        assert any(r['compression_count'] and r['matching_rendered_pixels'] for r in wire)
        if args.check_denied_tools:
            assert Fixture.denied_observed == Fixture.denied_names
        report = {'denied_tool_calls_verified': Fixture.denied_observed, 'answer_canary_absent_from_requests': True,
                  'workspace_instructions_not_loaded': True, 'passed': True, 'paid_model_calls': 0, 'native_tools_executed': Fixture.native_tools,
                  'model_visible_tools': TOOLS, 'actual_http_calls': len(Fixture.calls),
                  'rendered_pixels_preserved_at_wire': True, 'artifact': str(out)}
        (out/'result.json').write_text(json.dumps(report, indent=2)); print(json.dumps(report))
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
