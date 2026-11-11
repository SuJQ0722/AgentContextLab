"""Three-arm controlled continuation with immutable measured visual targets.

No source prefix, original native evidence, caption, or table content is replaced.
Only a successfully validated visual control can publish a target for text arms.
"""
import argparse
import base64
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from lab import ROOT
import controlled_visual_inline_worker_v4 as parent
import controlled_native_worker_bounded_v1 as bounded
import capture_multimodal_prefix_v5 as capture
from controlled_frozen_input_reuse_v1 import stage
from bc_route_runtime_v1 import immutable_json

VERSION = 'controlled-inline-matched-retry-v8'
METHODS = ('visual', 'summary', 'window')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def target_path(root, prefix_key):
    key = hashlib.sha256(prefix_key.encode()).hexdigest()
    return Path(root) / 'control-targets' / (key + '.json')


def prepare_spec(record, root, config_path, model, target_root=None):
    """Called by new campaign preparer, never modifies historical experiment files."""
    root = Path(root).resolve()
    candidate = record.get('bounded_candidate', record['source_job'])
    path = candidate.get('spec_path') or record.get('source_spec_path')
    if not path or not Path(path).exists():
        raise ValueError('Original prefix unavailable; cannot fabricate controlled evidence')
    source = json.loads(Path(path).read_text())
    if not Path(source['prefix_path']).is_file():
        raise ValueError('Original prefix unavailable; controlled group remains blocked')
    if source.get('bounded_native_protocol') != bounded.PROTOCOL:
        raise ValueError('A bounded candidate from the original frozen prefix is required')
    prefix_key = candidate.get('prefix_key', record['job_id'].rsplit('/', 1)[0])
    method = source['method']
    if method not in METHODS:
        raise ValueError('Unsupported controlled method')
    spec = {**source, 'model': model, 'config_path': str(config_path), 'timeout_seconds': 3600,
            'controlled_retry_version': VERSION,
            'controlled_retention_policy': 'recent_rendered_text_pages_then_all_native'}
    target = target_path(target_root or root, prefix_key)
    if method != 'visual':
        spec['target_reference_path'] = str(target)
    destination = root / 'controlled-specs' / (hashlib.sha256(record['job_id'].encode()).hexdigest()+'.json')
    immutable_json(destination, spec)
    return {'controlled_spec_path': str(destination), 'controlled_spec_sha256': sha(destination),
            'controlled_method': method, 'controlled_prefix_key': prefix_key,
            'controlled_target_root': str(Path(target_root or root).resolve()), 'control_target_path': str(target),
            'controlled_retry_version': VERSION,
            'controlled_input_reuse_version': 'controlled-frozen-input-reuse-v1',
            'controlled_dependency': None if method == 'visual' else str(target)}


def valid_target(value):
    return (value.get('passed') is True and value.get('method') == 'visual'
        and value.get('native_identity_verified') is True
        and value.get('final_wire_native_identity_preserved') is True
        and value.get('final_wire_observed') is True
        and value.get('bounded_native_protocol') == bounded.PROTOCOL
        and type(value.get('first_actual_prompt_tokens')) is int
        and 0 < value['first_actual_prompt_tokens'] <= 16384
        and bool(value.get('native_hashes')) and bool(value.get('prefix_sha256')))


def publish_target(job, value):
    if job.get('controlled_method') != 'visual' or not valid_target(value):
        return False
    target = Path(job['control_target_path'])
    expected = target_path(job['campaign_root'], job.get('controlled_prefix_key', job['job_id'].rsplit('/', 1)[0]))
    if target.resolve() != expected.resolve():
        raise ValueError('Controlled target outside its frozen group')
    if target.exists():
        prior = json.loads(target.read_text())
        if not valid_target(prior) or any(prior.get(k) != value.get(k) for k in ('prefix_sha256','native_hashes','bounded_native_protocol')):
            raise ValueError('Previously published target changed scientific identity')
        return False  # First valid target is immutable, including after a timeout.
    immutable_json(target, {**copy.deepcopy(value), 'controlled_retry_version': VERSION,
                            'target_selection': 'first valid measured visual request; independent of final answer'})
    return True


