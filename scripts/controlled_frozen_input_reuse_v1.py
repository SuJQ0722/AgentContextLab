"""Stage certified original input bytes without repeating remote downloads."""
import base64
import hashlib
import json
from pathlib import Path

VERSION = 'controlled-frozen-input-reuse-v1'


def resolve_inputs(row):
    roots = [Path(p).resolve() for p in row.get('native_asset_roots', [])]
    candidates = {r.parent / 'input-images.json' for r in roots if r.name == 'input-images'}
    if len(candidates) != 1:
        raise ValueError('Exactly one original input ledger required')
    ledger_path = next(iter(candidates))
    ledger = json.loads(ledger_path.read_text())
    sources = row.get('image') or []
    if [x['source'] for x in ledger] != sources:
        raise ValueError('Input URL/order does not match original ledger')
    prefix = json.loads(Path(row['prefix_path']).read_text()); hashes = set()
    for message in prefix['messages']:
        content = message.get('content')
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and part.get('type') == 'image_url':
                url = part['image_url']['url']
                if url.startswith('data:image/'):
                    hashes.add(hashlib.sha256(base64.b64decode(url.split(',', 1)[1], validate=True)).hexdigest())
    for item in ledger:
        path = Path(item['path']).resolve()
        if not any(path.is_relative_to(root) for root in roots if root.name == 'input-images'):
            raise ValueError('Input file outside certified input directory')
        raw = path.read_bytes(); actual = hashlib.sha256(raw).hexdigest()
        if actual != item['sha256'] or len(raw) != item['bytes'] or actual not in hashes:
            raise ValueError('Input bytes do not match ledger and frozen native prefix')
    return ledger_path, ledger


def stage(row, out, original):
    source, ledger = resolve_inputs(row)
    images, staged = original({**row, 'image': [x['path'] for x in ledger]}, out)
    if [x['sha256'] for x in staged] != [x['sha256'] for x in ledger]:
        raise ValueError('Local staging changed original input bytes')
    for item, old in zip(staged, ledger): item['source'] = old['source']
    (out / 'input-images.json').write_text(json.dumps(staged, indent=2) + '\n')
    (out / 'input-reuse.json').write_text(json.dumps({'version': VERSION,
        'source_ledger': str(source), 'source_ledger_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'input_sha256': [x['sha256'] for x in staged], 'remote_downloads': 0,
        'bytes_unchanged': True, 'matched_frozen_prefix': True}, indent=2) + '\n')
    return images, staged
