#!/usr/bin/env python3
"""Controlled synthetic history recall through the actual visual compressor and gateway."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import time
import urllib.request
from lab import ROOT, environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--font-size', type=int, default=8)
    parser.add_argument('--history-scale', type=float, default=.75)
    args = parser.parse_args()
    if not args.live:
        print('Dry run: one text control and one rendered-history request; no API calls.')
        return
    env, cfg = environment(ROOT, 'dsh')
    suffix = '' if (args.font_size, args.history_scale) == (8, .75) else f'-font{args.font_size}-scale{args.history_scale}'
    out = ROOT / f"outputs/preflight/visual-history-pdf-{cfg['max_output_tokens']}{suffix}"
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'results.json').exists():
        raise SystemExit('Existing paid probe results; inspect them before rerunning.')
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'Research the inventory records and retain exact facts.'}]}]
    expected = {'Cedar': 'BX-7319', 'Juniper': 'KQ-4826', 'Maple': 'VT-9053',
                'Cedar_units': 417, 'Juniper_units': 286, 'Maple_units': 953}
    for i in range(12):
        name, code, units = [('Cedar','BX-7319',417),('Juniper','KQ-4826',286),('Maple','VT-9053',953)][i // 4]
        content = f'Record page {i+1}. Warehouse: {name}.\n'
        content += '\n'.join(f'Archive row {j}: shipment audit completed; retain source records and reconcile inventory before dispatch.' for j in range(16))
        if i % 4 == 1:
            content += f'\nVERIFIED INVENTORY\n| Warehouse | Reference code | Units |\n| {name} | {code} | {units} |\n'
        messages.extend([
            {'role': 'assistant', 'content': [{'type': 'tool-call', 'id': f'c{i}', 'name': 'web_fetch', 'arguments': json.dumps({'url': f'https://inventory.example/record/{i}'})}]},
            {'role': 'tool', 'toolCallId': f'c{i}', 'content': [{'type': 'text', 'text': content}]},
        ])
    payload = {'messages': messages, 'history_scale': args.history_scale, 'font_size': args.font_size}
    (out / 'history.json').write_text(json.dumps(payload, indent=2))
    result = subprocess.run([env['ACL_PYTHON'], str(ROOT / 'scripts/render_dsh_history.py')],
                            input=json.dumps(payload), capture_output=True, text=True, env=env, check=True)
    rendered = json.loads(result.stdout)
    paths = []
    for i, url in enumerate(rendered['images']):
        path = out / f'history_{i}.png';path.write_bytes(base64.b64decode(url.split(',',1)[1])); paths.append(str(path))
    question = 'From the inventory records, return only a JSON object with keys Cedar, Juniper, Maple (reference codes), Cedar_units, Juniper_units, Maple_units (integer units). Do not guess missing facts.'
    (out / 'native-input.json').write_text(json.dumps({'question_id':'visual-history-probe','images':[{'path':p,'media_type':'image/png'} for p in paths]}))
    (out / 'question.txt').write_text(question)
    text_history = '\n'.join(b.get('text','') for m in messages for b in m['content'])
    records = []
    for mode in ['text', 'visual']:
        content = [{'type':'text','text': question}]
        content += [{'type':'text','text':text_history}] if mode == 'text' else [{'type':'image_url','image_url':{'url':u}} for u in rendered['images']]
        request = urllib.request.Request(env['TOKENHUB_BASE_URL'].rstrip('/')+'/chat/completions',
            data=json.dumps({'model':cfg['model'],'messages':[{'role':'user','content':content}],'max_tokens':cfg['max_output_tokens']}).encode(),
            headers={'Authorization':'Bearer '+env['TOKENHUB_API_KEY'],'Content-Type':'application/json'})
        start = time.monotonic()
        try:
            with urllib.request.urlopen(request,timeout=180) as stream: response=json.load(stream)
        except Exception as error:
            records.append({'mode':mode,'status':'transport_error','error_type':type(error).__name__,
                            'client_http_seconds':time.monotonic()-start})
            (out/'results.json').write_text(json.dumps({'synthetic_probe':True,'records':records},indent=2))
            raise
        answer=response['choices'][0]['message'].get('content') or ''
        try: parsed=json.loads(answer[answer.index('{'):answer.rindex('}')+1])
        except (ValueError,json.JSONDecodeError): parsed={}
        record={'mode':mode,'model':cfg['model'],'answer':answer,'finish_reason':response['choices'][0].get('finish_reason'),
                'max_output_tokens':cfg['max_output_tokens'],'correct_fields':sum(parsed.get(k)==v for k,v in expected.items()),
                'total_fields':len(expected),'usage':response.get('usage'),'client_http_seconds':time.monotonic()-start}
        records.append(record)
        (out/'results.json').write_text(json.dumps({'synthetic_probe':True,'expected':expected,
            'history_scale':args.history_scale,'font_size':args.font_size,
            'renderer':rendered['renderer'],'render_seconds':rendered['render_seconds'],'image_count':len(paths),'records':records},indent=2))
        print(json.dumps(record),flush=True)


if __name__ == '__main__':
    main()
