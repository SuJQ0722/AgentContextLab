#!/usr/bin/env python3
"""Routes1 native Hermes entry: unchanged native guards plus attribution sidecar."""
import json
from pathlib import Path
import sys
import hermes_bc_worker_v3 as native
from route_attribution_routes1 import RouteAttributionMixin,load_route_lineage

class RoutedVisionRecorder(RouteAttributionMixin,native.VisionRecorder):pass
class RoutedTextRecorder(RouteAttributionMixin,native.ReviewedTextRecorder):pass


def main():
    spec_path=Path(sys.argv[sys.argv.index('--spec')+1]);spec=json.loads(spec_path.read_text())
    load_route_lineage(spec['model'],spec['config_path'],spec_path)
    native.VisionRecorder=RoutedVisionRecorder;native.ReviewedTextRecorder=RoutedTextRecorder
    native.main()


if __name__=='__main__':main()
