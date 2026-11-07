#!/usr/bin/env python3
"""Bounded live capability probes; persist usage, never credentials."""
import argparse
import base64
import json
import struct
import time
import urllib.error
import urllib.request
import zlib
from lab import ROOT, environment


def png(color):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    raw = b''.join(b'\0' + bytes(color) * 128 for _ in range(128))
    data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>2I5B', 128, 128, 8, 2, 0, 0, 0))
    return 'data:image/png;base64,' + base64.b64encode(data + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')).decode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Make paid requests')
    args = parser.parse_args()
    env, cfg = environment(ROOT, 'hermes')
    if not args.live:
        print(json.dumps({'model': cfg['model'], 'tests': ['text', 'image_red', 'image_blue', 'tool_call', 'tool_result'], 'dry_run': True}))
        return
    outdir = ROOT / 'outputs/preflight'
    outdir.mkdir(parents=True, exist_ok=True)
    records = []
    def call(name, messages, **extra):
        payload = {'model': cfg['model'], 'messages': messages, 'max_tokens': 512, **extra}
        start = time.monotonic()
        record = {'test': name, 'model': cfg['model'], 'timestamp': time.time()}
        request = urllib.request.Request(env['TOKENHUB_BASE_URL'].rstrip('/') + '/chat/completions', data=json.dumps(payload).encode(), headers={'Authorization': 'Bearer ' + env['TOKENHUB_API_KEY'], 'Content-Type': 'application/json'})
        response = None
        try:
            with urllib.request.urlopen(request, timeout=90) as stream:
                response = json.load(stream)
            record.update(status='success', response=response)
        except urllib.error.HTTPError as error:
            record.update(status='http_error', http_status=error.code)
        except Exception as error:
            record.update(status='error', error_type=type(error).__name__)
        record['http_elapsed_seconds'] = time.monotonic() - start
        # This is client-observed HTTP elapsed time, not provider-internal latency.
        records.append(record)
        (outdir / 'gateway-probes.json').write_text(json.dumps(records, indent=2))
        print(json.dumps({k: v for k, v in record.items() if k != 'response'}), flush=True)
        return response
    text = call('text', [{'role': 'user', 'content': 'Reply exactly OK.'}])
    if text is None:
        return
    for name, color in [('red', (255, 0, 0)), ('blue', (0, 0, 255))]:
        call('image_' + name, [{'role': 'user', 'content': [{'type': 'text', 'text': 'What is the dominant color? Reply with one color word.'}, {'type': 'image_url', 'image_url': {'url': png(color)}}]}])
    messages = [{'role': 'user', 'content': 'Call lookup with key=probe. Then report its returned value.'}]
    response = call('tool_call', messages, tools=[{'type': 'function', 'function': {'name': 'lookup', 'description': 'Return a value for a key', 'parameters': {'type': 'object', 'properties': {'key': {'type': 'string'}}, 'required': ['key']}}}], tool_choice={'type': 'function', 'function': {'name': 'lookup'}})
    if response:
        message = response['choices'][0]['message']
        calls = message.get('tool_calls', [])
        if calls:
            call('tool_result', messages + [message] + [{'role': 'tool', 'tool_call_id': tc['id'], 'content': 'VALUE_7319'} for tc in calls])


if __name__ == '__main__':
    main()
