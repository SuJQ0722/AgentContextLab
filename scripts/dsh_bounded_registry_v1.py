#!/usr/bin/env python3
"""No-network pixel/source verification shared with the bounded Hermes worker."""
import json
from pathlib import Path
import sys
from hermes_bounded_rq3_worker_v1 import registered_pages

if __name__ == '__main__':
    print(json.dumps(sorted(registered_pages(Path(sys.argv[1]), .75))))
