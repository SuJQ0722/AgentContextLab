#!/usr/bin/env python3
"""Zero-network fixture: real Hermes tool artifacts -> native DSH compaction -> HTTP.

Only a localhost mock model is contacted. Tool responses reuse captured real
Hermes image_search/crop/zoom outputs through the production admission bridge.
"""
import base64
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import threading
import time
from lab import ROOT, command, environment
from dsh_image_preservation import preservation_patches


def main():
    out = ROOT / 'outputs/preflight' / f'dsh-multimodal-compaction-v2-{time.time_ns()}'
    work = out / 'workspace'
    work.mkdir(parents=True)
    fixtures = ROOT / 'outputs/preflight/hermes-tool-bridge-v2'
    artifacts = {name: json.loads((fixtures / 'offline' / f'{name}.json').read_text())
                 for name in ['image_crop', 'image_zoom_in']}
    artifacts['image_search'] = json.loads((fixtures / 'live-lens.json').read_text())['result']
    source = fixtures / 'offline/source.png'
    # Offline resource substitution only: retain real search-result JSON shape,
    # resolve all referenced pictures to an existing captured local source.
    for part in artifacts['image_search']['content']:
        if part['type'] == 'text':
            body = json.loads(part['text'])
            body['image_url'] = str(source)
            for row in body.get('results', []):
                if row.get('thumbnail_url'):
                    row['thumbnail_url'] = str(source)
            part['text'] = json.dumps(body)
    artifacts['image_search']['metadata']['offline_resource_substitution'] = True
    source_hashes = {hashlib.sha256(source.read_bytes()).hexdigest()}
    for result in artifacts.values():
        source_hashes.update(p['sha256'] for p in result['content'] if p['type'] == 'image')
    (out / 'artifacts.json').write_text(json.dumps(artifacts))
    recorded = []
    requests = json.loads((fixtures / 'offline/requests.json').read_text())
    first_tools = [('image_search', {'image_url': 'https://images.unsplash.com/photo-1502602898657-3e91760cbb34?w=640', 'top_k': 3})]
    first_tools.extend((r['tool'], r['arguments']) for r in requests)

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            images = [p for m in body['messages'] for p in
                      (m.get('content', []) if isinstance(m.get('content'), list) else [])
                      if p.get('type') == 'image_url']
            hashes = [hashlib.sha256(base64.b64decode(p['image_url']['url'].split(',', 1)[1])).hexdigest() for p in images]
            canvas = bool(set(hashes) - source_hashes)
            step = len(recorded)
            recorded.append({'step': step + 1, 'image_hashes': hashes, 'canvas_present': canvas})
            if canvas:
                delta = {'role': 'assistant', 'content': 'MULTIMODAL-COMPACTION-WIRE-OK'}
            else:
                name, args = first_tools[step] if step < len(first_tools) else ('web_search', {'query': f'offline table records {step}', 'num_results': 5})
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': f'fixture{step}', 'type': 'function',
                         'function': {'name': name, 'arguments': json.dumps(args)}}]}
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            base = {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1, 'model': body['model']}
            for chunk in [dict(base, choices=[{'index': 0, 'delta': delta, 'finish_reason': None}]),
                          dict(base, choices=[{'index': 0, 'delta': {}, 'finish_reason': 'stop' if canvas else 'tool_calls'}],
                               usage={'prompt_tokens': 1000, 'completion_tokens': 10, 'total_tokens': 1010,
                                      'prompt_tokens_details': {'cached_tokens': 0}})]:
                self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')

    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env, _ = environment(ROOT, 'dsh')
        env.update(TOKENHUB_BASE_URL=f'http://127.0.0.1:{server.server_port}/v1', TOKENHUB_API_KEY='fixture-only',
                   DSH_HOME=str(out / 'dsh-home'), ACL_WORKSPACE=str(work), ACL_STRATEGY='visual_native',
                   ACL_COMPRESSION_TRIGGER='32768', ACL_POST_COMPRESSION_BUDGET='16384',
                   ACL_RAW_CANVAS_AUDIT_DIR=str(out / 'raw-canvas'), ACL_IMAGE_WIRE_AUDIT_DIR=str(out / 'wire'),
                   ACL_IMAGE_WIRE_EXPECTED=str(out / 'expected.json'),
                   NODE_OPTIONS='--import=' + str(ROOT / 'scripts/dsh_wire_image_guard.mjs'))
        overlay = out / 'research.patch.yml'
        overlay.write_text((ROOT / 'configs/research.dsh.patch.yml').read_text().replace(
            '"@ACL_DSH_CONTEXT_PLUGIN@"', json.dumps(str(ROOT / 'plugins/dsh-context/index.mjs'))))
        inputs = out / 'input.json'
        inputs.write_text(json.dumps({'question_id': 'offline-multimodal-native-loop',
                                     'images': [{'path': str(source), 'media_type': 'image/png'}]}))
        tool_plugin = out / 'tools-fixture.mjs'
        tool_plugin.write_text("""
import {readFile} from 'node:fs/promises';
import {registerTools,TOOL_NAMES} from 'BRIDGE';
export const inject=['tools','attachments'];
export async function apply(ctx,config){
 const schemas=JSON.parse(await readFile(config.schemas,'utf8')).tools;
 const artifacts=JSON.parse(await readFile(config.artifacts,'utf8'));
 registerTools(ctx,config,schemas,async(_config,request)=>{
  if(request.tool in artifacts)return {...structuredClone(artifacts[request.tool]),call_id:request.call_id};
  const records=Array.from({length:80},(_,i)=>`Record ${i}: warehouse cedar held ${i+100} packages. Reference K-${i}.`).join(' ');
  return {tool:request.tool,call_id:request.call_id,handler_seconds:0,metadata:{fixture:true},content:[{type:'text',text:'| Item | Count |\\n|---|---|\\n| Cedar | 179 |\\n| Oak | 93 |\\n'+records}]};
 });
 ctx.on('agent/pre-step',async({agent},next)=>{agent.ctx.tools.restrict({allow:TOOL_NAMES});return next();});
}
""".replace('BRIDGE', str(ROOT / 'plugins/dsh-local-web/hermes-tools-v2.mjs')))
        plugins = [
            {'id': 'evaluation', 'name': str(ROOT / 'plugins/dsh-evaluation/index.mjs'), 'config': {
                'inputFile': str(inputs), 'metricsDir': str(work / 'metrics'), 'maxSteps': 40,
                'allowedTools': ['web_search', 'web_extract', 'image_search', 'image_crop', 'image_zoom_in'],
                'expectedStrategy': 'visual_native'}},
            {'id': 'fixture-hermes-tools', 'name': str(tool_plugin), 'config': {
                'schemas': str(ROOT / 'outputs/preflight/hermes-tool-bridge-v2-schemas.json'),
                'artifacts': str(out / 'artifacts.json'), 'metricsDir': str(work / 'metrics'), 'timeoutMs': 30000}},
            {'id': 'wire-expectations', 'name': str(ROOT / 'scripts/dsh_wire_expectations.mjs'),
             'config': {'expectedFile': str(out / 'expected.json')}},
        ]
        policy = {'strategy': 'visual_native', 'python': env['ACL_PYTHON'],
                  'renderer': str(ROOT / 'scripts/render_dsh_history_audited.py'), 'metricsDir': str(work / 'metrics'),
                  'historyScale': 1, 'fontSize': 16, 'postCompressionBudget': 16384,
                  'thresholdRatio': 32768 / int(env['ACL_CONTEXT_WINDOW']), 'headroomTokens': 8192,
                  'retainTokens': 4096, 'maxTokens': 4096, 'compactionRetries': 0, 'maxOverflowRetries': 0}
        patches = [{'id': 'tool-web', 'disabled': True}, {'id': 'session-title-llm', 'disabled': True}, {'insert': plugins},
                   {'id': 'acl-research-compaction', 'config': policy}, *preservation_patches(env)]
        patch = out / 'observer.json'
        patch.write_text(json.dumps(patches))
        prompt = 'Inspect the supplied historical source. Use image search, crop and zoom, then collect table records until the history is compressed.'
        cmd = command(ROOT, 'dsh', prompt, env)
        cmd[cmd.index(str(ROOT / '.state/dsh-research.patch.yml'))] = str(overlay)
        cmd[-1:] = ['--patch', str(patch), '--json', '--approval-policy', 'never', prompt]
        with (out / 'stdout.jsonl').open('w') as so, (out / 'stderr.log').open('w') as se:
            result = subprocess.run(cmd, cwd=work, env=env, stdout=so, stderr=se, timeout=180)
        def rows(path):
            return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []
        renders = rows(work / 'metrics/render.jsonl')
        compressions = rows(work / 'metrics/compression.jsonl')
        wire = rows(out / 'wire/requests.jsonl')
        raw = [json.loads(p.read_text()) for p in (out / 'raw-canvas').glob('*/manifest.json')]
        native = rows(out / 'expected.json.jsonl')
        report = {'paid_requests': 0, 'network': 'localhost model fixture only; captured tool outputs reused offline',
                  'exit_code': result.returncode, 'server_requests': recorded, 'render': renders,
                  'compression': compressions, 'raw_canvas': raw, 'native_expectations': native,
                  'guard_errors': [x['guard_error'] for x in wire if x['guard_error']],
                  'source_hashes': sorted(source_hashes), 'preservation_configuration': preservation_patches(env),
                  'scope': 'Real native compaction and shared renderer; real captured Hermes tool-result formats; synthetic repeated table/text. Not benchmark accuracy.'}
        if raw and recorded:
            final_hashes = recorded[-1]['image_hashes']
            raw_hashes = [i['sha256'] for i in raw[-1]['images']]
            report['raw_canvas_all_present_on_wire'] = all(h in final_hashes for h in raw_hashes)
            report['selected_evidence_not_duplicated_as_native'] = not (set(final_hashes) & source_hashes)
        (out / 'result.json').write_text(json.dumps(report, indent=2))
        print(json.dumps({'out': str(out), 'exit_code': result.returncode, 'compression_count': len(compressions),
                          'raw_canvas_all_present_on_wire': report.get('raw_canvas_all_present_on_wire'),
                          'guard_errors': report['guard_errors']}))
        assert result.returncode == 0 and compressions and all(c['valid'] for c in compressions)
        assert report['raw_canvas_all_present_on_wire'] and not report['guard_errors']
        assert renders[-1]['stats']['source_image_coverage_verified']
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
