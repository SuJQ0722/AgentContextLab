#!/usr/bin/env python3
"""Expand the review matrix locally. Never starts SCO or an evaluation."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def expand(plan):
    if plan.get('launch_authorized') is not False:
        raise ValueError('This review-only planner requires launch_authorized=false')
    resource = plan['instance']
    if resource != dict(cpu_count=8, memory_gib=32, gpu_count=0, worker_concurrency=32):
        raise ValueError('Resource request differs from the user review plan')
    cells = []
    for group in plan['groups']:
        for harness in group['harnesses']:
            for method in group['methods']:
                cells.append(dict(id=f"{group['experiment']}/{harness}/{method}",
                                  experiment=group['experiment'], harness=harness, method=method,
                                  priority=group['priority'], status=group['status'],
                                  **resource))
    if len({c['id'] for c in cells}) != len(cells):
        raise ValueError('Duplicate instance assignment')
    return dict(state='review_only_not_submittable', cloud=plan['cloud'], cells=cells,
                working_directory=plan.get('working_directory'),
                output_root=plan.get('output_root'), output_policy=plan.get('output_policy'),
                tool_policy=plan.get('tool_policy'),
                totals=dict(instances=len(cells), vcpus=len(cells)*resource['cpu_count'],
                            memory_gib=len(cells)*resource['memory_gib'],
                            worker_slots=len(cells)*resource['worker_concurrency']),
                required_gates=plan['required_gates'],
                os_process_count='unmeasured; workers have child processes',
                old_results='preserved, never automatically imported into the repaired version')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=ROOT/'configs/sco-review-plan.json')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    value = expand(json.loads(args.plan.read_text()))
    result = json.dumps(value, ensure_ascii=False, indent=2)+'\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(result)
    else:
        print(result, end='')


if __name__ == '__main__':
    main()
