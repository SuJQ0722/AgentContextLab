#!/usr/bin/env python3
"""Exercise the actual repaired DSH runner with localhost model/tool responses.

The production plugin, Python handlers, policy helper, native attachments and
final HTTP serialization all run. Synthetic usage tests policy routing only.
"""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from lab import ROOT, environment


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def main():
    root = ROOT / 'outputs/preflight' / f'dsh-v3-entry-{time.time_ns()}'
    root.mkdir(parents=True)
    manifest = json.loads((ROOT / 'outputs/cohorts/bc100-manifest.json').read_text())
    cohort = Path(manifest['datasets']['bc100']['cohort_path'])
    qid = json.loads(cohort.read_text().splitlines()[0])['id']
    report = {'paid_model_calls': 0, 'external_http_calls': 0, 'entrypoint': 'scripts/run_dsh_eval_v3.py',
              'scope': 'Synthetic localhost responses and provider usage; actual production tool/policy/attachment routing, not accuracy.',
              'lens_coverage': 'Schema is checked here; real public-URL Lens handler success is separately recorded in outputs/preflight/hermes-tool-bridge-v2/live-lens.json. No Lens network request in this fixture.',
              'strategies': []}
    from PIL import Image, ImageDraw

    for strategy in ('none', 'visual_native'):
        implementation_paths = ['scripts/run_dsh_eval_v3.py', 'scripts/shared_context_policy.py',
            'plugins/dsh-context/hermes-policy-v3.mjs', 'plugins/dsh-context/shared-surface.mjs',
            'plugins/dsh-local-web/hermes-tools-v2.mjs', 'scripts/hermes_tool_bridge.py',
            'scripts/dsh_wire_image_guard.mjs', 'scripts/dsh_wire_expectations.mjs', 'scripts/dsh_raw_usage_observer.mjs']
        implementation_before = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in implementation_paths}
        folder = root / strategy
        output = folder / 'runs'
        work = output / strategy / qid / 'workspace'
        work.mkdir(parents=True)
        source = work / 'synthetic-native-parent.png'
        picture = Image.new('RGB', (480, 320), 'white')
        draw = ImageDraw.Draw(picture)
        draw.rectangle((0, 0, 239, 159), fill=(180, 220, 250))
        draw.rectangle((240, 160, 479, 319), fill=(240, 210, 150))
        for y in range(20, 300, 30):
            draw.text((12, y), f'Fixture table row {y}: Cedar=179 Oak=93', fill='black')
        picture.save(source)
        observed, web = [], []
        tools = [('web_search', {'query': 'fixture Cedar inventory', 'limit': 2}),
                 ('web_extract', {'urls': ['https://93.184.216.34/fixture'], 'char_limit': 3000}),
                 ('image_crop', {'image_path': str(source), 'bbox': [0, 0, 240, 160], 'coord_format': 'absolute', 'padding': 0, 'use_smart_resize': False}),
                 ('image_zoom_in', {'image_path': str(source), 'bbox_2d': [160, 80, 400, 240], 'use_super_resolution': False, 'use_smart_resize': False})]
        marker = 'ENTRY-' + strategy.upper() + '-OK'

        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, value, status=200):
                data = json.dumps(value).encode()
                self.send_response(status); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data))); self.send_header('X-Cached', 'false')
                self.end_headers(); self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path == '/search':
                    web.append({'kind': 'search', 'payload': body})
                    self.reply({'organic': [{'title': 'Local fixture evidence', 'link': 'https://93.184.216.34/fixture',
                         'snippet': '\n'.join(f'Record {i}: Cedar warehouse {100+i} packages, reference K-{i:03d}.' for i in range(80))}]})
                    return
                if self.path == '/fetch':
                    web.append({'kind': 'fetch', 'mode': body.get('extractMode'), 'url': body.get('url')})
                    self.reply({'success': True, 'data': '| Warehouse | Count |\n|---|---|\n| Cedar | 179 |\n| Oak | 93 |\n' + '\n'.join(f'Page record {i}: shipped {i+200} crates from depot.' for i in range(100))})
                    return
                if self.path != '/v1/chat/completions':
                    self.reply({'error': 'Unexpected fixture endpoint'}, 404)
                    return
                images = [p for m in body['messages'] for p in (m.get('content', []) if isinstance(m.get('content'), list) else []) if p.get('type') == 'image_url']
                hashes = [hashlib.sha256(base64.b64decode(p['image_url']['url'].split(',', 1)[1])).hexdigest() for p in images]
                details = [p['image_url'].get('detail') for p in images]
                expected = json.loads((work / 'metrics/expected-wire.json').read_text())
                assert hashes == expected['wire_sha256'], 'Actual HTTP image bytes differ from native expectation'
                assert len(details) == len(expected['details'])
                assert all(want is None or got == want for got, want in zip(details, expected['details'])), 'Actual HTTP image detail differs from native expectation'
                evidence = set()
                for path in (work / 'tool-results').glob('*/result.json'):
                    result = json.loads(path.read_text())
                    evidence.update(part['sha256'] for part in result.get('content', []) if part['type'] == 'image')
                canvas = bool(set(hashes) - evidence)
                step = len(observed)
                schemas = {tool['function']['name']: tool['function']['parameters'] for tool in body.get('tools', [])}
                # This local API records the final serialized messages, not an SDK approximation.
                (folder / f'actual-request-{step:02d}.json').write_text(json.dumps(body, ensure_ascii=False))
                observed.append({'step': step + 1, 'image_hashes': hashes, 'canvas_present': canvas,
                                 'image_details': details, 'native_expected_details': expected['details'],
                                 'tool_names': sorted(schemas), 'schemas': schemas,
                                 'roles': [m['role'] for m in body['messages']]})
                final = step >= len(tools) and (strategy == 'none' or canvas)
                if final or step >= 10:
                    delta = {'role': 'assistant', 'content': marker if final else 'FAILED-NO-CANVAS'}
                else:
                    name, arguments = tools[step] if step < len(tools) else ('web_search', {'query': f'additional local evidence {step}', 'limit': 2})
                    delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': f'entry-{strategy}-{step}', 'type': 'function',
                             'function': {'name': name, 'arguments': json.dumps(arguments)}}]}
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                base = {'id': 'localhost-entry', 'object': 'chat.completion.chunk', 'created': 1, 'model': body['model']}
                usage = 40000 if step >= 3 else 1000
                for chunk in (dict(base, choices=[{'index': 0, 'delta': delta, 'finish_reason': None}]),
                              dict(base, choices=[{'index': 0, 'delta': {}, 'finish_reason': 'stop' if 'content' in delta else 'tool_calls'}],
                                   usage={'prompt_tokens': usage, 'completion_tokens': 20, 'total_tokens': usage + 20,
                                          'prompt_tokens_details': {'cached_tokens': 0}})):
                    self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n')

        server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}'
            cfg = json.loads((ROOT / 'configs/experiment.v3.review.json').read_text())
            cfg['web'].update(search_host='127.0.0.1', search_port=server.server_port, fetch_base_url=url)
            cfg['bc100']['max_rounds'] = 12
            config = folder / 'fixture-config.json'; config.write_text(json.dumps(cfg, indent=2))
            private = folder / 'web-fixture.json'
            private.write_text(json.dumps({'web': {'local_web': {'search': {'url': '127.0.0.1', 'port': server.server_port, 'api_key': 'fixture-only'},
                              'fetch': {'fetch_server': {'base_url': url, 'extract_mode': 'text', 'timeout': 5}}}}}))
            env, _ = environment(ROOT, 'dsh', config)
            env.update(TOKENHUB_BASE_URL=url + '/v1', TOKENHUB_API_KEY='fixture-only', SERPER_API_KEY='fixture-only',
                       FETCH_SERVER_URL=url, ACL_HERMES_WEB_CONFIG=str(private), JINA_API_KEY='fixture-only', NODE_OPTIONS='',
                       NO_PROXY='127.0.0.1,localhost,::1', no_proxy='127.0.0.1,localhost,::1')
            cmd = [sys.executable, str(ROOT / 'scripts/run_dsh_eval_v3.py'), '--dataset', 'bc100', '--strategies', strategy,
                   '--question-id', qid, '--limit', '1', '--timeout', '240', '--config', str(config), '--output-root', str(output),
                   '--web-prevalidated', '--offline-fixture', '--live']
            process = subprocess.Popen(cmd, env=env, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                stdout, stderr = process.communicate(timeout=275)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=15)
            (folder / 'runner-stdout.txt').write_text(stdout); (folder / 'runner-stderr.txt').write_text(stderr)
            metrics = work / 'metrics'
            policy = rows(metrics / 'shared-policy.jsonl')
            wire = rows(metrics / 'wire/requests.jsonl')
            tool_calls = rows(metrics / 'hermes-tool-bridge.jsonl')
            result_path = output / strategy / qid / 'result.json'
            result = json.loads(result_path.read_text()) if result_path.exists() else None
            item = {'strategy': strategy, 'exit_code': process.returncode, 'native_result': result, 'server_requests': observed,
                    'web_requests': web, 'tool_calls': [call['tool'] for call in tool_calls],
                    'shared_policy_records': policy, 'wire_guard_errors': [r['guard_error'] for r in wire if r['guard_error']],
                    'actual_wire_canvas': any(r['canvas_present'] for r in observed),
                    'helper_sha256': hashlib.sha256((ROOT / 'scripts/shared_context_policy.py').read_bytes()).hexdigest(),
                    'plugin_sha256': hashlib.sha256((ROOT / 'plugins/dsh-context/hermes-policy-v3.mjs').read_bytes()).hexdigest(),
                    'runner_sha256': hashlib.sha256((ROOT / 'scripts/run_dsh_eval_v3.py').read_bytes()).hexdigest()}
            item['implementation_before'] = implementation_before
            item['implementation_after'] = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in implementation_paths}
            canvas_hashes = {image['source_sha256'] for record in policy if record['status'] == 'compressed'
                             for image in record.get('image_ledger', [])}
            item['new_canvas_source_hashes'] = sorted(canvas_hashes)
            item['all_new_canvases_present_on_actual_wire'] = bool(canvas_hashes) and canvas_hashes.issubset(
                {sha for request in observed for sha in request['image_hashes']})
            report['strategies'].append(item)
            (root / 'result.json').write_text(json.dumps(report, indent=2))
            expected_names = {'web_search', 'web_extract', 'image_search', 'image_crop', 'image_zoom_in'}
            assert item['implementation_before'] == item['implementation_after'], 'Implementation changed during fixture; rerun after code is stable'
            assert process.returncode == 0 and result and result['status'] == 'completed', f'{strategy} runner failed; inspect {folder}'
            assert observed and all(set(row['tool_names']) == expected_names for row in observed)
            assert set(item['tool_calls']) >= {name for name, _ in tools}
            assert any(r['kind'] == 'search' and r['payload']['hl'] == 'en' for r in web)
            assert any(r['kind'] == 'fetch' and r['mode'] == 'text' for r in web)
            assert not item['wire_guard_errors']
            assert policy and all(r['strategy'] == strategy for r in policy)
            assert any(r.get('provider_usage', {}).get('prompt_tokens') == 40000 for r in policy if r.get('provider_usage'))
            if strategy == 'visual_native':
                assert item['actual_wire_canvas'] and any(r['status'] == 'compressed' for r in policy)
                assert item['all_new_canvases_present_on_actual_wire']
            else:
                assert not item['actual_wire_canvas'] and not any(r['status'] == 'compressed' for r in policy)
            print(json.dumps({'strategy': strategy, 'passed': True, 'requests': len(observed), 'canvas': item['actual_wire_canvas'], 'output': str(root)}), flush=True)
        finally:
            server.shutdown(); server.server_close()
    report['passed'] = True
    (root / 'result.json').write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
