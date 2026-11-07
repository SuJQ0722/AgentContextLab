#!/usr/bin/env python3
"""Freeze pilot question IDs before any paid inference or outcome inspection."""
import hashlib
import json
import argparse
from pathlib import Path
from lab import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bc100', action='store_true', help='Freeze the historical BC-100 in its original order')
    args = parser.parse_args()
    cfg = json.loads((ROOT / 'configs/experiment.json').read_text())
    if args.bc100:
        source = (ROOT / cfg['bc100']['source']).resolve()
        raw = source.read_bytes()
        rows = [dict(json.loads(line), id=f'q_{i:03d}') for i, line in enumerate(raw.decode().splitlines(), 1) if line.strip()]
        if len(rows) != 100:
            raise ValueError('BC-100 source must contain exactly 100 questions')
        destination = ROOT / 'outputs/cohorts'
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / 'bc100.jsonl'
        contents = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)
        manifest = {'datasets': {'bc100': {'source': str(source), 'dataset_sha256': hashlib.sha256(raw).hexdigest(),
            'cohort_path': str(path), 'cohort_sha256': hashlib.sha256(contents.encode()).hexdigest(),
            'selected_ids': [r['id'] for r in rows]}}}
        for target, data in [(path, contents), (destination / 'bc100-manifest.json', json.dumps(manifest, indent=2) + '\n')]:
            if target.exists() and target.read_text() != data:
                raise ValueError(f'Refusing to overwrite frozen cohort: {target}')
            target.write_text(data)
        print(json.dumps({'bc100': len(rows)}))
        return
    pilot = cfg['pilot']
    data = ROOT.parent / 'hermes-agent/Browsecomp_eval/data'
    sources = {
        'browsecomp': data / 'bc/questions_200.jsonl',
        'xbench_deepsearch': data / 'xbench_deepsearch/questions_100.jsonl',
        'browsecomp_v3': data / 'bc_v3/questions.jsonl',
        'mmbrowsecomp': data / 'mmbrowsecomp/questions.jsonl',
        'agenticdatabench': ROOT.parent / 'databench/sources/AgenticDataBench/testbed/tasks/dev.jsonl',
    }
    destination = ROOT / 'outputs/cohorts'
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {'seed': pilot['seed'], 'datasets': {}}
    for name, path in sources.items():
        raw = path.read_bytes()
        rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
        for index, row in enumerate(rows, 1):
            row.setdefault('id', f'q_{index:03d}')
        ids = [str(row['id']) for row in rows]
        if len(set(ids)) != len(ids):
            raise ValueError(f'{name}: duplicate question IDs')
        selected = sorted(rows, key=lambda row: hashlib.sha256(
            f"{pilot['seed']}:{name}:{row['id']}".encode()).digest())[:pilot['questions_per_dataset']]
        output = destination / (name + '.jsonl')
        contents = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in selected)
        if output.exists() and output.read_text() != contents:
            raise ValueError(f'Refusing to overwrite frozen cohort: {output}')
        output.write_text(contents)
        manifest['datasets'][name] = {
            'source': str(path), 'dataset_sha256': hashlib.sha256(raw).hexdigest(),
            'available_questions': len(rows), 'selected_ids': [row['id'] for row in selected],
            'cohort_path': str(output), 'cohort_sha256': hashlib.sha256(contents.encode()).hexdigest(),
        }
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k: len(v['selected_ids']) for k, v in manifest['datasets'].items()}))


if __name__ == '__main__':
    main()
