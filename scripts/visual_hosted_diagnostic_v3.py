"""One immutable URL reading probe after every image has been byte-verified."""
import argparse
import base64
import fcntl
import hashlib
import json
from pathlib import Path
import time

from bounded_visual_reading_gate_v1 import save
from lab import ROOT, environment

OUT = ROOT / 'outputs/preflight/visual-transport-engineering-v2/hosted-diagnostic'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live', action='store_true')
    args = p.parse_args()
    source = OUT.parent / 'live-diagnostic'
    payload = json.loads((source / 'requests/ten_page_reading.json').read_text())
    expected = json.loads((source / 'manifest.json').read_text())['expected_fields']
    registry = set()
    for m in payload['messages']:
        for part in m['content'] if isinstance(m['content'], list) else []:
            if part.get('type') == 'image_url':
                registry.add(hashlib.sha256(base64.b64decode(part['image_url']['url'].split(',', 1)[1])).hexdigest())
    for digest in registry:
        record = json.loads((OUT / 'hosted' / (digest + '.json')).read_text())
        if record.get('source_sha256') != digest or record.get('download_sha256') != digest:
            raise ValueError('All image uploads must already be verified before model call')
    if not args.live:
        print(json.dumps({'model_calls': 0, 'verified_images': len(registry)})); return
    import httpx
    from openai import OpenAI
    from visual_transport_runtime_v2 import install as runtime, DEFAULT_POLICY
    from verified_hosted_images_v3 import install as hosted, VerifiedImageHost
    env, _ = environment(ROOT, 'hermes')
    folder = OUT / 'model-probe'; folder.mkdir(exist_ok=True)
    with (folder / 'run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (folder / 'started.json').exists():
            raise ValueError('Already attempted; no model replay')
        h1 = runtime({**DEFAULT_POLICY, 'max_failed_sends': 1}, folder,
                     approved_base_url=env['TOKENHUB_BASE_URL'])
        h2 = hosted(folder, rendered_registry=registry, host=VerifiedImageHost(OUT, env),
                    approved_base_url=env['TOKENHUB_BASE_URL'])
        save(folder / 'started.json', {'at_unix': time.time(), 'model_calls_max': 1,
             'same_reading_task_and_pixels_as_inline_probe': True,
             'not_benchmark_evaluation': True, 'automatic_retries': 0})
        result = {'status': 'failed', 'usage': None, 'provider_api_seconds': None,
                  'actual_usd': None, 'model_calls': 1}
        started = time.monotonic(); content = ''; finishes = []
        try:
            thinking = payload.pop('thinking')
            with OpenAI(base_url=env['TOKENHUB_BASE_URL'], api_key=env['TOKENHUB_API_KEY'],
                        max_retries=0, http_client=httpx.Client(trust_env=False)) as client:
                with client.chat.completions.create(**payload, extra_body={'thinking': thinking}) as stream:
                    for chunk in stream:
                        if chunk.usage is not None: result['usage'] = chunk.usage.model_dump()
                        for choice in chunk.choices:
                            content += choice.delta.content or ''
                            if choice.finish_reason: finishes.append(choice.finish_reason)
            result.update(status='completed' if content and 'stop' in finishes else 'incomplete',
                          content=content, finish_reasons=finishes)
            try:
                parsed = json.loads(content.strip().removeprefix('```json').removesuffix('```'))
                result['reading_matches'] = {k: str(parsed.get(k, '')).lower() == str(v).lower()
                                              for k, v in expected.items()}
            except ValueError: result['reading_matches'] = None
        except (Exception, SystemExit) as exc:
            result['error_type'] = type(exc).__name__
        finally:
            result['client_wall_seconds'] = time.monotonic() - started
            h2['uninstall'](); h1['uninstall']()
            save(folder / 'result.json', result)
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
