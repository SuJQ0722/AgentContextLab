#!/usr/bin/env python3
"""Same repaired native Hermes loop and wire image guard; only frozen history_scale varies."""
import json
import os
from pathlib import Path
import sys
from lab import ROOT
import hermes_bc_worker_v3 as native
from run_rq3_parity_v3 import MODEL, sha
from prepare_rq3_scale0750_v1 import VERSION,validate_authorized_spec,MANIFEST
from rq3_hermes_parity_worker import RQ3VisionRecorder


def main():
    spec_path=Path(sys.argv[sys.argv.index('--spec')+1]);spec=json.loads(spec_path.read_text())
    cfg_path=Path(spec['config_path']);cfg=json.loads(cfg_path.read_text());scale=spec['scale']
    if scale!=.75 or cfg['visual_renderer']['history_scale']!=scale or spec['model']!=MODEL or cfg['model']!=MODEL:
        raise ValueError('RQ3 scale/model differs from its frozen specification')
    offline='--offline-fixture' in sys.argv
    if offline:
        from urllib.parse import urlparse
        if spec.get('offline_fixture') is not True or urlparse(os.environ.get('TOKENHUB_BASE_URL','')).hostname not in ('localhost','127.0.0.1','::1'):raise ValueError('Only explicit localhost fixtures may omit production scope')
        scope=None
    else:scope=validate_authorized_spec(spec)
    out=Path(sys.argv[sys.argv.index('--out')+1]);out.mkdir(parents=True,exist_ok=True)
    record={'runtime_route_version':VERSION,'logical_model':MODEL,'actual_route':MODEL,
        'route_plan_sha256':spec.get('plan_sha256'),'parent_plan_sha256':scope['parent_plan_sha256'] if scope else None,
        'scope_version':VERSION,'scope_manifest_sha256':sha(Path(spec['campaign_root'])/MANIFEST) if scope else None,'offline_fixture':offline,
        'config_sha256':sha(cfg_path),'far_history_scale':scale,
        'zero_semantics':'0x removes far-history canvases; recent canvases and head/tail evidence remain',
        'native_entry':'hermes_bc_worker_v3.py','guard':'Unmodified inherited VisionRecorder; no caption inference, final HTTP pixel/detail verification',
        'exposure':'A run without compression is not evidence of a scale intervention'}
    lineage=out/'rq3-lineage.json'
    if lineage.exists() and json.loads(lineage.read_text())!=record:raise ValueError('RQ3 native lineage changed')
    lineage.write_text(json.dumps(record,indent=2))
    old=os.environ.get('ACL_ROUTE_LINEAGE_FILE');original=native.VisionRecorder
    os.environ['ACL_ROUTE_LINEAGE_FILE']=str(lineage);native.VisionRecorder=RQ3VisionRecorder
    try:native.main()
    finally:
        native.VisionRecorder=original
        if old is None:os.environ.pop('ACL_ROUTE_LINEAGE_FILE',None)
        else:os.environ['ACL_ROUTE_LINEAGE_FILE']=old


if __name__=='__main__':main()
