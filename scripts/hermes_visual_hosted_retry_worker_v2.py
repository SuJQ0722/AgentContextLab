"""Explicit resilient hosted retry across MMBC, BC and frozen RQ3 scales."""
import argparse,json,os
from pathlib import Path
from lab import ROOT
from hermes_mmbc_hosted_worker_v3 import HostedRetentionVisionRecorder as PreviousRecorder
from verified_hosted_images_v4 import install as hosted
from isolated_verified_image_host_v1 import IsolatedVerifiedImageHost as VerifiedImageHost
from visual_transport_runtime_v2 import install as runtime
from verified_canvas_registry_cache import VerifiedCanvasRegistryCache

class HostedRetentionVisionRecorder(PreviousRecorder):
 def write(self,name,record):
  if name=='vision-wire.jsonl':
   name='vision-pre-retention.jsonl'
   record={**record,'event':'pre_retention_http_payload','wire_stage':'before_last_10_selection_and_verified_hosting',
           'not_final_wire':True,'actual_wire_ledger':'hosted-images-wire-v4.jsonl'}
  return super().write(name,record)

def main():
    from compression_inline_only import removed
    removed()
if __name__=='__main__':main()
