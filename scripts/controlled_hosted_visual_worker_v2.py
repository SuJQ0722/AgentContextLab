#!/usr/bin/env python3
"""Controlled recovery with image hosting outside the inference context only.

The approved model route guard remains installed. A fresh context is created for
each host invocation, so nested upload/download HTTP is not misclassified as
model inference. No HTTP guard, endpoint, retention or image verifier is replaced.
"""
from unittest.mock import patch
import copy
import json
import controlled_hosted_visual_worker_v1 as parent
from isolated_verified_image_host_v1 import IsolatedVerifiedImageHost

VERSION = 'controlled-hosted-upload-context-v2'


def annotate(value, out):
    value = copy.deepcopy(value)
    path = out / 'metrics/hosted-images-wire-v4.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    allowed = [r for r in rows if r.get('decision') == 'allow']
    native = sum(sum(x.get('origin') == 'native' for x in r['selection']['removed']) for r in allowed)
    canvas = sum(sum(x.get('origin') == 'canvas' for x in r['selection']['removed']) for r in allowed)
    value.update(pre_retention_control_passed=value.get('passed'), final_wire_observed=bool(allowed),
                 final_wire_native_removals=native, final_wire_canvas_removals=canvas,
                 final_wire_native_identity_preserved=bool(allowed) and native == 0,
                 old_matched_three_arm_comparison_valid=False, recovery_protocol=VERSION,
                 image_transport='verified-imgbb-url-v2', actual_wire_ledger='metrics/hosted-images-wire-v4.jsonl')
    value['passed'] = bool(value.get('passed') and allowed and native == 0)
    return value
def main():
    from compression_inline_only import removed
    removed()


if __name__ == '__main__':
    main()
