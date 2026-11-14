"""New core-only entry binding; preserve old worker guards and frozen source SHAs.

A fresh process explicitly opts into core_recent10. The inherited turns500
entry still validates actual constructor limits, route contracts and tool guards.
The existing wire ledger path is preserved; every new row declares the new
transport version and records any discarded native occurrence.
"""
import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import core_recent_ten_transport_v22 as core
import hermes_canvas_budget_worker_v11 as budget_worker
import hermes_turns500_worker_v12 as turns_worker
import hermes_visual_inline_retry_worker_v4 as visual_worker
import inline_visual_transport_v1 as frozen_transport

VERSION = 'hermes-core-recent-ten-worker-v23'
TRANSPORT_VERSION = core.VERSION


def validate(spec, config):
    for document in (spec, config):
        if document.get('native_image_policy') != 'core_recent10' or document.get('core_transport_version') != TRANSPORT_VERSION:
            raise ValueError('Explicit new core image policy/version required in spec and config')
        if document.get('controlled_spec_path') or document.get('calibration_not_scored'):
            raise ValueError('Controlled or calibration tasks cannot use core image deletion')
    if (spec.get('harness') != 'hermes' or spec.get('strategy') != 'visual' or
            spec.get('experiment_kind') not in ('mmbc', 'bc', 'rq3')):
        raise ValueError('Only explicitly typed core Hermes visual tasks supported')
    policy = config.get('visual_image_retention', {})
    if policy.get('max_images_per_request') != 10 or policy.get('page_budget') != {'history':5, 'recent':2}:
        raise ValueError('Core transport requires explicit last-ten and five/two canvas caps')
    if policy.get('max_request_bytes') != budget_worker.REQUEST_LIMIT:
        raise ValueError('Existing explicit 32MiB request envelope required')


def transform(body, **kwargs):
    wire, audit = core.transform(body, **kwargs, policy='core_recent10', harness='hermes')
    images = audit['selection']['final_guard']['images']
    canvas = [image for image in images if image.get('rendered_canvas') is True]
    audit['canvas_budget_recovery'] = {
        'version': VERSION, 'verified_canvas_count': len(canvas),
        'canvas_base64_bytes': sum(4*((image['bytes']+2)//3) for image in canvas),
        'canvas_base64_limit': None, 'total_request_limit': kwargs.get('max_body_bytes', budget_worker.REQUEST_LIMIT),
        'native_evidence_modified': not audit['native_evidence_preserved'],
        'native_images_removed': audit['native_images_removed'],
        'pages_merged': False, 'pixels_reencoded': False,
        'budget_applies_after_explicit_page_selection': True}
    return wire, audit


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args, _ = parser.parse_known_args()
    spec = json.loads(args.spec.read_text())
    config_path = Path(spec['config_path'])
    config = json.loads(config_path.read_text())
    validate(spec, config)
    path = args.out / 'metrics/core-image-policy-binding-v23.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    binding = {'version': VERSION, 'core_transport_version': TRANSPORT_VERSION,
               'native_image_policy': 'core_recent10', 'controlled_native_deletion_authorized': False,
               'spec_sha256': hashlib.sha256(args.spec.read_bytes()).hexdigest(),
               'config_sha256': hashlib.sha256(config_path.read_bytes()).hexdigest(),
               'harness': 'hermes', 'strategy': spec['strategy'], 'experiment_kind': spec['experiment_kind'],
               'actual_wire_ledger': 'metrics/inline-images-wire-v1.jsonl',
               'wire_schema_version': TRANSPORT_VERSION,
               'turn_limit_entry': 'hermes_turns500_worker_v12',
               'route_and_tool_guards_inherited': True, 'observer_model_calls': 0}
    path.write_text(json.dumps(binding, indent=2) + '\n')
    # Do not patch _ORIGINAL_TRANSFORM alone: the old recovery wrapper would
    # falsely report native_evidence_modified=False after core image deletion.
    with patch.object(budget_worker, 'transform', transform), \
         patch.object(frozen_transport, 'transport_version', lambda *_a, **_k: TRANSPORT_VERSION), \
         patch.object(visual_worker, 'transport_version', lambda *_a, **_k: TRANSPORT_VERSION):
        turns_worker.main()


if __name__ == '__main__':
    main()
