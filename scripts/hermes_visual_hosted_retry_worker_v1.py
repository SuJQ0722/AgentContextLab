"""Explicit hosted retry across MMBC, BC and frozen RQ3 scales."""
import argparse,json,os
from pathlib import Path
from lab import ROOT
from hermes_mmbc_hosted_worker_v3 import HostedRetentionVisionRecorder
from verified_hosted_images_v3 import install as hosted,VerifiedImageHost
from visual_transport_runtime_v2 import install as runtime
from verified_canvas_registry_cache import VerifiedCanvasRegistryCache

def main():
    from compression_inline_only import removed
    removed()
if __name__=='__main__':main()
