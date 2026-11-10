#!/usr/bin/env python3
"""Explicit opt-in hosted image runtime; identical retained bytes, no inline fallback."""
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
from verified_hosted_images_v3 import install as install_hosted, VerifiedImageHost, VERSION as HOSTED_VERSION


class HostedRetentionVisionRecorder(parent.VisionRecorder):
    def write(self,name,record):
        if name=='vision-wire.jsonl':
            name='vision-pre-retention.jsonl'
            record={**record,'event':'pre_retention_http_payload','wire_stage':'before_last_10_selection_and_verified_hosting',
                    'not_final_wire':True,'actual_wire_ledger':'hosted-images-wire-v3.jsonl'}
        return super().write(name,record)

def update_protocol(out):
    path=Path(out)/'bounded-protocol.json'
    if not path.exists():raise ValueError('Parent runtime protocol missing after configure')
    row=json.loads(path.read_text())
    row.update(image_transport=HOSTED_VERSION,actual_wire_ledger='hosted-images-wire-v3.jsonl',
               sdk_and_request_archive_stage='pre_retention inline images; actual hosted URL wire is defined by hosted-images-wire-v3.jsonl',
               provider_url_fetch_verified=False)
    path.write_text(json.dumps(row,indent=2))


def main():
    p=argparse.ArgumentParser(add_help=False);p.add_argument('--spec',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a,_=p.parse_known_args();spec=json.loads(a.spec.read_text());cfg=json.loads(Path(spec['config_path']).read_text())
    if spec.get('transport_runtime_version')!=VERSION or cfg.get('transport_runtime_version')!=VERSION:
        raise ValueError('Explicit new transport runtime spec and config required')
    if spec.get('image_transport')!=HOSTED_VERSION or cfg.get('image_transport')!=HOSTED_VERSION:
        raise ValueError('Hosted delivery must be explicitly selected in spec and config')
    policy=cfg['transport_runtime_policy'];original=retention.install;handles=[]
    def composed(reportpath,*,rendered_registry):
        cachelog=a.out.resolve()/'metrics/registry-cache-v2.jsonl'
        def observe(row):
            cachelog.parent.mkdir(parents=True,exist_ok=True)
            with cachelog.open('a')as f:f.write(json.dumps(row)+'\n')
        cache=VerifiedCanvasRegistryCache(a.out.resolve()/'context_images',parent.previous.registered_pages,observer=observe)
        runtime=install_runtime(policy,a.out.resolve()/'metrics',approved_base_url=os.environ['TOKENHUB_BASE_URL'])
        handles.append(runtime['uninstall'])
        hosted=install_hosted(a.out.resolve()/'metrics',rendered_registry=cache,host=VerifiedImageHost(a.out.resolve()/'hosted-image-cache',os.environ),approved_base_url=os.environ['TOKENHUB_BASE_URL'])
        handles.append(hosted['uninstall'])
        result={k:v for k,v in hosted.items()if k!='uninstall'}
        result['transport_runtime']={k:v for k,v in runtime.items()if k!='uninstall'}
        result['registry_cache']='VerifiedCanvasRegistryCache; dependency-signature invalidation'
        result['transport_runtime']['implementation_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()for name in ('scripts/hermes_mmbc_hosted_worker_v3.py','scripts/verified_hosted_images_v3.py','scripts/visual_transport_runtime_v2.py','scripts/verified_canvas_registry_cache.py')}
        (a.out.resolve()/'transport-runtime.json').write_text(json.dumps(result['transport_runtime'],indent=2))
        return result
    import hermes_bc_worker_v3 as native
    old_main=native.main;old_recorder=parent.RetentionVisionRecorder
    def run_native():
        configured=native.configure_engine
        def configure(*args,**kwargs):
            result=configured(*args,**kwargs)
            update_protocol(a.out.resolve())
            return result
        native.configure_engine=configure
        try:return old_main()
        finally:native.configure_engine=configured
    retention.install=composed;parent.RetentionVisionRecorder=HostedRetentionVisionRecorder;native.main=run_native
    try:parent.main()
    finally:
        for f in reversed(handles):f()
        retention.install=original;parent.RetentionVisionRecorder=old_recorder;native.main=old_main

if __name__=='__main__':main()