def validate(job, out):
    if job.get('controlled_retry_version') != VERSION:
        raise ValueError('Explicit controlled V8 protocol required')
    path = Path(job['controlled_spec_path'])
    if sha(path) != job['controlled_spec_sha256']:
        raise ValueError('Controlled source spec changed')
    source = json.loads(path.read_text())
    if source.get('method') not in METHODS or source['method'] != job['controlled_method']:
        raise ValueError('Controlled method differs from frozen job')
    for key in ('question_id','repeat','model','question'):
        if source[key] != job[key]:
            raise ValueError('Original controlled identity changed')
    root = Path(job['campaign_root']).resolve()
    if not out.resolve().is_relative_to(root/'jobs'):
        raise ValueError('Controlled output outside campaign jobs')
    spec = {**source, 'config_path': job['config_path']}
    if source['method'] != 'visual':
        reference_root = Path(job.get('controlled_target_root', str(root))).resolve()
        if reference_root != root and (reference_root.parent != root.parent or reference_root.name not in ('controlled_bc','controlled_mmbc')):
            raise ValueError('Controlled target must be in the same campaign cell family')
        if Path(spec['target_reference_path']).resolve() != target_path(reference_root, job['controlled_prefix_key']).resolve():
            raise ValueError('Controlled target differs from frozen group')
    with patch.object(bounded, 'OUTPUT_ROOT', root.parent):
        bounded.validate_spec(spec, out)
    if source['method'] != 'visual':
        reference = json.loads(Path(spec['target_reference_path']).read_text())
        if not valid_target(reference):
            raise ValueError('Text arm awaits a valid visual target; do not execute')
    cfg = json.loads(Path(job['config_path']).read_text())
    parent.validate_routes(job, cfg)
    if cfg.get('image_transport') != parent.INLINE or cfg.get('transport_runtime_version') != parent.RUNTIME:
        raise ValueError('Inline transport required')
    return spec, cfg


def native_last_compose(original, out, current, question, native, representation):
    """Preserve every native image; explicitly trim only older rendered text pages."""
    if len(native) > 10:
        raise ValueError('Native evidence alone exceeds ten images; do not omit native pixels')
    image_positions = [i for i, part in enumerate(representation) if part.get('type') == 'image_url']
    remove = set(image_positions[:max(0, len(image_positions) - (10-len(native)))])
    retained = [copy.deepcopy(p) for i, p in enumerate(representation) if i not in remove]
    messages = original(current, question, native, retained)
    user = next(m for m in messages if m.get('role') == 'user')
    # Original compose has [intro, native..., representation...]. Every arm now
    # places native evidence after its text representation, with identical bytes.
    content = user['content']; count = len(native)
    user['content'] = [content[0], *content[1+count:], *content[1:1+count]]
    row = {'version': VERSION, 'retention_policy': 'recent_rendered_text_pages_then_all_native',
           'native_image_count': count, 'native_images_removed': 0,
           'original_canvas_count': len(image_positions), 'retained_canvas_count': len(image_positions)-len(remove),
           'removed_canvas_ordinals': [image_positions.index(i) for i in sorted(remove)],
           'rendered_text_information_truncated': bool(remove), 'pixels_reencoded_by_retention': False}
    out.mkdir(parents=True, exist_ok=True)
    with (out/'controlled-retention.jsonl').open('a') as f:
        f.write(json.dumps(row)+'\n')
    return messages


def native_first_inspection(original, expected_ids):
    """The old native checker assumes position zero; inspect identity instead.

    This helper changes only the inspection ordering, never the request messages.
    Native occurrences remain ordered and duplicates are counted individually.
    """
    def inspect(messages):
        parts = original(messages); remaining = Counter(expected_ids); native = []; other = []
        for part in parts:
            key = bounded.v5.image_ids([part])[0]
            if remaining[key]:
                native.append(part); remaining[key] -= 1
            else:
                other.append(part)
        return native + other
    return inspect


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    args, _ = parser.parse_known_args()
    job = json.loads(args.spec.read_text())
    if not args.live:
        validate(job, args.out)
        print(json.dumps({'live':False,'model_calls':0,'controlled_method':job['controlled_method'],'version':VERSION}))
        return
    annotate = parent.annotate
    def observe(value, out):
        result = annotate(value, out)
        result.update(controlled_retry_version=VERSION,
                      matched_target_source='same frozen prefix and exact native image bytes')
        publish_target(job, result)
        return result
    original_load = capture.load_images
    adapter_type = bounded.BoundedAdapter
    original_parts = bounded.v5.native_parts
    frozen_spec = json.loads(Path(job['controlled_spec_path']).read_text())
    frozen_prefix = json.loads(Path(frozen_spec['prefix_path']).read_text())
    expected = bounded.v5.image_ids(original_parts(frozen_prefix['messages']))
    class Adapter(adapter_type):
        def __init__(self, spec, out):
            super().__init__(spec, out)
            original = self.original_compose
            self.original_compose = lambda current, question, native, representation: native_last_compose(original, out, current, question, native, representation)
    with patch.object(parent, 'validate', validate), patch.object(parent, 'annotate', observe), \
         patch.object(bounded, 'BoundedAdapter', Adapter), \
         patch.object(bounded.v5, 'native_parts', native_first_inspection(original_parts, expected)), \
         patch.object(capture, 'load_images', lambda row, out: stage(row, out, original_load)):
        parent.main()
    result_path = args.out/'native-result.json'
    if result_path.exists():
        value = json.loads(result_path.read_text())
        value.update(controlled_retry_version=VERSION, calibration_not_scored=bool(job.get('calibration_not_scored')),
                     control_target_path=job['control_target_path'])
        bounded.v5.write(result_path,value)


if __name__ == '__main__':
    main()
