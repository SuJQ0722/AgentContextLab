#!/usr/bin/env python3
"""New MMBC phase: retain only the last ten image blocks at final send."""
import argparse
import hashlib
import json
from pathlib import Path
from lab import ROOT
import hermes_bounded_mmbc_ten_image_worker_v1 as ten
import hermes_bounded_mmbc_worker_v1 as previous
from hermes_native_vision_worker_v2 import VisionRecorder
from recent_ten_images_transport_v1 import VERSION as PROTOCOL,RETENTION

BOUNDED_SOURCE_FILES=list(dict.fromkeys([
    'scripts/recent_ten_images_transport_v1.py','scripts/hermes_bounded_mmbc_ten_image_worker_v1.py',
    'scripts/hermes_native_vision_worker_v2.py',*ten.BOUNDED_SOURCE_FILES]))

class RetentionVisionRecorder(VisionRecorder):
    """Keep pre-retention routing checks, label them honestly as pre-retention."""
    def write(self,name,record):
        if name=='vision-wire.jsonl':
            name='vision-pre-retention.jsonl'
            record={**record,'event':'pre_retention_http_payload','wire_stage':'before_authorized_last_10_retention',
                    'not_final_wire':True,'actual_wire_ledger':'recent-ten-images-wire.jsonl'}
        return super().write(name,record)

def validate(spec,config,out):
    if any(value.get('bounded_request_protocol')!=PROTOCOL or value.get('bounded_image_retention')!=RETENTION
           for value in(spec,config)):
        raise ValueError('Independent explicit MMBC last-ten retention phase required')
    # Share scope, immutable namespace, geometry, count, and configuration hash
    # checks without rewriting either the frozen config or the scientific spec.
    ten.validate({**spec,'bounded_request_protocol':ten.PROTOCOL},
                 {**config,'bounded_request_protocol':ten.PROTOCOL},out)
    return True

def main():
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--spec',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args,_=parser.parse_known_args();spec=json.loads(args.spec.read_text())
    config=json.loads(Path(spec['config_path']).read_text());out=args.out.resolve();validate(spec,config,out)
    import hermes_bc_worker_v3 as native
    from mmbc_input_images import stage_images
    from recent_ten_images_transport_v1 import install
    original_configure,original_stage,original_recorder=native.configure_engine,native.stage_images,native.VisionRecorder
    def configure(engine,strategy,policy):
        original_configure(engine,strategy,policy)
        if strategy=='visual':
            from plugins.context_engine.visual import render
            from bounded_multimodal_renderer_v1 import install as install_renderer
            install_renderer(render)
            if getattr(engine,'_text_only',False):
                from mmbc_vanilla_renderer import install as install_vanilla
                install_vanilla(render)
            from bounded_lossless_transport_v1 import install as install_encoding
            install_encoding(render)
            if getattr(engine,'_history_scale',None)!=.75:raise ValueError('Frozen .75 scale changed')
        transport=install(out/'metrics/recent-ten-images-wire.jsonl',
                          rendered_registry=lambda:previous.registered_pages(out/'context_images'))
        out.mkdir(parents=True,exist_ok=True)
        sources=['scripts/hermes_bounded_mmbc_recent_ten_worker_v1.py',*BOUNDED_SOURCE_FILES]
        (out/'bounded-protocol.json').write_text(json.dumps({
            'version':PROTOCOL,'renderer_protocol':previous.PROTOCOL,'far_scale':.75,'recent_scale':1.,
            'max_canvas_size':[1024,2048],'detail':'high','vertical_merge':False,
            'guard_max_images':10,'guard_max_request_bytes':8*1024*1024,'retention_policy':RETENTION,
            'retention_scope':'all native and canvas image_url occurrences in message/content order',
            'older_image_blocks_removed':True,'text_and_tools_unchanged':True,'native_pixels_unchanged_when_retained':True,
            'full_visual_history_retained':False,'phase_not_comparable_as_unchanged_retention':True,
            'sdk_and_request_archive_stage':'pre_retention; actual wire is defined by recent-ten-images-wire.jsonl mapping and body SHA',
            'transport_encoding':config['bounded_transport_encoding'],'transport':transport,
            'implementation_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()for p in sources}
        },indent=2))
    native.stage_images,native.configure_engine,native.VisionRecorder=stage_images,configure,RetentionVisionRecorder
    try:native.main()
    finally:native.stage_images,native.configure_engine,native.VisionRecorder=original_stage,original_configure,original_recorder

if __name__=='__main__':main()
