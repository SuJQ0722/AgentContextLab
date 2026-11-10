#!/usr/bin/env python3
"""Independent MMBC entry with a ten-total-image wire limit; no silent fitting."""
import argparse
import hashlib
import json
from pathlib import Path
from lab import ROOT
import hermes_bounded_mmbc_worker_v1 as previous

PROTOCOL = 'bounded-multimodal-ten-images-v1'
BOUNDED_SOURCE_FILES = ['scripts/'+name for name in (
    'bounded_ten_image_guard_v1.py', 'bounded_visual_request_guard_v1.py',
    'hermes_bounded_mmbc_worker_v1.py', 'bounded_multimodal_renderer_v1.py',
    'bounded_lossless_transport_v1.py', 'hermes_bc_worker_v3.py', 'mmbc_input_images.py',
    'mmbc_vanilla_renderer.py')]

def validate(spec, config, out):
    previous.validate(spec, config, out)
    if any(value.get('bounded_request_protocol') != PROTOCOL or type(value.get('bounded_max_images')) is not int
           or value['bounded_max_images'] != 10 for value in (spec, config)):
        raise ValueError('Spec and config must explicitly freeze the independent ten-image protocol')
    if any(value.get('bounded_benchmark') != 'mmbc100' for value in (spec, config)):
        raise ValueError('Independent ten-image worker supports only explicit MMBC100')
    if not isinstance(spec.get('question_id'), str) or not spec['question_id'].startswith('mmbc_'):
        raise ValueError('Expected original MMBC question identity')
    if not isinstance(spec.get('image'), list) or not spec['image']:
        raise ValueError('Expected original MMBC native-image references')
    root = Path(spec.get('campaign_root', '/missing')).resolve()
    config_path = Path(spec.get('config_path', '/missing')).resolve()
    out = Path(out).resolve()
    if not root.is_relative_to((ROOT/'outputs/campaigns').resolve()) or root == (ROOT/'outputs/campaigns').resolve():
        raise ValueError('A separate MMBC campaign namespace is required')
    if not out.is_relative_to(root/'jobs') or not config_path.is_relative_to(root):
        raise ValueError('Attempt/config must belong to the new campaign namespace')
    old_roots = [ROOT/'outputs/campaigns'/name for name in (
        'mmbc-vera-bounded-retry-v1', 'bc-bounded-retry-v1', 'rq3-bounded-failure-retry-v1')]
    if any(root.is_relative_to(path.resolve()) for path in old_roots):
        raise ValueError('Existing bounded scientific namespace must not be reused')
    if not spec.get('config_sha256') or hashlib.sha256(config_path.read_bytes()).hexdigest() != spec['config_sha256']:
        raise ValueError('Explicit frozen configuration SHA required')
    if config.get('bounded_transport_encoding') != 'bounded-canvas-lossless-webp-v1':
        raise ValueError('Explicit unchanged lossless WebP transport required')
    return True

def main():
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--spec',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args,_=parser.parse_known_args();spec=json.loads(args.spec.read_text())
    config=json.loads(Path(spec['config_path']).read_text());out=args.out.resolve()
    validate(spec,config,out)
    import hermes_bc_worker_v3 as native
    from mmbc_input_images import stage_images
    from bounded_ten_image_guard_v1 import install as install_guard
    original_configure,original_stage=native.configure_engine,native.stage_images
    def configure(engine,strategy,policy):
        original_configure(engine,strategy,policy)
        if strategy=='visual':
            from plugins.context_engine.visual import render
            from bounded_multimodal_renderer_v1 import install
            install(render)
            if getattr(engine,'_text_only',False):
                from mmbc_vanilla_renderer import install as vanilla_install
                vanilla_install(render)
            from bounded_lossless_transport_v1 import install as encoding_install
            encoding_install(render)
            if getattr(engine,'_history_scale',None)!=.75:
                raise ValueError('Live renderer differs from frozen .75 scale')
        guard=install_guard(out/'metrics/bounded-ten-image-request-guard.jsonl',
                            rendered_registry=lambda:previous.registered_pages(out/'context_images'))
        out.mkdir(parents=True,exist_ok=True)
        sources=['scripts/hermes_bounded_mmbc_ten_image_worker_v1.py',*BOUNDED_SOURCE_FILES]
        (out/'bounded-protocol.json').write_text(json.dumps({
            'version':PROTOCOL,'renderer_protocol':previous.PROTOCOL,'far_scale':.75,'recent_scale':1.,
            'max_canvas_size':[1024,2048],'detail':'high','vertical_merge':False,
            'guard_max_images':10,'guard_max_request_bytes':8*1024*1024,
            'count_scope':'all native and canvas image_url occurrences',
            'overflow_policy':'reject before network; no deletion, merging, rescaling, or automatic retry added',
            'native_pixels_unchanged':True,'transport_encoding':config['bounded_transport_encoding'],
            'guard':guard,'implementation_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()for p in sources}
        },indent=2))
    native.stage_images,native.configure_engine=stage_images,configure
    try:native.main()
    finally:native.stage_images,native.configure_engine=original_stage,original_configure

if __name__=='__main__':main()
