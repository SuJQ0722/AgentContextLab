#!/usr/bin/env python3
"""Offline, lossless decoded-pixel tiling of explicitly identified rendered canvases.

This is a new layout variant, not a renderer or a provider image-token estimator.
Native evidence is copied byte-for-byte and never tiled. No network calls.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from PIL import Image

VERSION = 'canvas-vertical-tiles-v1'


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pixel_hash(image):
    """Hash dimensions and decoded RGBA8 pixels; not an encoded-file digest."""
    rgba = image.convert('RGBA')
    header = json.dumps(['RGBA8', *rgba.size], separators=(',', ':')).encode()
    return hashlib.sha256(header + b'\0' + rgba.tobytes()).hexdigest()


def read_canvas(path):
    with Image.open(path) as image:
        if image.format != 'PNG' or image.mode not in {'RGB', 'RGBA', 'L', 'LA', 'P'}:
            raise ValueError('Rendered canvas must be an 8-bit RGB/RGBA/L/LA/P PNG')
        if getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Animated canvases are unsupported')
        image.load()
        return image.convert('RGBA')


def intervals(height, max_height, overlap):
    if not 1 <= max_height <= 1536 or not 0 <= overlap < max_height:
        raise ValueError('Require 1 <= max_height <= 1536 and 0 <= overlap < max_height')
    if height < 1:
        raise ValueError('Image height must be positive')
    start = 0
    while True:
        end = min(height, start + max_height)
        yield start, end
        if end == height:
            break
        start = end - overlap


def verify_manifest(manifest_path):
    """Verify all files, exact ordered coverage, overlap pixels and reconstruction."""
    manifest_path = Path(manifest_path)
    root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text())
    if manifest['variant'] != VERSION:
        raise ValueError('Unsupported variant')
    proofs = []
    for record in manifest['images']:
        original = root / record['original_file']
        if file_hash(original) != record['original_file_sha256']:
            raise ValueError('Original file hash mismatch')
        if record['kind'] == 'native_evidence':
            if record['tiles'] or record['output_files'] != [record['original_file']]:
                raise ValueError('Native evidence must remain an untouched single file')
            proofs.append({'id': record['id'], 'native_bytes_preserved': True})
            continue
        if record['kind'] != 'rendered_canvas':
            raise ValueError('Unknown image kind')
        original_image = read_canvas(original)
        width, height = original_image.size
        if [width, height] != record['dimensions'] or pixel_hash(original_image) != record['original_pixel_sha256']:
            raise ValueError('Original pixel metadata mismatch')
        expected = list(intervals(height, manifest['max_height'], manifest['overlap']))
        if len(record['tiles']) != len(expected):
            raise ValueError('Missing or additional tile')
        if record['output_files'] != [tile['file'] for tile in record['tiles']]:
            raise ValueError('Output ordering mismatch')
        reconstructed = Image.new('RGBA', (width, height))
        counts = [0] * height
        for index, (tile, (start, end)) in enumerate(zip(record['tiles'], expected)):
            if tile['index'] != index or tile['box'] != [0, start, width, end]:
                raise ValueError('Tile coordinate/order mismatch or coverage gap')
            path = root / tile['file']
            if file_hash(path) != tile['file_sha256']:
                raise ValueError('Tile file hash mismatch')
            image = read_canvas(path)
            if image.size != (width, end - start) or pixel_hash(image) != tile['pixel_sha256']:
                raise ValueError('Tile pixel metadata mismatch')
            # Compare entire tiles, including overlapping rows, to the source.
            if image.tobytes() != original_image.crop((0, start, width, end)).tobytes():
                raise ValueError('Tile pixels differ from original')
            reconstructed.paste(image, (0, start))
            for row in range(start, end):
                counts[row] += 1
        same = reconstructed.tobytes() == original_image.tobytes()
        if min(counts) < 1 or not same:
            raise ValueError('Incomplete or inexact reconstruction')
        proofs.append({'id': record['id'], 'all_source_rows_covered': True,
                       'minimum_row_coverage': min(counts), 'maximum_row_coverage': max(counts),
                       'duplicate_overlap_rows': sum(count - 1 for count in counts),
                       'reconstructed_pixel_sha256': pixel_hash(reconstructed),
                       'reconstruction_pixel_identical': same})
    return proofs


def tile_images(spec, output, max_height=1536, overlap=32):
    """Write a new immutable artifact directory from ordered {id,kind,path} entries."""
    list(intervals(1, max_height, overlap))
    entries = spec['images']
    if not entries or len({item['id'] for item in entries}) != len(entries):
        raise ValueError('Require nonempty images with unique IDs')
    for item in entries:
        if item['kind'] not in {'rendered_canvas', 'native_evidence'}:
            raise ValueError('Explicit kind rendered_canvas/native_evidence is required')
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('Output exists; use verify or choose a new artifact directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.' + output.name + '-', dir=output.parent))
    try:
        records = []
        for index, item in enumerate(entries):
            source = Path(item['path']).resolve(strict=True)
            suffix = '.png' if item['kind'] == 'rendered_canvas' else source.suffix
            original_name = f'image-{index:03d}-original{suffix}'
            original = temporary / original_name
            shutil.copyfile(source, original)
            record = {'id': item['id'], 'kind': item['kind'], 'input_path': str(source),
                      'original_file': original_name, 'original_file_sha256': file_hash(original),
                      'tiles': [], 'output_files': [original_name]}
            if item['kind'] == 'rendered_canvas':
                image = read_canvas(original)
                width, height = image.size
                record.update(dimensions=[width, height], original_pixel_sha256=pixel_hash(image),
                              pixel_encoding='RGBA8', output_files=[])
                for tile_index, (start, end) in enumerate(intervals(height, max_height, overlap)):
                    cropped = image.crop((0, start, width, end))
                    name = f'image-{index:03d}-tile-{tile_index:03d}.png'
                    cropped.save(temporary / name, format='PNG')
                    record['tiles'].append({'index': tile_index, 'box': [0, start, width, end],
                                            'file': name, 'file_sha256': file_hash(temporary / name),
                                            'pixel_sha256': pixel_hash(cropped)})
                    record['output_files'].append(name)
            records.append(record)
        manifest = {'variant': VERSION, 'max_height': max_height, 'overlap': overlap,
                    'coordinate_convention': 'half-open [left, top, right, bottom], source pixels',
                    'resampling': 'none', 'images': records,
                    'limitations': ['New layout changes image count and may change provider token usage/caching.',
                                    'Pixel equivalence does not establish semantic readability or benchmark parity.',
                                    'Caller must correctly label rendered canvases; native evidence is never tiled.']}
        path = temporary / 'manifest.json'
        path.write_text(json.dumps(manifest, indent=2) + '\n')
        manifest['verification'] = verify_manifest(path)
        path.write_text(json.dumps(manifest, indent=2) + '\n')
        temporary.rename(output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output / 'manifest.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--max-height', type=int, default=1536)
    parser.add_argument('--overlap', type=int, default=32)
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_manifest(args.verify), indent=2))
    elif args.spec and args.out:
        spec = json.loads(args.spec.read_text())
        for item in spec['images']:
            item['path'] = str((args.spec.resolve().parent / item['path']).resolve())
        path = tile_images(spec, args.out, args.max_height, args.overlap)
        print(json.dumps({'manifest': str(path), 'verified': True}))
    else:
        parser.error('Provide --verify MANIFEST or both --spec SPEC and --out DIRECTORY')


if __name__ == '__main__':
    main()
