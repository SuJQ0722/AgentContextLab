#!/usr/bin/env python3
"""Render the table wrapping gallery from deterministic synthetic fixtures."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hermes-agent"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/table-wrap-cases')
    parser.add_argument('--renderer', type=Path, help='Optional renderer snapshot for before/after comparison')
    parser.add_argument('--case', help='Render a single fixture')
    parser.add_argument('--prefix', default='')
    args = parser.parse_args()
    import pymupdf

    if args.renderer:
        spec = importlib.util.spec_from_file_location('gallery_renderer', args.renderer)
        renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(renderer)
    else:
        from plugins.context_engine.visual import render as renderer

    fixtures = json.loads((ROOT / 'docs/table-wrap-cases/fixtures.json').read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    for name, fixture in fixtures.items():
        if args.case and args.case != name:
            continue
        data = renderer._blocks_to_pdf_bytes(
            fixture['blocks'], None, 10, 1000, fixture.get('max_height', 1800), 100,
            fit_to_content_height=True,
        )
        stem = args.prefix + name
        (args.output / f'{stem}.pdf').write_bytes(data)
        with pymupdf.open(stream=data, filetype='pdf') as doc:
            for index, page in enumerate(doc, 1):
                page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(
                    args.output / f'{stem}-{index}.png')
            print(f'{stem}: {len(doc)} page(s)')


if __name__ == '__main__':
    main()
