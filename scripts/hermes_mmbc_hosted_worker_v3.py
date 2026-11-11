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
    from compression_inline_only import removed
    removed()

if __name__=='__main__':main()
