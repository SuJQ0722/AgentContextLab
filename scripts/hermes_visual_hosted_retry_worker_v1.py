"""Explicit hosted retry across MMBC, BC and frozen RQ3 scales."""
import argparse,json,os
from pathlib import Path
from lab import ROOT
from hermes_mmbc_hosted_worker_v3 import HostedRetentionVisionRecorder
from verified_hosted_images_v3 import install as hosted,VerifiedImageHost
from visual_transport_runtime_v2 import install as runtime
from verified_canvas_registry_cache import VerifiedCanvasRegistryCache

def main():
 p=argparse.ArgumentParser(add_help=False);p.add_argument('--spec',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a,_=p.parse_known_args()
 spec=json.loads(a.spec.read_text());cfg=json.loads(Path(spec['config_path']).read_text());out=a.out.resolve()
 if spec.get('visual_hosted_retry_version')!='visual-hosted-failure-retry-v1' or spec.get('image_transport')!='verified-imgbb-url-v1' or cfg.get('image_transport')!='verified-imgbb-url-v1':raise ValueError('Explicit hosted retry required')
 kind=spec['experiment_kind'];scale=spec['scale']
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
  rt=runtime(cfg['transport_runtime_policy'],out/'metrics',approved_base_url=os.environ['TOKENHUB_BASE_URL']);handles.append(rt['uninstall'])
  ht=hosted(out/'metrics',rendered_registry=cache,host=VerifiedImageHost(Path(spec['campaign_root'])/'hosted-image-cache',os.environ),approved_base_url=os.environ['TOKENHUB_BASE_URL']);handles.append(ht['uninstall'])
  (out/'bounded-protocol.json').write_text(json.dumps({'version':spec['visual_hosted_retry_version'],'experiment_kind':kind,'scale':scale,'text_only':getattr(engine,'_text_only',False),'image_transport':'verified-imgbb-url-v1','max_images':10,'actual_wire_ledger':'metrics/hosted-images-wire-v3.jsonl','archive_stage':'pre-retention inline SDK messages','native_and_canvas_counted_together':True},indent=2))
 native.configure_engine=configure;native.VisionRecorder=HostedRetentionVisionRecorder
 if kind=='mmbc':
  from mmbc_input_images import stage_images
  native.stage_images=stage_images
 try:native.main()
 finally:
  for f in reversed(handles):f()
  native.configure_engine,native.VisionRecorder,native.stage_images=old
if __name__=='__main__':main()
