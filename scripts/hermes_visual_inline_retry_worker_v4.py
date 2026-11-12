"""Direct inline image recovery across MMBC, BC and frozen RQ3 scales."""
import argparse,json,os
from pathlib import Path
from lab import ROOT
from hermes_native_vision_worker_v2 import VisionRecorder as PreviousRecorder
from inline_visual_transport_v1 import install as inline_transport, visual_max_images, visual_page_budget, transport_version
from inline_route_contract_v2 import validate_routes
from visual_transport_runtime_v4 import install as runtime
from verified_canvas_registry_cache import VerifiedCanvasRegistryCache

class InlineRetentionVisionRecorder(PreviousRecorder):
 def write(self,name,record):
  if name=='vision-wire.jsonl':
   name='vision-pre-retention.jsonl'
   record={**record,'event':'pre_retention_http_payload','wire_stage':'before_inline_image_selection',
           'not_final_wire':True,'actual_wire_ledger':'inline-images-wire-v1.jsonl'}
  return super().write(name,record)

def main():
 p=argparse.ArgumentParser(add_help=False);p.add_argument('--spec',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a,_=p.parse_known_args()
 spec=json.loads(a.spec.read_text());cfg=json.loads(Path(spec['config_path']).read_text());out=a.out.resolve()
 if spec.get('visual_hosted_retry_version')!='visual-hosted-failure-retry-v1' or spec.get('image_transport')!='inline-recent-ten-chunked-v1' or cfg.get('image_transport')!='inline-recent-ten-chunked-v1':raise ValueError('Explicit inline direct retry required')
 if spec.get('transport_runtime_version')!='visual-transport-runtime-v4' or cfg.get('transport_runtime_version')!='visual-transport-runtime-v4':raise ValueError('Explicit 429-aware transport required')
 validate_routes(spec,cfg)
 kind=spec['experiment_kind'];scale=spec['scale'];max_images=visual_max_images(cfg)
 if kind=='mmbc':
  from hermes_bounded_mmbc_worker_v1 import validate,registered_pages
  validate(spec,cfg,out);validator=registered_pages
 elif kind=='bc':
  from hermes_bounded_bc_worker_v1 import validate_bc,registered_pages
  validate_bc(spec,cfg,out);validator=lambda d:registered_pages(d,scale)
 elif kind=='rq3':
  from hermes_bounded_rq3_worker_v1 import validate,registered_pages
  validate(spec,cfg,out);validator=lambda d:registered_pages(d,scale)
 else:raise ValueError('Unknown scientific cell')
 import hermes_bc_worker_v3 as native
 old=(native.configure_engine,native.VisionRecorder,native.stage_images);handles=[]
 def configure(engine,strategy,policy):
  old[0](engine,strategy,policy)
  from plugins.context_engine.visual import render
  if kind=='mmbc':
   from bounded_multimodal_renderer_v1 import install
  else:
   from rq3_bounded_renderer_v2 import install
  install(render)
  if getattr(engine,'_text_only',False):
   from mmbc_vanilla_renderer import install as vanilla
   vanilla(render)
  from bounded_lossless_transport_v1 import install as encoding
  encoding(render)
  if engine._history_scale!=scale:raise ValueError('Scale mismatch')
  def observe(row):
   path=out/'metrics/registry-cache-v2.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
   with path.open('a')as f:f.write(json.dumps(row)+'\n')
  cache=VerifiedCanvasRegistryCache(out/'context_images',validator,observer=observe)
  rt=runtime(cfg['transport_runtime_policy'],out/'metrics',approved_base_url=os.environ['TOKENHUB_BASE_URL'],route_policy=cfg['model_route_policy'],worker_key=spec['job_id'],deadline_seconds=spec['timeout_seconds'],gateway_proxy=cfg['gateway_proxy']);handles.append(rt['uninstall'])
  ht=inline_transport(out/'metrics',rendered_registry=cache,approved_base_url=os.environ['TOKENHUB_BASE_URL'],max_images=max_images,page_budget=visual_page_budget(cfg));handles.append(ht['uninstall'])
  (out/'bounded-protocol.json').write_text(json.dumps({'version':spec['visual_hosted_retry_version'],'experiment_kind':kind,'scale':scale,'text_only':getattr(engine,'_text_only',False),'image_transport':transport_version(max_images, visual_page_budget(cfg)),'max_images':max_images,'canvas_page_budget':visual_page_budget(cfg),'actual_wire_ledger':'metrics/inline-images-wire-v1.jsonl','archive_stage':'pre-retention inline SDK messages','native_and_canvas_counted_together':True},indent=2))
 native.configure_engine=configure;native.VisionRecorder=InlineRetentionVisionRecorder
 if kind=='mmbc':
  from mmbc_input_images import stage_images
  native.stage_images=stage_images
 try:native.main()
 finally:
  for f in reversed(handles):f()
  native.configure_engine,native.VisionRecorder,native.stage_images=old
if __name__=='__main__':main()
