#!/usr/bin/env python3
"""Independent MMBC runtime: recent-ten images, cached registry, bounded transport."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from lab import ROOT
import hermes_bounded_mmbc_recent_ten_worker_v1 as parent
import recent_ten_images_transport_v1 as retention
from visual_transport_runtime_v2 import install as install_runtime, VERSION, DEFAULT_POLICY
from verified_canvas_registry_cache import VerifiedCanvasRegistryCache


def main():
    p=argparse.ArgumentParser(add_help=False);p.add_argument('--spec',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a,_=p.parse_known_args();spec=json.loads(a.spec.read_text());cfg=json.loads(Path(spec['config_path']).read_text())
    if spec.get('transport_runtime_version')!=VERSION or cfg.get('transport_runtime_version')!=VERSION:
        raise ValueError('Explicit new transport runtime spec and config required')
    policy=cfg['transport_runtime_policy'];original=retention.install;handles=[]
    def composed(reportpath,*,rendered_registry):
        cachelog=a.out.resolve()/'metrics/registry-cache-v2.jsonl'
        def observe(row):
            cachelog.parent.mkdir(parents=True,exist_ok=True)
            with cachelog.open('a')as f:f.write(json.dumps(row)+'\n')
        cache=VerifiedCanvasRegistryCache(a.out.resolve()/'context_images',parent.previous.registered_pages,observer=observe)
        result=original(reportpath,rendered_registry=cache)
        runtime=install_runtime(policy,a.out.resolve()/'metrics',approved_base_url=os.environ['TOKENHUB_BASE_URL'])
        handles.append(runtime['uninstall'])
        result['transport_runtime']={k:v for k,v in runtime.items()if k!='uninstall'}
        result['registry_cache']='VerifiedCanvasRegistryCache; dependency-signature invalidation'
        result['transport_runtime']['implementation_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()for name in ('scripts/hermes_mmbc_transport_worker_v2.py','scripts/visual_transport_runtime_v2.py','scripts/verified_canvas_registry_cache.py')}
        (a.out.resolve()/'transport-runtime.json').write_text(json.dumps(result['transport_runtime'],indent=2))
        return result
    retention.install=composed
    try:parent.main()
    finally:
        for f in reversed(handles):f()
        retention.install=original

if __name__=='__main__':main()
