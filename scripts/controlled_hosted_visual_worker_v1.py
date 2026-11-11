"""Independent visual-only fixed-prefix recovery, with honest final-wire gates."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from lab import ROOT, environment
import controlled_native_worker_bounded_v1 as bounded
from visual_transport_runtime_v2 import install as runtime_install, VERSION as RUNTIME
from verified_hosted_images_v3 import install as hosted_install, VerifiedImageHost, VERSION as HOSTED


def read(path):
    return json.loads(Path(path).read_text())


def validate(job, out):
    source_path = Path(job['controlled_spec_path']).resolve()
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != job['controlled_spec_sha256']:
        raise ValueError('Frozen controlled source changed')
    source = read(source_path)
    if source.get('method') != 'visual' or job.get('strategy') != 'visual':
        raise ValueError('Only failed visual arms are authorized here')
    for field in ('question_id', 'repeat', 'model', 'question'):
        if source[field] != job[field]:
            raise ValueError('Original controlled identity changed')
    parent = Path(job['campaign_root']).resolve()
    if not parent.is_relative_to(ROOT / 'outputs/campaigns/visual-hosted-failure-retry-v1/cells'):
        raise ValueError('Independent hosted retry namespace required')
    if not out.resolve().is_relative_to(parent / 'jobs'):
        raise ValueError('Wrong output namespace')
    spec = {**source, 'config_path': job['config_path']}
    with patch.object(bounded, 'OUTPUT_ROOT', parent):
        bounded.validate_spec(spec, out)
    cfg = read(job['config_path'])
    if cfg.get('image_transport') != HOSTED or cfg.get('transport_runtime_version') != RUNTIME:
        raise ValueError('Explicit hosted runtime configuration required')
    return spec, cfg


def annotate(value, out):
    value = copy.deepcopy(value)
    rows = []
    path = out / 'metrics/hosted-images-wire-v3.jsonl'
    if path.exists():
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    allowed = [r for r in rows if r.get('decision') == 'allow']
    removed_native = sum(sum(x.get('origin') == 'native' for x in r['selection']['removed'])
                         for r in allowed)
    removed_canvas = sum(sum(x.get('origin') == 'canvas' for x in r['selection']['removed'])
                         for r in allowed)
    value.update(pre_retention_control_passed=value.get('passed'),
                 final_wire_observed=bool(allowed),
                 final_wire_native_removals=removed_native,
                 final_wire_canvas_removals=removed_canvas,
                 final_wire_native_identity_preserved=bool(allowed) and removed_native == 0,
                 old_matched_three_arm_comparison_valid=False,
                 recovery_protocol='controlled-hosted-visual-retry-v1',
                 image_transport=HOSTED)
    # The old native gate ran before retention. Never claim it passed on actual
    # model evidence if send-time retention removed any original native image.
    value['passed'] = bool(value.get('passed') and allowed and removed_native == 0)
    return value


def main():
    from compression_inline_only import removed
    removed()


if __name__ == '__main__':
    main()
