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
    from compression_inline_only import removed
    removed()

if __name__=='__main__':main()
