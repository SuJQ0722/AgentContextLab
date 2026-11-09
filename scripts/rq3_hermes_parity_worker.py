#!/usr/bin/env python3
"""Same repaired native Hermes loop and wire image guard; only frozen history_scale varies."""
import json
import os
from pathlib import Path
import sys
from lab import ROOT
import hermes_bc_worker_v3 as native
from route_attribution_routes1 import RouteAttributionMixin
from run_rq3_parity_v3 import VERSION, MODEL, SCALES, sha


class RQ3VisionRecorder(RouteAttributionMixin,native.VisionRecorder):pass


def main():
    spec_path=Path(sys.argv[sys.argv.index('--spec')+1]);spec=json.loads(spec_path.read_text())
    cfg_path=Path(spec['config_path']);cfg=json.loads(cfg_path.read_text());scale=spec['scale']
    if scale not in SCALES or cfg['visual_renderer']['history_scale']!=scale or spec['model']!=MODEL or cfg['model']!=MODEL:
        raise ValueError('RQ3 scale/model differs from its frozen specification')
    out=Path(sys.argv[sys.argv.index('--out')+1]);out.mkdir(parents=True,exist_ok=True)
    record={'runtime_route_version':VERSION,'logical_model':MODEL,'actual_route':MODEL,
        'route_plan_sha256':spec.get('plan_sha256'),'parent_plan_sha256':spec.get('plan_sha256'),
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
