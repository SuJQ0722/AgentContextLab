"""Two bounded transport/reading probes; no benchmark answers or scoring calls.

Default only prepares requests. --live issues each fixed probe at most once.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import time

from lab import ROOT, environment
from bounded_visual_reading_gate_v1 import save

OUT = ROOT / 'outputs/preflight/visual-transport-engineering-v2/live-diagnostic'


def prepare(out):
    source = ROOT / 'outputs/preflight/bounded-webp-reading-gate-v1'
    manifest = json.loads((source / 'manifest.json').read_text())
    item = next(x for x in manifest['calls'] if x['key'] == 'real_history_webp')
    raw = (source / 'requests/real_history_webp.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != item['request_sha256']:
        raise ValueError('Frozen reading diagnostic changed')
    visual = json.loads(raw)
    parts = visual['messages'][0]['content']
    images = [p for p in parts if p.get('type') == 'image_url']
    if len(images) != 10:
        raise ValueError('Expected ten frozen independent pages')
    # Earlier duplicate must be removed; final ten stay byte-identical.
    visual['messages'][0]['content'] = [images[0], *parts]
    visual.update(stream=True, stream_options={'include_usage': True})
    text = {'model': visual['model'], 'messages': [{'role': 'user', 'content': 'Reply with exactly OK.'}],
            'max_tokens': 16, 'thinking': {'type': 'disabled'}, 'temperature': 0,
            'stream': True, 'stream_options': {'include_usage': True}}
    for key, payload in [('text_control', text), ('ten_page_reading', visual)]:
        save(out / 'requests' / (key + '.json'), payload)
    save(out / 'manifest.json', {'maximum_model_calls': 2, 'automatic_retries': 0,
         'purpose': 'Transport and reading diagnostic, not full trajectory or benchmark score',
         'thinking_disabled_for_short_reading_probe_only': True,
         'source_request_sha256': item['request_sha256'],
         'expected_fields': item['expected_synthetic_fields'],
         'expected_original_image_count': 11, 'expected_sent_image_count': 10})


def run(out):
    import httpx
    from openai import OpenAI
    import recent_ten_images_transport_v1 as retention
    from visual_transport_runtime_v2 import install, DEFAULT_POLICY
    env, _ = environment(ROOT, 'hermes')
    manifest = json.loads((out / 'manifest.json').read_text())
    model_calls = 0
    for key in ('text_control', 'ten_page_reading'):
        folder = out / 'calls' / key
        if (folder / 'started.json').exists():
            raise ValueError('Paid diagnostic already attempted; no implicit retry')
        payload = json.loads((out / 'requests' / (key + '.json')).read_text())
        registry = set()
        for m in payload['messages']:
            for part in m['content'] if isinstance(m['content'], list) else []:
                if part.get('type') == 'image_url':
                    raw = base64.b64decode(part['image_url']['url'].split(',', 1)[1], validate=True)
                    registry.add(hashlib.sha256(raw).hexdigest())
        old_send = httpx.Client._send_single_request
        retention.install(folder / 'wire.jsonl', rendered_registry=registry)
        policy = {**DEFAULT_POLICY, 'max_failed_sends': 1}
        handle = install(policy, folder, approved_base_url=env['TOKENHUB_BASE_URL'])
        save(folder / 'started.json', {'at_unix': time.time(), 'model_calls_max': 1,
             'policy': policy, 'version': handle['version']})
        result = {'status': 'failed', 'usage': None, 'provider_api_seconds': None,
                  'actual_usd': None, 'model_calls': 1}
        model_calls += 1
        started = time.monotonic()
        content = ''; finishes = []
        try:
            thinking = payload.pop('thinking')
            with OpenAI(base_url=env['TOKENHUB_BASE_URL'], api_key=env['TOKENHUB_API_KEY'],
                        max_retries=0, http_client=httpx.Client(trust_env=False)) as client:
                with client.chat.completions.create(**payload, extra_body={'thinking': thinking}) as stream:
                    for chunk in stream:
                        if chunk.usage is not None:
                            result['usage'] = chunk.usage.model_dump()
                        for choice in chunk.choices:
                            content += choice.delta.content or ''
                            if choice.finish_reason:
                                finishes.append(choice.finish_reason)
            result.update(status='completed' if content and 'stop' in finishes else 'incomplete',
                          content=content, finish_reasons=finishes)
            if key == 'ten_page_reading':
                try:
                    parsed = json.loads(content.strip().removeprefix('```json').removesuffix('```'))
                    result['reading_matches'] = {k: str(parsed.get(k, '')).lower() == str(v).lower()
                                                  for k, v in manifest['expected_fields'].items()}
                except ValueError:
                    result['reading_matches'] = None
        except (Exception, SystemExit) as exc:
            result.update(error_type=type(exc).__name__)
        finally:
            result['client_wall_seconds'] = time.monotonic() - started
            handle['uninstall']()
            httpx.Client._send_single_request = old_send
            save(folder / 'result.json', result)
        print(json.dumps({'probe': key, **result}, ensure_ascii=False), flush=True)
        if result['status'] != 'completed':
            break
    return model_calls


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=OUT)
    p.add_argument('--live', action='store_true')
    args = p.parse_args()
    prepare(args.output)
    if args.live:
        run(args.output)
    else:
        print(json.dumps({'prepared': 2, 'model_calls': 0}))


if __name__ == '__main__':
    main()
