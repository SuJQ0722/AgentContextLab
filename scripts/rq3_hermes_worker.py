#!/usr/bin/env python3
"""Run the unchanged native Hermes worker with bounded-memory PDF rasterization."""
from lab import ROOT
import sys
import json
import hashlib
from pathlib import Path
sys.path.insert(0,str(ROOT/'hermes-agent'))
from rq3_pdf_renderer import install
metadata=install()
if '--out' in sys.argv:
    output=Path(sys.argv[sys.argv.index('--out')+1]);output.mkdir(parents=True,exist_ok=True)
    metadata['implementation_sha256']=hashlib.sha256((ROOT/'scripts/rq3_pdf_renderer.py').read_bytes()).hexdigest()
    (output/'rq3-render-adapter.json').write_text(json.dumps(metadata,indent=2))
from hermes_bc_worker import main

if __name__=='__main__':main()
