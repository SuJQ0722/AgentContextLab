"""Independent BC DSH entry: bounded renderer and final verified hosted ten images."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
import dsh_bounded_bc_worker_v1 as parent
from lab import ROOT

BOUNDED_SOURCE_FILES=list(dict.fromkeys(parent.BOUNDED_SOURCE_FILES+[
 'scripts/'+n for n in ('dsh_hosted_bc_worker_v1.py','dsh_bounded_bc_worker_v1.py',
 'dsh_hosted_wire_v1.mjs','dsh_hosted_transport_bridge_v1.py','verified_hosted_images_v3.py',
 'verified_canvas_registry_cache.py','recent_ten_images_transport_v1.py','bounded_ten_image_guard_v1.py',
 'bounded_visual_request_guard_v1.py','visual_transport_runtime_v2.py','info_loss_phase4_url.py')]))

def main():
 p=argparse.ArgumentParser(add_help=False);p.add_argument('--config',type=Path,required=True);a,_=p.parse_known_args()
 cfg=json.loads(a.config.read_text())
 if cfg.get('transport_runtime_version')!='visual-transport-runtime-v2' or cfg.get('image_transport')!='verified-imgbb-url-v1' or cfg.get('bounded_max_images')!=10 or cfg.get('bounded_request_protocol')!='bounded-multimodal-recent-ten-v1':raise ValueError('Explicit hosted recent-ten configuration required')
 original=parent.native.command
 def command(root,harness,prompt,env):
  old=str(ROOT/'scripts/dsh_bounded_wire_guard_v1.mjs');new=str(ROOT/'scripts/dsh_hosted_wire_v1.mjs')
  if env.get('NODE_OPTIONS','').count(old)!=1:raise ValueError('Expected one inner bounded guard')
  env['NODE_OPTIONS']=env['NODE_OPTIONS'].replace(old,new)
  metrics=Path(env['ACL_BOUNDED_WIRE_LEDGER']).parent
  env['ACL_HOSTED_DSH_LEDGER']=str(metrics/'hosted-images-wire-dsh-v1.jsonl');env['ACL_HOSTED_DSH_CACHE']=str(metrics/'hosted-image-cache')
  (metrics.parent.parent/'hosted-dsh-protocol.json').write_text(json.dumps({'version':'dsh-hosted-wire-v1','max_images':10,'image_transport':'verified-imgbb-url-v1','wire_ledger':env['ACL_HOSTED_DSH_LEDGER'],'prior_image_observer_stage':'pre_retention_and_pre_url_replacement','max_failed_identical_sends':2,'fetch_wall_timeout_seconds':300,'image_preparation_timeout_seconds':600},indent=2))
  return original(root,harness,prompt,env)
 with patch.object(parent.native,'command',command):parent.main()

if __name__=='__main__':main()
