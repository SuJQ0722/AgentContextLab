#!/usr/bin/env python3
"""Freeze original MMBC input bytes once, then stage identical bytes for every arm."""
import argparse
import hashlib
import io
import json
import shutil
import time
import urllib.request
from pathlib import Path
from PIL import Image
from run_bc_campaign_v3 import atomic, digest

VERSION = 'mmbc-original-input-images-v1'
MAX_BYTES = 25 * 1024 * 1024


def image_info(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('Input image exceeds original 25 MiB admission cap')
    with Image.open(io.BytesIO(raw)) as im:
        im.load()
        media = Image.MIME.get(im.format)
        if media not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif'):
            raise ValueError('Unsupported input image format')
        return {'media_type': media, 'bytes': len(raw), 'sha256': digest(raw),
                'dimensions': list(im.size), 'pixel_sha256': digest(im.mode.encode()+str(im.size).encode()+im.tobytes())}


def sources(root):
    rows = [json.loads(line) for line in (root/'cohort.jsonl').read_text().splitlines() if line.strip()]
    return sorted({url for row in rows for url in (row.get('image') or [])})


def validate_assets(root, deep=False):
    root = Path(root).resolve()
    manifest = json.loads((root/'image-assets/manifest.json').read_text())
    if manifest['version'] != VERSION or manifest['cohort_sha256'] != digest((root/'cohort.jsonl').read_bytes()):
        raise ValueError('Input asset cohort binding changed')
    if set(manifest['images']) != set(sources(root)):
        raise ValueError('Input assets must cover exactly the fixed cohort URLs')
    for url, record in manifest['images'].items():
        path = (root/record['relative_path']).resolve()
        if not path.is_relative_to(root/'image-assets') or not path.is_file():
            raise ValueError('Input asset path outside the frozen asset directory')
        if deep:
            actual = image_info(path.read_bytes())
            if actual != {k: record[k] for k in actual}:
                raise ValueError('Frozen input pixels or bytes changed')
    return manifest


def prepare(root, opener=urllib.request.urlopen, sleep=time.sleep):
    root = Path(root).resolve()
    directory = root/'image-assets'; directory.mkdir(parents=True, exist_ok=True)
    if (directory/'manifest.json').exists():
        return validate_assets(root, deep=True)
    records = {}
    for url in sources(root):
        # Fixed source URLs, never search for substitute images on download failure.
        if not url.startswith('https://raw.githubusercontent.com/'):
            raise ValueError('Unexpected MMBC source image host')
        stem = hashlib.sha256(url.encode()).hexdigest()
        path = directory/(stem+'.image')
        if not path.exists():
            last = None
            for attempt in range(3):
                try:
                    with opener(url, timeout=60) as response:
                        raw = response.read(MAX_BYTES+1)
                    image_info(raw)
                    temporary = path.with_suffix('.tmp')
                    temporary.write_bytes(raw); temporary.replace(path)
                    break
                except Exception as exc:
                    last = exc
                    if attempt == 2: raise
                    sleep(2 ** attempt)
            if not path.exists(): raise last
        records[url] = {'relative_path': str(path.relative_to(root)), **image_info(path.read_bytes())}
    manifest = {'version': VERSION, 'cohort_sha256': digest((root/'cohort.jsonl').read_bytes()), 'images': records}
    atomic(directory/'manifest.json', manifest)
    return validate_assets(root, deep=True)


def stage_images(spec, workspace):
    root = Path(spec['campaign_root']).resolve()
    manifest_path = root/'image-assets/manifest.json'
    plan = json.loads((root/'plan.json').read_text())
    if digest(manifest_path.read_bytes()) != plan['definition']['input_images_sha256']:
        raise ValueError('Frozen asset manifest changed')
    manifest = json.loads(manifest_path.read_text()); records = []
    for index, url in enumerate(spec.get('image') or []):
        record = manifest['images'][url]
        source = (root/record['relative_path']).resolve()
        if not source.is_relative_to(root/'image-assets') or digest(source.read_bytes()) != record['sha256']:
            raise ValueError('Frozen input image changed')
        destination = Path(workspace)/f'input_image_{index}'
        shutil.copyfile(source, destination)
        if digest(destination.read_bytes()) != record['sha256']:
            raise ValueError('Staged input image bytes differ')
        records.append({'path': str(destination), 'sha256': record['sha256'], 'media_type': record['media_type']})
    return records


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True); ap.add_argument('--prepare', action='store_true')
    a = ap.parse_args(); data = prepare(a.root) if a.prepare else validate_assets(a.root, deep=True)
    print(json.dumps({'images': len(data['images']), 'bytes': sum(r['bytes'] for r in data['images'].values()), 'model_calls': 0}))
