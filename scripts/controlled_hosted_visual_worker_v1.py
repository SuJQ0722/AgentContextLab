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
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--live', action='store_true')
    a = p.parse_args(); job = read(a.spec); out = a.out.resolve()
    spec, cfg = validate(job, out)
    if not a.live:
        print(json.dumps({'live': False, 'model_calls': 0, 'visual_only': True})); return
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'attempt-started.json').open('x') as f:
        json.dump({'job_id': job['job_id'], 'original_spec_sha256': job['controlled_spec_sha256']}, f)
    adapter = bounded.BoundedAdapter(spec, out)
    original_write = adapter.write
    def write(path, value):
        if Path(path).name == 'compression-control.json':
            value = annotate(value, out)
        elif Path(path).name == 'result.json' and 'control_gate' in value:
            value = copy.deepcopy(value)
            value['control_gate'] = annotate(value['control_gate'], out)
            value['old_matched_three_arm_comparison_valid'] = False
        return original_write(path, value)
    env, _ = environment(ROOT, 'hermes', job['config_path'])
    h1 = runtime_install(cfg['transport_runtime_policy'], out / 'metrics',
                         approved_base_url=env['TOKENHUB_BASE_URL'])
    h2 = hosted_install(out / 'metrics', rendered_registry=lambda: adapter.registry,
                         host=VerifiedImageHost(out / 'hosted-image-cache', env),
                         approved_base_url=env['TOKENHUB_BASE_URL'])
    try:
        with patch.object(bounded.v5, 'render_prefix', adapter.render_prefix), \
             patch.object(bounded.v5, 'compose', adapter.compose), \
             patch.object(bounded.v5, 'write', write):
            bounded.v5.run(spec, out)
    finally:
        h2['uninstall'](); h1['uninstall']()
    result = read(out / 'result.json') if (out / 'result.json').exists() else {}
    conversation = read(out / 'conversation.json') if (out / 'conversation.json').exists() else {}
    final = conversation.get('final_response') or ''
    (out / 'native-result.json').write_text(json.dumps({
        'status': 'completed' if result.get('status') == 'completed' and final else 'failed',
        'final': {'text': final}, 'source_controlled_status': result.get('status'),
        'error_type': result.get('error_type'), 'old_matched_three_arm_comparison_valid': False,
        'controlled_source_spec_sha256': job['controlled_spec_sha256']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
